"""World-owned stage artifacts linked to the server-bound assistant discussion."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.errors import ConflictError
from modules.assistant.contracts import (
    AssistantOperation,
    WorldCocreationCheckpointAdvanceRequest,
)
from modules.assistant.facade import AssistantSessionService, run_discussion_scope
from modules.evidence.contracts import VisibilityContextContract
from modules.evidence.facade import inspect_novel_target
from modules.world.schemas import (
    GeneratedWorldCoreConvergence,
    GeneratedWorldGenerationDecisionState,
    WorldCoreCheckpointDecision,
    WorldCoreCheckpointPayload,
    WorldCoreCheckpointSaveRequest,
    WorldDesignCheckpointPayload,
    WorldDesignCheckpointSaveRequest,
    WorldDesignWorldState,
)
from modules.world.services.worldbuilding.adoption_package_service import (
    WorldAdoptionPackageService,
)


class SaveCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["expand", "connect", "pressure", "consolidate"] = "consolidate"
    depth: Literal["seed", "candidate", "instance"] = "seed"
    decision_state: GeneratedWorldGenerationDecisionState | None = None
    world_core: GeneratedWorldCoreConvergence | None = None
    decisions: list[WorldCoreCheckpointDecision] = Field(
        default_factory=list, max_length=64
    )
    world_state: WorldDesignWorldState | None = None

    @model_validator(mode="after")
    def actual_content(self):
        if not (
            self.decision_state or self.world_core or self.decisions or self.world_state
        ):
            raise ValueError("阶段成果需要实际的讨论结果或作者决定")
        return self


async def _preview(db, novel_id, args, *, context=None):
    scope = await run_discussion_scope(db, novel_id, context.run_id, context.owner_id)
    if scope["checkpoint_id"] in {
        value.rsplit(":", 1)[-1] for value in context.work.excluded_targets
    }:
        raise ConflictError("原阶段成果已被排除，不能静默继承")
    if any(set(item.source_keys) - set(scope["evidence_ids"]) for item in args.decisions):
        raise ConflictError("决定引用了本轮未查证的来源")
    previous = {}
    if scope["checkpoint_id"]:
        inspected = await inspect_novel_target(
            db,
            novel_id=novel_id,
            target_ref={
                "target_type": "world_checkpoint",
                "target_id": scope["checkpoint_id"],
            },
            content_mode="working",
            visibility=VisibilityContextContract(
                mode="author",
                cutoff_chapter=context.work.chapter_index
                if context.work.scope == "current"
                else None,
                cutoff_scene_id=str(context.work.scene_id)
                if context.work.scope == "current" and context.work.scene_id
                else None,
            ),
        )
        if not inspected.get("visible"):
            raise ConflictError("当前范围不能继承完整阶段成果，请在原讨论工作台核对")
        previous = inspected["item"]["payload"]
    decisions = {item["item_key"]: item for item in previous.get("decisions", [])}
    decisions.update(
        {item.item_key: item.model_dump(mode="json") for item in args.decisions}
    )
    payload = {
        "round_no": scope["round_no"] + 1,
        "action": args.action,
        "parent_checkpoint_id": scope["checkpoint_id"],
        "source_manifest_hash": scope["source_manifest_hash"],
        "seeds": previous.get("seeds", []),
        "decisions": list(decisions.values()),
        "decision_state": args.decision_state or previous.get("decision_state"),
        "world_core": args.world_core or previous.get("world_core"),
    }
    world_state = args.world_state or previous.get("world_state")
    checkpoint = (
        WorldDesignCheckpointPayload(
            schema_version="world_design_checkpoint.v1",
            depth=args.depth,
            world_state=world_state,
            **payload,
        )
        if world_state
        else WorldCoreCheckpointPayload(
            schema_version="world_core_checkpoint.v1", **payload
        )
    )
    return {
        "target_key": f"discussion:{scope['session_id']}",
        "title": "保存当前讨论的阶段成果",
        "scope": scope,
        "checkpoint": checkpoint.model_dump(mode="json"),
        "after": checkpoint.model_dump(mode="json", exclude_none=True),
        "effect": "保存可继续深化的讨论快照并推进当前讨论；不是正式设定采用",
    }


async def _save(db, novel_id, args, preview, *, context=None):
    # Lock the pointer before saving an artifact; drift cannot leave a new orphan
    # checkpoint or overwrite another window's successfully advanced discussion.
    scope = await run_discussion_scope(
        db, novel_id, context.run_id, context.owner_id, lock=True
    )
    if (
        scope != preview["scope"]
        or await _preview(db, novel_id, args, context=context) != preview
    ):
        raise ConflictError("讨论的阶段成果或引用已变化，请重新查看方案")
    payload = preview["checkpoint"]
    service = WorldAdoptionPackageService()
    if payload["schema_version"] == "world_design_checkpoint.v1":
        result = await service.save_design_checkpoint(
            db,
            WorldDesignCheckpointSaveRequest(
                novel_id=novel_id,
                checkpoint=WorldDesignCheckpointPayload.model_validate(payload),
            ),
        )
    else:
        result = await service.save_checkpoint(
            db,
            WorldCoreCheckpointSaveRequest(
                novel_id=novel_id,
                checkpoint=WorldCoreCheckpointPayload.model_validate(payload),
            ),
        )
    sessions = AssistantSessionService()
    await sessions.advance_checkpoint(
        db,
        novel_id,
        scope["session_id"],
        WorldCocreationCheckpointAdvanceRequest(
            novel_id=novel_id,
            checkpoint_suggestion_id=result.id,
            expected_checkpoint_id=scope["checkpoint_id"],
            round_no=payload["round_no"],
            depth=args.depth,
        ),
    )
    await sessions.record_generation_outcome(
        db,
        novel_id=novel_id,
        session_id=scope["session_id"],
        action=args.action,
        author_content=None,
        task_id=scope["task_id"],
        context_confirmation_id=str(context.work.context_confirmation_id)
        if context.work.context_confirmation_id
        else None,
        outcome_suggestion_id=result.id,
        outcome_label="本轮世界讨论",
        outcome_kind="checkpoint",
    )
    return {
        "type": "world_checkpoint",
        "id": result.id,
        "label": "已保存当前讨论阶段成果",
    }


OPERATIONS = {
    "world.save_checkpoint": AssistantOperation(
        "保存并继续世界讨论阶段成果", SaveCheckpoint, _preview, _save
    ),
}
