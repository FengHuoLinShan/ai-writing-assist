"""PostgreSQL end-to-end flow for stable manuscript evidence."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_publish_index_search_read_inspect_trace_and_working_rebuild(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.config import get_settings

    embedding = [0.05] * get_settings().embedding_dim

    async def _deterministic_embedding(_self, value, **_kwargs):
        if isinstance(value, list):
            return [embedding.copy() for _ in value]
        return embedding.copy()

    monkeypatch.setattr(
        "infrastructure.llm.client.LLMClient.generate_embedding",
        _deterministic_embedding,
    )
    meta = await create_base_scene(db_session)
    novel_id = meta["project_id"]
    character_id = meta["entity_ids"]["克莱恩·莫雷蒂"]
    target_id = meta["entity_ids"]["源堡"]
    content = "第五十章\n阿澜在旧塔得知密钥藏在钟后。\n她把这条线索记了下来。"

    published = await async_client.post(
        "/api/writing/drafts",
        json={
            "novel_id": novel_id,
            "chapter_index": 50,
            "title": "第五十章",
            "content": content,
        },
    )
    assert published.status_code == 201, published.text
    published_draft = published.json()["draft"]

    from modules.evidence.facade import index_chapter_with_report
    from modules.evidence.indexing.index_state import RagIndexStateService

    state_service = RagIndexStateService()
    await state_service.begin_direct(
        db_session,
        novel_id=novel_id,
        chapter_index=50,
        content_mode="canonical",
    )
    canonical_report = await index_chapter_with_report(
        db_session,
        novel_id,
        50,
        content_mode="canonical",
    )
    await state_service.finish(
        db_session,
        novel_id=novel_id,
        report=canonical_report,
    )
    assert canonical_report.source_draft_id == published_draft["id"]

    visibility = {"mode": "reader", "cutoff_chapter": 50}
    grep = await async_client.post(
        "/api/context/evidence/grep",
        json={
            "novel_id": novel_id,
            "pattern": "密钥藏在钟后",
            "content_mode": "canonical",
            "visibility": visibility,
        },
    )
    assert grep.status_code == 200, grep.text
    source_ref = grep.json()["hits"][0]["source_ref"]
    assert source_ref["draft_id"] == published_draft["id"]

    search = await async_client.post(
        "/api/context/evidence/search",
        json={
            "novel_id": novel_id,
            "query": "旧塔密钥",
            "content_mode": "canonical",
            "visibility": {"mode": "author"},
            "scopes": ["manuscript"],
        },
    )
    assert search.status_code == 200, search.text
    assert search.json()["hits"]
    assert search.json()["degraded"] is False
    assert all(item["index_fresh"] for item in search.json()["hits"])

    read = await async_client.post(
        "/api/context/evidence/read",
        json={
            "novel_id": novel_id,
            "content_mode": "canonical",
            "visibility": visibility,
            "source_ref": source_ref,
            "before": 1,
            "after": 1,
        },
    )
    assert read.status_code == 200, read.text
    assert "密钥藏在钟后" in read.json()["text"]
    assert read.json()["visibility_decision"]["visible"] is True

    character = await async_client.post(
        f"/api/world/characters?novel_id={novel_id}",
        json={"entity_id": character_id, "name": "克莱恩·莫雷蒂"},
    )
    assert character.status_code == 201, character.text
    knowledge = await async_client.post(
        f"/api/world/characters/{character_id}/knowledge?novel_id={novel_id}",
        json={
            "character_id": character_id,
            "target_type": "entity",
            "target_id": target_id,
            "knowledge_level": "partial",
            "known_content": "密钥藏在钟后",
            "source_chapter_index": 49,
        },
    )
    assert knowledge.status_code == 201, knowledge.text
    target_ref = {
        "target_type": "character_knowledge",
        "target_id": knowledge.json()["id"],
        "target_path": "known_content",
    }

    from modules.evidence.facade import record_evidence_link

    await record_evidence_link(
        db_session,
        novel_id=novel_id,
        target_ref=target_ref,
        source_ref=source_ref,
        claim_path="known_content",
        provenance={"workflow": "postgres_e2e"},
    )

    character_visibility = {
        "mode": "character",
        "cutoff_chapter": 50,
        "character_id": character_id,
    }
    inspect = await async_client.post(
        "/api/context/evidence/inspect",
        json={
            "novel_id": novel_id,
            "content_mode": "canonical",
            "visibility": character_visibility,
            "target_ref": target_ref,
        },
    )
    assert inspect.status_code == 200, inspect.text
    assert inspect.json()["visible"] is True
    assert inspect.json()["evidence_count"] == 1

    trace = await async_client.post(
        "/api/context/evidence/trace",
        json={
            "novel_id": novel_id,
            "content_mode": "canonical",
            "visibility": character_visibility,
            "target_ref": target_ref,
            "claim_path": "known_content",
        },
    )
    assert trace.status_code == 200, trace.text
    assert "密钥藏在钟后" in trace.json()["links"][0]["read"]["text"]

    working_content = content + "\n工作稿新增铜铃与密钥的关联。"
    working = await async_client.put(
        f"/api/writing/drafts/{published_draft['id']}?novel_id={novel_id}",
        json={"content": working_content},
    )
    assert working.status_code == 200, working.text
    assert working.json()["id"] != published_draft["id"]

    working_grep = await async_client.post(
        "/api/context/evidence/grep",
        json={
            "novel_id": novel_id,
            "pattern": "工作稿新增铜铃",
            "content_mode": "working",
            "visibility": {"mode": "author"},
        },
    )
    assert working_grep.status_code == 200, working_grep.text
    assert working_grep.json()["hits"]

    stale_search = await async_client.post(
        "/api/context/evidence/search",
        json={
            "novel_id": novel_id,
            "query": "工作稿新增铜铃",
            "content_mode": "working",
            "visibility": {"mode": "author"},
            "scopes": ["manuscript"],
            "chapter_from": 50,
            "chapter_to": 50,
        },
    )
    assert stale_search.status_code == 200, stale_search.text
    assert stale_search.json()["hits"] == []
    assert any("工作稿索引更新中" in item for item in stale_search.json()["warnings"])

    await state_service.begin_direct(
        db_session,
        novel_id=novel_id,
        chapter_index=50,
        content_mode="working",
    )
    working_report = await index_chapter_with_report(
        db_session,
        novel_id,
        50,
        content_mode="working",
    )
    await state_service.finish(db_session, novel_id=novel_id, report=working_report)

    rebuilt_search = await async_client.post(
        "/api/context/evidence/search",
        json={
            "novel_id": novel_id,
            "query": "工作稿新增铜铃",
            "content_mode": "working",
            "visibility": {"mode": "author"},
            "scopes": ["manuscript"],
            "chapter_from": 50,
            "chapter_to": 50,
        },
    )
    assert rebuilt_search.status_code == 200, rebuilt_search.text
    assert rebuilt_search.json()["hits"]

    other = await create_base_scene(db_session)
    cross_read = await async_client.post(
        "/api/context/evidence/read",
        json={
            "novel_id": other["project_id"],
            "content_mode": "canonical",
            "visibility": {"mode": "author"},
            "source_ref": source_ref,
        },
    )
    assert cross_read.status_code in {400, 404}
