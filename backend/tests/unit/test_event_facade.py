"""
Unit tests for modules.world.event_facade.

Mocks the internal service instances (_event_service / _revision_service)
to keep these tests fast and isolated.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from modules.world.facade import (
    create_event,
    get_entity_revisions,
    get_events_context,
    rollback_to_revision,
)

pytestmark = [pytest.mark.asyncio]


# ============================================================
# create_event
# ============================================================


async def test_create_event_success_returns_event_context_dict(
    db_session,
    test_project_id: str,
):
    """Happy path: service creates event and facade returns EventContext dict."""
    # Arrange
    mock_event = MagicMock()
    mock_event.entity_id = "entity-1"
    mock_event.timeline_order = 3
    mock_event.occurrence_time_label = "三年前"

    with patch(
        "modules.world.event_facade._event_service.create",
        autospec=True,
    ) as mock_create:
        mock_create.return_value = mock_event

        data = {
            "entity_id": "entity-1",
            "source_chapter_id": "chapter-1",
            "location_entity_id": "loc-1",
            "timeline_order": 3,
            "occurrence_time_label": "三年前",
        }

        # Act
        result = await create_event(db_session, test_project_id, data)

        # Assert
        mock_create.assert_awaited_once()
        args, _ = mock_create.call_args
        assert args[0] is db_session
        assert args[1] == test_project_id
        assert result["entity_id"] == "entity-1"
        assert result["timeline_order"] == 3
        assert result["occurrence_time_label"] == "三年前"
        assert result["entity_name"] == ""


async def test_create_event_with_none_time_label_returns_dict(
    db_session,
    test_project_id: str,
):
    """边界: occurrence_time_label 为 None 时仍能正常返回."""
    # Arrange
    mock_event = MagicMock()
    mock_event.entity_id = "entity-2"
    mock_event.timeline_order = 0
    mock_event.occurrence_time_label = None

    with patch(
        "modules.world.event_facade._event_service.create",
        autospec=True,
    ) as mock_create:
        mock_create.return_value = mock_event

        data = {
            "entity_id": "entity-2",
            "source_chapter_id": "chapter-1",
            "location_entity_id": "loc-1",
            "timeline_order": 0,
        }

        # Act
        result = await create_event(db_session, test_project_id, data)

        # Assert
        assert result["occurrence_time_label"] is None
        assert result["timeline_order"] == 0


async def test_create_event_invalid_data_raises_validation_error(
    db_session,
    test_project_id: str,
):
    """异常路径: 缺少必填字段时 EventCreate 校验失败抛出 ValidationError."""
    # Arrange
    data = {
        "source_chapter_id": "chapter-1"
    }  # missing entity_id, location_entity_id, timeline_order

    # Act & Assert
    with pytest.raises(ValidationError):
        await create_event(db_session, test_project_id, data)


# ============================================================
# get_events_context
# ============================================================


async def test_get_events_context_success_returns_bundle_with_events(
    db_session,
    test_project_id: str,
):
    """Happy path: 返回包含事件列表的 EventsContextBundle."""
    # Arrange
    mock_ev1 = MagicMock()
    mock_ev1.entity_id = "e1"
    mock_ev1.timeline_order = 1
    mock_ev1.occurrence_time_label = "序章"

    mock_ev2 = MagicMock()
    mock_ev2.entity_id = "e2"
    mock_ev2.timeline_order = 2
    mock_ev2.occurrence_time_label = "第一章"

    with patch(
        "modules.world.event_facade._event_service.get_events_in_order",
        autospec=True,
    ) as mock_get:
        mock_get.return_value = [mock_ev1, mock_ev2]

        # Act
        bundle = await get_events_context(db_session, test_project_id, limit=10)

        # Assert
        mock_get.assert_awaited_once_with(db_session, test_project_id, limit=10)
        assert bundle.novel_id == test_project_id
        assert bundle.total_count == 2
        assert len(bundle.events) == 2
        assert bundle.events[0].entity_id == "e1"
        assert bundle.events[1].entity_id == "e2"


async def test_get_events_context_empty_returns_empty_bundle(
    db_session,
    test_project_id: str,
):
    """边界: 无事件时返回空 EventsContextBundle."""
    # Arrange
    with patch(
        "modules.world.event_facade._event_service.get_events_in_order",
        autospec=True,
    ) as mock_get:
        mock_get.return_value = []

        # Act
        bundle = await get_events_context(db_session, test_project_id)

        # Assert
        mock_get.assert_awaited_once_with(db_session, test_project_id, limit=50)
        assert bundle.total_count == 0
        assert bundle.events == []


# ============================================================
# get_entity_revisions
# ============================================================


async def test_get_entity_revisions_success_returns_revisions_dict(
    db_session,
    test_project_id: str,
):
    """Happy path: 服务返回强类型响应，facade 对外仍返回 dict."""
    # Arrange
    from datetime import UTC, datetime

    from modules.world.revision_history_schemas import (
        EntityRevisionItem,
        EntityRevisionListResponse,
        EntityRevisionSnapshotView,
    )

    service_response = EntityRevisionListResponse(
        items=[
            EntityRevisionItem(
                revision_id="r1",
                entity_id="e1",
                revision_reason="manual_update",
                created_at=datetime(2026, 10, 4, tzinfo=UTC),
                changed_fields=["summary"],
                changed_fields_exact=True,
                snapshot=EntityRevisionSnapshotView(
                    entity_type="character",
                    name="角色",
                    status="canonical",
                ),
                can_restore=True,
            ),
        ],
        total=1,
    )

    with patch(
        "modules.world.event_facade._revision_service.get_revisions",
        autospec=True,
    ) as mock_get:
        mock_get.return_value = service_response

        # Act
        result = await get_entity_revisions(
            db_session, test_project_id, "e1", skip=5, limit=10
        )

        # Assert
        mock_get.assert_awaited_once_with(
            db_session, "e1", test_project_id, skip=5, limit=10
        )
        assert result["total"] == 1
        assert result["items"][0]["revision_id"] == "r1"
        assert result["items"][0]["changed_fields"] == ["summary"]
        assert result["items"][0]["changed_fields_exact"] is True
        assert result["items"][0]["can_restore"] is True


async def test_get_entity_revisions_defaults_skip_and_limit(
    db_session,
    test_project_id: str,
):
    """边界: skip / limit 使用默认值 0 / 20 并正确传递."""
    # Arrange
    from modules.world.revision_history_schemas import EntityRevisionListResponse

    service_response = EntityRevisionListResponse(items=[], total=0)

    with patch(
        "modules.world.event_facade._revision_service.get_revisions",
        autospec=True,
    ) as mock_get:
        mock_get.return_value = service_response

        # Act
        result = await get_entity_revisions(db_session, test_project_id, "e1")

        # Assert
        mock_get.assert_awaited_once_with(
            db_session, "e1", test_project_id, skip=0, limit=20
        )
        assert result == {
            "items": [],
            "total": 0,
            "skip": 0,
            "limit": 20,
            "current_updated_at": None,
        }


# ============================================================
# rollback_to_revision
# ============================================================


async def test_rollback_to_revision_success_returns_dict(
    db_session,
    test_project_id: str,
):
    """Happy path: 回滚成功并返回实体 dict；expected_updated_at 为必填关键字参数."""
    # Arrange
    from datetime import UTC, datetime

    from modules.world.schemas import CoreEntityResponse

    baseline = datetime(2026, 10, 4, tzinfo=UTC)
    service_response = CoreEntityResponse(
        id="e1",
        novel_id=test_project_id,
        entity_type="character",
        name="旧版名称",
        status="canonical",
        created_at=baseline,
        updated_at=baseline,
    )

    with patch(
        "modules.world.event_facade._entity_service.rollback_to_revision",
        autospec=True,
    ) as mock_rollback:
        mock_rollback.return_value = service_response

        # Act
        result = await rollback_to_revision(
            db_session,
            test_project_id,
            "e1",
            "rev-1",
            expected_updated_at=baseline,
        )

        # Assert
        mock_rollback.assert_awaited_once_with(
            db_session,
            "e1",
            "rev-1",
            novel_id=test_project_id,
            expected_updated_at=baseline,
        )
        assert result["id"] == "e1"
        assert result["name"] == "旧版名称"


async def test_rollback_to_revision_requires_expected_updated_at_keyword(
    db_session,
    test_project_id: str,
):
    """边界: 不带 expected_updated_at 时按必填关键字参数报 TypeError."""
    # Arrange
    with patch(
        "modules.world.event_facade._entity_service.rollback_to_revision",
        autospec=True,
    ) as mock_rollback:
        # Act & Assert
        with pytest.raises(TypeError):
            await rollback_to_revision(db_session, test_project_id, "e1", "rev-1")
        mock_rollback.assert_not_awaited()
