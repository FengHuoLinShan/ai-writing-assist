"""Generation context snapshot transaction-boundary tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.evidence.compilation.models import ContextSnapshot
from modules.evidence.compilation.services.compiled_context import CompiledContext


async def _empty_compilation(*_args, **_kwargs) -> CompiledContext:
    return CompiledContext(sections=[], budget_tokens=4000)


@pytest.mark.asyncio
async def test_generation_snapshot_lifecycle_survives_caller_rollbacks(
    test_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Engine-bound generation snapshots commit independently of business work."""
    from modules.evidence.compilation import facade as context_facade

    monkeypatch.setattr(
        context_facade._compiler,
        "compile_with_tiers",
        _empty_compilation,
    )
    sessions = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    novel_id = str(uuid.uuid4())
    snapshot_ids: list[uuid.UUID] = []

    async with sessions() as caller_db:
        try:
            succeeded_result = await context_facade.compile_generation_background(
                caller_db,
                novel_id=novel_id,
                task="生成成功建议",
            )
            succeeded_id = uuid.UUID(
                succeeded_result["context_usage"]["context_snapshot_id"]
            )
            snapshot_ids.append(succeeded_id)

            await caller_db.execute(
                update(ContextSnapshot)
                .where(ContextSnapshot.id == succeeded_id)
                .values(operation="caller-write-must-roll-back")
            )
            await caller_db.rollback()

            async with sessions() as verify_db:
                running = await verify_db.get(ContextSnapshot, succeeded_id)
                assert running is not None
                assert running.status == "running"
                assert running.operation == "world.generation.core_entity"

            succeeded = await context_facade.succeed_generation_context_snapshot(
                caller_db,
                novel_id=novel_id,
                snapshot_id=str(succeeded_id),
                result_refs=[{"type": "suggestion", "id": "suggestion-1"}],
            )
            assert succeeded.status == "succeeded"

            await caller_db.execute(
                update(ContextSnapshot)
                .where(ContextSnapshot.id == succeeded_id)
                .values(status="caller-overwrite-must-roll-back")
            )
            await caller_db.rollback()

            async with sessions() as verify_db:
                stored_success = await verify_db.get(ContextSnapshot, succeeded_id)
                assert stored_success is not None
                assert stored_success.status == "succeeded"
                assert stored_success.result_refs == [
                    {"type": "suggestion", "id": "suggestion-1"}
                ]

            failed_result = await context_facade.compile_generation_background(
                caller_db,
                novel_id=novel_id,
                task="生成失败建议",
            )
            failed_id = uuid.UUID(failed_result["context_usage"]["context_snapshot_id"])
            snapshot_ids.append(failed_id)
            failed = await context_facade.fail_generation_context_snapshot(
                caller_db,
                novel_id=novel_id,
                snapshot_id=str(failed_id),
                error_kind="provider_error",
                error_message="provider failed",
            )
            assert failed.status == "failed"

            await caller_db.execute(
                update(ContextSnapshot)
                .where(ContextSnapshot.id == failed_id)
                .values(error_message="caller-overwrite-must-roll-back")
            )
            await caller_db.rollback()

            async with sessions() as verify_db:
                stored_failure = await verify_db.get(ContextSnapshot, failed_id)
                assert stored_failure is not None
                assert stored_failure.status == "failed"
                assert stored_failure.error_kind == "provider_error"
                assert stored_failure.error_message == "provider failed"
        finally:
            if snapshot_ids:
                await caller_db.execute(
                    delete(ContextSnapshot).where(ContextSnapshot.id.in_(snapshot_ids))
                )
                await caller_db.commit()


@pytest.mark.asyncio
async def test_sqlite_fixture_snapshot_seam_does_not_end_caller_transaction(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection-bound fixture sessions retain their caller-owned transaction."""
    from modules.evidence.compilation import facade as context_facade

    monkeypatch.setattr(
        context_facade._compiler,
        "compile_with_tiers",
        _empty_compilation,
    )
    await db_session.execute(select(ContextSnapshot.id).where(False))
    caller_transaction = db_session.sync_session.get_transaction()
    assert caller_transaction is not None

    result = await context_facade.compile_generation_background(
        db_session,
        novel_id=str(uuid.uuid4()),
        task="验证 SQLite fixture 事务边界",
    )

    assert db_session.sync_session.get_transaction() is caller_transaction
    stored = await db_session.get(
        ContextSnapshot,
        uuid.UUID(result["context_usage"]["context_snapshot_id"]),
    )
    assert stored is not None
    assert stored.status == "running"
