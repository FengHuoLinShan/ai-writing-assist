"""Author-only JSON manifest export, preview and revision-safe import."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, ValidationError
from infrastructure.stable_hash import stable_hash
from modules.project.facade import (
    require_active_project,
    require_active_project_exclusive,
)
from modules.world.dossier_service import (
    CORE_FACINGS,
    WorldObjectDossierService,
    _borrowed_core_facing_parts,
    _stored_core_facing_key,
)
from modules.world.models import (
    EntityProfileTemplate,
    EntityProfileTemplateRevision,
    WorldObjectDossierEntry,
)
from modules.world.schemas.dossier import (
    DossierAnchor,
    DossierEntryCreate,
    DossierEntryUpdate,
    DossierEvidenceRef,
    DossierFacingRef,
    DossierValidity,
)
from modules.world.schemas.dossier_manifest import (
    DossierManifest,
    DossierManifestApplyRequest,
    DossierManifestApplyResponse,
    DossierManifestConflict,
    DossierManifestEntry,
    DossierManifestPreviewRequest,
    DossierManifestPreviewResponse,
    DossierManifestTemplate,
)
from shared.utils import parse_uuid


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _facing_key(facing: DossierFacingRef, default_entity_type: str) -> str:
    if facing.kind == "project":
        return f"project:{facing.term_id}"
    borrowed = _borrowed_core_facing_parts(str(facing.key))
    source_type, key = borrowed or (default_entity_type, str(facing.key))
    return f"core:{source_type}:{key}"


def _anchor_key(anchor: DossierAnchor) -> str:
    return f"{anchor.kind}:{anchor.id}"


def _target_group_id(
    target_entity_id: uuid.UUID,
    source_project_id: uuid.UUID,
    source_entity_id: uuid.UUID,
    source_group_id: uuid.UUID,
) -> uuid.UUID:
    source = (
        f"{target_entity_id}:{source_project_id}:{source_entity_id}:{source_group_id}"
    )
    return uuid.uuid5(uuid.NAMESPACE_URL, f"novelcraft:dossier-manifest:{source}")


def _row_payload_hash(row: WorldObjectDossierEntry) -> str:
    validity = None
    if row.start_anchor_id or row.end_anchor_id:
        validity = {
            "start": (
                {"kind": row.start_anchor_kind, "id": str(row.start_anchor_id)}
                if row.start_anchor_id
                else None
            ),
            "end": (
                {"kind": row.end_anchor_kind, "id": str(row.end_anchor_id)}
                if row.end_anchor_id
                else None
            ),
        }
    return stable_hash(
        {
            "facing_kind": row.facing_kind,
            "facing_key": row.facing_key,
            "vocabulary_term_id": str(row.vocabulary_term_id)
            if row.vocabulary_term_id
            else None,
            "content": row.content,
            "tags": row.tags_json or [],
            "evidence": row.source_refs_json or [],
            "quote_text": row.quote_text,
            "visibility": row.visibility,
            "story_field_key": row.story_field_key,
            "validity": validity,
        }
    )


@dataclass
class _PlannedEntry:
    source: DossierManifestEntry
    target_facing: DossierFacingRef
    target_facing_label: str
    target_facing_key: str
    target_group_id: uuid.UUID
    target_story_field_key: str | None
    target_validity: DossierValidity | None
    target_evidence: list[DossierEvidenceRef]
    action: str
    current: WorldObjectDossierEntry | None = None
    reason: str | None = None


class WorldDossierInterchangeService:
    async def export_manifest(
        self, db: AsyncSession, novel_id: str, entity_id: str
    ) -> DossierManifest:
        await require_active_project(db, novel_id)
        service = WorldObjectDossierService()
        entity = await service._entity(db, novel_id, entity_id, require_canonical=True)
        read = await service.read(db, novel_id, entity_id, limit=251, offset=0)
        if read.omitted_count:
            raise ValidationError("此对象档案超过单份 JSON 清单上限，请先分批整理")

        template_payload = None
        template = await db.scalar(
            select(EntityProfileTemplate).where(
                EntityProfileTemplate.novel_id == entity.novel_id,
                EntityProfileTemplate.profile_type == entity.entity_type,
                EntityProfileTemplate.status == "active",
            )
        )
        if template is not None:
            revision = await db.scalar(
                select(EntityProfileTemplateRevision).where(
                    EntityProfileTemplateRevision.novel_id == entity.novel_id,
                    EntityProfileTemplateRevision.template_id == template.id,
                    EntityProfileTemplateRevision.version_number
                    == template.version_number,
                )
            )
            if revision is None:
                raise ConflictError("模板当前修订缺失，无法导出档案清单")
            snapshot = revision.snapshot_json or {}
            template_payload = DossierManifestTemplate(
                profile_type=template.profile_type,
                source_template_id=template.id,
                source_revision_id=revision.id,
                source_version_number=revision.version_number,
                revision_digest=revision.revision_digest,
                fields=snapshot.get("fields", []),
                state_fields=snapshot.get("state_fields", []),
                borrowed_facings=snapshot.get("borrowed_facings", []),
            )

        entries = [
            DossierManifestEntry(
                source_entry_group_id=item.entry_group_id,
                source_revision_id=item.id,
                source_revision_number=item.revision_number,
                previous_revision_id=item.previous_revision_id,
                facing=item.facing,
                facing_label=item.facing_label,
                content=item.content,
                story_field_key=item.story_field_key,
                tags=item.tags,
                evidence=item.evidence,
                quote_text=item.quote_text,
                source=item.source,
                visibility=item.visibility,
                validity=item.validity,
            )
            for item in read.entries
            if item.status == "active"
        ]
        return DossierManifest(
            created_at=datetime.now(UTC),
            source_project_id=entity.novel_id,
            source_entity_id=entity.id,
            source_entity_type=entity.entity_type,
            source_entity_name=entity.name,
            template=template_payload,
            entries=entries,
        )

    async def preview(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        request: DossierManifestPreviewRequest,
        *,
        lock: bool = False,
    ) -> tuple[DossierManifestPreviewResponse, list[_PlannedEntry]]:
        entity = await WorldObjectDossierService()._entity(
            db, novel_id, entity_id, lock=lock, require_canonical=True
        )
        nid = entity.novel_id
        manifest = request.manifest
        if manifest.template is not None:
            if not request.template_mapping_confirmed:
                raise ValidationError("请明确确认将来源模板映射到目标对象的当前模板")
            if request.expected_template_version_number is None:
                raise ValidationError("模板映射需要携带目标模板版本")
            target_template_statement = select(EntityProfileTemplate).where(
                EntityProfileTemplate.novel_id == nid,
                EntityProfileTemplate.profile_type == entity.entity_type,
                EntityProfileTemplate.status == "active",
            )
            if lock:
                target_template_statement = target_template_statement.with_for_update()
            target_template = await db.scalar(target_template_statement)
            if (
                target_template is None
                or target_template.version_number
                != request.expected_template_version_number
            ):
                raise ConflictError(
                    "目标档案模板已变化或不存在，请重新读取后确认",
                    code="dossier_manifest_template_stale",
                )
        elif request.expected_template_version_number is not None:
            target_template_statement = select(EntityProfileTemplate).where(
                EntityProfileTemplate.novel_id == nid,
                EntityProfileTemplate.profile_type == entity.entity_type,
                EntityProfileTemplate.status == "active",
            )
            if lock:
                target_template_statement = target_template_statement.with_for_update()
            target_template = await db.scalar(target_template_statement)
            if (
                target_template is None
                or target_template.version_number
                != request.expected_template_version_number
            ):
                raise ConflictError(
                    "目标档案模板已变化，请重新读取后确认",
                    code="dossier_manifest_template_stale",
                )
        else:
            target_template = None

        source_faces = self._source_faces(manifest)
        mapping_by_key = {
            _facing_key(item.source, manifest.source_entity_type): item.target
            for item in request.facing_mappings
        }
        extra_mapping_keys = set(mapping_by_key) - source_faces
        if extra_mapping_keys:
            raise ValidationError("面向映射包含清单中不存在的来源面向")
        is_cross_project = manifest.source_project_id != nid
        for source_key in source_faces:
            if (
                source_key.startswith("project:")
                and is_cross_project
                and source_key not in mapping_by_key
            ):
                raise ValidationError("跨项目的档案面向必须逐项映射到本项目词条")

        anchor_mapping = {
            _anchor_key(item.source): item.target for item in request.anchor_mappings
        }
        source_anchor_keys = {
            _anchor_key(anchor)
            for item in manifest.entries
            if item.validity
            for anchor in (item.validity.start, item.validity.end)
            if anchor is not None
        }
        if set(anchor_mapping) - source_anchor_keys:
            raise ValidationError("锚点映射包含清单中不存在的来源锚点")
        if is_cross_project and source_anchor_keys - set(anchor_mapping):
            raise ValidationError("跨项目的章节或 Scene 生效区间必须显式映射到目标锚点")

        story_keys = {
            item.story_field_key for item in manifest.entries if item.story_field_key
        }
        if set(request.story_field_mappings) - story_keys:
            raise ValidationError("Story 字段映射包含清单中不存在的来源字段")
        if is_cross_project and story_keys - set(request.story_field_mappings):
            raise ValidationError("跨项目的 Story 状态字段必须显式映射")
        if story_keys and request.expected_template_version_number is None:
            raise ValidationError("导入绑定 Story 字段时需要确认目标模板版本")

        planned: list[_PlannedEntry] = []
        group_ids = [
            _target_group_id(
                entity.id,
                manifest.source_project_id,
                manifest.source_entity_id,
                item.source_entry_group_id,
            )
            for item in manifest.entries
        ]
        existing_statement = select(WorldObjectDossierEntry).where(
            WorldObjectDossierEntry.novel_id == nid,
            WorldObjectDossierEntry.entity_id == entity.id,
            WorldObjectDossierEntry.entry_group_id.in_(group_ids),
        )
        if lock:
            existing_statement = existing_statement.with_for_update()
        existing_rows = list(
            (
                await db.scalars(
                    existing_statement.order_by(
                        WorldObjectDossierEntry.entry_group_id,
                        WorldObjectDossierEntry.revision_number,
                    ).execution_options(populate_existing=lock)
                )
            ).all()
        )
        rows_by_group: dict[uuid.UUID, list[WorldObjectDossierEntry]] = {}
        for row in existing_rows:
            rows_by_group.setdefault(row.entry_group_id, []).append(row)

        service = WorldObjectDossierService()
        skipped_ids = set(request.skip_conflicts)
        found_conflicts: list[DossierManifestConflict] = []
        for index, source in enumerate(manifest.entries):
            target_facing = self._target_facing(
                source.facing,
                manifest.source_entity_type,
                entity.entity_type,
                manifest.source_project_id,
                nid,
                mapping_by_key,
            )
            stored_key, facing_label = await service._validate_facing(
                db, nid, entity.entity_type, target_facing
            )
            target_story_key = (
                request.story_field_mappings.get(
                    source.story_field_key, source.story_field_key
                )
                if source.story_field_key
                else None
            )
            await service._validate_story_field_key(db, entity, target_story_key)
            target_validity = self._target_validity(
                source.validity, is_cross_project, anchor_mapping
            )
            await service._validate_validity(db, nid, target_validity)
            target_evidence = source.evidence if not is_cross_project else []
            group_id = group_ids[index]
            group_rows = rows_by_group.get(group_id, [])
            latest = group_rows[-1] if group_rows else None
            metadata = (
                (latest.metadata_json or {}).get("dossier_manifest_import")
                if latest is not None
                else None
            )
            action = "create"
            reason = None
            if latest is not None:
                source_identity_matches = (
                    isinstance(metadata, dict)
                    and metadata.get("source_project_id")
                    == str(manifest.source_project_id)
                    and metadata.get("source_entity_id") == str(manifest.source_entity_id)
                    and metadata.get("source_entry_group_id")
                    == str(source.source_entry_group_id)
                )
                if not source_identity_matches:
                    reason = "target_group_collision"
                elif (
                    metadata.get("source_revision_id") == str(source.source_revision_id)
                    and latest.status == "cleared"
                ):
                    action = "already_imported"
                elif _row_payload_hash(latest) != metadata.get("imported_entry_hash"):
                    reason = "already_changed"
                elif (
                    latest.facing_kind != target_facing.kind
                    or latest.facing_key != stored_key
                    or latest.vocabulary_term_id != target_facing.term_id
                ):
                    reason = "target_facing_changed"
                elif metadata.get("source_revision_id") == str(source.source_revision_id):
                    action = "already_imported"
                elif latest.status == "active":
                    action = "update"
                else:
                    reason = "already_changed"
            if reason is not None:
                found_conflicts.append(
                    DossierManifestConflict(
                        source_revision_id=source.source_revision_id,
                        facing_label=source.facing_label,
                        reason=reason,
                    )
                )
                action = (
                    "skip" if source.source_revision_id in skipped_ids else "conflict"
                )
            elif source.source_revision_id in skipped_ids:
                raise ValidationError("只能跳过预览中存在冲突的档案条目")
            planned.append(
                _PlannedEntry(
                    source=source,
                    target_facing=target_facing,
                    target_facing_label=facing_label,
                    target_facing_key=stored_key,
                    target_group_id=group_id,
                    target_story_field_key=target_story_key,
                    target_validity=target_validity,
                    target_evidence=target_evidence,
                    action=action,
                    current=latest,
                    reason=reason,
                )
            )
        if skipped_ids - {item.source_revision_id for item in found_conflicts}:
            raise ValidationError("跳过列表包含未发生冲突的档案条目")

        target_fingerprint = [
            {
                "id": str(row.id),
                "entry_group_id": str(row.entry_group_id),
                "revision_number": row.revision_number,
                "status": row.status,
                "payload_hash": _row_payload_hash(row),
            }
            for row in existing_rows
        ]
        preview_hash = stable_hash(
            {
                "target_entity_id": str(entity.id),
                "target_entity_type": entity.entity_type,
                "target_template_version": (
                    target_template.version_number if target_template else None
                ),
                "target_rows": target_fingerprint,
                "manifest": manifest.model_dump(mode="json"),
                "facing_mappings": [
                    item.model_dump(mode="json") for item in request.facing_mappings
                ],
                "story_field_mappings": request.story_field_mappings,
                "anchor_mappings": [
                    item.model_dump(mode="json") for item in request.anchor_mappings
                ],
                "skip_conflicts": sorted(str(item) for item in skipped_ids),
            }
        )
        conflict_blockers = any(item.action == "conflict" for item in planned)
        warnings = []
        if is_cross_project and any(item.evidence for item in manifest.entries):
            warnings.append(
                "来源项目中的证据引用仅保存在导入来源记录里，不会被当作本项目证据。"
            )
        response = DossierManifestPreviewResponse(
            preview_hash=preview_hash,
            target_entity_name=entity.name,
            create_count=sum(item.action == "create" for item in planned),
            update_count=sum(item.action == "update" for item in planned),
            already_imported_count=sum(
                item.action == "already_imported" for item in planned
            ),
            skipped_count=sum(item.action == "skip" for item in planned),
            conflicts=found_conflicts,
            warnings=warnings,
            can_apply=not conflict_blockers,
        )
        return response, planned

    @staticmethod
    def _source_faces(manifest: DossierManifest) -> set[str]:
        faces: set[str] = set()
        for item in manifest.entries:
            faces.add(_facing_key(item.facing, manifest.source_entity_type))
        if manifest.template is not None:
            for item in manifest.template.fields:
                faces.add(_facing_key(item.facing, manifest.source_entity_type))
            for item in manifest.template.borrowed_facings:
                faces.add(_facing_key(item, manifest.source_entity_type))
        return faces

    @staticmethod
    def _target_facing(
        source: DossierFacingRef,
        source_entity_type: str,
        target_entity_type: str,
        source_project_id: uuid.UUID,
        target_project_id: uuid.UUID,
        mappings: dict[str, DossierFacingRef],
    ) -> DossierFacingRef:
        mapped = mappings.get(_facing_key(source, source_entity_type))
        if mapped is not None:
            return mapped
        if source.kind == "project":
            if source_project_id != target_project_id:
                raise ValidationError("跨项目的档案面向必须显式映射")
            return source
        borrowed = _borrowed_core_facing_parts(str(source.key))
        core_source_type, core_key = borrowed or (source_entity_type, str(source.key))
        if core_key not in CORE_FACINGS.get(core_source_type, {}):
            raise ValidationError("清单中的内核面向已失效，必须显式映射或停止导入")
        if borrowed is not None:
            return source
        return DossierFacingRef(
            kind="core",
            key=(
                source.key
                if core_source_type == target_entity_type
                else _stored_core_facing_key(core_source_type, core_key)
            ),
        )

    @staticmethod
    def _target_validity(
        validity: DossierValidity | None,
        cross_project: bool,
        mappings: dict[str, DossierAnchor],
    ) -> DossierValidity | None:
        if validity is None:
            return None

        def resolve(anchor: DossierAnchor | None) -> DossierAnchor | None:
            if anchor is None:
                return None
            if cross_project:
                target = mappings.get(_anchor_key(anchor))
                if target is None:
                    raise ValidationError("跨项目的档案生效锚点必须显式映射")
                return target
            return anchor

        return DossierValidity(start=resolve(validity.start), end=resolve(validity.end))

    async def apply(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        request: DossierManifestApplyRequest,
        *,
        expected_preview_hash: str,
    ) -> DossierManifestApplyResponse:
        await require_active_project_exclusive(db, novel_id)
        preview, planned = await self.preview(db, novel_id, entity_id, request, lock=True)
        if preview.preview_hash != expected_preview_hash:
            raise ConflictError(
                "档案清单预览已过期，请重新预览后确认",
                code="dossier_manifest_preview_stale",
            )
        if not preview.can_apply:
            raise ConflictError(
                "档案清单仍有未处理冲突，请显式跳过或重新映射",
                code="dossier_manifest_conflict",
            )
        is_cross_project = request.manifest.source_project_id != parse_uuid(
            novel_id, "novel_id"
        )
        service = WorldObjectDossierService()
        applied = updated = 0
        for item in planned:
            if item.action not in {"create", "update"}:
                continue
            source = item.source
            evidence = item.target_evidence
            metadata = {
                "dossier_manifest_import": {
                    "source_project_id": str(request.manifest.source_project_id),
                    "source_entity_id": str(request.manifest.source_entity_id),
                    "source_entry_group_id": str(source.source_entry_group_id),
                    "source_revision_id": str(source.source_revision_id),
                    "source_revision_number": source.source_revision_number,
                    "source_revision_source": source.source,
                    "source_evidence": (
                        [ref.model_dump(mode="json") for ref in source.evidence]
                        if is_cross_project
                        else []
                    ),
                    "imported_entry_hash": self._planned_hash(item),
                }
            }
            if item.action == "create":
                await service.create_entry(
                    db,
                    novel_id,
                    entity_id,
                    DossierEntryCreate(
                        facing=item.target_facing,
                        content=source.content,
                        tags=source.tags,
                        evidence=evidence,
                        quote_text=source.quote_text,
                        visibility=source.visibility,
                        validity=item.target_validity,
                        story_field_key=item.target_story_field_key,
                    ),
                    source="author",
                    source_metadata=metadata,
                    reason="dossier_manifest_import",
                    entry_group_id=item.target_group_id,
                )
                applied += 1
            else:
                assert item.current is not None
                await service.update_entry(
                    db,
                    novel_id,
                    entity_id,
                    str(item.current.id),
                    DossierEntryUpdate(
                        expected_revision_id=item.current.id,
                        content=source.content,
                        tags=source.tags,
                        evidence=evidence,
                        quote_text=source.quote_text,
                        visibility=source.visibility,
                        validity=item.target_validity,
                        story_field_key=item.target_story_field_key,
                    ),
                    source="author",
                    source_metadata=metadata,
                    reason="dossier_manifest_import_update",
                )
                updated += 1
        await db.flush()
        return DossierManifestApplyResponse(
            applied_count=applied,
            updated_count=updated,
            already_imported_count=preview.already_imported_count,
            skipped_count=preview.skipped_count,
            preview_hash=preview.preview_hash,
        )

    @staticmethod
    def _planned_hash(item: _PlannedEntry) -> str:
        return stable_hash(
            {
                "facing_kind": item.target_facing.kind,
                "facing_key": item.target_facing_key,
                "vocabulary_term_id": str(item.target_facing.term_id)
                if item.target_facing.term_id
                else None,
                "content": item.source.content,
                "tags": item.source.tags,
                "evidence": [ref.model_dump(mode="json") for ref in item.target_evidence],
                "quote_text": item.source.quote_text,
                "visibility": item.source.visibility,
                "story_field_key": item.target_story_field_key,
                "validity": (
                    item.target_validity.model_dump(mode="json")
                    if item.target_validity
                    else None
                ),
            }
        )


_service = WorldDossierInterchangeService()


async def export_world_dossier_manifest(db, novel_id: str, entity_id: str):
    return await _service.export_manifest(db, novel_id, entity_id)


async def preview_world_dossier_manifest(
    db, novel_id: str, entity_id: str, request: DossierManifestPreviewRequest
):
    preview, _planned = await _service.preview(db, novel_id, entity_id, request)
    return preview


async def apply_world_dossier_manifest(
    db,
    novel_id: str,
    entity_id: str,
    request: DossierManifestApplyRequest,
):
    return await _service.apply(
        db,
        novel_id,
        entity_id,
        request,
        expected_preview_hash=request.expected_preview_hash,
    )


__all__ = [
    "apply_world_dossier_manifest",
    "export_world_dossier_manifest",
    "preview_world_dossier_manifest",
]
