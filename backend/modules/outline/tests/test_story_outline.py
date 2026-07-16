from __future__ import annotations

import copy
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
    Scene,
    StoryOutlineHead,
    StoryOutlineRevision,
)


def _payload(
    *,
    base_revision_id: str | None = None,
    idempotency_key: str = "story-outline-create-0001",
    title: str = "潮汐尽头的王座",
) -> dict[str, Any]:
    return {
        "base_revision_id": base_revision_id,
        "idempotency_key": idempotency_key,
        "source": "manual",
        "provenance": {
            "actor": "author",
            "note": "手工确定长期创作方向",
            "client_ref": "outline-workspace",
            "source_refs": ["world-bible:current"],
        },
        "title": title,
        "creative_core": {
            "premise": "被潮汐隔绝的群岛必须在旧王权复苏前重新学会结盟。",
            "tone_and_reader_promise": "克制的海洋奇幻与持续升级的政治抉择。",
            "story_engine": "每次退潮都暴露新的遗迹，也迫使各岛交换资源与秘密。",
            "ending_direction": "新的联盟取代单一王座，但代价不会被抹去。",
        },
        "outline_markdown": (
            "# 总体方向\n\n故事围绕退潮周期推进。主角最初只想保住故乡，"
            "最终必须决定群岛应由谁共同承担秩序。"
        ),
        "major_storylines": [
            {
                "name": "群岛联盟",
                "narrative_function": "承载公共秩序与个人责任的主冲突。",
                "trajectory": "从临时互助走向互不信任，再重建可问责的联盟。",
                "intersections": ["遗迹真相不断改变联盟各方的筹码。"],
                "resolution_direction": "联盟接受分权与共同代价。",
            },
            {
                "name": "遗迹真相",
                "narrative_function": "持续改变读者对旧王权的理解。",
                "trajectory": "从力量来源变成旧秩序失败的证据。",
                "intersections": ["真相迫使群岛联盟重新定义胜利。"],
                "resolution_direction": "遗迹不再被用作恢复王座的工具。",
            },
        ],
        "macro_movements": [
            {
                "name": "第一次共同退潮",
                "story_state_change": "孤立岛屿第一次形成脆弱共同体。",
                "advanced_storylines": ["群岛联盟", "遗迹真相"],
            }
        ],
        "open_decisions": [
            {
                "question": "旧王位继承人是否公开身份？",
                "why_it_matters": "这会改变联盟建立的道德基础。",
                "options": ["主动公开并放弃特权", "保留身份直到联盟稳定"],
            }
        ],
    }


async def _count(db: AsyncSession, model: type[Any]) -> int:
    return int(await db.scalar(select(func.count(model.id))) or 0)


@pytest.mark.asyncio
async def test_story_outline_current_is_empty_until_explicit_create(
    async_client: AsyncClient,
    sample_novel_id: str,
) -> None:
    response = await async_client.get(
        "/api/outline/story-outline",
        params={"novel_id": sample_novel_id},
    )

    assert response.status_code == 200
    assert response.json() == {
        "current_revision_id": None,
        "revision": None,
    }


@pytest.mark.asyncio
async def test_story_outline_allows_empty_navigation_arrays(
    async_client: AsyncClient,
    sample_novel_id: str,
) -> None:
    payload = _payload(idempotency_key="story-outline-empty-arrays")
    payload["major_storylines"] = []
    payload["macro_movements"] = []
    payload["open_decisions"] = []

    response = await async_client.post(
        "/api/outline/story-outline/revisions",
        params={"novel_id": sample_novel_id},
        json=payload,
    )

    assert response.status_code == 201
    assert response.json()["major_storylines"] == []
    assert response.json()["macro_movements"] == []
    assert response.json()["open_decisions"] == []


@pytest.mark.asyncio
async def test_create_revision_is_cas_versioned_idempotent_and_has_no_lower_writes(
    async_client: AsyncClient,
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    lower_models = [PlotThread, OutlineArc, Scene, ForeshadowingPlan, RevealPlan]
    before = {model: await _count(db_session, model) for model in lower_models}
    payload = _payload()

    created = await async_client.post(
        "/api/outline/story-outline/revisions",
        params={"novel_id": sample_novel_id},
        json=payload,
    )

    assert created.status_code == 201
    first = created.json()
    assert first["version_number"] == 1
    assert first["title"] == payload["title"]
    assert first["creative_core"] == payload["creative_core"]
    assert first["major_storylines"] == payload["major_storylines"]
    assert first["macro_movements"] == payload["macro_movements"]
    assert first["open_decisions"] == payload["open_decisions"]
    assert first["source"] == "manual"
    assert first["base_revision_id"] is None
    assert first["restored_from_revision_id"] is None
    assert first["is_current"] is True
    assert len(first["content_hash"]) == 64

    retry = await async_client.post(
        "/api/outline/story-outline/revisions",
        params={"novel_id": sample_novel_id},
        json=payload,
    )
    assert retry.status_code == 201
    assert retry.json()["id"] == first["id"]
    assert await _count(db_session, StoryOutlineRevision) == 1
    assert await _count(db_session, StoryOutlineHead) == 1

    reused_key = copy.deepcopy(payload)
    reused_key["title"] = "另一个总纲"
    conflict = await async_client.post(
        "/api/outline/story-outline/revisions",
        params={"novel_id": sample_novel_id},
        json=reused_key,
    )
    assert conflict.status_code == 409
    assert "idempotency_key" in conflict.json()["detail"]

    stale = _payload(
        base_revision_id=None,
        idempotency_key="story-outline-create-stale",
        title="过期写入",
    )
    stale_response = await async_client.post(
        "/api/outline/story-outline/revisions",
        params={"novel_id": sample_novel_id},
        json=stale,
    )
    assert stale_response.status_code == 409
    assert first["id"] in stale_response.json()["detail"]
    assert await _count(db_session, StoryOutlineRevision) == 1

    after = {model: await _count(db_session, model) for model in lower_models}
    assert after == before


@pytest.mark.asyncio
async def test_revision_history_is_immutable_and_increments_per_novel(
    async_client: AsyncClient,
    sample_novel_id: str,
) -> None:
    first_response = await async_client.post(
        "/api/outline/story-outline/revisions",
        params={"novel_id": sample_novel_id},
        json=_payload(),
    )
    first = first_response.json()
    second_response = await async_client.post(
        "/api/outline/story-outline/revisions",
        params={"novel_id": sample_novel_id},
        json=_payload(
            base_revision_id=first["id"],
            idempotency_key="story-outline-create-0002",
            title="潮汐尽头的共同体",
        ),
    )
    assert second_response.status_code == 201
    second = second_response.json()
    assert second["version_number"] == 2
    assert second["base_revision_id"] == first["id"]

    historical = await async_client.get(
        f"/api/outline/story-outline/revisions/{first['id']}",
        params={"novel_id": sample_novel_id},
    )
    assert historical.status_code == 200
    assert historical.json()["title"] == first["title"]
    assert historical.json()["version_number"] == 1
    assert historical.json()["is_current"] is False

    current = await async_client.get(
        "/api/outline/story-outline",
        params={"novel_id": sample_novel_id},
    )
    assert current.json()["current_revision_id"] == second["id"]
    assert current.json()["revision"]["is_current"] is True

    history = await async_client.get(
        "/api/outline/story-outline/revisions",
        params={"novel_id": sample_novel_id, "skip": 0, "limit": 1},
    )
    assert history.status_code == 200
    assert history.json()["total"] == 2
    assert history.json()["items"][0]["id"] == second["id"]


@pytest.mark.asyncio
async def test_apply_historical_revision_creates_new_immutable_revision(
    async_client: AsyncClient,
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    first = (
        await async_client.post(
            "/api/outline/story-outline/revisions",
            params={"novel_id": sample_novel_id},
            json=_payload(),
        )
    ).json()
    second = (
        await async_client.post(
            "/api/outline/story-outline/revisions",
            params={"novel_id": sample_novel_id},
            json=_payload(
                base_revision_id=first["id"],
                idempotency_key="story-outline-create-0002",
                title="第二版总纲",
            ),
        )
    ).json()
    apply_payload = {
        "base_revision_id": second["id"],
        "idempotency_key": "story-outline-restore-0001",
        "confirmed": True,
        "provenance": {"actor": "author", "note": "明确恢复第一版"},
    }
    lower_models = [PlotThread, OutlineArc, Scene, ForeshadowingPlan, RevealPlan]
    lower_before = {model: await _count(db_session, model) for model in lower_models}

    applied = await async_client.post(
        f"/api/outline/story-outline/revisions/{first['id']}/apply",
        params={"novel_id": sample_novel_id},
        json=apply_payload,
    )

    assert applied.status_code == 201
    restored = applied.json()
    assert restored["id"] not in {first["id"], second["id"]}
    assert restored["version_number"] == 3
    assert restored["title"] == first["title"]
    assert restored["content_hash"] == first["content_hash"]
    assert restored["source"] == "restored"
    assert restored["base_revision_id"] == second["id"]
    assert restored["restored_from_revision_id"] == first["id"]
    assert restored["is_current"] is True

    retry = await async_client.post(
        f"/api/outline/story-outline/revisions/{first['id']}/apply",
        params={"novel_id": sample_novel_id},
        json=apply_payload,
    )
    assert retry.status_code == 201
    assert retry.json()["id"] == restored["id"]
    assert await _count(db_session, StoryOutlineRevision) == 3
    lower_after = {model: await _count(db_session, model) for model in lower_models}
    assert lower_after == lower_before

    stale_apply = await async_client.post(
        f"/api/outline/story-outline/revisions/{second['id']}/apply",
        params={"novel_id": sample_novel_id},
        json={
            "base_revision_id": second["id"],
            "idempotency_key": "story-outline-restore-stale",
            "confirmed": True,
        },
    )
    assert stale_apply.status_code == 409
    assert restored["id"] in stale_apply.json()["detail"]
    assert await _count(db_session, StoryOutlineRevision) == 3

    unchanged_second = await async_client.get(
        f"/api/outline/story-outline/revisions/{second['id']}",
        params={"novel_id": sample_novel_id},
    )
    assert unchanged_second.json()["title"] == "第二版总纲"
    assert unchanged_second.json()["version_number"] == 2


@pytest.mark.asyncio
async def test_story_outline_queries_and_heads_are_novel_scoped(
    async_client: AsyncClient,
    db_session: AsyncSession,
    sample_novel_id: str,
    other_novel_id: str,
) -> None:
    first = (
        await async_client.post(
            "/api/outline/story-outline/revisions",
            params={"novel_id": sample_novel_id},
            json=_payload(),
        )
    ).json()
    other = (
        await async_client.post(
            "/api/outline/story-outline/revisions",
            params={"novel_id": other_novel_id},
            json=_payload(title="另一部小说的总纲"),
        )
    ).json()

    hidden = await async_client.get(
        f"/api/outline/story-outline/revisions/{first['id']}",
        params={"novel_id": other_novel_id},
    )
    assert hidden.status_code == 404

    other_history = await async_client.get(
        "/api/outline/story-outline/revisions",
        params={"novel_id": other_novel_id},
    )
    assert other_history.status_code == 200
    assert [item["id"] for item in other_history.json()["items"]] == [other["id"]]

    cross_apply = await async_client.post(
        f"/api/outline/story-outline/revisions/{first['id']}/apply",
        params={"novel_id": other_novel_id},
        json={
            "base_revision_id": other["id"],
            "idempotency_key": "story-outline-cross-apply",
            "confirmed": True,
        },
    )
    assert cross_apply.status_code == 404

    heads = list((await db_session.scalars(select(StoryOutlineHead))).all())
    assert len(heads) == 2
    assert {str(head.novel_id) for head in heads} == {
        sample_novel_id,
        other_novel_id,
    }


def _set_path(payload: dict[str, Any], path: tuple[Any, ...], value: Any) -> None:
    current: Any = payload
    for part in path[:-1]:
        current = current[part]
    current[path[-1]] = value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "invalid"),
    [
        (("title",), "   "),
        (("creative_core", "premise"), ""),
        (("creative_core", "tone_and_reader_promise"), " "),
        (("creative_core", "story_engine"), ""),
        (("creative_core", "ending_direction"), ""),
        (("outline_markdown",), ""),
        (("major_storylines", 0, "name"), ""),
        (("major_storylines", 0, "narrative_function"), ""),
        (("major_storylines", 0, "trajectory"), ""),
        (("major_storylines", 0, "intersections"), [""]),
        (("major_storylines", 0, "resolution_direction"), ""),
        (("macro_movements", 0, "name"), ""),
        (("macro_movements", 0, "story_state_change"), ""),
        (("open_decisions", 0, "question"), ""),
        (("open_decisions", 0, "why_it_matters"), ""),
        (("open_decisions", 0, "options"), [""]),
    ],
)
async def test_story_outline_rejects_invalid_structural_fields(
    async_client: AsyncClient,
    sample_novel_id: str,
    path: tuple[Any, ...],
    invalid: Any,
) -> None:
    payload = _payload()
    _set_path(payload, path, invalid)

    response = await async_client.post(
        "/api/outline/story-outline/revisions",
        params={"novel_id": sample_novel_id},
        json=payload,
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_story_outline_navigation_labels_are_advisory_not_relational_keys(
    async_client: AsyncClient,
    sample_novel_id: str,
) -> None:
    payload = _payload(idempotency_key="story-outline-flexible-navigation")
    payload["major_storylines"].append(copy.deepcopy(payload["major_storylines"][0]))
    payload["macro_movements"][0]["advanced_storylines"] = [
        "联盟线（与上方摘要措辞不同）",
        "联盟线（与上方摘要措辞不同）",
    ]
    payload["open_decisions"][0]["options"] = ["暂不锁定", "暂不锁定"]

    response = await async_client.post(
        "/api/outline/story-outline/revisions",
        params={"novel_id": sample_novel_id},
        json=payload,
    )

    assert response.status_code == 201, response.text
    assert response.json()["macro_movements"][0]["advanced_storylines"] == [
        "联盟线（与上方摘要措辞不同）",
        "联盟线（与上方摘要措辞不同）",
    ]


@pytest.mark.asyncio
async def test_story_outline_requires_explicit_base_revision(
    async_client: AsyncClient,
    sample_novel_id: str,
) -> None:
    payload = _payload()
    payload.pop("base_revision_id")

    response = await async_client.post(
        "/api/outline/story-outline/revisions",
        params={"novel_id": sample_novel_id},
        json=payload,
    )

    assert response.status_code == 422
