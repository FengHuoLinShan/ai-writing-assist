"""
Context 模块测试

测试 Context Compiler 的核心逻辑：
1. 各 scope 编译正确性
2. Budget 控制
3. Reveal 模式过滤
4. Markdown 渲染
5. 无数据库时的优雅降级

Context 模块没有自己的数据表，它是纯组合层。
测试中确保即使数据库为空，编译器也能正常工作。
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import (
    CONTEXT_BUDGET,
    StructureContextBundle,
)
from modules.context.facade import (
    compile_structure_context,
    render_context_markdown,
)
from modules.context.markdown_renderer import render_context_markdown as render_md
from modules.context.services import CompileOptions

# ============================================================
# 基本导入测试
# ============================================================


class TestImports:
    """验证模块可正常导入"""

    def test_import_contracts(self) -> None:
        from modules.context.contracts import (
            AUTHOR_ONLY_WARNING,
            StructureContextBundle,
        )

        assert StructureContextBundle is not None
        assert AUTHOR_ONLY_WARNING
        assert isinstance(CONTEXT_BUDGET, dict)

    def test_import_schemas(self) -> None:
        from modules.context.schemas import (
            BudgetUsedItem,
            ContextCompileRequest,
            ContextCompileResponse,
            ContextRenderRequest,
            ContextRenderResponse,
        )

        assert ContextCompileRequest is not None
        assert ContextCompileResponse is not None
        assert ContextRenderRequest is not None
        assert ContextRenderResponse is not None
        assert BudgetUsedItem is not None

    def test_import_facade(self) -> None:
        from modules.context.facade import (
            compile_structure_context,
            render_context_markdown,
        )

        assert compile_structure_context is not None
        assert render_context_markdown is not None


# ============================================================
# StructureContextBundle 基础测试
# ============================================================


class TestStructureContextBundle:
    """测试 StructureContextBundle 数据结构"""

    def test_create_empty_bundle(self) -> None:
        """验证可以创建空 bundle"""
        bundle = StructureContextBundle(
            novel_id="test-novel-id",
            task="测试任务",
            scope="project",
        )
        assert bundle.novel_id == "test-novel-id"
        assert bundle.task == "测试任务"
        assert bundle.scope == "project"
        assert bundle.chapter_index is None
        assert bundle.world_entities == []
        assert bundle.characters == []
        assert bundle.warnings == []
        assert bundle.geo_filtered is False

    def test_create_full_bundle(self) -> None:
        """验证完整 bundle 创建"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="生成章节卡",
            scope="chapter",
            chapter_index=5,
            arc_id="arc-1",
            project={"title": "测试小说"},
            world_entities=[{"name": "王国", "entity_type": "location"}],
            characters=[{"name": "主角"}],
            geo_locations=[{"location": {"name": "王城"}}],
            memory_records=[{"summary": "主角出发了", "memory_type": "event"}],
            timeline_events=[{"title": "启程", "summary": "主角离开家乡"}],
            plot_threads=[{"name": "主线"}],
            outline_arc={"title": "第一卷"},
            chapter_card={"chapter_index": 5, "chapter_goal": "主角到达王城"},
            rag_chunks=[{"text": "王城描述", "source_type": "world_entity"}],
            reveal_mode="author_safe",
            budget_used={"core_entities": 3, "characters": 2},
            warnings=["测试警告"],
        )
        assert len(bundle.world_entities) == 1
        assert len(bundle.characters) == 1
        assert bundle.chapter_index == 5


# ============================================================
# Context Compiler 核心测试
# ============================================================


class TestContextCompiler:
    """测试 Context Compiler 核心逻辑"""

    @pytest.mark.asyncio
    async def test_compile_empty_db_project_scope(
        self,
        db_session: AsyncSession,
    ) -> None:
        """空数据库中 project scope 应优雅降级"""
        bundle = await compile_structure_context(
            db=db_session,
            novel_id="00000000-0000-0000-0000-000000000001",
            task="测试",
            scope="project",
        )
        assert bundle.novel_id == "00000000-0000-0000-0000-000000000001"
        assert bundle.scope == "project"
        assert bundle.project is None
        # 不应崩溃

    @pytest.mark.asyncio
    async def test_compile_empty_db_world_scope(
        self,
        db_session: AsyncSession,
    ) -> None:
        """空数据库中 world scope 应返回空列表"""
        bundle = await compile_structure_context(
            db=db_session,
            novel_id="00000000-0000-0000-0000-000000000002",
            task="测试世界",
            scope="world",
        )
        assert bundle.scope == "world"
        assert bundle.world_entities == []

    @pytest.mark.asyncio
    async def test_compile_empty_db_full_scope(
        self,
        db_session: AsyncSession,
    ) -> None:
        """空数据库中 full scope 不应崩溃，所有数据应为空"""
        bundle = await compile_structure_context(
            db=db_session,
            novel_id="00000000-0000-0000-0000-000000000003",
            task="完整测试",
            scope="full",
        )
        assert bundle.scope == "full"
        assert bundle.project is None
        assert bundle.world_entities == []
        assert bundle.characters == []
        assert bundle.geo_locations == []
        # memory_records 现在是全景 dict（启用后），空列表兜底也兼容
        assert isinstance(bundle.memory_records, (list, dict))
        assert bundle.timeline_events == []
        assert bundle.plot_threads == []
        assert bundle.outline_arc is None
        assert bundle.chapter_card is None
        assert bundle.rag_chunks == []

    @pytest.mark.asyncio
    async def test_compile_chapter_scope_no_chapter_index(
        self,
        db_session: AsyncSession,
    ) -> None:
        """chapter scope 不提供 chapter_index 应仍能工作"""
        bundle = await compile_structure_context(
            db=db_session,
            novel_id="00000000-0000-0000-0000-000000000004",
            task="生成章节卡",
            scope="chapter",
        )
        assert bundle.scope == "chapter"
        assert bundle.chapter_index is None
        assert bundle.chapter_card is None
        # 不应崩溃

    @pytest.mark.asyncio
    async def test_compile_with_entity_ids(
        self,
        db_session: AsyncSession,
    ) -> None:
        """指定 entity_ids 应正确传递"""
        bundle = await compile_structure_context(
            db=db_session,
            novel_id="00000000-0000-0000-0000-000000000005",
            task="测试",
            scope="world",
            entity_ids=["e1", "e2", "e3"],
        )
        assert bundle.scope == "world"
        # 数据库为空，所以不会返回数据
        # 但重要的是不崩溃

    @pytest.mark.asyncio
    async def test_compile_with_character_ids(
        self,
        db_session: AsyncSession,
    ) -> None:
        """指定 character_ids 应正确传递"""
        bundle = await compile_structure_context(
            db=db_session,
            novel_id="00000000-0000-0000-0000-000000000006",
            task="测试人物",
            scope="world_character",
            character_ids=["c1", "c2"],
        )
        assert bundle.scope == "world_character"

    @pytest.mark.asyncio
    async def test_compile_nonexistent_project(
        self,
        db_session: AsyncSession,
    ) -> None:
        """项目不存在时应有警告"""
        bundle = await compile_structure_context(
            db=db_session,
            novel_id="00000000-0000-0000-0000-000000000007",
            task="测试",
            scope="project",
        )
        # 项目不存在时 project 应为 None
        assert bundle.project is None


# ============================================================
# CompileOptions 测试
# ============================================================


class TestCompileOptions:
    """测试 CompileOptions 数据类"""

    def test_create_default(self) -> None:
        opts = CompileOptions(
            novel_id="test-id",
            task="测试",
            scope="project",
        )
        assert opts.novel_id == "test-id"
        assert opts.reveal_mode == "author_safe"
        assert opts.enable_geo_filter is False

    def test_create_full(self) -> None:
        opts = CompileOptions(
            novel_id="test-id",
            task="生成剧情线",
            scope="arc",
            chapter_index=3,
            arc_id="arc-1",
            entity_ids=["e1", "e2"],
            character_ids=["c1"],
            location_ids=["l1"],
            reveal_mode="author_full",
            enable_geo_filter=True,
        )
        assert opts.chapter_index == 3
        assert opts.arc_id == "arc-1"
        assert opts.reveal_mode == "author_full"
        assert opts.enable_geo_filter is True


# ============================================================
# Markdown 渲染测试
# ============================================================


class TestMarkdownRenderer:
    """测试 Markdown 渲染"""

    def test_render_empty_bundle(self) -> None:
        """空 bundle 应渲染为完整结构"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试任务",
            scope="project",
        )
        md = render_md(bundle)
        # 验证基本结构存在
        assert "# 结构化创作上下文" in md
        assert "一、当前任务" in md
        assert "二、必须遵守的硬约束" in md
        assert "三、当前剧情阶段" in md
        assert "四、相关人物" in md
        assert "五、相关世界对象" in md
        assert "六、相关地理与历史" in md
        assert "七、相关剧情线" in md
        assert "八、相关 Memory" in md
        assert "九、相关伏笔与信息揭示" in md
        assert "十、禁止事项" in md
        assert "十一、可用创作素材" in md
        assert "十二、风险提示" in md

    def test_render_task_section(self) -> None:
        """任务段落应显示任务信息"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="生成第 5 章章节卡",
            scope="chapter",
            chapter_index=5,
        )
        md = render_md(bundle)
        assert "生成第 5 章章节卡" in md
        assert "第 5 章" in md

    def test_render_with_project(self) -> None:
        """项目信息应出现在当前剧情阶段段落"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="project",
            project={
                "title": "星辰之旅",
                "genre": "科幻",
                "tone": "严肃",
                "current_stage": "outlining",
            },
        )
        md = render_md(bundle)
        assert "星辰之旅" in md
        assert "科幻" in md
        assert "outlining" in md

    def test_render_with_characters(self) -> None:
        """人物信息应出现在相关人物段落"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="world_character",
            characters=[
                {
                    "name": "林明",
                    "role": "protagonist",
                    "current_goal": "寻找失落的文明",
                    "current_state": "准备出发",
                    "stance": "正义",
                    "voice_style": "沉稳",
                    "character_id": "c1",
                },
            ],
        )
        md = render_md(bundle)
        assert "林明" in md
        assert "protagonist" in md
        assert "寻找失落的文明" in md
        assert "知识边界" in md

    def test_render_with_world_entities(self) -> None:
        """世界对象应出现在相关世界对象段落"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="world",
            world_entities=[
                {
                    "name": "艾尔王国",
                    "entity_type": "location",
                    "summary": "大陆中央的古老王国",
                    "public_info": "以魔法文明著称",
                    "importance_level": "core",
                },
                {
                    "name": "暗影组织",
                    "entity_type": "faction",
                    "summary": "秘密操控世界的组织",
                    "hidden_truth": "幕后黑手是王室",
                    "importance_level": "important",
                },
            ],
        )
        md = render_md(bundle)
        assert "艾尔王国" in md
        assert "暗影组织" in md
        assert "大陆中央的古老王国" in md

    def test_render_with_memory(self) -> None:
        """记忆应出现在 Memory 段落"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="full",
            memory_records=[
                {
                    "memory_type": "event",
                    "title": "主角出发",
                    "summary": "林明离开村庄开始冒险",
                    "chapter_index": 1,
                },
            ],
        )
        md = render_md(bundle)
        assert "主角出发" in md
        assert "林明离开村庄开始冒险" in md

    def test_render_with_plot_threads(self) -> None:
        """剧情线应出现在剧情线段落"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="full",
            plot_threads=[
                {
                    "name": "寻找神器",
                    "thread_type": "main",
                    "summary": "主角寻找失落神器的旅程",
                    "current_stage": "启程阶段",
                },
            ],
        )
        md = render_md(bundle)
        assert "寻找神器" in md
        assert "main" in md
        assert "启程阶段" in md

    def test_render_with_warnings(self) -> None:
        """警告应出现在风险提示段落"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="full",
            warnings=["加载 geo_locations 时出错: 连接超时"],
            budget_used={"core_entities": 8, "characters": 6},
        )
        md = render_md(bundle)
        assert "加载 geo_locations" in md


# ============================================================
# Static Renderer Tests (no DB needed)
# ============================================================


class TestFacadeRenderContextMarkdown:
    """测试 facade.render_context_markdown（静态渲染，无需 DB）"""

    def test_facade_render(self) -> None:
        """facade 的 render_context_markdown 应正常工作"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="静态渲染测试",
            scope="project",
        )
        md = render_context_markdown(bundle)
        assert isinstance(md, str)
        assert "静态渲染测试" in md

    def test_facade_render_with_data(self) -> None:
        """带数据的渲染"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="带数据渲染",
            scope="world_character",
            project={"title": "测试", "genre": "玄幻"},
            characters=[{"name": "张三", "role": "protagonist"}],
            world_entities=[
                {"name": "灵界", "entity_type": "location", "summary": "修炼世界"}
            ],
        )
        md = render_context_markdown(bundle)
        assert "测试" in md
        assert "张三" in md
        assert "灵界" in md


# ============================================================
# API Schema 测试
# ============================================================


class TestApiSchemas:
    """测试 API 请求/响应 Schema 校验"""

    def test_compile_request_valid(self) -> None:
        """有效请求应能创建"""
        from modules.context.schemas import ContextCompileRequest

        req = ContextCompileRequest(
            novel_id="test-id",
            task="测试任务",
            scope="chapter",
            chapter_index=5,
        )
        assert req.novel_id == "test-id"
        assert req.scope == "chapter"
        assert req.chapter_index == 5

    def test_compile_request_minimal(self) -> None:
        """最小请求"""
        from modules.context.schemas import ContextCompileRequest

        req = ContextCompileRequest(
            novel_id="test-id",
            task="测试",
            scope="project",
        )
        assert req.reveal_mode == "author_safe"

    def test_render_request_valid(self) -> None:
        """渲染请求校验"""
        from modules.context.schemas import ContextRenderRequest

        req = ContextRenderRequest(
            novel_id="test-id",
            task="生成剧情线",
            scope="arc",
            arc_id="arc-1",
        )
        assert req.arc_id == "arc-1"

    def test_budget_used_item(self) -> None:
        """预算使用明细"""
        from modules.context.schemas import BudgetUsedItem

        item = BudgetUsedItem(category="core_entities", budget=8, used=3)
        assert item.category == "core_entities"
        assert item.budget == 8
        assert item.used == 3


# ============================================================
# GeoReachabilityFilter 测试
# ============================================================
