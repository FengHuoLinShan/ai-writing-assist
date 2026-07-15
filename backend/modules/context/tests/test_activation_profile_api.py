import uuid

import pytest
from httpx import AsyncClient


def _profile_payload(novel_id: str, target_id: str) -> dict:
    return {
        "novel_id": novel_id,
        "profile_key": "writing.api",
        "name": "API 规则",
        "applicable_actions_json": ["writing.scene.generate"],
        "rules_json": [
            {
                "rule_id": "north",
                "name": "北境资料",
                "scope": {
                    "actions": ["writing.scene.generate"],
                    "modes": ["author_safe"],
                    "match_sources": ["task_text"],
                },
                "match": {
                    "positive_terms": ["北境"],
                    "negative_terms": [],
                    "positive_logic": "any",
                    "negative_logic": "any",
                    "mode": "normalized_substring",
                },
                "select": {
                    "target_refs": [
                        {
                            "target_type": "core_entity",
                            "target_id": target_id,
                            "target_path": "",
                        }
                    ],
                    "expand_page_links": False,
                    "relation_types": [],
                    "max_depth": 0,
                },
                "rank": {"priority": 700, "top_k": 12, "token_cap": 1200},
            }
        ],
    }


@pytest.mark.asyncio
async def test_activation_profile_api_lifecycle_and_structured_preview(
    async_client: AsyncClient,
) -> None:
    project = await async_client.post("/api/projects", json={"title": "规则 API"})
    novel_id = project.json()["id"]
    created = await async_client.post(
        "/api/context/activation-profiles",
        json=_profile_payload(novel_id, str(uuid.uuid4())),
    )
    assert created.status_code == 201
    profile = created.json()
    assert profile["status"] == "draft"

    listed = await async_client.get(
        "/api/context/activation-profiles",
        params={"novel_id": novel_id},
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == profile["id"]

    preview = await async_client.post(
        "/api/context/activation-preview",
        json={
            "novel_id": novel_id,
            "profile_id": profile["id"],
            "action": "writing.scene.generate",
            "task_text": "描写北境商路",
        },
    )
    assert preview.status_code == 200
    trace = preview.json()
    assert trace["profile"]["status"] == "draft"
    assert trace["excluded_items"][0]["excluded_reason"] == "target_missing"

    updated = await async_client.patch(
        f"/api/context/activation-profiles/{profile['id']}",
        params={"novel_id": novel_id},
        json={"base_version_number": 1, "name": "API 规则二版"},
    )
    assert updated.status_code == 200
    assert updated.json()["version_number"] == 2

    conflict = await async_client.patch(
        f"/api/context/activation-profiles/{profile['id']}",
        params={"novel_id": novel_id},
        json={"base_version_number": 1, "name": "过期写入"},
    )
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_activation_profile_api_is_novel_scoped_and_legacy_get_survives(
    async_client: AsyncClient,
) -> None:
    first = await async_client.post("/api/projects", json={"title": "项目一"})
    second = await async_client.post("/api/projects", json={"title": "项目二"})
    novel_id = first.json()["id"]
    other_id = second.json()["id"]
    created = await async_client.post(
        "/api/context/activation-profiles",
        json=_profile_payload(novel_id, str(uuid.uuid4())),
    )
    profile_id = created.json()["id"]

    hidden = await async_client.patch(
        f"/api/context/activation-profiles/{profile_id}",
        params={"novel_id": other_id},
        json={"base_version_number": 1, "name": "越权"},
    )
    assert hidden.status_code == 404

    legacy = await async_client.get(
        "/api/context/activation-preview",
        params={"novel_id": novel_id, "top_k": 10, "depth": 2},
    )
    assert legacy.status_code == 200
    assert legacy.json()["profile"] is None
    assert legacy.json()["top_k"] == 10
