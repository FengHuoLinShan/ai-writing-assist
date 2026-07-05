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


async def test_smart_dedup_scan_sets_recommended_primary(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_world_suggest(*args, **kwargs):
        return {
            "total_entities_scanned": 2,
            "suggestion_count": 1,
            "suggestions": [
                {
                    "action": "alias_only",
                    "source_entity_id": "source-world",
                    "source_entity_name": "旧称",
                    "source_status": "candidate",
                    "target_entity_id": "target-world",
                    "target_entity_name": "主体世界对象",
                    "target_status": "canonical",
                    "confidence": 0.91,
                    "reason": "更像别名",
                }
            ],
        }

    async def fake_outline_suggest(*args, **kwargs):
        return {
            "scanned_counts": {"plot_thread": 2},
            "suggestion_count": 1,
            "suggestions": [
                {
                    "asset_type": "plot_thread",
                    "action": "merge",
                    "source_asset_id": "source-outline",
                    "source_title": "重复剧情线",
                    "target_asset_id": "target-outline",
                    "target_title": "主体剧情线",
                }
            ],
        }

    monkeypatch.setattr(
        "modules.world.facade.suggest_entity_fusion",
        fake_world_suggest,
    )
    monkeypatch.setattr(
        "modules.outline.facade.suggest_structure_dedup",
        fake_outline_suggest,
    )

    result = await SmartDedupService().scan(
        db_session,
        novel_id="project-1",
        scopes=["world_entity", "plot_thread"],
    )

    world, outline = result["suggestions"]
    assert world["recommended_primary_asset_id"] == "target-world"
    assert world["recommended_primary_title"] == "主体世界对象"
    assert outline["recommended_primary_asset_id"] == "target-outline"
    assert outline["recommended_primary_title"] == "主体剧情线"


async def test_smart_dedup_scan_marks_alias_derived_title_conflict_high_risk(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_world_suggest(*args, **kwargs):
        return {
            "total_entities_scanned": 2,
            "suggestion_count": 1,
            "suggestions": [
                {
                    "action": "merge",
                    "source_entity_id": "shen-lan",
                    "source_entity_name": "沈澜",
                    "source_status": "draft",
                    "target_entity_id": "mirror-restorer",
                    "target_entity_name": "北港镜修师",
                    "target_status": "canonical",
                    "recommended_primary_entity_id": "mirror-restorer",
                    "recommended_primary_entity_name": "北港镜修师",
                    "confidence": 0.99,
                    "match_method": "alias_name_match",
                    "reason": "别名命中",
                }
            ],
        }

    async def fake_outline_suggest(*args, **kwargs):
        return {"scanned_counts": {}, "suggestion_count": 0, "suggestions": []}

    monkeypatch.setattr(
        "modules.world.facade.suggest_entity_fusion",
        fake_world_suggest,
    )
    monkeypatch.setattr(
        "modules.outline.facade.suggest_structure_dedup",
        fake_outline_suggest,
    )

    result = await SmartDedupService().scan(
        db_session,
        novel_id="project-1",
        scopes=["world_entity"],
    )

    suggestion = result["suggestions"][0]
    assert suggestion["requires_manual_confirmation"] is True
    assert suggestion["risk_level"] == "high"
    assert suggestion["risk_reason"] == "alias_derived_title_conflict"
