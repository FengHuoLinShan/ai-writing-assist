"""Server-owned revision differences and referentially complete partial adoption."""

from core.errors import ConflictError, ValidationError
from modules.world.map_structure_geometry import route_key
from modules.world.map_structure_schemas import MapDocument

COLLECTIONS = {
    "space": ("spaces", "id"),
    "feature": ("features", "id"),
    "constraint": ("constraints", "id"),
    "journey": ("journeys", "id"),
    "image": ("images", "page_id"),
    "binding": ("annotation_bindings", "annotation_id"),
}


def document_items(document: MapDocument) -> dict:
    return {
        f"{prefix}:{getattr(item, identity)}": item
        for prefix, (collection, identity) in COLLECTIONS.items()
        for item in getattr(document, collection)
    }


def changed_items(before: MapDocument, after: MapDocument) -> set[str]:
    old, new = document_items(before), document_items(after)
    return {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}


def _references(key, item):
    if item is None:
        return set()
    if key.startswith("space:"):
        return set()
    if key.startswith("feature:"):
        return set(item.depends_on)
    if key.startswith("constraint:"):
        return {item.subject, item.target, *item.via}
    if key.startswith("journey:"):
        return {item.origin, item.destination}
    if key.startswith("image:"):
        return {anchor.feature_id for anchor in item.anchors} | (
            {item.feature_id} if item.feature_id else set()
        )
    return {item.feature_id}


def _dependency_keys(key, item):
    if item is None:
        return set()
    related = {f"feature:{reference}" for reference in _references(key, item)}
    if key.startswith("feature:"):
        related.add(f"space:{item.space_id}")
    return related


def apply_revision_changes(baseline, candidate, requested):
    """Include connected changed dependencies, never delete unchanged dependents."""
    old, new = document_items(baseline), document_items(candidate)
    changes = changed_items(baseline, candidate)
    selected = set(changes if requested is None else requested)
    if not selected.issubset(changes):
        raise ValidationError("所选修改已不属于这份候选，请重新比较")
    initial = set(selected)
    adjacent = {key: set() for key in changes}
    for key in changes:
        related = _dependency_keys(key, old.get(key)) | _dependency_keys(
            key, new.get(key)
        )
        if key.startswith("space:"):
            space_id = key.removeprefix("space:")
            related |= {
                f"feature:{item.id}"
                for document in (baseline, candidate)
                for item in document.features
                if item.space_id == space_id
            }
        related &= changes
        if key.startswith("constraint:"):
            related |= {f"feature:{route_key(key.removeprefix('constraint:'))}"} & changes
        for dependency in related:
            adjacent[key].add(dependency)
            adjacent[dependency].add(key)
    pending = list(selected)
    while pending:
        for key in adjacent[pending.pop()] - selected:
            selected.add(key)
            pending.append(key)
    required_deletions = sorted(
        key
        for key in selected - initial
        if key.startswith("feature:") and key not in new and old[key].points
    )
    if required_deletions:
        raise ConflictError(
            "这项修改还会移除关联图形，请明确勾选这些图形的移除项后再采用",
            code="map_review_requires_selection",
            context={"required_change_keys": required_deletions},
        )
    merged = dict(old)
    for key in selected:
        if key in new:
            merged[key] = new[key]
        else:
            merged.pop(key, None)
    feature_ids = {
        key.removeprefix("feature:") for key in merged if key.startswith("feature:")
    }
    for key, item in merged.items():
        if key.startswith("space:"):
            continue
        if not _references(key, item).issubset(feature_ids):
            raise ConflictError(
                "这项修改会丢失仍在使用的地点或手工图形，请先关联处理依赖内容"
            )
    payload = baseline.model_dump(mode="json")
    # Schema upgrades are monotonic and implicit. V2 documents need not expose a
    # synthetic version change key in the author's checkbox list.
    payload["schema_version"] = max(baseline.schema_version, candidate.schema_version)
    for prefix, (collection, _) in COLLECTIONS.items():
        payload[collection] = [
            item.model_dump(mode="json")
            for key, item in merged.items()
            if key.startswith(f"{prefix}:")
        ]
    try:
        document = MapDocument.model_validate(payload)
    except ValueError as exc:
        raise ConflictError("所选修改无法组成完整地图，请一并选择关联修改") from exc
    return document, sorted(selected), sorted(selected - initial)
