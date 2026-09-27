"""Explicit chapter handoff and structural wakeups on the shared Watch slot."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from sqlalchemy import select

from core.config import get_settings
from core.errors import ConflictError, DomainError, ValidationError
from modules.account.facade import current_account_id
from modules.assistant.editorial_contracts import EditorialPolicy, ReviewSubmit
from modules.assistant.editorial_models import EditorialIssue, EditorialReview
from modules.assistant.forecast.context import authorize
from modules.assistant.models import AssistantRun
from modules.assistant.proactive import _notice, _watch
from modules.project.facade import read_editorial_brief
from modules.writing.facade import get_latest_draft_for_chapter


def enabled(row):
    settings = get_settings()
    return bool(
        row
        and (row.policy_json or {}).get("editorial_v1", {}).get("enabled")
        and settings.assistant_enabled
        and settings.assistant_editorial_enabled
        and settings.assistant_editorial_automatic_enabled
    )


def pending(row):
    return dict((row.dirty_json or {}).get("_editorial_v1", {}).get("pending", {}))


async def policy(db, novel_id):
    await authorize(db, novel_id)
    row = await _watch(db, novel_id)
    saved = ((row.policy_json or {}).get("editorial_v1") or {}) if row else {}
    settings = EditorialPolicy(
        enabled=saved.get("enabled", False),
        excluded_chapters=saved.get("excluded_chapters", []),
    )
    return {
        "feature_available": bool(
            get_settings().assistant_enabled
            and get_settings().assistant_editorial_enabled
        ),
        "automatic_available": bool(get_settings().assistant_editorial_automatic_enabled),
        "enabled": settings.enabled,
        "generation": row.generation if row else 0,
        "excluded_chapters": settings.excluded_chapters,
        "pending_count": sum(not item.get("blocked") for item in pending(row).values())
        if row
        else 0,
    }


async def save_policy(db, novel_id, value: EditorialPolicy, *, expected_generation):
    await authorize(db, novel_id)
    if value.enabled and not (
        get_settings().assistant_enabled
        and get_settings().assistant_editorial_enabled
        and get_settings().assistant_editorial_automatic_enabled
    ):
        raise ValidationError("后台编辑尚未开放")
    row = await _watch(db, novel_id, create=True, lock=True)
    if row.generation != expected_generation:
        raise ConflictError("主动编辑设置已在其他位置更新，请核对后再保存")
    row.generation += 1
    row.policy_json = {
        **(row.policy_json or {}),
        "owner_id": str(current_account_id()),
        "version": row.generation,
        "editorial_v1": {
            **value.model_dump(mode="json"),
            "owner_id": str(current_account_id()),
            "generation": row.generation,
            "authorized_at": datetime.now(UTC).isoformat(),
        },
    }
    if not value.enabled:
        row.dirty_json = {
            key: item
            for key, item in (row.dirty_json or {}).items()
            if key != "_editorial_v1"
        }
    from modules.assistant.forecast.queue import refresh_due

    refresh_due(row)
    await db.flush()
    return await policy(db, novel_id)


def _record(row, key, target):
    targets = pending(row)
    if key not in targets and len(targets) >= 200:
        return
    targets[key] = target
    row.dirty_json = {
        **(row.dirty_json or {}),
        "_editorial_v1": {"pending": targets},
    }
    from modules.assistant.forecast.queue import refresh_due

    refresh_due(row)


async def mark_ready(db, novel_id, chapter_index, draft_id, content_hash):
    if not get_settings().assistant_editorial_automatic_enabled:
        return
    row = await _watch(db, novel_id, lock=True)
    if not enabled(row):
        return
    grant = row.policy_json["editorial_v1"]
    if chapter_index in grant["excluded_chapters"]:
        return
    key = f"ready:{chapter_index}:{content_hash}"
    if (row.last_checked_json or {}).get(f"editorial:{key}"):
        return
    _record(
        row,
        key,
        {
            "kind": "ready",
            "chapter_index": chapter_index,
            "draft_id": draft_id,
            "content_hash": content_hash,
            "due_at": (datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
        },
    )
    await db.flush()


async def mark_structure_change(db, row, asset_type, asset_id):
    if not enabled(row) or asset_type not in {
        "outline_scene",
        "story_outline",
        "outline_arc",
        "plot_thread",
        "foreshadowing_plan",
    }:
        return
    issues = (
        await db.scalars(
            select(EditorialIssue)
            .where(
                EditorialIssue.novel_id == row.novel_id,
                EditorialIssue.disposition != "closed",
            )
            .order_by(EditorialIssue.updated_at.desc())
            .limit(50)
        )
    ).all()
    excluded = set(row.policy_json["editorial_v1"]["excluded_chapters"])
    now = datetime.now(UTC)
    for issue in issues:
        chapter = issue.finding_json["evidence"][0]["chapter_index"]
        if chapter in excluded:
            continue
        _record(
            row,
            f"structure:{issue.id}",
            {
                "kind": "structure",
                "chapter_index": chapter,
                "issue_id": str(issue.id),
                "asset_type": asset_type,
                "asset_id": asset_id,
                "changed_at": now.isoformat(),
                "due_at": (now + timedelta(seconds=60)).isoformat(),
            },
        )
    await db.flush()


def due_targets(row, now):
    if not enabled(row):
        return []
    return [
        (key, item)
        for key, item in pending(row).items()
        if not item.get("blocked") and datetime.fromisoformat(item["due_at"]) <= now
    ]


async def claim(db, row, key, change):
    from modules.assistant.editorial import submit

    targets = pending(row)
    novel_id = str(row.novel_id)
    try:
        async with db.begin_nested():
            grant = row.policy_json["editorial_v1"]
            if (
                not enabled(row)
                or str(row.policy_json.get("owner_id")) != grant["owner_id"]
            ):
                raise ConflictError("后台编辑授权已变化")
            chapter = change["chapter_index"]
            if chapter in grant["excluded_chapters"]:
                raise ConflictError("章节已被排除")
            if change["kind"] == "structure":
                issue = await db.scalar(
                    select(EditorialIssue).where(
                        EditorialIssue.novel_id == row.novel_id,
                        EditorialIssue.id == UUID(change["issue_id"]),
                    )
                )
                if issue is None or issue.disposition == "closed":
                    raise ConflictError("原问题已关闭")
            draft = await get_latest_draft_for_chapter(db, novel_id, chapter)
            if draft is None:
                raise ConflictError("章节已不存在")
            if change["kind"] == "ready" and (
                draft.id != change["draft_id"]
                or draft.content_hash != change["content_hash"]
                or draft.editorial_ready_hash != draft.content_hash
            ):
                raise ConflictError("章节完成标记已失效")
            brief = await read_editorial_brief(db, novel_id)
            identity = f"{key}:{draft.content_hash}:{brief['version']}"
            if change["kind"] == "structure":
                identity += f":{change['changed_at']}"
            operation_id = uuid5(row.novel_id, identity)
            review = await submit(
                db,
                ReviewSubmit(
                    novel_id=row.novel_id,
                    operation_id=operation_id,
                    scope="chapter",
                    start_chapter=chapter,
                    expected_brief_version=brief["version"],
                ),
                background=True,
                grant_version=grant["generation"],
            )
            review_id = UUID(review["id"])
            marker = AssistantRun(
                id=review_id,
                novel_id=row.novel_id,
                owner_id=UUID(grant["owner_id"]),
                operation_id=operation_id,
                mode="background",
                status="pending",
                request_hash=hashlib.sha256(identity.encode()).hexdigest(),
                request_json={"protocol": "editorial_v1", "change_key": key},
                budget_json={},
                checkpoint_json={},
                result_json={},
                task_id=UUID(review["task_id"]),
            )
            db.add(marker)
            await db.flush()
    except ConflictError:
        targets.pop(key, None)
        submitted = False
    except (DomainError, ValueError):
        targets[key] = {**change, "blocked": True}
        submitted = False
    else:
        targets.pop(key, None)
        row.active_run_id = review_id
        row.last_checked_json = {
            **(row.last_checked_json or {}),
            f"editorial:{key}": {
                "at": datetime.now(UTC).isoformat(),
                "content_hash": draft.content_hash,
            },
        }
        submitted = True
    row.dirty_json = {**(row.dirty_json or {}), "_editorial_v1": {"pending": targets}}
    from modules.assistant.forecast.queue import refresh_due

    refresh_due(row)
    await db.flush()
    return submitted


async def guard(db, review: EditorialReview):
    row = await _watch(db, str(review.novel_id), lock=True)
    grant = (row.policy_json or {}).get("editorial_v1") if row else None
    if not (
        enabled(row)
        and grant
        and row.active_run_id == review.id
        and grant["generation"] == review.scope_json.get("grant_version")
        and grant["owner_id"] == str(review.owner_id)
    ):
        raise ConflictError("后台编辑授权已撤销", code="POLICY_CHANGED")


async def finish(db, review: EditorialReview):
    if not review.scope_json.get("background"):
        return
    row = await _watch(db, str(review.novel_id), lock=True)
    marker = await db.scalar(
        select(AssistantRun)
        .where(
            AssistantRun.novel_id == review.novel_id,
            AssistantRun.id == review.id,
        )
        .with_for_update()
    )
    if (
        marker
        and marker.status in {"completed", "budget_exceeded", "cancelled", "failed"}
        and (not row or row.active_run_id != review.id)
    ):
        return
    grant = (row.policy_json or {}).get("editorial_v1") if row else None
    if review.status in {"completed", "partial"} and not (
        enabled(row)
        and grant
        and row.active_run_id == review.id
        and grant["generation"] == review.scope_json.get("grant_version")
        and grant["owner_id"] == str(review.owner_id)
    ):
        review.status = "stale"
        review.error = "后台编辑授权已变化，旧结论仅供回看"
    if marker:
        marker.status = {
            "completed": "completed",
            "partial": "budget_exceeded",
            "cancelled": "cancelled",
        }.get(review.status, "failed")
    if row and row.active_run_id == review.id:
        row.active_run_id = None
    if review.status == "completed" and row and enabled(row):
        top = {
            finding["fingerprint"]
            for finding in review.report_json.get("top_findings", [])[:3]
        }
        for issue in (
            await db.scalars(
                select(EditorialIssue).where(
                    EditorialIssue.novel_id == review.novel_id,
                    EditorialIssue.review_id == review.id,
                    EditorialIssue.disposition == "open",
                )
            )
        ).all():
            finding = issue.finding_json
            if (
                issue.fingerprint not in top
                or finding["severity"] != "high"
                or finding["unchecked"]
            ):
                continue
            await _notice(
                db,
                review.novel_id,
                key=[
                    "editorial",
                    issue.fingerprint,
                    finding["evidence"][0]["content_hash"],
                ],
                title="这章有一处值得尽快核对",
                summary=finding["judgment"],
                sources=finding["evidence"],
                result_ref={"type": "editorial_issue", "id": str(issue.id)},
            )
    await db.flush()
