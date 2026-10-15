from __future__ import annotations

import asyncio
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from core.errors import ConflictError
from modules.assistant import notice_service
from modules.assistant.notice_contracts import NoticeDispositionRequest, NoticeScope
from modules.assistant.notice_models import AssistantNoticeDisposition
from modules.story.notice_sources import _scene_issues


def test_notice_disposition_migration_creates_and_drops_only_its_tables():
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic/versions/20261015_notice_dispositions.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_notice_dispositions_migration", migration_path
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261015_notice_dispositions"
    assert migration.down_revision == "20261015_map_node_merge"

    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            inspector = sa.inspect(connection)
            assert {
                "assistant_notice_dispositions",
                "assistant_notice_category_mutes",
            } <= set(inspector.get_table_names())
            disposition_columns = {
                column["name"]
                for column in inspector.get_columns("assistant_notice_dispositions")
            }
            assert {
                "novel_id",
                "source_id",
                "notice_key",
                "basis_fingerprint",
                "wake_at",
                "row_version",
            } <= disposition_columns
            migration.downgrade()
            assert not {
                "assistant_notice_dispositions",
                "assistant_notice_category_mutes",
            } & set(sa.inspect(connection).get_table_names())
    finally:
        engine.dispose()


def _item(source_id: str, *, basis: str = "a" * 64) -> dict:
    return {
        "notice_key": f"{source_id}:one",
        "source_id": source_id,
        "category": "structure",
        "severity": "medium",
        "target": {"chapter_index": 1},
        "summary": "待处理提醒",
        "evidence": [],
        "basis_fingerprint": basis,
        "stale": False,
        "actions": [],
        "disposition_ref": None,
    }


@pytest.mark.asyncio
async def test_parallel_sources_use_isolated_sessions_and_preserve_unavailable(
    db_session, test_project_id, monkeypatch
):
    opened = []

    class SourceSession:
        closed = False

        async def __aenter__(self):
            opened.append(self)
            return self

        async def __aexit__(self, *_args):
            self.closed = True

    manager = SimpleNamespace(session_factory=SourceSession)
    monkeypatch.setattr(notice_service, "get_manager", lambda: manager)
    gate = asyncio.Event()

    async def successful(db, _novel_id, _scope):
        await gate.wait()
        return [_item("test.good")]

    async def failing(_db, _novel_id, _scope):
        gate.set()
        raise RuntimeError("isolated provider failure")

    async def hanging(_db, _novel_id, _scope):
        await asyncio.Event().wait()

    sources = {
        "test.good": SimpleNamespace(
            source_id="test.good",
            label="可用来源",
            list_notices=successful,
            timeout_seconds=0.2,
        ),
        "test.failure": SimpleNamespace(
            source_id="test.failure",
            label="失败来源",
            list_notices=failing,
            timeout_seconds=0.2,
        ),
        "test.timeout": SimpleNamespace(
            source_id="test.timeout",
            label="超时来源",
            list_notices=hanging,
            timeout_seconds=0.01,
        ),
    }

    response = await notice_service.list_notices(
        db_session,
        test_project_id,
        NoticeScope(chapter_index=1),
        sources=sources,
    )

    assert [item.source_id for item in response.items] == ["test.good"]
    assert {item.source_id for item in response.unavailable_sources} == {
        "test.failure",
        "test.timeout",
    }
    assert response.partial is True
    assert len(opened) == 3
    assert len({id(session) for session in opened}) == 3
    assert all(session.closed for session in opened)


@pytest.mark.asyncio
async def test_disposition_is_basis_bound_and_mute_can_be_reversed(
    db_session, test_project_id
):
    novel_id = UUID(test_project_id)
    scope = NoticeScope(chapter_index=1)
    current = _item("test.notice")
    source = SimpleNamespace(
        source_id="test.notice",
        label="测试来源",
        list_notices=lambda *_args: asyncio.sleep(0, result=[current]),
        decide=None,
        timeout_seconds=1,
    )
    sources = {"test.notice": source}
    request = NoticeDispositionRequest(
        novel_id=novel_id,
        source_id="test.notice",
        notice_key=current["notice_key"],
        basis_fingerprint=current["basis_fingerprint"],
        scope=scope,
        expected_row_version=0,
        action="snooze",
        duration_hours=1,
    )

    saved = await notice_service.apply_disposition(db_session, request, sources=sources)
    assert saved["status"] == "snoozed"
    assert saved["row_version"] == 1
    assert saved["wake_at"] > datetime.now(UTC)
    assert await db_session.scalar(
        select(AssistantNoticeDisposition).where(
            AssistantNoticeDisposition.novel_id == novel_id
        )
    )

    response = await notice_service.list_notices(
        db_session, test_project_id, scope, sources=sources
    )
    assert response.items[0].status == "snoozed"
    assert response.items[0].row_version == 1

    changed = _item("test.notice", basis="b" * 64)
    source.list_notices = lambda *_args: asyncio.sleep(0, result=[changed])
    changed_response = await notice_service.list_notices(
        db_session, test_project_id, scope, sources=sources
    )
    assert changed_response.items[0].status == "unread"

    stale = request.model_copy(update={"basis_fingerprint": "c" * 64})
    with pytest.raises(ConflictError, match="提醒依据已变化"):
        await notice_service.apply_disposition(db_session, stale, sources=sources)

    muted = await notice_service.set_category_mute(
        db_session,
        test_project_id,
        "test.notice",
        "structure",
        0,
        muted=True,
        sources=sources,
    )
    assert muted["is_muted"] is True and muted["row_version"] == 1
    hidden = await notice_service.list_notices(
        db_session, test_project_id, scope, sources=sources
    )
    assert hidden.items == []

    restored = await notice_service.set_category_mute(
        db_session,
        test_project_id,
        "test.notice",
        "structure",
        1,
        muted=False,
        sources=sources,
    )
    assert restored["is_muted"] is False and restored["row_version"] == 2
    shown = await notice_service.list_notices(
        db_session, test_project_id, scope, sources=sources
    )
    assert shown.items[0].basis_fingerprint == "b" * 64


def test_story_structure_notice_trust_and_chapter_mapping_rules():
    scene = SimpleNamespace(
        source="manual_fusion",
        structure_meta={
            "semantic_field_statuses": {
                "core_conflict": "not_applicable",
                "goal": "uncertain",
            }
        },
        goal="",
        core_conflict="",
        emotional_beat="",
        pov_character_id="pov-id",
        chapter_ids=["2", "3"],
        scene_chunks=[],
    )
    issues = _scene_issues(SimpleNamespace(scene=scene, health=[]), chapter_index=2)
    codes = {item[0] for item in issues}
    assert "structure-core_conflict" not in codes
    assert "structure-goal" in codes
    assert "structure-chapter-map" not in codes

    scene.source = "manual"
    scene.structure_meta = {"semantic_field_statuses": {"goal": "uncertain"}}
    untrusted = {
        item[0] for item in _scene_issues(SimpleNamespace(scene=scene, health=[]), 4)
    }
    assert "structure-goal" in untrusted
    assert "structure-chapter-map" in untrusted


@pytest.mark.asyncio
async def test_scene_scope_requires_scene_to_belong_to_the_active_novel(
    db_session, test_project_id, project_factory
):
    from core.errors import NotFoundError
    from modules.assistant.notices_api import _authorize_scope
    from modules.story.outline_state.schemas import SceneCreate
    from modules.story.outline_state.services import SceneService

    scene = await SceneService().create(
        db_session,
        test_project_id,
        SceneCreate(scene_index=7, title="同项目场景"),
    )
    scope = NoticeScope(scene_id=UUID(scene.id))
    await _authorize_scope(db_session, UUID(test_project_id), scope)

    other_project_id = await project_factory.create_project(title="另一作品")
    with pytest.raises(NotFoundError):
        await _authorize_scope(db_session, other_project_id, scope)


def test_notice_operation_contract_has_complete_trace_metadata():
    from modules.assistant.notice_disposition_operations import OPERATIONS_SPEC

    assert set(OPERATIONS_SPEC) == {
        "assistant.notice.set_disposition",
        "assistant.notice.mute_category",
        "assistant.notice.unmute_category",
    }
    for spec in OPERATIONS_SPEC.values():
        assert spec["trace_rule"]["parameter_fields"] == tuple(
            spec["schema"].model_fields
        )
        assert spec["trace_rule"]["parameter_policy"] == "schema_safe"
        assert spec["fee_category"] == "free"
        assert spec["transaction_mode"] == "single_transaction"


@pytest.mark.asyncio
async def test_real_registered_sources_can_read_an_empty_project_without_ai(
    db_session, test_project_id
):
    from modules.assistant.forecast_notice_source import list_forecast_notices
    from modules.assistant.notice_sources import list_assistant_notices
    from modules.story.notice_sources import list_scene_structure_notices
    from modules.writing.notice_sources import (
        list_conflict_notices,
        list_invalidation_notices,
    )

    scope = {"chapter_index": 1, "scene_id": None}
    results = [
        await reader(db_session, test_project_id, scope)
        for reader in (
            list_assistant_notices,
            list_forecast_notices,
            list_scene_structure_notices,
            list_conflict_notices,
            list_invalidation_notices,
        )
    ]
    assert results[0] == []
    assert results[1] == []
    assert results[2] == []
    assert results[3][0]["notice_key"].startswith("writing.conflict:missing:")
    assert results[4] == []
