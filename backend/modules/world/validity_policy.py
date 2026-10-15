"""Read-only resolution for explicitly aligned World/Story validity conflicts."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StoryFieldObservation:
    value: str | None
    gap: str | None
    source_refs: list[dict[str, Any]] | None = None
    event_id: str | None = None
    scene_index: int | None = None
    author_confirmed: bool = False


@dataclass(frozen=True)
class StoryRelationObservation:
    status: str | None
    gap: str | None
    source_refs: list[dict[str, Any]] | None = None
    event_id: str | None = None
    scene_index: int | None = None


def exact_story_field_observation(
    view: Any,
    *,
    entity_id: str,
    entity_type: str,
    field_key: str,
    cutoff_scene_index: int,
) -> StoryFieldObservation:
    """Return only a confirmed, exact, same-object/same-field Story fact.

    The key is structural: World entity ID + declared Story field key. Text
    similarity never participates in selecting a Story observation.
    """
    dimensions = getattr(view, "dimensions", None)
    if dimensions is None and isinstance(view, dict):
        dimensions = view.get("dimensions")
    entities = next(
        (
            item
            for item in dimensions or []
            if (
                item.get("dimension")
                if isinstance(item, dict)
                else getattr(item, "dimension", None)
            )
            == "entities"
        ),
        None,
    )
    if entities is None:
        return StoryFieldObservation(None, "story_state_unavailable")
    status = (
        entities.get("status")
        if isinstance(entities, dict)
        else getattr(entities, "status", None)
    )
    if status in {"missing", "unsupported"}:
        return StoryFieldObservation(None, "story_observation_missing")
    facts = (
        entities.get("facts", [])
        if isinstance(entities, dict)
        else getattr(entities, "facts", [])
    )
    matching = []
    for fact in facts or []:
        get = (
            fact.get
            if isinstance(fact, dict)
            else lambda key, default=None: getattr(fact, key, default)
        )
        if str(get("subject_id", "")) != entity_id or get("field") != field_key:
            continue
        matching.append(fact)
    if not matching:
        return StoryFieldObservation(None, "story_observation_missing")
    fact = matching[-1]
    get = (
        fact.get
        if isinstance(fact, dict)
        else lambda key, default=None: getattr(fact, key, default)
    )
    source = get("source", {}) or {}
    provenance = source.get("provenance") if isinstance(source, dict) else None
    if not isinstance(provenance, dict):
        return StoryFieldObservation(None, "story_source_unverified")
    if (
        provenance.get("object_type") != entity_type
        or provenance.get("field") != field_key
    ):
        return StoryFieldObservation(None, "story_alignment_unverified")
    if get("confidence") != "confirmed":
        return StoryFieldObservation(None, "story_observation_unconfirmed")
    author_confirmed = provenance.get("author_confirmed") is True
    manuscript_proven = provenance.get("status") == "exact" and bool(
        provenance.get("source_refs")
    )
    if not author_confirmed and not manuscript_proven:
        return StoryFieldObservation(None, "story_source_unverified")
    occurred_at = get("occurred_at", {}) or {}
    observed_index = (
        occurred_at.get("scene_index") if isinstance(occurred_at, dict) else None
    )
    if isinstance(observed_index, bool) or not isinstance(observed_index, int):
        return StoryFieldObservation(None, "story_observation_time_unverified")
    if observed_index >= cutoff_scene_index:
        return StoryFieldObservation(None, "story_observation_not_before_cutoff")
    value = get("value")
    if not isinstance(value, str):
        return StoryFieldObservation(None, "story_observation_not_text")
    return StoryFieldObservation(
        value,
        None,
        source_refs=list(provenance.get("source_refs") or []),
        event_id=str(provenance.get("event_id") or "") or None,
        scene_index=observed_index,
        author_confirmed=author_confirmed,
    )


def exact_story_relation_observation(
    view: Any,
    *,
    relation_id: str,
    cutoff_scene_index: int,
) -> StoryRelationObservation:
    """Resolve an exact Story relation ID only when its status has trusted proof."""
    dimensions = getattr(view, "dimensions", None)
    if dimensions is None and isinstance(view, dict):
        dimensions = view.get("dimensions")
    relations = next(
        (
            item
            for item in dimensions or []
            if (
                item.get("dimension")
                if isinstance(item, dict)
                else getattr(item, "dimension", None)
            )
            == "relations"
        ),
        None,
    )
    if relations is None:
        return StoryRelationObservation(None, "story_state_unavailable")
    facts = (
        relations.get("facts", [])
        if isinstance(relations, dict)
        else getattr(relations, "facts", [])
    )
    matched = []
    for fact in facts or []:
        get = (
            fact.get
            if isinstance(fact, dict)
            else lambda key, default=None: getattr(fact, key, default)
        )
        value = get("value")
        if not isinstance(value, dict):
            continue
        if str(get("subject_id", "")) != relation_id:
            continue
        source = get("source", {}) or {}
        if get("field") == "relation" and isinstance(value, dict):
            status = value.get("relation_status")
            provenance = (source.get("field_provenance") or {}).get("relation_status")
        elif (
            get("field") == "relation_status" and value.get("relation_status") == "ended"
        ):
            status = value.get("relation_status")
            provenance = source.get("provenance")
        else:
            continue
        matched.append((fact, get, status, provenance))
    if not matched:
        return StoryRelationObservation(None, "story_observation_missing")

    def order(item):
        get = item[1]
        occurred = get("occurred_at", {}) or {}
        if not isinstance(occurred, dict):
            return (-1, -1)
        scene_index = occurred.get("scene_index", -1)
        sequence = occurred.get("scene_sequence", -1)
        return (
            scene_index
            if isinstance(scene_index, int) and not isinstance(scene_index, bool)
            else -1,
            sequence
            if isinstance(sequence, int) and not isinstance(sequence, bool)
            else -1,
        )

    latest_order = max(order(item) for item in matched)
    latest = [item for item in matched if order(item) == latest_order]
    if len(latest) != 1:
        return StoryRelationObservation(None, "story_relation_identity_ambiguous")
    fact, get, status, provenance = latest[0]
    if status not in {"active", "ended"} or not isinstance(provenance, dict):
        return StoryRelationObservation(None, "story_source_unverified")
    if (
        provenance.get("object_type") != "relation"
        or provenance.get("field") != "relation_status"
    ):
        return StoryRelationObservation(None, "story_alignment_unverified")
    if provenance.get("status") != "exact" or not provenance.get("source_refs"):
        return StoryRelationObservation(None, "story_source_unverified")
    if get("confidence") != "confirmed":
        return StoryRelationObservation(None, "story_observation_unconfirmed")
    occurred_at = get("occurred_at", {}) or {}
    observed_index = (
        occurred_at.get("scene_index") if isinstance(occurred_at, dict) else None
    )
    if isinstance(observed_index, bool) or not isinstance(observed_index, int):
        return StoryRelationObservation(None, "story_observation_time_unverified")
    if observed_index >= cutoff_scene_index:
        return StoryRelationObservation(None, "story_observation_not_before_cutoff")
    return StoryRelationObservation(
        status,
        None,
        source_refs=list(provenance.get("source_refs") or []),
        event_id=str(provenance.get("event_id") or "") or None,
        scene_index=observed_index,
    )
