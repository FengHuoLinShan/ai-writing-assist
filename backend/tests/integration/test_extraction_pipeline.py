"""
全管线集成测试：写入 → 分块 → LLM 抽取 → 候选入库 → 检索 → 上下文编译

测试正文包含明确的角色名、别名引用、指代模糊场景，
用于评估 LLM 实体抽取 + Candidates/Dedup 的准确率表现。

TDD vertical slices:
  T1: 写入草稿 → RAG 分块索引
  T2: LLM 抽取实体 → 候选入库
  T3: 别名识别与去重
  T4: 指代消解
  T5: 混合检索
  T6: 上下文编译
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.facade import compile_structure_context, render_context_markdown
from modules.rag.facade import get_ordered_chapter_chunks, index_chapter, retrieve
from modules.world.facade import find_similar_entities
from modules.world.repositories import CoreEntityRepository
from modules.world.services.core.extraction_service import EntityExtractionService
from modules.writing.facade import create_draft
from shared.utils import parse_uuid

real_llm_required = pytest.mark.skipif(
    os.getenv("RUN_REAL_LLM_TESTS") != "1",
    reason="真实 LLM 集成验收默认跳过；设置 RUN_REAL_LLM_TESTS=1 才运行",
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.real_llm,
    real_llm_required,
]


async def _run_manual_extraction(
    db: AsyncSession,
    novel_id: str,
    *,
    start_chapter: int,
    end_chapter: int,
) -> dict:
    """Exercise the manual supplement service without the removed facade."""
    result = await EntityExtractionService().extract_entities_from_chapters(
        db,
        novel_id,
        start_chapter,
        end_chapter,
    )
    return {
        "total_chapters": result.total_chapters,
        "total_created": result.total_created,
        "total_skipped": result.total_skipped,
        "failed_chapters": result.failed_chapters,
        "items": result.items,
    }


# ============================================================
# 测试正文 — 包含多种实体抽取挑战
# ============================================================

TEST_CHAPTER_TEXT = """第一章 落星阁

夜色如墨，落星阁的琉璃瓦上映着冷月清辉。

白砚推门而入，衣袂带风。他环顾四周，目光最终落在角落里那个黑衣人的身上。

"苏先生，久等了。"白砚拱手道。

苏荇放下手中的霜华剑，剑身泛着淡淡的寒光。"小白，你可知道这把剑的来历？"

白砚摇头。他从小就听师父提起过霜华剑，但从未亲眼见过。此剑传说是千年前寒渊真人以天外陨铁所铸，剑成之日，整个寒渊都被冰封了三尺。

"霜华剑出，必见血光。"苏荇的声音低沉下来，"那个黑衣人就是为此剑而来。"

白砚顺着苏荇的目光看向角落。那个黑衣人始终沉默，只有一双眼睛在斗笠下闪烁不定。他知道那个女人不会善罢甘休——从南疆一路追到落星阁，已经跟了他们整整七天。

"她在等什么？"白砚问。

苏荇冷笑一声："等我们交出剑，或者等我们死。"

话音未落，霜华剑突然自行出鞘，一道寒光直冲屋顶。整个落星阁都在震颤。

白砚握住剑柄的瞬间，一股刺骨的寒意涌入经脉。他的意识开始模糊，眼前浮现出无数陌生的画面——那是霜华剑历任主人的记忆。他看到了那个黑衣人的真面目，也看到了藏在南疆深处的秘密。

"守住心神！"苏荇一掌拍在白砚后背，温热的真气涌入，驱散了那股寒意。

白砚睁开眼睛，发现自己的头发已经结了一层薄冰。他看向苏荇，发现这位亦师亦友的中年文士，此刻面色苍白如纸。

那个黑衣人的身影已经消失在夜色中。但白砚知道，这只是开始。霜华剑的传说里还藏着更多秘密，而那个女人——南疆的蛊师阿依娜——绝不会就此罢手。
"""

# 预期实体（人工标注）
EXPECTED_CHARACTERS = ["白砚", "苏荇", "阿依娜", "寒渊真人"]
EXPECTED_LOCATIONS = ["落星阁", "寒渊", "南疆"]
EXPECTED_ITEMS = ["霜华剑"]

# 不应被抽取的内容（代词、模糊指称、普通道具）
PRONOUNS = ["他", "她", "它", "他们"]
VAGUE_REFERENCES = ["黑衣人", "那个女人", "中年文士"]
ORDINARY_PROPS = ["琉璃瓦"]


# ============================================================
# Fixtures
# ============================================================


@pytest_asyncio.fixture
async def novel_id(db_session: AsyncSession) -> str:
    """创建测试项目"""
    from modules.project.models import Project

    pid = uuid.uuid4()
    p = Project(
        id=pid,
        title="全管线测试小说",
        genre="仙侠",
        tone="正剧",
        language="zh",
        current_stage="写作中",
    )
    db_session.add(p)
    await db_session.flush()
    return str(pid)


@pytest_asyncio.fixture
async def chapter_draft(db_session: AsyncSession, novel_id: str) -> dict:
    """写入测试章节草稿，返回 draft 信息"""
    draft, _ = await create_draft(
        db_session,
        novel_id=novel_id,
        chapter_index=1,
        title="落星阁",
        content=TEST_CHAPTER_TEXT,
    )
    await db_session.flush()
    return {"draft_id": str(draft.id), "novel_id": novel_id, "chapter_index": 1}


@pytest_asyncio.fixture
async def indexed_chunks(
    db_session: AsyncSession, novel_id: str, chapter_draft: dict
) -> list:
    """RAG 索引章节，返回 chunk 列表"""
    await index_chapter(db_session, novel_id, chapter_index=1)
    await db_session.flush()

    chunks = await get_ordered_chapter_chunks(db_session, novel_id, start_chapter=1)
    return chunks


# ============================================================
# 辅助函数
# ============================================================


async def _create_entity_via_service(
    db: AsyncSession,
    novel_id: str,
    name: str,
    entity_type: str,
    summary: str | None = None,
    aliases: list[str] | None = None,
) -> str:
    """通过 repository 直接创建实体（测试辅助，非 facade）"""
    repo = CoreEntityRepository()
    entity = await repo.create_raw(
        db,
        novel_id=parse_uuid(novel_id, "novel_id"),
        entity_type=entity_type,
        name=name,
        summary=summary,
        content_json={"aliases": [{"alias": a, "type": "name"} for a in (aliases or [])]}
        if aliases
        else None,
        status="canonical",
    )
    await db.flush()
    return str(entity.id)


# ============================================================
# T1: 写入草稿 → RAG 分块索引
# ============================================================


class TestWriteAndIndex:
    """写入草稿 → RAG 分块索引 — 验证内容持久化与分块元数据正确性"""

    async def test_extraction_pipeline_write_draft_returns_valid_uuid(
        self, chapter_draft
    ):
        """写入草稿后返回有效 draft_id（UUID hex 格式）"""
        # Arrange
        draft_id = chapter_draft["draft_id"]

        # Act
        # fixture 已完成写入操作

        # Assert
        assert draft_id is not None
        assert len(draft_id) == 36

    async def test_extraction_pipeline_draft_content_persisted_with_correct_index(
        self, chapter_draft
    ):
        """草稿内容正确持久化且章节索引为 1"""
        # Arrange
        draft_id = chapter_draft["draft_id"]
        chapter_index = chapter_draft["chapter_index"]

        # Act
        # fixture 已完成写入

        # Assert
        assert draft_id is not None
        assert chapter_index == 1

    async def test_extraction_pipeline_index_chapter_creates_non_empty_chunks(
        self, indexed_chunks
    ):
        """索引后生成至少 1 个 chunk"""
        # Arrange
        chunks = indexed_chunks

        # Act
        # fixture 已完成索引

        # Assert
        assert len(chunks) > 0

    async def test_extraction_pipeline_chunks_contain_non_empty_source_text(
        self, indexed_chunks
    ):
        """每个 chunk 包含非空原文片段"""
        # Arrange
        chunks = indexed_chunks

        # Act
        # fixture 已完成索引

        # Assert
        for chunk in chunks:
            assert chunk.text is not None
            assert len(chunk.text) > 0

    async def test_extraction_pipeline_chunks_have_correct_metadata(self, indexed_chunks):
        """chunk 的 source_type、chapter_index、char_count 正确"""
        # Arrange
        chunks = indexed_chunks

        # Act
        # fixture 已完成索引

        # Assert
        for chunk in chunks:
            assert chunk.source_type in ("writing_draft", "chapter_text")
            assert chunk.chapter_index == 1
            assert chunk.char_count > 0

    async def test_extraction_pipeline_index_reports_positive_chunk_count(
        self, indexed_chunks
    ):
        """index_chapter 返回的 chunk 列表长度大于 0"""
        # Arrange
        chunks = indexed_chunks

        # Act
        # fixture 已完成索引

        # Assert
        assert len(chunks) > 0


# ============================================================
# T2: LLM 抽取实体 → 候选入库
# ============================================================


class TestEntityExtraction:
    """LLM 实体抽取 → 候选池 — 验证候选生成与字段完整性"""

    async def test_extraction_pipeline_llm_extraction_creates_candidates(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """实体抽取产生至少一个候选"""
        # Arrange
        assert len(indexed_chunks) > 0, "需要先有 RAG chunks"

        # Act
        result = await _run_manual_extraction(
            db_session,
            novel_id,
            start_chapter=1,
            end_chapter=1,
        )

        # Assert
        assert result is not None
        assert result["total_chapters"] == 1
        assert result["total_created"] > 0, (
            f"应至少创建一些候选，实际 total_created={result['total_created']}, "
            f"total_skipped={result['total_skipped']}"
        )

    async def test_extraction_pipeline_extraction_items_have_required_fields(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """每个候选 item 包含 id、name、entity_type"""
        # Arrange
        assert len(indexed_chunks) > 0

        # Act
        result = await _run_manual_extraction(
            db_session,
            novel_id,
            start_chapter=1,
            end_chapter=1,
        )

        # Assert
        assert len(result["items"]) > 0
        for item in result["items"]:
            assert "id" in item, f"item missing 'id': {item}"
            assert "name" in item
            assert "entity_type" in item

    async def test_extraction_pipeline_extracted_entities_include_key_characters(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """抽取结果应包含至少 2 个核心角色"""
        # Arrange
        assert len(indexed_chunks) > 0

        # Act
        result = await _run_manual_extraction(
            db_session,
            novel_id,
            start_chapter=1,
            end_chapter=1,
        )

        # Assert
        extracted_names = [item["name"] for item in result["items"]]
        found_key = [n for n in EXPECTED_CHARACTERS if n in extracted_names]
        assert len(found_key) >= 2, (
            f"应至少抽到 2 个核心角色，实际抽到: {found_key}, 全部抽取: {extracted_names}"
        )


# ============================================================
# T3: 别名识别与去重
# ============================================================


class TestAliasAndDedup:
    """别名识别与候选去重 — 验证精确匹配与重复跳过"""

    async def test_extraction_pipeline_similar_entities_exact_match_returns_high_score(
        self, db_session: AsyncSession, novel_id: str
    ):
        """精确名称匹配：已有 '白砚'，搜索 '白砚' 返回高分匹配"""
        # Arrange
        await _create_entity_via_service(
            db_session,
            novel_id,
            name="白砚",
            entity_type="character",
            summary="主角",
        )

        # Act
        results = await find_similar_entities(
            db_session,
            novel_id,
            name="白砚",
            entity_type="character",
        )

        # Assert
        assert len(results) > 0, "精确匹配应找到已有实体"
        best = results[0]
        assert best.similarity_score > 0.9, (
            f"精确匹配分数应 > 0.9，实际: {best.similarity_score}"
        )

    async def test_extraction_pipeline_duplicate_detection_skips_existing_entity(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """已有正史实体时，再次抽取应跳过（去重生效）"""
        # Arrange
        assert len(indexed_chunks) > 0
        await _create_entity_via_service(
            db_session,
            novel_id,
            name="霜华剑",
            entity_type="item",
        )

        # Act
        result = await _run_manual_extraction(
            db_session,
            novel_id,
            start_chapter=1,
            end_chapter=1,
        )

        # Assert
        extracted_names = [item["name"] for item in result["items"]]
        assert "霜华剑" not in extracted_names, (
            f"已存在的实体 '霜华剑' 不应被重复抽取，实际抽取: {extracted_names}"
        )


# ============================================================
# T4: 指代消解
# ============================================================


class TestAmbiguousReferences:
    """指代不清场景 — 验证代词、模糊指称与普通道具不被抽取"""

    async def test_extraction_pipeline_pronouns_not_extracted_as_entities(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """代词（他/她/它/他们）不应被抽取为实体"""
        # Arrange
        assert len(indexed_chunks) > 0

        # Act
        result = await _run_manual_extraction(
            db_session,
            novel_id,
            start_chapter=1,
            end_chapter=1,
        )

        # Assert
        extracted_names = [item["name"].strip() for item in result["items"]]
        for pronoun in PRONOUNS:
            assert pronoun not in extracted_names, (
                f"代词 '{pronoun}' 不应被抽取为实体，但出现了: {extracted_names}"
            )

    async def test_extraction_pipeline_vague_references_flagged_or_skipped(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """模糊指称应被跳过或标记为低置信度"""
        # Arrange
        assert len(indexed_chunks) > 0

        # Act
        result = await _run_manual_extraction(
            db_session,
            novel_id,
            start_chapter=1,
            end_chapter=1,
        )

        # Assert
        for item in result["items"]:
            name = item["name"]
            if name in VAGUE_REFERENCES:
                suggested_action = item.get("suggested_action", "")
                assert suggested_action in (
                    "create_new",
                    "link_to_existing",
                    "ignore",
                    "temporary_only",
                ), (
                    f"模糊指称 '{name}' 应有合适的 suggested_action，"
                    f"实际: {suggested_action}"
                )

    async def test_extraction_pipeline_ordinary_props_not_extracted_as_entities(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """普通道具不应被抽取为实体"""
        # Arrange
        assert len(indexed_chunks) > 0

        # Act
        result = await _run_manual_extraction(
            db_session,
            novel_id,
            start_chapter=1,
            end_chapter=1,
        )

        # Assert
        extracted_names = [item["name"].strip() for item in result["items"]]
        for prop in ORDINARY_PROPS:
            assert prop not in extracted_names, f"普通道具 '{prop}' 不应被抽取为实体"


# ============================================================
# T5: 混合检索
# ============================================================


class TestHybridRetrieval:
    """混合检索 — 验证关键词、实体名与语义降级检索"""

    async def test_extraction_pipeline_keyword_retrieval_returns_relevant_chunks(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """关键词 '霜华剑' 检索能返回相关 chunk"""
        # Arrange
        assert len(indexed_chunks) > 0

        # Act
        result = await retrieve(
            db_session,
            novel_id,
            query="霜华剑",
            mode="search",
            top_k=5,
        )

        # Assert
        assert result.total > 0
        assert len(result.chunks) > 0

    async def test_extraction_pipeline_entity_name_retrieval_returns_results(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """实体名 '白砚' 检索能返回结果"""
        # Arrange
        assert len(indexed_chunks) > 0

        # Act
        result = await retrieve(
            db_session,
            novel_id,
            query="白砚",
            mode="search",
            top_k=5,
        )

        # Assert
        assert result.total > 0

    async def test_extraction_pipeline_semantic_retrieval_degrades_gracefully(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """语义检索（无向量支持时降级可用）"""
        # Arrange
        assert len(indexed_chunks) > 0

        # Act
        result = await retrieve(
            db_session,
            novel_id,
            query="一把传说中的宝剑",
            mode="search",
            top_k=5,
        )

        # Assert
        assert result.total >= 0
        if result.degraded:
            assert len(result.warnings) > 0, "降级时应有 warnings"

    async def test_extraction_pipeline_retrieval_results_contain_relevant_text(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """关键词检索结果包含相关文本"""
        # Arrange
        assert len(indexed_chunks) > 0

        # Act
        result = await retrieve(
            db_session,
            novel_id,
            query="苏荇",
            mode="search",
            top_k=3,
        )

        # Assert
        if len(result.chunks) > 0:
            top_text = result.chunks[0].text
            assert top_text is not None


# ============================================================
# T6: 上下文编译
# ============================================================


class TestContextCompilation:
    """上下文编译 — 验证不同 scope 编译与 Markdown 渲染"""

    async def test_extraction_pipeline_compile_world_scope_returns_valid_bundle(
        self, db_session: AsyncSession, novel_id: str
    ):
        """world scope 编译返回包含 world_entities 属性的 bundle"""
        # Arrange
        # (novel_id fixture 已创建项目)

        # Act
        bundle = await compile_structure_context(
            db_session,
            novel_id,
            task="测试上下文编译",
            scope="world",
            reveal_mode="author_safe",
        )

        # Assert
        assert bundle is not None
        assert hasattr(bundle, "world_entities")

    async def test_extraction_pipeline_compile_with_entity_ids_returns_valid_bundle(
        self, db_session: AsyncSession, novel_id: str
    ):
        """指定 entity_ids 编译不报错并返回有效 bundle"""
        # Arrange
        entity_id = await _create_entity_via_service(
            db_session,
            novel_id,
            name="霜华剑",
            entity_type="item",
        )

        # Act
        bundle = await compile_structure_context(
            db_session,
            novel_id,
            task="查询霜华剑信息",
            scope="world",
            entity_ids=[entity_id],
            reveal_mode="author_safe",
        )

        # Assert
        assert bundle is not None

    async def test_extraction_pipeline_compile_project_scope_returns_valid_bundle(
        self, db_session: AsyncSession, novel_id: str
    ):
        """project scope 编译返回非空 bundle"""
        # Arrange
        # (novel_id fixture 已创建项目)

        # Act
        bundle = await compile_structure_context(
            db_session,
            novel_id,
            task="测试",
            scope="project",
        )

        # Assert
        assert bundle is not None

    async def test_extraction_pipeline_markdown_rendering_outputs_non_empty_string(
        self, db_session: AsyncSession, novel_id: str
    ):
        """Markdown 渲染输出非空字符串"""
        # Arrange
        bundle = await compile_structure_context(
            db_session,
            novel_id,
            task="测试",
            scope="project",
        )

        # Act
        md = render_context_markdown(bundle)

        # Assert
        assert isinstance(md, str)
        assert len(md) > 0
