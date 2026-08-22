"""EntityAliasService 测试 — 纯单元测试，repo 用 AsyncMock 替换。"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.errors import ConflictError, NotFoundError
from core.errors import ValidationError as DomainValidationError
from modules.world.services.core.entity_alias_service import EntityAliasService


@pytest.fixture
def novel_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def alias_service() -> EntityAliasService:
    service = EntityAliasService(
        repo=MagicMock(),
        context_marker=AsyncMock(return_value=0),
        activity_requester=AsyncMock(return_value=None),
    )
    service._require_legacy_canon_write_allowed = AsyncMock()  # type: ignore[method-assign]
    return service


@pytest.mark.asyncio
async def test_context_marker_failure_logs_without_blocking_alias_write(
    novel_id: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    marker = AsyncMock(side_effect=RuntimeError("api_key=credential-value"))
    service = EntityAliasService(repo=MagicMock(), context_marker=marker)
    entity_id = str(uuid.uuid4())

    with caplog.at_level(
        "WARNING",
        logger="modules.world.services.core.entity_alias_service",
    ):
        await service._mark_context_changed(
            MagicMock(),
            novel_id=novel_id,
            entity_id=entity_id,
            reason="alias_updated",
        )

    marker.assert_awaited_once()
    record = next(
        item
        for item in caplog.records
        if "world_alias_context_invalidation_failed" in item.getMessage()
    )
    assert novel_id in record.getMessage()
    assert entity_id in record.getMessage()
    assert record.exc_info is None
    assert "credential-value" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()
    assert "RuntimeError" in record.getMessage()


@pytest.mark.asyncio
async def test_entity_alias_service_has_no_direct_http_exception_dependency() -> None:
    source = (
        Path(__file__).parents[1] / "services/core/entity_alias_service.py"
    ).read_text()

    assert "from fastapi import HTTPException" not in source
    assert "raise HTTPException" not in source


def _make_entity(
    *,
    entity_id: str | None = None,
    novel_id: str | None = None,
    name: str = "Arthur",
    content_json: dict | None = None,
    status: str = "canonical",
) -> MagicMock:
    entity = MagicMock()
    entity.id = uuid.UUID(entity_id) if entity_id else uuid.uuid4()
    entity.novel_id = uuid.UUID(novel_id) if novel_id else uuid.uuid4()
    entity.name = name
    entity.content_json = content_json if content_json is not None else {}
    entity.status = status
    return entity


@pytest.mark.asyncio
async def test_list_aliases_returns_alias_for_entity(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
    )
    alias_service.repo.list_by_novel = AsyncMock(return_value=[entity])
    alias_service.repo.get_by_novel = AsyncMock()
    db = MagicMock()

    aliases = await alias_service.list_aliases(db, novel_id)

    assert len(aliases) == 1
    assert aliases[0]["entity_id"] == str(entity.id)
    assert aliases[0]["entity_name"] == "Arthur"
    assert aliases[0]["alias"] == "Art"
    assert aliases[0]["alias_type"] == "nickname"
    alias_service.repo.list_by_novel.assert_awaited_once()
    alias_service.repo.get_by_novel.assert_not_awaited()


@pytest.mark.asyncio
async def test_alias_under_archived_entity_is_projected_as_history(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        status="ignored",
        content_json={
            "aliases": [
                {
                    "alias": "旧称",
                    "type": "name",
                    "status": "canonical",
                    "source": "manual",
                }
            ]
        },
    )
    alias_service.repo.list_by_novel = AsyncMock(return_value=[entity])

    aliases = await alias_service.list_aliases(MagicMock(), novel_id)

    assert aliases[0]["display_state"] == "archived"


@pytest.mark.asyncio
async def test_list_aliases_pagination(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    arthur = _make_entity(
        name="Arthur",
        content_json={"aliases": ["Art", "Athy"]},
    )
    bella = _make_entity(
        name="Bella",
        content_json={"aliases": ["Bell", "Bells"]},
    )
    alias_service.repo.list_by_novel = AsyncMock(return_value=[arthur, bella])
    alias_service.repo.get_by_novel = AsyncMock()
    db = MagicMock()

    paginated = await alias_service.list_aliases(db, novel_id, skip=1, limit=2)
    page = await alias_service.list_aliases_page(db, novel_id, skip=1, limit=2)

    assert len(paginated) == 2
    assert paginated[0]["alias"] == "Athy"
    assert paginated[1]["alias"] == "Bell"
    assert page["total"] == 4
    assert [item["alias"] for item in page["items"]] == ["Athy", "Bell"]
    assert alias_service.repo.list_by_novel.await_count == 2
    alias_service.repo.get_by_novel.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_aliases_page_filters_before_pagination(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        name="克莱恩",
        content_json={
            "aliases": [
                {
                    "alias": "周明瑞",
                    "type": "alias",
                    "status": "candidate",
                    "source": "deep_import",
                    "workflow_id": "wf-1",
                    "scene_index": 3,
                    "source_chapter_index": 1,
                    "confidence": 0.95,
                    "needs_review": True,
                    "quote": "证据一",
                },
                {
                    "alias": "愚者",
                    "type": "title",
                    "status": "canonical",
                    "source": "manual",
                    "confidence": 0.7,
                    "needs_review": False,
                    "quote": "证据二",
                },
            ],
        },
    )
    alias_service.repo.list_by_novel = AsyncMock(return_value=[entity])
    db = MagicMock()

    page = await alias_service.list_aliases_page(
        db,
        novel_id,
        q="周明",
        needs_review=True,
        source="deep_import",
        workflow_id="wf-1",
        scene_index=3,
        source_chapter_index=1,
        confidence_min=0.9,
        skip=0,
        limit=1,
    )

    assert page["total"] == 1
    assert page["items"][0]["alias"] == "周明瑞"
    assert page["items"][0]["quote"] == "证据一"


@pytest.mark.asyncio
async def test_list_aliases_page_filters_legacy_shadow_alias_by_display_state(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    shadow = _make_entity(
        status="candidate",
        content_json={
            "_meta": {
                "compatibility_shadow": True,
                "suggestion_id": str(uuid.uuid4()),
            },
            "aliases": [{"alias": "影子称号", "type": "title"}],
        },
    )
    alias_service.repo.list_by_novel = AsyncMock(return_value=[shadow])

    page = await alias_service.list_aliases_page(
        MagicMock(),
        novel_id,
        display_state="review",
    )

    assert page["total"] == 1
    assert page["items"][0]["alias"] == "影子称号"
    assert page["items"][0]["display_state"] == "review"
    assert page["items"][0]["managed_by_suggestion"] is True


@pytest.mark.asyncio
async def test_alias_page_hides_archived_alias_or_owner_before_pagination(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    active = _make_entity(
        name="active",
        status="canonical",
        content_json={"aliases": [{"alias": "current", "status": "canonical"}]},
    )
    archived_alias = _make_entity(
        name="archived-alias",
        status="canonical",
        content_json={"aliases": [{"alias": "old-alias", "status": "ignored"}]},
    )
    archived_owner = _make_entity(
        name="archived-owner",
        status="merged",
        content_json={
            "_meta": {
                "compatibility_shadow": True,
                "suggestion_id": str(uuid.uuid4()),
            },
            "aliases": [{"alias": "old-owner", "status": "canonical"}],
        },
    )
    archived_alias_on_review_owner = _make_entity(
        name="review-owner",
        status="candidate",
        content_json={"aliases": [{"alias": "ignored-on-review", "status": "ignored"}]},
    )
    alias_service.repo.list_by_novel = AsyncMock(
        return_value=[
            active,
            archived_alias,
            archived_owner,
            archived_alias_on_review_owner,
        ]
    )

    default_page = await alias_service.list_aliases_page(
        MagicMock(), novel_id, skip=0, limit=1
    )
    history_page = await alias_service.list_aliases_page(
        MagicMock(), novel_id, display_state="archived", skip=0, limit=10
    )
    raw_status_page = await alias_service.list_aliases_page(
        MagicMock(), novel_id, status="canonical", skip=0, limit=10
    )
    ignored_status_page = await alias_service.list_aliases_page(
        MagicMock(), novel_id, status="ignored", skip=0, limit=10
    )

    assert default_page["total"] == 1
    assert len(default_page["items"]) == 1
    assert default_page["items"][0]["alias"] == "current"
    assert {item["alias"] for item in history_page["items"]} == {
        "ignored-on-review",
        "old-alias",
        "old-owner",
    }
    assert history_page["total"] == 3
    old_owner = next(
        item for item in history_page["items"] if item["alias"] == "old-owner"
    )
    assert old_owner["managed_by_suggestion"] is True
    assert {item["alias"] for item in raw_status_page["items"]} == {
        "current",
        "old-owner",
    }
    assert {item["alias"] for item in ignored_status_page["items"]} == {
        "ignored-on-review",
        "old-alias",
    }
    assert ignored_status_page["total"] == 2
    for call in alias_service.repo.list_by_novel.await_args_list:
        assert call.kwargs["include_archived"] is True


@pytest.mark.asyncio
async def test_create_alias_adds_to_content_json(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(novel_id=novel_id)
    alias_service.repo.get_for_update = AsyncMock(return_value=entity)
    db = AsyncMock()

    result = await alias_service.create_alias(
        db, novel_id, str(entity.id), "Art", "nickname"
    )

    assert result["entity_id"] == str(entity.id)
    assert result["alias"] == "Art"
    assert result["alias_type"] == "nickname"
    stored = entity.content_json["aliases"][0]
    assert stored["alias"] == "Art"
    assert stored["type"] == "nickname"
    assert stored["status"] == "confirmed"
    assert stored["source"] == "manual"
    assert stored["needs_review"] is False
    assert result["display_state"] == "active"
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_alias_appends_to_existing_content_json(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        novel_id=novel_id,
        content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
    )
    alias_service.repo.get_for_update = AsyncMock(return_value=entity)
    db = AsyncMock()

    result = await alias_service.create_alias(
        db, novel_id, str(entity.id), "King Arthur", "title"
    )

    assert result["alias"] == "King Arthur"
    assert entity.content_json["aliases"][0] == {
        "alias": "Art",
        "type": "nickname",
    }
    stored = entity.content_json["aliases"][1]
    assert stored["alias"] == "King Arthur"
    assert stored["type"] == "title"
    assert stored["status"] == "confirmed"
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_alias_removes_from_content_json(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        novel_id=novel_id,
        content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
    )
    alias_service.repo.get_for_update = AsyncMock(return_value=entity)
    db = AsyncMock()

    result = await alias_service.delete_alias(db, novel_id, str(entity.id), "Art")

    assert result["entity_id"] == str(entity.id)
    assert result["alias"] == "Art"
    assert result["deleted"] is True
    assert entity.content_json["aliases"] == []
    db.flush.assert_awaited_once()


@pytest.mark.parametrize("scenario", ["not_found", "cross_novel"])
@pytest.mark.asyncio
async def test_create_alias_not_found_variants(
    novel_id: str,
    alias_service: EntityAliasService,
    scenario: str,
) -> None:
    if scenario == "cross_novel":
        entity = _make_entity(novel_id=str(uuid.uuid4()))
        alias_service.repo.get_for_update = AsyncMock(return_value=entity)
    else:
        alias_service.repo.get_for_update = AsyncMock(return_value=None)

    db = MagicMock()
    with pytest.raises(NotFoundError) as exc_info:
        await alias_service.create_alias(db, novel_id, str(uuid.uuid4()), "Art")
    assert exc_info.value.status_code == 404
    assert "Entity not found" in exc_info.value.message


@pytest.mark.asyncio
async def test_create_alias_duplicate_returns_409(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        novel_id=novel_id,
        content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
    )
    alias_service.repo.get_for_update = AsyncMock(return_value=entity)
    db = MagicMock()

    with pytest.raises(ConflictError) as exc_info:
        await alias_service.create_alias(db, novel_id, str(entity.id), "Art")
    assert exc_info.value.status_code == 409
    assert "Alias already exists: Art" in exc_info.value.message


@pytest.mark.asyncio
async def test_update_alias_updates_metadata_and_removes_none_fields(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        novel_id=novel_id,
        content_json={
            "aliases": [
                {
                    "alias": "Art",
                    "type": "nickname",
                    "status": "candidate",
                    "needs_review": True,
                    "reviewed_at": "old",
                },
            ]
        },
    )
    alias_service.repo.get_for_update = AsyncMock(return_value=entity)
    db = AsyncMock()

    result = await alias_service.update_alias(
        db,
        novel_id,
        str(entity.id),
        "Art",
        {
            "status": "canonical",
            "needs_review": False,
            "reviewed_at": None,
            "reviewed_by": "manual",
        },
    )

    assert result["status"] == "canonical"
    assert result["needs_review"] is False
    assert result["reviewed_at"] is None
    assert result["reviewed_by"] == "manual"
    assert entity.content_json["aliases"] == [
        {
            "alias": "Art",
            "type": "nickname",
            "kind": "name",
            "status": "canonical",
            "needs_review": False,
            "reviewed_by": "manual",
        }
    ]
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_alias_renames_type_and_confirms_review_preserving_provenance(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        novel_id=novel_id,
        content_json={
            "aliases": [
                {
                    "alias": "Art",
                    "type": "nickname",
                    "status": "candidate",
                    "source": "deep_import",
                    "workflow_id": "wf-1",
                    "scene_id": "scene-1",
                    "confidence": 0.92,
                    "quote": "called Art",
                    "needs_review": True,
                },
            ]
        },
    )
    alias_service.repo.get_many_for_update = AsyncMock(return_value=[entity])
    db = AsyncMock()

    result = await alias_service.edit_alias(
        db,
        novel_id,
        str(entity.id),
        "Art",
        alias="King Arthur",
        alias_type="title",
    )

    updated = entity.content_json["aliases"][0]
    assert updated["alias"] == "King Arthur"
    assert updated["type"] == "title"
    assert updated["status"] == "canonical"
    assert updated["needs_review"] is False
    assert updated["source"] == "deep_import"
    assert updated["workflow_id"] == "wf-1"
    assert updated["scene_id"] == "scene-1"
    assert updated["confidence"] == 0.92
    assert updated["quote"] == "called Art"
    assert updated["user_edited"] is True
    assert updated["edited_by"] == "manual"
    assert updated["edited_at"]
    assert result["alias"] == "King Arthur"
    assert result["alias_type"] == "title"
    assert result["affected_ids"] == [str(entity.id)]
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_alias_moves_to_target_entity(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    source = _make_entity(
        novel_id=novel_id,
        content_json={"aliases": [{"alias": "Blackthorn", "type": "alias"}]},
    )
    target = _make_entity(
        novel_id=novel_id,
        name="Nighthawks",
        content_json={"aliases": []},
    )
    alias_service.repo.get_many_for_update = AsyncMock(return_value=[source, target])
    db = AsyncMock()

    result = await alias_service.edit_alias(
        db,
        novel_id,
        str(source.id),
        "Blackthorn",
        target_entity_id=str(target.id),
        alias_type="name",
    )

    assert source.content_json["aliases"] == []
    assert target.content_json["aliases"][0]["alias"] == "Blackthorn"
    assert target.content_json["aliases"][0]["type"] == "name"
    assert set(result["affected_ids"]) == {str(source.id), str(target.id)}
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_alias_rejects_duplicate_on_target(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    source = _make_entity(
        novel_id=novel_id,
        content_json={"aliases": [{"alias": "Blackthorn", "type": "alias"}]},
    )
    target = _make_entity(
        novel_id=novel_id,
        content_json={"aliases": [{"alias": "Blackthorn", "type": "name"}]},
    )
    alias_service.repo.get_many_for_update = AsyncMock(return_value=[source, target])
    db = AsyncMock()

    with pytest.raises(ConflictError):
        await alias_service.edit_alias(
            db,
            novel_id,
            str(source.id),
            "Blackthorn",
            target_entity_id=str(target.id),
        )
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_alias_rejects_cross_novel_target(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    source = _make_entity(
        novel_id=novel_id,
        content_json={"aliases": [{"alias": "Blackthorn"}]},
    )
    target = _make_entity(novel_id=str(uuid.uuid4()))
    alias_service.repo.get_many_for_update = AsyncMock(return_value=[source])
    db = AsyncMock()

    with pytest.raises(NotFoundError) as exc_info:
        await alias_service.edit_alias(
            db,
            novel_id,
            str(source.id),
            "Blackthorn",
            target_entity_id=str(target.id),
        )
    assert "Target entity not found" in exc_info.value.message
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_alias_rejects_invalid_target_status(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        novel_id=novel_id,
        status="merged",
        content_json={"aliases": [{"alias": "Blackthorn"}]},
    )
    alias_service.repo.get_many_for_update = AsyncMock(return_value=[entity])
    db = AsyncMock()

    with pytest.raises(DomainValidationError):
        await alias_service.edit_alias(db, novel_id, str(entity.id), "Blackthorn")
    db.flush.assert_not_awaited()


@pytest.mark.parametrize(
    "scenario,expected_detail",
    [
        ("not_found", "Alias not found: Art"),
        ("cross_novel", "Entity not found"),
    ],
)
@pytest.mark.asyncio
async def test_delete_alias_not_found_variants(
    novel_id: str,
    alias_service: EntityAliasService,
    scenario: str,
    expected_detail: str,
) -> None:
    if scenario == "cross_novel":
        entity = _make_entity(
            novel_id=str(uuid.uuid4()),
            content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
        )
    else:
        entity = _make_entity(novel_id=novel_id, content_json={})
    alias_service.repo.get_for_update = AsyncMock(return_value=entity)
    db = MagicMock()

    with pytest.raises(NotFoundError) as exc_info:
        await alias_service.delete_alias(db, novel_id, str(entity.id), "Art")
    assert exc_info.value.status_code == 404
    assert expected_detail in exc_info.value.message


@pytest.mark.asyncio
async def test_list_aliases_handles_string_aliases(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(content_json={"aliases": ["Art"]})
    alias_service.repo.list_by_novel = AsyncMock(return_value=[entity])
    alias_service.repo.get_by_novel = AsyncMock()
    db = MagicMock()

    aliases = await alias_service.list_aliases(db, novel_id)

    assert len(aliases) == 1
    assert aliases[0]["entity_id"] == str(entity.id)
    assert aliases[0]["entity_name"] == "Arthur"
    assert aliases[0]["alias"] == "Art"
    assert aliases[0]["alias_type"] == "name"
    alias_service.repo.get_by_novel.assert_not_awaited()


@pytest.mark.asyncio
async def test_append_candidate_alias_does_not_demote_existing_active_alias(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        novel_id=novel_id,
        content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
    )
    alias_service.repo.get_for_update = AsyncMock(return_value=entity)
    db = AsyncMock()

    appended = await alias_service.append_candidate_alias(
        db,
        novel_id,
        str(entity.id),
        alias=" Art ",
        alias_type="alias",
        workflow_id="wf-1",
        scene_id="scene-1",
        scene_index=7,
        confidence=0.82,
        quote="有人称他为 Art。",
    )

    assert appended is False
    assert entity.content_json["aliases"] == [{"alias": "Art", "type": "nickname"}]
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_append_candidate_alias_rejects_pending_suggestion_shadow(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        novel_id=novel_id,
        status="candidate",
        content_json={
            "_meta": {
                "compatibility_shadow": True,
                "suggestion_id": str(uuid.uuid4()),
            }
        },
    )
    alias_service.repo.get_for_update = AsyncMock(return_value=entity)

    with pytest.raises(DomainValidationError, match="authoritative suggestion queue"):
        await alias_service.append_candidate_alias(
            AsyncMock(),
            novel_id,
            str(entity.id),
            alias="Shadow Alias",
            workflow_id="wf-1",
        )


@pytest.mark.asyncio
async def test_rollback_deep_import_candidate_aliases_is_scoped_and_preserves_active(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        novel_id=novel_id,
        content_json={
            "aliases": [
                {
                    "alias": "待回滚",
                    "type": "alias",
                    "status": "candidate",
                    "source": "deep_import",
                    "workflow_id": "wf-1",
                    "needs_review": True,
                },
                {
                    "alias": "已采用",
                    "type": "title",
                    "status": "canonical",
                    "source": "deep_import",
                    "workflow_id": "wf-1",
                },
                {
                    "alias": "其他任务",
                    "type": "alias",
                    "status": "candidate",
                    "source": "deep_import",
                    "workflow_id": "wf-2",
                    "needs_review": True,
                },
            ]
        },
    )
    alias_service.repo.list_by_novel = AsyncMock(return_value=[entity])
    alias_service.repo.get_many_for_update = AsyncMock(return_value=[entity])

    db = MagicMock()
    db.flush = AsyncMock()

    count = await alias_service.rollback_deep_import_candidates_by_workflow(
        db,
        novel_id,
        "wf-1",
    )

    aliases = entity.content_json["aliases"]
    assert count == 1
    assert aliases[0]["status"] == "ignored"
    assert aliases[0]["rolled_back"] is True
    assert aliases[1]["status"] == "canonical"
    assert aliases[2]["status"] == "candidate"
    alias_service._activity_requester.assert_awaited_once_with(db, novel_id)


@pytest.mark.asyncio
async def test_rollback_preserves_manually_edited_unconfirmed_candidate_alias(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    entity = _make_entity(
        novel_id=novel_id,
        content_json={
            "aliases": [
                {
                    "alias": "旧称",
                    "type": "alias",
                    "status": "candidate",
                    "source": "deep_import",
                    "workflow_id": "wf-1",
                    "needs_review": True,
                }
            ]
        },
    )
    alias_service.repo.get_many_for_update = AsyncMock(return_value=[entity])
    alias_service.repo.list_by_novel = AsyncMock(return_value=[entity])
    db = MagicMock()
    db.flush = AsyncMock()

    await alias_service.edit_alias(
        db,
        novel_id,
        str(entity.id),
        "旧称",
        alias="作者修改的称呼",
        confirm_review=False,
    )
    count = await alias_service.rollback_deep_import_candidates_by_workflow(
        db,
        novel_id,
        "wf-1",
    )

    alias = entity.content_json["aliases"][0]
    assert count == 0
    assert alias["status"] == "candidate"
    assert alias["alias"] == "作者修改的称呼"
    assert alias["user_edited"] is True
    assert alias["edited_by"] == "manual"


@pytest.mark.asyncio
async def test_append_candidate_alias_missing_entity_raises_domain_not_found(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    alias_service.repo.get_for_update = AsyncMock(return_value=None)
    db = MagicMock()

    with pytest.raises(NotFoundError) as exc_info:
        await alias_service.append_candidate_alias(
            db,
            novel_id,
            str(uuid.uuid4()),
            alias="Art",
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Entity not found"


@pytest.mark.asyncio
async def test_append_candidate_alias_keeps_enriched_duplicate_unchanged(
    novel_id: str,
    alias_service: EntityAliasService,
) -> None:
    existing = {
        "alias": "Art",
        "type": "alias",
        "status": "candidate",
        "source": "deep_import",
        "workflow_id": "wf-1",
        "needs_review": True,
    }
    entity = _make_entity(novel_id=novel_id, content_json={"aliases": [existing]})
    alias_service.repo.get_for_update = AsyncMock(return_value=entity)
    db = AsyncMock()

    appended = await alias_service.append_candidate_alias(
        db,
        novel_id,
        str(entity.id),
        alias="Art",
        workflow_id="wf-2",
    )

    assert appended is False
    assert entity.content_json["aliases"] == [existing]
    db.flush.assert_not_awaited()
