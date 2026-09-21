"""Read-only feeds, immutable assessments and versioned presentation decisions."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select

from core.config import get_settings
from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.collaboration import content_hash
from modules.assistant.forecast.context import authorize, materialize
from modules.assistant.forecast.contracts import (
    ActionView,
    CandidateView,
    CoverageCounts,
    CoverageReport,
    DecisionReceipt,
    FeedResponse,
)
from modules.assistant.forecast.models import ForecastCandidate, ForecastDependency
from modules.assistant.forecast.ranking import (
    assessment_hash,
    hidden_by_decision,
    notice_key,
    rank_key,
)
from modules.assistant.models import AssistantNotice, AssistantRun


def coverage(counts, *, semantic="not_run", omissions=None):
    return CoverageReport(
        scope_label="当前授权的保存资料；未检查全书",
        enumerated_total=sum(counts.values()),
        enumeration_complete=True,
        semantic_search=semantic,
        counts=CoverageCounts(**counts),
        omissions=omissions or [],
    )


def aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def public_actions(candidate, *, dirty=False):
    return [
        ActionView(
            action_id="forecast.inspect_evidence",
            label="查看依据",
            kind="inspect",
            requires_confirmation=False,
            available=True,
        ),
        *[
            ActionView.model_validate(
                {**action, "available": False, "unavailable_reason": "请先保存当前输入"}
                if dirty and action["kind"] == "prepare_domain"
                else action
            )
            for action in candidate.payload_json.get("actions", [])
        ],
    ]


def candidate_view(candidate, notice, *, dirty=False):
    payload = candidate.payload_json
    proposal = payload["proposal"]
    return CandidateView(
        candidate_id=candidate.id,
        issue_key=candidate.issue_key,
        notice_version=notice.row_version if notice else 0,
        notice_status=notice.status if notice else "unread",
        disposition=notice.disposition if notice else None,
        run_id=candidate.run_id,
        capability_id=candidate.capability_id,
        assessment_hash=candidate.assessment_hash,
        context_hash=candidate.context_hash,
        title=proposal["title"],
        kind=candidate.output_kind,
        tier=candidate.tier,
        verification_status="uncertain",
        freshness="valid",
        statements=proposal["statements"],
        why_now=proposal["why_now"],
        directions=proposal.get("directions", []),
        unknowns=[
            *proposal.get("unknowns", []),
            *(
                [notice.result_ref_json["forecast_v1"]["wake_explanation"]]
                if notice
                and notice.result_ref_json.get("forecast_v1", {}).get("wake_explanation")
                else []
            ),
        ],
        evidence=payload["evidence"],
        actions=public_actions(candidate, dirty=dirty),
        navigation=payload.get("navigation"),
        basis_label="基于上次保存；尚有未保存输入" if dirty else "基于当前保存版本",
        expires_at=aware(candidate.expires_at),
    )


async def _notice(db, candidate, *, lock=False):
    query = select(AssistantNotice).where(
        AssistantNotice.novel_id == candidate.novel_id,
        AssistantNotice.fingerprint
        == notice_key(
            str(candidate.novel_id), candidate.audience_key, candidate.issue_key
        ),
    )
    if lock:
        query = query.with_for_update()
    return await db.scalar(query.execution_options(populate_existing=True))


async def _valid(db, candidate, ctx, dependencies=None):
    if dependencies is None:
        dependencies = (
            await db.scalars(
                select(ForecastDependency).where(
                    ForecastDependency.novel_id == candidate.novel_id,
                    ForecastDependency.candidate_id == candidate.id,
                )
            )
        ).all()
    values = [
        {
            key: getattr(row, key)
            for key in (
                "dependency_key",
                "resource_kind",
                "resource_id",
                "revision_token",
                "role",
                "required",
                "scope_stamp",
            )
        }
        for row in dependencies
    ]
    values = [{**value, "resource_id": str(value["resource_id"])} for value in values]
    return (
        candidate.validation_state == "valid"
        and aware(candidate.expires_at) > datetime.now(UTC)
        and candidate.scope_hash == ctx.scope.scope_hash
        and candidate.context_hash == ctx.scope.context_hash
        and assessment_hash(candidate.payload_json, values) == candidate.assessment_hash
    )


async def feed(db, novel_id, data, *, persona="author"):
    ctx = await materialize(db, novel_id, data.context, persona=persona)
    # Rank latest before testing validity: an invalid latest assessment must not
    # resurrect an older pass. Fetch dependency/notice sets once, not per card.
    latest_ids = (
        select(
            ForecastCandidate.id,
            func.row_number()
            .over(
                partition_by=ForecastCandidate.issue_key,
                order_by=(
                    ForecastCandidate.created_at.desc(),
                    ForecastCandidate.id.desc(),
                ),
            )
            .label("position"),
        )
        .where(
            ForecastCandidate.novel_id == UUID(novel_id),
            ForecastCandidate.audience_key == ctx.scope.audience_key,
            ForecastCandidate.scope_hash == ctx.scope.scope_hash,
        )
        .subquery()
    )
    rows = (
        await db.scalars(
            select(ForecastCandidate)
            .join(latest_ids, ForecastCandidate.id == latest_ids.c.id)
            .where(latest_ids.c.position == 1)
        )
    ).all()
    deps = {}
    if rows:
        for dependency in (
            await db.scalars(
                select(ForecastDependency).where(
                    ForecastDependency.novel_id == UUID(novel_id),
                    ForecastDependency.candidate_id.in_([row.id for row in rows]),
                )
            )
        ).all():
            deps.setdefault(dependency.candidate_id, []).append(dependency)
    fingerprints = {
        row.id: notice_key(novel_id, row.audience_key, row.issue_key) for row in rows
    }
    notices = (
        {
            row.fingerprint: row
            for row in (
                await db.scalars(
                    select(AssistantNotice).where(
                        AssistantNotice.novel_id == UUID(novel_id),
                        AssistantNotice.fingerprint.in_(list(fingerprints.values())),
                    )
                )
            ).all()
        }
        if rows
        else {}
    )
    valid, counts = [], {key: 0 for key in CoverageCounts.model_fields}
    for row in rows:
        if not await _valid(db, row, ctx, deps.get(row.id, [])):
            counts["source_invalid"] += 1
            continue
        notice = notices.get(fingerprints[row.id])
        if hidden_by_decision(notice) and not data.include_deferred:
            counts[
                "waiting_condition" if notice.status == "snoozed" else "suppressed"
            ] += 1
            continue
        valid.append((row, notice))
    valid.sort(key=lambda pair: rank_key(pair[0]))
    offset = int(data.cursor) if data.cursor and data.cursor.isdecimal() else 0
    selected = valid[offset : offset + data.max_items]
    counts["presented"], counts["backlog"] = len(selected), len(valid) - len(selected)
    items = [
        candidate_view(row, notice, dirty=data.context.editor_state == "dirty")
        for row, notice in selected
    ]
    computation = await db.scalar(
        select(AssistantRun)
        .where(
            AssistantRun.novel_id == UUID(novel_id),
            AssistantRun.status == "completed",
            AssistantRun.request_json["protocol"].as_string() == "forecast_v1",
            AssistantRun.request_json["scope"]["context_hash"].as_string()
            == ctx.scope.context_hash,
        )
        .order_by(AssistantRun.created_at.desc())
        .limit(1)
    )
    report = (computation.result_json or {}).get("coverage", {}) if computation else {}
    counts["not_checked"] = (report.get("counts") or {}).get("not_checked", 0)
    enabled = (
        get_settings().assistant_enabled and get_settings().assistant_forecast_enabled
    )
    return FeedResponse(
        client_context_id=data.context.client_context_id,
        focus_seq=data.context.focus_seq,
        context_hash=ctx.scope.context_hash,
        items=items,
        coverage=coverage(
            counts,
            semantic=report.get("semantic_search", "not_run"),
            omissions=report.get("omissions", []),
        ),
        state="ready"
        if items
        else "stale"
        if counts["source_invalid"]
        else "empty"
        if computation
        else "not_checked"
        if enabled
        else "disabled",
        next_cursor=str(offset + len(selected))
        if offset + len(selected) < len(valid)
        else None,
        generated_at=datetime.now(UTC),
        references=ctx.evidence,
    )


async def require_candidate(db, novel_id, candidate_id, *, focus=None, persona="author"):
    await authorize(db, novel_id, persona=persona)
    candidate = await db.scalar(
        select(ForecastCandidate).where(
            ForecastCandidate.novel_id == UUID(novel_id),
            ForecastCandidate.id == UUID(str(candidate_id)),
        )
    )
    if candidate is None:
        raise NotFoundError("前瞻结果不可访问")
    run = await db.scalar(
        select(AssistantRun).where(
            AssistantRun.novel_id == candidate.novel_id,
            AssistantRun.id == candidate.run_id,
        )
    )
    if run is None or run.request_json.get("protocol") != "forecast_v1":
        raise NotFoundError("前瞻结果不可访问")
    from modules.assistant.forecast.contracts import FocusRequest

    ctx = await materialize(
        db,
        novel_id,
        focus or FocusRequest.model_validate(run.request_json["context"]),
        persona=persona,
    )
    if not await _valid(db, candidate, ctx):
        raise ConflictError("资料或授权已变化，请重新检查", code="SOURCE_STALE")
    latest = await db.scalar(
        select(ForecastCandidate.id)
        .where(
            ForecastCandidate.novel_id == candidate.novel_id,
            ForecastCandidate.audience_key == candidate.audience_key,
            ForecastCandidate.scope_hash == candidate.scope_hash,
            ForecastCandidate.issue_key == candidate.issue_key,
        )
        .order_by(ForecastCandidate.created_at.desc(), ForecastCandidate.id.desc())
        .limit(1)
    )
    if latest != candidate.id:
        raise ConflictError("已有更新的判断，请查看最新结果", code="ASSESSMENT_CHANGED")
    return candidate, ctx


async def decide(db, novel_id, candidate_id, data, *, persona="author"):
    candidate, ctx = await require_candidate(db, novel_id, candidate_id, persona=persona)
    notice = await _notice(db, candidate, lock=True)
    if (
        notice is None
        or notice.row_version != data.expected_notice_version
        or candidate.assessment_hash != data.expected_assessment_hash
    ):
        raise ConflictError(
            "此事项已在其他位置处理，请读取最新状态", code="DECISION_CONFLICT"
        )
    if data.direction_id and data.direction_id not in {
        item["direction_id"]
        for item in candidate.payload_json["proposal"].get("directions", [])
    }:
        raise ConflictError("此方向不属于当前判断", code="DECISION_CONFLICT")
    wake = data.wake_condition.model_dump(mode="json") if data.wake_condition else None
    if wake and wake["kind"] == "at_time" and data.wake_condition.at <= datetime.now(UTC):
        raise ConflictError("请选择未来的提醒时间", code="INVALID_WAKE_CONDITION")
    if wake and wake["kind"] == "object_reappears":
        # The marker identifies a real source in the host receipt.
        refs = candidate.payload_json["evidence"]
        if not any(
            str(ref["resource_id"]) == str(data.wake_condition.object_id)
            and ref["revision_token"] == data.wake_condition.after_event_token
            for ref in refs
        ):
            raise ConflictError(
                "无法计算该对象的再次出现条件，请选择手动重开",
                code="WAKE_SCOPE_UNAVAILABLE",
            )
    from modules.assistant.forecast.wake import freeze_condition

    wake = await freeze_condition(db, novel_id, wake) if persona == "author" else wake
    notice.status = {
        "read": "read",
        "keep_observing": "read",
        "as_ordinary_detail": "dismissed",
        "not_this_direction": "dismissed",
        "snooze": "snoozed",
        "reopen": "unread",
    }[data.action]
    notice.wake_at = (
        data.wake_condition.at if wake and wake["kind"] == "at_time" else None
    )
    notice.disposition = data.action
    notice.row_version += 1
    previous = (notice.result_ref_json or {}).get("forecast_v1", {})
    notice.result_ref_json = {
        **notice.result_ref_json,
        "forecast_v1": {
            **previous,
            "disposition": data.action,
            "direction_id": data.direction_id,
            "wake_condition": wake,
            "decided_at": datetime.now(UTC).isoformat(),
            "decision_boundary": decision_boundary(ctx),
            "declined_choice": {
                "question": candidate.payload_json["proposal"]["title"],
                "directions": [
                    {"title": item["title"], "proposal": item["proposal"]}
                    for item in candidate.payload_json["proposal"].get("directions", [])
                    if not data.direction_id or item["direction_id"] == data.direction_id
                ],
            }
            if data.action in {"not_this_direction", "as_ordinary_detail"}
            else None,
        },
    }
    await db.flush()
    return DecisionReceipt(
        candidate_id=candidate.id,
        notice_version=notice.row_version,
        notice_status=notice.status,
        disposition=data.action,
    )


def decision_boundary(ctx):
    return content_hash(
        [
            ctx.scope.scope_hash,
            str(ctx.focus.scene_id),
            str(ctx.focus.context_confirmation_id),
            ctx.focus.context_confirmation_action,
            ctx.focus.selected_range.model_dump() if ctx.focus.selected_range else None,
        ]
    )


async def explicit_decisions(db, ctx):
    """Recent explicit choices are preferences, never newly established facts."""
    if ctx.scope.persona != "author":
        return []
    rows = (
        await db.scalars(
            select(AssistantNotice)
            .where(
                AssistantNotice.novel_id == ctx.scope.novel_id,
                AssistantNotice.result_ref_json["forecast_v1"][
                    "decision_boundary"
                ].as_string()
                == decision_boundary(ctx),
                AssistantNotice.disposition.in_(
                    ["not_this_direction", "as_ordinary_detail"]
                ),
            )
            .order_by(AssistantNotice.updated_at.desc(), AssistantNotice.id.desc())
            .limit(10)
        )
    ).all()
    return [
        {
            "disposition": row.disposition,
            "choice": row.result_ref_json["forecast_v1"].get("declined_choice"),
        }
        for row in rows
    ]


async def inherit_issue_identity(db, run, item, cache):
    """Carry a physical source issue across saved revisions; never use its title."""
    from difflib import SequenceMatcher

    from modules.writing.facade import get_draft

    anchor = item["payload"].get("anchor", {})
    if anchor.get("resource_kind") != "writing_draft":
        return item["issue_key"]
    previous = (
        await db.scalars(
            select(ForecastCandidate)
            .where(
                ForecastCandidate.novel_id == run.novel_id,
                ForecastCandidate.capability_id == item["capability_id"],
                ForecastCandidate.audience_key
                == run.request_json["scope"]["audience_key"],
                ForecastCandidate.payload_json["anchor"]["chapter_index"].as_integer()
                == anchor["chapter_index"],
            )
            .order_by(ForecastCandidate.created_at.desc())
            .limit(60)
        )
    ).all()
    for candidate in previous:
        old = candidate.payload_json.get("anchor", {})
        if old.get("resource_kind") != "writing_draft" or old.get(
            "question_kind"
        ) != anchor.get("question_kind"):
            continue
        pair = (old["resource_id"], anchor["resource_id"])
        for identity in pair:
            if ("draft", identity) not in cache:
                cache[("draft", identity)] = await get_draft(
                    db, str(run.novel_id), identity
                )
        before, after = (cache[("draft", identity)] for identity in pair)
        if not before or not after:
            continue
        if pair not in cache:
            # ponytail: bounded alignment; use persisted block IDs for larger chapters.
            if max(len(before.content or ""), len(after.content or "")) > 32000:
                cache[pair] = []
                continue
            matcher = SequenceMatcher(None, before.content or "", after.content or "")
            cache[pair] = matcher.get_opcodes() if matcher.ratio() >= 0.5 else []
        old_quote = (before.content or "")[old["start"] : old["end"]]
        new_quote = (after.content or "")[anchor["start"] : anchor["end"]]
        if (
            not old_quote
            or not new_quote
            or SequenceMatcher(None, old_quote, new_quote).ratio() < 0.7
        ):
            continue
        mapped = [
            (c + max(0, old["start"] - a), c + min(b, old["end"]) - a)
            if tag == "equal"
            else (c, d)
            for tag, a, b, c, d in cache[pair]
            if a < old["end"] and b > old["start"] and c < d
        ]
        if mapped:
            start, end = (
                min(value[0] for value in mapped),
                max(value[1] for value in mapped),
            )
            overlap = max(0, min(end, anchor["end"]) - max(start, anchor["start"]))
            if overlap >= 0.5 * max(1, min(end - start, anchor["end"] - anchor["start"])):
                return candidate.issue_key
    return item["issue_key"]


async def publish(db, run, ctx, assessments):
    if len(ctx.dependencies) > 256:
        raise ValidationError("依赖过多，请缩小本次资料范围", code="DEPENDENCY_LIMIT")
    rows = []
    for ordinal, item in enumerate(assessments):
        payload = item["payload"]
        if len(json.dumps(payload, ensure_ascii=False).encode()) > 65536:
            raise ValidationError(
                "单项建议资料过大，请缩小本次范围", code="PAYLOAD_LIMIT"
            )
        candidate = ForecastCandidate(
            id=uuid4(),
            novel_id=run.novel_id,
            run_id=run.id,
            ordinal=ordinal,
            issue_key=item["issue_key"],
            audience_key=ctx.scope.audience_key,
            scope_hash=ctx.scope.scope_hash,
            context_hash=ctx.scope.context_hash,
            assessment_hash=assessment_hash(payload, ctx.dependencies),
            capability_id=item["capability_id"],
            output_kind=payload["proposal"]["kind"],
            tier=item["tier"],
            policy_generation=ctx.scope.policy_generation,
            payload_json=payload,
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        db.add(candidate)
        await db.flush()
        for dependency in ctx.dependencies:
            db.add(
                ForecastDependency(
                    novel_id=run.novel_id,
                    candidate_id=candidate.id,
                    **{**dependency, "resource_id": UUID(dependency["resource_id"])},
                )
            )
        notice = await _notice(db, candidate, lock=True)
        reference = {
            "candidate_id": str(candidate.id),
            "assessment_hash": candidate.assessment_hash,
            "issue_key": candidate.issue_key,
        }
        if notice is None:
            notice = AssistantNotice(
                novel_id=run.novel_id,
                fingerprint=notice_key(
                    str(run.novel_id), candidate.audience_key, candidate.issue_key
                ),
                kind="suggestion",
                title=payload["proposal"]["title"],
                summary=payload["proposal"]["why_now"],
                result_ref_json={"type": "forecast", "forecast_v1": reference},
            )
            db.add(notice)
        else:
            notice.result_ref_json = {
                **notice.result_ref_json,
                "forecast_v1": {
                    **notice.result_ref_json.get("forecast_v1", {}),
                    **reference,
                },
            }
            notice.title, notice.summary = (
                payload["proposal"]["title"],
                payload["proposal"]["why_now"],
            )
        rows.append(candidate)
    await db.flush()
    return rows


async def legacy_decide_notice(db, novel_id, notice, value):
    from modules.assistant.forecast.contracts import DecisionRequest, WakeAt

    saved = notice.result_ref_json["forecast_v1"]
    if saved.get("disposition") in {"as_ordinary_detail", "not_this_direction"}:
        return {"status": notice.status}
    action = {
        "read": "read",
        "snooze": "snooze",
        "ignore": "as_ordinary_detail",
        "intentional": "as_ordinary_detail",
    }[value.action]
    receipt = await decide(
        db,
        novel_id,
        saved["candidate_id"],
        DecisionRequest(
            expected_notice_version=notice.row_version,
            expected_assessment_hash=saved["assessment_hash"],
            action=action,
            wake_condition=WakeAt(kind="at_time", at=aware(value.until))
            if action == "snooze" and value.until
            else None,
        ),
    )
    return {"status": receipt.notice_status}
