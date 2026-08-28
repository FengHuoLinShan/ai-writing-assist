"""
World API 路由 — v3 因果时空网

提供核心实体、事件、关系、版本、人物的 RESTful API。
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from fastapi.routing import APIRoute
from pydantic import ValidationError as PydanticValidationError

from core.api_params import NovelIdQuery
from core.config import get_settings
from core.csrf import require_xhr_request
from core.dependencies import DbSession
from core.errors import ConflictError, DomainError
from infrastructure.tasks.facade import (
    enqueue_task_with_optional_operation,
    get_operation_task,
)
from modules.account.facade import current_account_id
from modules.evidence.facade import attach_result_ref, require_fresh_confirmation
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    require_active_project,
)
from modules.project.facade import (
    require_active_project_exclusive as _require_active_project_exclusive,
)
from modules.world.authority import (
    CanonAdmissionPreviewRequest,
    CanonAdmissionPreviewResponse,
    CanonAdmissionRequest,
    CanonHeadResponse,
    CanonRevertRequest,
    CanonRevisionResponse,
    RevertPreviewInputV1,
)
from modules.world.entity_fusion import WorldEntityFusionService
from modules.world.schemas import (
    AliasKind,
    AskWorldCitationOpenRequest,
    AskWorldCitationOpenResponse,
    AskWorldQuestionRequest,
    AskWorldResponse,
    AskWorldSaveRequest,
    AskWorldSaveResponse,
    CharacterCreate,
    CharacterKnowledgeCreate,
    CharacterKnowledgeListResponse,
    CharacterKnowledgeResponse,
    CharacterKnowledgeUpdate,
    CharacterListResponse,
    CharacterResponse,
    CharacterUpdate,
    ConflictQueueListResponse,
    ConflictResolveRequest,
    CoreEntityCreate,
    CoreEntityListResponse,
    CoreEntityResponse,
    CoreEntitySuggestionEditConfirmRequest,
    CoreEntityUpdate,
    CreationSuggestionListResponse,
    CreationSuggestionResponse,
    EntityAliasCreate,
    EntityAliasEditRequest,
    EntityAliasReviewBatchRequest,
    EntityAliasReviewGroupListResponse,
    EntityAliasUpdate,
    EntityFusionApplyRequest,
    EntityFusionApplyResponse,
    EntityFusionSuggestionRequest,
    EntityFusionSuggestionResponse,
    EntityMergeRequest,
    EntityMergeResponse,
    EntityPromoteRequest,
    EntityPromoteResponse,
    EntityRelationCreate,
    EntityRelationListResponse,
    EntityRelationResponse,
    EntityRelationReviewBatchRequest,
    EntityRelationReviewEditRequest,
    EntityRelationReviewGroupListResponse,
    EntityRelationUpdate,
    EntityResolveAsAliasRequest,
    EntityRevisionListResponse,
    EntityRollbackRequest,
    EntityRollbackResponse,
    EntityTypeCatalogResponse,
    EventCreate,
    EventListResponse,
    EventResponse,
    EventUpdate,
    GenerationPromptTemplateCreate,
    GenerationPromptTemplateListResponse,
    GenerationPromptTemplateResponse,
    GenerationPromptTemplateRevisionResponse,
    GenerationPromptTemplateUpdate,
    KnowledgeTagExclusionRequest,
    KnowledgeTagExclusionResponse,
    ProjectionRefreshResponse,
    PromptTemplateCopyRequest,
    PromptTemplatePreviewRequest,
    PromptTemplatePreviewResponse,
    PromptTemplateValidateRequest,
    PromptTemplateValidateResponse,
    RelationKind,
    ReviewBatchResponse,
    ReviewTypeCatalogResponse,
    SuggestionDecisionResponse,
    TextArchiveSeedRequest,
    TextArchiveSeedResponse,
    WorldAdoptionPackageApplyRequest,
    WorldAdoptionPackagePreviewResponse,
    WorldAdoptionPackageSaveRequest,
    WorldAliasRelationExtractRequest,
    WorldAliasRelationExtractResponse,
    WorldBibleApplyTemplateRequest,
    WorldBibleCategoryCreate,
    WorldBibleCategoryListResponse,
    WorldBibleCategoryResponse,
    WorldBibleCategoryUpdate,
    WorldBiblePageCreate,
    WorldBiblePageDraftCreate,
    WorldBiblePageDraftListResponse,
    WorldBiblePageDraftResponse,
    WorldBiblePageDraftUpdate,
    WorldBiblePageListResponse,
    WorldBiblePageResponse,
    WorldBiblePageRevisionResponse,
    WorldBiblePageTemplateCreate,
    WorldBiblePageTemplateListResponse,
    WorldBiblePageTemplateResponse,
    WorldBiblePageTemplateRevisionResponse,
    WorldBiblePageTemplateUpdate,
    WorldBiblePageUpdate,
    WorldBiblePublishImpactResponse,
    WorldBibleSynopsisAutoRefreshRequest,
    WorldBibleSynopsisRefreshResponse,
    WorldBibleSynopsisResponse,
    WorldBibleSynopsisRevisionListResponse,
    WorldbookImportApplyRequest,
    WorldbookImportApplyResponse,
    WorldbookImportManifest,
    WorldbookImportPreviewResponse,
    WorldCoreCheckpointSaveRequest,
    WorldDesignCheckpointSaveRequest,
    WorldGenerationApplyPageDraftRequest,
    WorldGenerationApplyPageDraftResponse,
    WorldGenerationChatRequest,
    WorldGenerationChatResponse,
    WorldGenerationConvergenceRequest,
    WorldGenerationConvergenceResponse,
    WorldGenerationExplorationRequest,
    WorldGenerationExplorationResponse,
    WorldGenerationSemanticInspectionRequest,
    WorldGenerationSemanticInspectionResponse,
    WorldGenerationSuggestionRequest,
    WorldGenerationSuggestionResponse,
    WorldGenerationSuggestionTaskRequest,
    WorldGenerationTaskResponse,
    WorldKnowledgeGraphResponse,
    WorldProfileListResponse,
    WorldProfileMigrateResponse,
    WorldProfileResponse,
    WorldProfileUpsertRequest,
    WorldValidationPolicyStatus,
    WorldValidationRunCreate,
    WorldValidationRunListResponse,
    WorldValidationRunResponse,
    WorldValidationWarningAcceptRequest,
)
from modules.world.services import (
    CharacterKnowledgeService,
    CharacterService,
    EntityAliasService,
    EntityContextService,
    EntityRelationService,
    EntityRevisionService,
    EventService,
    WorldEntityService,
)
from modules.world.services.core.dedup_service import EntityDedupService
from modules.world.services.core.review_queue import review_type_catalog
from modules.world.services.worldbuilding.adoption_package_service import (
    WorldAdoptionPackageService,
)
from modules.world.services.worldbuilding.ask_world_service import AskWorldService
from modules.world.services.worldbuilding.generation_prompt_template_service import (
    GenerationPromptTemplateService,
    TemplateVersionConflictError,
)
from modules.world.services.worldbuilding.knowledge_graph_service import (
    WorldKnowledgeGraphService,
)
from modules.world.services.worldbuilding.world_authority_service import (
    WorldAuthorityService,
)
from modules.world.services.worldbuilding.world_generation_center_service import (
    WorldGenerationCenterService,
)
from modules.world.services.worldbuilding.world_validation_service import (
    WorldValidationService,
)
from modules.world.services.worldbuilding.worldbook_import_service import (
    WorldbookImportService,
)
from modules.world.services.worldbuilding.worldbuilding_service import (
    ConflictQueueService,
    KnowledgeTagService,
    ProjectionRefreshConflictError,
    SuggestionAlreadyProcessedError,
    SuggestionQueueService,
    WorldBibleLifecycleService,
    WorldBiblePageTemplateService,
    WorldBibleService,
    WorldBibleSynopsisService,
    WorldProfileService,
)
from modules.world.world_object_images import (
    MAX_UPLOAD_BYTES as MAX_WORLD_OBJECT_IMAGE_BYTES,
)
from modules.world.world_object_images import (
    WorldObjectImageService,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

_CANON_BODY_PATHS = frozenset(
    {
        "/api/world/canon/admissions/preview",
        "/api/world/canon/admissions",
        "/api/world/canon/revert",
    }
)


def _canon_validation_error_code(exc: RequestValidationError) -> str:
    for error in exc.errors():
        location = tuple(error.get("loc") or ())
        if "selector" in location:
            return "canon_reference_invalid"
        if "assertions" not in location:
            continue
        assertion_index = location.index("assertions")
        assertion_location = location[assertion_index + 2 :]
        if (
            assertion_location == ("statement",)
            and error.get("type") == "union_tag_invalid"
        ):
            return "unsupported_statement_kind"
    if any("assertions" in tuple(error.get("loc") or ()) for error in exc.errors()):
        return "invalid_statement_value"
    return "canon_reference_invalid"


class _WorldApiRoute(APIRoute):
    def get_route_handler(self):
        route_handler = super().get_route_handler()

        async def handle_canon_validation(request: Request):
            try:
                return await route_handler(request)
            except RequestValidationError as exc:
                if request.url.path in _CANON_BODY_PATHS:
                    code = _canon_validation_error_code(exc)
                    raise DomainError(
                        "Canon request is invalid",
                        code=code,
                        status_code=422,
                    ) from exc
                raise

        return handle_canon_validation


router = APIRouter(
    prefix="/api/world",
    tags=["world"],
    route_class=_WorldApiRoute,
)

_entity_service = WorldEntityService()
_entity_image_service = WorldObjectImageService()
_alias_service = EntityAliasService()
_context_service = EntityContextService()
_relation_service = EntityRelationService()
_dedup_service = EntityDedupService()
_fusion_service = WorldEntityFusionService()
_revision_service = EntityRevisionService()
_event_service = EventService()
_character_service = CharacterService()
_knowledge_service = CharacterKnowledgeService()
_profile_service = WorldProfileService()
_bible_service = WorldBibleService()
_bible_lifecycle_service = WorldBibleLifecycleService()
_bible_page_template_service = WorldBiblePageTemplateService()
_bible_synopsis_service = WorldBibleSynopsisService()
_suggestion_service = SuggestionQueueService()
_conflict_queue_service = ConflictQueueService()
_knowledge_tag_service = KnowledgeTagService()
_world_generation_service = WorldGenerationCenterService()
_ask_world_service = AskWorldService()
_adoption_package_service = WorldAdoptionPackageService()
_knowledge_graph_service = WorldKnowledgeGraphService()
_generation_template_service = GenerationPromptTemplateService()
_worldbook_import_service = WorldbookImportService()
_world_validation_service = WorldValidationService()
_world_authority_service = WorldAuthorityService()


async def _require_active_novel_id(
    db: DbSession,
    novel_id: NovelIdQuery,
) -> str:
    await require_active_project(db, novel_id)
    return novel_id


ActiveNovelIdQuery = Annotated[str, Depends(_require_active_novel_id)]


@router.get("/canon/head", response_model=CanonHeadResponse)
async def get_world_canon_head(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CanonHeadResponse:
    return await _world_authority_service.get_head(db, novel_id)


@router.get("/canon/revisions/{revision_id}", response_model=CanonRevisionResponse)
async def get_world_canon_revision(
    db: DbSession,
    revision_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CanonRevisionResponse:
    return await _world_authority_service.get_revision(db, novel_id, revision_id)


@router.post("/canon/admissions/preview", response_model=CanonAdmissionPreviewResponse)
async def preview_world_canon_admission(
    db: DbSession,
    data: CanonAdmissionPreviewRequest,
) -> CanonAdmissionPreviewResponse:
    await require_active_project(db, str(data.novel_id))
    return await _world_authority_service.preview(db, data)


@router.post("/canon/admissions", response_model=CanonRevisionResponse)
async def admit_world_canon_change(
    db: DbSession,
    data: CanonAdmissionRequest,
) -> CanonRevisionResponse:
    await _require_active_project_exclusive(db, str(data.novel_id))
    return await _world_authority_service.admit(
        db,
        data,
        authorizer_id=current_account_id(),
    )


@router.post("/canon/revert", response_model=CanonRevisionResponse)
async def revert_world_canon(
    db: DbSession,
    data: CanonRevertRequest,
) -> CanonRevisionResponse:
    await _require_active_project_exclusive(db, str(data.novel_id))
    preview = await _world_authority_service.preview(
        db,
        CanonAdmissionPreviewRequest(
            novel_id=data.novel_id,
            expected_previous_head=data.expected_previous_head,
            input=RevertPreviewInputV1(
                novel_id=data.novel_id,
                target_revision_id=data.target_revision_id,
            ),
        ),
    )
    return await _world_authority_service.admit(
        db,
        CanonAdmissionRequest(
            novel_id=data.novel_id,
            decision_id=data.decision_id,
            expected_previous_head=data.expected_previous_head,
            confirmed=True,
            input=preview.normalized_input,
        ),
        authorizer_id=current_account_id(),
    )


async def _read_worldbook_import_manifest(request: Request) -> WorldbookImportManifest:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 64 * 1024 * 1024:
            raise HTTPException(
                status_code=413, detail="Worldbook import body is too large"
            )
    try:
        value = json.loads(body.decode("utf-8"))
        return WorldbookImportManifest.model_validate(value)
    except (UnicodeDecodeError, json.JSONDecodeError, PydanticValidationError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Worldbook import manifest is invalid",
        ) from exc


@router.get("/knowledge-graph", response_model=WorldKnowledgeGraphResponse)
async def get_world_knowledge_graph(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    scope: Literal["local", "global"] = Query(default="global"),
    root_type: Literal["world_bible_page", "core_entity"] | None = Query(default=None),
    root_id: str | None = Query(default=None),
    depth: int = Query(default=1, ge=1, le=2),
) -> WorldKnowledgeGraphResponse:
    return await _knowledge_graph_service.get(
        db, novel_id, scope=scope, root_type=root_type, root_id=root_id, depth=depth
    )


def _template_version_conflict(exc: TemplateVersionConflictError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "status": "template_version_conflict",
            "expected_version": exc.expected,
            "actual_version": exc.actual,
        },
    )


# ============================================================
# Generate Center Chatbox 路由
# ============================================================


@router.post(
    "/generation-center/chat",
    response_model=WorldGenerationChatResponse,
)
async def chat_world_generation_center(
    db: DbSession,
    data: WorldGenerationChatRequest,
) -> WorldGenerationChatResponse:
    """World co-creation chat; never writes a business asset or suggestion."""
    await require_active_project(db, data.novel_id)
    try:
        return await _world_generation_service.chat(db, data)
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/generation-center/convergence",
    response_model=WorldGenerationConvergenceResponse,
)
async def converge_world_generation_center(
    db: DbSession,
    data: WorldGenerationConvergenceRequest,
) -> WorldGenerationConvergenceResponse:
    """Read-only convergence over the author-selected source window."""
    await require_active_project(db, data.novel_id)
    try:
        return await _world_generation_service.converge(db, data)
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/generation-center/exploration",
    response_model=WorldGenerationExplorationResponse,
)
async def explore_world_generation_center(
    db: DbSession,
    data: WorldGenerationExplorationRequest,
) -> WorldGenerationExplorationResponse:
    """Return at most three read-only, one-hop world gaps."""
    await require_active_project(db, data.novel_id)
    try:
        return await _world_generation_service.explore(db, data)
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/generation-center/semantic-inspection",
    response_model=WorldGenerationSemanticInspectionResponse,
)
async def inspect_world_generation_center_page(
    db: DbSession,
    data: WorldGenerationSemanticInspectionRequest,
) -> WorldGenerationSemanticInspectionResponse:
    """Inspect one exact current page; findings remain author-reviewable."""
    await require_active_project(db, data.novel_id)
    try:
        return await _world_generation_service.inspect_current_page(db, data)
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/ask-world", response_model=AskWorldResponse)
async def ask_world(
    db: DbSession,
    data: AskWorldQuestionRequest,
) -> AskWorldResponse:
    """Answer from current author-visible evidence without writing assets."""
    await require_active_project(db, data.novel_id)
    try:
        return await _ask_world_service.ask(db, data)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/ask-world/citations/open",
    response_model=AskWorldCitationOpenResponse,
)
async def open_ask_world_citation(
    db: DbSession,
    data: AskWorldCitationOpenRequest,
) -> AskWorldCitationOpenResponse:
    """Re-open one citation inside the active project and report freshness."""
    await require_active_project(db, data.novel_id)
    return await _ask_world_service.open_citation(db, data.novel_id, data.citation)


@router.post(
    "/ask-world/suggestions",
    response_model=AskWorldSaveResponse,
    status_code=201,
)
async def save_ask_world_suggestion(
    db: DbSession,
    data: AskWorldSaveRequest,
) -> AskWorldSaveResponse:
    """Explicitly save an answer as a pending, reviewable suggestion."""
    await require_active_project(db, data.novel_id)
    try:
        return await _suggestion_service.save_ask_world_answer(db, data)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/generation-center/suggestions",
    response_model=WorldGenerationSuggestionResponse,
    status_code=201,
    deprecated=True,
)
async def generate_world_suggestion(
    db: DbSession,
    data: WorldGenerationSuggestionRequest,
) -> WorldGenerationSuggestionResponse:
    """Generate one typed, pending suggestion for the author-selected target."""
    await require_active_project(db, data.novel_id)
    try:
        return await _world_generation_service.generate_suggestion(db, data)
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/generation-center/suggestions/task",
    response_model=WorldGenerationTaskResponse,
    status_code=202,
)
async def enqueue_world_suggestion(
    db: DbSession,
    data: WorldGenerationSuggestionTaskRequest,
) -> WorldGenerationTaskResponse:
    await require_active_project(db, data.novel_id)
    payload = data.model_dump(mode="json", exclude={"operation_id"})
    try:
        existing = await get_operation_task(
            db,
            operation_id=str(data.operation_id),
            task_type="world_generation_suggestion",
            novel_id=data.novel_id,
            request_payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if existing is not None:
        return WorldGenerationTaskResponse(
            task_id=existing.task_id,
            status=existing.status,
        )
    snapshot = await build_project_llm_execution_snapshot(db, data.novel_id)
    try:
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=str(data.operation_id),
            task_type="world_generation_suggestion",
            novel_id=data.novel_id,
            request_payload=payload,
            meta={
                **payload,
                "llm_execution_snapshot": snapshot,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.flush()
    return WorldGenerationTaskResponse(
        task_id=receipt.task_id,
        status=receipt.status,
    )


@router.get(
    "/generation-prompt-templates",
    response_model=GenerationPromptTemplateListResponse,
)
async def list_generation_prompt_templates(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    target_kind: str = Query(default="world_object"),
    include_archived: bool = Query(default=False),
) -> GenerationPromptTemplateListResponse:
    return await _generation_template_service.list(
        db,
        novel_id,
        target_kind=target_kind,
        include_archived=include_archived,
    )


@router.post(
    "/generation-prompt-templates",
    response_model=GenerationPromptTemplateResponse,
    status_code=201,
)
async def create_generation_prompt_template(
    db: DbSession,
    data: GenerationPromptTemplateCreate,
) -> GenerationPromptTemplateResponse:
    await require_active_project(db, data.novel_id)
    return await _generation_template_service.create(db, data)


@router.post(
    "/generation-prompt-templates/validate",
    response_model=PromptTemplateValidateResponse,
)
async def validate_generation_prompt_template(
    db: DbSession,
    data: PromptTemplateValidateRequest,
) -> PromptTemplateValidateResponse:
    if data.novel_id is not None:
        await require_active_project(db, data.novel_id)
    return _generation_template_service.validate(data)


@router.post(
    "/generation-prompt-templates/preview",
    response_model=PromptTemplatePreviewResponse,
)
async def preview_generation_prompt_template(
    db: DbSession,
    data: PromptTemplatePreviewRequest,
) -> PromptTemplatePreviewResponse:
    await require_active_project(db, data.novel_id)
    try:
        return await _generation_template_service.preview(db, data)
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc


@router.get(
    "/generation-prompt-templates/{template_id}",
    response_model=GenerationPromptTemplateResponse,
)
async def get_generation_prompt_template(
    db: DbSession,
    template_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> GenerationPromptTemplateResponse:
    return await _generation_template_service.get(db, novel_id, template_id)


@router.put(
    "/generation-prompt-templates/{template_id}",
    response_model=GenerationPromptTemplateResponse,
)
async def update_generation_prompt_template(
    db: DbSession,
    template_id: str,
    data: GenerationPromptTemplateUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> GenerationPromptTemplateResponse:
    try:
        return await _generation_template_service.update(db, novel_id, template_id, data)
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc


@router.delete("/generation-prompt-templates/{template_id}", status_code=204)
async def archive_generation_prompt_template(
    db: DbSession,
    template_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> None:
    await _generation_template_service.archive(db, novel_id, template_id)


@router.get(
    "/generation-prompt-templates/{template_id}/revisions",
    response_model=list[GenerationPromptTemplateRevisionResponse],
)
async def list_generation_prompt_template_revisions(
    db: DbSession,
    template_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> list[GenerationPromptTemplateRevisionResponse]:
    return await _generation_template_service.revisions(db, novel_id, template_id)


@router.post(
    "/generation-prompt-templates/{template_id}/copy",
    response_model=GenerationPromptTemplateResponse,
    status_code=201,
)
async def copy_builtin_generation_prompt_template(
    db: DbSession,
    template_id: str,
    data: PromptTemplateCopyRequest,
) -> GenerationPromptTemplateResponse:
    await require_active_project(db, data.novel_id)
    try:
        return await _generation_template_service.copy_builtin(db, template_id, data)
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc


# ============================================================
# Worldbuilding Workspace 路由
# ============================================================


@router.get("/profiles", response_model=WorldProfileListResponse)
async def list_world_profiles(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    entity_type: str | None = Query(None, description="实体类型"),
    status: str | None = Query(None, description="实体状态"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> WorldProfileListResponse:
    items, total = await _profile_service.list_profiles(
        db,
        novel_id,
        entity_type=entity_type,
        status=status,
        skip=skip,
        limit=limit,
    )
    return WorldProfileListResponse(items=items, total=total)


@router.get("/profiles/{entity_id}", response_model=WorldProfileResponse)
async def get_world_profile(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldProfileResponse:
    return await _profile_service.get_profile(db, novel_id, entity_id)


@router.put("/profiles/{entity_id}", response_model=WorldProfileResponse)
async def upsert_world_profile(
    db: DbSession,
    entity_id: str,
    data: WorldProfileUpsertRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldProfileResponse:
    return await _profile_service.upsert_profile(db, novel_id, entity_id, data)


@router.post(
    "/profiles/{entity_id}/migrate-generic",
    response_model=WorldProfileMigrateResponse,
)
async def migrate_generic_profile(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldProfileMigrateResponse:
    profile = await _profile_service.migrate_generic_to_strong(db, novel_id, entity_id)
    return WorldProfileMigrateResponse(
        entity_id=entity_id,
        migrated=True,
        profile=profile,
    )


@router.get("/bible/pages", response_model=WorldBiblePageListResponse)
async def list_bible_pages(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    page_type: str | None = Query(None, description="页面类型"),
) -> WorldBiblePageListResponse:
    items, total = await _bible_service.list_pages(db, novel_id, page_type=page_type)
    return WorldBiblePageListResponse(items=items, total=total)


@router.post("/bible/pages", response_model=WorldBiblePageResponse, status_code=201)
async def create_bible_page(
    db: DbSession,
    data: WorldBiblePageCreate,
) -> WorldBiblePageResponse:
    if data.status not in {"canonical", "confirmed"}:
        await require_active_project(db, data.novel_id)
        return await _bible_service.create_page(db, data)
    await _require_active_project_exclusive(db, data.novel_id)
    expected_canon_head = await _world_authority_service.lock_head_for_admission(
        db, data.novel_id
    )
    async with db.begin_nested():
        staged = await _bible_service.create_page(
            db,
            data.model_copy(update={"status": "draft"}),
        )
        draft = await _bible_lifecycle_service.create_draft(
            db,
            WorldBiblePageDraftCreate(
                novel_id=data.novel_id,
                page_id=staged.id,
                created_by=data.created_by,
            ),
        )
        return await _bible_lifecycle_service.admit_draft(
            db,
            data.novel_id,
            draft.id,
            authorizer_id=current_account_id(),
            expected_canon_head=expected_canon_head,
        )


@router.get("/bible/pages/{page_id}", response_model=WorldBiblePageResponse)
async def get_bible_page(
    db: DbSession,
    page_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBiblePageResponse:
    return await _bible_service.get_page(db, novel_id, page_id)


@router.patch("/bible/pages/{page_id}", response_model=WorldBiblePageResponse)
async def update_bible_page(
    db: DbSession,
    page_id: str,
    data: WorldBiblePageUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBiblePageResponse:
    current = await _bible_service.get_page(db, novel_id, page_id)
    payload = data.model_dump(mode="json", exclude_unset=True)
    if set(payload) <= {"updated_by"}:
        return await _bible_service.update_page(db, novel_id, page_id, data)
    if (
        current.status in {"canonical", "confirmed"}
        and payload.get("status") == "archived"
        and set(payload) <= {"status", "updated_by"}
    ):
        return await _bible_service.update_page(db, novel_id, page_id, data)
    needs_admission = current.status in {
        "canonical",
        "confirmed",
        "archived",
    } or payload.get("status") in {"canonical", "confirmed"}
    if not needs_admission:
        return await _bible_service.update_page(db, novel_id, page_id, data)
    if payload.get("status") not in {None, "canonical", "confirmed"}:
        raise ConflictError(
            "This World Bible status change is not supported by Canon admission",
            code="canon_admission_required",
            context={"next_action": "create_and_publish_world_bible_draft"},
        )
    if "activation_defaults_json" in payload:
        raise ConflictError(
            "Activation defaults cannot be changed through the legacy page adapter",
            code="canon_admission_required",
            context={"next_action": "create_and_publish_world_bible_draft"},
        )
    await _require_active_project_exclusive(db, novel_id)
    expected_canon_head = await _world_authority_service.lock_head_for_admission(
        db, novel_id
    )
    async with db.begin_nested():
        draft = await _bible_lifecycle_service.create_draft(
            db,
            WorldBiblePageDraftCreate(
                novel_id=novel_id,
                page_id=page_id,
                created_by=payload.get("updated_by"),
            ),
        )
        draft_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"status", "activation_defaults_json", "updated_by"}
        }
        if draft_payload:
            draft = await _bible_lifecycle_service.update_draft(
                db,
                novel_id,
                draft.id,
                WorldBiblePageDraftUpdate(
                    **draft_payload,
                    updated_by=payload.get("updated_by"),
                ),
            )
        return await _bible_lifecycle_service.admit_draft(
            db,
            novel_id,
            draft.id,
            authorizer_id=current_account_id(),
            expected_canon_head=expected_canon_head,
        )


@router.get("/bible/categories", response_model=WorldBibleCategoryListResponse)
async def list_bible_categories(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    include_archived: bool = Query(default=False),
) -> WorldBibleCategoryListResponse:
    items = await _bible_lifecycle_service.list_categories(
        db,
        novel_id,
        include_archived=include_archived,
    )
    return WorldBibleCategoryListResponse(items=items)


@router.post(
    "/bible/categories",
    response_model=WorldBibleCategoryResponse,
    status_code=201,
)
async def create_bible_category(
    db: DbSession,
    data: WorldBibleCategoryCreate,
) -> WorldBibleCategoryResponse:
    await require_active_project(db, data.novel_id)
    return await _bible_lifecycle_service.create_category(db, data)


@router.patch(
    "/bible/categories/{category_id}",
    response_model=WorldBibleCategoryResponse,
)
async def update_bible_category(
    db: DbSession,
    category_id: str,
    data: WorldBibleCategoryUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBibleCategoryResponse:
    return await _bible_lifecycle_service.update_category(
        db,
        novel_id,
        category_id,
        data,
    )


@router.get("/bible/drafts", response_model=WorldBiblePageDraftListResponse)
async def list_bible_drafts(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBiblePageDraftListResponse:
    items, total = await _bible_lifecycle_service.list_drafts(db, novel_id)
    return WorldBiblePageDraftListResponse(items=items, total=total)


@router.post(
    "/bible/imports/preview",
    response_model=WorldbookImportPreviewResponse,
    status_code=201,
)
async def preview_worldbook_import(
    db: DbSession,
    request: Request,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldbookImportPreviewResponse:
    manifest = await _read_worldbook_import_manifest(request)
    return await _worldbook_import_service.preview(db, novel_id, manifest)


@router.get(
    "/bible/imports/{suggestion_id}",
    response_model=WorldbookImportPreviewResponse,
)
async def get_worldbook_import_preview(
    db: DbSession,
    suggestion_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldbookImportPreviewResponse:
    return await _worldbook_import_service.get_preview(db, novel_id, suggestion_id)


@router.post(
    "/bible/imports/{suggestion_id}/apply",
    response_model=WorldbookImportApplyResponse,
)
async def apply_worldbook_import(
    db: DbSession,
    suggestion_id: str,
    data: WorldbookImportApplyRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldbookImportApplyResponse:
    return await _worldbook_import_service.apply(
        db,
        novel_id,
        suggestion_id,
        data,
    )


@router.get(
    "/bible/validation-policy",
    response_model=WorldValidationPolicyStatus,
)
async def get_world_validation_policy_status(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldValidationPolicyStatus:
    return await _world_validation_service.policy_status(db, novel_id)


@router.post(
    "/bible/validation-policy/activate",
    response_model=WorldBiblePageResponse,
    status_code=201,
)
async def activate_world_validation_policy(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> WorldBiblePageResponse:
    await _require_active_project_exclusive(db, novel_id)
    return await _world_validation_service.activate_builtin_policy(db, novel_id)


@router.post(
    "/bible/validation-runs",
    response_model=WorldValidationRunResponse,
    status_code=202,
)
async def create_world_validation_run(
    db: DbSession,
    data: WorldValidationRunCreate,
) -> WorldValidationRunResponse:
    await _require_active_project_exclusive(db, data.novel_id)
    try:
        return await _world_validation_service.create_run(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/bible/validation-runs",
    response_model=WorldValidationRunListResponse,
)
async def list_world_validation_runs(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    limit: int = Query(default=10, ge=1, le=20),
) -> WorldValidationRunListResponse:
    return await _world_validation_service.list_runs(db, novel_id, limit=limit)


@router.get(
    "/bible/validation-runs/latest",
    response_model=WorldValidationRunResponse | None,
)
async def get_latest_world_validation_run(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    scope: Literal["targeted", "full"] | None = Query(default=None),
    target_type: Literal["world_bible_draft", "world_adoption_package"] | None = Query(
        default=None
    ),
    target_id: str | None = Query(default=None),
) -> WorldValidationRunResponse | None:
    return await _world_validation_service.latest(
        db,
        novel_id,
        scope=scope,
        target_type=target_type,
        target_id=target_id,
    )


@router.get(
    "/bible/validation-runs/{run_id}",
    response_model=WorldValidationRunResponse,
)
async def get_world_validation_run(
    db: DbSession,
    run_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldValidationRunResponse:
    return await _world_validation_service.get(db, novel_id, run_id)


@router.post(
    "/bible/validation-runs/{run_id}/accept-warnings",
    response_model=WorldValidationRunResponse,
)
async def accept_world_validation_warnings(
    db: DbSession,
    run_id: str,
    data: WorldValidationWarningAcceptRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldValidationRunResponse:
    return await _world_validation_service.accept_warnings(
        db,
        novel_id,
        run_id,
        data,
    )


@router.post(
    "/bible/drafts",
    response_model=WorldBiblePageDraftResponse,
    status_code=201,
)
async def create_bible_draft(
    db: DbSession,
    data: WorldBiblePageDraftCreate,
) -> WorldBiblePageDraftResponse:
    await require_active_project(db, data.novel_id)
    return await _bible_lifecycle_service.create_draft(db, data)


@router.get("/bible/drafts/{draft_id}", response_model=WorldBiblePageDraftResponse)
async def get_bible_draft(
    db: DbSession,
    draft_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBiblePageDraftResponse:
    return await _bible_lifecycle_service.get_draft(db, novel_id, draft_id)


@router.patch("/bible/drafts/{draft_id}", response_model=WorldBiblePageDraftResponse)
async def update_bible_draft(
    db: DbSession,
    draft_id: str,
    data: WorldBiblePageDraftUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBiblePageDraftResponse:
    return await _bible_lifecycle_service.update_draft(
        db,
        novel_id,
        draft_id,
        data,
    )


@router.delete("/bible/drafts/{draft_id}")
async def discard_bible_draft(
    db: DbSession,
    draft_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    confirmed: bool = Query(default=False),
) -> dict:
    if not confirmed:
        raise HTTPException(status_code=400, detail="confirmed=true is required")
    await _bible_lifecycle_service.discard_draft(db, novel_id, draft_id)
    return {"draft_id": draft_id, "discarded": True}


@router.post(
    "/bible/drafts/{draft_id}/publish",
    response_model=WorldBiblePageResponse,
)
async def publish_bible_draft(
    db: DbSession,
    draft_id: str,
    *,
    novel_id: NovelIdQuery,
    expected_canon_head: uuid.UUID | None = Query(default=None),
    canon_decision_id: uuid.UUID | None = Query(default=None),
    expected_impact_scope_hash: str | None = Query(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    ),
    validation_run_id: uuid.UUID | None = Query(default=None),
) -> WorldBiblePageResponse:
    if (expected_canon_head is None) != (canon_decision_id is None):
        raise HTTPException(
            status_code=422,
            detail="expected_canon_head and canon_decision_id must be provided together",
        )
    await _require_active_project_exclusive(db, novel_id)
    return await _bible_lifecycle_service.admit_draft(
        db,
        novel_id,
        draft_id,
        authorizer_id=current_account_id(),
        expected_canon_head=expected_canon_head,
        canon_decision_id=canon_decision_id,
        expected_impact_scope_hash=expected_impact_scope_hash,
        validation_run_id=validation_run_id,
    )


@router.get(
    "/bible/drafts/{draft_id}/publish-impact",
    response_model=WorldBiblePublishImpactResponse,
)
async def preview_bible_draft_publish_impact(
    db: DbSession,
    draft_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBiblePublishImpactResponse:
    return await _bible_lifecycle_service.preview_publish_impact(
        db,
        novel_id,
        draft_id,
    )


@router.get(
    "/bible/pages/{page_id}/revisions",
    response_model=list[WorldBiblePageRevisionResponse],
)
async def list_bible_page_revisions(
    db: DbSession,
    page_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> list[WorldBiblePageRevisionResponse]:
    return await _bible_lifecycle_service.list_revisions(db, novel_id, page_id)


@router.post(
    "/bible/pages/{page_id}/revisions/{version_number}/restore-draft",
    response_model=WorldBiblePageDraftResponse,
)
async def restore_bible_revision_to_draft(
    db: DbSession,
    page_id: str,
    version_number: int,
    *,
    novel_id: ActiveNovelIdQuery,
    restored_by: str | None = Query(default=None, max_length=64),
) -> WorldBiblePageDraftResponse:
    return await _bible_lifecycle_service.restore_revision_to_draft(
        db,
        novel_id,
        page_id,
        version_number,
        restored_by=restored_by,
    )


@router.get("/bible/synopsis", response_model=WorldBibleSynopsisResponse)
async def get_bible_synopsis(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBibleSynopsisResponse:
    return await _bible_synopsis_service.get(db, novel_id)


@router.post(
    "/bible/synopsis/refresh",
    response_model=WorldBibleSynopsisRefreshResponse,
)
async def refresh_bible_synopsis(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBibleSynopsisRefreshResponse:
    (
        task_id,
        status,
        existing,
        source_hash,
    ) = await _bible_synopsis_service.request_refresh(db, novel_id)
    return WorldBibleSynopsisRefreshResponse(
        task_id=task_id,
        status=status,
        existing=existing,
        source_hash=source_hash,
    )


@router.patch(
    "/bible/synopsis/auto-refresh",
    response_model=WorldBibleSynopsisResponse,
)
async def set_bible_synopsis_auto_refresh(
    db: DbSession,
    data: WorldBibleSynopsisAutoRefreshRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBibleSynopsisResponse:
    return await _bible_synopsis_service.set_auto_refresh(
        db,
        novel_id,
        enabled=data.enabled,
        changed_by=data.changed_by,
    )


@router.get(
    "/bible/synopsis/revisions",
    response_model=WorldBibleSynopsisRevisionListResponse,
)
async def list_bible_synopsis_revisions(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBibleSynopsisRevisionListResponse:
    items, total = await _bible_synopsis_service.list_revisions(db, novel_id)
    return WorldBibleSynopsisRevisionListResponse(items=items, total=total)


@router.post(
    "/bible/synopsis/revisions/{revision_id}/restore",
    response_model=WorldBibleSynopsisResponse,
)
async def restore_bible_synopsis_revision(
    db: DbSession,
    revision_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBibleSynopsisResponse:
    return await _bible_synopsis_service.restore_revision(
        db,
        novel_id,
        revision_id,
    )


@router.post("/bible/synopsis/unpin", response_model=WorldBibleSynopsisResponse)
async def unpin_bible_synopsis(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBibleSynopsisResponse:
    return await _bible_synopsis_service.unpin(db, novel_id)


@router.get("/bible/templates")
async def list_bible_templates() -> list[dict]:
    return await _bible_service.list_templates()


@router.get(
    "/bible/page-templates",
    response_model=WorldBiblePageTemplateListResponse,
)
async def list_bible_page_templates(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    include_archived: bool = Query(default=False),
) -> WorldBiblePageTemplateListResponse:
    items = await _bible_page_template_service.list_templates(
        db,
        novel_id,
        include_archived=include_archived,
    )
    return WorldBiblePageTemplateListResponse(items=items, total=len(items))


@router.post(
    "/bible/page-templates",
    response_model=WorldBiblePageTemplateResponse,
    status_code=201,
)
async def create_bible_page_template(
    db: DbSession,
    data: WorldBiblePageTemplateCreate,
) -> WorldBiblePageTemplateResponse:
    await require_active_project(db, data.novel_id)
    return await _bible_page_template_service.create_template(db, data)


@router.patch(
    "/bible/page-templates/{template_id}",
    response_model=WorldBiblePageTemplateResponse,
)
async def update_bible_page_template(
    db: DbSession,
    template_id: str,
    data: WorldBiblePageTemplateUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBiblePageTemplateResponse:
    return await _bible_page_template_service.update_template(
        db,
        novel_id,
        template_id,
        data,
    )


@router.get(
    "/bible/page-templates/{template_id}/revisions",
    response_model=list[WorldBiblePageTemplateRevisionResponse],
)
async def list_bible_page_template_revisions(
    db: DbSession,
    template_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> list[WorldBiblePageTemplateRevisionResponse]:
    return await _bible_page_template_service.list_revisions(
        db,
        novel_id,
        template_id,
    )


@router.post(
    "/bible/page-templates/{template_id}/revisions/{version_number}/restore-draft",
    response_model=WorldBiblePageTemplateResponse,
)
async def restore_bible_page_template_revision(
    db: DbSession,
    template_id: str,
    version_number: int,
    *,
    novel_id: ActiveNovelIdQuery,
    restored_by: str | None = Query(default=None, max_length=64),
) -> WorldBiblePageTemplateResponse:
    return await _bible_page_template_service.restore_revision(
        db,
        novel_id,
        template_id,
        version_number,
        restored_by=restored_by,
    )


@router.post(
    "/bible/drafts/{draft_id}/apply-template",
    response_model=WorldBiblePageDraftResponse,
)
async def apply_bible_page_template(
    db: DbSession,
    draft_id: str,
    data: WorldBibleApplyTemplateRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBiblePageDraftResponse:
    return await _bible_page_template_service.apply_to_draft(
        db,
        novel_id,
        draft_id,
        data,
    )


@router.post(
    "/bible/pages/{page_id}/refresh-projection",
    response_model=ProjectionRefreshResponse,
)
async def refresh_bible_projection(
    db: DbSession,
    page_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    projection_type: str = Query(default="context_brief"),
    force: bool = Query(default=False),
) -> ProjectionRefreshResponse:
    try:
        task_id, status, existing = await _bible_service.refresh_projection_task(
            db,
            novel_id,
            page_id,
            projection_type=projection_type,
            force=force,
        )
    except ProjectionRefreshConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "projection_task_finished",
                "task_id": exc.task_id,
                "task_status": exc.status,
                "hint": "retry with force=true",
            },
        ) from exc
    return ProjectionRefreshResponse(
        task_id=task_id,
        status=status,
        existing=existing,
        projection_type=projection_type,
    )


@router.post("/bible/pages/{page_id}/organize")
async def organize_bible_page(
    page_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> dict:
    return {
        "page_id": page_id,
        "novel_id": novel_id,
        "status": "preview_only",
        "suggestions": [],
        "conflicts": [],
    }


@router.post(
    "/core-checkpoints",
    response_model=CreationSuggestionResponse,
    status_code=201,
)
async def save_world_core_checkpoint(
    db: DbSession,
    data: WorldCoreCheckpointSaveRequest,
) -> CreationSuggestionResponse:
    await require_active_project(db, data.novel_id)
    return await _adoption_package_service.save_checkpoint(db, data)


@router.post(
    "/design-checkpoints",
    response_model=CreationSuggestionResponse,
    status_code=201,
)
async def save_world_design_checkpoint(
    db: DbSession,
    data: WorldDesignCheckpointSaveRequest,
) -> CreationSuggestionResponse:
    await require_active_project(db, data.novel_id)
    return await _adoption_package_service.save_design_checkpoint(db, data)


@router.get(
    "/adoption-packages/{suggestion_id}", response_model=CreationSuggestionResponse
)
async def get_world_adoption_artifact(
    db: DbSession,
    suggestion_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CreationSuggestionResponse:
    return await _adoption_package_service.get(db, novel_id, suggestion_id)


@router.post(
    "/adoption-packages",
    response_model=CreationSuggestionResponse,
    status_code=201,
)
async def save_world_adoption_package(
    db: DbSession,
    data: WorldAdoptionPackageSaveRequest,
) -> CreationSuggestionResponse:
    await require_active_project(db, data.novel_id)
    return await _adoption_package_service.save(db, data)


@router.get(
    "/adoption-packages/{suggestion_id}/preview",
    response_model=WorldAdoptionPackagePreviewResponse,
)
async def preview_world_adoption_package(
    db: DbSession,
    suggestion_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldAdoptionPackagePreviewResponse:
    return await _adoption_package_service.preview(db, novel_id, suggestion_id)


@router.post(
    "/adoption-packages/{suggestion_id}/apply",
    response_model=CreationSuggestionResponse,
)
async def apply_world_adoption_package(
    db: DbSession,
    suggestion_id: str,
    data: WorldAdoptionPackageApplyRequest,
    *,
    novel_id: NovelIdQuery,
) -> CreationSuggestionResponse:
    await _require_active_project_exclusive(db, novel_id)
    try:
        async with db.begin_nested():
            return await _adoption_package_service.apply(
                db, novel_id, suggestion_id, data
            )
    except ConflictError as exc:
        if exc.code == "required_validation":
            raise
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/suggestions", response_model=CreationSuggestionListResponse)
async def list_world_suggestions(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    source_module: str | None = Query(None),
    review_group: str | None = Query(None),
    risk_level: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> CreationSuggestionListResponse:
    items, total = await _suggestion_service.list(
        db,
        novel_id,
        source_module=source_module,
        review_group=review_group,
        risk_level=risk_level,
        status=status,
        skip=skip,
        limit=limit,
    )
    return CreationSuggestionListResponse(items=items, total=total)


@router.post(
    "/suggestions/{suggestion_id}/confirm",
    response_model=SuggestionDecisionResponse,
)
async def confirm_world_suggestion(
    db: DbSession,
    suggestion_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> SuggestionDecisionResponse:
    try:
        suggestion = await _suggestion_service.confirm(db, novel_id, suggestion_id)
    except SuggestionAlreadyProcessedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "already_processed",
                "suggestion_status": exc.status,
            },
        ) from exc
    return SuggestionDecisionResponse(
        status="accepted",
        suggestion_status=suggestion.status,
        result_ref_json=suggestion.result_ref_json,
    )


@router.post(
    "/suggestions/{suggestion_id}/edit-confirm",
    response_model=SuggestionDecisionResponse,
)
async def edit_and_confirm_world_suggestion(
    db: DbSession,
    suggestion_id: str,
    data: CoreEntitySuggestionEditConfirmRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> SuggestionDecisionResponse:
    try:
        suggestion = await _suggestion_service.edit_and_confirm_core_entity(
            db,
            novel_id,
            suggestion_id,
            data,
        )
    except SuggestionAlreadyProcessedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "already_processed",
                "suggestion_status": exc.status,
            },
        ) from exc
    return SuggestionDecisionResponse(
        status="accepted",
        suggestion_status=suggestion.status,
        result_ref_json=suggestion.result_ref_json,
    )


@router.post(
    "/generation-center/suggestions/{suggestion_id}/apply-page-draft",
    response_model=WorldGenerationApplyPageDraftResponse,
)
async def apply_world_generation_page_draft(
    db: DbSession,
    suggestion_id: str,
    data: WorldGenerationApplyPageDraftRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldGenerationApplyPageDraftResponse:
    try:
        return await _suggestion_service.apply_world_generation_page_draft(
            db,
            novel_id,
            suggestion_id,
            data,
        )
    except SuggestionAlreadyProcessedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "already_processed",
                "suggestion_status": exc.status,
            },
        ) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/suggestions/{suggestion_id}/merge",
    response_model=SuggestionDecisionResponse,
)
async def merge_world_suggestion(
    db: DbSession,
    suggestion_id: str,
    data: EntityMergeRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> SuggestionDecisionResponse:
    try:
        suggestion = await _suggestion_service.merge_core_entity(
            db,
            novel_id,
            suggestion_id,
            data,
        )
    except SuggestionAlreadyProcessedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "already_processed",
                "suggestion_status": exc.status,
            },
        ) from exc
    return SuggestionDecisionResponse(
        status="accepted",
        suggestion_status=suggestion.status,
        result_ref_json=suggestion.result_ref_json,
    )


@router.post(
    "/suggestions/{suggestion_id}/resolve-as-alias",
    response_model=SuggestionDecisionResponse,
)
async def resolve_world_suggestion_as_alias(
    db: DbSession,
    suggestion_id: str,
    data: EntityResolveAsAliasRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> SuggestionDecisionResponse:
    try:
        suggestion = await _suggestion_service.resolve_core_entity_as_alias(
            db,
            novel_id,
            suggestion_id,
            data,
        )
    except SuggestionAlreadyProcessedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "already_processed",
                "suggestion_status": exc.status,
            },
        ) from exc
    return SuggestionDecisionResponse(
        status="accepted",
        suggestion_status=suggestion.status,
        result_ref_json=suggestion.result_ref_json,
    )


@router.post(
    "/suggestions/{suggestion_id}/reject",
    response_model=SuggestionDecisionResponse,
)
async def reject_world_suggestion(
    db: DbSession,
    suggestion_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> SuggestionDecisionResponse:
    try:
        suggestion = await _suggestion_service.reject(db, novel_id, suggestion_id)
    except SuggestionAlreadyProcessedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "already_processed",
                "suggestion_status": exc.status,
            },
        ) from exc
    return SuggestionDecisionResponse(
        status="rejected",
        suggestion_status=suggestion.status,
        result_ref_json=suggestion.result_ref_json,
    )


@router.get("/conflicts", response_model=ConflictQueueListResponse)
async def list_world_conflicts(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    status: str | None = Query(None),
    conflict_type: str | None = Query(None),
) -> ConflictQueueListResponse:
    items, total = await _conflict_queue_service.list(
        db,
        novel_id,
        status=status,
        conflict_type=conflict_type,
    )
    return ConflictQueueListResponse(items=items, total=total)


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_world_conflict(
    db: DbSession,
    conflict_id: str,
    data: ConflictResolveRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> dict:
    item = await _conflict_queue_service.resolve(
        db,
        novel_id,
        conflict_id,
        status=data.status,
        resolution_json=data.resolution_json,
    )
    return {"status": item.status, "id": item.id}


@router.post(
    "/characters/{character_id}/knowledge-tags/{tag_id}/exclude",
    response_model=KnowledgeTagExclusionResponse,
)
async def exclude_character_knowledge_tag(
    db: DbSession,
    character_id: str,
    tag_id: str,
    data: KnowledgeTagExclusionRequest,
) -> KnowledgeTagExclusionResponse:
    await require_active_project(db, data.novel_id)
    return await _knowledge_tag_service.create_exclusion(
        db,
        data.novel_id,
        character_id,
        tag_id,
        reason=data.reason,
    )


@router.delete(
    "/characters/{character_id}/knowledge-tags/{tag_id}/exclude",
    response_model=KnowledgeTagExclusionResponse,
)
async def delete_character_knowledge_tag_exclusion(
    db: DbSession,
    character_id: str,
    tag_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> KnowledgeTagExclusionResponse:
    return await _knowledge_tag_service.delete_exclusion(
        db,
        novel_id,
        character_id,
        tag_id,
    )


@router.post("/characters/{character_id}/knowledge-tags/{tag_id}/lock")
async def lock_character_knowledge_tag(
    db: DbSession,
    character_id: str,
    tag_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> dict:
    return await _knowledge_tag_service.lock_tag(db, novel_id, character_id, tag_id)


# ============================================================
# CoreEntity 路由
# ============================================================


@router.get("/entity-types", response_model=EntityTypeCatalogResponse)
async def list_entity_types(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
) -> EntityTypeCatalogResponse:
    return await _entity_service.list_entity_types(db, novel_id)


@router.get("/review-type-catalog", response_model=ReviewTypeCatalogResponse)
async def get_review_type_catalog() -> ReviewTypeCatalogResponse:
    """Author-facing recommendations; relation and alias values remain open strings."""
    return ReviewTypeCatalogResponse.model_validate(review_type_catalog())


@router.get("/entities", response_model=CoreEntityListResponse)
async def list_entities(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    entity_type: str | None = Query(None, description="实体类型过滤"),
    status: str | None = Query(None, description="状态过滤"),
    display_state: Literal["active", "review", "archived"] | None = Query(
        None,
        description="作者展示状态过滤（兼容保留 status）",
    ),
    q: str | None = Query(None, description="名称、别名或描述的模糊搜索"),
    source: str | None = Query(None, description="来源过滤"),
    workflow_id: str | None = Query(None, description="深度导入 workflow ID"),
    needs_review: bool | None = Query(None, description="是否需要复核"),
    auto_ingested: bool | None = Query(None, description="是否自动导入"),
    suggested_action: str | None = Query(None, description="待处理项的建议动作"),
    scene_id: str | None = Query(None, description="来源 Scene ID"),
    scene_index: int | None = Query(None, description="来源 Scene 索引"),
    source_chapter_index: int | None = Query(None, description="来源章节索引"),
    confidence_min: float | None = Query(None, ge=0.0, le=1.0, description="最低置信度"),
    confidence_max: float | None = Query(None, ge=0.0, le=1.0, description="最高置信度"),
    view_mode: Literal["normal", "hot"] = Query(
        "normal",
        description="列表浏览模式：normal / hot",
    ),
    focus: Literal["important", "hot", "other"] | None = Query(
        None,
        description="热点模式聚合筛选",
    ),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> CoreEntityListResponse:
    return await _entity_service.list(
        db,
        novel_id,
        entity_type=entity_type,
        status=status,
        display_state=display_state,
        q=q,
        source=source,
        workflow_id=workflow_id,
        needs_review=needs_review,
        auto_ingested=auto_ingested,
        suggested_action=suggested_action,
        scene_id=scene_id,
        scene_index=scene_index,
        source_chapter_index=source_chapter_index,
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        view_mode=view_mode,
        focus=focus,
        skip=skip,
        limit=limit,
    )


@router.post("/entities", response_model=CoreEntityResponse, status_code=201)
async def create_entity(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    data: CoreEntityCreate = ...,
) -> CoreEntityResponse:
    return await _entity_service.create(db, novel_id, data)


@router.post(
    "/alias-relations/extract",
    response_model=WorldAliasRelationExtractResponse,
    status_code=201,
)
async def extract_alias_relations(
    db: DbSession,
    data: WorldAliasRelationExtractRequest,
) -> WorldAliasRelationExtractResponse:
    """提交手动别名/关系补抽任务。"""
    await require_active_project(db, data.novel_id)
    if not data.context_confirmation_id:
        raise HTTPException(
            status_code=400,
            detail="context_confirmation_id is required",
        )
    payload = data.model_dump(mode="json", exclude_none=True, exclude={"operation_id"})
    try:
        existing = await get_operation_task(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type="world_alias_relation_extraction",
            novel_id=data.novel_id,
            request_payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if existing is not None:
        return WorldAliasRelationExtractResponse(
            task_id=existing.task_id,
            status=existing.status,
        )
    try:
        await require_fresh_confirmation(
            db,
            novel_id=data.novel_id,
            action="world.alias_relations.extract",
            confirmation_id=data.context_confirmation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    llm_execution_snapshot = await build_project_llm_execution_snapshot(
        db,
        data.novel_id,
    )
    try:
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type="world_alias_relation_extraction",
            novel_id=data.novel_id,
            request_payload=payload,
            meta={
                **payload,
                "llm_execution_snapshot": llm_execution_snapshot,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not receipt.reused:
        await attach_result_ref(
            db,
            novel_id=data.novel_id,
            confirmation_id=data.context_confirmation_id,
            result_type="task",
            result_id=receipt.task_id,
            status="running",
        )
    await db.flush()
    return WorldAliasRelationExtractResponse(
        task_id=receipt.task_id,
        status=receipt.status,
    )


@router.get("/entities/{entity_id}", response_model=CoreEntityResponse)
async def get_entity(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CoreEntityResponse:
    return await _entity_service.get(db, entity_id, novel_id=novel_id)


@router.put(
    "/entities/{entity_id}/image",
    response_model=CoreEntityResponse,
    dependencies=[Depends(require_xhr_request)],
)
async def upload_entity_image(
    db: DbSession,
    entity_id: str,
    image: Annotated[UploadFile, File()],
    *,
    novel_id: ActiveNovelIdQuery,
) -> CoreEntityResponse:
    payload = await image.read(MAX_WORLD_OBJECT_IMAGE_BYTES)
    if len(payload) >= MAX_WORLD_OBJECT_IMAGE_BYTES or await image.read(1):
        raise HTTPException(status_code=413, detail="图片必须小于 6MiB")
    try:
        return await _entity_image_service.upload(
            db,
            novel_id=novel_id,
            entity_id=entity_id,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/entities/{entity_id}/image")
async def get_entity_image(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    variant: Literal["thumbnail", "full"] = Query(default="thumbnail"),
) -> Response:
    payload = await _entity_image_service.get(
        db,
        novel_id=novel_id,
        entity_id=entity_id,
        variant=variant,
    )
    return Response(
        payload,
        media_type="image/webp",
        headers={"Cache-Control": "private, no-store"},
    )


@router.put("/entities/{entity_id}", response_model=CoreEntityResponse)
async def update_entity(
    db: DbSession,
    entity_id: str,
    data: CoreEntityUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CoreEntityResponse:
    return await _entity_service.update(db, entity_id, data, novel_id=novel_id)


@router.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> None:
    await _entity_service.delete(db, entity_id, novel_id=novel_id)


@router.post("/entities/{candidate_id}/merge", response_model=EntityMergeResponse)
async def merge_entity(
    db: DbSession,
    candidate_id: str,
    data: EntityMergeRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> EntityMergeResponse:
    result = await _dedup_service.merge_candidate_into_entity(
        db,
        novel_id,
        candidate_id,
        data.target_entity_id,
    )
    affected_ids = [result.candidate_entity_id, result.target_entity_id]
    return EntityMergeResponse(
        target_entity_id=result.target_entity_id,
        candidate_entity_id=result.candidate_entity_id,
        affected_ids=affected_ids,
        merged_ids=[result.candidate_entity_id],
    )


@router.post("/entities/{candidate_id}/resolve-as-alias")
async def resolve_entity_as_alias(
    db: DbSession,
    candidate_id: str,
    data: EntityResolveAsAliasRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> dict:
    return await _alias_service.resolve_candidate_as_alias(
        db,
        novel_id,
        candidate_id,
        target_entity_id=data.target_entity_id,
        alias=data.alias,
        alias_type=data.alias_type,
        alias_kind=data.alias_kind,
    )


@router.post(
    "/entities/fusion-suggestions",
    response_model=EntityFusionSuggestionResponse,
    status_code=201,
)
async def create_entity_fusion_suggestions(
    db: DbSession,
    data: EntityFusionSuggestionRequest,
) -> EntityFusionSuggestionResponse:
    await require_active_project(db, data.novel_id)
    payload = data.model_dump(mode="json", exclude_none=True, exclude={"operation_id"})
    try:
        existing = await get_operation_task(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type="world_entity_fusion_suggestions",
            novel_id=data.novel_id,
            request_payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if existing is not None:
        return EntityFusionSuggestionResponse(
            task_id=existing.task_id,
            status=existing.status,
        )
    try:
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type="world_entity_fusion_suggestions",
            novel_id=data.novel_id,
            request_payload=payload,
            meta=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.flush()
    return EntityFusionSuggestionResponse(
        task_id=receipt.task_id,
        status=receipt.status,
    )


@router.post(
    "/entities/fusion-suggestions/apply",
    response_model=EntityFusionApplyResponse,
)
async def apply_entity_fusion_suggestions(
    db: DbSession,
    data: EntityFusionApplyRequest,
) -> EntityFusionApplyResponse:
    await require_active_project(db, data.novel_id)
    result = await _fusion_service.apply(
        db,
        novel_id=data.novel_id,
        confirmed=data.confirmed,
        suggestions=data.suggestions,
    )
    return EntityFusionApplyResponse(**result)


@router.post(
    "/entities/{entity_id}/promote",
    response_model=EntityPromoteResponse,
)
async def promote_entity(
    db: DbSession,
    entity_id: str,
    data: EntityPromoteRequest = EntityPromoteRequest(),
    *,
    novel_id: ActiveNovelIdQuery,
) -> EntityPromoteResponse:
    """采用待处理实体；原始状态字段保持兼容。"""
    return await _entity_service.promote(
        db,
        entity_id,
        data,
        novel_id=novel_id,
    )


@router.get("/entities/{entity_id}/relations", response_model=EntityRelationListResponse)
async def get_entity_relations(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> EntityRelationListResponse:
    """获取实体的关联关系"""
    return await _relation_service.get_by_entity(db, novel_id, entity_id)


# ============================================================
# Event 路由
# ============================================================


@router.get("/events", response_model=EventListResponse)
async def list_events(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> EventListResponse:
    items, total = await _event_service.list(db, novel_id, skip=skip, limit=limit)
    return EventListResponse(items=items, total=total)


@router.post("/events", response_model=EventResponse, status_code=201)
async def create_event(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    data: EventCreate = ...,
) -> EventResponse:
    return await _event_service.create(db, novel_id, data)


@router.get("/events/{entity_id}", response_model=EventResponse)
async def get_event(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> EventResponse:
    return await _event_service.get(db, entity_id, novel_id=novel_id)


@router.put("/events/{entity_id}", response_model=EventResponse)
async def update_event(
    db: DbSession,
    entity_id: str,
    data: EventUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> EventResponse:
    return await _event_service.update(db, entity_id, data, novel_id=novel_id)


@router.delete("/events/{entity_id}", status_code=204)
async def delete_event(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> None:
    await _event_service.delete(db, entity_id, novel_id=novel_id)


# ============================================================
# EntityRelation 路由
# ============================================================


@router.get("/relations", response_model=EntityRelationListResponse)
async def list_relations(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    status: str | None = Query(None, description="状态过滤"),
    relation_type: str | None = Query(None, description="关系类型过滤"),
    relation_kind: RelationKind | None = Query(None, description="最小语义类型过滤"),
    q: str | None = Query(None, description="关系/端点名称搜索"),
    source_chapter_id: str | None = Query(None, description="来源章节 ID"),
    strength_min: float | None = Query(None, ge=0.0, le=1.0, description="最低强度"),
    strength_max: float | None = Query(None, ge=0.0, le=1.0, description="最高强度"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> EntityRelationListResponse:
    return await _relation_service.list(
        db,
        novel_id,
        status=status,
        relation_type=relation_type,
        relation_kind=relation_kind,
        q=q,
        source_chapter_id=source_chapter_id,
        strength_min=strength_min,
        strength_max=strength_max,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/relations/review-groups",
    response_model=EntityRelationReviewGroupListResponse,
)
async def list_relation_review_groups(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    q: str | None = Query(None),
    relation_type: str | None = Query(None),
    relation_kind: RelationKind | None = Query(None),
    source_chapter_id: str | None = Query(None),
    scene_id: str | None = Query(None),
    scene_index: int | None = Query(None),
    source_chapter_index: int | None = Query(None),
    strength_min: float | None = Query(None, ge=0.0, le=1.0),
    strength_max: float | None = Query(None, ge=0.0, le=1.0),
    has_quote: bool | None = Query(None),
    type_kind: Literal["recommended", "custom"] | None = Query(None),
    multi_type_only: bool = Query(False),
    has_reverse_candidates: bool | None = Query(None),
    has_canonical_relation: bool | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
) -> EntityRelationReviewGroupListResponse:
    return await _relation_service.list_review_groups(
        db,
        novel_id,
        q=q,
        relation_type=relation_type,
        relation_kind=relation_kind,
        source_chapter_id=source_chapter_id,
        scene_id=scene_id,
        scene_index=scene_index,
        source_chapter_index=source_chapter_index,
        strength_min=strength_min,
        strength_max=strength_max,
        has_quote=has_quote,
        type_kind=type_kind,
        multi_type_only=multi_type_only,
        has_reverse_candidates=has_reverse_candidates,
        has_canonical_relation=has_canonical_relation,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/relations/review-batch",
    response_model=ReviewBatchResponse,
)
async def review_relations_batch(
    db: DbSession,
    data: EntityRelationReviewBatchRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> ReviewBatchResponse:
    return await _relation_service.review_batch(db, novel_id, data)


@router.post("/relations", response_model=EntityRelationResponse, status_code=201)
async def create_relation(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    data: EntityRelationCreate = ...,
) -> EntityRelationResponse:
    return await _relation_service.create(db, novel_id, data)


@router.put("/relations/{rel_id}", response_model=EntityRelationResponse)
async def update_relation(
    db: DbSession,
    rel_id: str,
    data: EntityRelationUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> EntityRelationResponse:
    return await _relation_service.update(db, rel_id, data, novel_id=novel_id)


@router.patch("/relations/{rel_id}/review-edit")
async def review_edit_relation(
    db: DbSession,
    rel_id: str,
    data: EntityRelationReviewEditRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> dict[str, object]:
    return await _relation_service.review_edit(db, novel_id, rel_id, data)


@router.delete("/relations/{rel_id}", status_code=204)
async def delete_relation(
    db: DbSession,
    rel_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> None:
    await _relation_service.delete(db, rel_id, novel_id=novel_id)


# ============================================================
# EntityRevision 路由
# ============================================================


@router.get(
    "/entities/{entity_id}/revisions",
    response_model=EntityRevisionListResponse,
)
async def list_revisions(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(default=20, ge=1, le=100, description="每页条数"),
) -> EntityRevisionListResponse:
    result = await _revision_service.get_revisions(
        db,
        entity_id,
        novel_id,
        skip=skip,
        limit=limit,
    )
    return EntityRevisionListResponse(items=result["items"], total=result["total"])


@router.post("/entities/{entity_id}/rollback", response_model=EntityRollbackResponse)
async def rollback_entity(
    db: DbSession,
    entity_id: str,
    data: EntityRollbackRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> EntityRollbackResponse:
    result = await _revision_service.rollback_to_scene_index(
        db,
        entity_id,
        data.target_scene_index,
        novel_id,
    )
    return EntityRollbackResponse(
        entity_id=result["entity_id"],
        target_scene_index=result["target_scene_index"],
        restored_fields=result["restored_fields"],
        warnings=result["warnings"],
    )


@router.post(
    "/entities/{entity_id}/rollback-by-revision",
    response_model=CoreEntityResponse,
)
async def rollback_entity_by_revision(
    db: DbSession,
    entity_id: str,
    revision_id: str = Query(..., description="目标版本 ID"),
    *,
    novel_id: ActiveNovelIdQuery,
) -> CoreEntityResponse:
    return await _revision_service.rollback_to_revision(
        db,
        entity_id,
        revision_id,
        novel_id,
    )


@router.post(
    "/_test/entities/{entity_id}/text-archive",
    response_model=TextArchiveSeedResponse,
    status_code=201,
    summary="E2E 测试专用：为实体写入 TextArchive 归档",
)
async def seed_entity_text_archive(
    db: DbSession,
    entity_id: str,
    data: TextArchiveSeedRequest,
) -> TextArchiveSeedResponse:
    settings = get_settings()
    if settings.app_env != "test":
        raise HTTPException(status_code=404, detail="Not found")

    await require_active_project(db, data.novel_id)

    archive = await _revision_service.seed_text_archive(
        db,
        entity_id=entity_id,
        novel_id=data.novel_id,
        field_name=data.field_name,
        text_content=data.text_content,
        scene_index=data.scene_index,
    )
    return TextArchiveSeedResponse(
        status="ok",
        entity_id=entity_id,
        field_name=data.field_name,
        archive_id=str(archive.id),
    )


# ============================================================
# Character 路由
# ============================================================


@router.get("/characters", response_model=CharacterListResponse)
async def list_characters(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> CharacterListResponse:
    items, total = await _character_service.list(
        db,
        novel_id,
        skip=skip,
        limit=limit,
    )
    return CharacterListResponse(items=items, total=total)


@router.post("/characters", response_model=CharacterResponse, status_code=201)
async def create_character(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    data: CharacterCreate = ...,
) -> CharacterResponse:
    return await _character_service.create(db, novel_id, data)


@router.get("/characters/{character_id}", response_model=CharacterResponse)
async def get_character(
    db: DbSession,
    character_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CharacterResponse:
    return await _character_service.get(
        db,
        character_id,
        novel_id=novel_id,
    )


@router.put("/characters/{character_id}", response_model=CharacterResponse)
async def update_character(
    db: DbSession,
    character_id: str,
    data: CharacterUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CharacterResponse:
    return await _character_service.update(
        db,
        character_id,
        data,
        novel_id=novel_id,
    )


@router.delete("/characters/{character_id}", status_code=204)
async def delete_character(
    db: DbSession,
    character_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> None:
    await _character_service.delete(db, character_id, novel_id=novel_id)


# ============================================================
# CharacterKnowledge 路由 (独立 CharacterKnowledgeService)
# ============================================================


@router.get(
    "/characters/{character_id}/knowledge",
    response_model=CharacterKnowledgeListResponse,
)
async def list_knowledge(
    db: DbSession,
    character_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> CharacterKnowledgeListResponse:
    return await _knowledge_service.list(
        db,
        novel_id,
        character_id,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/characters/{character_id}/knowledge",
    response_model=CharacterKnowledgeResponse,
    status_code=201,
)
async def create_knowledge(
    db: DbSession,
    character_id: str,
    data: CharacterKnowledgeCreate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CharacterKnowledgeResponse:
    if data.character_id != character_id:
        raise HTTPException(
            status_code=400,
            detail="character_id in path and body must match",
        )
    return await _knowledge_service.create(db, novel_id, data)


@router.put(
    "/knowledge/{knowledge_id}",
    response_model=CharacterKnowledgeResponse,
)
async def update_knowledge(
    db: DbSession,
    knowledge_id: str,
    data: CharacterKnowledgeUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CharacterKnowledgeResponse:
    return await _knowledge_service.update(
        db,
        knowledge_id,
        data,
        novel_id=novel_id,
    )


@router.delete("/knowledge/{knowledge_id}", status_code=204)
async def delete_knowledge(
    db: DbSession,
    knowledge_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> None:
    await _knowledge_service.delete(
        db,
        knowledge_id,
        novel_id=novel_id,
    )


@router.get("/entity-batches")
async def list_entity_batches(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    limit: int = Query(default=10, ge=1, le=50, description="最多返回的批次数量"),
) -> list[dict]:
    """获取自动入库实体的批次分组列表

    每次 LLM 抽取生成一个 batch_id，同一批次的实体归为一组。
    按入库时间倒序排列。
    """
    return await _context_service.list_entity_batches(
        db,
        novel_id,
        limit=limit,
    )


# ============================================================
# Entity Alias 路由（操作 core_entities.content_json.aliases）
# ============================================================


@router.get("/aliases")
async def list_aliases(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    q: str | None = Query(None, description="别名/对象/引用搜索"),
    display_state: Literal["active", "review", "archived"] | None = Query(
        None,
        description="作者展示态过滤",
    ),
    status: str | None = Query(None, description="状态过滤"),
    alias_kind: AliasKind | None = Query(None, description="最小语义类型过滤"),
    needs_review: bool | None = Query(None, description="是否需要复核"),
    source: str | None = Query(None, description="来源过滤"),
    workflow_id: str | None = Query(None, description="深度导入 workflow ID"),
    scene_id: str | None = Query(None, description="来源 Scene ID"),
    scene_index: int | None = Query(None, description="来源 Scene 索引"),
    source_chapter_index: int | None = Query(None, description="来源章节索引"),
    confidence_min: float | None = Query(None, ge=0.0, le=1.0, description="最低置信度"),
    confidence_max: float | None = Query(None, ge=0.0, le=1.0, description="最高置信度"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """列出项目下所有实体的别名"""
    return await _alias_service.list_aliases_page(
        db,
        novel_id,
        q=q,
        display_state=display_state,
        status=status,
        alias_kind=alias_kind,
        needs_review=needs_review,
        source=source,
        workflow_id=workflow_id,
        scene_id=scene_id,
        scene_index=scene_index,
        source_chapter_index=source_chapter_index,
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/aliases/review-groups",
    response_model=EntityAliasReviewGroupListResponse,
)
async def list_alias_review_groups(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    q: str | None = Query(None),
    source: str | None = Query(None),
    workflow_id: str | None = Query(None),
    scene_id: str | None = Query(None),
    scene_index: int | None = Query(None),
    source_chapter_index: int | None = Query(None),
    confidence_min: float | None = Query(None, ge=0.0, le=1.0),
    confidence_max: float | None = Query(None, ge=0.0, le=1.0),
    has_quote: bool | None = Query(None),
    type_kind: Literal["recommended", "custom"] | None = Query(None),
    alias_kind: AliasKind | None = Query(None),
    multi_alias_only: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
) -> EntityAliasReviewGroupListResponse:
    return await _alias_service.list_review_groups(
        db,
        novel_id,
        q=q,
        source=source,
        workflow_id=workflow_id,
        scene_id=scene_id,
        scene_index=scene_index,
        source_chapter_index=source_chapter_index,
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        has_quote=has_quote,
        type_kind=type_kind,
        alias_kind=alias_kind,
        multi_alias_only=multi_alias_only,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/aliases/review-batch",
    response_model=ReviewBatchResponse,
)
async def review_aliases_batch(
    db: DbSession,
    data: EntityAliasReviewBatchRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> ReviewBatchResponse:
    return await _alias_service.review_batch(db, novel_id, data)


@router.post("/aliases", status_code=201)
async def create_alias(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    data: EntityAliasCreate = ...,
) -> dict:
    """为实体添加别名"""
    return await _alias_service.create_alias(
        db,
        novel_id,
        data.entity_id,
        data.alias,
        data.alias_type,
        alias_kind=data.alias_kind,
        status=data.status,
        source="manual",
        source_chapter_index=data.source_chapter_index,
        confidence=data.confidence,
    )


@router.patch("/entities/{entity_id}/aliases")
async def update_alias(
    db: DbSession,
    entity_id: str,
    data: EntityAliasUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
    alias: str = Query(..., description="要更新的别名文本"),
) -> dict:
    """更新实体的指定别名元数据。"""
    return await _alias_service.update_alias(
        db,
        novel_id,
        entity_id,
        alias,
        data.model_dump(exclude_unset=True),
    )


@router.patch("/entities/{entity_id}/aliases/edit")
async def edit_alias(
    db: DbSession,
    entity_id: str,
    data: EntityAliasEditRequest,
    *,
    novel_id: ActiveNovelIdQuery,
    alias: str = Query(..., description="要编辑的原别名文本"),
) -> dict:
    return await _alias_service.edit_alias(
        db,
        novel_id,
        entity_id,
        alias,
        target_entity_id=data.target_entity_id,
        alias=data.alias,
        alias_type=data.alias_type,
        alias_kind=data.alias_kind,
        confirm_review=data.confirm_review,
    )


@router.delete("/entities/{entity_id}/aliases")
async def delete_alias(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    alias: str = Query(..., description="要删除的别名文本"),
) -> dict:
    """删除实体的指定别名"""
    return await _alias_service.delete_alias(
        db,
        novel_id,
        entity_id,
        alias,
    )
