"""
Context 模块单元测试

测试范围（Mock 模式，无需真实 DB）：
1. Loader 协议 (protocol.py)
2. ContextCompiler 调度逻辑 (context_compiler.py)
3. 各 Loader 加载逻辑 (services/loaders/*.py)
4. Facade 入口函数 (facade.py)
5. Markdown 渲染边界条件 (markdown_renderer.py)
6. API 路由 (api.py)
7. 契约边界条件 (contracts.py)
8. Schema 校验 (schemas.py)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from core.container import register, reset
from modules.context.contracts import (
    AUTHOR_ONLY_WARNING,
    CONTEXT_BUDGET,
    StructureContextBundle,
)
from modules.context.facade import (
    compile_structure_context,
    render_context_markdown,
)
from modules.context.schemas import (
    BudgetUsedItem,
    ContextCompileRequest,
    ContextRenderRequest,
    ContextRenderResponse,
    ContextSectionItem,
    ContextTierCompileResponse,
)
from modules.context.services import CompileOptions, ContextCompiler
from modules.context.services.compiled_context import (
    CompiledContext,
    ContextSection,
    Tier,
)
from modules.context.services.constraint_engine import ConstraintEngine
from modules.context.services.context_compiler import SCOPE_LOADERS
from modules.context.services.loaders import (
    CharactersLoader,
    EventsLoader,
    MemoryRecordsLoader,
    OutlineArcLoader,
    PlotThreadsLoader,
    ProjectLoader,
    RagChunksLoader,
    SceneLoader,
    WorldEntitiesLoader,
    is_loader_available,
)
from modules.context.services.protocol import Loader

# ============================================================
# 1. Loader 协议测试
# ============================================================


class TestLoaderProtocol:
    """验证 Loader ABC 协议定义"""

    def test_loader_is_abstract(self) -> None:
        """Loader 不能直接实例化"""
        with pytest.raises(TypeError):
            Loader()  # type: ignore[abstract]

    def test_concrete_loader_has_name(self) -> None:
        """验证所有具体 Loader 都有 name 属性"""
        loaders = [
            ProjectLoader(),
            WorldEntitiesLoader(),
            CharactersLoader(),
            EventsLoader(),
            MemoryRecordsLoader(),
            RagChunksLoader(),
            PlotThreadsLoader(),
            OutlineArcLoader(),
            SceneLoader(),
        ]
        expected_names = [
            "project",
            "world_entities",
            "characters",
            "events",
            "memory_records",
            "rag_chunks",
            "plot_threads",
            "outline_arc",
            "scene",
        ]
        for loader, expected_name in zip(loaders, expected_names):
            assert loader.name == expected_name, (
                f"{type(loader).__name__}.name != {expected_name}"
            )

    def test_all_loaders_available(self) -> None:
        """所有 loader 都应被注册为可用"""
        for name in SCOPE_LOADERS["full"]:
            assert is_loader_available(name), f"{name} should be available"

    def test_unknown_loader_not_available(self) -> None:
        """未知 loader 应返回 False"""
        assert not is_loader_available("nonexistent_loader")


# ============================================================
# 2. ContextCompiler 调度逻辑测试（Mock Loader）
# ============================================================


class TestContextCompilerDispatch:
    """测试 ContextCompiler 的 Loader 调度逻辑"""

    @pytest.mark.asyncio
    async def test_compile_dispatches_correct_loaders_by_scope(self) -> None:
        """不同 scope 应调度不同的 loader 集"""
        for scope, expected_loader_names in SCOPE_LOADERS.items():
            called_names: list[str] = []

            class SpyLoader(Loader):
                def __init__(self, name: str) -> None:
                    self._name = name

                @property
                def name(self) -> str:
                    return self._name

                async def load(self, db, options, bundle) -> None:
                    called_names.append(self._name)

            spy_loaders = [SpyLoader(n) for n in SCOPE_LOADERS["full"]]
            compiler = ContextCompiler(loaders=spy_loaders)

            options = CompileOptions(
                novel_id="test-id",
                task="测试",
                scope=scope,
            )
            await compiler.compile(db=MagicMock(), options=options)

            for name in expected_loader_names:
                assert name in called_names, f"{scope}: {name} was not called"

    @pytest.mark.asyncio
    async def test_compile_prerequisites_run_first(self) -> None:
        """前置 loader (project, world_entities) 应在其他 loader 之前执行"""
        execution_order: list[str] = []

        class OrderTracker(Loader):
            def __init__(self, name: str) -> None:
                self._name = name

            @property
            def name(self) -> str:
                return self._name

            async def load(self, db, options, bundle) -> None:
                execution_order.append(self._name)

        loaders = [
            OrderTracker("rag_chunks"),
            OrderTracker("project"),
            OrderTracker("world_entities"),
            OrderTracker("memory_records"),
        ]
        compiler = ContextCompiler(loaders=loaders)
        options = CompileOptions(
            novel_id="test-id",
            task="测试",
            scope="full",
        )
        await compiler.compile(db=MagicMock(), options=options)

        project_idx = execution_order.index("project")
        we_idx = execution_order.index("world_entities")
        rag_idx = execution_order.index("rag_chunks")
        mem_idx = execution_order.index("memory_records")

        assert project_idx < rag_idx, "project should run before dependent loaders"
        assert we_idx < rag_idx, "world_entities should run before dependent loaders"
        assert project_idx < mem_idx, "project should run before dependent loaders"
        assert we_idx < mem_idx, "world_entities should run before dependent loaders"

    @pytest.mark.asyncio
    async def test_compile_unknown_loader_adds_warning(self) -> None:
        """未知 loader 名称应产生警告"""
        with patch.dict(
            "modules.context.services.context_compiler.SCOPE_LOADERS",
            {"project": ["unknown_loader"]},
        ):
            compiler = ContextCompiler(loaders=[])
            options = CompileOptions(
                novel_id="test-id",
                task="测试",
                scope="project",
            )
            bundle = await compiler.compile(db=MagicMock(), options=options)
            assert any("未知的加载器" in w for w in bundle.warnings)

    @pytest.mark.asyncio
    async def test_compile_loader_error_adds_warning(self) -> None:
        """Loader 抛出异常应产生警告而非崩溃"""

        class FailingLoader(Loader):
            @property
            def name(self) -> str:
                return "project"

            async def load(self, db, options, bundle) -> None:
                raise RuntimeError("模拟加载失败")

        compiler = ContextCompiler(loaders=[FailingLoader()])
        options = CompileOptions(
            novel_id="test-id",
            task="测试",
            scope="project",
        )
        bundle = await compiler.compile(db=MagicMock(), options=options)
        assert any("模拟加载失败" in w for w in bundle.warnings)

    @pytest.mark.asyncio
    async def test_compile_dependent_loader_error_is_isolated(self) -> None:
        """一个 dependent loader 失败不应影响其他 loader"""
        results: dict[str, bool] = {}

        class BadLoader(Loader):
            @property
            def name(self) -> str:
                return "rag_chunks"

            async def load(self, db, options, bundle) -> None:
                raise ValueError("RAG 加载失败")

        class GoodLoader(Loader):
            @property
            def name(self) -> str:
                return "memory_records"

            async def load(self, db, options, bundle) -> None:
                results["memory_records"] = True

        compiler = ContextCompiler(
            loaders=[
                ProjectLoader(),
                WorldEntitiesLoader(),
                BadLoader(),
                GoodLoader(),
            ]
        )
        options = CompileOptions(
            novel_id="test-id",
            task="测试",
            scope="full",
        )
        bundle = await compiler.compile(db=MagicMock(), options=options)
        assert any("RAG 加载失败" in w for w in bundle.warnings)
        assert results.get("memory_records") is True

    def test_default_loaders_created(self) -> None:
        """默认 loaders 列表应包含所有 9 个 loader"""
        compiler = ContextCompiler()
        assert len(compiler._loaders) == 9
        for name in SCOPE_LOADERS["full"]:
            assert name in compiler._loaders


class TestCompileWithTiers:
    """测试 compile_with_tiers 入口与双模式输出"""

    @pytest.mark.asyncio
    async def test_compile_with_tiers_returns_compiled_context(self) -> None:
        """compile_with_tiers 应返回 CompiledContext，且包含 Tier 标注的段"""

        class DummyLoader(Loader):
            @property
            def name(self) -> str:
                return "project"

            async def load(self, db, options, bundle) -> None:
                bundle.project = {"title": "测试小说"}

        def _make_db():
            db = AsyncMock()
            execute_result = MagicMock()
            execute_result.scalars.return_value.all.return_value = []
            db.execute.return_value = execute_result
            return db

        compiler = ContextCompiler(loaders=[DummyLoader()])
        options = CompileOptions(
            novel_id=str(uuid.uuid4()),
            task="测试",
            scope="project",
        )
        result = await compiler.compile_with_tiers(db=_make_db(), options=options)
        assert hasattr(result, "sections")
        assert hasattr(result, "total_tokens")
        assert hasattr(result, "budget_tokens")
        assert any(s.tier == Tier.P0 for s in result.sections)

    @pytest.mark.asyncio
    async def test_writing_mode_prefixes_delta(self) -> None:
        """writing 模式应在 P1 段前加 [Delta 模式] 前缀"""

        class CharLoader(Loader):
            @property
            def name(self) -> str:
                return "characters"

            async def load(self, db, options, bundle) -> None:
                bundle.characters = [{"name": "主角"}]
                bundle.memory_records = [{"event": "测试事件"}]

        def _make_db():
            db = AsyncMock()
            execute_result = MagicMock()
            execute_result.scalars.return_value.all.return_value = []
            db.execute.return_value = execute_result
            return db

        compiler = ContextCompiler(loaders=[CharLoader()])
        options = CompileOptions(
            novel_id=str(uuid.uuid4()),
            task="测试",
            scope="world_character",
            mode="writing",
        )
        result = await compiler.compile_with_tiers(db=_make_db(), options=options)
        p1_sections = [s for s in result.sections if s.tier == Tier.P1]
        assert len(p1_sections) == 2
        keys = {s.key for s in p1_sections}
        assert "pov_knowledge" in keys
        assert "delta_timeline" in keys
        for s in p1_sections:
            assert s.content.startswith("[Delta 模式] "), (
                f"Expected Delta prefix, got: {s.content[:20]}"
            )

    @pytest.mark.asyncio
    async def test_debug_mode_prefixes_snapshot(self) -> None:
        """debug 模式应在 P1 段前加 [Snapshot 模式] 前缀"""

        class CharLoader(Loader):
            @property
            def name(self) -> str:
                return "characters"

            async def load(self, db, options, bundle) -> None:
                bundle.characters = [{"name": "主角"}]
                bundle.memory_records = [{"event": "测试事件"}]

        def _make_db():
            db = AsyncMock()
            execute_result = MagicMock()
            execute_result.scalars.return_value.all.return_value = []
            db.execute.return_value = execute_result
            return db

        compiler = ContextCompiler(loaders=[CharLoader()])
        options = CompileOptions(
            novel_id=str(uuid.uuid4()),
            task="测试",
            scope="world_character",
            mode="debug",
        )
        result = await compiler.compile_with_tiers(db=_make_db(), options=options)
        p1_sections = [s for s in result.sections if s.tier == Tier.P1]
        assert len(p1_sections) == 2
        keys = {s.key for s in p1_sections}
        assert "pov_knowledge" in keys
        assert "delta_timeline" in keys
        for s in p1_sections:
            assert s.content.startswith("[Snapshot 模式] "), (
                f"Expected Snapshot prefix, got: {s.content[:20]}"
            )


class TestNineTierIR:
    """测试 9-tier IR 构建与预算跟踪"""

    def test_build_sections_produces_eight_data_keys(self) -> None:
        """_build_sections 在数据完整时应产出 8 个数据段

        第 9 段 hard_constraints 由 ConstraintEngine 在完整 compile_with_tiers
        流程中追加，因此不在 _build_sections 输出里。
        """
        bundle = StructureContextBundle(
            novel_id="id",
            task="创作目标",
            scope="full",
            scene={"id": "s1", "scene_index": 1, "pov_character_id": "c1"},
            characters=[{"name": "主角"}],
            memory_records=[{"event": "失忆"}],
            plot_threads=[{"name": "主线"}],
            rag_chunks=[{"text": "证据"}],
            project={"title": "小说"},
            warnings=["注意"],
        )
        compiler = ContextCompiler(loaders=[])
        sections = compiler._build_sections(bundle)
        keys = [s.key for s in sections]
        expected_keys = [
            "writing_objective",
            "scene_blueprint",
            "pov_knowledge",
            "delta_timeline",
            "open_narrative_obligations",
            "retrieval_evidence_packs",
            "style_assets",
            "compiler_warnings",
        ]
        assert len(sections) == 8
        assert keys == expected_keys
        for s in sections:
            assert s.token_count > 0

    def test_scene_blueprint_uses_bundle_scene(self) -> None:
        """scene_blueprint 应使用 bundle.scene 而非 chapter_card"""
        bundle = StructureContextBundle(
            novel_id="id",
            task="t",
            scope="chapter",
            scene={"id": "s1", "scene_index": 5},
            chapter_card={"title": "章节卡"},
        )
        compiler = ContextCompiler(loaders=[])
        sections = compiler._build_sections(bundle)
        blueprint = next(s for s in sections if s.key == "scene_blueprint")
        assert '"id": "s1"' in blueprint.content
        assert '"scene_index": 5' in blueprint.content
        assert "章节卡" not in blueprint.content

    def test_enforce_budget_tracks_evicted_keys(self) -> None:
        """P4/P3 被整体淘汰时应记录 evicted_keys"""
        sections = [
            ContextSection(
                key="writing_objective",
                tier=Tier.P0,
                content="目标",
                token_count=10,
            ),
            ContextSection(
                key="style_assets",
                tier=Tier.P3,
                content="风格" * 100,
                token_count=200,
            ),
            ContextSection(
                key="compiler_warnings",
                tier=Tier.P4,
                content="警告" * 100,
                token_count=200,
            ),
        ]
        ctx = CompiledContext(sections=sections, total_tokens=410, budget_tokens=20)
        result = ctx.enforce_budget()
        assert "style_assets" in result.evicted_keys
        assert "compiler_warnings" in result.evicted_keys
        assert result.total_tokens <= 20

    def test_enforce_budget_tracks_p2_truncated_keys(self) -> None:
        """P2 逐条截断时应记录 truncated_keys"""
        p2_content = "\n".join(f"item-{i:02d}" for i in range(20))
        sections = [
            ContextSection(
                key="writing_objective",
                tier=Tier.P0,
                content="目标",
                token_count=10,
            ),
            ContextSection(
                key="open_narrative_obligations",
                tier=Tier.P2,
                content=p2_content,
                token_count=200,
                truncatable_per_item=True,
            ),
        ]
        ctx = CompiledContext(sections=sections, total_tokens=210, budget_tokens=30)
        result = ctx.enforce_budget()
        assert "open_narrative_obligations" in result.truncated_keys
        assert result.total_tokens <= 30

    def test_enforce_budget_tracks_p1_truncated_keys(self) -> None:
        """P1 Delta 压缩时应记录 truncated_keys"""
        p1_content = "\n".join(f"delta-{i:02d}" for i in range(20))
        sections = [
            ContextSection(
                key="writing_objective",
                tier=Tier.P0,
                content="目标",
                token_count=10,
            ),
            ContextSection(
                key="delta_timeline",
                tier=Tier.P1,
                content=p1_content,
                token_count=200,
            ),
        ]
        ctx = CompiledContext(sections=sections, total_tokens=210, budget_tokens=50)
        result = ctx.enforce_budget()
        assert "delta_timeline" in result.truncated_keys
        assert result.total_tokens <= 50


class TestConstraintEngine:
    """测试 ConstraintEngine 场景化约束编译"""

    @pytest.mark.asyncio
    async def test_foreshadowing_with_future_payoff_scene_included(self) -> None:
        """planned_payoff_scene 大于当前 scene_index 的伏笔应进入约束"""
        engine = ConstraintEngine()
        novel_id = str(uuid.uuid4())
        plans = [
            {
                "name": "戒指伏笔",
                "surface_meaning": "主角捡到戒指",
                "planned_payoff_scene": 5,
            }
        ]
        db = MagicMock()
        with (
            patch(
                "modules.outline.facade.get_active_foreshadowing",
                AsyncMock(return_value=plans),
            ),
            patch(
                "modules.outline.facade.get_scene_contract",
                AsyncMock(return_value=None),
            ),
            patch(
                "modules.world.facade.get_character_knowledge_entries",
                AsyncMock(return_value=[]),
            ),
        ):
            sections = await engine.compile_constraints(
                db, novel_id, scene_index=3, chapter_index=1
            )
        keys = {s.key for s in sections}
        assert "foreshadowing_constraints" in keys
        fore = next(s for s in sections if s.key == "foreshadowing_constraints")
        assert "戒指伏笔" in fore.content
        assert "场景5" in fore.content
        assert fore.tier == Tier.P0

    @pytest.mark.asyncio
    async def test_foreshadowing_with_past_payoff_scene_excluded(self) -> None:
        """planned_payoff_scene 小于等于当前 scene_index 的伏笔不应进入约束"""
        engine = ConstraintEngine()
        novel_id = str(uuid.uuid4())
        plans = [
            {
                "name": "已到期伏笔",
                "surface_meaning": "伏笔已收回",
                "planned_payoff_scene": 2,
            }
        ]
        db = MagicMock()
        with (
            patch(
                "modules.outline.facade.get_active_foreshadowing",
                AsyncMock(return_value=plans),
            ),
            patch(
                "modules.outline.facade.get_scene_contract",
                AsyncMock(return_value=None),
            ),
            patch(
                "modules.world.facade.get_character_knowledge_entries",
                AsyncMock(return_value=[]),
            ),
        ):
            sections = await engine.compile_constraints(
                db, novel_id, scene_index=3, chapter_index=1
            )
        keys = {s.key for s in sections}
        assert "foreshadowing_constraints" not in keys

    @pytest.mark.asyncio
    async def test_foreshadowing_fallback_to_chapter_index(self) -> None:
        """无 scene_index 时按 chapter_index 过滤"""
        engine = ConstraintEngine()
        novel_id = str(uuid.uuid4())
        plans = [
            {
                "name": "章级伏笔",
                "surface_meaning": "主角发现地图",
                "planned_payoff_chapter": 10,
            }
        ]
        db = MagicMock()
        with (
            patch(
                "modules.outline.facade.get_active_foreshadowing",
                AsyncMock(return_value=plans),
            ),
            patch(
                "modules.outline.facade.get_scene_contract",
                AsyncMock(return_value=None),
            ),
            patch(
                "modules.world.facade.get_character_knowledge_entries",
                AsyncMock(return_value=[]),
            ),
        ):
            sections = await engine.compile_constraints(db, novel_id, chapter_index=5)
        keys = {s.key for s in sections}
        assert "foreshadowing_constraints" in keys
        fore = next(s for s in sections if s.key == "foreshadowing_constraints")
        assert "章级伏笔" in fore.content
        assert "第10章" in fore.content

    @pytest.mark.asyncio
    async def test_scene_must_not_happen_in_hard_constraints(self) -> None:
        """Scene 的 must_not_happen 应作为 scene_constraints 进入 P0"""
        engine = ConstraintEngine()
        novel_id = str(uuid.uuid4())
        scene = {"id": "s1", "must_not_happen": "主角不能死亡"}
        db = MagicMock()
        with (
            patch(
                "modules.outline.facade.get_scene_contract",
                AsyncMock(return_value=scene),
            ),
            patch(
                "modules.outline.facade.get_active_foreshadowing",
                AsyncMock(return_value=[]),
            ),
            patch(
                "modules.world.facade.get_character_knowledge_entries",
                AsyncMock(return_value=[]),
            ),
        ):
            sections = await engine.compile_constraints(
                db, novel_id, scene_id="s1", scene_index=3
            )
        keys = {s.key for s in sections}
        assert "scene_constraints" in keys
        scene_section = next(s for s in sections if s.key == "scene_constraints")
        assert "主角不能死亡" in scene_section.content
        assert scene_section.tier == Tier.P0

    @pytest.mark.asyncio
    async def test_knowledge_restricted_and_misunderstood(self) -> None:
        """knowledge_level=restricted 和 misunderstood 应出现在约束中"""
        engine = ConstraintEngine()
        novel_id = str(uuid.uuid4())
        entries = [
            {
                "target_type": "character",
                "target_id": "c1",
                "knowledge_level": "restricted",
            },
            {
                "target_type": "entity",
                "target_id": "e1",
                "knowledge_level": "misunderstood",
                "misconception": "误以为神器是坏的",
            },
        ]
        db = MagicMock()
        with (
            patch(
                "modules.world.facade.get_character_knowledge_entries",
                AsyncMock(return_value=entries),
            ),
            patch(
                "modules.outline.facade.get_scene_contract",
                AsyncMock(return_value=None),
            ),
            patch(
                "modules.outline.facade.get_active_foreshadowing",
                AsyncMock(return_value=[]),
            ),
        ):
            sections = await engine.compile_constraints(db, novel_id)
        keys = {s.key for s in sections}
        assert "knowledge_constraints" in keys
        knowledge = next(s for s in sections if s.key == "knowledge_constraints")
        assert "知识受限" in knowledge.content
        assert "hidden_truth" in knowledge.content
        assert "误以为神器是坏的" in knowledge.content
        assert knowledge.tier == Tier.P0


# ============================================================
# 3. 各 Loader 加载逻辑测试（Mock Facade）
# ============================================================


class TestProjectLoader:
    """测试 ProjectLoader"""

    @pytest.mark.asyncio
    async def test_load_populates_project(self) -> None:
        """加载成功应设置 bundle.project"""
        mock_ctx = MagicMock()
        mock_ctx.model_dump.return_value = {"title": "测试小说", "genre": "科幻"}

        loader = ProjectLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="project")

        with patch(
            "modules.context.services.loaders.project_loader.get_project_context",
            AsyncMock(return_value=mock_ctx),
        ):
            await loader.load(
                db=MagicMock(), options=MagicMock(novel_id="id"), bundle=bundle
            )

        assert bundle.project == {"title": "测试小说", "genre": "科幻"}

    @pytest.mark.asyncio
    async def test_load_project_not_found_adds_warning(self) -> None:
        """项目不存在应添加警告"""
        loader = ProjectLoader()
        bundle = StructureContextBundle(novel_id="nonexistent", task="t", scope="project")

        with patch(
            "modules.context.services.loaders.project_loader.get_project_context",
            AsyncMock(return_value=None),
        ):
            await loader.load(
                db=MagicMock(),
                options=MagicMock(novel_id="nonexistent"),
                bundle=bundle,
            )

        assert bundle.project is None
        assert any("不存在" in w for w in bundle.warnings)


class TestWorldEntitiesLoader:
    """测试 WorldEntitiesLoader"""

    @pytest.mark.asyncio
    async def test_load_with_entity_ids(self) -> None:
        """指定 entity_ids 时应按重要性排序并分割 core/normal"""
        mock_entity = MagicMock()
        mock_entity.model_dump.return_value = {
            "name": "测试物品",
            "entity_type": "item",
            "importance": 0.9,
            "importance_level": "core",
        }
        mock_ctx = MagicMock()
        mock_ctx.entities = [mock_entity]

        loader = WorldEntitiesLoader()
        bundle = StructureContextBundle(
            novel_id="id",
            task="t",
            scope="world",
        )
        options = MagicMock(
            novel_id="id",
            reveal_mode="author_safe",
            entity_ids=["e1"],
            enable_geo_filter=False,
        )

        with patch(
            "modules.world.facade.get_world_context",
            AsyncMock(return_value=mock_ctx),
        ):
            await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert len(bundle.world_entities) == 1
        assert bundle.budget_used["core_entities"] == 1

    @pytest.mark.asyncio
    async def test_load_without_entity_ids_sorts_by_importance(self) -> None:
        """未指定 entity_ids 时应按重要性排序"""
        mock_ctx = MagicMock()
        mock_ctx.entities = [
            MagicMock(
                model_dump=lambda: {
                    "name": "低重要性",
                    "entity_type": "item",
                    "importance": 0.3,
                    "importance_level": "normal",
                }
            ),
            MagicMock(
                model_dump=lambda: {
                    "name": "高重要性",
                    "entity_type": "location",
                    "importance": 0.9,
                    "importance_level": "core",
                }
            ),
        ]
        loader = WorldEntitiesLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="world")
        options = MagicMock(
            novel_id="id",
            reveal_mode="author_safe",
            entity_ids=None,
            enable_geo_filter=False,
        )

        with patch(
            "modules.world.facade.get_world_context",
            AsyncMock(return_value=mock_ctx),
        ):
            await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert len(bundle.world_entities) == 2
        assert bundle.world_entities[0]["name"] == "高重要性"
        assert bundle.budget_used["core_entities"] == 1
        assert bundle.budget_used["normal_entities"] == 1

    @pytest.mark.asyncio
    async def test_reveal_mode_author_safe_annotates_hidden_truth(self) -> None:
        """author_safe 模式应标注 hidden_truth"""
        mock_ctx = MagicMock()
        mock_ctx.entities = [
            MagicMock(
                model_dump=lambda: {
                    "name": "秘密",
                    "entity_type": "faction",
                    "importance": 0.8,
                    "importance_level": "core",
                    "hidden_truth": "这是隐藏真相",
                }
            ),
        ]
        loader = WorldEntitiesLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="world")
        options = MagicMock(
            novel_id="id",
            reveal_mode="author_safe",
            entity_ids=None,
            enable_geo_filter=False,
        )

        with patch(
            "modules.world.facade.get_world_context",
            AsyncMock(return_value=mock_ctx),
        ):
            await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert AUTHOR_ONLY_WARNING in bundle.world_entities[0]["hidden_truth"]


class TestCharactersLoader:
    """测试 CharactersLoader"""

    @pytest.mark.asyncio
    async def test_load_with_character_ids(self) -> None:
        """指定 character_ids 时应加载对应人物"""
        mock_char = MagicMock()
        mock_char.model_dump.return_value = {
            "name": "主角",
            "role": "protagonist",
            "character_id": "c1",
        }
        mock_ctx = MagicMock()
        mock_ctx.characters = [mock_char]

        loader = CharactersLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="world_character")
        options = MagicMock(
            novel_id="id",
            reveal_mode="author_safe",
            character_ids=["c1"],
            scope="world_character",
        )

        with patch(
            "modules.world.facade.get_characters_context",
            AsyncMock(return_value=mock_ctx),
        ):
            await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert len(bundle.characters) == 1
        assert bundle.characters[0]["name"] == "主角"
        assert bundle.budget_used["characters"] == 1

    @pytest.mark.asyncio
    async def test_load_without_ids_returns_empty(self) -> None:
        """未指定 character_ids 且没有推断来源时应返回空"""
        loader = CharactersLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="world_character")
        options = MagicMock(
            novel_id="id",
            reveal_mode="author_safe",
            character_ids=None,
            scene_id=None,
            scope="world_character",
        )

        await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert bundle.characters == []

    @pytest.mark.asyncio
    async def test_infer_from_scene_pov(self) -> None:
        """未指定 character_ids 时应从 Scene POV 推断人物"""
        mock_char = MagicMock()
        mock_char.model_dump.return_value = {
            "name": "主角",
            "role": "protagonist",
            "character_id": "c1",
        }
        mock_ctx = MagicMock()
        mock_ctx.characters = [mock_char]

        loader = CharactersLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="chapter")
        options = MagicMock(
            novel_id="id",
            reveal_mode="author_safe",
            character_ids=None,
            scene_id="s1",
            scope="chapter",
        )

        with (
            patch(
                "modules.outline.facade.get_scene_contract",
                AsyncMock(return_value={"pov_character_id": "c1"}),
            ),
            patch(
                "modules.world.facade.get_characters_context",
                AsyncMock(return_value=mock_ctx),
            ),
        ):
            await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert len(bundle.characters) == 1
        assert bundle.characters[0]["name"] == "主角"

    @pytest.mark.asyncio
    async def test_infer_from_world_entities(self) -> None:
        """没有 Scene POV 和 character_ids 时应从世界实体推断人物"""
        mock_char = MagicMock()
        mock_char.model_dump.return_value = {
            "name": "配角",
            "role": "supporting",
            "character_id": "c2",
        }
        mock_ctx = MagicMock()
        mock_ctx.characters = [mock_char]

        loader = CharactersLoader()
        bundle = StructureContextBundle(
            novel_id="id",
            task="t",
            scope="world",
            world_entities=[
                {"entity_type": "character", "entity_id": "c2", "name": "配角"}
            ],
        )
        options = MagicMock(
            novel_id="id",
            reveal_mode="author_safe",
            character_ids=None,
            scene_id=None,
            scope="world",
        )

        with patch(
            "modules.world.facade.get_characters_context",
            AsyncMock(return_value=mock_ctx),
        ):
            await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert len(bundle.characters) == 1
        assert bundle.characters[0]["name"] == "配角"

    @pytest.mark.asyncio
    async def test_character_knowledge_filter_called(self) -> None:
        """character reveal 模式且 scope 非 project 时应调用知识边界过滤"""
        mock_char = MagicMock()
        mock_char.model_dump.return_value = {
            "name": "主角",
            "role": "protagonist",
            "character_id": "c1",
        }
        mock_ctx = MagicMock()
        mock_ctx.characters = [mock_char]

        loader = CharactersLoader()
        bundle = StructureContextBundle(
            novel_id="id",
            task="t",
            scope="world_character",
            world_entities=[{"name": "秘密", "entity_type": "secret"}],
        )
        options = MagicMock(
            novel_id="id",
            reveal_mode="character",
            viewpoint_character_id="c1",
            character_ids=["c1"],
            scope="world_character",
        )

        with (
            patch(
                "modules.world.facade.get_characters_context",
                AsyncMock(return_value=mock_ctx),
            ),
            patch(
                "modules.world.facade.filter_context_by_character_knowledge",
                AsyncMock(return_value=[]),
            ),
        ):
            await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert bundle.world_entities == []


class TestSceneLoader:
    """测试 SceneLoader"""

    @pytest.mark.asyncio
    async def test_load_without_scene_id_skips(self) -> None:
        """未提供 scene_id 时应直接返回"""
        loader = SceneLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="chapter")
        options = MagicMock(scene_id=None)

        await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert bundle.scene is None
        assert bundle.warnings == []

    @pytest.mark.asyncio
    async def test_load_missing_scene_adds_warning(self) -> None:
        """Scene 不存在时应添加警告"""
        loader = SceneLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="chapter")
        options = MagicMock(scene_id="missing", viewpoint_character_id=None)

        with patch(
            "modules.outline.facade.get_scene_contract",
            AsyncMock(return_value=None),
        ):
            await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert bundle.scene is None
        assert any("missing" in w for w in bundle.warnings)

    @pytest.mark.asyncio
    async def test_load_populates_scene(self) -> None:
        """加载成功应设置 bundle.scene"""
        loader = SceneLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="chapter")
        options = MagicMock(scene_id="s1", viewpoint_character_id=None)

        with patch(
            "modules.outline.facade.get_scene_contract",
            AsyncMock(return_value={"id": "s1", "pov_character_id": "c1"}),
        ):
            await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert bundle.scene == {"id": "s1", "pov_character_id": "c1"}
        assert any("POV" in w for w in bundle.warnings)

    @pytest.mark.asyncio
    async def test_load_with_viewpoint_no_warning(self) -> None:
        """已指定视角人物时不应产生 POV 警告"""
        loader = SceneLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="chapter")
        options = MagicMock(scene_id="s1", viewpoint_character_id="c1")

        with patch(
            "modules.outline.facade.get_scene_contract",
            AsyncMock(return_value={"id": "s1", "pov_character_id": "c1"}),
        ):
            await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert bundle.scene == {"id": "s1", "pov_character_id": "c1"}
        assert not any("POV" in w for w in bundle.warnings)


class TestEventsLoader:
    """测试 EventsLoader"""

    @pytest.mark.asyncio
    async def test_load_events(self) -> None:
        """应加载时间线事件"""
        mock_event = MagicMock()
        mock_event.model_dump.return_value = {
            "id": "evt1",
            "title": "大战",
            "summary": "一场大战",
        }
        mock_ctx = MagicMock()
        mock_ctx.events = [mock_event]

        loader = EventsLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="full")
        options = MagicMock(novel_id="id", entity_ids=None)

        with patch(
            "modules.world.facade.get_events_context",
            AsyncMock(return_value=mock_ctx),
        ):
            await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert len(bundle.timeline_events) == 1
        assert bundle.timeline_events[0]["title"] == "大战"
        assert bundle.budget_used["timeline"] == 1


class TestMemoryRecordsLoader:
    """测试 MemoryRecordsLoader"""

    @pytest.mark.asyncio
    async def test_load_panorama_success(self) -> None:
        """加载成功应注入全景数据"""
        mock_panorama = MagicMock()
        mock_panorama.model_dump.return_value = {"entities": [], "relations": []}
        mock_panorama.entities = []

        loader = MemoryRecordsLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="full")
        options = MagicMock(novel_id="id", chapter_index=3)

        with patch(
            "modules.memory.services.MemoryService.get_panorama",
            AsyncMock(return_value=mock_panorama),
        ):
            await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert isinstance(bundle.memory_records, dict)
        assert bundle.budget_used["memory"] == 0

    @pytest.mark.asyncio
    async def test_load_panorama_failure_graceful(self) -> None:
        """加载失败应优雅降级为空列表"""
        loader = MemoryRecordsLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="full")
        options = MagicMock(novel_id="id", chapter_index=1)

        with patch(
            "modules.memory.services.MemoryService.get_panorama",
            AsyncMock(side_effect=RuntimeError("DB connection failed")),
        ):
            await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert bundle.memory_records == []
        assert bundle.budget_used["memory"] == 0


class TestRagChunksLoader:
    """测试 RagChunksLoader"""

    @pytest.mark.asyncio
    async def test_load_rag_chunks(self) -> None:
        """应加载 RAG 检索片段"""
        mock_chunk = MagicMock()
        mock_chunk.model_dump.return_value = {
            "text": "相关文章内容",
            "score": 0.85,
            "source_type": "world_entity",
        }
        mock_result = MagicMock()
        mock_result.chunks = [mock_chunk]

        loader = RagChunksLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="full")
        options = MagicMock(
            novel_id="id",
            task="生成章节",
            reveal_mode="author_safe",
            entity_ids=None,
            character_ids=None,
            chapter_index=1,
            top_k=8,
        )

        with patch(
            "modules.rag.facade.retrieve",
            AsyncMock(return_value=mock_result),
        ):
            await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert len(bundle.rag_chunks) == 1
        assert bundle.rag_chunks[0]["score"] == 0.85
        assert bundle.budget_used["rag_chunks"] == 1

    @pytest.mark.asyncio
    async def test_reader_mode_passes_visibility(self) -> None:
        """reader 模式应传递 visibility=reader_known"""
        mock_result = MagicMock()
        mock_result.chunks = []

        loader = RagChunksLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="full")
        options = MagicMock(
            novel_id="id",
            task="test",
            reveal_mode="reader",
            entity_ids=None,
            character_ids=None,
            chapter_index=1,
            top_k=8,
        )

        with patch(
            "modules.rag.facade.retrieve",
            AsyncMock(return_value=mock_result),
        ) as mock_retrieve:
            await loader.load(db=MagicMock(), options=options, bundle=bundle)
            _, kwargs = mock_retrieve.call_args
            assert kwargs.get("visibility") == "reader_known"

    @pytest.mark.asyncio
    async def test_top_k_caps_chunks(self) -> None:
        """top_k 应限制返回的 chunks 数量"""
        chunks = []
        for i in range(5):
            mock_chunk = MagicMock()
            mock_chunk.model_dump.return_value = {"text": f"chunk{i}", "score": 0.9}
            chunks.append(mock_chunk)
        mock_result = MagicMock()
        mock_result.chunks = chunks

        loader = RagChunksLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="full")
        options = MagicMock(
            novel_id="id",
            task="test",
            reveal_mode="author_safe",
            entity_ids=None,
            character_ids=None,
            chapter_index=1,
            top_k=2,
        )

        with patch(
            "modules.rag.facade.retrieve",
            AsyncMock(return_value=mock_result),
        ):
            await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert len(bundle.rag_chunks) == 2
        assert bundle.budget_used["rag_chunks"] == 2


class TestPlotThreadsLoader:
    """测试 PlotThreadsLoader"""

    def setup_method(self):
        reset()

    def teardown_method(self):
        reset()

    @pytest.mark.asyncio
    async def test_load_plot_threads(self) -> None:
        """应加载剧情线数据"""
        mock_thread = MagicMock()
        mock_thread.id = "t1"
        mock_thread.name = "主线"
        mock_thread.thread_type = "main"
        mock_thread.summary = "主角的旅程"
        mock_thread.visible_goal = "找到神器"
        mock_thread.hidden_truth = ""
        mock_thread.start_chapter = 1
        mock_thread.planned_payoff_chapter = 10
        mock_thread.current_stage = "启程"
        mock_thread.reader_known_state = ""
        mock_thread.author_known_state = ""
        mock_thread.status = "active"

        mock_svc = MagicMock()
        mock_svc.get_active = AsyncMock(return_value=[mock_thread])
        register("outline.thread_service", mock_svc)

        loader = PlotThreadsLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="full")
        options = MagicMock(novel_id="id", chapter_index=5)

        await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert len(bundle.plot_threads) == 1
        assert bundle.plot_threads[0]["name"] == "主线"
        assert bundle.plot_threads[0]["thread_type"] == "main"


class TestOutlineArcLoader:
    """测试 OutlineArcLoader"""

    def setup_method(self):
        reset()

    def teardown_method(self):
        reset()

    @pytest.mark.asyncio
    async def test_load_arc_with_chapter(self) -> None:
        """提供 chapter_index 时应加载篇章信息"""
        mock_arc = MagicMock()
        mock_arc.id = "arc1"
        mock_arc.title = "第一卷"
        mock_arc.arc_index = 1
        mock_arc.start_chapter = 1
        mock_arc.end_chapter = 10
        mock_arc.arc_goal = "建立世界观"
        mock_arc.core_conflict = "正邪对抗"
        mock_arc.main_opposition = ""
        mock_arc.entry_hook = ""
        mock_arc.midpoint_turn = ""
        mock_arc.climax = ""
        mock_arc.result = ""
        mock_arc.next_hook = ""
        mock_arc.status = "active"

        mock_svc = MagicMock()
        mock_svc.get_by_chapter = AsyncMock(return_value=mock_arc)
        register("outline.arc_service", mock_svc)

        loader = OutlineArcLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="full")
        options = MagicMock(novel_id="id", chapter_index=5)

        await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert bundle.outline_arc is not None
        assert bundle.outline_arc["title"] == "第一卷"
        assert bundle.outline_arc["arc_goal"] == "建立世界观"

    @pytest.mark.asyncio
    async def test_load_arc_no_chapter_returns_none(self) -> None:
        """未提供 chapter_index 应跳过"""
        loader = OutlineArcLoader()
        bundle = StructureContextBundle(novel_id="id", task="t", scope="full")
        options = MagicMock(novel_id="id", chapter_index=None)

        await loader.load(db=MagicMock(), options=options, bundle=bundle)

        assert bundle.outline_arc is None


# ============================================================
# 4. Facade 函数测试
# ============================================================


class TestFacade:
    """测试 facade 入口函数"""

    def test_render_context_markdown_static(self) -> None:
        """render_context_markdown 应委托给 markdown_renderer"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试渲染",
            scope="project",
        )
        md = render_context_markdown(bundle)
        assert "# 结构化创作上下文" in md
        assert "测试渲染" in md

    @pytest.mark.asyncio
    async def test_compile_structure_context_delegates_to_compiler(self) -> None:
        """compile_structure_context 应构造 CompileOptions 并调用 compiler.compile"""
        from modules.context import facade as ctx_facade

        mock_bundle = StructureContextBundle(
            novel_id="id",
            task="test",
            scope="project",
        )

        with patch.object(
            ctx_facade._compiler,
            "compile",
            AsyncMock(return_value=mock_bundle),
        ) as mock_compile:
            result = await compile_structure_context(
                db=MagicMock(),
                novel_id="id",
                task="test",
                scope="project",
            )

            assert result.novel_id == "id"
            mock_compile.assert_awaited_once()


# ============================================================
# 5. Markdown 渲染边界条件
# ============================================================


class TestMarkdownRendererEdgeCases:
    """测试 Markdown 渲染器边界条件"""

    def test_render_with_panorama_memory_format(self) -> None:
        """全景 dict 格式的 memory_records 应被正确渲染"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="full",
            memory_records={
                "entities": [
                    {"name": "主角", "entity_type": "character", "importance": 0.9}
                ],
                "relations": [
                    {"source_id": "s1", "target_id": "t1", "relation_type": "ally"}
                ],
                "character_locations": {
                    "c1": {"location_id": "loc1", "text_state": "休息中"}
                },
                "chapter_index": 3,
            },
        )
        md = render_context_markdown(bundle)
        assert "第 3 章关系全景" in md
        assert "主角" in md
        assert "ally" in md

    def test_render_with_budget_warnings(self) -> None:
        """预算用尽或接近上限应在风险提示中显示"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="full",
            budget_used={"core_entities": 8, "characters": 5},
        )
        md = render_context_markdown(bundle)
        assert "预算已用尽" in md
        assert "core_entities" in md

    def test_render_with_hidden_plot_threads_in_forbidden(self) -> None:
        """hidden 类型的剧情线应在禁止事项中列出"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="full",
            plot_threads=[
                {
                    "name": "暗线",
                    "thread_type": "hidden",
                    "hidden_truth": "幕后黑手是国王",
                },
            ],
        )
        md = render_context_markdown(bundle)
        assert "暗线" in md
        assert "幕后黑手是国王" in md

    def test_render_with_geo_locations(self) -> None:
        """地缘数据应正确渲染"""
        mock_loc = MagicMock()
        mock_loc.name = "王城"
        mock_loc.location_level = "capital"
        mock_loc.summary = "大陆中心"
        mock_loc.terrain = "平原"
        mock_loc.climate = "温带"
        mock_loc.access_level = "public"

        mock_edge = MagicMock()
        mock_edge.relation_type = "road"
        mock_edge.direction_label = "北门"
        mock_edge.difficulty = "easy"

        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="full",
            geo_locations=[
                {
                    "location": mock_loc,
                    "edges": [mock_edge],
                    "parent_locations": [],
                    "child_locations": [],
                    "current_era": None,
                },
            ],
        )
        md = render_context_markdown(bundle)
        assert "王城" in md
        assert "capital" in md
        assert "平原" in md
        assert "road" in md

    def test_render_empty_geo_returns_no_data(self) -> None:
        """空 geo_locations 应显示无相关数据"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="full",
            geo_locations=[],
        )
        md = render_context_markdown(bundle)
        assert "无相关数据" in md

    def test_render_foreshadowing_from_chapter_card(self) -> None:
        """从 chapter_card 提取伏笔信息"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="chapter",
            chapter_card={
                "foreshadowing_actions": [
                    {"description": "埋下戒指伏笔"},
                    {"action": "主角梦到未来"},
                ],
                "must_happen": ["主角必须到达王城"],
                "must_not_happen": ["主角死亡"],
            },
        )
        md = render_context_markdown(bundle)
        assert "埋下戒指伏笔" in md
        assert "主角必须到达王城" in md
        assert "主角死亡" in md

    def test_render_creative_materials_with_entity_tags(self) -> None:
        """可用创作素材应包含实体标签"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="full",
            world_entities=[
                {"id": "e1", "name": "王国"},
                {"id": "e2", "name": "神器"},
            ],
            characters=[
                {"character_id": "c1", "name": "英雄"},
            ],
            rag_chunks=[
                {
                    "text": "关于王国的古老传说",
                    "score": 0.92,
                    "source_type": "world_entity",
                    "chapter_index": 3,
                    "meta": {"arc_name": "第一卷"},
                    "entity_ids": ["e1", "e2"],
                    "character_ids": ["c1"],
                },
            ],
        )
        md = render_context_markdown(bundle)
        assert "#王国" in md
        assert "#神器" in md
        assert "@英雄" in md
        assert "0.92" in md
        assert "第一卷" in md

    def test_render_risks_no_warnings(self) -> None:
        """无警告时应显示无相关风险"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="project",
        )
        md = render_context_markdown(bundle)
        assert "无相关风险" in md

    def test_section_renderer_fallback(self) -> None:
        """未识别的段落 key 应返回 fallback 内容"""
        from modules.context.markdown_renderer import _get_section_renderer

        bundle = StructureContextBundle(novel_id="id", task="t", scope="project")
        renderer = _get_section_renderer("nonexistent_key")
        result = renderer(bundle)
        assert result == "无相关数据\n"


# ============================================================
# 6. API 路由测试（Mock Facade）
# ============================================================


class TestContextApi:
    """测试 API 路由"""

    def _compiled_context(self) -> CompiledContext:
        """构造一个用于 API 测试的 CompiledContext。"""
        return CompiledContext(
            sections=[
                ContextSection(
                    key="writing_objective",
                    tier=Tier.P0,
                    content="创作目标",
                    token_count=10,
                ),
                ContextSection(
                    key="compiler_warnings",
                    tier=Tier.P4,
                    content="测试警告",
                    token_count=5,
                ),
            ],
            total_tokens=15,
            budget_tokens=4000,
            evicted_keys=[],
            truncated_keys=[],
        )

    @pytest.mark.asyncio
    async def test_compile_context_success(self) -> None:
        """POST /api/context/compile 应返回 Tier 编译结果"""
        mock_ctx = self._compiled_context()

        with patch(
            "modules.context.api.compile_with_tiers",
            AsyncMock(return_value=mock_ctx),
        ):
            from modules.context.api import compile_context

            request = ContextCompileRequest(
                novel_id="nid",
                task="测试",
                scope="project",
            )
            response = await compile_context(
                db=MagicMock(),
                request=request,
            )

        assert isinstance(response, ContextTierCompileResponse)
        assert response.novel_id == "nid"
        assert response.scope == "project"
        assert response.total_tokens == 15
        assert response.budget_tokens == 4000
        assert len(response.sections) == 2
        assert response.sections[0].key == "writing_objective"

    @pytest.mark.asyncio
    async def test_compile_context_character_reveal_requires_viewpoint(self) -> None:
        """character 揭示模式未提供 viewpoint_character_id 应抛出 400"""
        from modules.context.api import compile_context

        request = ContextCompileRequest(
            novel_id="nid",
            task="测试",
            scope="project",
            reveal_mode="character",
        )
        with pytest.raises(HTTPException) as exc_info:
            await compile_context(db=MagicMock(), request=request)

        assert exc_info.value.status_code == 400
        assert "viewpoint_character_id" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_compile_context_invalid_scope_raises_400(self) -> None:
        """无效 scope 在 /compile 中应抛出 400"""
        from modules.context.api import compile_context

        request = ContextCompileRequest(
            novel_id="nid",
            task="测试",
            scope="invalid_scope",
        )
        with pytest.raises(HTTPException) as exc_info:
            await compile_context(db=MagicMock(), request=request)

        assert exc_info.value.status_code == 400
        assert "invalid_scope" in exc_info.value.detail
        assert "scope" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_render_context_success(self) -> None:
        """POST /api/context/render 应返回 Markdown + Tier 编译信息"""
        mock_ctx = self._compiled_context()

        with (
            patch(
                "modules.context.api.render_compiled_context",
                MagicMock(return_value="# 渲染结果\n"),
            ),
            patch(
                "modules.context.api.compile_with_tiers",
                AsyncMock(return_value=mock_ctx),
            ),
        ):
            from modules.context.api import render_context

            request = ContextRenderRequest(
                novel_id="nid",
                task="测试",
                scope="project",
            )
            response = await render_context(
                db=MagicMock(),
                request=request,
            )

        assert isinstance(response, ContextRenderResponse)
        assert "# 渲染结果" in response.markdown
        assert isinstance(response.compile_info, ContextTierCompileResponse)
        assert response.compile_info.novel_id == "nid"
        assert response.compile_info.total_tokens == 15
        assert response.compile_info.budget_tokens == 4000
        assert len(response.compile_info.sections) == 2

    @pytest.mark.asyncio
    async def test_render_context_invalid_scope_raises_400(self) -> None:
        """无效 scope 在 /render 中应抛出 400"""
        from modules.context.api import render_context

        request = ContextRenderRequest(
            novel_id="nid",
            task="测试",
            scope="bad_scope",
        )
        with pytest.raises(HTTPException) as exc_info:
            await render_context(db=MagicMock(), request=request)

        assert exc_info.value.status_code == 400
        assert "bad_scope" in exc_info.value.detail
        assert "scope" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_render_context_character_reveal_requires_viewpoint(self) -> None:
        """character 揭示模式未提供 viewpoint_character_id 应抛出 400"""
        from modules.context.api import render_context

        request = ContextRenderRequest(
            novel_id="nid",
            task="测试",
            scope="project",
            reveal_mode="character",
        )
        with pytest.raises(HTTPException) as exc_info:
            await render_context(db=MagicMock(), request=request)

        assert exc_info.value.status_code == 400
        assert "viewpoint_character_id" in exc_info.value.detail


# ============================================================
# 7. 契约边界条件
# ============================================================


class TestContracts:
    """测试 contracts 边界条件"""

    def test_contxet_budget_is_immutable(self) -> None:
        """验证 CONTEXT_BUDGET 所有 key 均为正数"""
        for key, value in CONTEXT_BUDGET.items():
            assert isinstance(key, str), f"key {key} should be str"
            assert isinstance(value, int) and value > 0, (
                f"{key} budget should be positive int, got {value}"
            )

    def test_author_only_warning_is_not_empty(self) -> None:
        """AUTHOR_ONLY_WARNING 不应为空"""
        assert AUTHOR_ONLY_WARNING
        assert len(AUTHOR_ONLY_WARNING) > 10

    def test_bundle_default_values(self) -> None:
        """bundle 默认值应为空列表/None/False"""
        bundle = StructureContextBundle(
            novel_id="id",
            task="t",
            scope="project",
        )
        assert bundle.world_entities == []
        assert bundle.characters == []
        assert bundle.geo_locations == []
        assert bundle.memory_records == []
        assert bundle.timeline_events == []
        assert bundle.plot_threads == []
        assert bundle.rag_chunks == []
        assert bundle.project is None
        assert bundle.outline_arc is None
        assert bundle.chapter_card is None
        assert bundle.geo_filtered is False
        assert bundle.reveal_mode == "author_safe"
        assert bundle.budget_used == {}
        assert bundle.warnings == []

    def test_full_bundle_all_fields_set(self) -> None:
        """验证所有字段类型"""
        bundle = StructureContextBundle(
            novel_id="id",
            task="t",
            scope="full",
            chapter_index=3,
            arc_id="arc1",
            project={"key": "val"},
            world_entities=[{"name": "e1"}],
            characters=[{"name": "c1"}],
            geo_locations=[{"location": {"name": "loc1"}}],
            memory_records=[{"summary": "mem1"}],
            timeline_events=[{"title": "evt1"}],
            plot_threads=[{"name": "p1"}],
            outline_arc={"title": "arc1"},
            chapter_card={"chapter_goal": "goal"},
            rag_chunks=[{"text": "chunk1"}],
            geo_filtered=True,
            reveal_mode="author_full",
            viewpoint_character_id="vc1",
            budget_used={"core_entities": 5},
            warnings=["warn1"],
        )
        assert bundle.chapter_index == 3
        assert len(bundle.world_entities) == 1
        assert bundle.geo_filtered is True
        assert bundle.reveal_mode == "author_full"
        assert bundle.viewpoint_character_id == "vc1"


# ============================================================
# 8. Schema 校验测试
# ============================================================


class TestSchemaValidation:
    """测试 Schema 数据校验"""

    def test_compile_request_chapter_index_ge_zero(self) -> None:
        """chapter_index 必须 >= 0"""
        req = ContextCompileRequest(
            novel_id="id",
            task="t",
            scope="chapter",
            chapter_index=0,
        )
        assert req.chapter_index == 0

    def test_compile_request_default_reveal_mode(self) -> None:
        """reveal_mode 默认值应为 author_safe"""
        req = ContextCompileRequest(
            novel_id="id",
            task="t",
            scope="project",
        )
        assert req.reveal_mode == "author_safe"

    def test_compile_response_with_warnings(self) -> None:
        """编译响应应能包含警告"""
        resp = ContextTierCompileResponse(
            novel_id="id",
            task="t",
            scope="full",
            reveal_mode="author_safe",
            warnings=["数据库连接失败"],
            sections=[
                ContextSectionItem(
                    key="project",
                    tier=0,
                    content="项目信息",
                    token_count=10,
                ),
            ],
        )
        assert len(resp.warnings) == 1
        assert resp.total_tokens == 0
        assert len(resp.sections) == 1

    def test_render_request_all_fields(self) -> None:
        """渲染请求应接受所有字段"""
        req = ContextRenderRequest(
            novel_id="nid",
            task="生成章节",
            scope="chapter",
            chapter_index=5,
            arc_id="arc1",
            entity_ids=["e1"],
            character_ids=["c1"],
            location_ids=["l1"],
            reveal_mode="character",
            viewpoint_character_id="vc1",
            enable_geo_filter=True,
        )
        assert req.chapter_index == 5
        assert req.reveal_mode == "character"
        assert req.enable_geo_filter is True

    def test_budget_used_item_values(self) -> None:
        """预算使用明细应接受数值"""
        item = BudgetUsedItem(category="core_entities", budget=8, used=4)
        assert item.model_dump() == {
            "category": "core_entities",
            "budget": 8,
            "used": 4,
        }

    def test_compile_response_sections_count(self) -> None:
        """sections 长度应与返回的段数一致"""
        resp = ContextTierCompileResponse(
            novel_id="id",
            task="t",
            scope="world",
            reveal_mode="author_safe",
            sections=[
                ContextSectionItem(
                    key="project",
                    tier=0,
                    content="项目信息",
                    token_count=10,
                ),
            ],
        )
        assert len(resp.sections) == 1
        assert resp.budget_tokens == 4000

    def test_compile_request_accepts_scene_id_and_budget_tokens(self) -> None:
        """编译请求应接受 scene_id 和 budget_tokens"""
        req = ContextCompileRequest(
            novel_id="id",
            task="t",
            scope="chapter",
            scene_id="scene-1",
            budget_tokens=8000,
        )
        assert req.scene_id == "scene-1"
        assert req.budget_tokens == 8000

    def test_compile_request_budget_tokens_bounds(self) -> None:
        """budget_tokens 低于 500 或高于 32000 应被拒绝"""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ContextCompileRequest(
                novel_id="id",
                task="t",
                scope="chapter",
                budget_tokens=499,
            )

        with pytest.raises(ValidationError):
            ContextCompileRequest(
                novel_id="id",
                task="t",
                scope="chapter",
                budget_tokens=32001,
            )

    def test_tier_compile_response_defaults(self) -> None:
        """Tier 编译响应默认值应正确"""
        resp = ContextTierCompileResponse(
            novel_id="id",
            task="t",
            scope="chapter",
            reveal_mode="author_safe",
        )
        assert resp.total_tokens == 0
        assert resp.budget_tokens == 4000
        assert resp.sections == []
        assert resp.evicted == []
        assert resp.truncated == []
        assert resp.warnings == []

    def test_section_item_defaults(self) -> None:
        """ContextSectionItem 默认值应正确"""
        item = ContextSectionItem(
            key="project",
            tier=0,
            content="test",
            token_count=10,
        )
        assert item.truncated is False
