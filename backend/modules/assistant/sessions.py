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

from core.container import get
from core.errors import ConflictError, NotFoundError
from modules.assistant.contracts import (
    WorldCocreationCheckpointAdvanceRequest,
    WorldCocreationMessageCreateRequest,
    WorldCocreationMessageResponse,
    WorldCocreationSessionCreateRequest,
    WorldCocreationSessionDetailResponse,
    WorldCocreationSessionResponse,
    WorldCocreationSessionUpdateRequest,
)
from modules.assistant.session_models import (
    COCREATION_ACTIONS,
)
from modules.assistant.session_models import (
    AssistantMessage as WorldCocreationMessage,
)
from modules.assistant.session_models import (
    AssistantSession as WorldCocreationSession,
)
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)

SESSION_LIST_LIMIT = 100
MESSAGE_PAGE_LIMIT = 200
RECENT_MESSAGE_LIMIT = 40
MESSAGE_CONTENT_MAX = 100_000


class AssistantSessionService:
    """CRUD, pagination and generation binding for co-creation sessions."""

    async def _require_session(
        self,
        db: AsyncSession,
        novel_id: str,
        session_id: str,
        *,
        lock: bool = False,
    ) -> WorldCocreationSession:
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(session_id, "session_id")
        query = select(WorldCocreationSession).where(
            WorldCocreationSession.novel_id == nid,
            WorldCocreationSession.id == sid,
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = await db.scalar(query)
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
        await get("world.assistant.require_source")(db, nid, source_kind, source_id)

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
        return await get("world.assistant.outcome_states")(db, nid, suggestion_ids)

    async def _message_responses(
        self,
        db: AsyncSession,
        messages: list[WorldCocreationMessage],
        states: dict[Any, str],
    ) -> list[WorldCocreationMessageResponse]:
        from modules.assistant.models import AssistantRun

        runs = {}
        if messages:
            runs = dict(
                (
                    await db.execute(
                        select(AssistantRun.task_id, AssistantRun.id).where(
                            AssistantRun.novel_id == messages[0].novel_id,
                            AssistantRun.session_id == messages[0].session_id,
                            AssistantRun.task_id.in_(
                                [m.task_id for m in messages if m.task_id]
                            ),
                        )
                    )
                ).all()
            )
        items = []
        for message in messages:
            item = WorldCocreationMessageResponse.model_validate(message)
            if message.task_id in runs:
                item.assistant_run_id = str(runs[message.task_id])
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
        conditions = [
            WorldCocreationMessage.session_id == session.id,
            WorldCocreationMessage.novel_id == session.novel_id,
        ]
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
        return await self._message_responses(db, list(rows), states), (total or 0)

    async def recent_messages(
        self,
        db: AsyncSession,
        session: WorldCocreationSession,
        limit: int = RECENT_MESSAGE_LIMIT,
    ) -> tuple[list[WorldCocreationMessageResponse], int]:
        total = await db.scalar(
            select(func.count())
            .select_from(WorldCocreationMessage)
            .where(
                WorldCocreationMessage.session_id == session.id,
                WorldCocreationMessage.novel_id == session.novel_id,
            )
        )
        newest = (
            await db.scalars(
                select(WorldCocreationMessage)
                .where(
                    WorldCocreationMessage.session_id == session.id,
                    WorldCocreationMessage.novel_id == session.novel_id,
                )
                .order_by(
                    WorldCocreationMessage.created_at.desc(),
                    WorldCocreationMessage.id.desc(),
                )
                .limit(limit)
            )
        ).all()
        rows = list(reversed(list(newest)))
        states = await self._outcome_states(db, session.novel_id, rows)
        return await self._message_responses(db, rows, states), (total or 0)

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
        session = await self._require_session(db, novel_id, session_id, lock=True)
        suggestion_id = parse_uuid(
            data.checkpoint_suggestion_id,
            "checkpoint_suggestion_id",
        )
        await get("world.assistant.require_checkpoint")(
            db, session.novel_id, suggestion_id
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
        session.current_checkpoint_id = suggestion_id
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
        data: Any,
    ) -> Any:
        """Run one confirmed chat turn and persist the completed turn."""
        from modules.assistant.service import AssistantService, get_settings

        if get_settings().assistant_enabled:
            return await AssistantService().submit_cocreation(db, data, session_id)
        session = await self._require_session(db, data.novel_id, session_id)
        result = await get("world.assistant.chat")(db, data)
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
        outcome_kind: str = "candidate",
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
            content=f"已保存阶段成果《{outcome_label}》，可继续深化；尚未正式采用。"
            if outcome_kind == "checkpoint"
            else f"已生成候选《{outcome_label}》，已进入待审阅。",
            context_confirmation_id=context_confirmation_id,
            task_id=task_id,
            outcome_suggestion_id=outcome_suggestion_id,
            outcome_kind=outcome_kind,
        )
