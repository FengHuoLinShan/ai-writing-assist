"""World object dossier and template routes."""

from __future__ import annotations

from fastapi import Query

from core.dependencies import DbSession
from modules.world.api._shared import ActiveNovelIdQuery, router
from modules.world.dossier_facade import (
    create_world_object_dossier_entry,
    edit_world_object_dossier_entry,
    get_world_object_dossier_template,
    list_world_object_dossier_facets_for_entity,
    read_world_object_dossier,
    read_world_object_dossier_history,
    read_world_object_dossier_template_history,
    restore_world_object_dossier_entry,
    save_world_object_dossier_template,
)
from modules.world.schemas.dossier import (
    DossierEntryCreate,
    DossierEntryResponse,
    DossierEntryRestore,
    DossierEntryUpdate,
    DossierFacetCatalog,
    DossierHistoryResponse,
    DossierReadResponse,
    DossierTemplateHistoryResponse,
    DossierTemplateResponse,
    DossierTemplateUpsert,
)


@router.get(
    "/entities/{entity_id}/dossier",
    response_model=DossierReadResponse,
    openapi_extra={"x-novelcraft-operation-id": "world.dossier.read"},
)
async def read_dossier(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    as_of_scene_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
) -> DossierReadResponse:
    return await read_world_object_dossier(
        db,
        novel_id,
        entity_id,
        as_of_scene_id=as_of_scene_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/entities/{entity_id}/dossier/facets",
    response_model=DossierFacetCatalog,
)
async def list_dossier_facets(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> DossierFacetCatalog:
    return await list_world_object_dossier_facets_for_entity(db, novel_id, entity_id)


@router.get(
    "/entities/{entity_id}/dossier/history",
    response_model=DossierHistoryResponse,
    openapi_extra={"x-novelcraft-operation-id": "world.dossier.history.read"},
)
async def read_dossier_history(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    entry_group_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> DossierHistoryResponse:
    return await read_world_object_dossier_history(
        db,
        novel_id,
        entity_id,
        entry_group_id=entry_group_id,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/entities/{entity_id}/dossier/entries",
    response_model=DossierEntryResponse,
    status_code=201,
    openapi_extra={
        "x-novelcraft-operation-id": "world.dossier.entry.create",
        "x-novelcraft-operation-argument-map": {"data": "entry"},
    },
)
async def create_dossier_entry(
    db: DbSession,
    entity_id: str,
    data: DossierEntryCreate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> DossierEntryResponse:
    return await create_world_object_dossier_entry(db, novel_id, entity_id, data)


@router.patch(
    "/entities/{entity_id}/dossier/entries/{revision_id}",
    response_model=DossierEntryResponse,
    openapi_extra={
        "x-novelcraft-operation-id": "world.dossier.entry.edit",
        "x-novelcraft-operation-argument-map": {"data": "update"},
    },
)
async def update_dossier_entry(
    db: DbSession,
    entity_id: str,
    revision_id: str,
    data: DossierEntryUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> DossierEntryResponse:
    return await edit_world_object_dossier_entry(
        db, novel_id, entity_id, revision_id, data
    )


@router.post(
    "/entities/{entity_id}/dossier/groups/{entry_group_id}/restore",
    response_model=DossierEntryResponse,
    openapi_extra={
        "x-novelcraft-operation-id": "world.dossier.entry.restore",
        "x-novelcraft-operation-argument-map": {"data": "restore"},
    },
)
async def restore_dossier_entry(
    db: DbSession,
    entity_id: str,
    entry_group_id: str,
    data: DossierEntryRestore,
    *,
    novel_id: ActiveNovelIdQuery,
) -> DossierEntryResponse:
    return await restore_world_object_dossier_entry(
        db, novel_id, entity_id, entry_group_id, data
    )


@router.get(
    "/dossier-templates/{profile_type}",
    response_model=DossierTemplateResponse,
    openapi_extra={"x-novelcraft-operation-id": "world.dossier.template.read"},
)
async def read_dossier_template(
    db: DbSession,
    profile_type: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> DossierTemplateResponse:
    return await get_world_object_dossier_template(db, novel_id, profile_type)


@router.get(
    "/dossier-templates/{profile_type}/history",
    response_model=DossierTemplateHistoryResponse,
)
async def read_dossier_template_history(
    db: DbSession,
    profile_type: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> DossierTemplateHistoryResponse:
    return await read_world_object_dossier_template_history(db, novel_id, profile_type)


@router.put(
    "/dossier-templates/{profile_type}",
    response_model=DossierTemplateResponse,
    openapi_extra={
        "x-novelcraft-operation-id": "world.dossier.template.edit",
        "x-novelcraft-operation-argument-map": {"data": "update"},
    },
)
async def upsert_dossier_template(
    db: DbSession,
    profile_type: str,
    data: DossierTemplateUpsert,
    *,
    novel_id: ActiveNovelIdQuery,
) -> DossierTemplateResponse:
    return await save_world_object_dossier_template(db, novel_id, profile_type, data)
