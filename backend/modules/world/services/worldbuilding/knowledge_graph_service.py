"""Read-only, deterministic World Bible association graph."""

from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from modules.world.models import CoreEntity, EntityRelation, WorldBiblePage
from modules.world.schemas import (
    WorldKnowledgeGraphEdge,
    WorldKnowledgeGraphNode,
    WorldKnowledgeGraphResponse,
)
from shared.target_ref import TargetRef


class WorldKnowledgeGraphService:
    _PAGE_SCAN_LIMIT = 2000
    _LOCAL_NODE_CAP, _LOCAL_EDGE_CAP = 120, 240
    _GLOBAL_NODE_CAP, _GLOBAL_EDGE_CAP = 500, 1500

    async def get(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        scope: str,
        root_type: str | None,
        root_id: str | None,
        depth: int,
    ) -> WorldKnowledgeGraphResponse:
        if scope not in {"local", "global"} or depth not in {1, 2}:
            raise ValidationError("knowledge graph scope/depth is invalid")
        if scope == "local" and (
            root_type not in {"world_bible_page", "core_entity"} or not root_id
        ):
            raise ValidationError("local knowledge graph requires a page or entity root")
        nid = uuid.UUID(novel_id)
        page_rows = list(
            (
                await db.execute(
                    select(WorldBiblePage)
                    .where(
                        WorldBiblePage.novel_id == nid,
                        WorldBiblePage.status.in_({"canonical", "confirmed"}),
                    )
                    .order_by(WorldBiblePage.id)
                    .limit(self._PAGE_SCAN_LIMIT + 1)
                )
            ).scalars()
        )
        page_scan_overflow = max(0, len(page_rows) - self._PAGE_SCAN_LIMIT)
        pages = page_rows[: self._PAGE_SCAN_LIMIT]
        if scope == "local" and root_type == "world_bible_page" and root_id:
            root_page = next(
                (page for page in page_rows if str(page.id) == root_id),
                None,
            )
            if root_page is None:
                try:
                    root_uuid = uuid.UUID(root_id)
                except ValueError as exc:
                    raise NotFoundError("Knowledge graph root was not found") from exc
                root_page = await db.scalar(
                    select(WorldBiblePage).where(
                        WorldBiblePage.id == root_uuid,
                        WorldBiblePage.novel_id == nid,
                        WorldBiblePage.status.in_({"canonical", "confirmed"}),
                    )
                )
            if root_page is None:
                raise NotFoundError("Knowledge graph root was not found")
            if all(page.id != root_page.id for page in pages):
                pages.append(root_page)
        entities = list(
            (
                await db.execute(
                    select(CoreEntity)
                    .where(CoreEntity.novel_id == nid, CoreEntity.status == "canonical")
                    .order_by(CoreEntity.id)
                )
            ).scalars()
        )
        relations = list(
            (
                await db.execute(
                    select(EntityRelation)
                    .where(
                        EntityRelation.novel_id == nid,
                        EntityRelation.status == "canonical",
                    )
                    .order_by(EntityRelation.id)
                )
            ).scalars()
        )
        page_ids = {str(page.id) for page in pages}
        entity_ids = {str(entity.id) for entity in entities}
        relation_map = {str(relation.id): relation for relation in relations}
        edges, omissions = [], 0
        for page in pages:
            for ref in page.linked_asset_refs_json or []:
                try:
                    target = TargetRef.model_validate(
                        {
                            "target_type": ref.get("target_type") or ref.get("type"),
                            "target_id": ref.get("target_id") or ref.get("id"),
                            "target_path": ref.get("target_path") or "",
                        }
                    )
                except Exception:
                    omissions += 1
                    continue
                page_ref = TargetRef(
                    target_type="world_bible_page", target_id=str(page.id)
                )
                page_hash = self._hash(
                    {
                        "id": str(page.id),
                        "version": page.version_number,
                        "refs": page.linked_asset_refs_json,
                    }
                )
                if (
                    target.target_type in {"world_bible_page", "page"}
                    and target.target_id in page_ids
                ):
                    kind = "page_reference"
                elif (
                    target.target_type in {"core_entity", "entity"}
                    and target.target_id in entity_ids
                ):
                    kind = "page_entity_reference"
                elif (
                    target.target_type in {"entity_relation", "relation"}
                    and target.target_id in relation_map
                ):
                    relation = relation_map[target.target_id]
                    for endpoint in (relation.source_id, relation.target_id):
                        edges.append(
                            WorldKnowledgeGraphEdge(
                                id=f"page:{page.id}:{target.target_hash()}:{endpoint}",
                                kind="page_entity_reference",
                                source_id=str(page.id),
                                target_id=str(endpoint),
                                status=page.status,
                                authority=page.status,
                                source_ref=page_ref.canonical_dict(),
                                revision=page.version_number,
                                source_hash=page_hash,
                                via_relation_id=str(relation.id),
                            )
                        )
                    continue
                else:
                    omissions += 1
                    continue
                edges.append(
                    WorldKnowledgeGraphEdge(
                        id=f"page:{page.id}:{target.target_hash()}",
                        kind=kind,
                        source_id=str(page.id),
                        target_id=target.target_id,
                        status=page.status,
                        authority=page.status,
                        source_ref=page_ref.canonical_dict(),
                        revision=page.version_number,
                        source_hash=page_hash,
                    )
                )
        for relation in relations:
            provenance = self._provenance(relation.review_meta)
            edges.append(
                WorldKnowledgeGraphEdge(
                    id=str(relation.id),
                    kind="entity_relation",
                    source_id=str(relation.source_id),
                    target_id=str(relation.target_id),
                    status=relation.status,
                    provenance=provenance,
                    authority="canonical",
                    source_ref=TargetRef(
                        target_type="entity_relation", target_id=str(relation.id)
                    ).canonical_dict(),
                    source_hash=self._hash(
                        {
                            "id": str(relation.id),
                            "source": str(relation.source_id),
                            "target": str(relation.target_id),
                            "type": relation.relation_type,
                            "description": relation.description,
                            "status": relation.status,
                            "provenance": provenance,
                        }
                    ),
                )
            )
        node_map = {
            str(p.id): WorldKnowledgeGraphNode(
                id=str(p.id), kind="world_bible_page", label=p.title, status=p.status
            )
            for p in pages
        }
        node_map.update(
            {
                str(e.id): WorldKnowledgeGraphNode(
                    id=str(e.id), kind="core_entity", label=e.name, status=e.status
                )
                for e in entities
            }
        )
        if scope == "local":
            assert root_id
            if root_id not in node_map or node_map[root_id].kind != root_type:
                raise NotFoundError("Knowledge graph root was not found")
            keep = {root_id}
            for _ in range(depth):
                keep |= {edge.target_id for edge in edges if edge.source_id in keep} | {
                    edge.source_id for edge in edges if edge.target_id in keep
                }
            edges = [
                edge
                for edge in edges
                if edge.source_id in keep and edge.target_id in keep
            ]
            node_map = {key: value for key, value in node_map.items() if key in keep}
            cap_nodes, cap_edges = self._LOCAL_NODE_CAP, self._LOCAL_EDGE_CAP
        else:
            cap_nodes, cap_edges = self._GLOBAL_NODE_CAP, self._GLOBAL_EDGE_CAP
        ordered_nodes = sorted(
            node_map.values(), key=lambda node: (node.kind, node.label, node.id)
        )[:cap_nodes]
        kept = {node.id for node in ordered_nodes}
        ordered_edges = sorted(
            (edge for edge in edges if edge.source_id in kept and edge.target_id in kept),
            key=lambda edge: (edge.kind, edge.source_id, edge.target_id, edge.id),
        )[:cap_edges]
        page_map = {str(page.id): page for page in pages}
        entity_map = {str(entity.id): entity for entity in entities}
        manifest = [
            {
                "kind": node.kind,
                "id": node.id,
                "status": node.status,
                "source_hash": self._hash(
                    {
                        "label": node.label,
                        "status": node.status,
                        "updated_at": getattr(
                            page_map.get(node.id) or entity_map.get(node.id),
                            "updated_at",
                            None,
                        ),
                        "version_number": getattr(
                            page_map.get(node.id), "version_number", None
                        ),
                        "entity_type": getattr(
                            entity_map.get(node.id), "entity_type", None
                        ),
                    }
                ),
            }
            for node in ordered_nodes
        ] + [
            {"kind": edge.kind, "id": edge.id, "source_hash": edge.source_hash or ""}
            for edge in ordered_edges
        ]
        source_hash = hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode()
        ).hexdigest()
        reasons = []
        if page_scan_overflow:
            reasons.append("page_scan_partial")
        if len(node_map) > cap_nodes or len(edges) > cap_edges:
            reasons.append("result_cap")
        return WorldKnowledgeGraphResponse(
            nodes=ordered_nodes,
            edges=ordered_edges,
            truncated=bool(reasons),
            truncation_reasons=reasons,
            omitted_counts={
                "bad_or_unavailable_ref": omissions,
                "page_scan_overflow": page_scan_overflow,
            },
            source_manifest=manifest,
            source_hash=source_hash,
        )

    @staticmethod
    def _hash(value: object) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def _provenance(value: dict | None) -> dict | None:
        raw = value or {}
        adopted = raw.get("world_adoption")
        if isinstance(adopted, dict):
            return {
                key: adopted[key]
                for key in (
                    "package_id",
                    "item_key",
                    "authority_kind",
                    "source_manifest_hash",
                )
                if key in adopted
            }
        return {
            key: raw[key]
            for key in ("source", "workflow_id", "scene_index")
            if key in raw
        } or None
