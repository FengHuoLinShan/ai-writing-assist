"""Story-owned persistence and read operations for candidate world progression."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from core.errors import ConflictError, NotFoundError
from infrastructure.llm.collaboration import content_hash
from modules.story.world_progression_models import (
    StoryWorldProgressionAuthorization,
    StoryWorldProgressionBranch,
    StoryWorldProgressionRoot,
    StoryWorldProgressionStep,
)


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


async def get_progression_root(db, novel_id: str, root_id: str, *, lock=False):
    query = select(StoryWorldProgressionRoot).where(
        StoryWorldProgressionRoot.novel_id == _uuid(novel_id),
        StoryWorldProgressionRoot.id == _uuid(root_id),
    )
    row = await db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise NotFoundError("世界推进运行不存在")
    return row


async def get_progression_branch(
    db, novel_id: str, branch_id: str, *, lock=False, include_deleted=False
):
    query = select(StoryWorldProgressionBranch).where(
        StoryWorldProgressionBranch.novel_id == _uuid(novel_id),
        StoryWorldProgressionBranch.id == _uuid(branch_id),
    )
    if not include_deleted:
        query = query.where(StoryWorldProgressionBranch.deleted_at.is_(None))
    row = await db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise NotFoundError("世界推进分支不存在")
    return row


async def get_progression_step(db, novel_id: str, step_id: str):
    row = await db.scalar(
        select(StoryWorldProgressionStep).where(
            StoryWorldProgressionStep.novel_id == _uuid(novel_id),
            StoryWorldProgressionStep.id == _uuid(step_id),
        )
    )
    if row is None:
        raise NotFoundError("世界推进步骤不存在")
    return row


async def list_root_metrics(
    db, novel_id: str, *, model_name: str | None = None
) -> list[dict]:
    rows = (
        await db.scalars(
            select(StoryWorldProgressionStep)
            .where(StoryWorldProgressionStep.novel_id == _uuid(novel_id))
            .order_by(StoryWorldProgressionStep.created_at, StoryWorldProgressionStep.id)
        )
    ).all()
    metrics = [dict(row.metrics_json or {}) for row in rows]
    if model_name is not None:
        metrics = [item for item in metrics if item.get("model_name") == model_name]
    return metrics


async def lineage_metrics(db, novel_id: str, *, parent_step_id: str | None) -> list[dict]:
    if parent_step_id is None:
        return []
    rows = (
        await db.scalars(
            select(StoryWorldProgressionStep).where(
                StoryWorldProgressionStep.novel_id == _uuid(novel_id)
            )
        )
    ).all()
    by_id = {str(item.id): item for item in rows}
    result = []
    current = str(parent_step_id)
    seen: set[str] = set()
    while current and current in by_id and current not in seen:
        seen.add(current)
        row = by_id[current]
        result.append({"step_id": str(row.id), **dict(row.metrics_json or {})})
        current = str(row.parent_step_id) if row.parent_step_id else ""
    result.reverse()
    return result


async def append_progression_step(
    db,
    *,
    novel_id: str,
    root: StoryWorldProgressionRoot,
    branch: StoryWorldProgressionBranch,
    parent_step_id: str | None,
    source_hash: str,
    input_payload: dict,
    output_payload: dict,
    state: dict,
    metrics: dict,
    basis_changed: bool,
) -> StoryWorldProgressionStep:
    if str(branch.root_id) != str(root.id):
        raise ConflictError("分支不属于当前推进根")
    if parent_step_id:
        parent = await get_progression_step(db, novel_id, parent_step_id)
        if str(parent.root_id) != str(root.id):
            raise ConflictError("续跑步骤不属于当前推进根")
    previous = await db.scalar(
        select(StoryWorldProgressionStep)
        .where(
            StoryWorldProgressionStep.novel_id == _uuid(novel_id),
            StoryWorldProgressionStep.branch_id == branch.id,
        )
        .order_by(StoryWorldProgressionStep.step_number.desc())
        .limit(1)
    )
    expected_parent = (
        str(previous.id)
        if previous is not None
        else (str(branch.parent_step_id) if branch.parent_step_id else None)
    )
    if expected_parent != (str(parent_step_id) if parent_step_id else None):
        raise ConflictError("推进分支的父步骤已变化，请从当前历史重新选择")
    number = int(previous.step_number) + 1 if previous is not None else 1
    input_json = dict(input_payload)
    output_json = dict(output_payload)
    input_hash = content_hash(
        {
            "source_hash": source_hash,
            "parent_step_id": parent_step_id,
            "parent_output_hash": input_json.get("parent_output_hash"),
            "input": input_json,
        }
    )
    output_hash = content_hash(
        {
            "input_hash": input_hash,
            "output": output_json,
            "state": state,
        }
    )
    row = StoryWorldProgressionStep(
        novel_id=_uuid(novel_id),
        root_id=root.id,
        branch_id=branch.id,
        parent_step_id=_uuid(parent_step_id) if parent_step_id else None,
        step_number=number,
        source_hash=source_hash,
        input_hash=input_hash,
        output_hash=output_hash,
        input_json=input_json,
        result_json=output_json,
        state_json=dict(state),
        metrics_json=dict(metrics),
        basis_changed=basis_changed,
    )
    db.add(row)
    await db.flush()
    return row


async def read_progression_history(
    db,
    novel_id: str,
    *,
    scene_id: str | None = None,
    root_id: str | None = None,
    include_deleted: bool = False,
) -> dict:
    roots_query = select(StoryWorldProgressionRoot).where(
        StoryWorldProgressionRoot.novel_id == _uuid(novel_id)
    )
    if scene_id:
        roots_query = roots_query.where(
            StoryWorldProgressionRoot.scene_id == _uuid(scene_id)
        )
    if root_id:
        roots_query = roots_query.where(StoryWorldProgressionRoot.id == _uuid(root_id))
    roots = list(
        (
            await db.scalars(
                roots_query.order_by(
                    StoryWorldProgressionRoot.created_at.desc(),
                    StoryWorldProgressionRoot.id.desc(),
                )
            )
        ).all()
    )
    if not roots and root_id:
        raise NotFoundError("世界推进运行不存在")
    root_ids = [item.id for item in roots]
    if not root_ids:
        return {"roots": [], "basis_status": "not_checked"}
    branches_query = select(StoryWorldProgressionBranch).where(
        StoryWorldProgressionBranch.novel_id == _uuid(novel_id),
        StoryWorldProgressionBranch.root_id.in_(root_ids),
    )
    if not include_deleted:
        branches_query = branches_query.where(
            StoryWorldProgressionBranch.deleted_at.is_(None)
        )
    branches = list(
        (
            await db.scalars(
                branches_query.order_by(
                    StoryWorldProgressionBranch.created_at,
                    StoryWorldProgressionBranch.id,
                )
            )
        ).all()
    )
    branch_ids = [item.id for item in branches]
    steps = (
        list(
            (
                await db.scalars(
                    select(StoryWorldProgressionStep)
                    .where(
                        StoryWorldProgressionStep.novel_id == _uuid(novel_id),
                        StoryWorldProgressionStep.branch_id.in_(branch_ids),
                    )
                    .order_by(
                        StoryWorldProgressionStep.created_at,
                        StoryWorldProgressionStep.id,
                    )
                )
            ).all()
        )
        if branch_ids
        else []
    )
    steps_by_branch: dict[str, list[dict]] = {}
    for step in steps:
        result = dict(step.result_json or {})
        hooks = [
            {
                **dict(hook),
                "hook_id": content_hash(
                    {
                        "step_id": str(step.id),
                        "output_hash": step.output_hash,
                        "index": index,
                        "hook": dict(hook),
                    }
                )[:32],
            }
            for index, hook in enumerate(result.get("plot_hooks") or [])
        ]
        if hooks:
            result["plot_hooks"] = hooks
        steps_by_branch.setdefault(str(step.branch_id), []).append(
            {
                "id": str(step.id),
                "root_id": str(step.root_id),
                "branch_id": str(step.branch_id),
                "parent_step_id": str(step.parent_step_id)
                if step.parent_step_id
                else None,
                "step_number": step.step_number,
                "source_hash": step.source_hash,
                "input_hash": step.input_hash,
                "output_hash": step.output_hash,
                "basis_changed": step.basis_changed,
                "input": {
                    key: value
                    for key, value in dict(step.input_json or {}).items()
                    if key not in {"context_confirmation_id", "operation_id"}
                },
                "result": result,
                "state": dict(step.state_json or {}),
                "metrics": dict(step.metrics_json or {}),
                "created_at": step.created_at.isoformat() if step.created_at else None,
            }
        )
    branches_by_root: dict[str, list[dict]] = {}
    for branch in branches:
        pending = dict(branch.pending_step_json or {})
        branches_by_root.setdefault(str(branch.root_id), []).append(
            {
                "id": str(branch.id),
                "root_id": str(branch.root_id),
                "parent_step_id": str(branch.parent_step_id)
                if branch.parent_step_id
                else None,
                "branch_kind": branch.branch_kind,
                "basis_choice": branch.basis_choice,
                "source_hash": branch.source_hash,
                "status": branch.status,
                "stop_reason": branch.stop_reason,
                "pending_step": {
                    "pending": bool(pending),
                    "cached_participant_count": len(pending.get("actor_drafts") or {}),
                    "resolution_saved": pending.get("resolution") is not None,
                },
                "name": branch.name,
                "note": branch.note,
                "starred": branch.starred,
                "updated_at": branch.updated_at.isoformat()
                if branch.updated_at
                else None,
                "deleted_at": branch.deleted_at.isoformat()
                if branch.deleted_at
                else None,
                "restore_until": branch.restore_until.isoformat()
                if branch.restore_until
                else None,
                "steps": steps_by_branch.get(str(branch.id), []),
            }
        )
    return {
        "roots": [
            _root_history_view(root, branches_by_root.get(str(root.id), []))
            for root in roots
        ],
        "basis_status": "not_checked",
    }


def _root_history_view(root, branches: list[dict]) -> dict:
    request = dict(root.request_json or {})
    safe_request = {
        key: value
        for key, value in request.items()
        if key not in {"operation_id", "context_confirmation_id", "budget_preview_hash"}
    }
    envelope = dict(root.run_envelope_json or {})
    usage = envelope.get("usage") or {}
    cutoff = (
        ((root.source_snapshot_json or {}).get("time_basis") or {}).get("cutoff") or {}
    )
    return {
        "id": str(root.id),
        "novel_id": str(root.novel_id),
        "scene_id": str(root.scene_id),
        "cutoff_chapter": cutoff.get("chapter_index"),
        "source_hash": root.source_hash,
        "request": safe_request,
        "budget": {
            "requests_used": int(envelope.get("requests_started") or 0),
            "requests_authorized": envelope.get("request_limit"),
            "tokens_used": int(usage.get("total_tokens") or 0),
            "tokens_authorized": envelope.get("token_limit"),
            "unknown_requests": int(envelope.get("requests_unknown") or 0),
            "started_at": envelope.get("started_at"),
            "deadline_at": envelope.get("deadline_at"),
            "fee_status": "可能产生计费请求；未估算金额",
        },
        "status": root.status,
        "created_at": root.created_at.isoformat() if root.created_at else None,
        "branches": branches,
    }


async def update_branch_metadata(
    db,
    *,
    novel_id: str,
    branch_id: str,
    changes: dict,
    expected_updated_at: str,
) -> dict:
    row = await get_progression_branch(db, novel_id, branch_id, lock=True)
    try:
        expected = datetime.fromisoformat(expected_updated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("分支版本标识无效") from exc
    current = row.updated_at
    if current is None or current.tzinfo is None:
        current = current.replace(tzinfo=UTC) if current else None
    if current is None or expected.astimezone(UTC) != current.astimezone(UTC):
        raise ConflictError("推进历史已被编辑，请刷新后再试")
    for field in ("name", "note", "starred"):
        if field in changes:
            setattr(row, field, changes[field])
    row.updated_at = datetime.now(UTC)
    await db.flush()
    return {
        "id": str(row.id),
        "name": row.name,
        "note": row.note,
        "starred": row.starred,
        "updated_at": row.updated_at.isoformat(),
    }


async def delete_progression_branch(db, *, novel_id: str, branch_id: str) -> dict:
    row = await get_progression_branch(db, novel_id, branch_id, lock=True)
    authorization = await db.scalar(
        select(StoryWorldProgressionAuthorization)
        .where(StoryWorldProgressionAuthorization.novel_id == _uuid(novel_id))
        .with_for_update()
    )
    if (
        authorization is not None
        and authorization.enabled
        and authorization.branch_id == row.id
    ):
        authorization.enabled = False
        authorization.revision += 1
        authorization.participant_ids_json = []
        authorization.root_id = None
        authorization.branch_id = None
        authorization.context_confirmation_id = None
        authorization.updated_at = datetime.now(UTC)
    now = datetime.now(UTC)
    row.deleted_at = now
    row.restore_until = now + timedelta(days=30)
    row.updated_at = now
    await db.flush()
    return {
        "id": str(row.id),
        "deleted_at": now.isoformat(),
        "restore_until": row.restore_until.isoformat(),
    }


async def restore_progression_branch(db, *, novel_id: str, branch_id: str) -> dict:
    row = await get_progression_branch(
        db, novel_id, branch_id, lock=True, include_deleted=True
    )
    if row.deleted_at is None:
        return {"id": str(row.id), "restored": True}
    if row.restore_until is None or row.restore_until < datetime.now(UTC):
        raise ConflictError("这条分支已超过 30 天恢复期")
    row.deleted_at = None
    row.restore_until = None
    row.updated_at = datetime.now(UTC)
    await db.flush()
    return {"id": str(row.id), "restored": True}


async def compare_progression_steps(
    db, *, novel_id: str, first_step_id: str, second_step_id: str
) -> dict:
    left, right = await asyncio_gather_steps(db, novel_id, first_step_id, second_step_id)
    if str(left.root_id) != str(right.root_id):
        raise ConflictError("只能比较同一推进根中的两个步骤")
    return {
        "root_id": str(left.root_id),
        "left": {
            "id": str(left.id),
            "input_hash": left.input_hash,
            "output_hash": left.output_hash,
            "result": dict(left.result_json or {}),
        },
        "right": {
            "id": str(right.id),
            "input_hash": right.input_hash,
            "output_hash": right.output_hash,
            "result": dict(right.result_json or {}),
        },
        "state_equal": content_hash(left.state_json or {})
        == content_hash(right.state_json or {}),
        "basis_changed": bool(left.basis_changed or right.basis_changed),
    }


async def asyncio_gather_steps(db, novel_id: str, first: str, second: str):
    # Same-session sequential reads avoid an asyncio dependency in this service.
    left = await get_progression_step(db, novel_id, first)
    right = await get_progression_step(db, novel_id, second)
    return left, right
