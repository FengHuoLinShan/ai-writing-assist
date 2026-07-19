"""Deterministic Phase 2 map-proposal mapping into the stable world seam."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from modules.imports.llm_schemas import ExtractedMapObservationProposal
from modules.world.contracts import (
    MapBoundaryProposal,
    MapCharacterLocationProposal,
    MapEventLocationProposal,
    MapObservationCandidateAuthorization,
    MapObservationCandidateInput,
    MapRouteStateProposal,
)


@dataclass(frozen=True)
class MapObservationProposalPosition:
    """Exact published-draft coordinate for one materialized proposal."""

    scene_sequence: int
    source_start_offset: int
    source_end_offset: int


def build_map_observation_candidates(
    proposals: list[ExtractedMapObservationProposal],
    *,
    novel_id: str,
    workflow_id: str,
    scene_id: str,
    scene_index: int,
    source_chapter_index: int,
    scene_source_fingerprint: str,
    context_snapshot_id: str | None = None,
    task_id: str | None = None,
    source_workflow: Literal["deep_import", "map_enrichment"] = "deep_import",
    proposal_positions: list[MapObservationProposalPosition | None] | None = None,
    target_entity_ids: list[str | None] | None = None,
    location_entity_ids: list[str | None] | None = None,
    authorization_snapshot: dict[str, Any],
) -> list[MapObservationCandidateInput]:
    """Map untrusted LLM output to provenance-complete stable inputs."""
    positions = (
        [None] * len(proposals) if proposal_positions is None else proposal_positions
    )
    if len(positions) != len(proposals):
        raise ValueError("proposal positions must align with proposals")
    targets = [None] * len(proposals) if target_entity_ids is None else target_entity_ids
    locations = (
        [None] * len(proposals) if location_entity_ids is None else location_entity_ids
    )
    if len(targets) != len(proposals):
        raise ValueError("target entity ids must align with proposals")
    if len(locations) != len(proposals):
        raise ValueError("location entity ids must align with proposals")
    if not isinstance(authorization_snapshot, dict) or not authorization_snapshot:
        raise ValueError("typed map proposals require an authorization snapshot")
    fingerprint_payload = json.dumps(
        authorization_snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    authorization = MapObservationCandidateAuthorization.model_validate(
        {
            "adoption_policy": authorization_snapshot.get("adoption_policy"),
            "authorization_confirmed": authorization_snapshot.get(
                "authorization_confirmed"
            ),
            "authorized_at": authorization_snapshot.get("authorized_at"),
            "scope": authorization_snapshot.get("scope"),
            "snapshot_fingerprint": hashlib.sha256(fingerprint_payload).hexdigest(),
        }
    )
    if authorization.scope.novel_id != str(uuid.UUID(novel_id)):
        raise ValueError("authorization snapshot novel scope does not match proposal")
    if not (
        authorization.scope.start_chapter
        <= source_chapter_index
        <= authorization.scope.end_chapter
    ):
        raise ValueError("authorization snapshot chapter scope does not cover proposal")

    source_metadata: list[tuple[str, str]] = []
    source_groups: dict[str, list[tuple[str, int]]] = {}
    for index, item in enumerate(proposals):
        evidence_anchor = hashlib.sha256(item.quote.encode("utf-8")).hexdigest()
        source_key_basis = "|".join(
            (scene_source_fingerprint, item.proposal_type, evidence_anchor)
        )
        identity_hint = json.dumps(
            item.model_dump(
                mode="json",
                exclude={"quote", "confidence", "supporting_scene_ids"},
                exclude_none=False,
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        source_metadata.append((source_key_basis, evidence_anchor))
        source_groups.setdefault(source_key_basis, []).append((identity_hint, index))

    stable_ordinals: dict[int, int] = {}
    for items in source_groups.values():
        for local_ordinal, (_identity_hint, index) in enumerate(sorted(items)):
            stable_ordinals[index] = local_ordinal

    candidates: list[MapObservationCandidateInput] = []
    for index, item in enumerate(proposals):
        proposal_type = item.proposal_type
        target_name: str | None = None
        if proposal_type == "character_location":
            target_name = item.character_name
            proposal = MapCharacterLocationProposal(
                proposal_type=proposal_type,
                location_name=item.location_name,
                movement_mode=item.movement_mode,
                state=item.state,
            )
        elif proposal_type == "event_location":
            target_name = item.event_name
            proposal = MapEventLocationProposal(
                proposal_type=proposal_type,
                location_name=item.location_name,
                state=item.state,
            )
        elif proposal_type == "route_state":
            proposal = MapRouteStateProposal(
                proposal_type=proposal_type,
                path_name=item.path_name,
                state=item.state,
                reason=item.reason,
            )
        else:
            target_name = item.controller_name
            proposal = MapBoundaryProposal(
                proposal_type="boundary",
                controller_name=item.controller_name,
                area_description=item.area_description,
            )
        source_key_basis, evidence_anchor = source_metadata[index]
        local_ordinal = stable_ordinals[index]
        position = positions[index]
        source_key_digest = hashlib.sha256(source_key_basis.encode("utf-8")).hexdigest()
        candidates.append(
            MapObservationCandidateInput(
                workflow_id=workflow_id,
                source_workflow=source_workflow,
                task_id=task_id,
                source_item_key=(
                    f"map-proposal:v1:{proposal_type}:{source_key_digest}:{local_ordinal}"
                ),
                scene_id=scene_id,
                scene_index=scene_index,
                scene_sequence=(position.scene_sequence if position else None),
                source_chapter_index=source_chapter_index,
                source_start_offset=(position.source_start_offset if position else None),
                source_end_offset=(position.source_end_offset if position else None),
                scene_source_fingerprint=scene_source_fingerprint,
                context_snapshot_id=context_snapshot_id,
                evidence_text=item.quote,
                evidence_anchor=evidence_anchor,
                confidence=item.confidence,
                target_entity_id=targets[index],
                resolved_location_entity_id=locations[index],
                target_name=target_name,
                proposal=proposal,
                authorization=authorization,
            )
        )
    return candidates


__all__ = [
    "MapObservationProposalPosition",
    "build_map_observation_candidates",
]
