from unittest.mock import patch

import pytest

from core.errors import ValidationError
from modules.world.services.core.entity_revision_service import (
    _snapshot_view,
    diff_revision_snapshots,
)
from modules.world.validity import validate_changed_alias_intervals


@pytest.mark.asyncio
async def test_retained_alias_interval_rechecks_a_removed_scene_anchor() -> None:
    alias = {
        "alias": "灰鸦",
        "validity": {
            "start": {
                "kind": "scene",
                "id": "d58a3a56-9d6b-45d8-85d6-854c1132b042",
            }
        },
    }
    with patch(
        "modules.world.validity.validate_scene_validity",
        autospec=True,
        side_effect=ValidationError("Scene anchor removed"),
    ) as validate:
        with pytest.raises(ValidationError, match="Scene anchor removed"):
            await validate_changed_alias_intervals(None, "novel-id", [alias])
    validate.assert_awaited_once()


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
