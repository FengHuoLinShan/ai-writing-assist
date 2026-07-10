import uuid

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select

from core.errors import NotFoundError, ValidationError
from infrastructure.llm.schemas import LLMCallResponse
from infrastructure.tasks.models import AsyncTask
from modules.imports.worldbuilding_risk import ImportWriteRiskClassifier
from modules.world.models import (
    Character,
    CoreEntity,
    CreationSuggestion,
    EntityRelation,
    WorldBiblePage,
    WorldBiblePageRevision,
)
from modules.world.schemas import (
    CoreEntityDraftSuggestionPayload,
    CoreEntitySuggestionEditConfirmRequest,
    CreationSuggestionCreate,
    EntityMergeRequest,
    EntityResolveAsAliasRequest,
    WorldBibleAiGenerateRequest,
    WorldBiblePageCreate,
    WorldProfileUpsertRequest,
)
from modules.world.services.worldbuilding.world_bible_ai_generation_service import (
    WorldBibleAiGenerationService,
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


class _FakeBibleAiClient:
    provider = "fake-provider"

    async def generate(self, request):
        return LLMCallResponse(
            content="可以把这一页拆成历史与规则两段。",
            model=request.model,
            provider=self.provider,
        )

    async def generate_structured(self, request, schema, **_kwargs):
        name = schema.__name__
        if name == "GeneratedWorldBiblePagePatchOutput":
            return schema(
                append_text="补写内容：星海帝国以长夜为纪元。",
                reason="补全背景",
            )
        if name == "GeneratedWorldBibleNewPageOutput":
            return schema(
                title="星海规则",
                page_type="rule",
                free_text="航道规则与禁忌。",
            )
        return schema(
            name="星海帝国",
            summary="长夜之后建立的跨星域政体，维系航道秩序。",
            public_info="以星港和航道税维持统治。",
            hidden_truth="长夜并未真正结束。",
            details={"hook": "长夜遗产"},
        )


def test_target_ref_hash_normalizes_empty_path() -> None:
    left = TargetRef(target_type="profile", target_id="species:1", target_path=None)
    right = TargetRef(target_type="profile", target_id="species:1", target_path="")
    assert left.canonical_json() == right.canonical_json()
    assert left.target_hash() == right.target_hash()


def test_target_ref_rejects_wildcards() -> None:
    with pytest.raises(ValueError):
        TargetRef(target_type="profile", target_id="species:1", target_path="items[*]")


def test_worldbuilding_service_hub_reexports_concept_services_by_identity() -> None:
    from modules.world.services.worldbuilding import (
        activation_preview_service,
        conflict_queue_service,
        knowledge_tag_service,
        profile_service,
        suggestion_queue_service,
        world_bible_service,
        worldbuilding_service,
    )

    assert (
        worldbuilding_service.ActivationPreviewService
        is activation_preview_service.ActivationPreviewService
    )
    assert (
        worldbuilding_service.ConflictQueueService
        is conflict_queue_service.ConflictQueueService
    )
    assert (
        worldbuilding_service.KnowledgeTagService
        is knowledge_tag_service.KnowledgeTagService
    )
    assert (
        worldbuilding_service.WorldProfileService is profile_service.WorldProfileService
    )
    assert (
        worldbuilding_service.SuggestionQueueService
        is suggestion_queue_service.SuggestionQueueService
    )
    assert (
        worldbuilding_service.SuggestionAlreadyProcessedError
        is suggestion_queue_service.SuggestionAlreadyProcessedError
    )
    assert (
        worldbuilding_service.WorldBibleService is world_bible_service.WorldBibleService
    )
    assert (
        worldbuilding_service.ProjectionRefreshConflictError
        is world_bible_service.ProjectionRefreshConflictError
    )


@pytest.mark.asyncio
async def test_worldbuilding_service_old_hub_monkeypatch_affects_task_consumer(
    monkeypatch,
) -> None:
    from modules.world.tasks import handle_world_bible_projection_refresh

    calls: list[tuple[str, str, str]] = []

    class FakeProjection:
        id = "projection-1"
        projection_type = "context_brief"
        status = "ready"
        token_estimate = 12
        error_kind = None
        error_summary = None
        stale = False

    class FakeWorldBibleService:
        async def refresh_projection_now(
            self,
            db,
            *,
            novel_id: str,
            page_id: str,
            projection_type: str,
        ):
            calls.append((novel_id, page_id, projection_type))
            return FakeProjection()

    class FakeTask:
        meta = {
            "novel_id": "novel-1",
            "page_id": "page-1",
            "projection_type": "context_brief",
        }

        def __init__(self) -> None:
            self.progress: list[float] = []

        def update_progress(self, value: float) -> None:
            self.progress.append(value)

    monkeypatch.setattr(
        "modules.world.services.worldbuilding.worldbuilding_service.WorldBibleService",
        FakeWorldBibleService,
    )
    task = FakeTask()

    result = await handle_world_bible_projection_refresh(None, task)

    assert calls == [("novel-1", "page-1", "context_brief")]
    assert task.progress == [0.15, 1.0]
    assert result["projection_id"] == "projection-1"


def test_worldbuilding_service_old_hub_monkeypatch_affects_default_collaborators(
    monkeypatch,
) -> None:
    class FakeWorldProfileService:
        pass

    class FakeWorldBibleService:
        pass

    class FakeSuggestionQueueService:
        pass

    monkeypatch.setattr(
        "modules.world.services.worldbuilding.worldbuilding_service.WorldProfileService",
        FakeWorldProfileService,
    )
    monkeypatch.setattr(
        "modules.world.services.worldbuilding.worldbuilding_service.WorldBibleService",
        FakeWorldBibleService,
    )
    monkeypatch.setattr(
        "modules.world.services.worldbuilding.worldbuilding_service.SuggestionQueueService",
        FakeSuggestionQueueService,
    )

    suggestion_service = SuggestionQueueService()
    ai_service = WorldBibleAiGenerationService()

    assert isinstance(suggestion_service._profiles, FakeWorldProfileService)  # noqa: SLF001
    assert isinstance(suggestion_service._bible, FakeWorldBibleService)  # noqa: SLF001
    assert isinstance(ai_service._bible_service, FakeWorldBibleService)  # noqa: SLF001
    assert isinstance(ai_service._suggestions, FakeSuggestionQueueService)  # noqa: SLF001


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
            target_type="core_entity",
            risk_level="high",
            payload_json={
                "entity_type": "concept",
                "name": "长夜纪元",
            },
        ),
    )
    accepted = await service.confirm(db_session, project_novel_id, suggestion.id)
    assert accepted.status == "accepted"
    with pytest.raises(SuggestionAlreadyProcessedError):
        await service.confirm(db_session, project_novel_id, suggestion.id)
    with pytest.raises(SuggestionAlreadyProcessedError):
        await service.reject(db_session, project_novel_id, suggestion.id)


@pytest.mark.asyncio
async def test_reject_archives_compatibility_shadow_and_blocks_repeat_decisions(
    db_session,
    project_novel_id: str,
) -> None:
    service = SuggestionQueueService()
    suggestion, shadow = await service.create_core_entity_suggestion(
        db_session,
        novel_id=project_novel_id,
        source_module="world_extraction",
        review_group="manual_extract",
        payload=CoreEntityDraftSuggestionPayload(
            entity_type="concept",
            name="废弃的建议",
        ),
        compatibility_status="candidate",
        compatibility_created_by="ai_import",
    )
    assert shadow is not None

    rejected = await service.reject(db_session, project_novel_id, suggestion.id)

    stored_shadow = await db_session.get(CoreEntity, uuid.UUID(shadow.id))
    assert rejected.status == "rejected"
    assert rejected.result_ref_json["status"] == "archived"
    assert stored_shadow.status == "ignored"
    assert stored_shadow.content_json["_meta"]["needs_review"] is False
    assert (
        stored_shadow.content_json["_meta"]["reviewed_from"]
        == "creation_suggestion_reject"
    )
    with pytest.raises(SuggestionAlreadyProcessedError):
        await service.reject(db_session, project_novel_id, suggestion.id)
    with pytest.raises(SuggestionAlreadyProcessedError):
        await service.confirm(db_session, project_novel_id, suggestion.id)


@pytest.mark.asyncio
async def test_compatibility_shadow_cannot_bypass_authoritative_suggestion_queue(
    db_session,
    project_novel_id: str,
) -> None:
    from modules.world.schemas import (
        CoreEntityUpdate,
        EntityPromoteRequest,
        EntityRelationCreate,
    )
    from modules.world.services.core.dedup_service import EntityDedupService
    from modules.world.services.core.entity_alias_service import EntityAliasService
    from modules.world.services.core.entity_relation_service import (
        EntityRelationService,
    )
    from modules.world.services.core.entity_service import WorldEntityService

    service = SuggestionQueueService()
    suggestion, shadow = await service.create_core_entity_suggestion(
        db_session,
        novel_id=project_novel_id,
        source_module="world_extraction",
        review_group="manual_extract",
        payload=CoreEntityDraftSuggestionPayload(
            entity_type="concept",
            name="待处理星门",
        ),
        compatibility_status="candidate",
        compatibility_created_by="ai_import",
    )
    assert shadow is not None
    entities = WorldEntityService()

    with pytest.raises(ValidationError, match="待处理建议"):
        await entities.promote(
            db_session,
            shadow.id,
            EntityPromoteRequest(),
            novel_id=project_novel_id,
        )
    with pytest.raises(ValidationError, match="待处理建议"):
        await entities.update(
            db_session,
            shadow.id,
            CoreEntityUpdate(status="ignored"),
            novel_id=project_novel_id,
        )
    with pytest.raises(ValidationError, match="待处理建议"):
        await entities.delete(db_session, shadow.id, novel_id=project_novel_id)

    target = await _create_entity(
        db_session,
        project_novel_id,
        "concept",
        "已采用星门",
    )
    with pytest.raises(ValidationError, match="authoritative suggestion queue"):
        await EntityDedupService().merge_candidate_into_entity(
            db_session,
            project_novel_id,
            shadow.id,
            str(target.id),
        )
    with pytest.raises(ValidationError, match="authoritative suggestion queue"):
        await EntityAliasService().resolve_candidate_as_alias(
            db_session,
            project_novel_id,
            shadow.id,
            target_entity_id=str(target.id),
            alias="星门",
        )
    with pytest.raises(ValidationError, match="authoritative suggestion queue"):
        await EntityAliasService().create_alias(
            db_session,
            project_novel_id,
            shadow.id,
            "影子别名",
        )
    with pytest.raises(ValidationError, match="authoritative suggestion"):
        await EntityRelationService().create(
            db_session,
            project_novel_id,
            EntityRelationCreate(
                source_id=shadow.id,
                target_id=str(target.id),
                relation_type="related_to",
            ),
        )
    with pytest.raises(ValidationError, match="authoritative suggestion"):
        await EntityRelationService().create_or_merge(
            db_session,
            project_novel_id,
            EntityRelationCreate(
                source_id=shadow.id,
                target_id=str(target.id),
                relation_type="related_to",
            ),
        )
    with pytest.raises(ValidationError, match="authoritative suggestion"):
        await EntityRelationService().upsert(
            db_session,
            project_novel_id,
            shadow.id,
            str(target.id),
            "related_to",
        )

    stored_suggestion = await db_session.get(
        CreationSuggestion,
        uuid.UUID(suggestion.id),
    )
    stored_shadow = await db_session.get(CoreEntity, uuid.UUID(shadow.id))
    assert stored_suggestion.status == "pending"
    assert stored_shadow.status == "candidate"

    accepted = await service.confirm(db_session, project_novel_id, suggestion.id)
    await db_session.refresh(stored_shadow)
    assert accepted.status == "accepted"
    assert stored_shadow.status == "canonical"
    assert stored_shadow.content_json["_meta"]["compatibility_shadow"] is False
    assert stored_shadow.content_json["_meta"]["compatibility_shadow_adopted"] is True

    updated = await entities.update(
        db_session,
        shadow.id,
        CoreEntityUpdate(summary="采用后可编辑"),
        novel_id=project_novel_id,
    )
    assert updated.summary == "采用后可编辑"


@pytest.mark.asyncio
async def test_core_entity_suggestion_can_be_edited_and_adopted_atomically(
    db_session,
    project_novel_id: str,
) -> None:
    service = SuggestionQueueService()
    suggestion, shadow = await service.create_core_entity_suggestion(
        db_session,
        novel_id=project_novel_id,
        source_module="world_extraction",
        review_group="manual_extract",
        payload=CoreEntityDraftSuggestionPayload(
            entity_type="concept",
            name="旧名",
            summary="旧概要",
        ),
        compatibility_status="candidate",
    )
    assert shadow is not None

    accepted = await service.edit_and_confirm_core_entity(
        db_session,
        project_novel_id,
        suggestion.id,
        CoreEntitySuggestionEditConfirmRequest(
            name="新名",
            summary="编辑后采用的概要",
        ),
    )

    stored_shadow = await db_session.get(CoreEntity, uuid.UUID(shadow.id))
    assert accepted.status == "accepted"
    assert accepted.payload_json["name"] == "新名"
    assert stored_shadow.name == "新名"
    assert stored_shadow.summary == "编辑后采用的概要"
    assert stored_shadow.status == "canonical"
    assert stored_shadow.content_json["_meta"]["compatibility_shadow"] is False


@pytest.mark.asyncio
async def test_core_entity_suggestion_can_merge_into_adopted_entity(
    db_session,
    project_novel_id: str,
) -> None:
    target = await _create_entity(
        db_session,
        project_novel_id,
        "concept",
        "星门",
    )
    service = SuggestionQueueService()
    suggestion, shadow = await service.create_core_entity_suggestion(
        db_session,
        novel_id=project_novel_id,
        source_module="world_extraction",
        review_group="manual_extract",
        payload=CoreEntityDraftSuggestionPayload(
            entity_type="concept",
            name="古代星门",
            summary="失落文明留下的星门。",
        ),
        compatibility_status="candidate",
    )
    assert shadow is not None

    accepted = await service.merge_core_entity(
        db_session,
        project_novel_id,
        suggestion.id,
        EntityMergeRequest(target_entity_id=str(target.id)),
    )

    stored_shadow = await db_session.get(CoreEntity, uuid.UUID(shadow.id))
    await db_session.refresh(target)
    assert accepted.status == "accepted"
    assert accepted.result_ref_json["type"] == "core_entity_merge"
    assert accepted.result_ref_json["id"] == str(target.id)
    assert stored_shadow.status == "merged"
    assert stored_shadow.content_json["merged_into"] == str(target.id)
    assert "失落文明留下的星门" in (target.summary or "")


@pytest.mark.asyncio
async def test_core_entity_suggestion_can_become_alias_of_adopted_entity(
    db_session,
    project_novel_id: str,
) -> None:
    target = await _create_entity(
        db_session,
        project_novel_id,
        "character",
        "林岚",
    )
    service = SuggestionQueueService()
    suggestion, shadow = await service.create_core_entity_suggestion(
        db_session,
        novel_id=project_novel_id,
        source_module="world_extraction",
        review_group="manual_extract",
        payload=CoreEntityDraftSuggestionPayload(
            entity_type="character",
            name="岚姐",
        ),
        compatibility_status="candidate",
    )
    assert shadow is not None

    accepted = await service.resolve_core_entity_as_alias(
        db_session,
        project_novel_id,
        suggestion.id,
        EntityResolveAsAliasRequest(
            target_entity_id=str(target.id),
            alias="岚姐",
        ),
    )

    stored_shadow = await db_session.get(CoreEntity, uuid.UUID(shadow.id))
    await db_session.refresh(target)
    aliases = target.content_json.get("aliases") or []
    assert accepted.status == "accepted"
    assert accepted.result_ref_json["type"] == "core_entity_alias"
    assert stored_shadow.status == "merged"
    assert stored_shadow.content_json["resolved_as"] == "alias"
    assert any(item.get("alias") == "岚姐" for item in aliases)


@pytest.mark.asyncio
async def test_suggestion_unknown_target_type_is_rejected_before_write(
    db_session,
    project_novel_id: str,
) -> None:
    with pytest.raises(ValidationError, match="Unsupported suggestion target_type"):
        await SuggestionQueueService().create(
            db_session,
            CreationSuggestionCreate(
                novel_id=project_novel_id,
                target_type="reader_reveal_policy",
            ),
        )

    count = (
        await db_session.execute(select(func.count(CreationSuggestion.id)))
    ).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_world_bible_ai_chat_does_not_create_suggestion(
    db_session,
    project_novel_id: str,
) -> None:
    page = await WorldBibleService().create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            title="世界基本背景",
            free_text="星海帝国建立于长夜之后。",
        ),
    )
    before = (
        await db_session.execute(select(func.count(CreationSuggestion.id)))
    ).scalar_one()
    result = await WorldBibleAiGenerationService(
        llm_client=_FakeBibleAiClient()
    ).generate(
        db_session,
        project_novel_id,
        page.id,
        WorldBibleAiGenerateRequest(
            output_target="chat",
            messages=[{"role": "user", "content": "帮我整理这一页"}],
        ),
    )

    assert "历史与规则" in result.reply
    after = (
        await db_session.execute(select(func.count(CreationSuggestion.id)))
    ).scalar_one()
    assert after == before


@pytest.mark.asyncio
async def test_world_bible_page_patch_suggestion_confirm_updates_page_and_revision(
    db_session,
    project_novel_id: str,
) -> None:
    page = await WorldBibleService().create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            title="世界基本背景",
            free_text="星海帝国建立于长夜之后。",
        ),
    )
    result = await WorldBibleAiGenerationService(
        llm_client=_FakeBibleAiClient()
    ).generate(
        db_session,
        project_novel_id,
        page.id,
        WorldBibleAiGenerateRequest(output_target="page_patch"),
    )

    suggestion_id = result.suggestions[0].id
    accepted = await SuggestionQueueService().confirm(
        db_session,
        project_novel_id,
        suggestion_id,
    )

    assert accepted.status == "accepted"
    refreshed = await db_session.get(WorldBiblePage, uuid.UUID(page.id))
    assert "补写内容" in refreshed.free_text
    assert refreshed.version_number == 2
    revisions = (
        (
            await db_session.execute(
                select(WorldBiblePageRevision).where(
                    WorldBiblePageRevision.page_id == uuid.UUID(page.id)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(revisions) == 1
    assert revisions[0].revision_reason == "ai_suggestion"


@pytest.mark.asyncio
async def test_world_bible_new_page_and_object_draft_suggestions_confirm(
    db_session,
    project_novel_id: str,
) -> None:
    page = await WorldBibleService().create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            title="世界基本背景",
            free_text="星海帝国建立于长夜之后。",
        ),
    )
    service = WorldBibleAiGenerationService(llm_client=_FakeBibleAiClient())
    new_page = await service.generate(
        db_session,
        project_novel_id,
        page.id,
        WorldBibleAiGenerateRequest(output_target="new_page"),
    )
    object_draft = await service.generate(
        db_session,
        project_novel_id,
        page.id,
        WorldBibleAiGenerateRequest(output_target="world_object_draft"),
    )

    page_accept = await SuggestionQueueService().confirm(
        db_session,
        project_novel_id,
        new_page.suggestions[0].id,
    )
    object_accept = await SuggestionQueueService().confirm(
        db_session,
        project_novel_id,
        object_draft.suggestions[0].id,
    )

    created_page = await db_session.get(
        WorldBiblePage,
        uuid.UUID(page_accept.result_ref_json["id"]),
    )
    entity = await db_session.get(
        CoreEntity,
        uuid.UUID(object_accept.result_ref_json["id"]),
    )
    assert created_page.title == "星海规则"
    assert created_page.status == "confirmed"
    assert entity.status == "canonical"
    assert entity.approved_by == "manual"
    assert entity.created_by == "ai_world_bible"
    assert entity.content_json["_meta"]["source_refs"][0]["page_id"] == page.id


@pytest.mark.asyncio
async def test_relation_and_alias_suggestions_use_validated_domain_handlers(
    db_session,
    project_novel_id: str,
) -> None:
    source = await _create_entity(
        db_session,
        project_novel_id,
        "character",
        "沈砚",
    )
    target = await _create_entity(
        db_session,
        project_novel_id,
        "organization",
        "巡夜司",
    )
    service = SuggestionQueueService()
    relation_suggestion = await service.create(
        db_session,
        CreationSuggestionCreate(
            novel_id=project_novel_id,
            source_module="imports",
            review_group="phase2",
            target_type="entity_relation",
            payload_json={
                "source_id": str(source.id),
                "target_id": str(target.id),
                "relation_type": "member_of",
                "description": "沈砚加入巡夜司。",
            },
            evidence_refs_json=[{"scene_id": "scene-1"}],
        ),
    )
    alias_suggestion = await service.create(
        db_session,
        CreationSuggestionCreate(
            novel_id=project_novel_id,
            source_module="imports",
            review_group="phase2",
            target_type="entity_alias",
            payload_json={
                "entity_id": str(source.id),
                "alias": "夜巡人",
                "alias_type": "title",
                "confidence": 0.88,
            },
        ),
    )

    accepted_relation = await service.confirm(
        db_session,
        project_novel_id,
        relation_suggestion.id,
    )
    accepted_alias = await service.confirm(
        db_session,
        project_novel_id,
        alias_suggestion.id,
    )

    relation = await db_session.get(
        EntityRelation,
        uuid.UUID(accepted_relation.result_ref_json["id"]),
    )
    await db_session.refresh(source)
    alias = next(
        item for item in source.content_json["aliases"] if item["alias"] == "夜巡人"
    )
    assert relation.status == "canonical"
    assert relation.review_meta["source"] == "imports"
    assert accepted_relation.display_state == "archived"
    assert alias["status"] == "canonical"
    assert alias["source"] == "imports"
    assert accepted_alias.result_ref_json["entity_id"] == str(source.id)


@pytest.mark.asyncio
async def test_world_bible_bad_suggestion_payload_does_not_write(
    db_session,
    project_novel_id: str,
) -> None:
    service = SuggestionQueueService()
    with pytest.raises(PydanticValidationError):
        await service.create(
            db_session,
            CreationSuggestionCreate(
                novel_id=project_novel_id,
                source_module="world_bible",
                review_group="world_bible_ai",
                target_type="world_bible_page_patch",
                payload_json={"page_id": "not-a-page"},
            ),
        )

    suggestion = CreationSuggestion(
        novel_id=uuid.UUID(hex=project_novel_id),
        source_module="world_bible",
        review_group="world_bible_ai",
        target_type="world_bible_page_patch",
        payload_json={"page_id": "not-a-page"},
        status="pending",
    )
    db_session.add(suggestion)
    await db_session.flush()

    with pytest.raises(PydanticValidationError):
        await service.confirm(
            db_session,
            project_novel_id,
            str(suggestion.id),
        )
    stored = await db_session.get(CreationSuggestion, suggestion.id)
    assert stored.status == "pending"


@pytest.mark.asyncio
async def test_world_bible_suggestion_confirm_rejects_cross_novel_id(
    db_session,
    two_projects: tuple[str, str],
) -> None:
    novel_id, other_novel_id = two_projects
    page = await WorldBibleService().create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=novel_id,
            title="世界基本背景",
            free_text="原始正文。",
        ),
    )
    suggestion = await SuggestionQueueService().create(
        db_session,
        CreationSuggestionCreate(
            novel_id=novel_id,
            source_module="world_bible",
            review_group="world_bible_ai",
            target_type="world_bible_page_patch",
            payload_json={
                "page_id": page.id,
                "append_text": "不应跨项目写入。",
                "source_refs": [],
            },
        ),
    )

    with pytest.raises(NotFoundError):
        await SuggestionQueueService().confirm(
            db_session,
            other_novel_id,
            suggestion.id,
        )
    stored = await db_session.get(CreationSuggestion, uuid.UUID(suggestion.id))
    assert stored.status == "pending"
    refreshed = await db_session.get(WorldBiblePage, uuid.UUID(page.id))
    assert refreshed.free_text == "原始正文。"


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
