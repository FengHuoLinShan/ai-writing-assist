from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_context_routes_hide_recycled_and_missing_projects(
    async_client: AsyncClient,
) -> None:
    created = await async_client.post("/api/projects", json={"title": "Context gate"})
    novel_id = created.json()["id"]
    missing_id = str(uuid.uuid4())

    active = await async_client.post(
        "/api/context/compile",
        json={"novel_id": novel_id, "task": "Compile", "scope": "project"},
    )
    assert active.status_code == 200

    deleted = await async_client.delete(f"/api/projects/{novel_id}")
    assert deleted.status_code == 204

    for blocked_id in (novel_id, missing_id):
        compile_response = await async_client.post(
            "/api/context/compile",
            json={"novel_id": blocked_id, "task": "Compile", "scope": "project"},
        )
        confirm_response = await async_client.post(
            "/api/context/confirm",
            json={
                "novel_id": blocked_id,
                "action": "writing.generate",
                "task": "Confirm",
                "scope": "project",
            },
        )
        maintenance_response = await async_client.post(
            "/api/context/snapshots/maintenance",
            json={"novel_id": blocked_id},
        )
        scene_lens_response = await async_client.post(
            "/api/context/scene-lens",
            json={"novel_id": blocked_id, "scene_id": str(uuid.uuid4())},
        )
        assert compile_response.status_code == 404
        assert confirm_response.status_code == 404
        assert maintenance_response.status_code == 404
        assert scene_lens_response.status_code == 404


@pytest.mark.asyncio
async def test_evidence_grep_http_returns_author_scene_context(
    async_client: AsyncClient,
    monkeypatch,
) -> None:
    created = await async_client.post("/api/projects", json={"title": "RAG context"})
    novel_id = created.json()["id"]
    captured = {}

    async def fake_grep(_db, **kwargs):
        captured.update(kwargs)
        return {
            "hits": [
                {
                    "kind": "manuscript",
                    "title": "第十一章",
                    "snippet": "旧塔铜铃",
                    "chapter_index": 11,
                    "scene_refs": [
                        {
                            "target_type": "outline_scene",
                            "target_id": "scene-11",
                            "scene_index": 11,
                            "scene_title": "旧塔铜铃",
                            "context_summary": "目标：确认密道入口",
                        }
                    ],
                    "writing_relevance": {
                        "kind": "previous_scene",
                        "label": "前序 Scene：可用于核对剧情承接。",
                    },
                }
            ],
            "total": 1,
            "warnings": [],
            "degraded": False,
            "missing_chapters": [],
        }

    monkeypatch.setattr("modules.context.api._grep_novel_evidence", fake_grep)
    response = await async_client.post(
        "/api/context/evidence/grep",
        json={
            "novel_id": novel_id,
            "pattern": "铜铃",
            "visibility": {"mode": "author"},
            "context_scene_id": "scene-current",
        },
    )

    assert response.status_code == 200
    assert captured["context_scene_id"] == "scene-current"
    hit = response.json()["hits"][0]
    assert hit["scene_refs"][0]["scene_title"] == "旧塔铜铃"
    assert hit["writing_relevance"]["kind"] == "previous_scene"
