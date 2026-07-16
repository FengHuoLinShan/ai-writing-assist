"""Persistence gateway for Phase 2 scene entity extraction."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.context_snapshot_helpers import build_result_ref
from modules.imports.entity_extraction.scene_entity_runtime import (
    SceneEntityExtractionRuntime,
)
from modules.imports.llm_schemas import (
    AliasRelationExtractionOutput,
    DeltaEvent,
    ExtractedEntity,
    ExtractedMapObservationProposal,
    ExtractedRelation,
)

logger = logging.getLogger(__name__)

_EXTRACTION_ALIAS_PLACEHOLDERS = frozenset({"变量", "variable", "placeholder"})


def entity_key(entity_type: str, name: str) -> tuple[str, str]:
    return (entity_type.strip().lower(), " ".join(name.strip().lower().split()))


def _high_confidence_duplicate_id(similar_items: list[Any]) -> str | None:
    best_score = 0.0
    best_id: str | None = None
    for item in similar_items:
        if not item:
            continue
        if isinstance(item, dict):
            raw_score = item.get("similarity_score", item.get("score", 0))
            entity_id = item.get("existing_entity_id") or item.get("entity_id")
        else:
            raw_score = getattr(
                item,
                "similarity_score",
                getattr(item, "score", 0),
            )
            entity_id = getattr(
                item,
                "existing_entity_id",
                getattr(item, "entity_id", None),
            )
        try:
            score = float(raw_score or 0)
        except (TypeError, ValueError):
            score = 0.0
        if score >= 0.88 and score > best_score and entity_id:
            best_score = score
            best_id = str(entity_id)
    return best_id


def _is_extraction_alias_placeholder(alias: object) -> bool:
    normalized = " ".join(str(alias or "").strip().split()).casefold()
    return normalized in _EXTRACTION_ALIAS_PLACEHOLDERS


def normalize_candidate_alias_item(
    alias_item: Any,
    *,
    workflow_id: str | None,
    scene_id: str | None,
    scene_index: int,
    confidence: float,
) -> dict[str, Any] | None:
    if isinstance(alias_item, dict):
        raw_alias = alias_item.get("alias") or alias_item.get("name") or ""
        alias_type = alias_item.get("type") or alias_item.get("alias_type") or "alias"
    else:
        raw_alias = alias_item
        alias_type = "alias"
    alias_text = " ".join(str(raw_alias).strip().split())
    if not alias_text or _is_extraction_alias_placeholder(alias_text):
        return None
    return {
        "alias": alias_text,
        "type": alias_type,
        "status": "candidate",
        "source": "deep_import",
        "workflow_id": workflow_id,
        "scene_id": scene_id,
        "scene_index": scene_index,
        "confidence": confidence,
        "quote": alias_item.get("quote") if isinstance(alias_item, dict) else None,
        "needs_review": True,
    }


def _relation_review_meta(
    *,
    workflow_id: str | None,
    scene_id: str | None,
    scene_index: int,
    source_chapter_index: int | None,
    quote: str | None,
    context_snapshot_id: str | None = None,
) -> dict[str, Any]:
    evidence_ref = {
        key: value
        for key, value in {
            "source_type": "scene",
            "scene_id": scene_id,
            "scene_index": scene_index,
            "source_chapter_index": source_chapter_index,
            "quote": quote,
        }.items()
        if value is not None and value != ""
    }
    return {
        key: value
        for key, value in {
            "source": "deep_import",
            "workflow_id": workflow_id,
            "scene_id": scene_id,
            "scene_index": scene_index,
            "source_chapter_index": source_chapter_index,
            "context_snapshot_id": context_snapshot_id,
            "quote": quote,
            "evidence_refs": [evidence_ref],
        }.items()
        if value is not None and value != ""
    }


class SceneEntityPersistenceGateway:
    """Persists Phase 2 entities, aliases, relations, deltas, and map observations."""

    def __init__(self, service: SceneEntityExtractionRuntime) -> None:
        self.service = service

    async def _record_quote_evidence(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        target_ref: dict,
        quote: str | None,
        scene_id: str | None,
        workflow_id: str | None,
        evidence_type: str = "supports",
        visible_until_chapter: int | None = None,
    ) -> None:
        from modules.context.facade import (
            locate_scene_quote,
            record_evidence_link,
            record_unresolved_evidence_link,
        )

        provenance = {
            "source": "deep_import",
            "workflow_id": workflow_id,
            "scene_id": scene_id,
            "quote": quote,
        }
        source_ref = None
        reason = "missing_scene_id"
        if scene_id:
            source_ref, reason = await locate_scene_quote(
                db,
                novel_id=novel_id,
                scene_id=scene_id,
                quote=quote or "",
                content_mode="working",
                visible_until_chapter=visible_until_chapter,
            )
        if source_ref is not None:
            await record_evidence_link(
                db,
                novel_id=novel_id,
                target_ref=target_ref,
                source_ref=source_ref,
                claim_path=target_ref.get("target_path", ""),
                evidence_type=evidence_type,
                provenance=provenance,
            )
            return
        await record_unresolved_evidence_link(
            db,
            novel_id=novel_id,
            target_ref=target_ref,
            claim_path=target_ref.get("target_path", ""),
            evidence_type=evidence_type,
            provenance={**provenance, "review_reason": reason},
        )

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
        strict: bool = False,
    ) -> dict[str, int]:
        from modules.world.facade import (
            append_candidate_alias,
            create_or_merge_relation,
            find_working_entity_ids_by_names,
        )

        names_to_resolve = {alias.entity_name for alias in output.aliases}
        for rel in output.relations:
            names_to_resolve.add(rel.source_name)
            names_to_resolve.add(rel.target_name)
        entity_ids = await find_working_entity_ids_by_names(
            db,
            novel_id,
            names_to_resolve,
        )

        aliases_created = 0
        relations_created = 0
        for alias in output.aliases:
            if _is_extraction_alias_placeholder(alias.alias):
                continue
            entity_id = entity_ids.get(alias.entity_name)
            if not entity_id:
                continue
            async with db.begin_nested():
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
                    await self._record_quote_evidence(
                        db,
                        novel_id=novel_id,
                        target_ref={
                            "target_type": "core_entity",
                            "target_id": entity_id,
                            "target_path": "aliases",
                        },
                        quote=alias.quote,
                        scene_id=scene_id,
                        workflow_id=workflow_id,
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
            source_id = entity_ids.get(rel.source_name)
            target_id = entity_ids.get(rel.target_name)
            if not source_id or not target_id:
                continue
            try:
                async with db.begin_nested():
                    relation_result = await create_or_merge_relation(
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
                            "review_meta": _relation_review_meta(
                                workflow_id=workflow_id,
                                scene_id=scene_id,
                                scene_index=scene_index,
                                source_chapter_index=None,
                                quote=rel.quote,
                            ),
                        },
                    )
                    relation = relation_result.get("relation")
                    relation_id = getattr(relation, "id", None)
                    if relation_id and relation_result.get("action") != "deduplicated":
                        await self._record_quote_evidence(
                            db,
                            novel_id=novel_id,
                            target_ref={
                                "target_type": "entity_relation",
                                "target_id": str(relation_id),
                                "target_path": "description",
                            },
                            quote=rel.quote,
                            scene_id=scene_id,
                            workflow_id=workflow_id,
                        )
            except Exception as exc:
                logger.warning(
                    "Failed to create phase2b relation %s -> %s: %s",
                    rel.source_name,
                    rel.target_name,
                    exc,
                )
                if strict:
                    raise
                continue
            if relation_result.get("action") == "created":
                relations_created += 1
            if (
                result_refs is not None
                and relation_id
                and relation_result.get("action") != "deduplicated"
            ):
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
        from modules.world.facade import (
            create_entity,
            find_entity_id_by_name,
            find_similar_entities,
        )

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

            high_confidence_target_id: str | None = None
            resolved_existing_entity_id: str | None = None
            if action == "link_to_existing" and ent.suggested_existing_entity_name:
                resolved_existing_entity_id = await find_entity_id_by_name(
                    db,
                    str(nid),
                    ent.suggested_existing_entity_name,
                    entity_type=ent.entity_type,
                )
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
                            and not _is_extraction_alias_placeholder(
                                alias.get("alias", "")
                            )
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
                high_confidence_target_id = _high_confidence_duplicate_id(
                    similar_items,
                )

            normalized_aliases = [
                normalized
                for alias in (ent.aliases or [])
                if (
                    normalized := normalize_candidate_alias_item(
                        alias,
                        workflow_id=workflow_id,
                        scene_id=scene_id,
                        scene_index=scene_index,
                        confidence=ent.confidence,
                    )
                )
            ]

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
                    "suggested_existing_entity_id": resolved_existing_entity_id,
                    "candidate_reason": ent.candidate_reason,
                    "confidence": ent.confidence,
                    "suggested_target_entity_id": high_confidence_target_id,
                },
                "aliases": normalized_aliases,
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
                    evidence_target_id = created_entity.get("id")
                    if evidence_target_id:
                        await self._record_quote_evidence(
                            db,
                            novel_id=str(nid),
                            target_ref={
                                "target_type": "core_entity",
                                "target_id": str(evidence_target_id),
                                "target_path": "summary",
                            },
                            quote=ent.quote,
                            scene_id=scene_id,
                            workflow_id=workflow_id,
                            visible_until_chapter=source_chapter_index,
                        )
                created += 1
                seen_entity_keys.add(entity_key)
                if persistence_stats is not None:
                    if action == "create_new" and high_confidence_target_id:
                        persistence_stats["dedup_counts"]["review_suggested"] += 1
                    elif action == "create_new":
                        persistence_stats["dedup_counts"]["candidate_created"] += 1
                    elif action == "link_to_existing":
                        persistence_stats["dedup_counts"]["review_suggested"] += 1
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
        source_chapter_index: int | None = None,
        workflow_id: str | None = None,
        scene_id: str | None = None,
        context_snapshot_id: str | None = None,
        result_refs: list[dict[str, str]] | None = None,
        persistence_stats: dict[str, Any] | None = None,
    ) -> int:
        from modules.world.facade import (
            create_or_merge_relation,
            find_working_entity_ids_by_names,
        )

        created = 0
        names_to_resolve = set()
        for rel in relations:
            names_to_resolve.add(rel.source_name)
            names_to_resolve.add(rel.target_name)
        entity_ids = await find_working_entity_ids_by_names(
            db,
            str(nid),
            names_to_resolve,
        )
        for rel in relations:
            source_id = entity_ids.get(rel.source_name)
            target_id = entity_ids.get(rel.target_name)
            if not source_id or not target_id:
                logger.debug(
                    "Skipping relation %s -> %s: entity not found",
                    rel.source_name,
                    rel.target_name,
                )
                continue
            try:
                async with db.begin_nested():
                    relation_result = await create_or_merge_relation(
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
                            "review_meta": _relation_review_meta(
                                workflow_id=workflow_id,
                                scene_id=scene_id,
                                scene_index=scene_index,
                                source_chapter_index=source_chapter_index,
                                quote=rel.quote,
                                context_snapshot_id=context_snapshot_id,
                            ),
                        },
                    )
                    relation = relation_result.get("relation")
                    relation_id = getattr(relation, "id", None)
                    if relation_id and relation_result.get("action") != "deduplicated":
                        await self._record_quote_evidence(
                            db,
                            novel_id=str(nid),
                            target_ref={
                                "target_type": "entity_relation",
                                "target_id": str(relation_id),
                                "target_path": "description",
                            },
                            quote=rel.quote,
                            scene_id=scene_id,
                            workflow_id=workflow_id,
                            visible_until_chapter=source_chapter_index,
                        )
                if relation_result.get("action") == "created":
                    created += 1
                elif (
                    relation_result.get("action") == "deduplicated"
                    and persistence_stats is not None
                ):
                    persistence_stats["dedup_counts"]["relation_duplicate_skipped"] += 1
                elif persistence_stats is not None:
                    persistence_stats["dedup_counts"]["relation_merged"] += 1
                if (
                    result_refs is not None
                    and relation_id
                    and relation_result.get("action") != "deduplicated"
                ):
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
        from modules.memory.contracts import MemoryDeltaEventIngest
        from modules.memory.facade import ingest_delta_events
        from modules.world.facade import create_map_observation_from_delta_event

        ingest_events: list[MemoryDeltaEventIngest] = []
        map_payloads: list[dict] = []
        for event in delta_events or []:
            event_meta = event.meta or {}
            scene_key = (
                scene_provenance_key or f"{workflow_id or 'manual'}:scene:{scene_index}"
            )
            ingest_events.append(
                MemoryDeltaEventIngest(
                    scene_index=scene_index,
                    category=event.category,
                    field_path=event.field,
                    old_value=event.old,
                    new_value=event.new,
                    source="deep_import",
                    meta=event_meta,
                    workflow_id=workflow_id,
                    scene_id=scene_id,
                    scene_provenance_key=scene_key,
                    context_snapshot_id=context_snapshot_id,
                )
            )
            source_ref = {
                "workflow_id": workflow_id,
                "scene_id": scene_id,
                "scene_provenance_key": scene_key,
                "auto_ingested": True,
            }
            observation_meta = {
                **event_meta,
                "source": "deep_import",
                "workflow_id": workflow_id,
                "scene_provenance_key": scene_key,
                "auto_ingested": True,
                "source_ref": {
                    **(event_meta.get("source_ref") or {}),
                    **source_ref,
                },
            }
            map_payload = event.model_dump()
            observation_meta.pop("scene_id", None)
            map_payload["meta"] = observation_meta
            map_payloads.append(map_payload)

        result = await ingest_delta_events(
            db,
            str(nid),
            ingest_events,
            result_refs=result_refs,
        )
        for event_payload, delta in zip(map_payloads, result.delta_logs):
            delta_log_id = delta.get("id")
            try:
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
                    event_payload.get("category"),
                    exc,
                )
        return result.count

    async def record_map_observation_proposals(
        self,
        db: AsyncSession,
        nid,
        proposals: list[ExtractedMapObservationProposal],
        *,
        scene_index: int,
        source_chapter_index: int | None,
        workflow_id: str | None,
        scene_id: str | None,
        scene_source_fingerprint: str | None,
        authorization_snapshot: dict[str, Any] | None,
        context_snapshot_id: str | None = None,
        result_refs: list[dict[str, str]] | None = None,
    ) -> dict[str, int]:
        if not isinstance(proposals, list) or not proposals:
            return {"created": 0, "reused": 0}
        if not workflow_id or not scene_id or source_chapter_index is None:
            raise ValueError(
                "typed map proposals require workflow_id, scene_id, and source chapter"
            )
        if not scene_source_fingerprint:
            raise ValueError(
                "typed map proposals require a frozen Scene source fingerprint"
            )
        if not isinstance(authorization_snapshot, dict) or not authorization_snapshot:
            raise ValueError("typed map proposals require an authorization snapshot")

        from modules.imports.map_observation_candidates import (
            build_map_observation_candidates,
        )
        from modules.world.facade import create_map_observation_candidates

        candidates = build_map_observation_candidates(
            proposals,
            novel_id=str(nid),
            workflow_id=workflow_id,
            scene_id=scene_id,
            scene_index=scene_index,
            source_chapter_index=source_chapter_index,
            scene_source_fingerprint=scene_source_fingerprint,
            context_snapshot_id=context_snapshot_id,
            task_id=workflow_id,
            authorization_snapshot=authorization_snapshot,
        )
        result = await create_map_observation_candidates(
            db,
            str(nid),
            candidates=candidates,
        )
        if result_refs is not None:
            result_refs.extend(
                build_result_ref("map_observation", item.observation_id)
                for item in result.items
            )
        return {"created": result.created_count, "reused": result.reused_count}
