from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.smart_dedup import SmartDedupService

pytestmark = [pytest.mark.asyncio]


async def test_smart_dedup_scan_api_enqueues_task(async_client: AsyncClient) -> None:
    created = await async_client.post("/api/projects", json={"title": "去重测试"})
    assert created.status_code == 201
    project_id = created.json()["id"]

    resp = await async_client.post(
        f"/api/projects/{project_id}/smart-dedup/scan",
        json={"scopes": ["world_entity", "plot_thread"], "max_suggestions": 12},
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["task_id"]
    assert data["status"] == "pending"


async def test_smart_dedup_apply_dispatches_by_asset_type(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, list] = {"world": [], "outline": []}

    async def fake_world_apply(db, novel_id, *, confirmed, suggestions):
        calls["world"].extend(suggestions)
        return {"applied": len(suggestions), "skipped": 0, "warnings": []}

    async def fake_outline_apply(db, novel_id, *, confirmed, suggestions):
        calls["outline"].extend(suggestions)
        return {"applied": len(suggestions), "skipped": 0, "warnings": []}

    monkeypatch.setattr(
        "modules.world.facade.apply_entity_fusion",
        fake_world_apply,
    )
    monkeypatch.setattr(
        "modules.outline.facade.apply_structure_dedup",
        fake_outline_apply,
    )

    result = await SmartDedupService().apply(
        db_session,
        novel_id="project-1",
        confirmed=True,
        suggestions=[
            {
                "asset_type": "world_entity",
                "action": "alias_only",
                "source_asset_id": "e1",
                "target_asset_id": "e2",
                "alias": "别名",
            },
            {
                "asset_type": "plot_thread",
                "action": "deprecate_duplicate",
                "source_asset_id": "t1",
                "target_asset_id": "t2",
            },
        ],
    )

    assert result["applied"] == 2
    assert calls["world"] == [
        {
            "action": "alias_only",
            "source_entity_id": "e1",
            "target_entity_id": "e2",
            "alias": "别名",
            "allow_canonical_merge": False,
        }
    ]
    assert calls["outline"][0]["asset_type"] == "plot_thread"
