import uuid

import pytest

from infrastructure.tasks.models import AsyncTask
from modules.imports.worldbuilding_risk import ImportWriteRiskClassifier
from modules.world.models import Character, EntityRelation
from modules.world.schemas import (
    CreationSuggestionCreate,
    WorldBiblePageCreate,
    WorldProfileUpsertRequest,
)
from modules.world.services.worldbuilding.worldbuilding_service import (
    KnowledgeTagService,
    ProjectionRefreshConflictError,
    SuggestionAlreadyProcessedError,
    SuggestionQueueService,
    WorldBibleService,
    WorldProfileService,
)
from shared.target_ref import TargetRef
from tests.utils import _create_entity


def test_target_ref_hash_normalizes_empty_path() -> None:
    left = TargetRef(target_type="profile", target_id="species:1", target_path=None)
    right = TargetRef(target_type="profile", target_id="species:1", target_path="")
    assert left.canonical_json() == right.canonical_json()
    assert left.target_hash() == right.target_hash()


def test_target_ref_rejects_wildcards() -> None:
    with pytest.raises(ValueError):
        TargetRef(target_type="profile", target_id="species:1", target_path="items[*]")


@pytest.mark.asyncio
async def test_profile_registry_rejects_generic_for_strong_entity(
    db_session,
    project_novel_id: str,
) -> None:
    entity = await _create_entity(db_session, project_novel_id, "species", "精灵")
    service = WorldProfileService()
    profile = await service.upsert_profile(
        db_session,
        project_novel_id,
        str(entity.id),
        WorldProfileUpsertRequest(status="confirmed", lifespan="永生"),
    )
    assert profile.profile_kind == "strong"
    assert profile.fields["lifespan"] == "永生"


@pytest.mark.asyncio
async def test_projection_refresh_task_lifecycle_conflict(
    db_session,
    project_novel_id: str,
) -> None:
    service = WorldBibleService()
    page = await service.create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            title="世界基本背景",
            free_text="星海帝国建立于长夜之后。",
        ),
    )
    task_id, status, existing = await service.refresh_projection_task(
        db_session,
        project_novel_id,
        page.id,
        projection_type="context_brief",
    )
    assert status == "pending"
    assert existing is False
    task = await db_session.get(AsyncTask, uuid.UUID(task_id))
    task.status = "done"
    await db_session.flush()
    with pytest.raises(ProjectionRefreshConflictError):
        await service.refresh_projection_task(
            db_session,
            project_novel_id,
            page.id,
            projection_type="context_brief",
        )


@pytest.mark.asyncio
async def test_suggestion_duplicate_confirm_returns_domain_error(
    db_session,
    project_novel_id: str,
) -> None:
    service = SuggestionQueueService()
    suggestion = await service.create(
        db_session,
        CreationSuggestionCreate(
            novel_id=project_novel_id,
            source_module="imports",
            review_group="import_knowledge",
            target_type="reader_reveal_policy",
            risk_level="high",
        ),
    )
    accepted = await service.confirm(db_session, project_novel_id, suggestion.id)
    assert accepted.status == "accepted"
    with pytest.raises(SuggestionAlreadyProcessedError):
        await service.confirm(db_session, project_novel_id, suggestion.id)


@pytest.mark.asyncio
async def test_derived_tag_sync_reads_character_meta_and_member_relation(
    db_session,
    project_novel_id: str,
) -> None:
    character_entity = await _create_entity(
        db_session,
        project_novel_id,
        "character",
        "阿洛",
    )
    species = await _create_entity(db_session, project_novel_id, "species", "精灵")
    faction = await _create_entity(db_session, project_novel_id, "faction", "星盟")
    location = await _create_entity(db_session, project_novel_id, "location", "星港")
    db_session.add(
        Character(
            entity_id=character_entity.id,
            novel_id=uuid.UUID(hex=project_novel_id),
            name="阿洛",
            aliases=[],
            meta={
                "worldbuilding": {
                    "species_entity_id": str(species.id),
                    "location_entity_id": str(location.id),
                }
            },
            status="canonical",
        )
    )
    db_session.add(
        EntityRelation(
            novel_id=uuid.UUID(hex=project_novel_id),
            source_id=character_entity.id,
            target_id=faction.id,
            relation_type="member_of",
            status="canonical",
        )
    )
    await db_session.flush()
    stats = await KnowledgeTagService().sync_derived_tags(
        db_session,
        project_novel_id,
        str(character_entity.id),
    )
    assert stats["added"] == 3


def test_import_risk_classifier_unknown_and_draft_source_are_high() -> None:
    classifier = ImportWriteRiskClassifier()
    assert classifier.classify({"target_type": "unknown"}).risk_level == "high"
    decision = classifier.classify(
        {
            "target_type": "derived_public_tag",
            "source_status": "draft",
            "profession_confirmed": True,
        }
    )
    assert decision.risk_level == "high"
