"""Persistence and author operations for scene-director history."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select

from core.errors import ConflictError, NotFoundError
from modules.story.director_candidates import transfer_choices
from modules.story.models import (
    StorySceneDirectorBranch,
    StorySceneDirectorCandidateTransfer,
    StorySceneDirectorPreference,
    StorySceneDirectorReference,
    StorySceneDirectorRoot,
    StorySceneDirectorRound,
)

DEFAULT_CLICHE_PHRASES = ["嘴角微微上扬", "眼中闪过一丝", "不由得攥紧了拳头"]


def _uuid(value: str | UUID) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("导演记录标识无效") from exc


async def get_director_root(db, novel_id: str, root_id: str, *, lock=False):
    query = select(StorySceneDirectorRoot).where(
        StorySceneDirectorRoot.novel_id == _uuid(novel_id),
        StorySceneDirectorRoot.id == _uuid(root_id),
    )
    row = await db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise NotFoundError("导演历史不存在")
    return row


async def get_director_branch(db, novel_id: str, branch_id: str, *, lock=False):
    query = select(StorySceneDirectorBranch).where(
        StorySceneDirectorBranch.novel_id == _uuid(novel_id),
        StorySceneDirectorBranch.id == _uuid(branch_id),
    )
    row = await db.scalar(query.with_for_update() if lock else query)
    if row is None or row.deleted_at is not None:
        raise NotFoundError("导演分支不存在")
    return row


async def get_director_round(db, novel_id: str, round_id: str):
    row = await db.scalar(
        select(StorySceneDirectorRound).where(
            StorySceneDirectorRound.novel_id == _uuid(novel_id),
            StorySceneDirectorRound.id == _uuid(round_id),
        )
    )
    if row is None:
        raise NotFoundError("导演回合不存在")
    branch = await get_director_branch(db, novel_id, str(row.branch_id))
    return row, branch


async def recheck_director_round_consistency(db, novel_id: str, round_id: str) -> dict:
    """Recompute deterministic findings against today's confirmed Scene sources.

    Historical output stays immutable; a changed source never silently validates an old
    role perception or typed reference.
    """
    from modules.story.director_consistency import build_consistency
    from modules.story.director_context import read_director_source
    from modules.story.director_schemas import (
        DirectorCandidateEvent,
        DirectorConsistencyFinding,
        DirectorMaterial,
    )

    row, _branch = await get_director_round(db, novel_id, round_id)
    root = await get_director_root(db, novel_id, str(row.root_id))
    request = root.request_json or {}
    current = await read_director_source(
        db,
        novel_id=novel_id,
        scene_id=str(root.scene_id),
        character_ids=list(request.get("character_ids") or []),
        related_object_ids=list(request.get("related_object_ids") or []),
    )
    output = row.output_json or {}
    materials = [
        DirectorMaterial.model_validate(item) for item in output.get("materials") or []
    ]
    for material in materials:
        # The frozen round's material verdict is historical evidence, not a
        # verdict produced by this recheck against today's sources.
        material.conflict_status = "unknown"
    consistency = build_consistency(
        source=current,
        intents=[],
        candidates={},
        materials=materials,
        candidate_events=[
            DirectorCandidateEvent.model_validate(item)
            for item in output.get("candidate_events") or []
        ],
        object_ids=set(),
        map_node_ids=set(),
        state_replayed=False,
    )
    consistency.unavailable_checks.append(
        "冻结回合的对象身份、人物感知、动作结算与状态回放本次未重新执行；原回执仅作为历史依据。"
    )
    source_changed = current["source_hash"] != row.source_hash
    if source_changed:
        consistency.coverage = "unknown"
        consistency.unavailable_checks.append(
            "当前确认来源与冻结回合不同；旧人物知情、感知和对象身份须重排演后核验。"
        )
        consistency.findings.append(
            DirectorConsistencyFinding(
                severity="unknown",
                field="source_changed",
                statement="资料已变化；本次只重算当前精确来源冲突，不追认旧回合的角色可知断言。",
            )
        )
    return {
        "round_id": str(row.id),
        "original_source_hash": row.source_hash,
        "current_source_hash": current["source_hash"],
        "output_hash": row.output_hash,
        "source_changed": source_changed,
        "consistency": consistency.model_dump(mode="json"),
        "model_requests": 0,
    }


async def list_director_history(
    db, novel_id: str, scene_id: str, *, purge_expired: bool = True
) -> dict:
    nid, sid = _uuid(novel_id), _uuid(scene_id)
    if purge_expired:
        await purge_expired_director_history(db, novel_id)
    branches = list(
        (
            await db.scalars(
                select(StorySceneDirectorBranch)
                .where(
                    StorySceneDirectorBranch.novel_id == nid,
                    StorySceneDirectorBranch.deleted_at.is_(None),
                    StorySceneDirectorBranch.root_id.in_(
                        select(StorySceneDirectorRoot.id).where(
                            StorySceneDirectorRoot.novel_id == nid,
                            StorySceneDirectorRoot.scene_id == sid,
                        )
                    ),
                )
                .order_by(
                    StorySceneDirectorBranch.created_at, StorySceneDirectorBranch.id
                )
            )
        ).all()
    )
    recoverable_branches = list(
        (
            await db.scalars(
                select(StorySceneDirectorBranch)
                .where(
                    StorySceneDirectorBranch.novel_id == nid,
                    StorySceneDirectorBranch.deleted_at.is_not(None),
                    StorySceneDirectorBranch.restore_until >= datetime.now(UTC),
                    StorySceneDirectorBranch.root_id.in_(
                        select(StorySceneDirectorRoot.id).where(
                            StorySceneDirectorRoot.novel_id == nid,
                            StorySceneDirectorRoot.scene_id == sid,
                        )
                    ),
                )
                .order_by(StorySceneDirectorBranch.deleted_at)
            )
        ).all()
    )
    branch_ids = [item.id for item in branches]
    rounds = (
        list(
            (
                await db.scalars(
                    select(StorySceneDirectorRound)
                    .where(
                        StorySceneDirectorRound.novel_id == nid,
                        StorySceneDirectorRound.branch_id.in_(branch_ids),
                    )
                    .order_by(
                        StorySceneDirectorRound.created_at,
                        StorySceneDirectorRound.round_number,
                    )
                )
            ).all()
        )
        if branch_ids
        else []
    )
    references = list(
        (
            await db.scalars(
                select(StorySceneDirectorReference)
                .where(
                    StorySceneDirectorReference.novel_id == nid,
                    StorySceneDirectorReference.scene_id == sid,
                    StorySceneDirectorReference.deleted_at.is_(None),
                )
                .order_by(StorySceneDirectorReference.created_at)
            )
        ).all()
    )
    round_ids = {item.id for item in rounds}
    round_to_branch = {item.id: item.branch_id for item in rounds}
    roots = list(
        (
            await db.scalars(
                select(StorySceneDirectorRoot)
                .where(
                    StorySceneDirectorRoot.novel_id == nid,
                    StorySceneDirectorRoot.scene_id == sid,
                )
                .order_by(StorySceneDirectorRoot.created_at, StorySceneDirectorRoot.id)
            )
        ).all()
    )
    recoverable_references = list(
        (
            await db.scalars(
                select(StorySceneDirectorReference)
                .where(
                    StorySceneDirectorReference.novel_id == nid,
                    StorySceneDirectorReference.scene_id == sid,
                    StorySceneDirectorReference.deleted_at.is_not(None),
                    StorySceneDirectorReference.restore_until >= datetime.now(UTC),
                )
                .order_by(StorySceneDirectorReference.deleted_at)
            )
        ).all()
    )
    return {
        "scene_id": str(sid),
        "roots": [
            {
                "id": str(row.id),
                "status": row.status,
                "character_ids": list(
                    (row.request_json or {}).get("character_ids") or []
                ),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "usage": _usage_summary(row.run_envelope_json),
            }
            for row in roots
        ],
        "branches": [
            {
                "id": str(row.id),
                "root_id": str(row.root_id),
                "parent_round_id": str(row.parent_round_id)
                if row.parent_round_id
                else None,
                "branch_kind": row.branch_kind,
                "status": row.status,
                "name": row.name,
                "note": row.note,
                "starred": row.starred,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "round_ids": [
                    str(item.id) for item in rounds if item.branch_id == row.id
                ],
            }
            for row in branches
        ],
        "recoverable_branches": [
            {
                "id": str(row.id),
                "root_id": str(row.root_id),
                "name": row.name,
                "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
                "restore_until": row.restore_until.isoformat()
                if row.restore_until
                else None,
            }
            for row in recoverable_branches
        ],
        "rounds": [_round_summary(row, round_to_branch, round_ids) for row in rounds],
        "references": [
            {
                "id": str(row.id),
                "root_id": str(row.root_id),
                "name": row.name,
                "origin": row.origin,
                "source_round_id": str(row.source_round_id)
                if row.source_round_id
                else None,
                "source_round_deleted": bool(
                    row.source_round_id and row.source_round_id not in round_ids
                ),
                "source_basis_hash": row.source_basis_hash,
                "source_deleted": row.source_deleted,
                "angle": row.angle_json,
                "content_copy": row.content_copy_json,
                "material_ids": row.material_ids_json,
                "annotation": row.annotation,
                "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
            }
            for row in references
        ],
        "recoverable_references": [
            {
                "id": str(row.id),
                "name": row.name,
                "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
                "restore_until": row.restore_until.isoformat()
                if row.restore_until
                else None,
            }
            for row in recoverable_references
        ],
    }


async def read_director_history_view(db, novel_id: str, scene_id: str) -> dict:
    """Author-scoped history with source freshness from the current Scene."""
    from modules.story.director_context import read_director_source

    history = await list_director_history(db, novel_id, scene_id)
    transfers = (
        await db.scalars(
            select(StorySceneDirectorCandidateTransfer).where(
                StorySceneDirectorCandidateTransfer.novel_id == _uuid(novel_id),
                StorySceneDirectorCandidateTransfer.scene_id == _uuid(scene_id),
            )
        )
    ).all()
    history["candidate_transfers"] = [
        {
            "round_id": str(row.round_id),
            "candidate_id": row.candidate_ref,
            "world_candidate_id": str(row.world_candidate_id),
            "entity_type": row.entity_type,
        }
        for row in transfers
    ]
    current_hash_by_root: dict[str, str | None] = {}
    for root_item in history.get("roots", []):
        root_id = str(root_item.get("id") or "")
        try:
            root = await get_director_root(db, novel_id, root_id)
            request = root.request_json or {}
            source = await read_director_source(
                db,
                novel_id=novel_id,
                scene_id=str(root.scene_id),
                character_ids=list(request.get("character_ids") or []),
                related_object_ids=list(request.get("related_object_ids") or []),
            )
            current_hash_by_root[root_id] = source["source_hash"]
        except (NotFoundError, ValueError):
            current_hash_by_root[root_id] = None
    root_by_branch = {
        str(item["id"]): str(item.get("root_id") or "")
        for item in history.get("branches", [])
    }
    for round_item in history.get("rounds", []):
        current_hash = current_hash_by_root.get(
            root_by_branch.get(str(round_item.get("branch_id") or ""), "")
        )
        round_item["basis_status"] = (
            "unknown"
            if current_hash is None
            else "changed"
            if current_hash != round_item.get("source_hash")
            else "current"
        )
    for reference in history.get("references", []):
        current_hash = current_hash_by_root.get(str(reference.get("root_id") or ""))
        reference["source_changed"] = bool(
            current_hash is not None
            and current_hash != reference.get("source_basis_hash")
        )
        reference["source_basis_available"] = current_hash is not None
    return history


def _usage_summary(value: dict | None) -> dict:
    envelope = value or {}
    usage = envelope.get("usage") or {}
    return {
        "requests_started": int(envelope.get("requests_started") or 0),
        "requests_settled": int(envelope.get("requests_settled") or 0),
        "requests_unknown": int(envelope.get("requests_unknown") or 0),
        "request_limit": envelope.get("request_limit"),
        "tokens_used": int(usage.get("total_tokens") or 0),
        "token_limit": envelope.get("token_limit"),
        "deadline_at": envelope.get("deadline_at"),
        "charge_state": envelope.get("charge_state", "none"),
        "usage_complete": envelope.get("usage_complete", True),
        "authorization_revision": int(envelope.get("authorization_revision") or 0),
        "status": envelope.get("status", "running"),
    }


def _round_summary(row, round_to_branch, round_ids):
    output = row.output_json or {}
    source = row.input_json or {}
    request = source.get("request") or {}
    return {
        "id": str(row.id),
        "branch_id": str(row.branch_id),
        "parent_round_id": str(row.parent_round_id) if row.parent_round_id else None,
        "branch_parent_branch_id": (
            str(round_to_branch.get(row.parent_round_id))
            if row.parent_round_id in round_to_branch
            else None
        ),
        "round_number": row.round_number,
        "source_hash": row.source_hash,
        "input_hash": row.input_hash,
        "output_hash": row.output_hash,
        "input": {
            "instructions": request.get("instructions", ""),
            "intervention": request.get("intervention", ""),
            "public_stimulus": request.get("public_stimulus", ""),
            "divergence": request.get("divergence", "balanced"),
            "basis_choice": source.get("basis_choice", "current"),
            "source_changed": bool(source.get("source_changed")),
            "groups": output.get("groups", {}),
            "omitted": output.get("omitted", []),
        },
        "performances": output.get("performances", []),
        "materials": output.get("materials", []),
        "recommended_angles": output.get("recommended_angles", []),
        "alternatives": output.get("alternatives", []),
        "candidate_events": output.get("candidate_events", []),
        "candidate_transfer_choices": transfer_choices(output),
        "consistency": output.get("consistency", {}),
        "warnings": output.get("warnings", []),
        "state_delta": output.get("state_delta", []),
        "observed_events": output.get("observed_events", []),
        "usage": _usage_summary(row.run_envelope_json),
        "name": row.name,
        "note": row.note,
        "starred": row.starred,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def save_round_metadata(db, novel_id: str, round_id: str, changes: dict):
    row, _ = await get_director_round(db, novel_id, round_id)
    if "starred" in changes and changes["starred"] is not None:
        row.starred = changes["starred"]
    if "name" in changes and changes["name"] is not None:
        row.name = changes["name"].strip() or None
    if "note" in changes and changes["note"] is not None:
        row.note = changes["note"]
    await db.flush()
    return {"id": str(row.id), "name": row.name, "note": row.note, "starred": row.starred}


async def delete_director_branch(db, novel_id: str, branch_id: str) -> dict:
    now = datetime.now(UTC)
    branch = await db.scalar(
        select(StorySceneDirectorBranch)
        .where(
            StorySceneDirectorBranch.novel_id == _uuid(novel_id),
            StorySceneDirectorBranch.id == _uuid(branch_id),
            StorySceneDirectorBranch.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if branch is None:
        raise NotFoundError("导演分支不存在")
    round_ids = [
        row.id
        for row in (
            await db.scalars(
                select(StorySceneDirectorRound).where(
                    StorySceneDirectorRound.novel_id == _uuid(novel_id),
                    StorySceneDirectorRound.branch_id == branch.id,
                )
            )
        ).all()
    ]
    refs = (
        list(
            (
                await db.scalars(
                    select(StorySceneDirectorReference).where(
                        StorySceneDirectorReference.novel_id == _uuid(novel_id),
                        StorySceneDirectorReference.source_round_id.in_(round_ids),
                        StorySceneDirectorReference.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        if round_ids
        else []
    )
    branch.deleted_at = now
    branch.restore_until = now + timedelta(days=30)
    branch.status = "deleted"
    for reference in refs:
        reference.source_deleted = True
    return {
        "deleted_branch_ids": [str(branch.id)],
        "affected_round_count": len(round_ids),
        "referenced_scripts": [
            {
                "id": str(item.id),
                "name": item.name,
                "source_round_id": str(item.source_round_id),
            }
            for item in refs
        ],
        "restore_until": (now + timedelta(days=30)).isoformat(),
    }


async def delete_unstarred_director_branches(db, novel_id: str, scene_id: str) -> dict:
    """Soft-delete only unstarred branches in this Scene; starred siblings survive."""
    nid, sid = _uuid(novel_id), _uuid(scene_id)
    now = datetime.now(UTC)
    rows = list(
        (
            await db.scalars(
                select(StorySceneDirectorBranch)
                .where(
                    StorySceneDirectorBranch.novel_id == nid,
                    StorySceneDirectorBranch.starred.is_(False),
                    StorySceneDirectorBranch.deleted_at.is_(None),
                    StorySceneDirectorBranch.root_id.in_(
                        select(StorySceneDirectorRoot.id).where(
                            StorySceneDirectorRoot.novel_id == nid,
                            StorySceneDirectorRoot.scene_id == sid,
                        )
                    ),
                )
                .with_for_update()
            )
        ).all()
    )
    if not rows:
        return {
            "deleted_branch_ids": [],
            "affected_round_count": 0,
            "restore_until": None,
        }
    branch_ids = [item.id for item in rows]
    round_ids = list(
        (
            await db.scalars(
                select(StorySceneDirectorRound.id).where(
                    StorySceneDirectorRound.novel_id == nid,
                    StorySceneDirectorRound.branch_id.in_(branch_ids),
                )
            )
        ).all()
    )
    references = (
        list(
            (
                await db.scalars(
                    select(StorySceneDirectorReference).where(
                        StorySceneDirectorReference.novel_id == nid,
                        StorySceneDirectorReference.source_round_id.in_(round_ids),
                        StorySceneDirectorReference.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        if round_ids
        else []
    )
    for row in rows:
        row.deleted_at = now
        row.restore_until = now + timedelta(days=30)
        row.status = "deleted"
    for reference in references:
        reference.source_deleted = True
    return {
        "deleted_branch_ids": [str(row.id) for row in rows],
        "affected_round_count": len(round_ids),
        "referenced_scripts": [
            {
                "id": str(item.id),
                "name": item.name,
                "source_round_id": str(item.source_round_id),
            }
            for item in references
        ],
        "restore_until": (now + timedelta(days=30)).isoformat(),
    }


async def restore_director_branch(db, novel_id: str, branch_id: str) -> dict:
    nid, bid = _uuid(novel_id), _uuid(branch_id)
    row = await db.scalar(
        select(StorySceneDirectorBranch)
        .where(
            StorySceneDirectorBranch.novel_id == nid,
            StorySceneDirectorBranch.id == bid,
            StorySceneDirectorBranch.deleted_at.is_not(None),
        )
        .with_for_update()
    )
    if row is None:
        raise NotFoundError("可恢复的导演分支不存在")
    now = datetime.now(UTC)
    if row.restore_until is None or row.restore_until < now:
        raise ConflictError("导演分支已超过 30 天恢复期限")
    row.deleted_at = None
    row.restore_until = None
    row.status = "ready"
    rounds = list(
        (
            await db.scalars(
                select(StorySceneDirectorRound).where(
                    StorySceneDirectorRound.novel_id == nid,
                    StorySceneDirectorRound.branch_id == bid,
                )
            )
        ).all()
    )
    round_ids = [item.id for item in rounds]
    if round_ids:
        refs = list(
            (
                await db.scalars(
                    select(StorySceneDirectorReference).where(
                        StorySceneDirectorReference.novel_id == nid,
                        StorySceneDirectorReference.source_round_id.in_(round_ids),
                    )
                )
            ).all()
        )
        for ref in refs:
            ref.source_deleted = False
    return {"restored_branch_count": 1}


async def purge_expired_director_history(db, novel_id: str) -> None:
    """Clear expired soft-deletes; keep copied references independent."""
    now = datetime.now(UTC)
    nid = _uuid(novel_id)
    expired = list(
        (
            await db.scalars(
                select(StorySceneDirectorBranch.id).where(
                    StorySceneDirectorBranch.novel_id == nid,
                    StorySceneDirectorBranch.restore_until.is_not(None),
                    StorySceneDirectorBranch.restore_until < now,
                )
            )
        ).all()
    )
    if expired:
        expired_round_ids = list(
            (
                await db.scalars(
                    select(StorySceneDirectorRound.id).where(
                        StorySceneDirectorRound.novel_id == nid,
                        StorySceneDirectorRound.branch_id.in_(expired),
                    )
                )
            ).all()
        )
        if expired_round_ids:
            refs_for_expired = list(
                (
                    await db.scalars(
                        select(StorySceneDirectorReference).where(
                            StorySceneDirectorReference.novel_id == nid,
                            StorySceneDirectorReference.source_round_id.in_(
                                expired_round_ids
                            ),
                        )
                    )
                ).all()
            )
            for ref in refs_for_expired:
                ref.source_deleted = True
        await db.execute(
            delete(StorySceneDirectorBranch).where(
                StorySceneDirectorBranch.novel_id == nid,
                StorySceneDirectorBranch.id.in_(expired),
            )
        )
    refs = list(
        (
            await db.scalars(
                select(StorySceneDirectorReference).where(
                    StorySceneDirectorReference.novel_id == nid,
                    StorySceneDirectorReference.restore_until.is_not(None),
                    StorySceneDirectorReference.restore_until < now,
                )
            )
        ).all()
    )
    if refs:
        await db.execute(
            delete(StorySceneDirectorReference).where(
                StorySceneDirectorReference.novel_id == nid,
                StorySceneDirectorReference.id.in_([item.id for item in refs]),
            )
        )
    roots = list(
        (
            await db.scalars(
                select(StorySceneDirectorRoot).where(
                    StorySceneDirectorRoot.novel_id == nid,
                    ~StorySceneDirectorRoot.id.in_(
                        select(StorySceneDirectorBranch.root_id).where(
                            StorySceneDirectorBranch.novel_id == nid,
                        )
                    ),
                    ~StorySceneDirectorRoot.id.in_(
                        select(StorySceneDirectorReference.root_id).where(
                            StorySceneDirectorReference.novel_id == nid,
                        )
                    ),
                )
            )
        ).all()
    )
    for root in roots:
        await db.delete(root)
    if expired or refs or roots:
        await db.flush()


async def update_reference_metadata(
    db,
    novel_id: str,
    reference_id: str,
    *,
    annotation: str | None = None,
    name: str | None = None,
):
    row = await db.scalar(
        select(StorySceneDirectorReference).where(
            StorySceneDirectorReference.novel_id == _uuid(novel_id),
            StorySceneDirectorReference.id == _uuid(reference_id),
            StorySceneDirectorReference.deleted_at.is_(None),
        )
    )
    if row is None:
        raise NotFoundError("参考剧本不存在")
    if annotation is not None:
        row.annotation = annotation
    if name is not None:
        row.name = name.strip()
    await db.flush()
    return {"id": str(row.id), "name": row.name, "annotation": row.annotation}


async def delete_director_reference(db, novel_id: str, reference_id: str) -> dict:
    row = await db.scalar(
        select(StorySceneDirectorReference)
        .where(
            StorySceneDirectorReference.novel_id == _uuid(novel_id),
            StorySceneDirectorReference.id == _uuid(reference_id),
            StorySceneDirectorReference.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        raise NotFoundError("参考剧本不存在")
    now = datetime.now(UTC)
    row.deleted_at = now
    row.restore_until = now + timedelta(days=30)
    return {"id": str(row.id), "restore_until": row.restore_until.isoformat()}


async def restore_director_reference(db, novel_id: str, reference_id: str) -> dict:
    now = datetime.now(UTC)
    row = await db.scalar(
        select(StorySceneDirectorReference)
        .where(
            StorySceneDirectorReference.novel_id == _uuid(novel_id),
            StorySceneDirectorReference.id == _uuid(reference_id),
            StorySceneDirectorReference.deleted_at.is_not(None),
        )
        .with_for_update()
    )
    if row is None:
        raise NotFoundError("可恢复的参考剧本不存在")
    if row.restore_until is None or row.restore_until < now:
        raise ConflictError("参考剧本已超过 30 天恢复期限")
    row.deleted_at = None
    row.restore_until = None
    await db.flush()
    return {"id": str(row.id), "restored": True, "source_deleted": row.source_deleted}


async def save_director_reference(
    db, novel_id: str, request, *, origin: str = "author_ui"
) -> dict:
    if origin not in {"author_ui", "author_via_assistant"}:
        raise ValueError("导演参考来源无效")
    row, branch = await get_director_round(db, novel_id, str(request.source_round_id))
    root = await get_director_root(db, novel_id, str(row.root_id))
    if str(root.id) != str(branch.root_id):
        raise ValueError("参考来源的导演运行身份不一致")
    allowed_actors = set((root.request_json or {}).get("character_ids") or [])
    if (
        request.angle.viewpoint_character_id
        and request.angle.viewpoint_character_id not in allowed_actors
    ):
        raise ValueError("角度 POV 不属于此场景的导演参与者")
    output = row.output_json or {}
    available = {item.get("material_id"): item for item in output.get("materials", [])}
    selected_ids = list(dict.fromkeys(request.material_ids))
    if len(selected_ids) != len(request.material_ids):
        raise ValueError("素材卡选择不能重复")
    if not set(selected_ids) <= set(available):
        raise ValueError("所选素材卡不属于来源回合")
    if not set(request.angle.material_ids) <= set(selected_ids):
        raise ValueError("保存的角度引用了未选择的素材卡")
    content_copy = {
        "materials": [available[item] for item in selected_ids],
        "angle": request.angle.model_dump(mode="json"),
        "performances": [
            item
            for item in output.get("performances", [])
            if request.angle.viewpoint_kind == "omniscient"
            or item.get("character_id") == request.angle.viewpoint_character_id
        ],
    }
    record = StorySceneDirectorReference(
        novel_id=_uuid(novel_id),
        root_id=root.id,
        scene_id=root.scene_id,
        source_round_id=row.id,
        source_basis_hash=row.source_hash,
        source_deleted=False,
        name=request.name.strip(),
        content_copy_json=content_copy,
        material_ids_json=selected_ids,
        angle_json=request.angle.model_dump(mode="json"),
        annotation=request.annotation,
        origin=origin,
    )
    if not record.name:
        raise ValueError("参考剧本需要一个名称")
    db.add(record)
    await db.flush()
    return {
        "id": str(record.id),
        "name": record.name,
        "source_round_id": str(row.id),
        "source_basis_hash": row.source_hash,
        "material_ids": selected_ids,
        "angle": record.angle_json,
        "content_copy": record.content_copy_json,
        "annotation": record.annotation,
        "origin": record.origin,
        "advisory_only": True,
        "adoption_status": "not_adopted",
    }


def fit_director_references_for_writing(items: list[dict], max_chars: int | None) -> dict:
    """Keep references advisory: an over-budget copy is omitted with a warning."""
    if max_chars is None:
        return {"items": items, "omitted": [], "omission_reasons": {}, "warnings": []}
    included: list[dict] = []
    omitted: list[str] = []
    omission_reasons: dict[str, str] = {}
    used = 0
    for item in items:
        size = len(json.dumps(item.get("content_copy") or {}, ensure_ascii=False))
        if size <= max_chars - used:
            included.append(item)
            used += size
        else:
            reference_id = str(item.get("reference_id") or "")
            omitted.append(reference_id)
            if reference_id:
                omission_reasons[reference_id] = (
                    "所选副本超出 Evidence 导演参考维度的独立字符预算"
                )
    warnings = (
        ["部分导演参考剧本因写作上下文预算未纳入；此来源是可选建议，不影响写作运行。"]
        if omitted
        else []
    )
    return {
        "items": included,
        "omitted": omitted,
        "omission_reasons": omission_reasons,
        "warnings": warnings,
    }


async def read_director_references_for_writing(
    db,
    novel_id: str,
    reference_ids: list[str],
    *,
    consumer_action: str,
    expected_scene_id: str | None = None,
    max_chars: int | None = None,
) -> dict:
    if consumer_action not in {"writing.generate", "writing.targeted_revision"}:
        raise ValueError("导演参考只可由 Writing generate 或 targeted revision 显式读取")
    if not reference_ids:
        return {"items": [], "omitted": [], "omission_reasons": {}, "warnings": []}
    if len(reference_ids) > 20:
        raise ValueError("导演参考选择必须唯一且不超过 20 份")
    normalized_ids = []
    warnings: list[str] = []
    for item in reference_ids:
        try:
            normalized_ids.append(str(_uuid(item)))
        except ValueError:
            warnings.append("部分已选导演参考已不可用，写作仍可继续。")
    if len(set(normalized_ids)) != len(normalized_ids):
        raise ValueError("导演参考选择必须唯一且不超过 20 份")
    omission_reasons: dict[str, str] = {}
    rows = (
        list(
            (
                await db.scalars(
                    select(StorySceneDirectorReference).where(
                        StorySceneDirectorReference.novel_id == _uuid(novel_id),
                        StorySceneDirectorReference.id.in_(
                            [_uuid(item) for item in normalized_ids]
                        ),
                        StorySceneDirectorReference.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        if normalized_ids
        else []
    )
    found = {str(item.id) for item in rows}
    if found != set(normalized_ids):
        warnings.append("部分已选导演参考已删除、过期或不属于当前作品，写作仍可继续。")
        omission_reasons.update(
            {
                missing: "所选副本当前不可读取或不属于当前作品"
                for missing in set(normalized_ids) - found
            }
        )
    result_items = []
    from modules.story.director_context import read_director_source

    for row in rows:
        if expected_scene_id and str(row.scene_id) != str(_uuid(expected_scene_id)):
            warnings.append("部分已选导演参考不属于当前场景，未提供给正文任务。")
            omission_reasons[str(row.id)] = "所选副本不属于当前 Scene"
            continue
        source_changed = False
        current_basis_available = True
        try:
            root = await get_director_root(db, novel_id, str(row.root_id))
            source = await read_director_source(
                db,
                novel_id=novel_id,
                scene_id=str(row.scene_id),
                character_ids=list((root.request_json or {}).get("character_ids") or []),
                related_object_ids=list(
                    (root.request_json or {}).get("related_object_ids") or []
                ),
            )
            source_changed = source["source_hash"] != row.source_basis_hash
        except (NotFoundError, ValueError):
            current_basis_available = False
        item = {
            "reference_id": str(row.id),
            "scene_id": str(row.scene_id),
            "name": row.name,
            "content_copy": row.content_copy_json,
            "material_ids": row.material_ids_json,
            "angle": row.angle_json,
            "source_round_id": str(row.source_round_id) if row.source_round_id else None,
            "source_deleted": row.source_deleted,
            "source_basis_hash": row.source_basis_hash,
            "source_changed": source_changed,
            "current_basis_available": current_basis_available,
            "warnings": [
                *(
                    ["导演来源回合已删除；保存的内容副本仍可供作者参考。"]
                    if row.source_deleted
                    else []
                ),
                *(
                    ["来源资料指纹已变化；当前正文仅保留原参考副本。"]
                    if source_changed
                    else []
                ),
                *(
                    ["当前来源资料不可读取；参考副本仍为可选内容。"]
                    if not current_basis_available
                    else []
                ),
            ],
            "advisory_only": True,
            "adoption_status": "not_adopted",
        }
        result_items.append(item)
    fitted = fit_director_references_for_writing(result_items, max_chars)
    fitted["omission_reasons"] = {
        **omission_reasons,
        **fitted.get("omission_reasons", {}),
    }
    fitted["warnings"] = list(dict.fromkeys([*warnings, *fitted["warnings"]]))
    return fitted


async def get_director_preferences(db, novel_id: str) -> dict:
    row = await db.scalar(
        select(StorySceneDirectorPreference).where(
            StorySceneDirectorPreference.novel_id == _uuid(novel_id)
        )
    )
    return {
        "cliche_phrases": list(row.cliche_phrases_json)
        if row
        else list(DEFAULT_CLICHE_PHRASES),
        "customized": row is not None,
    }


async def set_director_preferences(db, novel_id: str, phrases: list[str]) -> dict:
    clean = list(dict.fromkeys(item.strip() for item in phrases if item.strip()))
    if len(clean) != len(phrases):
        raise ValueError("套话清单不能包含空项或重复项")
    if any(len(item) > 120 for item in clean):
        raise ValueError("每条套话不能超过 120 个字符")
    row = await db.scalar(
        select(StorySceneDirectorPreference)
        .where(StorySceneDirectorPreference.novel_id == _uuid(novel_id))
        .with_for_update()
    )
    if row is None:
        row = StorySceneDirectorPreference(
            novel_id=_uuid(novel_id), cliche_phrases_json=clean
        )
        db.add(row)
    else:
        row.cliche_phrases_json = clean
    await db.flush()
    return {"cliche_phrases": clean, "customized": True}
