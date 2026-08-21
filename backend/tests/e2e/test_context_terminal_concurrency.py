from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from modules.evidence.compilation.models import (
    ContextConfirmation,
    ContextConfirmationAssetRef,
    ContextSnapshot,
)
from modules.evidence.compilation.repositories import ContextConfirmationRepository
from modules.evidence.contracts import ContextSnapshotRequest
from modules.evidence.facade import (
    attach_result_ref,
    fail_context_snapshot,
    open_context_snapshot,
    succeed_context_snapshot,
)
from modules.project.models import Project
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


def _snapshot_request(novel_id: str) -> ContextSnapshotRequest:
    return ContextSnapshotRequest(
        novel_id=novel_id,
        phase="e2e",
        operation="context_terminal_concurrency",
        prompt_name="context_terminal_concurrency",
        model="deterministic-test",
        compile_options={},
        included_asset_ids={},
        context_summary={},
        section_metadata={},
        token_metadata={},
    )


async def test_confirmation_result_binding_is_project_scoped() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=2, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_id = uuid.uuid4()
    other_id = uuid.uuid4()

    try:
        async with sessions.begin() as setup_db:
            setup_db.add_all(
                [
                    Project(id=owner_id, title="context confirmation owner"),
                    Project(id=other_id, title="context confirmation other"),
                ]
            )
            await setup_db.flush()
            confirmation = await ContextConfirmationRepository().create(
                setup_db,
                novel_id=owner_id,
                action="writing.generate",
                task="project isolation",
                scope="project",
                context_mode="canonical",
                include_pending_objects=False,
                excluded_asset_ids={},
                selected_asset_ids={},
                user_note=None,
                compile_options={},
                warnings=[],
            )
            confirmation_id = str(confirmation.id)

        async with sessions.begin() as wrong_db:
            with pytest.raises(ValueError, match="not found"):
                await attach_result_ref(
                    wrong_db,
                    novel_id=str(other_id),
                    confirmation_id=confirmation_id,
                    result_type="task",
                    result_id="must-not-bind",
                )

        async def bind_once(result_id: str):
            async with sessions.begin() as db:
                return await attach_result_ref(
                    db,
                    novel_id=str(owner_id),
                    confirmation_id=confirmation_id,
                    result_type="task",
                    result_id=result_id,
                )

        await asyncio.gather(bind_once("task-1"), bind_once("task-2"))

        async with sessions() as verify_db:
            stored = await verify_db.get(
                ContextConfirmation,
                uuid.UUID(confirmation_id),
            )
            assert stored is not None
            assert {(ref["type"], ref["id"]) for ref in stored.result_refs} == {
                ("task", "task-1"),
                ("task", "task-2"),
            }
            ref_count = await verify_db.scalar(
                select(func.count(ContextConfirmationAssetRef.confirmation_id)).where(
                    ContextConfirmationAssetRef.confirmation_id
                    == uuid.UUID(confirmation_id)
                )
            )
            assert ref_count == 2
    finally:
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(
                delete(Project).where(Project.id.in_([owner_id, other_id]))
            )
        await engine.dispose()


async def test_competing_snapshot_terminals_have_one_winner() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()

    try:
        async with sessions.begin() as setup_db:
            setup_db.add(Project(id=novel_id, title="snapshot terminal concurrency"))
            await setup_db.flush()
            snapshot = await open_context_snapshot(
                setup_db,
                _snapshot_request(str(novel_id)),
            )
            snapshot_id = snapshot.id

        async def succeed_once():
            async with sessions.begin() as db:
                return await succeed_context_snapshot(
                    db,
                    novel_id=str(novel_id),
                    snapshot_id=snapshot_id,
                    result_refs=[{"type": "scene", "id": "scene-1"}],
                )

        async def fail_once():
            async with sessions.begin() as db:
                return await fail_context_snapshot(
                    db,
                    novel_id=str(novel_id),
                    snapshot_id=snapshot_id,
                    error_kind="provider_error",
                    error_message="deterministic failure",
                )

        results = await asyncio.gather(
            succeed_once(),
            fail_once(),
            return_exceptions=True,
        )
        winners = [result for result in results if not isinstance(result, Exception)]
        losers = [result for result in results if isinstance(result, Exception)]
        assert len(winners) == 1
        assert len(losers) == 1
        assert isinstance(losers[0], ValueError)
        assert "already finalized" in str(losers[0])

        async with sessions() as verify_db:
            stored = await verify_db.get(ContextSnapshot, uuid.UUID(snapshot_id))
            assert stored is not None
            assert stored.status in {"succeeded", "failed"}
            if stored.status == "succeeded":
                assert stored.result_refs == [{"type": "scene", "id": "scene-1"}]
                assert stored.error_kind is None
            else:
                assert stored.result_refs == []
                assert stored.error_kind == "provider_error"
    finally:
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()
