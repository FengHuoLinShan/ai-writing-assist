"""词法召回通道契约（M3 切片 2c：有界词项 + PG 数组召回 + 回退）。

SQLite 单测验证规划/评分/回退语义；真实 GIN 索引与延迟以 PG 实测为准
（设计 §4，D7 对照见 evals）。
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.indexing.facade import create_chunk
from modules.evidence.indexing.repositories import RagChunkRepository
from modules.evidence.indexing.retrieval import RetrievalOrchestrator
from modules.evidence.indexing.schemas import RagChunkCreate


async def _seed_chunk(db: AsyncSession, novel_id: uuid.UUID, text: str) -> None:
    await create_chunk(
        db,
        str(novel_id),
        RagChunkCreate(
            source_type="chapter_text",
            source_id=str(uuid.uuid4()),
            content_mode="canonical",
            chapter_index=1,
            chunk_index=0,
            start_offset=0,
            end_offset=len(text),
            char_count=len(text),
            text=text,
            index_version="cn-novel-v1",
        ),
    )
    await db.flush()


@pytest.mark.asyncio
async def test_keyword_search_uses_precomputed_terms_only(
    db_with_project, sample_novel_id
) -> None:
    await _seed_chunk(db_with_project, sample_novel_id, "沈砚在雾渡港找到了铜钥匙。")
    await _seed_chunk(db_with_project, sample_novel_id, "灯塔下的旧仓库门锁生锈了。")

    repo = RagChunkRepository()
    hits = await repo.keyword_search(
        db_with_project,
        sample_novel_id,
        "",  # 空 query：完全依赖调用方词项，不再本地 n-gram 展开
        precomputed_terms=["沈砚", "不存在的词"],
        limit=10,
    )

    assert len(hits) == 1
    assert "沈砚" in hits[0].text


@pytest.mark.asyncio
async def test_lexical_search_returns_empty_off_postgres(
    db_with_project, sample_novel_id
) -> None:
    await _seed_chunk(db_with_project, sample_novel_id, "沈砚在雾渡港找到了铜钥匙。")

    repo = RagChunkRepository()
    assert await repo.lexical_search(db_with_project, sample_novel_id, ["沈砚"]) == []
    # 非 PG 方言探针恒 False：调用方直接走有界 ILIKE，不依赖探针
    assert (
        await repo.has_unindexed_lexical_terms(db_with_project, sample_novel_id) is False
    )


@pytest.mark.asyncio
async def test_hybrid_search_falls_back_to_bounded_like_with_diagnostics(
    db_with_project, sample_novel_id
) -> None:
    await _seed_chunk(db_with_project, sample_novel_id, "沈砚在雾渡港找到了铜钥匙。")
    await _seed_chunk(db_with_project, sample_novel_id, "灯塔下的旧仓库门锁生锈了。")

    orchestrator = RetrievalOrchestrator()
    diagnostics: dict[str, bool | str] = {}
    results = await orchestrator.hybrid_search(
        db_with_project,
        sample_novel_id,
        "铜钥匙在哪里",
        lexical_terms=["铜钥匙", "灯塔"],
        expand_query=False,
        diagnostics=diagnostics,
    )

    assert diagnostics["lexical_method"] == "bounded-like-v1"
    texts = {chunk.text for chunk, _score in results}
    assert any("铜钥匙" in text for text in texts)
    assert any("灯塔" in text for text in texts)


@pytest.mark.asyncio
async def test_hybrid_search_without_terms_keeps_legacy_path(
    db_with_project, sample_novel_id
) -> None:
    await _seed_chunk(db_with_project, sample_novel_id, "沈砚在雾渡港找到了铜钥匙。")

    orchestrator = RetrievalOrchestrator()
    diagnostics: dict[str, bool | str] = {}
    results = await orchestrator.hybrid_search(
        db_with_project,
        sample_novel_id,
        "沈砚 铜钥匙",
        expand_query=False,
        diagnostics=diagnostics,
    )

    assert diagnostics["lexical_method"] == "legacy-ngram-v1"
    assert results
