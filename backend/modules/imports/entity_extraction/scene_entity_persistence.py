"""Persistence gateway for Phase 2 scene entity extraction."""

from __future__ import annotations

import logging
import unicodedata
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.context_snapshot_helpers import build_result_ref
from modules.imports.llm_schemas import (
    AliasRelationExtractionOutput,
    DeltaEvent,
    ExtractedEntity,
    ExtractedMapObservationProposal,
    ExtractedRelation,
)

logger = logging.getLogger(__name__)

_EXTRACTION_ALIAS_PLACEHOLDERS = frozenset(
    {
        "变量",
        "variable",
        "placeholder",
        "未知",
        "unknown",
        "某人",
        "某物",
        "n/a",
        "none",
    }
)

_MAP_INTENT_META_KEYS = (
    "map_id",
    "map_dynamic_type",
    "dynamic_type",
    "map_value",
    "normalized_value",
)


def _delta_event_has_map_intent(meta: dict[str, Any]) -> bool:
    """Return whether a generic memory delta explicitly carries map semantics."""
    if any(meta.get(key) not in (None, "", {}, []) for key in _MAP_INTENT_META_KEYS):
        return True
    return bool(meta.get("spatial_anchor"))


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
    normalized = _normalize_phase2b_alias(alias).casefold()
    return normalized in _EXTRACTION_ALIAS_PLACEHOLDERS


def _normalize_phase2b_alias(alias: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(alias or "")).strip().split())


def _alias_matches_known_identity(
    alias: str,
    candidates: Any,
) -> bool:
    normalized = _normalize_phase2b_alias(alias).casefold()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for term in [candidate.get("name"), *(candidate.get("aliases") or [])]:
            if _normalize_phase2b_alias(term).casefold() == normalized:
                return True
    return False


def _phase2b_exact_evidence_quotes(quotes: list[str], scene_text: str) -> list[str]:
    normalized = list(
        dict.fromkeys(str(quote).strip() for quote in quotes if str(quote).strip())
    )
    if not normalized or any(quote not in scene_text for quote in normalized):
        return []
    return normalized


def _previous_relation_matches(
    previous: dict[str, Any],
    *,
    novel_id: str,
    source_id: str,
    target_id: str,
    directionality: str,
) -> bool:
    if str(previous.get("novel_id") or "") != str(novel_id):
        return False
    previous_source = str(previous.get("source_id") or "")
    previous_target = str(previous.get("target_id") or "")
    if directionality == "symmetric":
        return {previous_source, previous_target} == {source_id, target_id}
    return previous_source == source_id and previous_target == target_id


def _live_relation_matches_frozen(live: Any, frozen: dict[str, Any]) -> bool:
    """Reject stale prompt refs instead of applying observations to changed rows."""

    def _value(name: str) -> str:
        raw = live.get(name) if isinstance(live, dict) else getattr(live, name, "")
        return str(raw or "")

    if _value("status") not in {"canonical", "draft", "candidate"}:
        return False
    for key in ("id", "source_id", "target_id", "relation_type", "status"):
        expected = str(frozen.get(key) or "")
        if expected and _value(key) != expected:
            return False
    return True


def _frozen_relation_matches_claim(
    frozen: dict[str, Any],
    *,
    source_id: str,
    target_id: str,
    relation_type: str,
    directionality: str,
) -> bool:
    if str(frozen.get("relation_type") or "") != relation_type:
        return False
    frozen_source = str(frozen.get("source_id") or "")
    frozen_target = str(frozen.get("target_id") or "")
    if directionality == "symmetric":
        return {frozen_source, frozen_target} == {source_id, target_id}
    return frozen_source == source_id and frozen_target == target_id


def _phase2b_diagnostic(
    *,
    kind: str,
    refs: list[str],
    claim: str,
    reason: str,
    evidence_quotes: list[str],
) -> dict[str, Any]:
    return {
        "source": "deterministic_materializer",
        "kind": kind,
        "related_refs": [ref for ref in refs if ref],
        "mention_or_claim": claim,
        "reason": reason,
        "evidence_quotes": evidence_quotes,
    }


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


class SceneEntityPersistenceMixin:
    """Internal Phase 2 persistence implementation."""

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

    async def _persist_alias_relation_output(
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
        context_bundle: dict[str, Any] | None = None,
        current_scene_text: str | None = None,
        context_snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        from modules.world.facade import (
            append_candidate_alias,
            create_or_merge_relation,
            get_entity_relations,
            list_entities,
        )

        bundle = dict(context_bundle or {})
        scene_text = str(
            current_scene_text
            if current_scene_text is not None
            else bundle.get("_current_scene_text") or ""
        )
        entity_ref_map = {
            str(key): str(value)
            for key, value in (bundle.get("_entity_ref_map") or {}).items()
            if str(key) and str(value)
        }
        relation_ref_map = {
            str(key): dict(value)
            for key, value in (bundle.get("_relation_ref_map") or {}).items()
            if str(key) and isinstance(value, dict)
        }
        candidate_by_ref = {
            str(item.get("prompt_ref")): item
            for item in (bundle.get("identity_candidates") or [])
            if isinstance(item, dict) and item.get("prompt_ref")
        }
        current_entities = await list_entities(
            db,
            novel_id,
            statuses=("canonical", "draft", "candidate"),
            limit=10_000,
        )
        current_entity_ids = {
            str(item.get("id"))
            for item in current_entities
            if isinstance(item, dict) and item.get("id")
        }
        referenced_previous_ids = {
            str(relation_ref_map[ref]["id"])
            for item in output.relations
            for ref in [str(item.previous_relation_ref or "")]
            if ref in relation_ref_map and relation_ref_map[ref].get("id")
        }
        live_relation_by_id: dict[str, Any] = {}
        if referenced_previous_ids:
            relation_skip = 0
            while referenced_previous_ids - set(live_relation_by_id):
                live_relations, live_relation_total = await get_entity_relations(
                    db,
                    novel_id,
                    skip=relation_skip,
                    limit=10_000,
                )
                for item in live_relations:
                    relation_id = str(
                        item.get("id")
                        if isinstance(item, dict)
                        else getattr(item, "id", "")
                    )
                    if relation_id in referenced_previous_ids:
                        live_relation_by_id[relation_id] = item
                relation_skip += len(live_relations)
                if not live_relations or relation_skip >= live_relation_total:
                    break
        diagnostics = [
            {
                "source": "model_uncertain_item",
                **item.model_dump(mode="json"),
            }
            for item in output.uncertain_items
        ]

        aliases_created = 0
        relations_created = 0
        for alias in output.aliases:
            evidence_quotes = _phase2b_exact_evidence_quotes(
                alias.evidence_quotes,
                scene_text,
            )
            entity_id = entity_ref_map.get(alias.entity_ref)
            candidate = candidate_by_ref.get(alias.entity_ref)
            reason: str | None = None
            normalized_alias = _normalize_phase2b_alias(alias.alias)
            if not entity_id or candidate is None:
                reason = "unknown_entity_ref"
            elif entity_id not in current_entity_ids:
                reason = "entity_ref_outside_novel_or_inactive"
            elif alias.identity_scope == "uncertain":
                reason = "alias_identity_uncertain"
            elif not evidence_quotes:
                reason = "evidence_not_found_in_current_scene"
            elif not normalized_alias or _is_extraction_alias_placeholder(
                normalized_alias
            ):
                reason = "blank_or_placeholder_alias"
            elif _alias_matches_known_identity(
                normalized_alias,
                candidate_by_ref.values(),
            ):
                reason = "alias_matches_existing_name_or_alias"
            if reason:
                diagnostics.append(
                    _phase2b_diagnostic(
                        kind="alias_identity",
                        refs=[alias.entity_ref],
                        claim=alias.alias,
                        reason=reason,
                        evidence_quotes=evidence_quotes,
                    )
                )
                continue

            async with db.begin_nested():
                added = await append_candidate_alias(
                    db,
                    novel_id,
                    entity_id,
                    alias=normalized_alias,
                    alias_type=alias.alias_type,
                    workflow_id=workflow_id,
                    scene_id=scene_id,
                    scene_index=scene_index,
                    confidence=alias.confidence,
                    quote=evidence_quotes[0],
                    review_meta={
                        "identity_scope": alias.identity_scope,
                        "identity_basis": alias.identity_basis,
                        "confidence": alias.confidence,
                        "evidence_quotes": evidence_quotes,
                        "prompt_entity_ref": alias.entity_ref,
                        "context_fingerprint": bundle.get("context_fingerprint"),
                        "context_snapshot_id": context_snapshot_id,
                    },
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
                        quote=evidence_quotes[0],
                        scene_id=scene_id,
                        workflow_id=workflow_id,
                    )
            if added:
                aliases_created += 1
                if result_refs is not None:
                    result_refs.append(
                        {
                            "type": "entity_alias",
                            "id": f"{entity_id}:{normalized_alias}",
                        }
                    )

        for rel in output.relations:
            evidence_quotes = _phase2b_exact_evidence_quotes(
                rel.evidence_quotes,
                scene_text,
            )
            source_ref = rel.source_ref
            target_ref = rel.target_ref
            source_id = entity_ref_map.get(source_ref)
            target_id = entity_ref_map.get(target_ref)
            reason: str | None = None
            previous = (
                relation_ref_map.get(str(rel.previous_relation_ref))
                if rel.previous_relation_ref
                else None
            )
            live_previous = (
                live_relation_by_id.get(str(previous.get("id") or ""))
                if previous is not None
                else None
            )
            established_collision = bool(
                rel.claim_status == "established"
                and source_id
                and target_id
                and any(
                    _frozen_relation_matches_claim(
                        frozen,
                        source_id=source_id,
                        target_id=target_id,
                        relation_type=rel.relation_type,
                        directionality=rel.directionality,
                    )
                    for frozen in relation_ref_map.values()
                )
            )
            if not source_id or not target_id:
                reason = "unknown_relation_endpoint_ref"
            elif (
                source_id not in current_entity_ids or target_id not in current_entity_ids
            ):
                reason = "relation_endpoint_outside_novel_or_inactive"
            elif source_id == target_id:
                reason = "self_relation"
            elif not evidence_quotes:
                reason = "evidence_not_found_in_current_scene"
            elif rel.persistence_scope in {"episodic", "uncertain"}:
                reason = f"relation_not_persistable_{rel.persistence_scope}"
            elif established_collision:
                reason = "established_relation_already_exists"
            elif rel.claim_status != "established" and previous is None:
                reason = "unknown_previous_relation_ref"
            elif previous is not None and live_previous is None:
                reason = "previous_relation_outside_novel_or_inactive"
            elif previous is not None and not _live_relation_matches_frozen(
                live_previous,
                previous,
            ):
                reason = "previous_relation_changed_since_context"
            elif previous is not None and not _previous_relation_matches(
                previous,
                novel_id=novel_id,
                source_id=source_id,
                target_id=target_id,
                directionality=rel.directionality,
            ):
                reason = "previous_relation_endpoint_or_novel_mismatch"
            elif (
                rel.claim_status == "reaffirmed"
                and previous is not None
                and str(previous.get("relation_type") or "") != rel.relation_type
            ):
                reason = "reaffirmed_relation_type_contradiction"
            if reason:
                diagnostics.append(
                    _phase2b_diagnostic(
                        kind=(
                            "relation_endpoint"
                            if "endpoint" in reason or "self" in reason
                            else "relation_change"
                        ),
                        refs=[
                            rel.source_ref,
                            rel.target_ref,
                            *(
                                [str(rel.previous_relation_ref)]
                                if rel.previous_relation_ref
                                else []
                            ),
                        ],
                        claim=rel.description,
                        reason=reason,
                        evidence_quotes=evidence_quotes,
                    )
                )
                continue

            if rel.directionality == "symmetric" and source_id > target_id:
                source_id, target_id = target_id, source_id
                source_ref, target_ref = target_ref, source_ref
            review_meta = _relation_review_meta(
                workflow_id=workflow_id,
                scene_id=scene_id,
                scene_index=scene_index,
                source_chapter_index=None,
                quote=evidence_quotes[0],
                context_snapshot_id=context_snapshot_id,
            )
            review_meta.update(
                {
                    "claim_status": rel.claim_status,
                    "previous_relation_ref": rel.previous_relation_ref,
                    "previous_relation_id": (
                        previous.get("id") if previous is not None else None
                    ),
                    "basis": rel.basis,
                    "persistence_scope": rel.persistence_scope,
                    "directionality": rel.directionality,
                    "confidence": rel.confidence,
                    "evidence_quotes": evidence_quotes,
                    "source_prompt_ref": source_ref,
                    "target_prompt_ref": target_ref,
                    "context_fingerprint": bundle.get("context_fingerprint"),
                    "needs_review": True,
                }
            )
            if rel.claim_status in {"changed", "ended"}:
                diagnostics.append(
                    {
                        **_phase2b_diagnostic(
                            kind="relation_change",
                            refs=[
                                source_ref,
                                target_ref,
                                str(rel.previous_relation_ref),
                            ],
                            claim=rel.description,
                            reason="relation_change_requires_author_review",
                            evidence_quotes=evidence_quotes,
                        ),
                        "review_meta": review_meta,
                        "candidate_payload": {
                            "source_ref": source_ref,
                            "target_ref": target_ref,
                            "relation_type": rel.relation_type,
                            "description": rel.description,
                            "strength": rel.strength,
                        },
                    }
                )
            try:
                async with db.begin_nested():
                    relation_payload: dict[str, Any] = {
                        "source_id": source_id,
                        "target_id": target_id,
                        "relation_type": rel.relation_type,
                        "description": rel.description,
                        "quote": evidence_quotes[0],
                        "status": "candidate",
                        "review_meta": review_meta,
                    }
                    if rel.strength is not None:
                        relation_payload["strength"] = rel.strength
                    relation_result = await create_or_merge_relation(
                        db,
                        novel_id,
                        relation_payload,
                    )
                    relation = relation_result.get("relation")
                    relation_id = getattr(relation, "id", None)
                    if relation_id and (
                        relation_result.get("action") != "deduplicated"
                        or rel.claim_status == "reaffirmed"
                    ):
                        await self._record_quote_evidence(
                            db,
                            novel_id=novel_id,
                            target_ref={
                                "target_type": "entity_relation",
                                "target_id": str(relation_id),
                                "target_path": "description",
                            },
                            quote=evidence_quotes[0],
                            scene_id=scene_id,
                            workflow_id=workflow_id,
                        )
            except Exception as exc:
                logger.warning(
                    "Failed to create phase2b relation %s -> %s: %s",
                    rel.source_ref,
                    rel.target_ref,
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

        return {
            "aliases": aliases_created,
            "relations": relations_created,
            "uncertain_count": len(diagnostics),
            "diagnostics": diagnostics,
        }

    async def _persist_entities(
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
        service = self
        from modules.world.facade import (
            create_entity,
            find_entity_id_by_name,
            find_similar_entities,
            find_working_entity_id_by_name,
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
            exact_working_entity_id = await find_working_entity_id_by_name(
                db,
                str(nid),
                ent.name,
                entity_type=ent.entity_type,
            )
            if exact_working_entity_id:
                evidence_quotes = list(dict.fromkeys(ent.evidence_quotes or [ent.quote]))
                for quote in evidence_quotes:
                    await self._record_quote_evidence(
                        db,
                        novel_id=str(nid),
                        target_ref={
                            "target_type": "core_entity",
                            "target_id": exact_working_entity_id,
                            "target_path": "summary",
                        },
                        quote=quote,
                        scene_id=scene_id,
                        workflow_id=workflow_id,
                        visible_until_chapter=source_chapter_index,
                    )
                seen_entity_keys.add(entity_key)
                if persistence_stats is not None:
                    persistence_stats["dedup_counts"]["skipped"] += 1
                if result_refs is not None:
                    result_refs.append(
                        build_result_ref("core_entity", exact_working_entity_id)
                    )
                continue
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
                        evidence_quotes = list(
                            dict.fromkeys(ent.evidence_quotes or [ent.quote])
                        )
                        for quote in evidence_quotes:
                            await self._record_quote_evidence(
                                db,
                                novel_id=str(nid),
                                target_ref={
                                    "target_type": "core_entity",
                                    "target_id": str(evidence_target_id),
                                    "target_path": "summary",
                                },
                                quote=quote,
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

    async def _persist_relations(
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

    async def _record_deltas(
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
        map_payloads: list[tuple[int, dict[str, Any]]] = []
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
            if _delta_event_has_map_intent(event_meta):
                map_payload = event.model_dump()
                observation_meta.pop("scene_id", None)
                map_payload["meta"] = observation_meta
                map_payloads.append((len(ingest_events) - 1, map_payload))

        result = await ingest_delta_events(
            db,
            str(nid),
            ingest_events,
            result_refs=result_refs,
        )
        for delta_index, event_payload in map_payloads:
            delta = result.delta_logs[delta_index]
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

    async def _record_map_observation_proposals(
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


class SceneEntityPersistenceGateway(SceneEntityPersistenceMixin):
    """Compatibility adapter for the former persistence gateway."""

    def __init__(self, service) -> None:
        self.service = service

    def __getattr__(self, name):
        return getattr(self.service, name)

    async def persist_alias_relation_output(self, *args, **kwargs):
        return await self._persist_alias_relation_output(*args, **kwargs)

    async def persist_entities(self, *args, **kwargs):
        return await self._persist_entities(*args, **kwargs)

    async def persist_relations(self, *args, **kwargs):
        return await self._persist_relations(*args, **kwargs)

    async def record_deltas(self, *args, **kwargs):
        return await self._record_deltas(*args, **kwargs)

    async def record_map_observation_proposals(self, *args, **kwargs):
        return await self._record_map_observation_proposals(*args, **kwargs)
