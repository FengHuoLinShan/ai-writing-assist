"""HTTP routes for the owner-managed project vocabulary."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from core.dependencies import DbSession
from modules.project.facade import require_active_project
from modules.world.project_vocabulary_schemas import (
    ProjectVocabularyReadResponse,
    VocabularyArchiveRequest,
    VocabularyKind,
    VocabularyMergeRequest,
    VocabularyPresetApplyRequest,
    VocabularyPresetApplyResponse,
    VocabularyRestoreRequest,
    VocabularySplitRequest,
    VocabularySplitResponse,
    VocabularyTermCreate,
    VocabularyTermResponse,
    VocabularyTermUpdate,
)
from modules.world.project_vocabulary_service import (
    apply_vocabulary_presets,
    archive_project_vocabulary_term,
    create_project_vocabulary_term,
    get_project_vocabulary_term,
    get_project_vocabulary_term_revision,
    merge_project_vocabulary_terms,
    read_project_vocabulary,
    restore_project_vocabulary_term,
    split_project_vocabulary_term,
    update_project_vocabulary_term,
)

router = APIRouter(prefix="/api/world/project-vocabulary", tags=["world-vocabulary"])


@router.get("/{novel_id}", response_model=ProjectVocabularyReadResponse)
async def list_project_vocabulary(
    db: DbSession,
    novel_id: UUID,
    kind: VocabularyKind | None = None,
    include_archived: bool = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    await require_active_project(db, str(novel_id))
    return await read_project_vocabulary(
        db,
        str(novel_id),
        kind=kind,
        limit=limit,
        include_archived=include_archived,
    )


@router.get("/{novel_id}/terms/{type_ref}", response_model=VocabularyTermResponse)
async def get_vocabulary_term(
    db: DbSession,
    novel_id: UUID,
    type_ref: UUID,
    revision_id: UUID | None = None,
):
    await require_active_project(db, str(novel_id))
    if revision_id is not None:
        return await get_project_vocabulary_term_revision(
            db, str(novel_id), str(type_ref), str(revision_id)
        )
    return await get_project_vocabulary_term(db, str(novel_id), str(type_ref))


@router.post(
    "/{novel_id}/terms",
    response_model=VocabularyTermResponse,
    status_code=201,
    openapi_extra={"x-novelcraft-operation-id": "world.vocabulary.create"},
)
async def create_vocabulary_term(
    db: DbSession, novel_id: UUID, data: VocabularyTermCreate
):
    await require_active_project(db, str(novel_id))
    return await create_project_vocabulary_term(db, str(novel_id), data)


@router.patch(
    "/{novel_id}/terms/{type_ref}",
    response_model=VocabularyTermResponse,
    openapi_extra={"x-novelcraft-operation-id": "world.vocabulary.edit"},
)
async def update_vocabulary_term(
    db: DbSession,
    novel_id: UUID,
    type_ref: UUID,
    data: VocabularyTermUpdate,
):
    await require_active_project(db, str(novel_id))
    return await update_project_vocabulary_term(db, str(novel_id), str(type_ref), data)


@router.post(
    "/{novel_id}/terms/{type_ref}/archive",
    response_model=VocabularyTermResponse,
    openapi_extra={"x-novelcraft-operation-id": "world.vocabulary.archive"},
)
async def archive_vocabulary_term(
    db: DbSession,
    novel_id: UUID,
    type_ref: UUID,
    data: VocabularyArchiveRequest,
):
    await require_active_project(db, str(novel_id))
    return await archive_project_vocabulary_term(
        db, str(novel_id), str(type_ref), data.expected_revision_id
    )


@router.post(
    "/{novel_id}/terms/{type_ref}/restore",
    response_model=VocabularyTermResponse,
    openapi_extra={"x-novelcraft-operation-id": "world.vocabulary.restore"},
)
async def restore_vocabulary_term(
    db: DbSession,
    novel_id: UUID,
    type_ref: UUID,
    data: VocabularyRestoreRequest,
):
    await require_active_project(db, str(novel_id))
    return await restore_project_vocabulary_term(
        db, str(novel_id), str(type_ref), data.expected_revision_id
    )


@router.post(
    "/{novel_id}/merge",
    response_model=VocabularyTermResponse,
    openapi_extra={"x-novelcraft-operation-id": "world.vocabulary.merge"},
)
async def merge_vocabulary_terms(
    db: DbSession, novel_id: UUID, data: VocabularyMergeRequest
):
    await require_active_project(db, str(novel_id))
    return await merge_project_vocabulary_terms(db, str(novel_id), data)


@router.post(
    "/{novel_id}/terms/{type_ref}/split",
    response_model=VocabularySplitResponse,
    openapi_extra={"x-novelcraft-operation-id": "world.vocabulary.split"},
)
async def split_vocabulary_term(
    db: DbSession,
    novel_id: UUID,
    type_ref: UUID,
    data: VocabularySplitRequest,
):
    await require_active_project(db, str(novel_id))
    retained, split_off = await split_project_vocabulary_term(
        db, str(novel_id), str(type_ref), data
    )
    return {"retained": retained, "split_off": split_off}


@router.post(
    "/{novel_id}/presets",
    response_model=VocabularyPresetApplyResponse,
    openapi_extra={"x-novelcraft-operation-id": "world.vocabulary.apply_presets"},
)
async def apply_project_vocabulary_presets(
    db: DbSession, novel_id: UUID, data: VocabularyPresetApplyRequest
):
    await require_active_project(db, str(novel_id))
    return await apply_vocabulary_presets(db, str(novel_id), data.preset_ids)
