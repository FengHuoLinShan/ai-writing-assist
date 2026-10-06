"""Canon 正史与知识图谱路由。"""

from __future__ import annotations

from typing import Literal

from fastapi import Query

from core.dependencies import DbSession
from modules.account.facade import current_account_id
from modules.project.facade import require_active_project
from modules.project.facade import (
    require_active_project_exclusive as _require_active_project_exclusive,
)
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _knowledge_graph_service,
    _world_authority_service,
    router,
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
from modules.world.schemas import WorldKnowledgeGraphResponse


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
