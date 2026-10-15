import json

import pytest

from modules.assistant import evidence_tools


@pytest.mark.asyncio
async def test_precise_map_queries_do_not_treat_other_journeys_or_positions_as_answers(
    monkeypatch,
):
    async def brief(ctx, query):
        return {
            "items": [
                {
                    "evidence_id": "map-evidence",
                    "snippet": json.dumps(
                        {
                            "行程与通行条件": [
                                {"from": "黑港", "to": "白塔", "duration": "三天"}
                            ],
                            "移动对象最后位置": [
                                {"object": "远行船", "location": "黑港"}
                            ],
                        }
                    ),
                }
            ]
        }

    monkeypatch.setattr(evidence_tools, "map_spatial_brief", brief)
    assert (await evidence_tools.map_journey(None, "黑港", "白塔"))["status"] == "known"
    assert (await evidence_tools.map_journey(None, "白塔", "黑港"))["status"] == "unknown"
    assert (await evidence_tools.map_object_position(None, "远行船"))["status"] == "known"
    assert (await evidence_tools.map_object_position(None, "青舟"))["status"] == "unknown"
    for version in ("1", "2", "3", "4", "5"):
        assert not {
            "map_journey",
            "map_object_position",
            "map_spatial_advisories",
        }.intersection(
            tool.name
            for tool in evidence_tools.author_read_tools(allow_web=False, version=version)
        )
    assert {"map_journey", "map_object_position", "map_spatial_advisories"}.issubset(
        tool.name
        for tool in evidence_tools.author_read_tools(allow_web=False, version="6")
    )
