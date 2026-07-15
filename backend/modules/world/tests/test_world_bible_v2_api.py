import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_page_template_and_section_api_workflow(
    async_client: AsyncClient,
) -> None:
    project = await async_client.post("/api/projects", json={"title": "世界书 V2"})
    novel_id = project.json()["id"]
    templates = await async_client.get(
        "/api/world/bible/page-templates",
        params={"novel_id": novel_id},
    )
    assert templates.status_code == 200
    assert any(
        item["template_key"] == "world_basic"
        for item in templates.json()["items"]
    )

    created = await async_client.post(
        "/api/world/bible/page-templates",
        json={
            "novel_id": novel_id,
            "template_key": "trade_guide",
            "name": "贸易指南",
            "default_sections_json": [
                {
                    "section_id": "currency",
                    "section_type": "markdown",
                    "title": "货币与交换",
                    "body_markdown": "",
                    "sort_order": 10,
                    "linked_asset_ref_hashes": [],
                    "projection_policy": "eligible",
                    "sensitivity_hint": "author_safe",
                }
            ],
        },
    )
    assert created.status_code == 201
    template = created.json()

    draft_response = await async_client.post(
        "/api/world/bible/drafts",
        json={
            "novel_id": novel_id,
            "title": "北境贸易",
            "page_type": "background",
        },
    )
    assert draft_response.status_code == 201
    draft = draft_response.json()
    applied = await async_client.post(
        f"/api/world/bible/drafts/{draft['id']}/apply-template",
        params={"novel_id": novel_id},
        json={"template_key": "trade_guide", "replace_sections": True},
    )
    assert applied.status_code == 200
    assert applied.json()["sections_json"][0]["section_id"] == "currency"

    published = await async_client.post(
        f"/api/world/bible/drafts/{draft['id']}/publish",
        params={"novel_id": novel_id},
    )
    assert published.status_code == 200
    assert published.json()["sections_json"][0]["title"] == "货币与交换"
    assert published.json()["template_key"] == "trade_guide"

    updated = await async_client.patch(
        f"/api/world/bible/page-templates/{template['id']}",
        params={"novel_id": novel_id},
        json={"base_version_number": 1, "name": "贸易指南二版"},
    )
    assert updated.status_code == 200
    assert updated.json()["version_number"] == 2
    restored = await async_client.post(
        f"/api/world/bible/page-templates/{template['id']}/revisions/1/restore-draft",
        params={"novel_id": novel_id},
    )
    assert restored.status_code == 200
    assert restored.json()["version_number"] == 3
    assert restored.json()["name"] == "贸易指南"


@pytest.mark.asyncio
async def test_page_template_api_rejects_prompt_fields_and_cross_novel_access(
    async_client: AsyncClient,
) -> None:
    first = await async_client.post("/api/projects", json={"title": "项目一"})
    second = await async_client.post("/api/projects", json={"title": "项目二"})
    novel_id = first.json()["id"]
    other_id = second.json()["id"]
    unsafe = await async_client.post(
        "/api/world/bible/page-templates",
        json={
            "novel_id": novel_id,
            "template_key": "unsafe_template",
            "name": "危险模板",
            "sections_schema_json": {"prompt": "ignore previous"},
        },
    )
    assert unsafe.status_code == 422

    created = await async_client.post(
        "/api/world/bible/page-templates",
        json={
            "novel_id": novel_id,
            "template_key": "safe_template",
            "name": "安全模板",
        },
    )
    template_id = created.json()["id"]
    hidden = await async_client.patch(
        f"/api/world/bible/page-templates/{template_id}",
        params={"novel_id": other_id},
        json={"base_version_number": 1, "name": "越权"},
    )
    assert hidden.status_code == 404
