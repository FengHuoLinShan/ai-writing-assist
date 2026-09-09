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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError
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
    WorldGenerationChatResponse,
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
    ) -> WorldCocreationSession:
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(session_id, "session_id")
        row = await db.scalar(
            select(WorldCocreationSession).where(
                WorldCocreationSession.novel_id == nid,
                WorldCocreationSession.id == sid,
            )
        )
        if row is None:
            raise NotFoundError("Co-creation session not found")
        return row

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
                select(func.count()).select_from(model).where(
                    model.novel_id == nid,
                    model.id == source_id,
                )
            )
            if count:
                return
        raise NotFoundError(
            "Co-creation session source not found in this project"
        )

    async def create(
        self,
        db: AsyncSession,
        data: WorldCocreationSessionCreateRequest,
    ) -> WorldCocreationSessionResponse:
        nid = parse_uuid(data.novel_id, "novel_id")
        source_id = (
            parse_uuid(data.source.id, "source id") if data.source.id else None
        )
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
        limit: int = 20,
        skip: int = 0,
    ) -> tuple[list[WorldCocreationSessionResponse], int]:
        nid = parse_uuid(novel_id, "novel_id")
        conditions = [WorldCocreationSession.novel_id == nid]
        if not include_archived:
            conditions.append(WorldCocreationSession.status == "active")
        if source_kind:
            conditions.append(WorldCocreationSession.source_kind == source_kind)
        if source_id:
            conditions.append(
                WorldCocreationSession.source_id
                == parse_uuid(source_id, "source_id")
            )
        total = await db.scalar(
            select(func.count()).select_from(WorldCocreationSession).where(
                *conditions
            )
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
        return WorldCocreationSessionDetailResponse(
            session=WorldCocreationSessionResponse.model_validate(session),
            messages=messages,
            message_total=total,
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
    ) -> tuple[list[WorldCocreationMessageResponse], int]:
        session = await self._require_session(db, novel_id, session_id)
        conditions = [WorldCocreationMessage.session_id == session.id]
        if search:
            escaped = (
                search.strip()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            conditions.append(
                WorldCocreationMessage.content.ilike(f"%{escaped}%")
            )
        total = await db.scalar(
            select(func.count()).select_from(WorldCocreationMessage).where(
                *conditions
            )
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
        return self._message_responses(list(rows), states), (total or 0)

    async def recent_messages(
        self,
        db: AsyncSession,
        session: WorldCocreationSession,
        limit: int = RECENT_MESSAGE_LIMIT,
    ) -> tuple[list[WorldCocreationMessageResponse], int]:
        total = await db.scalar(
            select(func.count()).select_from(WorldCocreationMessage).where(
                WorldCocreationMessage.session_id == session.id
            )
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
        session = await self._require_session(db, novel_id, session_id)
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
                "Only a world design/core checkpoint can advance the session "
                "pointer",
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
        if data.round_no is not None:
            session.checkpoint_round = data.round_no
        if data.depth is not None:
            session.checkpoint_depth = data.depth
        await db.flush()
        return WorldCocreationSessionResponse.model_validate(session)

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
        result = await WorldGenerationCenterService().chat(db, data)
        last_user = next(
            (
                message
                for message in reversed(data.messages)
                if message.role == "user"
            ),
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
        except Exception as exc:
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
