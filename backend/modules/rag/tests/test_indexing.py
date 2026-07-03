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
    await repo.create(
        db_session,
        nid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            text="第一章内容。",
        ),
    )
    await repo.create(
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
async def test_incremental_index_reuses_equal_chunks_without_mutating_iteration(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """增量索引复用 unchanged chunk 时不能边遍历 dict 边删除 key。"""
    from modules.rag.indexing import IndexingService

    nid_uuid = uuid.UUID(hex=test_project_id)
    old_chunk = await repo.create(
        db_session,
        nid_uuid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            chunk_index=0,
            start_offset=0,
            end_offset=4,
            char_count=4,
            text="完全相同",
            embedding_status="succeeded",
        ),
    )
    await db_session.flush()

    report = await IndexingService(repo=repo).index_chapter_incremental(
        db_session,
        nid_uuid,
        1,
        old_content="完全相同",
        new_content="完全相同",
    )

    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    assert report.chunks_created_ids == [str(old_chunk.id)]
    assert [chunk.id for chunk in chunks] == [old_chunk.id]


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


@pytest.mark.asyncio
async def test_index_chapter_replaces_stale_chunks_on_update(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """RED: 更新章节正文后重新索引，旧 chunk 不应残留，新 chunk 应出现"""
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from modules.rag.facade import index_chapter_with_report
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)

    db_session.add(
        WritingDraft(
            id=_uuid.uuid4(),
            novel_id=nid_uuid,
            chapter_index=1,
            title="第一章",
            content="旧正文片段。旧正文片段。旧内容应被清除。" * 6,
            version_number=1,
        )
    )
    await db_session.flush()

    fake_embedding = [0.1] * 768
    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(return_value=fake_embedding)
        mock_client_cls.return_value = mock_client
        result = await index_chapter_with_report(db_session, test_project_id, 1)

    assert result.chunks_created > 0
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    assert any("旧正文片段" in c.text for c in chunks)
    assert len(chunks) == result.chunks_created, "首次索引后 chunk 总数应与报告一致"

    # 更新章节：创建新版本草稿
    db_session.add(
        WritingDraft(
            id=_uuid.uuid4(),
            novel_id=nid_uuid,
            chapter_index=1,
            title="第一章（修订）",
            content="新正文片段。新正文片段。新内容应保留。" * 6,
            version_number=2,
        )
    )
    await db_session.flush()

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(return_value=fake_embedding)
        mock_client_cls.return_value = mock_client
        result = await index_chapter_with_report(db_session, test_project_id, 1)

    assert result.chunks_created > 0
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    assert all("旧正文片段" not in c.text for c in chunks)
    assert any("新正文片段" in c.text for c in chunks)
    assert len(chunks) == result.chunks_created, (
        "重新索引后旧 chunk 应被删除，总数应与报告一致"
    )


@pytest.mark.asyncio
async def test_index_chapter_with_report_marks_failed_embeddings(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """RED: embedding 失败时 chunk 状态应为 failed 且报告携带 warnings"""
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from modules.rag.facade import index_chapter_with_report
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)

    db_session.add(
        WritingDraft(
            id=_uuid.uuid4(),
            novel_id=nid_uuid,
            chapter_index=1,
            title="第一章",
            content="测试正文。用于验证 embedding 失败降级。" * 8,
            version_number=1,
        )
    )
    await db_session.flush()

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(
            side_effect=Exception("embedding down"),
        )
        mock_client_cls.return_value = mock_client
        result = await index_chapter_with_report(db_session, test_project_id, 1)

    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    assert any(c.embedding_status == "failed" for c in chunks)
    assert result.warnings


@pytest.mark.asyncio
async def test_index_chapter_annotates_scene_id(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """索引章节时应按 scene_chunks 区间把 chunk 标注上 scene_id。"""
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from modules.outline.repositories import SceneRepository
    from modules.outline.schemas import SceneCreate
    from modules.rag.facade import index_chapter_with_report
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)
    scene_repo = SceneRepository()

    content = "周明瑞从梦中醒来，脑海里残留着穿越谜团。" * 30
    scene = await scene_repo.create(
        db_session,
        nid_uuid,
        SceneCreate(
            scene_index=0,
            title="开场",
            chapter_ids=["1"],
            scene_chunks=[
                {
                    "chapter_id": "1",
                    "chapter_index": 1,
                    "start_pos": 0,
                    "end_pos": len(content),
                }
            ],
            status="draft",
        ),
    )

    db_session.add(
        WritingDraft(
            id=_uuid.uuid4(),
            novel_id=nid_uuid,
            chapter_index=1,
            title="第一章",
            content=content,
            version_number=1,
        )
    )
    await db_session.flush()

    embed_exc = Exception("embedding down")
    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=embed_exc)
        mock_client_cls.return_value = mock_client

        report = await index_chapter_with_report(db_session, test_project_id, 1)

    assert report.chunks_created > 0
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    assert chunks
    assert any(str(c.scene_id) == str(scene.id) for c in chunks), (
        f"至少有一个 chunk 应被标注 scene_id {scene.id}"
    )


@pytest.mark.asyncio
async def test_index_chapter_uses_chapter_scene_fallback_without_offsets(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """只有段落映射、没有字符偏移时，应回退到章节级 scene_id。"""
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from modules.outline.repositories import SceneRepository
    from modules.outline.schemas import SceneCreate
    from modules.rag.facade import index_chapter_with_report
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)
    scene_repo = SceneRepository()

    content = "克莱恩在廷根整理线索，确认占卜与梦境的关系。" * 30
    scene = await scene_repo.create(
        db_session,
        nid_uuid,
        SceneCreate(
            scene_index=0,
            title="段落映射场景",
            chapter_ids=["1"],
            scene_chunks=[
                {
                    "chapter_index": 1,
                    "start_paragraph": 0,
                    "end_paragraph": 0,
                }
            ],
            status="draft",
        ),
    )

    db_session.add(
        WritingDraft(
            id=_uuid.uuid4(),
            novel_id=nid_uuid,
            chapter_index=1,
            title="第一章",
            content=content,
            version_number=1,
        )
    )
    await db_session.flush()

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=Exception("offline"))
        mock_client_cls.return_value = mock_client

        report = await index_chapter_with_report(db_session, test_project_id, 1)

    assert report.chunks_created > 0
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    assert chunks
    assert all(str(c.scene_id) == str(scene.id) for c in chunks)


@pytest.mark.asyncio
async def test_rebuild_novel_with_chapter_range(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
):
    """rag_reindex_novel 任务应只重建指定章节范围。"""
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from infrastructure.tasks.models import AsyncTask
    from modules.rag.tasks import handle_rag_reindex_novel
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)
    for idx in (1, 2, 3):
        db_session.add(
            WritingDraft(
                id=_uuid.uuid4(),
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
        meta={"novel_id": test_project_id, "start_chapter": 2, "end_chapter": 2},
        progress=0.0,
    )
    db_session.add(task)
    await db_session.flush()

    embed_exc = Exception("embedding down")
    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=embed_exc)
        mock_client_cls.return_value = mock_client

        result = await handle_rag_reindex_novel(db_session, task)

    assert result["total_chapters"] == 1
    assert result["chunks_created"] >= 1
    chapter_indices = [c["chapter_index"] for c in result["chapters"]]
    assert chapter_indices == [2]


@pytest.mark.asyncio
async def test_retry_embeddings_task_updates_failed_chunks(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """rag_retry_embeddings 只修复目标项目内的失败向量。"""
    from unittest.mock import AsyncMock, patch

    from infrastructure.tasks.models import AsyncTask
    from modules.rag.tasks import handle_rag_retry_embeddings

    nid_uuid = uuid.UUID(hex=test_project_id)
    retry_chunk = await repo.create(
        db_session,
        nid_uuid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            text="需要重试的片段",
            embedding_status="failed",
            embedding_error="old error",
        ),
    )
    skipped_chunk = await repo.create(
        db_session,
        nid_uuid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=2,
            text="范围外失败片段",
            embedding_status="failed",
        ),
    )
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_retry_embeddings",
        status="running",
        meta={"novel_id": test_project_id, "start_chapter": 1, "end_chapter": 1},
        progress=0.0,
    )
    db_session.add(task)
    await db_session.flush()

    fake_embedding = [0.1] * 768
    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(return_value=[fake_embedding])
        mock_client_cls.return_value = mock_client

        result = await handle_rag_retry_embeddings(db_session, task)

    assert result["total"] == 1
    assert result["succeeded"] == 1
    assert result["failed"] == 0
    assert task.progress == 1.0
    refreshed = await repo.get(db_session, retry_chunk.id)
    skipped = await repo.get(db_session, skipped_chunk.id)
    assert refreshed.embedding_status == "succeeded"
    assert refreshed.embedding is not None
    assert refreshed.embedding_error is None
    assert skipped.embedding_status == "failed"


@pytest.mark.asyncio
async def test_retry_embeddings_task_processes_more_than_one_batch(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """失败向量超过单批上限时，任务应循环直到无剩余候选。"""
    from unittest.mock import AsyncMock, patch

    from infrastructure.tasks.models import AsyncTask
    from modules.rag.tasks import handle_rag_retry_embeddings

    nid_uuid = uuid.UUID(hex=test_project_id)
    for index in range(501):
        await repo.create(
            db_session,
            nid_uuid,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                chunk_index=index,
                text=f"失败片段 {index}",
                embedding_status="failed",
            ),
        )
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_retry_embeddings",
        status="running",
        meta={"novel_id": test_project_id},
        progress=0.0,
    )
    db_session.add(task)
    await db_session.flush()

    fake_embedding = [0.1] * 768

    async def _fake_embedding(texts):
        return [fake_embedding for _ in texts]

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=_fake_embedding)
        mock_client_cls.return_value = mock_client

        result = await handle_rag_retry_embeddings(db_session, task)

    remaining = await repo.count_retryable_embeddings(
        db_session,
        nid_uuid,
        statuses=["failed", "pending_vectorization"],
    )
    assert result["total"] == 501
    assert result["succeeded"] == 501
    assert result["failed"] == 0
    assert result["remaining_retryable_count"] == 0
    assert remaining == 0
    assert mock_client.generate_embedding.call_count == 2


@pytest.mark.asyncio
async def test_retry_embeddings_task_marks_batch_failure(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """批量 embedding 失败时保持 failed 并写入截断错误。"""
    from unittest.mock import AsyncMock, patch

    from infrastructure.tasks.models import AsyncTask
    from modules.rag.tasks import handle_rag_retry_embeddings

    nid_uuid = uuid.UUID(hex=test_project_id)
    chunk = await repo.create(
        db_session,
        nid_uuid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            text="失败片段",
            embedding_status="failed",
        ),
    )
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_retry_embeddings",
        status="running",
        meta={"novel_id": test_project_id},
        progress=0.0,
    )
    db_session.add(task)
    await db_session.flush()

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=Exception("x" * 1200))
        mock_client_cls.return_value = mock_client

        result = await handle_rag_retry_embeddings(db_session, task)

    refreshed = await repo.get(db_session, chunk.id)
    assert result["total"] == 1
    assert result["succeeded"] == 0
    assert result["failed"] == 1
    assert refreshed.embedding_status == "failed"
    assert len(refreshed.embedding_error) == 1000
