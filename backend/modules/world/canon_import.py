"""Append-only demo-copy canon import with identity-space manifest rewrite.

Canon admission history is author provenance and is never copied.  A demo
copy instead appends one ``demo_import`` revision onto the fresh bootstrap
canon, carrying the source head manifest with every resource reference
rewritten into the destination identity space (new ids, recomputed digests).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DomainError
from modules.world.authority import (
    CanonManifestV1,
    ExactResourceRevisionRef,
    ResourceRef,
    canonical_digest,
    empty_canon_manifest,
    resource_revision_digest,
)
from modules.world.models import WorldCanonHead, WorldCanonRevision
from shared.utils import parse_uuid


@dataclass(frozen=True, slots=True)
class DemoImportSource:
    head_revision_id: uuid.UUID
    manifest_digest: str
    manifest: CanonManifestV1


@dataclass(frozen=True, slots=True)
class CanonImportResourceMaps:
    """Destination identity maps built by the demo-copy asset pass."""

    novel_id: uuid.UUID
    page_ids: dict[uuid.UUID, uuid.UUID]
    page_revisions: dict[uuid.UUID, tuple[uuid.UUID, str]]
    template_ids: dict[uuid.UUID, uuid.UUID]
    template_revisions: dict[uuid.UUID, tuple[uuid.UUID, str]]


def revision_import_digest(
    kind: str,
    *,
    novel_id: uuid.UUID,
    resource_id: uuid.UUID,
    revision_id: uuid.UUID,
    snapshot: dict,
) -> str:
    """Recompute a resource revision digest under the destination identity."""
    return resource_revision_digest(
        ResourceRef(kind=kind, novel_id=novel_id, resource_id=resource_id),
        revision_id,
        snapshot,
    )


async def load_demo_import_source(
    db: AsyncSession,
    source_novel_id: str | uuid.UUID,
) -> DemoImportSource | None:
    """Load the source head manifest, or None when the source has no canon."""
    nid = parse_uuid(str(source_novel_id), "novel_id")
    head = await db.get(WorldCanonHead, nid)
    if head is None:
        return None
    revision = await db.get(WorldCanonRevision, head.current_revision_id)
    if revision is None:
        raise DomainError(
            "Demo source canon head is invalid",
            code="demo_import_source_invalid",
            status_code=500,
        )
    try:
        manifest = CanonManifestV1.model_validate(revision.manifest_json)
    except (TypeError, ValueError) as exc:
        raise DomainError(
            "Demo source canon manifest is invalid",
            code="demo_import_source_invalid",
            status_code=500,
        ) from exc
    return DemoImportSource(
        head_revision_id=revision.id,
        manifest_digest=revision.manifest_digest,
        manifest=manifest,
    )


def rewrite_demo_import_manifest(
    manifest: CanonManifestV1,
    maps: CanonImportResourceMaps,
) -> CanonManifestV1 | None:
    """Rewrite the source manifest into the destination identity space.

    Returns None for an empty source manifest: nothing needs importing and
    the destination keeps its plain bootstrap canon.
    """
    if manifest == empty_canon_manifest():
        return None
    if manifest.selected_assertions:
        raise DomainError(
            "演示项目包含暂不支持转移的断言历史",
            code="demo_assertion_transfer_unsupported",
            status_code=409,
        )
    rewritten = manifest.model_copy(
        update={
            "active_resources": [
                _rewrite_resource_ref(ref, maps) for ref in manifest.active_resources
            ],
            "validation_policy_ref": (
                _rewrite_resource_ref(manifest.validation_policy_ref, maps)
                if manifest.validation_policy_ref is not None
                else None
            ),
            "pinned_dependencies": [
                dependency.model_copy(
                    update={"revision": _rewrite_resource_ref(dependency.revision, maps)}
                )
                for dependency in manifest.pinned_dependencies
            ],
        }
    )
    return rewritten


def import_manifest_digest(manifest: CanonManifestV1) -> str:
    return canonical_digest(manifest)


def _rewrite_resource_ref(
    ref: ExactResourceRevisionRef,
    maps: CanonImportResourceMaps,
) -> ExactResourceRevisionRef:
    parent_ids, revision_map = _maps_for_kind(maps, ref.resource.kind)
    resource_id = parent_ids.get(ref.resource.resource_id)
    revision = revision_map.get(ref.revision_id)
    if resource_id is None or revision is None:
        raise DomainError(
            "Demo import manifest references an asset outside the copied set",
            code="demo_import_reference_unmapped",
            status_code=500,
        )
    new_revision_id, new_digest = revision
    return ref.model_copy(
        update={
            "resource": ref.resource.model_copy(
                update={"novel_id": maps.novel_id, "resource_id": resource_id}
            ),
            "revision_id": new_revision_id,
            "revision_digest": new_digest,
        }
    )


def _maps_for_kind(
    maps: CanonImportResourceMaps,
    kind: str,
) -> tuple[dict[uuid.UUID, uuid.UUID], dict[uuid.UUID, tuple[uuid.UUID, str]]]:
    if kind == "world_bible_page":
        return maps.page_ids, maps.page_revisions
    if kind == "entity_profile_template":
        return maps.template_ids, maps.template_revisions
    raise DomainError(
        "Demo import manifest references an unknown resource kind",
        code="demo_import_reference_unmapped",
        status_code=500,
    )
