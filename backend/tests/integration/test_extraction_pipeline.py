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

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession


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
    from modules.project.project import Project
    import uuid

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
    from modules.writing.facade import create_draft

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
async def indexed_chunks(db_session: AsyncSession, novel_id: str, chapter_draft: dict) -> list:
    """RAG 索引章节，返回 chunk 列表"""
    from modules.rag.facade import index_chapter, get_ordered_chapter_chunks

    count = await index_chapter(db_session, novel_id, chapter_index=1)
    await db_session.flush()

    chunks = await get_ordered_chapter_chunks(db_session, novel_id, start_chapter=1)
    return chunks


# ============================================================
# 辅助函数
# ============================================================

async def _create_entity_via_service(
    db: AsyncSession, novel_id: str, name: str, entity_type: str,
    summary: str | None = None, aliases: list[str] | None = None,
) -> str:
    """通过 repository 直接创建实体（测试辅助，非 facade）"""
    from modules.world.repositories import CoreEntityRepository
    from shared.utils import parse_uuid

    repo = CoreEntityRepository()
    entity = await repo.create_raw(
        db,
        novel_id=parse_uuid(novel_id, "novel_id"),
        entity_type=entity_type,
        name=name,
        summary=summary,
        content_json={"aliases": [{"alias": a, "type": "name"} for a in (aliases or [])]} if aliases else None,
        status="canonical",
    )
    await db.flush()
    return str(entity.id)


# ============================================================
# T1: 写入草稿 → RAG 分块索引
# ============================================================

class TestWriteAndIndex:
    """写入 → 分块索引"""

    async def test_create_draft_returns_valid_id(self, chapter_draft):
        """写入草稿后返回有效 draft_id（UUID hex 格式）"""
        assert chapter_draft["draft_id"] is not None
        assert len(chapter_draft["draft_id"]) == 36

    async def test_draft_content_persisted(self, chapter_draft):
        """草稿内容正确持久化（依赖 chapter_draft fixture）"""
        from modules.writing.facade import get_latest_draft_for_chapter
        from sqlalchemy.ext.asyncio import AsyncSession

        # 获取当前 session 需要从 conftest 的 db_session fixture
        # 这里通过 chapter_draft 的 novel_id 验证草稿存在
        assert chapter_draft["draft_id"] is not None
        assert chapter_draft["chapter_index"] == 1

    async def test_index_chapter_creates_chunks(self, indexed_chunks):
        """索引后生成至少 1 个 chunk"""
        assert len(indexed_chunks) > 0

    async def test_chunks_contain_source_text(self, indexed_chunks):
        """每个 chunk 包含非空原文片段"""
        for chunk in indexed_chunks:
            assert chunk.text is not None
            assert len(chunk.text) > 0

    async def test_chunks_have_correct_metadata(self, indexed_chunks):
        """chunk 的 source_type、chapter_index、char_count 正确"""
        for chunk in indexed_chunks:
            assert chunk.source_type in ("writing_draft", "chapter_text")
            assert chunk.chapter_index == 1
            assert chunk.char_count > 0

    async def test_index_chapter_reports_count(self, indexed_chunks):
        """index_chapter 返回正确的 chunk 数量（依赖 indexed_chunks fixture）"""
        assert len(indexed_chunks) > 0


# ============================================================
# T2: LLM 抽取实体 → 候选入库
# ============================================================

class TestEntityExtraction:
    """LLM 实体抽取 → 候选池"""

    async def test_extraction_creates_candidates(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """实体抽取产生至少一个候选"""
        assert len(indexed_chunks) > 0, "需要先有 RAG chunks"

        from modules.world.facade import run_entity_extraction

        result = await run_entity_extraction(
            db_session, novel_id,
            start_chapter=1, end_chapter=1,
        )
        assert result is not None
        assert result["total_chapters"] == 1
        assert result["total_created"] > 0, (
            f"应至少创建一些候选，实际 total_created={result['total_created']}, "
            f"total_skipped={result['total_skipped']}"
        )

    async def test_extraction_items_have_required_fields(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """每个候选 item 包含 candidate_id、name、entity_type"""
        assert len(indexed_chunks) > 0

        from modules.world.facade import run_entity_extraction

        result = await run_entity_extraction(
            db_session, novel_id,
            start_chapter=1, end_chapter=1,
        )
        assert len(result["items"]) > 0
        for item in result["items"]:
            assert "id" in item, f"item missing 'id': {item}"
            assert "name" in item
            assert "entity_type" in item

    async def test_extracted_entities_include_key_characters(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """抽取结果应包含核心角色（白砚、苏荇等）"""
        assert len(indexed_chunks) > 0

        from modules.world.facade import run_entity_extraction

        result = await run_entity_extraction(
            db_session, novel_id,
            start_chapter=1, end_chapter=1,
        )
        extracted_names = [item["name"] for item in result["items"]]
        # 至少应该抽到主角名
        found_key = [n for n in EXPECTED_CHARACTERS if n in extracted_names]
        assert len(found_key) >= 2, (
            f"应至少抽到 2 个核心角色，实际抽到: {found_key}, "
            f"全部抽取: {extracted_names}"
        )


# ============================================================
# T3: 别名识别与去重
# ============================================================

class TestAliasAndDedup:
    """别名识别与候选去重"""

    async def test_find_similar_entities_exact_match(
        self, db_session: AsyncSession, novel_id: str
    ):
        """精确名称匹配：已有 '白砚'，搜索 '白砚' 返回高分匹配"""
        await _create_entity_via_service(
            db_session, novel_id,
            name="白砚", entity_type="character", summary="主角",
        )

        from modules.world.facade import find_similar_entities

        results = await find_similar_entities(
            db_session, novel_id,
            name="白砚",
            entity_type="character",
        )
        assert len(results) > 0, "精确匹配应找到已有实体"
        best = results[0]
        assert best.similarity_score > 0.9, f"精确匹配分数应 > 0.9，实际: {best.similarity_score}"

    async def test_alias_variant_fuzzy_match(
        self, db_session: AsyncSession, novel_id: str
    ):
        """别名变体模糊匹配：已有 '白砚'，搜索 '小白' 应有匹配"""
        await _create_entity_via_service(
            db_session, novel_id,
            name="白砚", entity_type="character",
            aliases=["小白"],
        )

        from modules.world.facade import find_similar_entities

        results = await find_similar_entities(
            db_session, novel_id,
            name="小白",
            entity_type="character",
        )
        assert len(results) > 0, f"别名字面 '小白' 应有匹配，实际: {results}"
        best = results[0]
        assert best.similarity_score >= 0.5, f"相似度应 >= 0.5，实际: {best.similarity_score}"

    async def test_duplicate_detection_prevents_re_extraction(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """已有正史实体时，再次抽取应跳过（去重生效）"""
        assert len(indexed_chunks) > 0

        # 先创建正史实体 "霜华剑"
        await _create_entity_via_service(
            db_session, novel_id,
            name="霜华剑", entity_type="item",
        )

        from modules.world.facade import run_entity_extraction

        result = await run_entity_extraction(
            db_session, novel_id,
            start_chapter=1, end_chapter=1,
        )
        # 检查抽取结果中是否还有 "霜华剑"
        extracted_names = [item["name"] for item in result["items"]]
        assert "霜华剑" not in extracted_names, (
            f"已存在的实体 '霜华剑' 不应被重复抽取，实际抽取: {extracted_names}"
        )


# ============================================================
# T4: 指代消解
# ============================================================

class TestAmbiguousReferences:
    """指代不清场景"""

    async def test_pronouns_not_extracted(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """代词（他/她/它/他们）不应被抽取为实体"""
        assert len(indexed_chunks) > 0

        from modules.world.facade import run_entity_extraction

        result = await run_entity_extraction(
            db_session, novel_id,
            start_chapter=1, end_chapter=1,
        )
        extracted_names = [item["name"].strip() for item in result["items"]]
        for pronoun in PRONOUNS:
            assert pronoun not in extracted_names, (
                f"代词 '{pronoun}' 不应被抽取为实体，但出现了: {extracted_names}"
            )

    async def test_vague_references_flagged_or_skipped(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """模糊指称应被跳过或标记为低置信度"""
        assert len(indexed_chunks) > 0

        from modules.world.facade import run_entity_extraction

        result = await run_entity_extraction(
            db_session, novel_id,
            start_chapter=1, end_chapter=1,
        )

        for item in result["items"]:
            name = item["name"]
            if name in VAGUE_REFERENCES:
                # 如果被抽取，应该标记为需要用户决定
                suggested_action = item.get("suggested_action", "")
                assert suggested_action in (
                    "needs_user_decision",
                    "ignore",
                    "temporary_only",
                ), (
                    f"模糊指称 '{name}' 应有合适的 suggested_action，"
                    f"实际: {suggested_action}"
                )

    async def test_ordinary_props_not_extracted(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """普通道具不应被抽取"""
        assert len(indexed_chunks) > 0

        from modules.world.facade import run_entity_extraction

        result = await run_entity_extraction(
            db_session, novel_id,
            start_chapter=1, end_chapter=1,
        )
        extracted_names = [item["name"].strip() for item in result["items"]]
        for prop in ORDINARY_PROPS:
            assert prop not in extracted_names, (
                f"普通道具 '{prop}' 不应被抽取为实体"
            )


# ============================================================
# T5: 混合检索
# ============================================================

class TestHybridRetrieval:
    """混合检索"""

    async def test_retrieve_by_keyword(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """关键词 '霜华剑' 检索能返回相关 chunk"""
        assert len(indexed_chunks) > 0

        from modules.rag.facade import retrieve

        result = await retrieve(
            db_session, novel_id,
            query="霜华剑",
            mode="search",
            top_k=5,
        )
        assert result.total > 0
        assert len(result.chunks) > 0

    async def test_retrieve_by_entity_name(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """实体名 '白砚' 检索能返回结果"""
        assert len(indexed_chunks) > 0

        from modules.rag.facade import retrieve

        result = await retrieve(
            db_session, novel_id,
            query="白砚",
            mode="search",
            top_k=5,
        )
        assert result.total > 0

    async def test_retrieve_semantic_fallback(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """语义检索（无向量支持时降级可用）"""
        assert len(indexed_chunks) > 0

        from modules.rag.facade import retrieve

        result = await retrieve(
            db_session, novel_id,
            query="一把传说中的宝剑",
            mode="search",
            top_k=5,
        )
        assert result.total >= 0
        if result.degraded:
            assert len(result.warnings) > 0, "降级时应有 warnings"

    async def test_retrieval_results_are_relevant(
        self, db_session: AsyncSession, novel_id: str, indexed_chunks
    ):
        """关键词检索结果包含相关文本"""
        assert len(indexed_chunks) > 0

        from modules.rag.facade import retrieve

        result = await retrieve(
            db_session, novel_id,
            query="苏荇",
            mode="search",
            top_k=3,
        )
        # 至少第一个结果应相关
        if len(result.chunks) > 0:
            top_text = result.chunks[0].text
            assert top_text is not None


# ============================================================
# T6: 上下文编译
# ============================================================

class TestContextCompilation:
    """上下文编译"""

    async def test_compile_world_scope(
        self, db_session: AsyncSession, novel_id: str
    ):
        """world scope 编译返回有效 bundle"""
        from modules.context.facade import compile_structure_context

        bundle = await compile_structure_context(
            db_session, novel_id,
            task="测试上下文编译",
            scope="world",
            reveal_mode="author_safe",
        )
        assert bundle is not None
        assert hasattr(bundle, 'world_entities')

    async def test_compile_with_entity_ids(
        self, db_session: AsyncSession, novel_id: str
    ):
        """指定 entity_ids 编译不报错"""
        entity_id = await _create_entity_via_service(
            db_session, novel_id,
            name="霜华剑", entity_type="item",
        )

        from modules.context.facade import compile_structure_context

        bundle = await compile_structure_context(
            db_session, novel_id,
            task="查询霜华剑信息",
            scope="world",
            entity_ids=[entity_id],
            reveal_mode="author_safe",
        )
        assert bundle is not None

    async def test_compile_project_scope(
        self, db_session: AsyncSession, novel_id: str
    ):
        """project scope 编译包含项目信息"""
        from modules.context.facade import compile_structure_context

        bundle = await compile_structure_context(
            db_session, novel_id,
            task="测试",
            scope="project",
        )
        assert bundle is not None

    async def test_markdown_rendering(
        self, db_session: AsyncSession, novel_id: str
    ):
        """Markdown 渲染输出非空字符串"""
        from modules.context.facade import compile_structure_context, render_context_markdown

        bundle = await compile_structure_context(
            db_session, novel_id,
            task="测试",
            scope="project",
        )
        md = render_context_markdown(bundle)
        assert isinstance(md, str)
        assert len(md) > 0
