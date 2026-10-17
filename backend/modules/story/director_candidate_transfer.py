"""Explicit author transfer from a frozen Director event into World review."""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from core.errors import ConflictError, NotFoundError
from modules.story.director_candidates import transfer_choices
from modules.story.director_context import read_director_source
from modules.story.director_schemas import (
    DirectorCandidateTransferReceipt,
    DirectorCandidateTransferRequest,
)
from modules.story.director_service import (
    get_director_branch,
    get_director_root,
    get_director_round,
)
from modules.story.models import StorySceneDirectorCandidateTransfer
from modules.world.facade import create_entity


def _receipt(row: StorySceneDirectorCandidateTransfer, *, repeated: bool):
    return DirectorCandidateTransferReceipt(
        round_id=row.round_id,
        candidate_id=row.candidate_ref,
        world_candidate_id=row.world_candidate_id,
        entity_type=row.entity_type,
        repeated=repeated,
    )


def _check_receipt(row, data: DirectorCandidateTransferRequest) -> None:
    if (
        row.scene_id != data.scene_id
        or row.entity_type != data.entity_type
        or row.source_hash != data.expected_source_hash
        or row.output_hash != data.expected_output_hash
    ):
        raise ConflictError("该导演候选已按另一份类型或来源转入 World，请刷新历史")


async def _existing(db, novel_id: UUID, round_id: UUID, candidate_ref: str):
    return await db.scalar(
        select(StorySceneDirectorCandidateTransfer).where(
            StorySceneDirectorCandidateTransfer.novel_id == novel_id,
            StorySceneDirectorCandidateTransfer.round_id == round_id,
            StorySceneDirectorCandidateTransfer.candidate_ref == candidate_ref,
        )
    )


async def preview_director_candidate_transfer(
    db, round_id: str, data: DirectorCandidateTransferRequest
) -> dict:
    """Read-only exact source check; apply repeats it under the branch lock."""
    existing = await _existing(db, UUID(data.novel_id), UUID(round_id), data.candidate_id)
    if existing is not None:
        _check_receipt(existing, data)
        return {
            "candidate_id": data.candidate_id,
            "entity_type": data.entity_type,
            "world_candidate_id": str(existing.world_candidate_id),
            "repeated": True,
        }
    round_row, _branch = await get_director_round(db, data.novel_id, round_id)
    root = await get_director_root(db, data.novel_id, str(round_row.root_id))
    if root.scene_id != data.scene_id:
        raise NotFoundError("导演回合不属于当前 Scene")
    from modules.story.exploration_service import require_legacy_transfer_source

    require_legacy_transfer_source(round_row)
    if (
        round_row.source_hash != data.expected_source_hash
        or round_row.output_hash != data.expected_output_hash
    ):
        raise ConflictError("导演候选来源已变化，请刷新历史后再确认")
    request = root.request_json or {}
    current_source = await read_director_source(
        db,
        novel_id=data.novel_id,
        scene_id=str(root.scene_id),
        character_ids=list(request.get("character_ids") or []),
        related_object_ids=list(request.get("related_object_ids") or []),
    )
    if current_source["source_hash"] != round_row.source_hash:
        raise ConflictError("导演候选依据已有变化，请重新生成或核对后再转入")
    matching = [
        choice
        for choice in transfer_choices(round_row.output_json or {})
        if choice["candidate_id"] == data.candidate_id
    ]
    if len(matching) != 1 or matching[0]["conflict"]:
        raise ConflictError("所选导演候选不存在或来源不唯一，请刷新历史")
    choice = matching[0]
    if (choice["source_kind"] == "event") != (data.entity_type == "event"):
        raise ConflictError(
            "剧情事件只能转为事件；对象引用须单独选择人物、物件、地点或设定"
        )
    return {
        "candidate_id": data.candidate_id,
        "source_kind": choice["source_kind"],
        "source_id": choice["source_id"],
        "label": choice["label"],
        "description": choice["description"],
        "entity_type": data.entity_type,
        "source_hash": round_row.source_hash,
        "output_hash": round_row.output_hash,
        "repeated": False,
    }


async def transfer_director_candidate(
    db, round_id: str, data: DirectorCandidateTransferRequest
):
    """One candidate per source event; the branch lock serializes confirmations."""
    novel_id = UUID(data.novel_id)
    source_round_id = UUID(round_id)
    existing = await _existing(db, novel_id, source_round_id, data.candidate_id)
    if existing is not None:
        _check_receipt(existing, data)
        return _receipt(existing, repeated=True)

    _round_row, branch = await get_director_round(db, data.novel_id, round_id)
    await get_director_branch(db, data.novel_id, str(branch.id), lock=True)
    existing = await _existing(db, novel_id, source_round_id, data.candidate_id)
    if existing is not None:
        _check_receipt(existing, data)
        return _receipt(existing, repeated=True)

    preview = await preview_director_candidate_transfer(db, round_id, data)
    world_candidate_id = uuid5(
        NAMESPACE_URL,
        f"story-director-world-candidate:{novel_id}:{source_round_id}:{data.candidate_id}",
    )
    created = await create_entity(
        db,
        data.novel_id,
        {
            "entity_type": data.entity_type,
            "name": preview["label"],
            "summary": preview["description"] or None,
            "status": "candidate",
            "created_by": "scene_director",
            "content_json": {
                "director_source": {
                    "scene_id": str(data.scene_id),
                    "round_id": str(source_round_id),
                    "candidate_id": data.candidate_id,
                    "source_kind": preview["source_kind"],
                    "source_id": preview["source_id"],
                    "source_hash": preview["source_hash"],
                    "output_hash": preview["output_hash"],
                    "candidate_only": True,
                }
            },
        },
        candidate_id=str(world_candidate_id),
    )
    if str(created["id"]) != str(world_candidate_id) or created["status"] != "candidate":
        raise ConflictError("World 未保存为待审核候选")
    receipt = StorySceneDirectorCandidateTransfer(
        novel_id=novel_id,
        round_id=source_round_id,
        candidate_ref=data.candidate_id,
        scene_id=data.scene_id,
        source_hash=preview["source_hash"],
        output_hash=preview["output_hash"],
        entity_type=data.entity_type,
        world_candidate_id=world_candidate_id,
    )
    db.add(receipt)
    await db.flush()
    return _receipt(receipt, repeated=False)
