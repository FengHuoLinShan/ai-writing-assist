"""Persistent co-creation session service (ADR-0021).

Sessions bind one project-scoped creation object (project / World Bible page /
core entity / library topic) and persist terminal discussion records only:
author messages, completed model replies and author decisions.  Generation
turns bind their source confirmation and task receipt; candidate outcomes
reference the existing suggestion queue instead of duplicating it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.models.cocreation import (
    COCREATION_ACTIONS,
    COCREATION_CHECKPOINT_TARGET_TYPES,
    WorldCocreationMessage,
    WorldCocreationSession,
)
from modules.world.models.core import CoreEntity
from modules.world.models.library import WorldLibraryTopic
from modules.world.models.worldbuilding import (
    CreationSuggestion,
    WorldBiblePage,
    WorldBiblePageDraft,
)
from modules.world.schemas import (
    WorldCocreationChatRequest,
    WorldCocreationCheckpointAdvanceRequest,
    WorldCocreationMessageCreateRequest,
    WorldCocreationMessageResponse,
    WorldCocreationSessionCreateRequest,
    WorldCocreationSessionDetailResponse,
    WorldCocreationSessionResponse,
    WorldCocreationSessionUpdateRequest,
    WorldCocreationTurnTaskRequest,
    WorldDesignCheckpointPayload,
    WorldGenerationChatResponse,
    WorldGenerationRequestBase,
    WorldGenerationTaskResponse,
)
from modules.world.services.common import parse_uuid

logger = logging.getLogger(__name__)

SESSION_LIST_LIMIT = 100
MESSAGE_PAGE_LIMIT = 200
RECENT_MESSAGE_LIMIT = 40
MESSAGE_CONTENT_MAX = 100_000

_SOURCE_MODELS = {
    "world_bible_page": WorldBiblePage,
    "core_entity": CoreEntity,
    "world_library_topic": WorldLibraryTopic,
}

_OUTCOME_RESULT_DRAFT_TYPES = {"world_bible_page_draft"}


class WorldCocreationSessionService:
    """CRUD, pagination and generation binding for co-creation sessions."""

    async def _require_session(
        self,
        db: AsyncSession,
        novel_id: str,
        session_id: str,
        *,
        for_update: bool = False,
    ) -> WorldCocreationSession:
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(session_id, "session_id")
        statement = (
            select(WorldCocreationSession)
            .where(
                WorldCocreationSession.novel_id == nid,
                WorldCocreationSession.id == sid,
            )
            .execution_options(populate_existing=True)
        )
        if for_update:
            statement = statement.execution_options(
                populate_existing=True
            ).with_for_update()
        row = await db.scalar(statement)
        if row is None:
            raise NotFoundError("Co-creation session not found")
        return row

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

    async def _require_source(
        self,
        db: AsyncSession,
        nid: Any,
        source_kind: str,
        source_id: Any,
    ) -> None:
        models = [_SOURCE_MODELS[source_kind]]
        if source_kind == "world_bible_page":
            # 资料 source 同时接受正式页与其工作稿：两者都是作者可打开的资料对象。
            models.append(WorldBiblePageDraft)
        for model in models:
            count = await db.scalar(
                select(func.count())
                .select_from(model)
                .where(
                    model.novel_id == nid,
                    model.id == source_id,
                )
            )
            if count:
                return
        raise NotFoundError("Co-creation session source not found in this project")

    async def create(
        self,
        db: AsyncSession,
        data: WorldCocreationSessionCreateRequest,
    ) -> WorldCocreationSessionResponse:
        nid = parse_uuid(data.novel_id, "novel_id")
        source_id = parse_uuid(data.source.id, "source id") if data.source.id else None
        if data.source.kind != "project":
            await self._require_source(db, nid, data.source.kind, source_id)
        row = WorldCocreationSession(
            novel_id=nid,
            title=data.title.strip(),
            source_kind=data.source.kind,
            source_id=source_id,
            workflow_preset=data.workflow_preset,
            target_kind=data.target_kind,
            source_page_id=(
                parse_uuid(data.source_page_id, "source_page_id")
                if data.source_page_id
                else None
            ),
        )
        db.add(row)
        await db.flush()
        return WorldCocreationSessionResponse.model_validate(row)

    async def list_sessions(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        include_archived: bool = False,
        source_kind: str | None = None,
        source_id: str | None = None,
        workflow_preset: str | None = None,
        target_kind: str | None = None,
        search: str | None = None,
        limit: int = 20,
        skip: int = 0,
    ) -> tuple[list[WorldCocreationSessionResponse], int]:
        nid = parse_uuid(novel_id, "novel_id")
        conditions = [WorldCocreationSession.novel_id == nid]
        if not include_archived:
            conditions.append(WorldCocreationSession.status == "active")
        if source_kind:
            conditions.append(WorldCocreationSession.source_kind == source_kind)
        if workflow_preset:
            conditions.append(WorldCocreationSession.workflow_preset == workflow_preset)
        if target_kind:
            conditions.append(WorldCocreationSession.target_kind == target_kind)
        if search:
            conditions.append(
                WorldCocreationSession.title.icontains(search.strip(), autoescape=True)
            )
        if source_id:
            conditions.append(
                WorldCocreationSession.source_id == parse_uuid(source_id, "source_id")
            )
        total = await db.scalar(
            select(func.count()).select_from(WorldCocreationSession).where(*conditions)
        )
        rows = (
            await db.scalars(
                select(WorldCocreationSession)
                .where(*conditions)
                .order_by(
                    func.coalesce(
                        WorldCocreationSession.last_message_at,
                        WorldCocreationSession.created_at,
                    ).desc(),
                    WorldCocreationSession.created_at.desc(),
                    WorldCocreationSession.id.desc(),
                )
                .offset(skip)
                .limit(limit)
            )
        ).all()
        return [WorldCocreationSessionResponse.model_validate(row) for row in rows], (
            total or 0
        )

    async def get_detail(
        self,
        db: AsyncSession,
        novel_id: str,
        session_id: str,
    ) -> WorldCocreationSessionDetailResponse:
        session = await self._require_session(db, novel_id, session_id)
        messages, total = await self.recent_messages(db, session)
        from infrastructure.tasks.facade import find_session_operation

        operation = await find_session_operation(
            db,
            novel_id=novel_id,
            task_type="world_cocreation_turn",
            session_id=session_id,
        )
        return WorldCocreationSessionDetailResponse(
            session=WorldCocreationSessionResponse.model_validate(session),
            messages=messages,
            message_total=total,
            last_operation=WorldGenerationTaskResponse(
                task_id=operation.task_id, status=operation.status
            )
            if operation
            else None,
        )

    async def update_session(
        self,
        db: AsyncSession,
        novel_id: str,
        session_id: str,
        data: WorldCocreationSessionUpdateRequest,
    ) -> WorldCocreationSessionResponse:
        row = await self._require_session(db, novel_id, session_id)
        if data.title is not None:
            row.title = data.title.strip()
        if data.archived is True:
            row.status = "archived"
        elif data.archived is False:
            row.status = "active"
        await db.flush()
        return WorldCocreationSessionResponse.model_validate(row)

    async def _outcome_states(
        self,
        db: AsyncSession,
        nid: Any,
        messages: list[WorldCocreationMessage],
    ) -> dict[Any, str]:
        suggestion_ids = {
            message.outcome_suggestion_id
            for message in messages
            if message.outcome_suggestion_id is not None
        }
        if not suggestion_ids:
            return {}
        rows = await db.scalars(
            select(CreationSuggestion).where(
                CreationSuggestion.novel_id == nid,
                CreationSuggestion.id.in_(tuple(suggestion_ids)),
            )
        )
        states: dict[Any, str] = {}
        for suggestion in rows:
            if suggestion.status == "rejected":
                state = "rejected"
            elif suggestion.status == "accepted":
                result_type = (suggestion.result_ref_json or {}).get("type")
                state = (
                    "saved_draft"
                    if result_type in _OUTCOME_RESULT_DRAFT_TYPES
                    else "adopted"
                )
            else:
                state = "pending_review"
            states[suggestion.id] = state
        return states

    def _message_responses(
        self,
        messages: list[WorldCocreationMessage],
        states: dict[Any, str],
    ) -> list[WorldCocreationMessageResponse]:
        items = []
        for message in messages:
            item = WorldCocreationMessageResponse.model_validate(message)
            if message.outcome_suggestion_id is not None:
                item.outcome_state = states.get(message.outcome_suggestion_id)
            items.append(item)
        return items

    async def list_messages(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        session_id: str,
        limit: int = 50,
        skip: int = 0,
        search: str | None = None,
        around_message_id: str | None = None,
    ) -> tuple[list[WorldCocreationMessageResponse], int, int]:
        session = await self._require_session(db, novel_id, session_id)
        conditions = [WorldCocreationMessage.session_id == session.id]
        if around_message_id:
            anchor = await db.scalar(
                select(WorldCocreationMessage).where(
                    *conditions,
                    WorldCocreationMessage.id
                    == parse_uuid(around_message_id, "message_id"),
                )
            )
            if anchor is None:
                raise NotFoundError("历史消息不属于当前会话")
            before = await db.scalar(
                select(func.count())
                .select_from(WorldCocreationMessage)
                .where(
                    *conditions,
                    or_(
                        WorldCocreationMessage.created_at < anchor.created_at,
                        and_(
                            WorldCocreationMessage.created_at == anchor.created_at,
                            WorldCocreationMessage.id < anchor.id,
                        ),
                    ),
                )
            )
            skip = max(0, int(before or 0) - limit // 2)
            search = None
        if search:
            escaped = (
                search.strip()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            conditions.append(WorldCocreationMessage.content.ilike(f"%{escaped}%"))
        total = await db.scalar(
            select(func.count()).select_from(WorldCocreationMessage).where(*conditions)
        )
        rows = (
            await db.scalars(
                select(WorldCocreationMessage)
                .where(*conditions)
                .order_by(
                    WorldCocreationMessage.created_at.asc(),
                    WorldCocreationMessage.id.asc(),
                )
                .offset(skip)
                .limit(limit)
            )
        ).all()
        states = await self._outcome_states(db, session.novel_id, list(rows))
        return self._message_responses(list(rows), states), (total or 0), skip

    async def recent_messages(
        self,
        db: AsyncSession,
        session: WorldCocreationSession,
        limit: int = RECENT_MESSAGE_LIMIT,
    ) -> tuple[list[WorldCocreationMessageResponse], int]:
        total = await db.scalar(
            select(func.count())
            .select_from(WorldCocreationMessage)
            .where(WorldCocreationMessage.session_id == session.id)
        )
        newest = (
            await db.scalars(
                select(WorldCocreationMessage)
                .where(WorldCocreationMessage.session_id == session.id)
                .order_by(
                    WorldCocreationMessage.created_at.desc(),
                    WorldCocreationMessage.id.desc(),
                )
                .limit(limit)
            )
        ).all()
        rows = list(reversed(list(newest)))
        states = await self._outcome_states(db, session.novel_id, rows)
        return self._message_responses(rows, states), (total or 0)

    async def append_message(
        self,
        db: AsyncSession,
        session: WorldCocreationSession,
        *,
        role: str,
        content: str,
        kind: str = "message",
        action: str | None = None,
        context_confirmation_id: str | None = None,
        task_id: str | None = None,
        outcome_suggestion_id: str | None = None,
        outcome_kind: str | None = None,
    ) -> WorldCocreationMessage:
        row = WorldCocreationMessage(
            novel_id=session.novel_id,
            session_id=session.id,
            role=role,
            kind=kind,
            action=action,
            content=content[:MESSAGE_CONTENT_MAX],
            context_confirmation_id=(
                parse_uuid(context_confirmation_id, "context_confirmation_id")
                if context_confirmation_id
                else None
            ),
            task_id=parse_uuid(task_id, "task_id") if task_id else None,
            outcome_suggestion_id=(
                parse_uuid(outcome_suggestion_id, "outcome_suggestion_id")
                if outcome_suggestion_id
                else None
            ),
            outcome_kind=outcome_kind,
        )
        db.add(row)
        session.last_message_at = datetime.now(UTC)
        await db.flush()
        return row

    async def create_message(
        self,
        db: AsyncSession,
        novel_id: str,
        session_id: str,
        data: WorldCocreationMessageCreateRequest,
    ) -> WorldCocreationMessageResponse:
        session = await self._require_session(db, novel_id, session_id)
        row = await self.append_message(
            db,
            session,
            role="author",
            content=data.content,
            kind=data.kind,
            action=data.action,
        )
        item = WorldCocreationMessageResponse.model_validate(row)
        return item

    async def advance_checkpoint(
        self,
        db: AsyncSession,
        novel_id: str,
        session_id: str,
        data: WorldCocreationCheckpointAdvanceRequest,
    ) -> WorldCocreationSessionResponse:
        session = await self._require_session(db, novel_id, session_id, for_update=True)
        suggestion_id = parse_uuid(
            data.checkpoint_suggestion_id,
            "checkpoint_suggestion_id",
        )
        suggestion = await db.scalar(
            select(CreationSuggestion).where(
                CreationSuggestion.novel_id == session.novel_id,
                CreationSuggestion.id == suggestion_id,
            )
        )
        if suggestion is None:
            raise NotFoundError("Checkpoint suggestion not found in this project")
        if suggestion.target_type not in COCREATION_CHECKPOINT_TARGET_TYPES:
            raise ConflictError(
                "Only a world design/core checkpoint can advance the session pointer",
                code="checkpoint_target_mismatch",
            )
        expected = (
            parse_uuid(data.expected_checkpoint_id, "expected_checkpoint_id")
            if data.expected_checkpoint_id
            else None
        )
        if session.current_checkpoint_id != expected:
            raise ConflictError(
                "checkpoint_pointer_drift: 会话基线已变化，请重新核对本轮提案",
                code="checkpoint_pointer_drift",
            )
        session.current_checkpoint_id = suggestion.id
        payload = suggestion.payload_json or {}
        if payload.get("round_no") is not None:
            session.checkpoint_round = int(payload["round_no"])
        elif data.round_no is not None:
            session.checkpoint_round = data.round_no
        if payload.get("depth") in {"seed", "candidate", "instance"}:
            session.checkpoint_depth = payload["depth"]
        elif data.depth is not None:
            session.checkpoint_depth = data.depth
        changes = (payload.get("world_state") or {}).get("change_log") or []
        await self.append_message(
            db,
            session,
            role="author",
            kind="decision",
            content=(changes[-1].get("summary") if changes else None)
            or f"保存第 {session.checkpoint_round} 轮阶段成果",
            action=payload.get("action"),
            outcome_suggestion_id=str(suggestion.id),
            outcome_kind=suggestion.target_type,
        )
        await db.flush()
        return WorldCocreationSessionResponse.model_validate(session)

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

    async def chat(
        self,
        db: AsyncSession,
        session_id: str,
        data: WorldCocreationChatRequest,
    ) -> WorldGenerationChatResponse:
        """Run one confirmed chat turn and persist the completed turn."""
        from modules.world.services.worldbuilding.world_generation_center_service import (
            WorldGenerationCenterService,
        )

        session = await self._require_session(db, data.novel_id, session_id)
        data = data.model_copy(update={"session_id": session_id})
        result = await WorldGenerationCenterService().chat(db, data)
        last_user = next(
            (message for message in reversed(data.messages) if message.role == "user"),
            None,
        )
        if last_user is not None:
            await self.append_message(
                db,
                session,
                role="author",
                content=last_user.content,
                action=data.session_action,
                context_confirmation_id=data.context_confirmation_id,
            )
        await self.append_message(
            db,
            session,
            role="assistant",
            content=result.reply,
            context_confirmation_id=data.context_confirmation_id,
        )
        return result

    async def record_generation_outcome(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        session_id: str,
        action: str | None,
        author_content: str | None,
        task_id: str | None,
        context_confirmation_id: str | None,
        outcome_suggestion_id: str,
        outcome_label: str,
    ) -> None:
        """Append the completed async candidate turn into its session."""
        try:
            session = await self._require_session(db, novel_id, session_id)
        except NotFoundError as exc:
            logger.warning(
                "Skip co-creation outcome recording for missing session %s: %s",
                session_id,
                exc,
            )
            return
        if author_content:
            await self.append_message(
                db,
                session,
                role="author",
                content=author_content,
                action=action if action in COCREATION_ACTIONS else None,
                context_confirmation_id=context_confirmation_id,
            )
        await self.append_message(
            db,
            session,
            role="assistant",
            content=f"已生成候选《{outcome_label}》，已进入待审阅。",
            context_confirmation_id=context_confirmation_id,
            task_id=task_id,
            outcome_suggestion_id=outcome_suggestion_id,
            outcome_kind="candidate",
        )
