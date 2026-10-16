"""Stable World-layer dossier facade; it never aggregates Story or Evolution."""

from modules.world.dossier_interchange import (
    apply_world_dossier_manifest,
    export_world_dossier_manifest,
    preview_world_dossier_manifest,
)
from modules.world.dossier_service import WorldObjectDossierService

_service = WorldObjectDossierService()


async def read_world_object_dossier(
    db,
    novel_id: str,
    entity_id: str,
    *,
    as_of_scene_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    visibility_filter: str | None = None,
    visible_contents: list[str] | None = None,
    visible_fields: dict[str, list[str]] | None = None,
    story_viewpoint: dict | None = None,
):
    return await _service.read(
        db,
        novel_id,
        entity_id,
        as_of_scene_id=as_of_scene_id,
        limit=limit,
        offset=offset,
        visibility_filter=visibility_filter,
        visible_contents=visible_contents,
        visible_fields=visible_fields,
        story_viewpoint=story_viewpoint,
    )


async def read_world_object_dossier_history(
    db,
    novel_id: str,
    entity_id: str,
    *,
    entry_group_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    return await _service.history(
        db,
        novel_id,
        entity_id,
        entry_group_id=entry_group_id,
        limit=limit,
        offset=offset,
    )


async def create_world_object_dossier_entry(
    db, novel_id, entity_id, data, *, source="author"
):
    return await _service.create_entry(db, novel_id, entity_id, data, source=source)


async def preview_world_object_dossier_entry_create(db, novel_id, entity_id, data):
    return await _service.preview_create_entry(db, novel_id, entity_id, data)


async def edit_world_object_dossier_entry(
    db, novel_id, entity_id, revision_id, data, *, source="author"
):
    return await _service.update_entry(
        db, novel_id, entity_id, revision_id, data, source=source
    )


async def preview_world_object_dossier_entry_edit(
    db, novel_id, entity_id, revision_id, data
):
    return await _service.preview_update_entry(db, novel_id, entity_id, revision_id, data)


async def restore_world_object_dossier_entry(
    db, novel_id, entity_id, entry_group_id, data, *, source="author"
):
    return await _service.restore_entry(
        db, novel_id, entity_id, entry_group_id, data, source=source
    )


async def preview_world_object_dossier_entry_restore(
    db, novel_id, entity_id, entry_group_id, data
):
    return await _service.preview_restore_entry(
        db, novel_id, entity_id, entry_group_id, data
    )


async def list_world_object_dossier_facets(db, novel_id, entity_type):
    return await _service.list_facets(db, novel_id, entity_type)


async def list_world_object_dossier_facets_for_entity(db, novel_id, entity_id):
    return await _service.list_facets_for_entity(db, novel_id, entity_id)


async def get_world_object_dossier_template(db, novel_id, profile_type):
    return await _service.get_template(db, novel_id, profile_type)


async def get_author_world_object_dossier_template(db, novel_id, profile_type):
    return await _service.get_template(
        db, novel_id, profile_type, include_author_fields=True
    )


async def require_custom_text_state_field(
    db, novel_id, entity_id, field_key, expected_version_number
):
    return await _service.require_custom_text_state_field(
        db, novel_id, entity_id, field_key, expected_version_number
    )


async def save_world_object_dossier_template(
    db, novel_id, profile_type, data, *, source="author"
):
    return await _service.upsert_template(db, novel_id, profile_type, data, source=source)


async def preview_world_object_dossier_template(db, novel_id, profile_type, data):
    return await _service.preview_template_upsert(db, novel_id, profile_type, data)


async def read_world_object_dossier_template_history(db, novel_id, profile_type):
    return await _service.template_history(db, novel_id, profile_type)


__all__ = [
    "create_world_object_dossier_entry",
    "get_author_world_object_dossier_template",
    "apply_world_dossier_manifest",
    "export_world_dossier_manifest",
    "preview_world_dossier_manifest",
    "edit_world_object_dossier_entry",
    "get_world_object_dossier_template",
    "list_world_object_dossier_facets",
    "list_world_object_dossier_facets_for_entity",
    "preview_world_object_dossier_entry_create",
    "preview_world_object_dossier_entry_edit",
    "preview_world_object_dossier_entry_restore",
    "preview_world_object_dossier_template",
    "require_custom_text_state_field",
    "read_world_object_dossier",
    "read_world_object_dossier_history",
    "read_world_object_dossier_template_history",
    "restore_world_object_dossier_entry",
    "save_world_object_dossier_template",
]
