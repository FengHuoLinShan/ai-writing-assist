from decimal import Decimal
from types import SimpleNamespace

from modules.world.map_spatial_advisory_service import (
    _direction_conflicts,
    _intervals_disjoint,
    _journey_key,
)


def _journey(
    *,
    transport="步行",
    traveler=None,
    condition="无门禁",
    minimum=Decimal("2"),
    maximum=Decimal("3"),
    unit="日",
):
    return SimpleNamespace(
        origin="north-gate",
        destination="river-town",
        transport_label=transport,
        transport_type_ref=None,
        transport_type_revision_id=None,
        traveler_type_ref=traveler,
        traveler_type_revision_id="traveler-revision" if traveler else None,
        access_conditions=[
            SimpleNamespace(type_ref=None, type_revision_id=None, label=condition)
        ],
        duration=SimpleNamespace(minimum=minimum, maximum=maximum, unit=unit),
    )


def test_journey_duration_conflict_requires_compatible_mode_traveler_and_conditions():
    base = _journey()
    same_conditions = _journey(minimum=Decimal("5"), maximum=Decimal("6"))
    assert _journey_key(base) == _journey_key(same_conditions)
    assert _intervals_disjoint(base.duration, same_conditions.duration)

    assert _journey_key(base) != _journey_key(_journey(transport="马车"))
    assert _journey_key(base) != _journey_key(_journey(traveler="traveler-a"))
    assert _journey_key(base) != _journey_key(_journey(condition="只在白天通行"))


def test_duration_ranges_need_same_unit_and_proven_non_overlap():
    base = _journey(minimum=Decimal("2"), maximum=Decimal("4"))
    assert not _intervals_disjoint(
        base.duration,
        _journey(minimum=Decimal("4"), maximum=Decimal("6")).duration,
    )
    assert not _intervals_disjoint(
        base.duration,
        _journey(minimum=Decimal("5"), maximum=Decimal("6"), unit="小时").duration,
    )
    assert not _intervals_disjoint(
        base.duration,
        _journey(minimum=None, maximum=None).duration,
    )


def test_opposite_direction_advisory_requires_two_explicit_same_space_claims():
    features = {
        "a": SimpleNamespace(entity_id="entity-a", space_id="main"),
        "b": SimpleNamespace(entity_id="entity-b", space_id="main"),
        "c": SimpleNamespace(entity_id="entity-c", space_id="dream"),
    }
    north = SimpleNamespace(subject="a", target="b", relation="north")
    reverse_north = SimpleNamespace(subject="b", target="a", relation="north")
    consistent_reverse = SimpleNamespace(subject="b", target="a", relation="south")
    cross_space = SimpleNamespace(subject="a", target="c", relation="south")

    assert len(_direction_conflicts(features, [north, reverse_north])) == 1
    assert _direction_conflicts(features, [north, consistent_reverse]) == []
    assert _direction_conflicts(features, [north, cross_space]) == []
    assert _direction_conflicts(features, [north]) == []
