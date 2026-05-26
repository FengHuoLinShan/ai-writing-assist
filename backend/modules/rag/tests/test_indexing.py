"""
TB1: RAG 章节索引 — 测试
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag.repositories import RagChunkRepository
from modules.rag.schemas import RagChunkCreate

from tests.conftest import test_project_id, test_character_id  # noqa: F401


@pytest.fixture
def repo() -> RagChunkRepository:
    return RagChunkRepository()


@pytest.mark.asyncio
async def test_delete_by_chapter_removes_chunks(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """RED: delete_by_chapter 应删除指定章节的所有 chunk"""
    nid = uuid.UUID(hex=test_project_id)

    # 先创建 2 个第 1 章 chunk + 1 个第 2 章 chunk
    chunk1 = await repo.create(db_session, nid, RagChunkCreate(
        source_type="chapter_text", chapter_index=1, text="第一章内容。",
    ))
    chunk2 = await repo.create(db_session, nid, RagChunkCreate(
        source_type="chapter_text", chapter_index=1, text="第一章更多内容。",
    ))
    await repo.create(db_session, nid, RagChunkCreate(
        source_type="chapter_text", chapter_index=2, text="第二章内容。",
    ))

    # 执行删除第 1 章
    deleted = await repo.delete_by_chapter(db_session, nid, "chapter_text", 1)
    assert deleted == 2, f"应删除 2 个 chunk，实际删除了 {deleted}"

    # 验证第 1 章的 chunk 已删除
    remaining = await repo.find_by_chapter(db_session, nid, 1)
    assert len(remaining) == 0, "第 1 章的 chunk 应全部删除"

    # 第 2 章的 chunk 应保留
    ch2 = await repo.find_by_chapter(db_session, nid, 2)
    assert len(ch2) == 1, "第 2 章的 chunk 应保留 1 个"


@pytest.mark.asyncio
async def test_delete_by_chapter_no_op_when_none(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """RED: 删除不存在的章节应返回 0"""
    nid = uuid.UUID(hex=test_project_id)
    deleted = await repo.delete_by_chapter(db_session, nid, "chapter_text", 99)
    assert deleted == 0


@pytest.mark.asyncio
async def test_index_chapter_creates_chunks_with_character_ids(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
    test_character_id: str,  # noqa: F811
):
    """RED: index_chapter 应创建带角色标记的 chunk"""
    from modules.rag.facade import index_chapter
    from modules.writing.models import WritingDraft
    import uuid as _uuid

    nid_uuid = uuid.UUID(hex=test_project_id)
    cid_uuid = uuid.UUID(hex=test_character_id)

    # 先创建一个草稿
    draft = WritingDraft(
        id=_uuid.uuid4(),
        novel_id=nid_uuid,
        chapter_index=1,
        title="第一章",
        content="测试主角从沉睡中醒来。测试主角环顾四周。",
        version_number=1,
        status="draft",
    )
    db_session.add(draft)
    await db_session.flush()

    # 执行索引
    chunk_count = await index_chapter(db_session, test_project_id, 1)
    assert chunk_count > 0, f"应创建至少 1 个 chunk，实际创建 {chunk_count}"

    # 验证 chunk 包含 character_ids
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    assert len(chunks) > 0, "应能找到第 1 章的 chunk"

    all_char_ids = []
    for c in chunks:
        all_char_ids.extend(c.character_ids or [])
    assert test_character_id in all_char_ids, (
        f"chunk 应包含角色 ID {test_character_id}，"
        f"实际包含: {all_char_ids}"
    )


@pytest.mark.asyncio
async def test_index_chapter_replaces_old_chunks(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
    test_character_id: str,  # noqa: F811
):
    """RED: 重新索引应替换旧 chunk 而非追加"""
    from modules.rag.facade import index_chapter
    from modules.writing.models import WritingDraft
    import uuid as _uuid

    nid_uuid = uuid.UUID(hex=test_project_id)

    # 先创建旧 chunk
    await repo.create(db_session, nid_uuid, RagChunkCreate(
        source_type="chapter_text", chapter_index=1, text="旧内容。",
    ))

    # 创建草稿
    draft = WritingDraft(
        id=_uuid.uuid4(),
        novel_id=nid_uuid,
        chapter_index=1,
        title="第一章",
        content="测试主角做了某事。",
        version_number=2,
        status="draft",
    )
    db_session.add(draft)
    await db_session.flush()

    # 索引新内容
    chunk_count = await index_chapter(db_session, test_project_id, 1)
    assert chunk_count > 0

    # 验证只有新 chunk，旧 chunk 被替换
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    for c in chunks:
        assert "旧内容" not in c.text, "旧 chunk 应已被删除"


@pytest.mark.asyncio
async def test_index_chapter_with_embeddings(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """RED: index_chapter 应生成并存储 embedding"""
    from modules.rag.facade import index_chapter
    from unittest.mock import patch, AsyncMock
    from modules.writing.models import WritingDraft
    import uuid as _uuid

    nid_uuid = uuid.UUID(hex=test_project_id)

    # 创建草稿
    draft = WritingDraft(
        id=_uuid.uuid4(),
        novel_id=nid_uuid,
        chapter_index=1,
        title="第一章",
        content="测试主角的欲望是找到真相。",
        version_number=1,
        status="draft",
    )
    db_session.add(draft)
    await db_session.flush()

    # mock embedding provider（使用 1024 维匹配 Vector(1024) 列定义）
    fake_embedding = [0.1] * 1024

    with patch(
        "infrastructure.llm.client.LLMClient",
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(return_value=[fake_embedding])
        mock_client_cls.return_value = mock_client

        chunk_count = await index_chapter(db_session, test_project_id, 1)

    assert chunk_count > 0, "应创建 chunks"

    # 验证 chunk 有 embedding
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    for c in chunks:
        assert c.embedding is not None, f"chunk {c.id} 应有 embedding"

    # 验证 generate_embedding 被调用（批量调用）
    mock_client.generate_embedding.assert_called_once()
    args = mock_client.generate_embedding.call_args
    assert args is not None, "generate_embedding 应被调用"
    # 参数应为字符串列表（批量）
    input_texts = args[0][0] if args else []
    assert isinstance(input_texts, list), "应接收文本列表（批量）"
    assert all(isinstance(t, str) for t in input_texts), "每项应为字符串"


@pytest.mark.asyncio
async def test_index_chapter_embedding_empty_when_no_llm(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """RED: LLM 不可用时不应阻塞索引"""
    from modules.rag.facade import index_chapter
    from unittest.mock import patch, AsyncMock
    from modules.writing.models import WritingDraft
    import uuid as _uuid

    nid_uuid = uuid.UUID(hex=test_project_id)

    draft = WritingDraft(
        id=_uuid.uuid4(),
        novel_id=nid_uuid,
        chapter_index=1,
        title="第一章",
        content="测试内容。",
        version_number=1,
        status="draft",
    )
    db_session.add(draft)
    await db_session.flush()

    with patch(
        "infrastructure.llm.client.LLMClient",
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=Exception("API 不可用"))
        mock_client_cls.return_value = mock_client

        # 不应抛出异常
        chunk_count = await index_chapter(db_session, test_project_id, 1)

    assert chunk_count > 0, "即使 embedding 失败也应创建 chunks"
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    # embedding 应为 None（不阻塞索引）
    has_any_embedding = any(c.embedding is not None for c in chunks)
    assert not has_any_embedding, "embedding 失败时所有 chunk 的 embedding 应为 None"


@pytest.mark.asyncio
async def test_index_chapter_skips_no_draft(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """RED: 无草稿的章节应返回 0"""
    from modules.rag.facade import index_chapter

    count = await index_chapter(db_session, test_project_id, 99)
    assert count == 0, "无草稿章节应返回 0"
