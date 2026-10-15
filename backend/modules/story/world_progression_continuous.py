"""Persistent author authorization and ingest-triggered light progression."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from core.container import get as container_get
from core.errors import ConflictError
from core.service_keys import EVOLUTION_READ_COMPLETED_CHAPTERS
from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.schemas import read_ai_run_envelope
from infrastructure.llm.workflow_budget import AIRunEnvelope
from infrastructure.tasks.facade import (
    enqueue_coalesced_task,
    enqueue_task_with_optional_operation,
    get_operation_task,
)
from infrastructure.tasks.models import AsyncTask
from modules.evidence.facade import require_fresh_confirmation
from modules.story.generation import STORY_ONE_CLICK_ACTION
from modules.story.world_progression_context import read_progression_source
from modules.story.world_progression_models import (
    StoryWorldProgressionAuthorization,
    StoryWorldProgressionBranch,
    StoryWorldProgressionRoot,
    StoryWorldProgressionStep,
)
from modules.story.world_progression_schemas import (
    ProgressionContinuousAuthorizationRequest,
    ProgressionParticipant,
)
from modules.story.world_progression_tasks import (
    WORLD_PROGRESSION_TASK,
    _budget_stop,
    _task_meta,
)

SOURCE_ID = "story.world_progression"
_MIN_DEPARTED_STEPS = 2
_READ_COMMIT_CHECK_TASK = "story_world_progression_read_commit_check"


def _progression_enabled() -> bool:
    return os.getenv("STORY_WORLD_PROGRESSION_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def _completed_read_chapters(
    db, novel_id: str, *, exclude_chapter_indices: list[int] | None = None
) -> list[int]:
    reader = container_get(EVOLUTION_READ_COMPLETED_CHAPTERS)
    return await reader(db, novel_id, exclude_chapter_indices=exclude_chapter_indices)


async def invalidate_world_progression_authorization_for_reorder(
    db, *, novel_id: str
) -> bool:
    """Revoke index-based standing consent in the same chapter reorder transaction."""
    authorization = await db.scalar(
        select(StoryWorldProgressionAuthorization)
        .where(StoryWorldProgressionAuthorization.novel_id == UUID(novel_id))
        .with_for_update()
    )
    if authorization is None or not authorization.enabled:
        return False
    authorization.enabled = False
    authorization.revision += 1
    authorization.participant_ids_json = []
    authorization.root_id = None
    authorization.branch_id = None
    authorization.context_confirmation_id = None
    authorization.read_count_initialized = False
    await db.flush()
    return True


async def queue_progression_read_check(db, *, novel_id: str) -> str | None:
    """Place a free check in the successful read transaction.

    The standing grant is an opt-in gate. A rollback also removes this outbox row.
    The worker proves complete canonical reads after the transaction closes.
    """
    if not _progression_enabled():
        return None
    authorization = await db.scalar(
        select(StoryWorldProgressionAuthorization.id).where(
            StoryWorldProgressionAuthorization.novel_id == UUID(novel_id),
            StoryWorldProgressionAuthorization.enabled.is_(True),
        )
    )
    if authorization is None:
        return None
    receipt = await enqueue_coalesced_task(
        db,
        task_type=_READ_COMMIT_CHECK_TASK,
        scope=("completed-chapters",),
        mode="one_pending_follower",
        meta={"novel_id": novel_id},
        novel_id=novel_id,
    )
    return receipt.task_id


def _budget_view(root) -> dict:
    envelope = dict(root.run_envelope_json or {})
    usage = envelope.get("usage") or {}
    return {
        "requests_used": int(envelope.get("requests_started") or 0),
        "requests_authorized": envelope.get("request_limit"),
        "tokens_used": int(usage.get("total_tokens") or 0),
        "tokens_authorized": envelope.get("token_limit"),
        "unknown_requests": int(envelope.get("requests_unknown") or 0),
        "deadline_at": envelope.get("deadline_at"),
        "fee_status": "可能产生计费请求；未估算金额",
    }


async def set_continuous_authorization(
    db,
    *,
    root: StoryWorldProgressionRoot,
    branch: StoryWorldProgressionBranch,
    data: ProgressionContinuousAuthorizationRequest,
) -> dict:
    """Change persisted authorization without adding or resetting budget."""
    if str(root.novel_id) != data.novel_id or str(branch.root_id) != str(root.id):
        raise ValueError("持续授权作品或推进根不匹配")
    if branch.deleted_at is not None:
        raise ConflictError("已删除分支不能开启持续推进")
    if data.enabled and branch.status not in {"ready", "complete"}:
        raise ConflictError("持续推进只能绑定到已完成的一步历史")
    source_participants = {
        str(item["id"]): str(item.get("kind", "character"))
        for item in root.request_json.get("participants") or []
    }
    selected = set(data.participant_ids)
    if data.enabled and not selected <= set(source_participants):
        raise ConflictError("持续授权不能加入原运行未选择的参与者")
    if data.enabled:
        confirmation = await require_fresh_confirmation(
            db,
            novel_id=data.novel_id,
            action=STORY_ONE_CLICK_ACTION,
            confirmation_id=data.context_confirmation_id,
        )
        options = dict(confirmation.compile_options or {})
        if str(options.get("scene_id") or "") != str(root.scene_id):
            raise ConflictError("持续授权确认的 Scene 与世界推进根不一致")
        selected_chars = {
            actor for actor in selected if source_participants[actor] == "character"
        }
        selected_groups = {
            actor for actor in selected if source_participants[actor] == "group"
        }
        if not selected_chars <= set(map(str, options.get("character_ids") or [])):
            raise ConflictError("持续授权确认没有包含所选人物")
        if not selected_groups <= set(map(str, options.get("entity_ids") or [])):
            raise ConflictError("持续授权确认没有包含所选群体")
    current = await db.scalar(
        select(StoryWorldProgressionAuthorization)
        .where(StoryWorldProgressionAuthorization.novel_id == UUID(data.novel_id))
        .with_for_update()
    )
    if (
        data.enabled
        and current is not None
        and current.enabled
        and current.root_id is not None
        and current.root_id != root.id
    ):
        raise ConflictError("当前作品已有另一条持续推进授权；请先明确关闭它")
    revision = int(current.revision) if current is not None else 0
    if data.expected_revision is not None and data.expected_revision != revision:
        raise ConflictError("持续授权设置已被修改，请刷新")
    envelope = read_ai_run_envelope(root.run_envelope_json)
    if envelope is None or envelope.run_id != str(root.id):
        raise ConflictError("原运行预算不可恢复，不能授权持续推进")
    if data.enabled and _budget_stop(AIRunEnvelope(envelope)):
        raise ConflictError("原运行已暂停，持续授权不会追加或重置预算")
    if data.enabled and root.current_task_id is not None:
        active = await db.get(AsyncTask, root.current_task_id)
        if active is not None and active.status in {"pending", "running"}:
            raise ConflictError("原推进根仍在运行；完成或暂停后再授权持续提醒")

    completed_chapters = (
        await _completed_read_chapters(db, data.novel_id) if data.enabled else []
    )
    latest_chapter = max(completed_chapters, default=0)
    if current is None:
        current = StoryWorldProgressionAuthorization(
            novel_id=UUID(data.novel_id),
            enabled=False,
            revision=0,
            participant_ids_json=sorted(selected),
            every_new_chapters=data.every_new_chapters,
            last_seen_chapter=latest_chapter,
            trigger_count=0,
        )
        db.add(current)
    current.enabled = data.enabled
    current.revision = revision + 1
    current.participant_ids_json = sorted(selected) if data.enabled else []
    current.every_new_chapters = data.every_new_chapters
    current.last_seen_chapter = latest_chapter
    current.counted_read_chapters_json = completed_chapters if data.enabled else []
    current.last_triggered_read_count = len(completed_chapters) if data.enabled else 0
    current.read_count_initialized = bool(data.enabled)
    current.root_id = root.id if data.enabled else None
    current.branch_id = branch.id if data.enabled else None
    current.context_confirmation_id = (
        data.context_confirmation_id if data.enabled else None
    )
    current.updated_at = datetime.now(UTC)
    await db.flush()
    return {
        "enabled": current.enabled,
        "revision": current.revision,
        "participant_ids": list(current.participant_ids_json or []),
        "every_new_chapters": current.every_new_chapters,
        "trigger_count": current.trigger_count,
        "root_id": str(current.root_id) if current.root_id else None,
        "branch_id": str(current.branch_id) if current.branch_id else None,
        "budget": _budget_view(root),
        "last_seen_chapter": current.last_seen_chapter,
        "completed_read_chapter_count": len(current.counted_read_chapters_json),
        "new_read_chapters_since_trigger": 0,
    }


async def read_continuous_authorization(db, novel_id: str) -> dict:
    row = await db.scalar(
        select(StoryWorldProgressionAuthorization).where(
            StoryWorldProgressionAuthorization.novel_id == UUID(novel_id)
        )
    )
    if row is None:
        return {
            "enabled": False,
            "revision": 0,
            "participant_ids": [],
            "every_new_chapters": 3,
            "trigger_count": 0,
            "root_id": None,
            "branch_id": None,
            "budget": None,
            "completed_read_chapter_count": 0,
            "new_read_chapters_since_trigger": 0,
        }
    root = None
    if row.root_id:
        root = await db.scalar(
            select(StoryWorldProgressionRoot).where(
                StoryWorldProgressionRoot.novel_id == UUID(novel_id),
                StoryWorldProgressionRoot.id == row.root_id,
            )
        )
    return {
        "enabled": bool(row.enabled),
        "revision": row.revision,
        "participant_ids": list(row.participant_ids_json or []),
        "every_new_chapters": row.every_new_chapters,
        "trigger_count": row.trigger_count,
        "root_id": str(row.root_id) if row.root_id else None,
        "branch_id": str(row.branch_id) if row.branch_id else None,
        "last_seen_chapter": row.last_seen_chapter,
        "completed_read_chapter_count": len(row.counted_read_chapters_json or []),
        "new_read_chapters_since_trigger": max(
            0,
            len(row.counted_read_chapters_json or [])
            - int(row.last_triggered_read_count or 0),
        ),
        "budget": _budget_view(root) if root is not None else None,
    }


async def consider_progression_after_chapter_commit(
    db, *, novel_id: str, latest_effective_chapter: int
) -> dict:
    """Enqueue a light step only after N distinct whole chapters were read.

    The chapter argument is a receipt-derived display hint, never the counter.
    The Evolution read receipt and free outbox commit together before this runs.
    """
    del latest_effective_chapter
    if not _progression_enabled():
        return {"status": "disabled", "task_id": None}
    authorization = await db.scalar(
        select(StoryWorldProgressionAuthorization)
        .where(StoryWorldProgressionAuthorization.novel_id == UUID(novel_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if authorization is None or not authorization.enabled:
        return {"status": "disabled", "task_id": None}
    if not authorization.read_count_initialized:
        authorization.enabled = False
        authorization.revision += 1
        await db.flush()
        return {"status": "read_count_requires_reauthorization", "task_id": None}
    previous = set(authorization.counted_read_chapters_json or [])
    completed = set(
        await _completed_read_chapters(
            db, novel_id, exclude_chapter_indices=sorted(previous)
        )
    )
    new_chapters = completed - previous
    already_pending = len(previous) - int(authorization.last_triggered_read_count or 0)
    if not new_chapters and already_pending < int(authorization.every_new_chapters or 1):
        return {"status": "no_new_read_chapters", "task_id": None}
    counted = sorted(previous | new_chapters)
    authorization.counted_read_chapters_json = counted
    authorization.last_seen_chapter = max(counted, default=0)
    if len(counted) - int(authorization.last_triggered_read_count or 0) < int(
        authorization.every_new_chapters or 1
    ):
        await db.flush()
        return {"status": "waiting_for_chapters", "task_id": None}
    root = await db.scalar(
        select(StoryWorldProgressionRoot)
        .where(
            StoryWorldProgressionRoot.novel_id == UUID(novel_id),
            StoryWorldProgressionRoot.id == authorization.root_id,
        )
        .with_for_update()
    )
    branch = await db.scalar(
        select(StoryWorldProgressionBranch)
        .where(
            StoryWorldProgressionBranch.novel_id == UUID(novel_id),
            StoryWorldProgressionBranch.id == authorization.branch_id,
        )
        .with_for_update()
    )
    if root is None or branch is None or branch.deleted_at is not None:
        authorization.enabled = False
        authorization.revision += 1
        await db.flush()
        return {"status": "authorization_target_missing", "task_id": None}
    if root.current_task_id is not None:
        active = await db.get(AsyncTask, root.current_task_id)
        if active is not None and active.status in {"pending", "running"}:
            return {"status": "run_active", "task_id": str(root.current_task_id)}
        root.current_task_id = None
    raw_envelope = read_ai_run_envelope(root.run_envelope_json)
    if raw_envelope is None or raw_envelope.run_id != str(root.id):
        authorization.enabled = False
        authorization.revision += 1
        await db.flush()
        return {"status": "budget_unavailable", "task_id": None}
    envelope = AIRunEnvelope(raw_envelope)
    if _budget_stop(envelope):
        authorization.enabled = False
        authorization.revision += 1
        await db.flush()
        return {"status": "budget_stopped", "task_id": None}

    parent = await db.scalar(
        select(StoryWorldProgressionStep)
        .where(
            StoryWorldProgressionStep.novel_id == UUID(novel_id),
            StoryWorldProgressionStep.branch_id == branch.id,
        )
        .order_by(StoryWorldProgressionStep.step_number.desc())
        .limit(1)
    )
    if parent is None:
        return {"status": "no_progression_step", "task_id": None}
    goal_step = await _lineage_goal_step(db, root, parent)
    result = dict(goal_step.result_json or {})
    pending_targets = {
        str(item.get("target_id"))
        for item in result.get("goal_outcomes") or []
        if item.get("status") in {"in_progress", "blocked", "uncertain"}
    }
    paths = [
        item
        for item in result.get("target_paths") or []
        if str(item.get("target_id")) in pending_targets
    ]
    path_actor_ids = {
        str(actor) for path in paths for actor in path.get("actor_ids") or []
    }
    absent = await _long_absent_actor_ids(db, root, parent, path_actor_ids)
    long_away = path_actor_ids & absent
    authorized_ids = set(map(str, authorization.participant_ids_json or []))
    eligible = sorted(long_away & authorized_ids)
    if not eligible:
        authorization.last_triggered_read_count = len(counted)
        await db.flush()
        return {"status": "no_long_away_unfinished_actor", "task_id": None}

    all_participants = [
        ProgressionParticipant.model_validate(item)
        for item in (root.request_json or {}).get("participants") or []
    ]
    selected_participants = [item for item in all_participants if item.id in eligible]
    source = await read_progression_source(
        db,
        novel_id=novel_id,
        scene_id=None,
        participants=selected_participants,
        targets=[],
    )
    operation_id = str(
        uuid5(
            NAMESPACE_URL,
            f"world-progression:{root.id}:{authorization.revision}:{len(counted)}",
        )
    )
    branch_id = uuid5(NAMESPACE_URL, f"{operation_id}:branch")
    branch_request = {
        "participants": [item.model_dump(mode="json") for item in selected_participants],
        "targets": [],
        "mode": "free",
        "instructions": "",
        "retained_constraints": [],
        "step_length": "auto",
        "run_policy": "one_step",
        "steps": None,
        "stop_at_goal": False,
        "scene_id": source["scene_id"],
        "continuous_authorization": True,
    }
    request_payload = {
        "root_id": str(root.id),
        "branch_id": str(branch_id),
        **branch_request,
    }
    existing = await get_operation_task(
        db,
        operation_id=operation_id,
        task_type=WORLD_PROGRESSION_TASK,
        novel_id=novel_id,
        request_payload=request_payload,
    )
    if existing is not None:
        existing_task = await db.get(AsyncTask, UUID(str(existing.task_id)))
        existing_meta = dict(existing_task.meta or {}) if existing_task else {}
        existing_branch_id = str(existing_meta.get("world_progression_branch_id") or "")
        if str(existing_meta.get("world_progression_root_id") or "") != str(
            root.id
        ) or existing_branch_id != str(branch_id):
            raise ConflictError("持续推进的幂等任务与授权根不匹配")
        existing_branch = await db.scalar(
            select(StoryWorldProgressionBranch).where(
                StoryWorldProgressionBranch.novel_id == UUID(novel_id),
                StoryWorldProgressionBranch.id == UUID(existing_branch_id),
                StoryWorldProgressionBranch.root_id == root.id,
            )
        )
        if existing_branch is None:
            raise ConflictError("持续推进的既有分支不可恢复")
        root.current_task_id = UUID(str(existing.task_id))
        root.status = (
            "queued" if existing.status in {"pending", "running"} else root.status
        )
        authorization.branch_id = existing_branch.id
        authorization.last_triggered_read_count = len(counted)
        await db.flush()
        return {
            "status": existing.status,
            "task_id": str(existing.task_id),
            "branch_id": existing_branch_id,
            "selected_participant_ids": eligible,
            "reused": True,
        }
    child = StoryWorldProgressionBranch(
        id=branch_id,
        novel_id=UUID(novel_id),
        root_id=root.id,
        parent_step_id=parent.id,
        branch_kind="continuous_light_step",
        basis_choice="current",
        source_hash=source["source_hash"],
        request_json=branch_request,
        source_snapshot_json=source,
        status="queued",
    )
    db.add(child)
    snapshot = root.llm_execution_snapshot_json
    meta = _task_meta(
        request={"novel_id": novel_id, "continuous": True},
        root_id=root.id,
        branch_id=child.id,
        execution_snapshot=snapshot,
        envelope=envelope,
    )
    meta["continuous_authorization_revision"] = authorization.revision
    meta["continuous_authorized_participant_ids"] = sorted(authorized_ids)
    meta["continuous_trigger_chapter"] = max(completed, default=0)
    meta["continuous_trigger_read_count"] = len(counted)
    receipt = await enqueue_task_with_optional_operation(
        db,
        operation_id=operation_id,
        task_type=WORLD_PROGRESSION_TASK,
        novel_id=novel_id,
        request_payload=request_payload,
        meta=meta,
    )
    if receipt.reused:
        await db.delete(child)
        raise ConflictError("持续推进任务在根锁内发生重复提交，请重试")
    root.current_task_id = UUID(str(receipt.task_id))
    root.status = "queued"
    child.current_task_id = UUID(str(receipt.task_id))
    child.status = "queued"
    authorization.branch_id = child.id
    authorization.last_triggered_read_count = len(counted)
    authorization.trigger_count += 1
    await db.flush()
    return {
        "status": "queued",
        "task_id": str(receipt.task_id),
        "branch_id": str(child.id),
        "selected_participant_ids": eligible,
    }


async def _long_absent_actor_ids(db, root, latest, actor_ids: set[str]) -> set[str]:
    """Require two persisted consecutive simulated steps of typed departure."""
    if not actor_ids:
        return set()
    rows = (
        await db.scalars(
            select(StoryWorldProgressionStep)
            .where(
                StoryWorldProgressionStep.novel_id == root.novel_id,
                StoryWorldProgressionStep.root_id == root.id,
            )
            .order_by(StoryWorldProgressionStep.created_at.desc())
        )
    ).all()
    by_id = {str(item.id): item for item in rows}
    current = by_id.get(str(latest.id))
    counts = {actor_id: 0 for actor_id in actor_ids}
    found: set[str] = set()
    while current is not None and found != actor_ids:
        departed = {
            str(value).partition(":")[2]
            for value in (current.state_json or {}).get("departed") or []
            if str(value).startswith("object:")
        }
        for actor_id in counts:
            if actor_id in found:
                continue
            if actor_id in departed:
                counts[actor_id] += 1
                if counts[actor_id] >= _MIN_DEPARTED_STEPS:
                    found.add(actor_id)
            else:
                counts[actor_id] = 0
        current = (
            by_id.get(str(current.parent_step_id))
            if current.parent_step_id is not None
            else None
        )
    return found


async def _lineage_goal_step(db, root, latest):
    """Use this branch's author step, never an unrelated sibling's goals."""
    steps = (
        await db.scalars(
            select(StoryWorldProgressionStep).where(
                StoryWorldProgressionStep.novel_id == root.novel_id,
                StoryWorldProgressionStep.root_id == root.id,
            )
        )
    ).all()
    branches = (
        await db.scalars(
            select(StoryWorldProgressionBranch).where(
                StoryWorldProgressionBranch.novel_id == root.novel_id,
                StoryWorldProgressionBranch.root_id == root.id,
            )
        )
    ).all()
    by_step = {str(item.id): item for item in steps}
    by_branch = {str(item.id): item for item in branches}
    current = latest
    while current is not None:
        branch = by_branch.get(str(current.branch_id))
        if branch is None or branch.branch_kind != "continuous_light_step":
            return current
        current = by_step.get(str(current.parent_step_id))
    return latest


async def list_progression_notices(
    db, novel_id: str, scope: dict | None = None
) -> list[dict]:
    """Read reminder candidates without starting tasks or changing authorization."""
    authorization = await db.scalar(
        select(StoryWorldProgressionAuthorization).where(
            StoryWorldProgressionAuthorization.novel_id == UUID(novel_id)
        )
    )
    if (
        authorization is None
        or not authorization.enabled
        or authorization.root_id is None
    ):
        return []
    root = await db.scalar(
        select(StoryWorldProgressionRoot).where(
            StoryWorldProgressionRoot.novel_id == UUID(novel_id),
            StoryWorldProgressionRoot.id == authorization.root_id,
        )
    )
    if root is None:
        return []
    branch = (
        await db.scalar(
            select(StoryWorldProgressionBranch).where(
                StoryWorldProgressionBranch.novel_id == UUID(novel_id),
                StoryWorldProgressionBranch.id == authorization.branch_id,
                StoryWorldProgressionBranch.root_id == root.id,
            )
        )
        if authorization.branch_id
        else None
    )
    if branch is None or branch.branch_kind != "continuous_light_step":
        return []
    task = (
        await db.get(AsyncTask, root.current_task_id)
        if root.current_task_id is not None
        else None
    )
    task_active = task is not None and task.status in {"pending", "running"}
    task_meta = dict(task.meta or {}) if task is not None else {}
    task_matches = str(task_meta.get("world_progression_root_id") or "") == str(
        root.id
    ) and str(task_meta.get("world_progression_branch_id") or "") == str(branch.id)
    if task_active and not task_matches:
        return []
    step = None
    if not task_active:
        step = await db.scalar(
            select(StoryWorldProgressionStep)
            .where(
                StoryWorldProgressionStep.novel_id == UUID(novel_id),
                StoryWorldProgressionStep.branch_id == branch.id,
            )
            .order_by(StoryWorldProgressionStep.step_number.desc())
            .limit(1)
        )
    if step is None and not task_active:
        return []
    output = dict(step.result_json or {}) if step is not None else {}
    digest = content_hash(
        {
            "root_id": str(root.id),
            "revision": authorization.revision,
            "last_seen_chapter": authorization.last_seen_chapter,
            "participant_ids": sorted(authorization.participant_ids_json or []),
            "step_id": str(step.id) if step is not None else None,
            "step_output_hash": step.output_hash if step is not None else None,
            "task_status": task.status if task is not None else None,
        }
    )
    return [
        {
            "notice_key": f"{SOURCE_ID}:{root.id}:{authorization.revision}",
            "source_id": SOURCE_ID,
            "category": "world_progression",
            "severity": "info",
            "target": {
                "scene_id": str(root.scene_id),
                "root_id": str(root.id),
                "branch_id": str(branch.id),
                "step_id": str(step.id) if step is not None else None,
            },
            "summary": (
                "持续推进正在原预算内生成一步自由候选。"
                if task_active
                else "持续推进候选："
                + str(output.get("narrative_summary") or "已生成一条候选步骤。")
                + " 尚未写入正史。"
            ),
            "evidence": [
                {
                    "field": "authorization_revision",
                    "value": authorization.revision,
                    "last_seen_chapter": authorization.last_seen_chapter,
                    "interval": authorization.every_new_chapters,
                    "step_id": str(step.id) if step is not None else None,
                    "step_output_hash": step.output_hash if step is not None else None,
                }
            ],
            "basis_fingerprint": digest,
            "stale": False,
            "actions": [
                {
                    "kind": "navigate",
                    "page": "outline",
                    "tab": "world-progression",
                    "label": "查看持续推进授权",
                }
            ],
            "disposition_ref": None,
        }
    ]


NOTICE_SOURCE_SPEC = {
    "source_id": SOURCE_ID,
    "label": "持续世界推进",
    "list_notices": list_progression_notices,
}
