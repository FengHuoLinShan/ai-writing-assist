"""Assistant world focus refs are owner-, child-, and version-scoped."""

import uuid
from datetime import timedelta

import pytest

from core.errors import ConflictError, NotFoundError
from modules.world.facade import (
    create_world_object_dossier_entry,
    read_assistant_world_focus,
    upsert_relation,
    validate_assistant_world_focus,
)
from modules.world.models import CoreEntity
from modules.world.schemas.dossier import DossierEntryCreate
from tests.utils import _create_entity


@pytest.mark.asyncio
async def test_entity_focus_checks_project_and_saved_version(
    db_session, project_novel_id: str, other_novel_id: str, location_entity_id: str
) -> None:
    entity = await db_session.get(CoreEntity, uuid.UUID(location_entity_id))
    assert entity is not None and entity.updated_at is not None
    focus = {
        "kind": "entity",
        "entity_id": entity.id,
        "updated_at": entity.updated_at,
    }

    await validate_assistant_world_focus(db_session, project_novel_id, focus)
    material = await read_assistant_world_focus(db_session, project_novel_id, focus)
    assert material["kind"] == "entity"
    assert material["content"]["name"] == entity.name
    stale = {**focus, "updated_at": focus["updated_at"] + timedelta(seconds=1)}
    with pytest.raises(ConflictError, match="对象资料已变化"):
        await validate_assistant_world_focus(db_session, project_novel_id, stale)
    with pytest.raises(NotFoundError, match="当前作品"):
        await validate_assistant_world_focus(db_session, other_novel_id, focus)


@pytest.mark.asyncio
async def test_dossier_focus_requires_current_revision_and_matching_object(
    db_session,
    project_novel_id: str,
    location_entity_id: str,
) -> None:
    entry = await create_world_object_dossier_entry(
        db_session,
        project_novel_id,
        location_entity_id,
        DossierEntryCreate(
            facing={"kind": "core", "key": "geography"},
            content="城门外有一座旧驿站。",
        ),
    )
    focus = {
        "kind": "dossier_entry",
        "entity_id": uuid.UUID(location_entity_id),
        "entry_group_id": entry.entry_group_id,
        "revision_id": entry.id,
    }

    await validate_assistant_world_focus(db_session, project_novel_id, focus)
    material = await read_assistant_world_focus(db_session, project_novel_id, focus)
    assert material["kind"] == "dossier_entry"
    assert material["content"]["content"] == "城门外有一座旧驿站。"
    assert material["content"]["revision_number"] == entry.revision_number
    stale = {**focus, "revision_id": uuid.uuid4()}
    with pytest.raises(ConflictError, match="档案条目已变化"):
        await validate_assistant_world_focus(db_session, project_novel_id, stale)

    other_entity = await _create_entity(
        db_session,
        project_novel_id,
        entity_type="location",
        name="另一处地点",
    )
    other_entry = await create_world_object_dossier_entry(
        db_session,
        project_novel_id,
        str(other_entity.id),
        DossierEntryCreate(
            facing={"kind": "core", "key": "geography"},
            content="一个只用于确认对象归属的条目。",
        ),
    )
    wrong_object = {
        **focus,
        "entry_group_id": other_entry.entry_group_id,
        "revision_id": other_entry.id,
    }
    with pytest.raises(ConflictError, match="档案条目已变化"):
        await validate_assistant_world_focus(db_session, project_novel_id, wrong_object)


@pytest.mark.asyncio
async def test_relation_focus_requires_endpoint_and_current_version(
    db_session,
    project_novel_id: str,
    location_entity_id: str,
    organization_entity_id: str,
) -> None:
    unrelated_entity = await _create_entity(
        db_session,
        project_novel_id,
        entity_type="character",
        name="无关人物",
    )
    relation = await upsert_relation(
        db_session,
        project_novel_id,
        location_entity_id,
        organization_entity_id,
        "守护",
        description="替城门守夜。",
        relation_kind="social",
    )
    assert relation.updated_at is not None
    focus = {
        "kind": "relation",
        "entity_id": uuid.UUID(location_entity_id),
        "relation_id": uuid.UUID(str(relation.id)),
        "updated_at": relation.updated_at,
    }

    await validate_assistant_world_focus(db_session, project_novel_id, focus)
    material = await read_assistant_world_focus(db_session, project_novel_id, focus)
    assert material["kind"] == "relation"
    assert material["content"]["relation_type"] == "守护"
    assert material["content"]["description"] == "替城门守夜。"
    assert material["content"]["source_name"]
    assert material["content"]["target_name"]
    stale = {**focus, "updated_at": focus["updated_at"] + timedelta(seconds=1)}
    with pytest.raises(ConflictError, match="关系已变化"):
        await validate_assistant_world_focus(db_session, project_novel_id, stale)
    unrelated_focus = {**focus, "entity_id": unrelated_entity.id}
    with pytest.raises(NotFoundError, match="不属于当前对象"):
        await validate_assistant_world_focus(
            db_session, project_novel_id, unrelated_focus
        )
