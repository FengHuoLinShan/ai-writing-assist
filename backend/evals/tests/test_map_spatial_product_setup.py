"""SQLite product-API behavior for the synthetic map evaluation setup."""

from __future__ import annotations

import pytest

from evals.map_spatial import ALLOWED_GENRES
from evals.map_spatial_control import _setup_family_via_client, _validated_setup
from evals.tests.test_map_spatial import _fixture


@pytest.mark.asyncio
async def test_setup_family_uses_real_project_draft_and_scene_apis(
    tmp_path, monkeypatch, async_client, db_session
):
    root, _, matrix = _fixture(tmp_path, monkeypatch)
    family = next(
        row
        for row in matrix["families"]
        if row["genre"] == ALLOWED_GENRES[0] and row["split"] == "development"
    )
    source = {
        "family_id": family["family_id"],
        "genre": family["genre"],
        "split": "development",
        "project_setup": {"chapter_index": 1},
        "cases": [
            {
                "case_id": f"{family['family_id']}-p{index}",
                "source_excerpt": f"合成地图来源片段 {index}：门外有一座钟楼。",
            }
            for index in range(1, 6)
        ],
    }
    monkeypatch.setattr(
        "evals.map_spatial_control._load_family_source",
        lambda *_args, **_kwargs: source,
    )

    result = await _setup_family_via_client(
        private_root=root,
        family_id=family["family_id"],
        client=async_client,
    )

    assert result["status"] == "completed"
    setup, scopes = _validated_setup(root, family, source)
    assert setup["project_id"] == result["novel_id"]
    assert len(setup["scenes"]) == 5
    assert len({scope["scene_id"] for scope in scopes.values()}) == 5
    from evals.map_spatial import scene_source_refs

    for case in source["cases"]:
        scope = scopes[case["case_id"]]
        refs = await scene_source_refs(
            db_session,
            scope["novel_id"],
            scope["scene_id"],
            scope["chapter_index"],
            case["source_excerpt"],
        )
        assert len(refs) == 1
        assert refs[0]["content_mode"] == "canonical"
        assert refs[0]["start_offset"] < refs[0]["end_offset"]
        assert refs[0]["source_hash"] == setup["scenes"][case["case_id"]]["source_hash"]
