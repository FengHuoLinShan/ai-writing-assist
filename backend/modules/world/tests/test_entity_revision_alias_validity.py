from modules.world.services.core.entity_revision_service import (
    _snapshot_view,
    diff_revision_snapshots,
)


def test_alias_validity_change_is_visible_in_entity_revision_diff() -> None:
    before = {
        "content_json": {
            "aliases": [
                {
                    "alias": "灰鸦",
                    "type": "identity",
                    "validity": {"start": {"kind": "scene", "id": "scene-1"}},
                    "reviewed_by": "manual",
                }
            ]
        }
    }
    after = {
        "content_json": {
            "aliases": [
                {
                    "alias": "灰鸦",
                    "type": "identity",
                    "validity": {"start": {"kind": "scene", "id": "scene-2"}},
                    "reviewed_by": "manual",
                }
            ]
        }
    }

    assert diff_revision_snapshots(before, after) == ["aliases"]


def test_alias_review_metadata_change_does_not_fake_interval_change() -> None:
    before = {
        "content_json": {
            "aliases": [
                {
                    "alias": "灰鸦",
                    "validity": {"start": {"kind": "scene", "id": "scene-1"}},
                    "reviewed_by": "import",
                }
            ]
        }
    }
    after = {
        "content_json": {
            "aliases": [
                {
                    "alias": "灰鸦",
                    "validity": {"start": {"kind": "scene", "id": "scene-1"}},
                    "reviewed_by": "author",
                }
            ]
        }
    }

    assert diff_revision_snapshots(before, after) == []


def test_entity_history_snapshot_exposes_alias_interval_without_review_metadata() -> None:
    snapshot = _snapshot_view(
        {
            "entity_type": "character",
            "name": "沈砚",
            "status": "canonical",
            "content_json": {
                "aliases": [
                    {
                        "alias": "灰鸦",
                        "type": "identity",
                        "validity": {
                            "start": {"kind": "scene", "id": "scene-1"},
                            "end": None,
                        },
                        "reviewed_by": "manual",
                    }
                ]
            },
        }
    )

    assert snapshot.aliases == ["灰鸦"]
    assert snapshot.alias_details == [
        {
            "alias": "灰鸦",
            "validity": {
                "start": {"kind": "scene", "id": "scene-1"},
                "end": None,
            },
        }
    ]
