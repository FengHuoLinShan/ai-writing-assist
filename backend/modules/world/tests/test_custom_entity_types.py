from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select

from core.errors import ConflictError
from modules.project.models import Project
from modules.world.models import (
    Character,
    CoreEntity,
    Event,
    GenericEntityProfile,
    LocationProfile,
    SpeciesProfile,
    WorldBiblePage,
    WorldBiblePageDraft,
)
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityDraftSuggestionPayload,
    CoreEntitySuggestionEditConfirmRequest,
    CoreEntityUpdate,
    EntityPromoteRequest,
    ExtractedEntity,
    WorldProfileUpsertRequest,
)
from modules.world.services.core.entity_service import WorldEntityService
from modules.world.services.core.entity_type_transition_service import (
    EntityTypeTransitionService,
)
from modules.world.services.core.entity_types import (
    normalize_author_entity_type,
    normalize_system_entity_type,
)
from modules.world.services.worldbuilding.profile_service import WorldProfileService
from modules.world.services.worldbuilding.suggestion_queue_service import (
    SuggestionQueueService,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" 宗教/神祇 ", "宗教/神祇"),
        ("Guild·Prime", "guild·prime"),
        ("概念（抽象）", "concept"),
        ("势力/派系", "faction"),
    ],
)
def test_author_entity_type_normalization(raw: str, expected: str) -> None:
    assert normalize_author_entity_type(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "bad\nvalue", "__custom_entity_type__", "x" * 65],
)
def test_author_entity_type_rejects_unsafe_values(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_author_entity_type(raw)


def test_author_schemas_accept_custom_but_ai_schema_remains_system_only() -> None:
    assert (
        CoreEntityCreate(entity_type="宗教/神祇", name="月廷").entity_type == "宗教/神祇"
    )
    assert CoreEntityUpdate(entity_type="Lore·Class").entity_type == "lore·class"
    assert EntityPromoteRequest(entity_type="学派（秘术）").entity_type == "学派（秘术）"
    assert (
        CoreEntitySuggestionEditConfirmRequest(entity_type="宗教/神祇").entity_type
        == "宗教/神祇"
    )
    with pytest.raises(PydanticValidationError):
        ExtractedEntity(entity_type="宗教/神祇", name="月廷")
    with pytest.raises(ValueError):
        normalize_system_entity_type("宗教/神祇")


@pytest.mark.asyncio
async def test_entity_type_catalog_is_project_scoped_and_includes_all_statuses(
    db_session,
) -> None:
    novel_id, other_id = uuid.uuid4(), uuid.uuid4()
    db_session.add_all([Project(id=novel_id, title="A"), Project(id=other_id, title="B")])
    await db_session.flush()
    db_session.add_all(
        [
            CoreEntity(
                novel_id=novel_id, entity_type="宗教/神祇", name="A", status="deprecated"
            ),
            CoreEntity(
                novel_id=novel_id, entity_type="character", name="B", status="canonical"
            ),
            CoreEntity(
                novel_id=other_id,
                entity_type="另一个项目类型",
                name="C",
                status="canonical",
            ),
        ]
    )
    await db_session.flush()

    result = await WorldEntityService().list_entity_types(db_session, str(novel_id))
    values = {item.value: item for item in result.items}

    assert values["species"].kind == "system"
    assert values["group"].kind == "system"
    assert values["faction"].label == "势力/派系"
    assert values["organization"].label == "组织"
    assert values["宗教/神祇"].kind == "custom"
    assert "另一个项目类型" not in values


@pytest.mark.asyncio
async def test_ai_suggestion_creation_rejects_author_custom_type(db_session) -> None:
    novel_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="A"))
    await db_session.flush()
    payload = CoreEntityDraftSuggestionPayload(entity_type="宗教/神祇", name="月廷")

    with pytest.raises(ValueError):
        await SuggestionQueueService().create_core_entity_suggestion(
            db_session,
            novel_id=str(novel_id),
            source_module="test_ai",
            review_group="test",
            payload=payload,
        )


@pytest.mark.asyncio
async def test_strong_generic_roundtrip_restores_profile_snapshot(db_session) -> None:
    novel_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="A"))
    entity = CoreEntity(
        id=entity_id,
        novel_id=novel_id,
        entity_type="location",
        name="星港",
        status="canonical",
    )
    location = LocationProfile(
        novel_id=novel_id,
        entity_id=entity_id,
        status="canonical",
        source="manual",
        confidence=0.8,
        evidence_refs_json=[{"kind": "note"}],
        climate="寒冷",
        resources_json=["星砂"],
        extra_json={"author_note": "保留"},
    )
    db_session.add_all([entity, location])
    await db_session.flush()
    service = EntityTypeTransitionService()

    await service.transition(db_session, entity=entity, new_type="宗教/神祇")
    entity.entity_type = "宗教/神祇"
    await db_session.flush()
    generic = await db_session.scalar(
        select(GenericEntityProfile).where(GenericEntityProfile.entity_id == entity_id)
    )
    assert generic is not None
    assert generic.profile_type == "宗教/神祇"
    assert generic.status == "canonical"
    assert generic.source == "manual"
    assert generic.confidence == 0.8
    assert generic.evidence_refs_json == [{"kind": "note"}]
    assert generic.extra_json["author_note"] == "保留"
    projection = await service.dossier.generic_profile_projection(
        db_session, entity, generic
    )
    assert projection["data_json"]["climate"] == "寒冷"
    assert location.status == "migrated"
    assert "location" in generic.extra_json["_type_migration_v1"]["snapshots"]

    compatibility = await WorldProfileService().get_profile(
        db_session, str(novel_id), str(entity_id)
    )
    await WorldProfileService().upsert_profile(
        db_session,
        str(novel_id),
        str(entity_id),
        WorldProfileUpsertRequest(
            data_json={"教义": "守望星海"},
            expected_dossier_revision=compatibility.expected_dossier_revision,
        ),
    )
    await service.transition(db_session, entity=entity, new_type="location")
    entity.entity_type = "location"
    await db_session.flush()

    assert location.status == "canonical"
    assert location.climate == "寒冷"
    assert location.resources_json == ["星砂"]
    assert location.extra_json["author_note"] == "保留"
    assert location.extra_json["unmapped_generic"]["教义"] == "守望星海"
    assert location.source == "manual"
    assert location.confidence == 0.8
    assert location.evidence_refs_json == [{"kind": "note"}]
    assert generic.status == "migrated"
    assert "宗教/神祇" in generic.extra_json["_type_migration_v1"]["snapshots"]
    journal = generic.extra_json["_type_migration_v1"]
    assert journal["history"][-1]["from_type"] == "宗教/神祇"
    assert journal["history"][-1]["to_type"] == "location"
    assert journal["snapshots"]["location"]["data"]["climate"] == "寒冷"
    assert journal["snapshots"]["宗教/神祇"]["data"] == {"教义": "守望星海"}


@pytest.mark.asyncio
async def test_type_change_rejects_active_profile_that_mismatches_entity_type(
    db_session,
) -> None:
    novel_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="A"))
    entity = CoreEntity(
        id=entity_id,
        novel_id=novel_id,
        entity_type="location",
        name="错配档案对象",
        status="canonical",
    )
    wrong_profile = SpeciesProfile(
        novel_id=novel_id,
        entity_id=entity_id,
        status="canonical",
        origin_summary="不应被迁移吞掉",
    )
    db_session.add_all([entity, wrong_profile])
    await db_session.flush()

    with pytest.raises(ConflictError) as caught:
        await EntityTypeTransitionService().transition(
            db_session,
            entity=entity,
            new_type="宗教/神祇",
        )

    assert caught.value.code == "profile_state_conflict"
    assert caught.value.context == {
        "from_type": "location",
        "to_type": "宗教/神祇",
    }
    assert wrong_profile.status == "canonical"
    generic = await db_session.scalar(
        select(GenericEntityProfile).where(GenericEntityProfile.entity_id == entity_id)
    )
    assert generic is None


@pytest.mark.asyncio
async def test_world_bible_profile_ref_wire_shapes_block_type_change(db_session) -> None:
    novel_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="A"))
    entity = CoreEntity(
        id=entity_id,
        novel_id=novel_id,
        entity_type="location",
        name="星港",
        status="canonical",
    )
    page = WorldBiblePage(
        novel_id=novel_id,
        page_type="location",
        page_key="location-star-port",
        title="星港",
        status="canonical",
        linked_asset_refs_json=[{"type": "profile", "id": str(entity_id)}],
    )
    draft = WorldBiblePageDraft(
        novel_id=novel_id,
        title="星港工作稿",
        page_type="location",
        linked_asset_refs_json=[
            {"source_type": "profile", "source_id": str(entity_id)},
            {"target_type": "profile", "target_id": str(entity_id)},
        ],
    )
    db_session.add_all([entity, page, draft])
    await db_session.flush()

    with pytest.raises(ConflictError) as caught:
        await EntityTypeTransitionService().transition(
            db_session,
            entity=entity,
            new_type="宗教/神祇",
        )

    assert caught.value.code == "entity_type_change_blocked"
    assert caught.value.context == {
        "from_type": "location",
        "to_type": "宗教/神祇",
        "blockers": [{"kind": "active_profile_target_ref", "count": 2}],
    }
    assert str(entity_id) not in str(caught.value.context)


@pytest.mark.asyncio
async def test_generic_profile_id_reference_blocks_type_change(db_session) -> None:
    novel_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="A"))
    entity = CoreEntity(
        id=entity_id,
        novel_id=novel_id,
        entity_type="宗教/神祇",
        name="守望教团",
        status="canonical",
    )
    profile = GenericEntityProfile(
        id=profile_id,
        novel_id=novel_id,
        entity_id=entity_id,
        profile_type="宗教/神祇",
        status="canonical",
    )
    page = WorldBiblePage(
        novel_id=novel_id,
        page_type="custom",
        page_key="watcher-order",
        title="守望教团",
        status="canonical",
        linked_asset_refs_json=[
            {
                "type": "profile",
                "id": f"generic_entity_profiles:{profile_id}",
            }
        ],
    )
    db_session.add_all([entity, profile, page])
    await db_session.flush()

    with pytest.raises(ConflictError) as caught:
        await EntityTypeTransitionService().transition(
            db_session,
            entity=entity,
            new_type="concept",
        )

    assert caught.value.context == {
        "from_type": "宗教/神祇",
        "to_type": "concept",
        "blockers": [{"kind": "active_profile_target_ref", "count": 1}],
    }


@pytest.mark.asyncio
async def test_profile_mutations_request_entity_and_profile_row_locks(db_session) -> None:
    class RecordingProfileService(WorldProfileService):
        def __init__(self) -> None:
            self.lock_calls: list[tuple[str, bool]] = []

        async def _get_entity(self, *args, lock: bool = False, **kwargs):
            self.lock_calls.append(("entity", lock))
            return await super()._get_entity(*args, lock=lock, **kwargs)

        async def _get_generic(self, *args, lock: bool = False, **kwargs):
            self.lock_calls.append(("generic", lock))
            return await super()._get_generic(*args, lock=lock, **kwargs)

        async def _get_strong(self, *args, lock: bool = False, **kwargs):
            self.lock_calls.append(("strong", lock))
            return await super()._get_strong(*args, lock=lock, **kwargs)

    novel_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="A"))
    db_session.add(
        CoreEntity(
            id=entity_id,
            novel_id=novel_id,
            entity_type="location",
            name="星港",
            status="canonical",
        )
    )
    await db_session.flush()
    service = RecordingProfileService()

    await service.upsert_profile(
        db_session,
        str(novel_id),
        str(entity_id),
        WorldProfileUpsertRequest(status="canonical", climate="寒冷"),
    )

    assert service.lock_calls == [
        ("entity", True),
        ("generic", True),
        ("strong", True),
    ]

    legacy_id = uuid.uuid4()
    db_session.add_all(
        [
            CoreEntity(
                id=legacy_id,
                novel_id=novel_id,
                entity_type="species",
                name="旧通用种族",
                status="canonical",
            ),
            GenericEntityProfile(
                novel_id=novel_id,
                entity_id=legacy_id,
                profile_type="species",
                status="canonical",
            ),
        ]
    )
    await db_session.flush()
    service.lock_calls.clear()

    await service.migrate_generic_to_strong(
        db_session,
        str(novel_id),
        str(legacy_id),
    )

    assert service.lock_calls == [
        ("entity", True),
        ("generic", True),
        ("strong", True),
    ]


@pytest.mark.asyncio
async def test_generic_to_strong_migration_preserves_unknowns_and_history(
    db_session,
) -> None:
    novel_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    entity = CoreEntity(
        id=entity_id,
        novel_id=novel_id,
        entity_type="species",
        name="雾生族",
        status="canonical",
    )
    profile = GenericEntityProfile(
        novel_id=novel_id,
        entity_id=entity_id,
        profile_type="species",
        status="canonical",
        source="imported",
        confidence=0.73,
        evidence_refs_json=[{"kind": "source", "id": "book:chapter-2"}],
        data_json={
            "origin_summary": "从雾海迁徙而来",
            "unmapped_field": {"detail": ["保留"]},
        },
        extra_json={
            "author_note": "旧备注",
            "unmapped_generic": {"older_unknown": "keep"},
        },
    )
    db_session.add_all([Project(id=novel_id, title="A"), entity, profile])
    await db_session.flush()

    result = await WorldProfileService().migrate_generic_to_strong(
        db_session, str(novel_id), str(entity_id)
    )

    migrated = await db_session.get(SpeciesProfile, entity_id)
    assert migrated is not None
    assert migrated.status == "canonical"
    assert migrated.origin_summary == "从雾海迁徙而来"
    assert migrated.source == "imported"
    assert migrated.confidence == 0.73
    assert migrated.evidence_refs_json == [{"kind": "source", "id": "book:chapter-2"}]
    assert migrated.extra_json["author_note"] == "旧备注"
    assert migrated.extra_json["unmapped_generic"] == {
        "unmapped_field": {"detail": ["保留"]},
        "older_unknown": "keep",
    }
    assert profile.status == "migrated"
    assert profile.data_json == {}
    history = profile.extra_json["_generic_to_strong_history_v1"]
    assert len(history) == 1
    assert history[0]["source"] == "imported"
    assert history[0]["confidence"] == 0.73
    assert history[0]["evidence_refs_json"] == [
        {"kind": "source", "id": "book:chapter-2"}
    ]
    assert history[0]["extra_json"]["unmapped_generic"] == {"older_unknown": "keep"}
    assert result.fields["origin_summary"] == "从雾海迁徙而来"


@pytest.mark.asyncio
async def test_generic_to_strong_migration_keeps_existing_strong_values_and_unknowns(
    db_session,
) -> None:
    novel_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    entity = CoreEntity(
        id=entity_id,
        novel_id=novel_id,
        entity_type="species",
        name="雾生族",
        status="canonical",
    )
    generic = GenericEntityProfile(
        novel_id=novel_id,
        entity_id=entity_id,
        profile_type="species",
        status="canonical",
        data_json={"origin_summary": "通用来源", "unknown": "留存"},
    )
    strong = SpeciesProfile(
        novel_id=novel_id,
        entity_id=entity_id,
        status="canonical",
        origin_summary="强档案当前值",
        extra_json={"unmapped_generic": {"strong_unknown": "保留"}},
    )
    db_session.add_all([Project(id=novel_id, title="A"), entity, generic, strong])
    await db_session.flush()

    await WorldProfileService().migrate_generic_to_strong(
        db_session, str(novel_id), str(entity_id)
    )

    assert strong.origin_summary == "强档案当前值"
    assert strong.extra_json["unmapped_generic"] == {
        "unknown": "留存",
        "strong_unknown": "保留",
    }
    assert generic.status == "migrated"


@pytest.mark.asyncio
async def test_character_extension_blocks_type_change_without_exposing_ids(
    db_session,
) -> None:
    novel_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="A"))
    entity = CoreEntity(
        id=entity_id,
        novel_id=novel_id,
        entity_type="character",
        name="阿澜",
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()
    db_session.add(
        Character(
            entity_id=entity_id,
            novel_id=novel_id,
            name="阿澜",
            status="canonical",
        )
    )
    await db_session.flush()

    with pytest.raises(ConflictError) as caught:
        await EntityTypeTransitionService().transition(
            db_session,
            entity=entity,
            new_type="宗教/神祇",
        )

    assert caught.value.code == "entity_type_change_blocked"
    assert caught.value.context == {
        "from_type": "character",
        "to_type": "宗教/神祇",
        "blockers": [{"kind": "character_extension", "count": 1}],
    }
    assert str(entity_id) not in str(caught.value.context)


@pytest.mark.asyncio
async def test_only_live_event_extension_blocks_type_change(db_session) -> None:
    novel_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="A"))
    event_entity = CoreEntity(
        novel_id=novel_id, entity_type="event", name="城门之战", status="canonical"
    )
    location = CoreEntity(
        novel_id=novel_id, entity_type="location", name="北城门", status="canonical"
    )
    db_session.add_all([event_entity, location])
    await db_session.flush()
    event = Event(
        entity_id=event_entity.id,
        novel_id=novel_id,
        source_chapter_id=uuid.uuid4(),
        location_entity_id=location.id,
        timeline_order=1,
    )
    db_session.add(event)
    await db_session.flush()
    service = EntityTypeTransitionService()

    with pytest.raises(ConflictError) as event_blocked:
        await service.transition(db_session, entity=event_entity, new_type="faction")
    with pytest.raises(ConflictError) as location_blocked:
        await service.transition(db_session, entity=location, new_type="faction")
    assert event_blocked.value.context["blockers"] == [
        {"kind": "event_extension", "count": 1}
    ]
    assert location_blocked.value.context["blockers"] == [
        {"kind": "event_location", "count": 1}
    ]

    # 已删除（deprecated）的事件扩展只是历史，不再阻止改类型。
    event.status = "deprecated"
    await db_session.flush()
    await service.transition(db_session, entity=event_entity, new_type="faction")
    await service.transition(db_session, entity=location, new_type="faction")
