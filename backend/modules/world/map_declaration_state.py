"""Author-confirmed Story state bound to an adopted map declaration."""

from __future__ import annotations

import json
import uuid
from typing import Literal

from sqlalchemy import select

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.map_structure_schemas import MapDocument
from modules.world.map_structure_service import canonical_map_feature_ids
from shared.utils import parse_uuid

MapDeclarationKind = Literal["feature", "constraint", "journey"]
MAP_DECLARATION_FIELD_KEY = "effective_status"


def map_declaration_subject_id(
    novel_id: str,
    node_id: str,
    declaration_kind: MapDeclarationKind,
    declaration_id: str,
) -> str:
    """Return an isolated Story projection key for one stable map declaration.

    The UUID is only a Story storage key. It does not represent a World
    CoreEntity. Canonical JSON makes the UUIDv5 name unambiguous even when
    declaration IDs contain separators.
    """
    novel_uuid = parse_uuid(novel_id, "novel_id")
    node_uuid = parse_uuid(node_id, "node_id")
    if declaration_kind not in {"feature", "constraint", "journey"}:
        raise ValidationError("Unsupported map declaration kind")
    if not isinstance(declaration_id, str) or not declaration_id:
        raise ValidationError("Map declaration ID is required")
    identity = json.dumps(
        {
            "contract": "world.map-declaration-state.v1",
            "declaration_id": declaration_id,
            "declaration_kind": declaration_kind,
            "node_id": str(node_uuid),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return str(uuid.uuid5(novel_uuid, identity))


async def require_map_declaration_state(
    db,
    novel_id: str,
    *,
    node_id: str,
    revision_id: str,
    declaration_kind: MapDeclarationKind,
    declaration_id: str,
) -> dict[str, str]:
    """Revalidate and bind an author-confirmed Story state write to current World.

    The caller verifies the active Scene and author confirmation. This port
    locks the project-owned map node while the same transaction appends the
    Story event, so a concurrent save cannot replace the checked revision.
    """
    novel_uuid = parse_uuid(novel_id, "novel_id")
    node_uuid = parse_uuid(node_id, "node_id")
    requested_revision = parse_uuid(revision_id, "revision_id")
    node = await db.scalar(
        select(MapAtlasNode)
        .where(
            MapAtlasNode.novel_id == novel_uuid,
            MapAtlasNode.id == node_uuid,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if node is None or node.status != "adopted" or node.merged_into_node_id is not None:
        raise NotFoundError("Adopted map declaration not found")
    if node.current_revision_id is None:
        raise NotFoundError("Map has no saved revision")
    if node.current_revision_id != requested_revision:
        raise ConflictError("Map changed; reload its current revision before confirming")
    revision = await db.scalar(
        select(MapAtlasRevision).where(
            MapAtlasRevision.novel_id == novel_uuid,
            MapAtlasRevision.node_id == node_uuid,
            MapAtlasRevision.id == requested_revision,
            MapAtlasRevision.status == "saved",
        )
    )
    if revision is None:
        raise NotFoundError("Saved map revision not found")
    document = MapDocument.model_validate(revision.document)
    declarations = {
        "feature": document.features,
        "constraint": document.constraints,
        "journey": document.journeys,
    }.get(declaration_kind)
    if declarations is None:
        raise ValidationError("Unsupported map declaration kind")
    declaration = next((item for item in declarations if item.id == declaration_id), None)
    if declaration is None or declaration.effective is None:
        raise ConflictError("The map declaration or its author interval has changed")
    if declaration.modality != "event_observed":
        raise ValidationError(
            "Only adopted event-observed map declarations accept Story state"
        )

    canonical_features = await canonical_map_feature_ids(db, novel_id, document)
    if declaration_kind == "feature":
        supported = declaration_id in canonical_features
    elif declaration_kind == "constraint":
        supported = {
            declaration.subject,
            declaration.target,
            *declaration.via,
        }.issubset(canonical_features)
    else:
        supported = {declaration.origin, declaration.destination}.issubset(
            canonical_features
        )
    if not supported:
        raise ConflictError("The map declaration no longer has canonical endpoints")

    return {
        "novel_id": str(novel_uuid),
        "node_id": str(node_uuid),
        "revision_id": str(requested_revision),
        "declaration_kind": declaration_kind,
        "declaration_id": declaration_id,
        "field_key": MAP_DECLARATION_FIELD_KEY,
        "subject_id": map_declaration_subject_id(
            str(novel_uuid), str(node_uuid), declaration_kind, declaration_id
        ),
        "label": "地图结构状态",
    }


__all__ = [
    "MAP_DECLARATION_FIELD_KEY",
    "MapDeclarationKind",
    "map_declaration_subject_id",
    "require_map_declaration_state",
]
