"""World API 共享基建。

持有唯一的 ``APIRouter``（前缀 /api/world、tag world、canon 校验路由类）、
active-novel 依赖与各子域共用的服务单例。子域模块从本模块导入 ``router``
装饰端点；``modules.world.api`` 聚合导入各子域以保持原注册顺序。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from core.api_params import NovelIdQuery
from core.dependencies import DbSession
from core.errors import DomainError
from modules.evidence.facade import attach_result_ref, require_fresh_confirmation
from modules.project.facade import require_active_project
from modules.world.entity_fusion import WorldEntityFusionService
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
from modules.world.services.revision_history_service import WorldChangeHistoryService
from modules.world.services.worldbuilding.adoption_package_service import (
    WorldAdoptionPackageService,
)
from modules.world.services.worldbuilding.ask_world_service import AskWorldService
from modules.world.services.worldbuilding.cocreation_session_service import (
    WorldCocreationSessionService,
)
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
from modules.world.services.worldbuilding.world_impact_service import (
    WorldImpactService,
)
from modules.world.services.worldbuilding.world_library_service import (
    WorldLibraryService,
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
    SuggestionQueueService,
    WorldBibleLifecycleService,
    WorldBiblePageTemplateService,
    WorldBibleService,
    WorldBibleSynopsisService,
    WorldProfileService,
)
from modules.world.world_object_image_generation import (
    WorldObjectImageGenerationService,
)
from modules.world.world_object_images import WorldObjectImageService

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
_entity_image_generation_service = WorldObjectImageGenerationService()
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
_world_impact_service = WorldImpactService()
_world_authority_service = WorldAuthorityService()
_world_library_service = WorldLibraryService()
_cocreation_session_service = WorldCocreationSessionService()
_change_history_service = WorldChangeHistoryService()


async def _require_active_novel_id(
    db: DbSession,
    novel_id: NovelIdQuery,
) -> str:
    await require_active_project(db, novel_id)
    return novel_id


ActiveNovelIdQuery = Annotated[str, Depends(_require_active_novel_id)]


def _template_version_conflict(exc: TemplateVersionConflictError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "status": "template_version_conflict",
            "expected_version": exc.expected,
            "actual_version": exc.actual,
        },
    )


async def _require_generation_confirmation(db: DbSession, data, action: str) -> None:
    if not data.context_confirmation_id:
        raise HTTPException(status_code=400, detail="context_confirmation_id is required")
    try:
        await require_fresh_confirmation(
            db,
            novel_id=data.novel_id,
            action=action,
            confirmation_id=data.context_confirmation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _attach_manual_context_result(db: DbSession, data, result) -> None:
    confirmation_id = getattr(data, "context_confirmation_id", None)
    if not confirmation_id:
        return
    usage = getattr(result, "context_usage", None)
    result_type = "context_snapshot"
    result_id = getattr(usage, "context_snapshot_id", None)
    if not result_id:
        result_id = getattr(result, "context_snapshot_id", None)
    if not result_id:
        suggestion = getattr(getattr(result, "result", None), "suggestion", None)
        result_id = getattr(suggestion, "id", None)
        result_type = "creation_suggestion"
    if not result_id:
        return
    await attach_result_ref(
        db,
        novel_id=data.novel_id,
        confirmation_id=confirmation_id,
        result_type=result_type,
        result_id=str(result_id),
        status="completed",
    )
