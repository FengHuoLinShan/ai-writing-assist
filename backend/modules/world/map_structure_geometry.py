"""Deterministic schematic layout, diagnostics, calibration and image guidance."""

from __future__ import annotations

import hashlib
import heapq
import io
import json
from math import hypot
from typing import Any

from modules.world.map_structure_schemas import (
    MapDocument,
    MapFeature,
    MapImagePlacement,
    MapLayoutResponse,
    MapPoint,
    MapProblem,
)

DIRECTIONS = {
    "north": (0, -1),
    "south": (0, 1),
    "east": (1, 0),
    "west": (-1, 0),
    "northeast": (1, -1),
    "northwest": (-1, -1),
    "southeast": (1, 1),
    "southwest": (-1, 1),
}
_KIND_GEOMETRY = {
    "location": "point",
    "landmark": "point",
    "road": "line",
    "river": "line",
    "area": "area",
}


def _pinned_traits(item, type_traits: dict | None, *, prefix: str = ""):
    type_ref = getattr(item, f"{prefix}type_ref")
    revision_id = getattr(item, f"{prefix}type_revision_id")
    if type_ref is None or revision_id is None or type_traits is None:
        return None
    return type_traits.get((type_ref, revision_id))


def _trait_values(traits: Any, name: str) -> set[str]:
    if traits is None:
        return set()
    value = getattr(traits, name, None)
    if value is None and isinstance(traits, dict):
        value = traits.get(name)
    return set(value or [])


def _feature_geometry(feature: MapFeature, type_traits: dict | None) -> str | None:
    expected = _KIND_GEOMETRY.get(feature.kind)
    if feature.type_ref is None:
        return expected
    traits = _pinned_traits(feature, type_traits)
    if expected is None or expected not in _trait_values(traits, "geometry"):
        return None
    return expected


def feature_has_calculable_geometry(
    feature: MapFeature, *, type_traits: dict | None = None
) -> bool:
    return _feature_geometry(feature, type_traits) is not None


def constraint_is_calculable(constraint, *, type_traits: dict | None = None) -> bool:
    if constraint.type_ref is None:
        return True
    traits = _pinned_traits(constraint, type_traits)
    if traits is None:
        return False
    if constraint.relation in DIRECTIONS or constraint.relation == "faces":
        return "compass" in _trait_values(traits, "orientation")
    if constraint.relation == "inside":
        return "can_contain" in _trait_values(traits, "containment")
    if constraint.relation in {
        "connects",
        "passes_through",
        "along_street",
        "entrance_to",
    }:
        return "traversable" in _trait_values(traits, "connection")
    if constraint.relation == "adjacent":
        return "distance_constrained" in _trait_values(traits, "connection")
    return False


def _path_is_calculable(constraint, type_traits: dict | None) -> bool:
    if constraint.path_type_ref is None:
        return True
    traits = _pinned_traits(constraint, type_traits, prefix="path_")
    return "line" in _trait_values(traits, "geometry")


def geometry_hash(document: MapDocument) -> str:
    feature_fields = {"id", "kind", "entity_id", "target_node_id", "points"}
    # Upgrading an unchanged v1 map to v2 must keep its calibrated main-space hash.
    if document.schema_version == 2 and any(
        feature.space_id != "main" for feature in document.features
    ):
        feature_fields.add("space_id")
    payload = {
        "layout_version": document.layout_version,
        "features": [
            f.model_dump(
                mode="json",
                include=feature_fields,
            )
            for f in sorted(document.features, key=lambda f: f.id)
        ],
        "constraints": [
            c.model_dump(
                mode="json",
                include={
                    "id",
                    "subject",
                    "relation",
                    "target",
                    "via",
                    "path_kind",
                    "path_label",
                },
            )
            for c in sorted(document.constraints, key=lambda c: c.id)
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def route_key(constraint_id: str) -> str:
    return "route:" + hashlib.sha256(constraint_id.encode()).hexdigest()[:24]


def _ranks(
    ids: set[str], edges: list[tuple[str, str]]
) -> tuple[dict[str, int], set[str]]:
    outgoing = {key: set() for key in ids}
    indegree = dict.fromkeys(ids, 0)
    for left, right in edges:
        if right not in outgoing[left]:
            outgoing[left].add(right)
            indegree[right] += 1
    heap = [key for key in ids if not indegree[key]]
    heapq.heapify(heap)
    ranks = dict.fromkeys(ids, 0)
    while heap:
        key = heapq.heappop(heap)
        for target in sorted(outgoing[key]):
            ranks[target] = max(ranks[target], ranks[key] + 1)
            indegree[target] -= 1
            if not indegree[target]:
                heapq.heappush(heap, target)
    return ranks, {key for key, degree in indegree.items() if degree}


def _center(feature: MapFeature) -> MapPoint | None:
    if not feature.points:
        return None
    return MapPoint(
        x=sum(p.x for p in feature.points) / len(feature.points),
        y=sum(p.y for p in feature.points) / len(feature.points),
    )


def _inside(point: MapPoint, polygon: list[MapPoint]) -> bool:
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        if ((a.y > point.y) != (b.y > point.y)) and point.x < (b.x - a.x) * (
            point.y - a.y
        ) / (b.y - a.y) + a.x:
            inside = not inside
    return inside


def _direction_ok(a: MapPoint, b: MapPoint, direction: tuple[int, int]) -> bool:
    return all(
        sign == 0 or (left - right) * sign >= 24
        for left, right, sign in zip((a.x, a.y), (b.x, b.y), direction, strict=True)
    )


def _nearest_edge(point: MapPoint, feature: MapFeature) -> MapPoint | None:
    if feature.kind in {"location", "landmark"}:
        return _center(feature)
    points = feature.points + (feature.points[:1] if feature.kind == "area" else [])
    nearest, distance = None, float("inf")
    for start, end in zip(points, points[1:]):
        dx, dy = end.x - start.x, end.y - start.y
        length = dx * dx + dy * dy
        fraction = (
            max(0, min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / length))
            if length
            else 0
        )
        projected = MapPoint(x=start.x + dx * fraction, y=start.y + dy * fraction)
        candidate = hypot(projected.x - point.x, projected.y - point.y)
        if candidate < distance:
            nearest, distance = projected, candidate
    return nearest


def _point_relation_ok(point: MapPoint, target: MapFeature, relation: str) -> bool:
    if relation == "faces":
        center = _center(target)
        return center is not None and hypot(point.x - center.x, point.y - center.y) >= 1
    edge = _nearest_edge(point, target)
    return edge is not None and hypot(point.x - edge.x, point.y - edge.y) <= (
        45 if relation == "along_street" else 75
    )


def diagnose(
    document: MapDocument, *, type_traits: dict | None = None
) -> list[MapProblem]:
    features = {f.id: f for f in document.features}
    calculable_features = {
        feature_id: feature
        for feature_id, feature in features.items()
        if feature.modality == "event_observed" and feature.effective is None
        and _feature_geometry(feature, type_traits) is not None
    }
    problems = []
    for f in document.features:
        if f.id in calculable_features and not f.points:
            problems.append(
                MapProblem(
                    code="unplaced", message=f"“{f.label}”尚未定位", feature_ids=[f.id]
                )
            )
    for c in document.constraints:
        if (
            c.modality != "event_observed"
            or c.effective is not None
            or not constraint_is_calculable(c, type_traits=type_traits)
        ):
            continue
        if c.subject not in calculable_features or c.target not in calculable_features:
            continue
        if features[c.subject].space_id != features[c.target].space_id:
            continue
        a, b = _center(features[c.subject]), _center(features[c.target])
        if not a or not b:
            continue
        if c.relation in DIRECTIONS and not _direction_ok(a, b, DIRECTIONS[c.relation]):
            problems.append(
                MapProblem(
                    code="direction_conflict",
                    message="地点位置与方位资料不一致",
                    feature_ids=[c.subject, c.target],
                )
            )
        if (
            c.relation == "inside"
            and features[c.target].kind == "area"
            and not _inside(a, features[c.target].points)
        ):
            problems.append(
                MapProblem(
                    code="containment_conflict",
                    message="地点不在资料指定的区域内",
                    feature_ids=[c.subject, c.target],
                )
            )
        if c.relation in {
            "along_street",
            "entrance_to",
            "faces",
        } and not _point_relation_ok(a, features[c.target], c.relation):
            problems.append(
                MapProblem(
                    code=f"{c.relation}_conflict",
                    message={
                        "along_street": "地点离所属街道较远，请核对位置",
                        "entrance_to": "入口离所属地点或区域边界较远，请核对位置",
                        "faces": "地点与朝向目标重合，无法确定朝向",
                    }[c.relation],
                    feature_ids=[c.subject, c.target],
                )
            )
        if c.relation in {"connects", "passes_through"}:
            road = features.get(route_key(c.id))
            if road and road.points and (road.points[0] != a or road.points[-1] != b):
                problems.append(
                    MapProblem(
                        code="route_alignment",
                        message="路线端点需要重新对齐地点",
                        feature_ids=[road.id],
                    )
                )
    _, cyclic = _ranks(
        set(calculable_features),
        [
            (c.subject, c.target)
            for c in document.constraints
            if c.relation == "inside"
            and c.modality == "event_observed"
            and c.effective is None
            and constraint_is_calculable(c, type_traits=type_traits)
            and c.subject in calculable_features
            and c.target in calculable_features
        ],
    )
    if cyclic:
        problems.append(
            MapProblem(
                code="containment_cycle",
                message="包含关系存在循环",
                feature_ids=sorted(cyclic),
            )
        )
    return problems


def _place_points(result, features, ranks, cycles, geometry_by_id):
    dependencies, _ = _ranks(
        set(features),
        [
            (c.target, c.subject)
            for c in result.constraints
            if c.relation in {"along_street", "entrance_to", "faces"}
        ],
    )
    # ponytail: bounded grid search; use a solver if 200-feature maps outgrow it.
    for f in sorted(
        result.features,
        key=lambda f: (
            dependencies[f.id],
            ranks[1].get(f.id, 0),
            ranks[0].get(f.id, 0),
            f.id,
        ),
    ):
        if (
            f.points
            or f.locked
            or f.id in cycles
            or geometry_by_id.get(f.id) != "point"
        ):
            continue
        point_relations = [
            c
            for c in result.constraints
            if c.subject == f.id
            and c.relation in {"along_street", "entrance_to", "faces"}
        ]
        if any(
            not features[c.target].points and c.relation != "faces"
            for c in point_relations
        ):
            continue
        x, y = 100 + ranks[0][f.id] * 180, 100 + ranks[1][f.id] * 140
        for c in sorted(point_relations, key=lambda c: c.id):
            other = _nearest_edge(MapPoint(x=x, y=y), features[c.target])
            if other:
                x, y = other.x, other.y
                if c.relation in {"entrance_to", "faces"}:
                    x += 60
                break
        for c in sorted(result.constraints, key=lambda c: c.id):
            if f.id not in {c.subject, c.target}:
                continue
            other = _center(features[c.target if c.subject == f.id else c.subject])
            if other is None:
                continue
            direction = DIRECTIONS.get(c.relation)
            if direction:
                sign = 1 if c.subject == f.id else -1
                x, y = (
                    other.x + direction[0] * 180 * sign,
                    other.y + direction[1] * 140 * sign,
                )
                break
            if c.relation == "adjacent":
                x, y = other.x + 100, other.y
                break
        for radius in range(21):
            found = False
            offsets = [
                (dx, dy)
                for dx in range(-radius, radius + 1)
                for dy in range(-radius, radius + 1)
                if max(abs(dx), abs(dy)) == radius
            ]
            for dx, dy in offsets:
                if abs(x + dx * 60) > 100000 or abs(y + dy * 60) > 100000:
                    continue
                point = MapPoint(x=x + dx * 60, y=y + dy * 60)
                if any(
                    hypot(point.x - p.x, point.y - p.y) < 55
                    for other in result.features
                    if other.id != f.id and geometry_by_id.get(other.id) == "point"
                    for p in other.points
                ):
                    continue
                fits = True
                for c in result.constraints:
                    if c.relation not in DIRECTIONS or f.id not in {c.subject, c.target}:
                        continue
                    a = point if c.subject == f.id else _center(features[c.subject])
                    b = point if c.target == f.id else _center(features[c.target])
                    if a and b and not _direction_ok(a, b, DIRECTIONS[c.relation]):
                        fits = False
                        break
                if fits:
                    fits = all(
                        not features[c.target].points
                        or _point_relation_ok(point, features[c.target], c.relation)
                        for c in point_relations
                    )
                if fits:
                    f.points = [point]
                    found = True
                    break
            if found:
                break


def _layout_single_space(
    document: MapDocument, *, type_traits: dict | None = None
) -> MapLayoutResponse:
    original = document.model_copy(deep=True)
    calculable_features = [
        feature
        for feature in original.features
        if feature.modality == "event_observed" and feature.effective is None
        and _feature_geometry(feature, type_traits) is not None
    ]
    feature_ids = {feature.id for feature in calculable_features}
    calculable_constraints = [
        constraint
        for constraint in original.constraints
        if constraint.modality == "event_observed"
        and constraint.effective is None
        and constraint_is_calculable(constraint, type_traits=type_traits)
        and constraint.subject in feature_ids
        and constraint.target in feature_ids
        and set(constraint.via).issubset(feature_ids)
    ]
    result = original.model_copy(
        update={
            "features": calculable_features,
            "constraints": calculable_constraints,
            "journeys": [],
            "images": [],
            "annotation_bindings": [],
        },
        deep=True,
    )
    features = {f.id: f for f in result.features}
    geometry_by_id = {
        feature.id: _feature_geometry(feature, type_traits)
        for feature in result.features
    }
    ranks, cycles = [], set()
    for axis in (0, 1):
        edges = []
        for c in result.constraints:
            sign = DIRECTIONS.get(c.relation, (0, 0))[axis]
            if sign:
                edges.append((c.target, c.subject) if sign > 0 else (c.subject, c.target))
        rank, cyclic = _ranks(set(features), edges)
        ranks.append(rank)
        cycles.update(cyclic)
    _place_points(result, features, ranks, cycles, geometry_by_id)
    for f in result.features:
        if geometry_by_id.get(f.id) != "area" or f.points or f.locked:
            continue
        children = [
            features[c.subject]
            for c in result.constraints
            if c.relation == "inside" and c.target == f.id
        ]
        points = [p for child in children for p in child.points]
        if points:
            left, right = (
                max(-100000, min(p.x for p in points) - 45),
                min(100000, max(p.x for p in points) + 45),
            )
            top, bottom = (
                max(-100000, min(p.y for p in points) - 45),
                min(100000, max(p.y for p in points) + 45),
            )
            f.points = [
                MapPoint(x=left, y=top),
                MapPoint(x=right, y=top),
                MapPoint(x=right, y=bottom),
                MapPoint(x=left, y=bottom),
            ]
            f.depends_on = sorted(set(f.depends_on) | {child.id for child in children})
    # Areas generated from known contents can now anchor their entrance points.
    _place_points(result, features, ranks, cycles, geometry_by_id)
    for c in result.constraints:
        if c.relation not in {"connects", "passes_through"}:
            continue
        if not _path_is_calculable(c, type_traits):
            continue
        route_id = route_key(c.id)
        route = [c.subject, *c.via, c.target]
        points = [_center(features[key]) for key in route]
        if route_id in features:
            continue
        if len(result.features) >= 200:
            continue
        result.features.append(
            MapFeature(
                id=route_id,
                kind=c.path_kind,
                label=c.path_label
                or ("已知河流" if c.path_kind == "river" else "已知路线"),
                sources=c.sources,
                points=[p for p in points if p] if all(points) else [],
                depends_on=list(dict.fromkeys(route)),
                space_id=features[c.subject].space_id,
                type_ref=c.path_type_ref,
                type_revision_id=c.path_type_revision_id,
            )
        )
    placed_by_id = {feature.id: feature for feature in result.features}
    merged_features = [
        placed_by_id.get(feature.id, feature) for feature in original.features
    ]
    original_feature_ids = {item.id for item in original.features}
    merged_features.extend(
        feature
        for feature in result.features
        if feature.id not in original_feature_ids
    )
    result = original.model_copy(update={"features": merged_features}, deep=True)
    problems = diagnose(result, type_traits=type_traits)
    if cycles:
        problems.append(
            MapProblem(
                code="direction_cycle",
                message="方位资料存在循环，相关地点需要核对",
                feature_ids=sorted(cycles),
            )
        )
    return MapLayoutResponse(
        document=result, geometry_hash=geometry_hash(result), problems=problems
    )


def layout(
    document: MapDocument, *, type_traits: dict | None = None
) -> MapLayoutResponse:
    space_ids = {feature.space_id for feature in document.features}
    if document.schema_version == 1 or len(space_ids) <= 1:
        return _layout_single_space(document, type_traits=type_traits)

    placed_by_id = {}
    problems = []
    for space_id in sorted(space_ids):
        features = [item for item in document.features if item.space_id == space_id]
        feature_ids = {item.id for item in features}
        constraints = [
            item
            for item in document.constraints
            if item.subject in feature_ids
            and item.target in feature_ids
            and set(item.via).issubset(feature_ids)
        ]
        local = document.model_copy(
            update={
                "features": features,
                "constraints": constraints,
                "journeys": [],
                "images": [],
                "annotation_bindings": [],
            },
            deep=True,
        )
        result = _layout_single_space(local, type_traits=type_traits)
        placed_by_id.update({item.id: item for item in result.document.features})
        problems.extend(result.problems)

    result_document = document.model_copy(
        update={
            "features": [placed_by_id.get(item.id, item) for item in document.features]
        },
        deep=True,
    )
    return MapLayoutResponse(
        document=result_document,
        geometry_hash=geometry_hash(result_document),
        problems=problems,
    )


def affine_transform(placement: MapImagePlacement, document: MapDocument) -> list[float]:
    features = {f.id: f for f in document.features}
    anchors = placement.anchors
    if len(anchors) != 3 or len({a.feature_id for a in anchors}) != 3:
        raise ValueError("请选择三个不同的地图地点")
    points = []
    for anchor in anchors:
        feature = features.get(anchor.feature_id)
        if (
            not feature
            or feature.kind not in {"location", "landmark"}
            or len(feature.points) != 1
        ):
            raise ValueError("校准锚点必须是已定位地点")
        points.append(feature.points[0])
    x1, x2, x3 = (a.image_x for a in anchors)
    y1, y2, y3 = (a.image_y for a in anchors)
    det = (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)
    world_det = (points[1].x - points[0].x) * (points[2].y - points[0].y) - (
        points[2].x - points[0].x
    ) * (points[1].y - points[0].y)
    span = max(hypot(point.x - points[0].x, point.y - points[0].y) for point in points)
    if abs(det) < 1e-6 or abs(world_det) < 1e-6 * max(1, span * span):
        raise ValueError("三个锚点不能共线或过于接近")

    def solve(values):
        a = (
            (values[1] - values[0]) * (y3 - y1) - (values[2] - values[0]) * (y2 - y1)
        ) / det
        b = (
            (x2 - x1) * (values[2] - values[0]) - (x3 - x1) * (values[1] - values[0])
        ) / det
        return a, b, values[0] - a * x1 - b * y1

    a, c, e = solve([p.x for p in points])
    b, d, f = solve([p.y for p in points])
    return [a, b, c, d, e, f]


def structure_reference_manifest(document: MapDocument) -> list[dict]:
    """Match names to exact normalized pixels in the provider-only reference image."""
    points = [point for feature in document.features for point in feature.points]
    if not points:
        return []
    left, top = min(p.x for p in points) - 40, min(p.y for p in points) - 40
    width = max(p.x for p in points) - left + 40
    height = max(p.y for p in points) - top + 40
    scale = min(984 / width, 728 / height)
    return [
        {
            "reference": f"S{index + 1:03d}",
            "name": feature.label,
            "kind": feature.kind,
            "points": [
                {
                    "x": round((20 + (point.x - left) * scale) / 1024, 6),
                    "y": round((20 + (point.y - top) * scale) / 768, 6),
                }
                for point in feature.points
            ],
        }
        for index, feature in enumerate(
            sorted(document.features, key=lambda item: item.id)
        )
        if feature.points
    ]


def render_structure_png(document: MapDocument) -> bytes:
    """Provider reference marks must be removed from the final generated artwork."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1024, 768), "#f4efe4")
    draw = ImageDraw.Draw(image)
    manifest = structure_reference_manifest(document)
    for item in sorted(manifest, key=lambda item: item["kind"] != "area"):
        xy = [(point["x"] * 1024, point["y"] * 768) for point in item["points"]]
        if item["kind"] == "area":
            draw.polygon(xy, fill="#c6d3b5", outline="#697e54")
        elif item["kind"] in {"river", "road"}:
            draw.line(
                xy, fill="#407aa4" if item["kind"] == "river" else "#92634a", width=5
            )
        else:
            x, y = xy[0]
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill="#49382f")
    for item in manifest:
        point = item["points"][0]
        draw.text(
            (point["x"] * 1024 + 9, point["y"] * 768 + 5),
            item["reference"],
            fill="#49382f",
        )
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
