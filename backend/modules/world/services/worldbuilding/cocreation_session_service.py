"""World generation over the shared Assistant discussion records."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.assistant.facade import AssistantSessionService
from modules.world.models.cocreation import WorldCocreationMessage
from modules.world.models.worldbuilding import CreationSuggestion
from modules.world.schemas import (
    WorldCocreationTurnTaskRequest,
    WorldDesignCheckpointPayload,
    WorldGenerationRequestBase,
    WorldGenerationTaskResponse,
)


class WorldCocreationSessionService(AssistantSessionService):
    async def generation_context(
        self, db: AsyncSession, data: WorldGenerationRequestBase
    ) -> dict:
        """Resolve durable author state and server-owned history."""
        if not data.session_id:
            if (
                data.selected_history_ids
                or data.expected_checkpoint_id
                or data.world_state_target_id
            ):
                raise ValidationError("历史与阶段成果必须绑定当前会话")
            return {}
        session = await self._require_session(db, data.novel_id, data.session_id)
        if session.status != "active":
            raise ConflictError("请先恢复已归档的会话")
        if session.workflow_preset != data.workflow_preset or (
            session.target_kind and session.target_kind != data.target.kind
        ):
            raise ConflictError("会话与当前创作目标不一致")
        if session.source_page_id and session.source_page_id != getattr(
            data.source_context, "page_id", None
        ):
            raise ConflictError("会话与当前来源页面不一致")
        if session.source_kind != "project":
            await self._require_source(
                db, session.novel_id, session.source_kind, session.source_id
            )
        current = (
            str(session.current_checkpoint_id) if session.current_checkpoint_id else None
        )
        if current != data.expected_checkpoint_id:
            raise ConflictError(
                "会话的阶段成果已变化，请重新核对", code="checkpoint_pointer_drift"
            )
        checkpoint = None
        if current:
            row = await db.scalar(
                select(CreationSuggestion).where(
                    CreationSuggestion.id == session.current_checkpoint_id,
                    CreationSuggestion.novel_id == session.novel_id,
                )
            )
            if row is None:
                raise NotFoundError("当前阶段成果不可用")
            if row.target_type == "world_design_checkpoint":
                checkpoint = WorldDesignCheckpointPayload.model_validate(
                    row.payload_json
                ).model_dump(mode="json", by_alias=True)
                if data.scene_id:
                    raise ValidationError(
                        "完整世界模型尚无场景可见性投影，请取消场景截止后进行作者世界推演"
                    )
            else:
                checkpoint = dict(row.payload_json)
        recent, _ = await self.recent_messages(db, session)
        if any(item.role == "user" for item in data.messages):
            recent = recent[-39:]
        selected_ids = set(data.selected_history_ids)
        selected = (
            list(
                (
                    await db.scalars(
                        select(WorldCocreationMessage)
                        .where(
                            WorldCocreationMessage.session_id == session.id,
                            WorldCocreationMessage.id.in_(selected_ids),
                        )
                        .order_by(
                            WorldCocreationMessage.created_at, WorldCocreationMessage.id
                        )
                    )
                ).all()
            )
            if selected_ids
            else []
        )
        if {item.id for item in selected} != selected_ids:
            raise NotFoundError("选中的历史不属于当前会话或已不可用")
        recent_ids = {item.id for item in recent}
        history = [
            {"id": str(item.id), "role": item.role, "content": item.content}
            for item in selected
            if str(item.id) not in recent_ids
        ]
        conversation = [
            {"id": item.id, "role": item.role, "content": item.content} for item in recent
        ]
        import json

        result = {
            "checkpoint": checkpoint,
            "selected_history": history,
            "recent_messages": conversation,
        }
        workspace = dict(checkpoint or {})
        if workspace.get("world_state"):
            workspace.pop("world_core", None)
            workspace.pop("decision_state", None)
        if data.world_state_sections and workspace.get("world_state"):
            keep = {"project", "authority", *data.world_state_sections}
            workspace["world_state"] = {
                key: value
                for key, value in workspace["world_state"].items()
                if key in keep
            }
            workspace.pop("world_core", None)
        result["model_context"] = {"checkpoint": workspace, "selected_history": history}
        if data.world_state_target_id:
            state = (checkpoint or {}).get("world_state") or {}
            entry = next(
                (
                    item
                    for key in ("rules", "actors", "places", "institutions", "history")
                    for item in state.get(key, [])
                    if item["id"] == data.world_state_target_id
                ),
                None,
            )
            if entry is None or entry.get("status") == "deprecated":
                raise ValidationError("选定的世界条目已不可用，请重新选择")
            result["model_context"]["author_selected_entry"] = entry
        if (
            len(
                json.dumps(
                    {
                        "workspace": result["model_context"],
                        "recent": conversation,
                        "message": [
                            item.model_dump()
                            for item in data.messages
                            if item.role == "user"
                        ][-1:],
                    },
                    ensure_ascii=False,
                )
            )
            > 80_000
        ):
            raise ValidationError(
                "本轮资料超出可用范围，请选择更少的世界面向、减少选入历史；未裁掉任何长期决定"
            )
        return result

    async def enqueue_turn(
        self, db: AsyncSession, data: WorldCocreationTurnTaskRequest
    ) -> WorldGenerationTaskResponse:
        from infrastructure.tasks.facade import enqueue_operation_task, get_operation_task
        from modules.evidence.facade import attach_result_ref, require_fresh_confirmation
        from modules.project.facade import build_project_llm_execution_snapshot

        payload = data.model_dump(mode="json", exclude={"operation_id"})
        existing = await get_operation_task(
            db,
            operation_id=str(data.operation_id),
            task_type="world_cocreation_turn",
            novel_id=data.novel_id,
            request_payload=payload,
        )
        if existing:
            return WorldGenerationTaskResponse(
                task_id=existing.task_id, status=existing.status
            )
        await require_fresh_confirmation(
            db,
            novel_id=data.novel_id,
            action="world.generation.chat",
            confirmation_id=data.context_confirmation_id,
        )
        await self.generation_context(db, data)
        snapshot = await build_project_llm_execution_snapshot(db, data.novel_id)
        receipt = await enqueue_operation_task(
            db,
            operation_id=str(data.operation_id),
            task_type="world_cocreation_turn",
            novel_id=data.novel_id,
            request_payload=payload,
            meta={**payload, "llm_execution_snapshot": snapshot},
        )
        await db.flush()
        if not receipt.reused:
            await attach_result_ref(
                db,
                novel_id=data.novel_id,
                confirmation_id=data.context_confirmation_id,
                result_type="task",
                result_id=receipt.task_id,
                status="running",
            )
        return WorldGenerationTaskResponse(task_id=receipt.task_id, status=receipt.status)
