from uuid import uuid4

import pytest

from scripts.curate_character_profiles import ProfileCuration, pending_fields


def test_curated_fills_are_idempotent_and_preserve_author_edits():
    profile = ProfileCuration.model_validate(
        {
            "character_id": str(uuid4()),
            "name": "人物",
            "fills": [
                {
                    "field": "appearance",
                    "value": "黑发",
                    "sources": [
                        {
                            "quote": "黑发",
                            "source_ref": {
                                "draft_id": str(uuid4()),
                                "chapter_index": 1,
                                "version_number": 1,
                                "content_mode": "canonical",
                                "start_offset": 0,
                                "end_offset": 2,
                                "source_hash": "a" * 64,
                                "range_hash": "b" * 64,
                            },
                        }
                    ],
                }
            ],
        }
    )
    assert pending_fields({"appearance": None}, profile) == {"appearance": "黑发"}
    assert pending_fields({"appearance": "黑发"}, profile) == {}
    with pytest.raises(ValueError, match="Existing author field"):
        pending_fields({"appearance": "作者刚修改的外貌"}, profile)
    profile.fills.append(profile.fills[0])
    with pytest.raises(ValueError, match="Duplicate field"):
        pending_fields({}, profile)
