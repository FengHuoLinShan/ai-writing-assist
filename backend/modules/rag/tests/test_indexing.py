"""
TB1: RAG 章节索引 — 测试
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag.repositories import RagChunkRepository
from modules.rag.schemas import RagChunkCreate
from tests.conftest import test_character_id, test_project_id  # noqa: F401


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
    chunk1 = await repo.create(
        db_session,
        nid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            text="第一章内容。",
        ),
    )
    chunk2 = await repo.create(
        db_session,
        nid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            text="第一章更多内容。",
        ),
    )
    await repo.create(
        db_session,
        nid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=2,
            text="第二章内容。",
        ),
    )

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
    import uuid as _uuid

    from modules.rag.facade import index_chapter
    from modules.writing.models import WritingDraft

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
    )
    db_session.add(draft)
    await db_session.flush()

    # 执行索引
    chunk_count = await index_chapter(db_session, test_project_id, 1)
    assert chunk_count > 0, f"应创建至少 1 个 chunk，实际创建 {chunk_count}"

    # 验证 chunk 包含 character_ids
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    assert len(chunks) > 0, "应能找到第 1 章的 chunk"

    # CoreEntity 角色的 ID 出现在 entity_ids（list_entity_terms 返回 type="entity"）
    all_entity_ids = []
    for c in chunks:
        all_entity_ids.extend(c.entity_ids or [])
    assert test_character_id in all_entity_ids, (
        f"chunk 应包含角色 entity ID {test_character_id}，实际包含: {all_entity_ids}"
    )


@pytest.mark.asyncio
async def test_index_chapter_replaces_old_chunks(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
    test_character_id: str,  # noqa: F811
):
    """RED: 重新索引应替换旧 chunk 而非追加"""
    import uuid as _uuid

    from modules.rag.facade import index_chapter
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)

    # 先创建旧 chunk
    await repo.create(
        db_session,
        nid_uuid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            text="旧内容。",
        ),
    )

    # 创建草稿
    draft = WritingDraft(
        id=_uuid.uuid4(),
        novel_id=nid_uuid,
        chapter_index=1,
        title="第一章",
        content="测试主角做了某事。",
        version_number=2,
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
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from modules.rag.facade import index_chapter
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)

    # 创建草稿
    draft = WritingDraft(
        id=_uuid.uuid4(),
        novel_id=nid_uuid,
        chapter_index=1,
        title="第一章",
        content="测试主角的欲望是找到真相。",
        version_number=1,
    )
    db_session.add(draft)
    await db_session.flush()

    # mock embedding provider（使用 768 维匹配 Vector(768) 列定义）
    fake_embedding = [0.1] * 768

    with patch(
        "infrastructure.llm.client.LLMClient",
    ) as mock_client_cls:
        mock_client = AsyncMock()
        # 逐 chunk 调用：单个字符串 → 返回 list[float]
        mock_client.generate_embedding = AsyncMock(return_value=fake_embedding)
        mock_client_cls.return_value = mock_client

        chunk_count = await index_chapter(db_session, test_project_id, 1)

    assert chunk_count > 0, "应创建 chunks"

    # 验证 chunk 有 embedding
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    for c in chunks:
        assert c.embedding is not None, f"chunk {c.id} 应有 embedding"

    # 验证 generate_embedding 按逐 chunk 模式被调用
    call_count = mock_client.generate_embedding.call_count
    assert call_count > 0, "generate_embedding 应被调用"
    assert call_count == len(chunks), (
        f"应为 {len(chunks)} 次调用（逐 chunk），实际 {call_count} 次"
    )
    for call_args in mock_client.generate_embedding.call_args_list:
        input_text = call_args[0][0] if call_args else ""
        assert isinstance(input_text, str), "应接收字符串（逐 chunk）"


@pytest.mark.asyncio
async def test_index_chapter_uses_cn_novel_index_and_project_terms(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """索引应记录显式位置字段，并用人物/世界/剧情线词典标注 chunk。"""
    from unittest.mock import AsyncMock, patch

    from modules.rag.facade import index_chapter_with_report
    from modules.world.models import Character, CoreEntity
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)
    char_id = uuid.uuid4()
    entity_id = uuid.uuid4()

    db_session.add(
        CoreEntity(
            id=char_id,
            novel_id=nid_uuid,
            entity_type="character",
            name="克莱恩·莫雷蒂",
            content_json={"aliases": [{"alias": "周明瑞", "type": "original_name"}]},
            status="canonical",
        )
    )
    db_session.add(
        Character(
            entity_id=char_id,
            novel_id=nid_uuid,
            name="克莱恩·莫雷蒂",
            aliases=[{"alias": "周明瑞", "type": "original_name"}],
            role="主角",
            status="canonical",
        )
    )
    db_session.add(
        CoreEntity(
            id=entity_id,
            novel_id=nid_uuid,
            entity_type="secret",
            name="灰雾",
            summary="神秘空间",
            status="canonical",
        )
    )
    db_session.add(
        WritingDraft(
            id=uuid.uuid4(),
            novel_id=nid_uuid,
            chapter_index=1,
            title="第一章",
            content=(
                "周明瑞从梦中醒来，脑海里残留着穿越谜团。"
                "他看见神秘空间一样的灰雾在眼前翻涌。" * 20
            ),
            version_number=1,
        )
    )
    await db_session.flush()

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(
            side_effect=Exception("embedding down")
        )
        mock_client_cls.return_value = mock_client

        report = await index_chapter_with_report(db_session, test_project_id, 1)

    assert report.chunks_created > 0
    assert report.embedding_failed_count == report.chunks_created
    assert report.warnings

    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    assert chunks
    assert all(c.index_version == "cn-novel-v1" for c in chunks)
    assert all(c.chunk_index is not None for c in chunks)
    assert all(c.start_offset is not None and c.end_offset is not None for c in chunks)
    assert all(c.char_count == len(c.text) for c in chunks)
    # CoreEntity 角色的 ID 作为 entity_id（item["type"] == "entity"）匹配
    assert any(str(char_id) in (c.entity_ids or []) for c in chunks)
    assert any(str(entity_id) in (c.entity_ids or []) for c in chunks)
    assert all(c.embedding_status == "failed" for c in chunks)


@pytest.mark.asyncio
async def test_index_chapter_embedding_empty_when_no_llm(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """RED: LLM 不可用时不应阻塞索引"""
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from modules.rag.facade import index_chapter
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)

    draft = WritingDraft(
        id=_uuid.uuid4(),
        novel_id=nid_uuid,
        chapter_index=1,
        title="第一章",
        content="测试内容。",
        version_number=1,
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
async def test_reindex_novel_task_rebuilds_all_chapters_with_report(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
):
    """全量重建任务应逐章索引并返回可展示的诊断结果。"""
    from unittest.mock import AsyncMock, patch

    from infrastructure.tasks.models import AsyncTask
    from modules.rag.tasks import handle_rag_reindex_novel
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)
    for idx in (1, 2):
        db_session.add(
            WritingDraft(
                id=uuid.uuid4(),
                novel_id=nid_uuid,
                chapter_index=idx,
                title=f"第{idx}章",
                content=f"第{idx}章正文。周明瑞醒来并观察这个世界。" * 8,
                version_number=1,
            )
        )
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_reindex_novel",
        status="running",
        meta={"novel_id": test_project_id, "force": True},
        progress=0.0,
    )
    db_session.add(task)
    await db_session.flush()

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(
            side_effect=Exception("embedding down")
        )
        mock_client_cls.return_value = mock_client

        result = await handle_rag_reindex_novel(db_session, task)

    assert result["total_chapters"] == 2
    assert result["chunks_created"] >= 2
    assert result["embedding_failed_count"] == result["chunks_created"]
    assert result["warnings"]
    assert len(result["chapters"]) == 2
    assert task.progress == 1.0


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
