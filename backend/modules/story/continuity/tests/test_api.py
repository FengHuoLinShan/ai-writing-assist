from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "suffix", "params"),
    [
        ("GET", "/panorama", {"chapter_index": 1}),
        ("GET", "/events", {}),
        ("GET", "/events/entity-1/timeline", {}),
        ("POST", "/snapshots/capture", {"chapter_index": 1}),
        ("GET", "/snapshots", {}),
        ("POST", "/rebuild", {"from_chapter": 1}),
        ("GET", "/status", {}),
        ("GET", "/scene-checkpoints/history", {"scene_id": "scene-1"}),
    ],
)
async def test_memory_api_hides_recycled_project(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
    method: str,
    suffix: str,
    params: dict[str, int],
) -> None:
    project = await db_session.get(Project, uuid.UUID(test_project_id))
    project.deleted_at = datetime.now(UTC)
    await db_session.flush()

    response = await async_client.request(
        method,
        f"/api/novels/{test_project_id}/memories{suffix}",
        params=params,
    )

    assert response.status_code == 404


# ============================================================
# P2-A A4：Scene checkpoint 历史版本列表端点（facade DI 替身验证）
# ============================================================


def _history_row(**overrides):
    row = {
        "checkpoint_id": "11111111-1111-1111-1111-111111111111",
        "dimension": "entities",
        "chapter_index": 2,
        "version": 1,
        "scene_sequence": 3,
        "is_current": True,
        "has_field_provenance": True,
        "created_at": datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC),
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_scene_checkpoint_history_maps_facade_rows_to_author_summaries(
    async_client: AsyncClient,
    test_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """facade 摘要行映射为作者语言；历史行不被洗成当前表述。"""
    from modules.story.continuity import facade as continuity_facade

    calls = []

    class _FacadeResult:
        def model_dump(self):
            return {
                "items": [
                    _history_row(
                        checkpoint_id="22222222-2222-2222-2222-222222222222",
                        is_current=False,
                        has_field_provenance=False,
                        version=1,
                    ),
                    _history_row(),
                ]
            }

    async def fake_list(db, novel_id, scene_id):
        calls.append((novel_id, scene_id))
        return _FacadeResult()

    monkeypatch.setattr(
        continuity_facade,
        "list_scene_checkpoints",
        fake_list,
        raising=False,
    )

    response = await async_client.get(
        f"/api/novels/{test_project_id}/memories/scene-checkpoints/history",
        params={"scene_id": "scene-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert calls == [(test_project_id, "scene-1")]
    assert payload["scene_id"] == "scene-1"
    assert payload["total"] == 2
    current, history = payload["items"][1], payload["items"][0]
    assert current["label"] == "当前版本"
    assert current["is_current"] is True
    assert current["has_field_provenance"] is True
    assert current["chapter_index"] == 2
    assert current["version"] == 1
    assert current["scene_sequence"] == 3
    # 旧版本语义清楚：历史行标注为历史版本，且不带字段级来源能力时如实透传。
    assert history["label"] == "历史版本"
    assert history["is_current"] is False
    assert history["has_field_provenance"] is False
    assert history["checkpoint_id"] == "22222222-2222-2222-2222-222222222222"


@pytest.mark.asyncio
async def test_scene_checkpoint_history_gate_precedes_facade(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """项目门禁先行：回收项目返回 404 且不触达 facade。"""
    from modules.story.continuity import facade as continuity_facade

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("facade must not be reached for recycled projects")

    monkeypatch.setattr(
        continuity_facade,
        "list_scene_checkpoints",
        forbidden,
        raising=False,
    )
    project = await db_session.get(Project, uuid.UUID(test_project_id))
    project.deleted_at = datetime.now(UTC)
    await db_session.flush()

    response = await async_client.get(
        f"/api/novels/{test_project_id}/memories/scene-checkpoints/history",
        params={"scene_id": "scene-1"},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_scene_checkpoint_history_requires_scene_id(
    async_client: AsyncClient,
    test_project_id: str,
) -> None:
    response = await async_client.get(
        f"/api/novels/{test_project_id}/memories/scene-checkpoints/history",
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_scene_checkpoint_history_accepts_plain_list_and_orm_aliases(
    async_client: AsyncClient,
    test_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """facade 返回裸列表 + ORM 同义键（id/version_number/scene_index）时同样可映射。

    与 A3 当前实现（scene_state_view.list_scene_checkpoints）对齐：无章节锚的
    行 chapter_index 为 None，created_at 为 ISO 字符串。
    """
    from modules.story.continuity import facade as continuity_facade

    async def fake_list(_db, _novel_id, _scene_id):
        return [
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "dimension": "entities",
                "version_number": 4,
                "scene_index": 7,
                "chapter_index": None,
                "is_current": False,
                "has_field_provenance": False,
                "created_at": "2026-10-07T12:00:00+00:00",
            }
        ]

    monkeypatch.setattr(
        continuity_facade,
        "list_scene_checkpoints",
        fake_list,
        raising=False,
    )

    response = await async_client.get(
        f"/api/novels/{test_project_id}/memories/scene-checkpoints/history",
        params={"scene_id": "scene-1"},
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["checkpoint_id"] == "33333333-3333-3333-3333-333333333333"
    assert item["version"] == 4
    assert item["scene_sequence"] == 7
    assert item["chapter_index"] is None
    assert item["label"] == "历史版本"
    assert item["created_at"] == "2026-10-07T12:00:00Z"


@pytest.mark.asyncio
async def test_scene_checkpoint_history_reaches_real_facade(
    async_client: AsyncClient,
    test_project_id: str,
) -> None:
    """A3 落地后端点直连真实 facade：未知 Scene 显式 404，证明导入路径可用。"""
    response = await async_client.get(
        f"/api/novels/{test_project_id}/memories/scene-checkpoints/history",
        params={"scene_id": "00000000-0000-0000-0000-000000000000"},
    )

    assert response.status_code == 404
