"""Narrow author HTTP entries for catalog operations without a matching domain route."""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as SchemaError

from core.api_params import NovelIdQuery
from core.dependencies import DbSession
from core.errors import ConflictError
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.evidence_tools import fingerprint
from modules.assistant.operations import catalog
from modules.assistant.schemas import WorkContext
from modules.project.facade import require_active_project

router = APIRouter(prefix="/api/assistant/operation-http", tags=["assistant"])


class OperationArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arguments: dict = Field(default_factory=dict)


class ConfirmedOperationArguments(OperationArguments):
    expected_preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]


def _author_context(*, page: Literal["world", "scene", "writing", "rag"]):
    return AssistantOperationContext(
        run_id=str(uuid4()),
        owner_id=str(current_account_id()),
        work=WorkContext(page=page, scope="project"),
        trace_entrypoint="assistant.http",
        trace_actor_type="ui",
    )


def _validate_arguments(operation_id: str, values: dict):
    try:
        return catalog()[operation_id].schema.model_validate(values)
    except SchemaError as error:
        raise HTTPException(
            status_code=422,
            detail=error.errors(include_input=False, include_url=False),
        ) from None


async def _preview(db, novel_id: str, operation_id: str, values: dict, page):
    await require_active_project(db, novel_id, allow_demo_readonly=False)
    operation = catalog()[operation_id]
    args = _validate_arguments(operation_id, values)
    preview = await operation.prepare(
        db, novel_id, args, context=_author_context(page=page)
    )
    return {"preview": preview, "preview_hash": fingerprint(preview)}


async def _apply(db, novel_id: str, operation_id: str, data, page):
    await require_active_project(db, novel_id, allow_demo_readonly=False)
    operation = catalog()[operation_id]
    args = _validate_arguments(operation_id, data.arguments)
    context = _author_context(page=page)
    preview = await operation.prepare(db, novel_id, args, context=context)
    if fingerprint(preview) != data.expected_preview_hash:
        raise ConflictError("操作预览已经变化，请重新核对并确认")
    return await operation.apply(db, novel_id, args, preview, context=context)


async def _read(db, novel_id: str, operation_id: str, values: dict):
    await require_active_project(db, novel_id, allow_demo_readonly=False)
    operation = catalog()[operation_id]
    args = _validate_arguments(operation_id, values)
    return await operation.prepare(
        db, novel_id, args, context=_author_context(page="rag")
    )


@router.post(
    "/previews/world/entity/transition-type",
    openapi_extra={
        "x-novelcraft-operation-id": "world.entity.transition_type",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": {
            "entity_id": "data.arguments.entity_id",
            "new_type": "data.arguments.new_type",
        },
    },
)
async def preview_entity_type_transition(
    db: DbSession, data: OperationArguments, *, novel_id: NovelIdQuery
):
    return await _preview(
        db, novel_id, "world.entity.transition_type", data.arguments, "world"
    )


@router.post(
    "/previews/story/scene/split",
    openapi_extra={
        "x-novelcraft-operation-id": "story.scene.split",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": {
            "source_scene_id": "data.arguments.source_scene_id",
            "split_chapter_index": "data.arguments.split_chapter_index",
            "split_pos": "data.arguments.split_pos",
            "new_scene_title": "data.arguments.new_scene_title",
            "new_scene_status": "data.arguments.new_scene_status",
        },
    },
)
async def preview_scene_split(
    db: DbSession, data: OperationArguments, *, novel_id: NovelIdQuery
):
    return await _preview(db, novel_id, "story.scene.split", data.arguments, "scene")


@router.post(
    "/previews/writing/chapter/rename",
    openapi_extra={
        "x-novelcraft-operation-id": "writing.chapter.rename",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": {
            "draft_id": "data.arguments.draft_id",
            "title": "data.arguments.title",
        },
    },
)
async def preview_chapter_rename(
    db: DbSession, data: OperationArguments, *, novel_id: NovelIdQuery
):
    return await _preview(
        db, novel_id, "writing.chapter.rename", data.arguments, "writing"
    )


@router.post(
    "/previews/writing/chapter/check-conflicts",
    openapi_extra={
        "x-novelcraft-operation-id": "writing.conflict_check.create",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": {
            "draft_id": "data.arguments.draft_id",
            "expected_content_hash": "data.arguments.expected_content_hash",
            "scene_id": "data.arguments.scene_id",
        },
    },
)
async def preview_chapter_conflicts(
    db: DbSession, data: OperationArguments, *, novel_id: NovelIdQuery
):
    return await _preview(
        db, novel_id, "writing.conflict_check.create", data.arguments, "writing"
    )


@router.post(
    "/world/entity/transition-type",
    openapi_extra={
        "x-novelcraft-operation-id": "world.entity.transition_type",
        "x-novelcraft-operation-confirmation-field": "data.confirmed",
        "x-novelcraft-operation-trace-fields": {
            "entity_id": "data.arguments.entity_id",
            "new_type": "data.arguments.new_type",
        },
    },
)
async def transition_entity_type(
    db: DbSession, data: ConfirmedOperationArguments, *, novel_id: NovelIdQuery
):
    return await _apply(db, novel_id, "world.entity.transition_type", data, "world")


@router.post(
    "/story/scene/split",
    openapi_extra={
        "x-novelcraft-operation-id": "story.scene.split",
        "x-novelcraft-operation-confirmation-field": "data.confirmed",
        "x-novelcraft-operation-trace-fields": {
            "source_scene_id": "data.arguments.source_scene_id",
            "split_chapter_index": "data.arguments.split_chapter_index",
            "split_pos": "data.arguments.split_pos",
            "new_scene_title": "data.arguments.new_scene_title",
            "new_scene_status": "data.arguments.new_scene_status",
        },
    },
)
async def split_scene(
    db: DbSession, data: ConfirmedOperationArguments, *, novel_id: NovelIdQuery
):
    return await _apply(db, novel_id, "story.scene.split", data, "scene")


@router.post(
    "/writing/chapter/rename",
    openapi_extra={
        "x-novelcraft-operation-id": "writing.chapter.rename",
        "x-novelcraft-operation-confirmation-field": "data.confirmed",
        "x-novelcraft-operation-trace-fields": {
            "draft_id": "data.arguments.draft_id",
            "title": "data.arguments.title",
        },
    },
)
async def rename_chapter(
    db: DbSession, data: ConfirmedOperationArguments, *, novel_id: NovelIdQuery
):
    return await _apply(db, novel_id, "writing.chapter.rename", data, "writing")


@router.post(
    "/writing/chapter/check-conflicts",
    openapi_extra={
        "x-novelcraft-operation-id": "writing.conflict_check.create",
        "x-novelcraft-operation-confirmation-field": "data.confirmed",
        "x-novelcraft-operation-trace-fields": {
            "draft_id": "data.arguments.draft_id",
            "expected_content_hash": "data.arguments.expected_content_hash",
            "scene_id": "data.arguments.scene_id",
        },
    },
)
async def check_chapter_conflicts(
    db: DbSession, data: ConfirmedOperationArguments, *, novel_id: NovelIdQuery
):
    return await _apply(db, novel_id, "writing.conflict_check.create", data, "writing")


@router.post(
    "/evidence/search",
    openapi_extra={
        "x-novelcraft-operation-id": "evidence.project.search",
        "x-novelcraft-operation-trace-fields": {
            "query": "data.arguments.query",
            "scopes": "data.arguments.scopes",
        },
    },
)
async def search_project_evidence(
    db: DbSession, data: OperationArguments, *, novel_id: NovelIdQuery
):
    return await _read(db, novel_id, "evidence.project.search", data.arguments)


@router.post(
    "/evidence/read",
    openapi_extra={
        "x-novelcraft-operation-id": "evidence.source.read",
        "x-novelcraft-operation-trace-fields": {
            "source_ref": "data.arguments.source_ref"
        },
    },
)
async def read_project_evidence(
    db: DbSession, data: OperationArguments, *, novel_id: NovelIdQuery
):
    return await _read(db, novel_id, "evidence.source.read", data.arguments)


@router.post(
    "/evidence/inspect",
    openapi_extra={
        "x-novelcraft-operation-id": "evidence.knowledge.preview_scope",
        "x-novelcraft-operation-trace-fields": {"target": "data.arguments.target"},
    },
)
async def inspect_project_evidence(
    db: DbSession, data: OperationArguments, *, novel_id: NovelIdQuery
):
    return await _read(db, novel_id, "evidence.knowledge.preview_scope", data.arguments)
