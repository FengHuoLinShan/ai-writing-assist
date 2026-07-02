"""Persistence gateway for Phase 2 scene entity extraction."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.context_snapshot_helpers import build_result_ref
from modules.imports.llm_schemas import (
    AliasRelationExtractionOutput,
    DeltaEvent,
    ExtractedEntity,
    ExtractedRelation,
)

logger = logging.getLogger(__name__)


def entity_key(entity_type: str, name: str) -> tuple[str, str]:
    return (entity_type.strip().lower(), " ".join(name.strip().lower().split()))


class SceneEntityPersistenceGateway:
    """Persists Phase 2 entities, aliases, relations, deltas, and map observations."""

    def __init__(self, service: Any) -> None:
        self.service = service

    async def persist_alias_relation_output(
        self,
        db: AsyncSession,
        novel_id: str,
        output: AliasRelationExtractionOutput,
        *,
        scene_index: int,
        workflow_id: str | None = None,
        scene_id: str | None = None,
        result_refs: list[dict[str, str]] | None = None,
    ) -> dict[str, int]:
        from modules.world.facade import (
            append_candidate_alias,
            create_relation,
            find_working_entity_id_by_name,
        )

        aliases_created = 0
        relations_created = 0
        for alias in output.aliases:
            entity_id = await find_working_entity_id_by_name(
                db,
                novel_id,
                alias.entity_name,
            )
            if not entity_id:
                continue
            added = await append_candidate_alias(
                db,
                novel_id,
                entity_id,
                alias=alias.alias,
                alias_type=alias.alias_type,
                workflow_id=workflow_id,
                scene_id=scene_id,
                scene_index=scene_index,
                confidence=alias.confidence,
                quote=alias.quote,
            )
            if added:
                aliases_created += 1
                if result_refs is not None:
                    result_refs.append(
                        {
                            "type": "entity_alias",
                            "id": f"{entity_id}:{alias.alias.strip()}",
                        }
                    )

        for rel in output.relations:
            source_id = await find_working_entity_id_by_name(
                db,
                novel_id,
                rel.source_name,
            )
            target_id = await find_working_entity_id_by_name(
                db,
                novel_id,
                rel.target_name,
            )
            if not source_id or not target_id:
                continue
            try:
                relation = await create_relation(
                    db,
                    novel_id,
                    {
                        "source_id": source_id,
                        "target_id": target_id,
                        "relation_type": rel.relation_type,
                        "description": rel.description,
                        "quote": rel.quote,
                        "strength": rel.strength,
                        "status": "candidate",
                    },
                )
            except Exception as exc:
                logger.warning(
                    "Failed to create phase2b relation %s -> %s: %s",
                    rel.source_name,
                    rel.target_name,
                    exc,
                )
                continue
            relations_created += 1
            relation_id = getattr(relation, "id", None)
            if result_refs is not None and relation_id:
                result_refs.append(build_result_ref("entity_relation", relation_id))

        return {"aliases": aliases_created, "relations": relations_created}

    async def persist_entities(
        self,
        db: AsyncSession,
        nid,
        entities: list[ExtractedEntity],
        scene_index: int,
        source_chapter_index: int,
        seen_entity_keys: set[tuple[str, str]] | None = None,
        workflow_id: str | None = None,
        scene_id: str | None = None,
        scene_provenance_key: str | None = None,
        context_snapshot_id: str | None = None,
        result_refs: list[dict[str, str]] | None = None,
        persistence_stats: dict[str, Any] | None = None,
    ) -> int:
        service = self.service
        from modules.world.facade import create_entity, find_similar_entities

        created = 0
        seen_entity_keys = seen_entity_keys if seen_entity_keys is not None else set()

        for ent in entities:
            action = ent.suggested_action
            if persistence_stats is not None:
                persistence_stats.setdefault("action_counts", {}).setdefault(action, 0)
                persistence_stats["action_counts"][action] += 1
                if ent.confidence < 0.6:
                    persistence_stats["low_confidence"] = (
                        int(persistence_stats.get("low_confidence", 0) or 0) + 1
                    )
                if action == "link_to_existing":
                    persistence_stats["linked_to_existing"] = (
                        int(persistence_stats.get("linked_to_existing", 0) or 0) + 1
                    )
                if action == "ignore":
                    persistence_stats["ignored"] = (
                        int(persistence_stats.get("ignored", 0) or 0) + 1
                    )
                if action == "temporary_only":
                    persistence_stats["temporary_only"] = (
                        int(persistence_stats.get("temporary_only", 0) or 0) + 1
                    )
            if action == "ignore":
                continue

            if not ent.name:
                continue

            entity_key = service._entity_key(ent.entity_type, ent.name)
            if entity_key in seen_entity_keys:
                continue

            if action == "create_new":
                try:
                    similar = await find_similar_entities(
                        db,
                        str(nid),
                        ent.name,
                        aliases=[
                            alias.get("alias", "")
                            for alias in (ent.aliases or [])
                            if isinstance(alias, dict)
                        ],
                        entity_type=ent.entity_type,
                    )
                    if persistence_stats is not None:
                        persistence_stats["dedup_counts"]["checked"] += 1
                except Exception:
                    similar = []
                    if persistence_stats is not None:
                        persistence_stats["dedup_counts"]["degraded"] += 1
                similar_items = similar if isinstance(similar, list) else [similar]
                high_confidence_duplicate = any(
                    (
                        item.get("similarity_score", item.get("score", 0))
                        if isinstance(item, dict)
                        else getattr(item, "similarity_score", 0)
                    )
                    >= 0.88
                    for item in similar_items
                    if item
                )
                if high_confidence_duplicate:
                    seen_entity_keys.add(entity_key)
                    if persistence_stats is not None:
                        persistence_stats["dedup_counts"]["skipped"] += 1
                    continue

            content_json: dict[str, Any] = {
                "_meta": {
                    "auto_ingested": True,
                    "source": "deep_import",
                    "workflow_id": workflow_id,
                    "scene_id": scene_id,
                    "scene_provenance_key": (
                        scene_provenance_key
                        or f"{workflow_id or 'manual'}:scene:{scene_index}"
                    ),
                    "source_scene_index": scene_index,
                    "source_chapter_index": source_chapter_index,
                    "ingested_at": datetime.now(UTC).isoformat(),
                    "batch_id": workflow_id or "",
                    "suggested_action": action,
                    "suggested_existing_entity_name": (
                        ent.suggested_existing_entity_name
                    ),
                    "candidate_reason": ent.candidate_reason,
                    "confidence": ent.confidence,
                },
                "aliases": ent.aliases or [],
            }
            if context_snapshot_id:
                content_json["_meta"]["context_snapshot_id"] = context_snapshot_id
            if action == "temporary_only":
                content_json["_meta"]["temporary"] = True
            entity_payload = {
                "name": ent.name,
                "entity_type": ent.entity_type,
                "summary": ent.summary or None,
                "public_info": ent.public_info or None,
                "hidden_truth": ent.hidden_truth or None,
                "importance": ent.importance,
                "content_json": content_json,
                "status": "candidate",
                "created_by": "ai_import",
            }
            try:
                async with db.begin_nested():
                    created_entity = await create_entity(db, str(nid), entity_payload)
                created += 1
                seen_entity_keys.add(entity_key)
                if result_refs is not None and created_entity.get("id"):
                    result_refs.append(
                        build_result_ref("core_entity", created_entity["id"])
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to create entity '%s': %s",
                    ent.name,
                    exc,
                )

        return created

    async def persist_relations(
        self,
        db: AsyncSession,
        nid,
        relations: list[ExtractedRelation],
        scene_index: int,
        workflow_id: str | None = None,
        context_snapshot_id: str | None = None,
        result_refs: list[dict[str, str]] | None = None,
    ) -> int:
        from modules.world.facade import create_relation, find_working_entity_id_by_name

        created = 0
        for rel in relations:
            source_id = await find_working_entity_id_by_name(
                db,
                str(nid),
                rel.source_name,
            )
            target_id = await find_working_entity_id_by_name(
                db,
                str(nid),
                rel.target_name,
            )
            if not source_id or not target_id:
                logger.debug(
                    "Skipping relation %s -> %s: entity not found",
                    rel.source_name,
                    rel.target_name,
                )
                continue
            try:
                relation = await create_relation(
                    db,
                    str(nid),
                    {
                        "source_id": source_id,
                        "target_id": target_id,
                        "relation_type": rel.relation_type,
                        "description": rel.description,
                        "quote": rel.quote,
                        "strength": rel.strength,
                        "status": "candidate",
                    },
                )
                created += 1
                relation_id = getattr(relation, "id", None)
                if result_refs is not None and relation_id:
                    result_refs.append(build_result_ref("entity_relation", relation_id))
            except Exception as exc:
                logger.warning(
                    "Failed to create relation %s -> %s: %s",
                    rel.source_name,
                    rel.target_name,
                    exc,
                )
        return created

    async def record_deltas(
        self,
        db: AsyncSession,
        nid,
        delta_events: list[DeltaEvent],
        scene_index: int,
        workflow_id: str | None = None,
        scene_id: str | None = None,
        scene_provenance_key: str | None = None,
        context_snapshot_id: str | None = None,
        result_refs: list[dict[str, str]] | None = None,
    ) -> int:
        from modules.memory.facade import create_delta_log
        from modules.world.facade import create_map_observation_from_delta_event

        count = 0
        for event in delta_events or []:
            event_meta = event.meta or {}
            provenance_meta = {
                "source": "deep_import",
                "workflow_id": workflow_id,
                "scene_id": scene_id,
                "scene_provenance_key": (
                    scene_provenance_key
                    or f"{workflow_id or 'manual'}:scene:{scene_index}"
                ),
                "auto_ingested": True,
            }
            source_ref = {
                "workflow_id": workflow_id,
                "scene_id": scene_id,
                "scene_provenance_key": provenance_meta["scene_provenance_key"],
                "auto_ingested": True,
            }
            merged_meta = {
                **event_meta,
                **provenance_meta,
                "source_ref": {
                    **(event_meta.get("source_ref") or {}),
                    **source_ref,
                },
            }
            delta = await create_delta_log(
                db,
                str(nid),
                scene_index=scene_index,
                category=event.category,
                field_path=event.field,
                old_value=json.dumps(event.old) if event.old is not None else None,
                new_value=json.dumps(event.new) if event.new is not None else None,
                source="deep_import",
                meta={
                    **merged_meta,
                    **(
                        {"context_snapshot_id": context_snapshot_id}
                        if context_snapshot_id
                        else {}
                    ),
                },
            )
            count += 1
            delta_log_id = delta.get("id")
            if result_refs is not None and delta.get("id"):
                result_refs.append(build_result_ref("delta_log", delta_log_id))
            try:
                event_payload = event.model_dump()
                observation_meta = {**merged_meta}
                observation_meta.pop("scene_id", None)
                event_payload["meta"] = observation_meta
                observation = await create_map_observation_from_delta_event(
                    db,
                    str(nid),
                    event=event_payload,
                    scene_index=scene_index,
                    context_snapshot_id=context_snapshot_id,
                    delta_log_id=delta_log_id,
                )
                if result_refs is not None:
                    result_refs.append(
                        build_result_ref("map_observation", observation["id"])
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to create map observation for delta event %s: %s",
                    event.category,
                    exc,
                )
        return count
