"""Read-only resolution for explicitly aligned World/Story validity conflicts."""

from dataclasses import dataclass
from typing import Any

from modules.world.map_declaration_state import (
    MAP_DECLARATION_FIELD_KEY,
    MapDeclarationKind,
    map_declaration_subject_id,
)
from shared.utils import parse_uuid


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


@dataclass(frozen=True)
class StoryMapDeclarationObservation:
    status: str | None
    gap: str | None
    source_refs: list[dict[str, Any]] | None = None
    event_id: str | None = None
    scene_index: int | None = None
    author_confirmed: bool = False
    identity_ref: dict[str, Any] | None = None


@dataclass(frozen=True)
class MapDeclarationValidityDecision:
    effective: bool
    author_active: bool | None
    status: str | None
    gap: str | None
    observation: StoryMapDeclarationObservation | None = None


def exact_story_map_declaration_observation(
    view: Any,
    *,
    novel_id: str,
    cutoff_scene_id: str,
    node_id: str,
    revision_id: str,
    declaration_kind: MapDeclarationKind,
    declaration_id: str,
    cutoff_scene_index: int,
) -> StoryMapDeclarationObservation:
    """Read a confirmed event only for this exact project/map declaration.

    The source must be an author-confirmed typed Story field whose persisted
    identity metadata matches the project, node, current revision, kind, and
    original FeatureKey. Location or content matches never participate.
    """

    def value_of(value: Any, key: str, default: Any = None) -> Any:
        return (
            value.get(key, default)
            if isinstance(value, dict)
            else getattr(value, key, default)
        )

    dimensions = value_of(view, "dimensions")
    entities = next(
        (item for item in dimensions or [] if value_of(item, "dimension") == "entities"),
        None,
    )
    if entities is None:
        return StoryMapDeclarationObservation(None, "story_state_unavailable")
    if str(value_of(view, "novel_id", "")) != str(parse_uuid(novel_id, "novel_id")):
        return StoryMapDeclarationObservation(None, "story_view_project_mismatch")
    if str(value_of(view, "scene_id", "")) != str(
        parse_uuid(cutoff_scene_id, "scene_id")
    ):
        return StoryMapDeclarationObservation(None, "story_view_scene_mismatch")
    view_scene_index = value_of(view, "scene_index")
    if (
        isinstance(view_scene_index, bool)
        or not isinstance(view_scene_index, int)
        or view_scene_index != cutoff_scene_index
    ):
        return StoryMapDeclarationObservation(None, "story_view_cutoff_mismatch")
    dimension_status = value_of(entities, "status")
    if dimension_status in {"missing", "unsupported"}:
        return StoryMapDeclarationObservation(None, "story_observation_missing")
    if dimension_status != "ok":
        return StoryMapDeclarationObservation(None, "story_state_degraded")

    subject_id = map_declaration_subject_id(
        novel_id, node_id, declaration_kind, declaration_id
    )
    matching = [
        fact
        for fact in value_of(entities, "facts", []) or []
        if str(value_of(fact, "subject_id", "")) == subject_id
        and value_of(fact, "field") == MAP_DECLARATION_FIELD_KEY
    ]
    if not matching:
        return StoryMapDeclarationObservation(None, "story_observation_missing")

    def order(fact: Any) -> tuple[int, int]:
        occurred = value_of(fact, "occurred_at") or {}
        scene_index = value_of(occurred, "scene_index", -1)
        sequence = value_of(occurred, "scene_sequence", -1)
        return (
            scene_index
            if isinstance(scene_index, int) and not isinstance(scene_index, bool)
            else -1,
            sequence
            if isinstance(sequence, int) and not isinstance(sequence, bool)
            else -1,
        )

    latest_order = max(order(fact) for fact in matching)
    latest = [fact for fact in matching if order(fact) == latest_order]
    if len(latest) != 1:
        return StoryMapDeclarationObservation(
            None, "story_map_declaration_identity_ambiguous"
        )
    fact = latest[0]
    source = value_of(fact, "source") or {}
    provenance = value_of(source, "provenance")
    if not isinstance(provenance, dict):
        return StoryMapDeclarationObservation(None, "story_source_unverified")
    if (
        provenance.get("object_type") != "map_declaration"
        or provenance.get("field") != MAP_DECLARATION_FIELD_KEY
    ):
        return StoryMapDeclarationObservation(None, "story_alignment_unverified")
    expected_identity = {
        "contract_version": 1,
        "novel_id": str(parse_uuid(novel_id, "novel_id")),
        "node_id": str(parse_uuid(node_id, "node_id")),
        "revision_id": str(parse_uuid(revision_id, "revision_id")),
        "subject_id": subject_id,
        "declaration_kind": declaration_kind,
        "declaration_id": declaration_id,
        "field_key": MAP_DECLARATION_FIELD_KEY,
    }
    identity = provenance.get("identity_ref")
    if identity != expected_identity:
        if isinstance(identity, dict) and identity.get("revision_id") != str(revision_id):
            return StoryMapDeclarationObservation(
                None,
                "story_map_declaration_revision_changed",
                identity_ref=identity,
            )
        return StoryMapDeclarationObservation(
            None,
            "story_alignment_unverified",
            identity_ref=identity if isinstance(identity, dict) else None,
        )
    if value_of(fact, "confidence") != "confirmed":
        return StoryMapDeclarationObservation(None, "story_observation_unconfirmed")
    if provenance.get("author_confirmed") is not True:
        return StoryMapDeclarationObservation(None, "story_source_unverified")
    observed_index = value_of(value_of(fact, "occurred_at") or {}, "scene_index")
    if isinstance(observed_index, bool) or not isinstance(observed_index, int):
        return StoryMapDeclarationObservation(None, "story_observation_time_unverified")
    if observed_index >= cutoff_scene_index:
        return StoryMapDeclarationObservation(None, "story_observation_not_before_cutoff")
    status = value_of(fact, "value")
    if status not in {"active", "inactive"}:
        return StoryMapDeclarationObservation(None, "story_observation_unverified")
    return StoryMapDeclarationObservation(
        status=status,
        gap=None,
        source_refs=list(provenance.get("source_refs") or []),
        event_id=str(provenance.get("event_id") or "") or None,
        scene_index=observed_index,
        author_confirmed=True,
        identity_ref=identity,
    )


def resolve_map_declaration_validity(
    *,
    author_active: bool | None,
    anchor_gap: str | None,
    story_view: Any,
    novel_id: str,
    cutoff_scene_id: str,
    node_id: str,
    revision_id: str,
    declaration_kind: MapDeclarationKind,
    declaration_id: str,
    cutoff_scene_index: int | None,
    allow_story_override: bool,
    policy_gap: str | None = None,
) -> MapDeclarationValidityDecision:
    """Apply the project read policy without materializing or mutating Story."""
    if anchor_gap or author_active is None:
        return MapDeclarationValidityDecision(
            effective=False,
            author_active=author_active,
            status="gap",
            gap=anchor_gap or "scene_cutoff_unavailable",
        )
    if cutoff_scene_index is None:
        return MapDeclarationValidityDecision(
            effective=False,
            author_active=author_active,
            status="gap",
            gap="scene_cutoff_unavailable",
        )
    if story_view is None:
        return MapDeclarationValidityDecision(
            effective=author_active,
            author_active=author_active,
            status="gap",
            gap=policy_gap or "story_map_declaration_unavailable",
        )
    observation = exact_story_map_declaration_observation(
        story_view,
        novel_id=novel_id,
        cutoff_scene_id=cutoff_scene_id,
        node_id=node_id,
        revision_id=revision_id,
        declaration_kind=declaration_kind,
        declaration_id=declaration_id,
        cutoff_scene_index=cutoff_scene_index,
    )
    if observation.gap:
        return MapDeclarationValidityDecision(
            effective=author_active,
            author_active=author_active,
            status="gap",
            gap=policy_gap or observation.gap,
            observation=observation,
        )
    if policy_gap:
        return MapDeclarationValidityDecision(
            effective=author_active,
            author_active=author_active,
            status="gap",
            gap=policy_gap,
            observation=observation,
        )
    story_active = observation.status == "active"
    if story_active == author_active:
        return MapDeclarationValidityDecision(
            effective=author_active,
            author_active=author_active,
            status="consistent",
            gap=None,
            observation=observation,
        )
    return MapDeclarationValidityDecision(
        effective=story_active if allow_story_override else author_active,
        author_active=author_active,
        status="story_override" if allow_story_override else "author_priority",
        gap=None,
        observation=observation,
    )


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
    if status != "ok":
        return StoryFieldObservation(None, "story_state_degraded")
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

    def order(fact: Any) -> tuple[int, int]:
        occurred = (
            fact.get("occurred_at", {})
            if isinstance(fact, dict)
            else getattr(fact, "occurred_at", {})
        ) or {}
        index = occurred.get("scene_index") if isinstance(occurred, dict) else None
        sequence = occurred.get("scene_sequence") if isinstance(occurred, dict) else None
        return (
            index if isinstance(index, int) and not isinstance(index, bool) else -1,
            sequence
            if isinstance(sequence, int) and not isinstance(sequence, bool)
            else -1,
        )

    latest_order = max(order(fact) for fact in matching)
    latest = [fact for fact in matching if order(fact) == latest_order]
    if len(latest) != 1:
        return StoryFieldObservation(None, "story_field_identity_ambiguous")
    fact = latest[0]
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
    relation_status = (
        relations.get("status")
        if isinstance(relations, dict)
        else getattr(relations, "status", None)
    )
    if relation_status in {"missing", "unsupported"}:
        return StoryRelationObservation(None, "story_observation_missing")
    if relation_status != "ok":
        return StoryRelationObservation(None, "story_state_degraded")
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
