"""Changes, standing authorization, bounded domain reviews and quiet notifications."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from core.config import get_settings
from core.container import get
from core.errors import ConflictError, DomainError, NotFoundError, ValidationError
from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.workflow_budget import workflow_budget
from infrastructure.tasks.facade import list_task_lifecycle_contracts
from modules.account.facade import current_account_id
from modules.assistant.evidence_tools import fingerprint
from modules.assistant.models import AssistantNotice, AssistantRun, AssistantWatch
from modules.assistant.schemas import NoticeDecision, ProactivePolicy
from modules.project.facade import (
    get_any_project_context,
    require_active_project,
    require_interaction_project,
)
from shared.constants import TASK_MAX_HEARTBEAT_GAP

_DOMAINS = {
    "writing_draft": "writing",
    "world_entity": "world",
    "core_entity": "world",
    "world_bible_page": "world",
    "world_bible_draft": "world",
    "world_bible_page_draft": "world",
    "scene": "story",
    "outline_scene": "story",
    "scene_story_assets": "story",
    "plot_thread": "story",
    "outline_arc": "story",
    "story_outline": "story",
    "foreshadowing_plan": "story",
    "reveal_plan": "story",
    "import_workflow": "imports",
    "interaction_journey": "interaction",
}
_ACTIVE = {"pending", "running"}


def _now():
    return datetime.now(UTC)


def _aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _authorized_change(setting, change):
    return (
        isinstance(change, dict)
        and change.get("domain") in setting.categories
        and change.get("asset_id")
        not in {value.rsplit(":", 1)[-1] for value in setting.excluded_targets}
    )


async def _watch(db, novel_id, *, create=False, lock=False):
    query = select(AssistantWatch).where(
        AssistantWatch.novel_id == uuid.UUID(str(novel_id))
    )
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query.execution_options(populate_existing=True))
    if row is None and create:
        try:
            async with db.begin_nested():
                row = AssistantWatch(novel_id=uuid.UUID(str(novel_id)))
                db.add(row)
                await db.flush()
        except IntegrityError:
            row = await db.scalar(query)
    return row


async def policy(db, novel_id, *, interaction=False):
    await (require_interaction_project if interaction else require_active_project)(
        db, str(novel_id)
    )
    row = await _watch(db, novel_id)
    default = (
        ProactivePolicy(categories=["interaction"]) if interaction else ProactivePolicy()
    )
    settings = (
        ProactivePolicy.model_validate(
            (row.policy_json or {}).get("settings") or default.model_dump()
        )
        if row
        else default
    )
    dirty = dict(row.dirty_json or {}) if row else {}
    return {
        "available": get_settings().interaction_agent_enabled
        if interaction
        else get_settings().assistant_enabled,
        "policy": settings.model_dump(mode="json"),
        "pending_count": sum(not key.startswith("_") for key in dirty),
        "overflow": bool(dirty.get("_overflow")),
        "active_run_id": str(row.active_run_id) if row and row.active_run_id else None,
    }


async def save_policy(db, novel_id, value: ProactivePolicy, *, interaction=False):
    await (require_interaction_project if interaction else require_active_project)(
        db, str(novel_id)
    )
    allowed = {"interaction"} if interaction else {"writing", "world", "story", "imports"}
    available = (
        get_settings().interaction_agent_enabled
        if interaction
        else get_settings().assistant_enabled
    )
    if value.enabled and not available:
        raise ValidationError("主动服务尚未启用")
    if not set(value.categories).issubset(allowed):
        raise ValidationError("检查类型与当前作品入口不匹配")
    row = await _watch(db, novel_id, create=True, lock=True)
    row.generation += 1
    row.policy_json = {
        "settings": value.model_dump(mode="json"),
        "owner_id": str(current_account_id()),
        "version": row.generation,
        "authorized_at": _now().isoformat(),
    }
    if value.enabled and row.dirty_json:
        row.dirty_json = {
            key: {name: item for name, item in change.items() if name != "blocked"}
            if not key.startswith("_")
            else change
            for key, change in row.dirty_json.items()
            if key.startswith("_") or _authorized_change(value, change)
        }
        row.due_at = _now() + timedelta(seconds=60)
    if not value.enabled:
        row.due_at = None
    await db.flush()
    return await policy(db, novel_id, interaction=interaction)


async def mark_changed(db, novel_id, asset_type, asset_id, *, related_scene_ids=None):
    if not (
        get_settings().interaction_agent_enabled
        if asset_type == "interaction_journey"
        else get_settings().assistant_enabled
    ):
        return
    asset_type = {
        "scene": "outline_scene",
        "scene_story_assets": "outline_scene",
        "world_entity": "core_entity",
        "world_bible_page_draft": "world_bible_draft",
    }.get(asset_type, asset_type)
    domain = _DOMAINS.get(asset_type)
    if domain is None:
        return
    row = await _watch(db, novel_id, lock=True)
    if row is None:
        return
    setting = ProactivePolicy.model_validate(
        (row.policy_json or {}).get("settings") or {}
    )
    if not setting.enabled or domain not in setting.categories:
        return
    asset_id = str(asset_id)
    uuid.UUID(asset_id)
    key = f"{asset_type}:{asset_id}"
    if asset_id in {value.rsplit(":", 1)[-1] for value in setting.excluded_targets}:
        return
    now = _now()
    dirty = dict(row.dirty_json or {})
    # ponytail: cap pending metadata at 500 targets. Overflow requires an
    # explicit full review; use a normalized backlog if real usage warrants it.
    if key not in dirty and len(dirty) >= 500:
        dirty["_overflow"] = True
    else:
        last = (row.last_checked_json or {}).get(key) or {}
        due = now + timedelta(seconds=60)
        if last.get("at"):
            due = max(
                due, _aware(datetime.fromisoformat(last["at"])) + timedelta(minutes=10)
            )
        dirty[key] = {
            "domain": domain,
            "asset_type": asset_type,
            "asset_id": asset_id,
            "changed_at": now.isoformat(),
            "due_at": due.isoformat(),
        }
        related = sorted(
            {
                str(uuid.UUID(str(value)))
                for value in [
                    *((row.dirty_json or {}).get(key, {}).get("related_scene_ids") or []),
                    *(related_scene_ids or []),
                ]
            }
        )
        if related:
            dirty[key]["related_scene_ids"] = related[:500]
            dirty[key]["related_overflow"] = len(related) > 500 or bool(
                (row.dirty_json or {}).get(key, {}).get("related_overflow")
            )
    row.dirty_json = dirty
    dates = [
        _aware(datetime.fromisoformat(item["due_at"]))
        for key, item in dirty.items()
        if not key.startswith("_") and not item.get("blocked")
    ]
    row.due_at = min(dates) if dates else None
    await db.flush()


async def _notice(
    db, novel_id, *, key, title, summary, kind="suggestion", sources=None, result_ref=None
):
    nid = uuid.UUID(str(novel_id))
    identity = fingerprint(key)
    row = await db.scalar(
        select(AssistantNotice).where(
            AssistantNotice.novel_id == nid, AssistantNotice.fingerprint == identity
        )
    )
    if row is None:
        row = AssistantNotice(
            novel_id=nid,
            fingerprint=identity,
            title=title[:200],
            summary=summary[:4000],
            kind=kind,
            sources_json=sources or [],
            result_ref_json=result_ref or {},
        )
        db.add(row)
        await db.flush()
    else:
        row.sources_json = sources or []
        receipts = (row.result_ref_json or {}).get("recheck_operation_ids")
        row.result_ref_json = {
            **(result_ref or {}),
            **({"recheck_operation_ids": receipts} if receipts else {}),
        }
        row.title, row.summary = title[:200], summary[:4000]
    return row


async def schedule_due(db):
    from modules.assistant.service import expire_run_histories

    await expire_run_histories(db)
    if not (get_settings().assistant_enabled or get_settings().interaction_agent_enabled):
        return 0
    now = _now()
    rows = (
        await db.scalars(
            select(AssistantWatch)
            .where(AssistantWatch.due_at <= now)
            .order_by(AssistantWatch.due_at)
            .limit(10)
            .with_for_update(skip_locked=True)
        )
    ).all()
    count = 0
    submitters = get("assistant.proactive.submitters")
    for row in rows:
        setting = ProactivePolicy.model_validate(
            (row.policy_json or {}).get("settings") or {}
        )
        row.dirty_json = {
            key: change
            for key, change in (row.dirty_json or {}).items()
            if key.startswith("_") or _authorized_change(setting, change)
        }
        project = await get_any_project_context(db, str(row.novel_id))
        if (
            not setting.enabled
            or project is None
            or str(project.owner_id) != (row.policy_json or {}).get("owner_id")
        ):
            row.due_at = None
            continue
        if not (
            get_settings().interaction_agent_enabled
            if project.project_kind == "interaction"
            else get_settings().assistant_enabled
        ):
            continue
        from modules.imports.facade import get_active_organization

        if await get_active_organization(db, str(row.novel_id)):
            # Derived assets may still be changing during an authorized import.
            # Keep their markers until that workflow has a stable terminal state.
            continue
        if row.active_run_id:
            previous = await db.scalar(
                select(AssistantRun).where(
                    AssistantRun.novel_id == row.novel_id,
                    AssistantRun.id == row.active_run_id,
                )
            )
            if previous and previous.task_id:
                life = (
                    await list_task_lifecycle_contracts(
                        db,
                        task_ids=[str(previous.task_id)],
                        novel_id=str(row.novel_id),
                        max_heartbeat_gap=TASK_MAX_HEARTBEAT_GAP,
                    )
                ).get(str(previous.task_id))
                if life and life.status in _ACTIVE:
                    continue
                if previous.status in _ACTIVE:
                    previous.status = "failed"
                    previous.error = "检查未完成，可从来源位置继续。"
                    dirty = dict(row.dirty_json or {})
                    key = previous.request_json.get("change_key")
                    if key in dirty:
                        dirty[key] = {**dirty[key], "blocked": True}
                    row.dirty_json = dirty
                    await _notice(
                        db,
                        row.novel_id,
                        key=["incomplete", key, previous.request_hash],
                        title="一次后台检查未完成",
                        summary="已保留来源与执行记录；你可以继续编辑，或从来源位置主动检查。",
                        kind="reminder",
                        result_ref=previous.result_json.get("source", {}),
                    )
            row.active_run_id = None
        zone = ZoneInfo(setting.timezone)
        day = datetime.combine(now.astimezone(zone).date(), time.min, tzinfo=zone)
        start, end = day.astimezone(UTC), (day + timedelta(days=1)).astimezone(UTC)
        used = await db.scalar(
            select(func.count())
            .select_from(AssistantRun)
            .where(
                AssistantRun.novel_id == row.novel_id,
                AssistantRun.mode == "background",
                AssistantRun.created_at >= start,
                AssistantRun.created_at < end,
            )
        )
        if used >= setting.daily_limit:
            row.due_at = end
            continue
        dirty = dict(row.dirty_json or {})
        eligible = [
            (key, item)
            for key, item in dirty.items()
            if not key.startswith("_")
            and not item.get("blocked")
            and _aware(datetime.fromisoformat(item["due_at"])) <= now
        ]
        if not eligible:
            dates = [
                _aware(datetime.fromisoformat(item["due_at"]))
                for key, item in dirty.items()
                if not key.startswith("_") and not item.get("blocked")
            ]
            row.due_at = min(dates) if dates else None
            continue
        key, change = min(eligible, key=lambda pair: pair[1]["due_at"])
        submit = submitters.get(change["domain"])
        if submit is None:
            row.dirty_json = {k: v for k, v in dirty.items() if k != key}
            continue
        run = AssistantRun(
            novel_id=row.novel_id,
            owner_id=uuid.UUID(project.owner_id),
            mode="background",
            request_hash=fingerprint(change),
            request_json={
                "change_key": key,
                "change": change,
                "policy_version": row.policy_json["version"],
            },
            budget_json=AgentRunBudget(mode="background").model_dump(mode="json"),
        )
        grant = {
            "run_id": str(uuid.uuid4()),
            "owner_id": project.owner_id,
            "version": row.policy_json["version"],
            "excluded_targets": setting.excluded_targets,
            "allow_web": setting.allow_web,
            "web_backend": setting.web_backend,
        }
        run.id = uuid.UUID(grant["run_id"])
        try:
            async with db.begin_nested():
                submission = await submit(
                    db,
                    str(row.novel_id),
                    change,
                    {"_assistant_policy": grant, "_task_priority": "background"},
                )
                if submission:
                    run.task_id = uuid.UUID(submission["task_id"])
                    run.result_json = {"source": submission}
                    db.add(run)
                    await db.flush()
        except (DomainError, ValueError) as error:
            dirty[key] = {**change, "blocked": True}
            row.dirty_json = dirty
            await _notice(
                db,
                row.novel_id,
                key=[
                    "preparation",
                    key,
                    getattr(error, "code", None) or type(error).__name__,
                ],
                title="这处变化暂时无法自动检查",
                summary="请到来源位置核对资料或模型连接；其他内容仍可继续编辑。",
                kind="reminder",
                result_ref={
                    "type": change["asset_type"],
                    "id": change["asset_id"],
                    "change_key": key,
                    "change_at": change["changed_at"],
                },
            )
            continue
        if not submission:
            row.dirty_json = {k: v for k, v in dirty.items() if k != key}
            continue
        row.active_run_id = run.id
        count += 1
    await db.flush()
    return count


async def _run_guard(db, task, grant):
    row = await _watch(db, str(task.novel_id), lock=True)
    if (
        row is None
        or not (row.policy_json or {}).get("settings", {}).get("enabled")
        or row.policy_json.get("version") != grant.get("version")
        or row.policy_json.get("owner_id") != grant.get("owner_id")
    ):
        raise ValidationError("主动检查授权已变化或关闭")
    project = await get_any_project_context(db, str(task.novel_id))
    if project is None or str(project.owner_id) != grant.get("owner_id"):
        raise NotFoundError("检查项目已不可访问")
    if not (
        get_settings().interaction_agent_enabled
        if project.project_kind == "interaction"
        else get_settings().assistant_enabled
    ):
        raise ValidationError("该项目的主动服务已暂停")
    run = await db.scalar(
        select(AssistantRun)
        .where(
            AssistantRun.id == uuid.UUID(grant["run_id"]),
            AssistantRun.novel_id == task.novel_id,
        )
        .with_for_update()
    )
    if (
        run is None
        or run.task_id != task.id
        or str(run.owner_id) != grant.get("owner_id")
        or row.active_run_id != run.id
    ):
        raise ConflictError("检查任务归属已变化")
    setting = ProactivePolicy.model_validate(row.policy_json["settings"])
    if not _authorized_change(setting, run.request_json.get("change")):
        raise ValidationError("此处变化已不在主动检查授权内")
    return row, run


async def execute_review_task(db, task, handler):
    grant = (task.meta or {}).get("_assistant_policy")
    if not grant:
        return await handler(db=db, task=task)
    row, run = await _run_guard(db, task, grant)
    saved = (task.result or {}).get("_assistant_budget") or run.budget_json
    budget = AgentRunBudget.model_validate(saved or {"mode": "background"})
    if run.status == "pending" and not (task.result or {}).get("_assistant_budget"):
        budget.started_at = _now()
    run.status = "running"
    await db.commit()

    async def checkpoint(values):
        if db.new or db.dirty or db.deleted:
            raise RuntimeError("Review provider checkpoint requires clean domain state")
        _, owned = await _run_guard(db, task, grant)
        owned.budget_json = values
        task.result = {**(task.result or {}), "_assistant_budget": values}
        await db.commit()

    try:
        with workflow_budget(budget, checkpoint):
            async with asyncio.timeout(budget.remaining_seconds):
                result = await handler(db=db, task=task)
        row, run = await _run_guard(db, task, grant)
        reader = get("assistant.proactive.findings").get(task.task_type)
        findings = (
            await reader(db, str(task.novel_id), result)
            if reader
            else list(result.get("findings") or [])
        )
        current_change = (row.dirty_json or {}).get(run.request_json["change_key"])
        # A newer source never receives the older run's notification, even if a
        # domain returns a useful historical receipt instead of raising stale.
        fresh = current_change == run.request_json["change"] and result.get(
            "status"
        ) not in {"stale", "failed", "cancelled", "superseded"}
        for finding in findings[:3] if fresh else []:
            if not isinstance(finding, dict):
                continue
            location = finding.get("location") or finding.get("source") or {}
            if not isinstance(location, dict):
                raise ValidationError("领域检查未提供可定位的结果引用")
            target = run.result_json.get("source", {}).get("target") or {}
            change_identity = run.request_json["change_key"]
            if task.task_type == "writing_semantic_review" and (
                location.get("chapter_index") or target.get("chapter_index")
            ):
                chapter = location.get("chapter_index") or target["chapter_index"]
                change_identity = f"writing_chapter:{chapter}"
            stable = {
                key: value
                for key, value in location.items()
                if key
                not in {
                    "source_hash",
                    "draft_hash",
                    "run_id",
                    "task_id",
                    "version_number",
                    "start_hint",
                    "end_hint",
                    "start_offset",
                    "end_offset",
                    "draft_id",
                }
            }
            evidence = (
                finding.get("evidence")
                or location.get("excerpt")
                or finding.get("excerpt")
                or finding.get("message")
                or ""
            )
            title = str(
                finding.get("summary")
                or finding.get("title")
                or finding.get("message")
                or "有一处值得核对"
            )
            await _notice(
                db,
                task.novel_id,
                key=[
                    task.task_type,
                    change_identity,
                    finding.get("code") or finding.get("kind") or finding.get("category"),
                    stable,
                    str(evidence),
                    *(
                        [finding["world_evidence"]]
                        if finding.get("world_evidence")
                        else []
                    ),
                ],
                title=title,
                kind="reminder" if finding.get("kind") == "reminder" else "suggestion",
                summary=str(
                    finding.get("rationale")
                    or finding.get("description")
                    or finding.get("message")
                    or title
                ),
                sources=([location] if location else [])
                + finding.get("world_evidence", []),
                result_ref={
                    "type": task.task_type,
                    "task_id": str(task.id),
                    "finding_id": finding.get("id") or finding.get("finding_id"),
                    "location": location,
                    "target": run.result_json.get("source", {}).get("target"),
                    "change_key": run.request_json["change_key"],
                    "change_at": run.request_json["change"]["changed_at"],
                },
            )
        dirty = dict(row.dirty_json or {})
        key = run.request_json["change_key"]
        if dirty.get(key) == run.request_json["change"]:
            dirty.pop(key, None)
        row.dirty_json = dirty
        row.last_checked_json = {
            **(row.last_checked_json or {}),
            key: {
                "at": _now().isoformat(),
                "task_id": str(task.id),
                "change_at": run.request_json["change"]["changed_at"],
            },
        }
        row.active_run_id = None
        run.status = "completed"
        run.budget_json = budget.model_dump(mode="json")
        run.result_json = {
            **run.result_json,
            "review_task_id": str(task.id),
            "finding_count": len(findings),
            "superseded": not fresh,
        }
        # Domain result, notices and the queue's completed receipt share the
        # worker's final fenced commit. A crash cannot expose an unlinked notice.
        await db.flush()
        return result
    except asyncio.CancelledError:
        raise
    except Exception:
        await db.rollback()
        raise


async def list_notices(db, novel_id, *, interaction=False):
    await (require_interaction_project if interaction else require_active_project)(
        db, str(novel_id)
    )
    rows = (
        await db.scalars(
            select(AssistantNotice)
            .where(
                AssistantNotice.novel_id == uuid.UUID(str(novel_id)),
                AssistantNotice.status != "dismissed",
            )
            .order_by(AssistantNotice.created_at.desc())
            .limit(50)
        )
    ).all()
    now = _now()
    watch = await _watch(db, novel_id)
    dirty = (watch.dirty_json or {}) if watch else {}
    stale_reviews = {}
    for row in rows:
        reference = row.result_ref_json or {}
        task_id = reference.get("task_id")
        if (
            reference.get("type") == "interaction_continuity_review"
            and task_id not in stale_reviews
        ):
            from modules.interaction.facade import read_continuity_review

            result = await read_continuity_review(db, str(novel_id), task_id)
            stale_reviews[task_id] = result["status"] != "completed"
        capability = {
            "writing_semantic_review": "writing.review",
            "world_validation": "world.review",
        }.get(reference.get("type"))
        if capability and task_id not in stale_reviews:
            operation = get("assistant.operations")[capability]
            result = await operation.read_result(db, str(novel_id), reference)
            stale_reviews[task_id] = result.get("status") != "completed"
    return {
        "items": [
            {
                "id": str(row.id),
                "title": row.title,
                "summary": row.summary,
                "kind": row.kind,
                "status": "unread"
                if row.status == "snoozed" and row.wake_at and _aware(row.wake_at) <= now
                else row.status,
                "sources": row.sources_json,
                "source": row.result_ref_json,
                "can_recheck": bool(
                    row.result_ref_json.get("task_id")
                    or row.result_ref_json.get("change_key")
                ),
                "needs_recheck": bool(
                    stale_reviews.get(row.result_ref_json.get("task_id"))
                    or (change := dirty.get(row.result_ref_json.get("change_key")))
                    and change.get("changed_at") != row.result_ref_json.get("change_at")
                    or (
                        (
                            checked := (
                                (watch.last_checked_json or {}) if watch else {}
                            ).get(row.result_ref_json.get("change_key"))
                        )
                        and checked.get("change_at")
                        != row.result_ref_json.get("change_at")
                    )
                ),
            }
            for row in rows
            if row.status != "snoozed" or (row.wake_at and _aware(row.wake_at) <= now)
        ]
    }


async def decide_notice(db, notice_id, value: NoticeDecision, *, interaction=False):
    await (require_interaction_project if interaction else require_active_project)(
        db, str(value.novel_id)
    )
    row = await db.scalar(
        select(AssistantNotice)
        .where(
            AssistantNotice.id == uuid.UUID(str(notice_id)),
            AssistantNotice.novel_id == value.novel_id,
        )
        .with_for_update()
    )
    if row is None:
        raise NotFoundError("提醒不存在")
    if value.action == "snooze":
        if value.until is None or _aware(value.until) <= _now():
            raise ValidationError("请选择之后的提醒时间")
        row.status, row.wake_at = "snoozed", _aware(value.until)
    else:
        row.status = "read" if value.action == "read" else "dismissed"
        row.disposition = value.action
    await db.flush()
    return {"status": row.status}


async def recheck_notice(db, novel_id, notice_id, operation_id, *, interaction=False):
    await (require_interaction_project if interaction else require_active_project)(
        db, str(novel_id)
    )
    watch = await _watch(db, novel_id, lock=True)
    if watch is None:
        raise ValidationError("请先开启主动服务")
    setting = ProactivePolicy.model_validate(watch.policy_json.get("settings") or {})
    if not setting.enabled:
        raise ValidationError("主动服务已关闭，请先重新选择检查范围")
    if watch.policy_json.get("owner_id") != str(current_account_id()):
        raise ValidationError("项目授权归属已变化，请重新保存主动服务设置")
    notice = await db.scalar(
        select(AssistantNotice)
        .where(
            AssistantNotice.novel_id == uuid.UUID(str(novel_id)),
            AssistantNotice.id == uuid.UUID(str(notice_id)),
        )
        .with_for_update()
    )
    if notice is None:
        raise NotFoundError("提醒不存在")
    ref = notice.result_ref_json or {}
    prior = (
        await db.scalar(
            select(AssistantRun).where(
                AssistantRun.novel_id == uuid.UUID(str(novel_id)),
                AssistantRun.task_id == uuid.UUID(ref["task_id"]),
                AssistantRun.owner_id == current_account_id(),
            )
        )
        if ref.get("task_id")
        else None
    )
    change = (
        prior.request_json.get("change")
        if prior
        else (watch.dirty_json or {}).get(ref.get("change_key"))
    )
    if not change or not _authorized_change(setting, change):
        raise ValidationError("原检查来源已不在当前授权范围内")
    receipts = list(ref.get("recheck_operation_ids") or [])
    if str(operation_id) in receipts:
        return {"status": "queued", "replayed": True}
    notice.result_ref_json = {
        **ref,
        "recheck_operation_ids": [*receipts, str(operation_id)],
    }
    if prior is not None and watch.active_run_id == prior.id:
        life = (
            await list_task_lifecycle_contracts(
                db,
                task_ids=[str(prior.task_id)],
                novel_id=str(novel_id),
                max_heartbeat_gap=TASK_MAX_HEARTBEAT_GAP,
            )
        ).get(str(prior.task_id))
        if life and life.status in _ACTIVE:
            return {"status": "running", "replayed": True}
        watch.active_run_id = None
        if prior.status in _ACTIVE:
            prior.status = "failed"
            prior.error = "原检查已停止，新检查将使用新的运行额度。"
    key = prior.request_json["change_key"] if prior else ref["change_key"]
    pending = (watch.dirty_json or {}).get(key)
    if pending and not pending.get("blocked"):
        return {"status": "queued", "replayed": True}
    await mark_changed(
        db,
        novel_id,
        change["asset_type"],
        change["asset_id"],
        related_scene_ids=change.get("related_scene_ids"),
    )
    pending = (watch.dirty_json or {}).get(key)
    if pending is None:
        raise ValidationError("检查待办已满，请先处理现有检查")
    now = _now()
    watch.dirty_json = {**watch.dirty_json, key: {**pending, "due_at": now.isoformat()}}
    watch.due_at = now
    await db.flush()
    return {
        "status": "queued",
        "replayed": False,
        "message": "已排入新一轮检查，仍受项目每日额度限制",
    }
