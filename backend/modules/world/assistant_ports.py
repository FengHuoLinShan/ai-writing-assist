"""World-owned validation and generation for the shared discussion service."""

from sqlalchemy import func, select

from core.errors import ConflictError, NotFoundError
from modules.world.models.core import CoreEntity
from modules.world.models.library import WorldLibraryTopic
from modules.world.models.worldbuilding import (
    CreationSuggestion,
    WorldBiblePage,
    WorldBiblePageDraft,
)


async def require_source(db, novel_id, kind, source_id):
    models = {
        "world_bible_page": (WorldBiblePage, WorldBiblePageDraft),
        "core_entity": (CoreEntity,),
        "world_library_topic": (WorldLibraryTopic,),
    }.get(kind, ())
    for model in models:
        if await db.scalar(
            select(func.count())
            .select_from(model)
            .where(model.novel_id == novel_id, model.id == source_id)
        ):
            return
    raise NotFoundError("Co-creation session source not found in this project")


async def outcome_states(db, novel_id, suggestion_ids):
    rows = await db.scalars(
        select(CreationSuggestion).where(
            CreationSuggestion.novel_id == novel_id,
            CreationSuggestion.id.in_(tuple(suggestion_ids)),
        )
    )
    return {
        row.id: "rejected"
        if row.status == "rejected"
        else (
            "saved_draft"
            if (row.result_ref_json or {}).get("type") == "world_bible_page_draft"
            else "adopted"
        )
        if row.status == "accepted"
        else "pending_review"
        for row in rows
    }


async def require_checkpoint(db, novel_id, suggestion_id):
    row = await db.scalar(
        select(CreationSuggestion).where(
            CreationSuggestion.novel_id == novel_id,
            CreationSuggestion.id == suggestion_id,
        )
    )
    if row is None:
        raise NotFoundError("Checkpoint suggestion not found in this project")
    if row.target_type not in {"world_design_checkpoint", "world_core_checkpoint"}:
        raise ConflictError(
            "Only a world design/core checkpoint can advance the session pointer",
            code="checkpoint_target_mismatch",
        )

    return {"payload": dict(row.payload_json or {}), "target_type": row.target_type}


async def chat(db, data):
    from modules.world.services.worldbuilding.world_generation_center_service import (
        WorldGenerationCenterService,
    )

    return await WorldGenerationCenterService().chat(db, data)


async def chat_intent(db, data):
    """Freeze author-selected templates and direction; fact reading stays in Evidence."""
    from modules.world.services.worldbuilding.world_generation_center_service import (
        _WORLD_CORE_CHAT_BOUNDARY,
        WorldGenerationCenterService,
    )

    service = WorldGenerationCenterService()
    source = await service._load_source(db, data)
    await service._validate_explicit_context(db, data)
    template = None
    if data.target.kind == "core_entity":
        selected = await service._prompt_templates.resolve_for_generation(
            db,
            novel_id=data.novel_id,
            template_id=data.target.template_id,
            template_version=data.target.template_version,
            template_variables=data.target.template_variables,
            object_template=data.target.template,
            template_name=data.target.template_name,
            template_prompt=data.target.template_prompt,
        )
        template = {"label": selected.label, "instruction": selected.rendered_prompt}
    page = await service._resolve_page_template(db, data, source)
    return {
        "direction": service._target_brief(data),
        "boundary": _WORLD_CORE_CHAT_BOUNDARY
        if data.workflow_preset == "world_core"
        else "",
        "template": template,
        "page_template": page.model_dump(
            mode="json",
            include={
                "name",
                "description",
                "sections_schema_json",
                "default_sections_json",
                "validation_rules_json",
                "version_number",
            },
        )
        if page
        else None,
        "pasted_context": data.pasted_context,
        "quality_mode": data.quality_mode,
    }
