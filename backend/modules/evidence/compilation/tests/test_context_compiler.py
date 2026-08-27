"""
Context 模块测试

测试 Context Compiler 的核心逻辑：
1. 各 scope 编译正确性
2. Budget 控制
3. Reveal 模式过滤
4. Markdown 渲染
5. 无数据库时的优雅降级

编译器仍以组合各模块资料为主；确认记录和自动上下文快照由 context 模块持久化。
测试中确保即使业务资料为空，编译器也能正常工作。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.compilation.contracts import (
    ContextSnapshotRequest,
    StructureContextBundle,
)
from modules.evidence.compilation.facade import (
    compile_structure_context,
    render_context_markdown,
)
from modules.evidence.compilation.markdown_renderer import (
    render_context_markdown as render_md,
)
from modules.evidence.compilation.services import CompileOptions
from modules.evidence.compilation.services.context_compiler import ContextCompiler
from modules.evidence.compilation.services.protocol import Loader
from modules.story.continuity.contracts import SCENE_MEMORY_DIMENSIONS


@pytest.mark.asyncio
async def test_compiler_serializes_loaders_sharing_one_async_session() -> None:
    active_loaders = 0
    overlap_detected = False

    class SessionUsingLoader(Loader):
        def __init__(self, name: str) -> None:
            self._name = name

        @property
        def name(self) -> str:
            return self._name

        async def load(self, db, options, bundle) -> None:
            nonlocal active_loaders, overlap_detected
            active_loaders += 1
            overlap_detected = overlap_detected or active_loaders > 1
            await asyncio.sleep(0)
            active_loaders -= 1

    compiler = ContextCompiler(
        [
            SessionUsingLoader("memory_records"),
            SessionUsingLoader("events"),
        ]
    )
    await compiler.compile(
        db=object(),
        options=CompileOptions(novel_id="test-id", task="test", scope="full"),
    )

    assert overlap_detected is False


@pytest.mark.asyncio
async def test_compiler_redacts_loader_failure_warning() -> None:
    secret = "private-token-value"

    class FailingLoader(Loader):
        @property
        def name(self) -> str:
            return "project"

        async def load(self, db, options, bundle) -> None:
            raise RuntimeError(f"Authorization: Bearer {secret} api_key={secret}")

    bundle = await ContextCompiler([FailingLoader()]).compile(
        db=object(),
        options=CompileOptions(novel_id="test-id", task="test", scope="project"),
    )

    serialized = " ".join(bundle.warnings)
    assert secret not in serialized
    assert "[REDACTED]" in serialized


def _snapshot_request(
    novel_id: str,
    **overrides,
) -> ContextSnapshotRequest:
    payload = {
        "phase": "entity_extraction",
        "operation": "scene_entity_extraction",
        "prompt_name": "scene_entity_extraction",
        "model": "test-model",
        "compile_options": {},
        "included_asset_ids": {},
        "context_summary": {},
        "section_metadata": {},
        "token_metadata": {},
    }
    payload.update(overrides)
    return ContextSnapshotRequest(novel_id=novel_id, **payload)


async def _open_snapshot(
    db_session: AsyncSession,
    novel_id: str,
    **overrides,
):
    from modules.evidence.compilation.facade import open_context_snapshot

    return await open_context_snapshot(
        db_session,
        _snapshot_request(novel_id, **overrides),
    )


async def _add_active_project(db_session: AsyncSession, novel_id: str) -> None:
    from modules.project.models import Project

    db_session.add(Project(id=uuid.UUID(novel_id), title=f"Project {novel_id[-4:]}"))
    await db_session.flush()


async def _setup_character_knowledge(
    db_session: AsyncSession,
    knowledge_level: str,
    known_content: str | None = None,
    misconception: str | None = None,
) -> tuple[str, str, str, str]:
    """创建项目、POV 人物、目标实体与知识边界记录。

    返回: (novel_id_hex, character_id_hex, target_id_hex, hidden_truth)
    """
    from modules.project.models import Project
    from modules.world.models import Character, CharacterKnowledge, CoreEntity

    nid = uuid.uuid4()
    novel_id_hex = nid.hex
    db_session.add(
        Project(
            id=nid,
            title="测试小说",
            genre="奇幻",
            language="zh",
        )
    )

    char_id = uuid.uuid4()
    db_session.add(
        CoreEntity(
            id=char_id,
            novel_id=nid,
            entity_type="character",
            name="POV角色",
            status="canonical",
        )
    )
    db_session.add(
        Character(
            entity_id=char_id,
            novel_id=nid,
            name="POV角色",
            status="canonical",
        )
    )

    target_id = uuid.uuid4()
    hidden_truth = "源堡是诡秘之主的唯一性"
    db_session.add(
        CoreEntity(
            id=target_id,
            novel_id=nid,
            entity_type="location",
            name="源堡",
            summary="神秘的源质空间",
            hidden_truth=hidden_truth,
            status="canonical",
            importance_level="core",
            importance=0.9,
        )
    )
    db_session.add(
        CharacterKnowledge(
            id=uuid.uuid4(),
            novel_id=nid,
            character_id=char_id,
            target_type="location",
            target_id=target_id,
            knowledge_level=knowledge_level,
            known_content=known_content,
            misconception=misconception,
            source_chapter_index=1,
            status="canonical",
        )
    )
    await db_session.flush()
    return novel_id_hex, char_id.hex, target_id.hex, hidden_truth


def _response_text(data: dict) -> str:
    """把 API 返回的 Tier 编译结果合并为可搜索文本。"""
    parts = [s.get("content", "") for s in data.get("sections", [])]
    return "\n".join(parts)


class TestContextCompiler:
    """测试 Context Compiler 核心逻辑"""

    @pytest.mark.asyncio
    async def test_project_loader_keeps_only_prompt_safe_fields(self) -> None:
        from modules.evidence.compilation.services.loaders.project_loader import (
            ProjectLoader,
        )

        project_context = SimpleNamespace(
            model_dump=lambda: {
                "novel_id": "novel-1",
                "title": "安全项目",
                "genre": "悬疑",
                "tone": "冷峻",
                "language": "zh",
                "target_length": 300000,
                "current_stage": "drafting",
                "default_reveal_policy": "author_safe",
                "settings": {
                    "llm": {
                        "api_key": "sk-must-not-enter-context",
                        "base_url": "https://private-llm.example/v1",
                    }
                },
                "internal_note": "不可进入提示的内部字段",
            }
        )

        async def _get_project_context(_db, _novel_id):
            return project_context

        options = CompileOptions(
            novel_id="novel-1",
            task="续写",
            scope="project",
        )
        bundle = StructureContextBundle(
            novel_id=options.novel_id,
            task=options.task,
            scope=options.scope,
        )

        await ProjectLoader(_get_project_context).load(object(), options, bundle)

        assert bundle.project == {
            "novel_id": "novel-1",
            "title": "安全项目",
            "genre": "悬疑",
            "tone": "冷峻",
            "language": "zh",
            "target_length": 300000,
            "current_stage": "drafting",
            "default_reveal_policy": "author_safe",
        }

    def test_author_project_section_preserves_safe_metadata_only(self) -> None:
        from modules.evidence.compilation.services.context_compiler import ContextCompiler

        bundle = StructureContextBundle(
            novel_id="novel-1",
            task="续写",
            scope="project",
            project={
                "novel_id": "novel-1",
                "title": "安全项目",
                "genre": "悬疑",
                "tone": "冷峻",
                "language": "zh",
                "target_length": 300000,
                "current_stage": "drafting",
                "default_reveal_policy": "author_safe",
                "settings": {"llm": {"api_key": "sk-must-not-render"}},
            },
        )
        options = CompileOptions(
            novel_id=bundle.novel_id,
            task=bundle.task,
            scope=bundle.scope,
        )

        sections = ContextCompiler()._build_sections(bundle, options)
        project_section = next(
            section for section in sections if section.key == "style_assets"
        )

        assert "安全项目" in project_section.content
        assert "drafting" in project_section.content
        assert "300000" in project_section.content
        assert "author_safe" in project_section.content
        assert "settings" not in project_section.content
        assert "api_key" not in project_section.content
        assert "sk-must-not-render" not in project_section.content

    def test_rag_section_metadata_keeps_stable_source_ref(self) -> None:
        from modules.evidence.compilation.services.context_compiler import ContextCompiler

        source_ref = {
            "draft_id": "00000000-0000-0000-0000-000000000123",
            "chapter_index": 3,
            "version_number": 2,
            "content_mode": "working",
            "start_offset": 10,
            "end_offset": 20,
            "source_hash": "a" * 64,
            "range_hash": "b" * 64,
        }
        bundle = StructureContextBundle(
            novel_id="00000000-0000-0000-0000-000000000399",
            task="稳定来源",
            scope="full",
            rag_chunks=[
                {
                    "id": "chunk-1",
                    "source_type": "chapter_text",
                    "chapter_index": 3,
                    "text": "已从 writing 回读的原文",
                    "source_ref": source_ref,
                }
            ],
        )
        options = CompileOptions(
            novel_id=bundle.novel_id,
            task=bundle.task,
            scope=bundle.scope,
            content_mode="working",
        )

        sections = ContextCompiler()._build_sections(bundle, options)
        section = next(
            item for item in sections if item.key == "retrieval_evidence_packs"
        )

        assert section.sources[0]["source_ref"] == source_ref
        assert section.sources[0]["source_hash"] == "a" * 64

        options.consumer_action = "world.map_atlas.generate"
        atlas_section = next(
            item
            for item in ContextCompiler()._build_sections(bundle, options)
            if item.key == "retrieval_evidence_packs"
        )
        assert atlas_section.sources[0]["type"] == "rag"
        assert atlas_section.sources[0]["id"] == "chunk-1"
        assert atlas_section.sources[0]["chapter_index"] == "3"

    @pytest.mark.asyncio
    async def test_world_loader_requires_explicit_pending_opt_in(
        self,
        db_session: AsyncSession,
    ) -> None:
        from modules.evidence.compilation.services.loaders.world_entities_loader import (
            WorldEntitiesLoader,
        )

        entities = [
            SimpleNamespace(
                model_dump=lambda: {
                    "id": "active-1",
                    "name": "已采用对象",
                    "status": "canonical",
                    "importance": 0.8,
                }
            ),
            SimpleNamespace(
                model_dump=lambda: {
                    "id": "review-1",
                    "name": "未采用建议",
                    "status": "candidate",
                    "importance": 0.9,
                }
            ),
            SimpleNamespace(
                model_dump=lambda: {
                    "id": "archived-1",
                    "name": "已归档对象",
                    "status": "deprecated",
                    "importance": 1.0,
                }
            ),
        ]

        async def fake_get_world_context(*_args, **_kwargs):
            return SimpleNamespace(entities=entities)

        loader = WorldEntitiesLoader(fake_get_world_context)
        base = CompileOptions(
            novel_id=str(uuid.uuid4()),
            task="编译世界上下文",
            scope="world",
            include_pending_objects=False,
        )
        without_pending = StructureContextBundle(
            novel_id=base.novel_id,
            task=base.task,
            scope=base.scope,
        )
        await loader.load(db_session, base, without_pending)

        assert [item["id"] for item in without_pending.world_entities] == ["active-1"]
        assert without_pending.world_entities[0]["display_state"] == "active"
        assert without_pending.warnings == []

        with_pending_options = CompileOptions(
            **{
                **base.__dict__,
                "include_pending_objects": True,
            }
        )
        with_pending = StructureContextBundle(
            novel_id=base.novel_id,
            task=base.task,
            scope=base.scope,
        )
        await loader.load(db_session, with_pending_options, with_pending)

        assert [item["id"] for item in with_pending.world_entities] == [
            "review-1",
            "active-1",
        ]
        assert with_pending.world_entities[0]["display_state"] == "review"
        assert "上下文包含未采用的世界对象" in with_pending.warnings

    @pytest.mark.asyncio
    async def test_map_atlas_world_loader_keeps_canonical_author_full_contract(
        self,
        db_session: AsyncSession,
    ) -> None:
        from modules.evidence.compilation.services.loaders.world_entities_loader import (
            WorldEntitiesLoader,
        )
        observed: dict[str, object] = {}

        async def fake_canon(_db, _novel_id, **kwargs):
            observed.update(kwargs)
            return SimpleNamespace(
                entities=[],
                canon_revision_id="canon-map",
                canon_manifest_digest="digest-map",
            )

        options = CompileOptions(
            novel_id=str(uuid.uuid4()),
            task="规划 AI 地图册",
            scope="generation_center",
            consumer_action="world.map_atlas.generate",
            context_mode="canonical",
            reveal_mode="author_full",
        )
        bundle = StructureContextBundle(
            novel_id=options.novel_id,
            task=options.task,
            scope=options.scope,
        )

        await WorldEntitiesLoader(get_world_canon_context_fn=fake_canon).load(
            db_session, options, bundle
        )

        assert observed == {
            "reveal_mode": "author_full",
            "limit": 160,
        }
        assert options.world_canon_revision_id == "canon-map"
        assert options.world_canon_manifest_digest == "digest-map"

    @pytest.mark.asyncio
    async def test_world_loader_pins_canon_and_uses_legacy_only_for_working(
        self,
        db_session: AsyncSession,
    ) -> None:
        from modules.evidence.compilation.services.loaders.world_entities_loader import (
            WorldEntitiesLoader,
        )

        calls: list[tuple[str, dict]] = []

        async def canon_reader(*_args, **kwargs):
            calls.append(("canon", kwargs))
            return SimpleNamespace(
                entities=[],
                canon_revision_id="canon-1",
                canon_manifest_digest="digest-1",
            )

        async def legacy_reader(*_args, **kwargs):
            calls.append(("legacy", kwargs))
            return SimpleNamespace(entities=[])

        loader = WorldEntitiesLoader(legacy_reader, canon_reader)
        canonical = CompileOptions(
            novel_id=str(uuid.uuid4()),
            task="编译正典上下文",
            scope="world",
            world_canon_revision_id="requested-canon",
        )
        await loader.load(
            db_session,
            canonical,
            StructureContextBundle(
                novel_id=canonical.novel_id,
                task=canonical.task,
                scope=canonical.scope,
            ),
        )
        working = CompileOptions(
            novel_id=str(uuid.uuid4()),
            task="编译工作视图",
            scope="world",
            context_mode="working",
        )
        await loader.load(
            db_session,
            working,
            StructureContextBundle(
                novel_id=working.novel_id,
                task=working.task,
                scope=working.scope,
            ),
        )

        assert calls[0] == (
            "canon",
            {
                "reveal_mode": "author_safe",
                "limit": 16,
                "canon_revision_id": "requested-canon",
            },
        )
        assert calls[1][0] == "legacy"
        assert "include_review" in calls[1][1]
        assert canonical.world_canon_revision_id == "canon-1"
        assert canonical.world_canon_manifest_digest == "digest-1"
        assert working.world_canon_revision_id is None

    @pytest.mark.asyncio
    async def test_rag_loader_propagates_retrieval_warnings(
        self,
        db_session: AsyncSession,
    ) -> None:
        """RAG 检索降级应进入 Context Compiler warnings。"""
        from dataclasses import dataclass, field

        from modules.evidence.compilation.services.loaders.rag_chunks_loader import (
            RagChunksLoader,
        )

        @dataclass
        class _FakeRagResult:
            chunks: list = field(default_factory=list)
            warnings: list[str] = field(default_factory=list)
            degraded: bool = False

        async def _fake_retrieve(*args, **kwargs):
            return _FakeRagResult(
                chunks=[],
                warnings=["embedding 生成失败，本次检索已降级"],
                degraded=True,
            )

        bundle = StructureContextBundle(
            novel_id="00000000-0000-0000-0000-000000000399",
            task="测试 RAG warning",
            scope="full",
        )
        options = CompileOptions(
            novel_id=bundle.novel_id,
            task=bundle.task,
            scope=bundle.scope,
        )

        await RagChunksLoader(retrieve_fn=_fake_retrieve).load(
            db_session,
            options,
            bundle,
        )

        assert "embedding 生成失败，本次检索已降级" in bundle.warnings
        assert "RAG 检索降级" in bundle.warnings

    @pytest.mark.asyncio
    async def test_rag_loader_passes_visible_until_chapter(
        self,
        db_session: AsyncSession,
    ) -> None:
        from dataclasses import dataclass, field

        from modules.evidence.compilation.services.loaders.rag_chunks_loader import (
            RagChunksLoader,
        )

        calls: list[dict] = []

        @dataclass
        class _FakeRagResult:
            chunks: list = field(default_factory=list)
            warnings: list[str] = field(default_factory=list)
            degraded: bool = False

        async def _fake_retrieve(*args, **kwargs):
            calls.append(kwargs)
            return _FakeRagResult()

        bundle = StructureContextBundle(
            novel_id="00000000-0000-0000-0000-000000000398",
            task="测试 RAG 读者进度",
            scope="chapter",
        )
        options = CompileOptions(
            novel_id=bundle.novel_id,
            task=bundle.task,
            scope=bundle.scope,
            chapter_index=3,
        )

        await RagChunksLoader(retrieve_fn=_fake_retrieve).load(
            db_session,
            options,
            bundle,
        )

        assert calls[0]["chapter_index"] == 3
        assert calls[0]["reference_chapter_index"] == 3
        assert calls[0]["visible_until_chapter"] == 3

        calls.clear()
        options.visible_until_chapter = 5
        await RagChunksLoader(retrieve_fn=_fake_retrieve).load(
            db_session,
            options,
            bundle,
        )
        assert calls[0]["visible_until_chapter"] == 5

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
        assert isinstance(bundle.memory_records, list)
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

    @pytest.mark.asyncio
    async def test_compile_character_false_belief_hides_hidden_truth(
        self,
        db_session: AsyncSession,
    ) -> None:
        """RED: character 视角 false_belief 应显示误解，不暴露 hidden_truth"""
        from modules.project.models import Project
        from modules.world.models import Character, CharacterKnowledge, CoreEntity
        from modules.world.schemas import CoreEntityCreate
        from modules.world.services.core.entity_service import WorldEntityService

        nid = uuid.uuid4()
        novel_id = str(nid)
        db_session.add(
            Project(
                id=nid,
                title="测试小说",
                genre="奇幻",
                language="zh",
            )
        )

        # POV 人物
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=nid,
                entity_type="character",
                name="POV角色",
                status="canonical",
            )
        )
        db_session.add(
            Character(
                entity_id=char_id,
                novel_id=nid,
                name="POV角色",
                status="canonical",
            )
        )

        # 目标实体：带 hidden_truth
        await db_session.flush()
        target = await WorldEntityService().create(
            db_session,
            novel_id,
            CoreEntityCreate(
                entity_type="faction",
                name="暗影组织",
                summary="一个神秘组织。",
                hidden_truth="真实隐藏真相：首领是国王。",
                importance_level="core",
            ),
        )
        target_id = uuid.UUID(target.id)

        # 人物知识边界：false_belief
        db_session.add(
            CharacterKnowledge(
                id=uuid.uuid4(),
                novel_id=nid,
                character_id=char_id,
                target_type="entity",
                target_id=target_id,
                knowledge_level="false_belief",
                known_content="一个神秘组织。",
                misconception="错误认知：暗影组织是正义的。",
                source_chapter_index=1,
                status="canonical",
            )
        )
        await db_session.flush()

        bundle = await compile_structure_context(
            db=db_session,
            novel_id=novel_id,
            task="生成章节",
            scope="world_character",
            character_ids=[str(char_id)],
            reveal_mode="character",
            viewpoint_character_id=str(char_id),
            visible_until_chapter=2,
        )
        rendered = render_context_markdown(bundle)

        assert "错误认知" in rendered
        assert "真实隐藏真相" not in rendered

        # 强断言：summary 被 misconception 替换，hidden_truth 字段被移除
        assert bundle.world_entities, "应保留至少一个世界对象"
        assert bundle.world_entities[0]["summary"] == "错误认知：暗影组织是正义的。"
        assert "hidden_truth" not in bundle.world_entities[0]

    @pytest.mark.asyncio
    async def test_compile_author_safe_preserves_entities_without_knowledge(
        self,
        db_session: AsyncSession,
    ) -> None:
        """RED: 非 character 模式下，无 knowledge 记录的世界对象应被保留"""
        from modules.project.models import Project
        from modules.world.models import Character, CoreEntity
        from modules.world.schemas import CoreEntityCreate
        from modules.world.services.core.entity_service import WorldEntityService

        nid = uuid.uuid4()
        novel_id = str(nid)
        db_session.add(
            Project(
                id=nid,
                title="测试小说",
                genre="奇幻",
                language="zh",
            )
        )

        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=nid,
                entity_type="character",
                name="POV角色",
                status="canonical",
            )
        )
        db_session.add(
            Character(
                entity_id=char_id,
                novel_id=nid,
                name="POV角色",
                status="canonical",
            )
        )

        await db_session.flush()
        await WorldEntityService().create(
            db_session,
            novel_id,
            CoreEntityCreate(
                entity_type="faction",
                name="暗影组织",
                summary="一个神秘组织。",
                hidden_truth="真实隐藏真相：首领是国王。",
                importance_level="core",
            ),
        )
        await db_session.flush()

        bundle = await compile_structure_context(
            db=db_session,
            novel_id=novel_id,
            task="生成章节",
            scope="world_character",
            character_ids=[str(char_id)],
            reveal_mode="author_safe",
        )

        faction_entities = [
            e for e in bundle.world_entities if e.get("entity_type") == "faction"
        ]
        assert len(faction_entities) == 1, (
            "无 knowledge 记录的 faction 实体在 author_safe 模式下应被保留"
        )
        assert faction_entities[0]["name"] == "暗影组织"
        assert faction_entities[0]["summary"] == "一个神秘组织。"

    @pytest.mark.asyncio
    async def test_compile_character_reveal_allows_public_info_without_knowledge(
        self,
        db_session: AsyncSession,
    ) -> None:
        """character 视角下，无 knowledge 记录不等同 unknown，只保留公开最小视图。"""
        from modules.project.models import Project
        from modules.world.models import Character, CoreEntity
        from modules.world.schemas import CoreEntityCreate
        from modules.world.services.core.entity_service import WorldEntityService

        nid = uuid.uuid4()
        novel_id = str(nid)
        db_session.add(
            Project(
                id=nid,
                title="测试小说",
                genre="奇幻",
                language="zh",
            )
        )

        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=nid,
                entity_type="character",
                name="POV角色",
                status="canonical",
            )
        )
        db_session.add(
            Character(
                entity_id=char_id,
                novel_id=nid,
                name="POV角色",
                status="canonical",
            )
        )

        await db_session.flush()
        await WorldEntityService().create(
            db_session,
            novel_id,
            CoreEntityCreate(
                entity_type="faction",
                name="暗影组织",
                summary="作者摘要：这个组织由国王秘密操纵。",
                public_info="公开信息：城中传闻有暗影组织活动。",
                hidden_truth="真实隐藏真相：首领是国王。",
                importance_level="core",
            ),
        )
        await db_session.flush()

        bundle = await compile_structure_context(
            db=db_session,
            novel_id=novel_id,
            task="生成章节",
            scope="world_character",
            character_ids=[str(char_id)],
            reveal_mode="character",
            viewpoint_character_id=str(char_id),
            visible_until_chapter=2,
        )

        faction_entities = [
            e for e in bundle.world_entities if e.get("entity_type") == "faction"
        ]
        assert len(faction_entities) == 1
        assert faction_entities[0]["public_info"] == "公开信息：城中传闻有暗影组织活动。"
        assert faction_entities[0]["summary"] == "公开信息：城中传闻有暗影组织活动。"
        assert faction_entities[0]["knowledge_level"] == "public_default"
        assert "hidden_truth" not in faction_entities[0]
        assert "国王秘密操纵" not in str(faction_entities[0])

    def test_character_reveal_sections_split_role_and_director_context(self) -> None:
        """character reveal 渲染角色可见面，不重复旧 scene_blueprint/pov_knowledge。"""
        from modules.evidence.compilation.markdown_renderer import render_compiled_context
        from modules.evidence.compilation.services.compiled_context import CompiledContext
        from modules.evidence.compilation.services.context_compiler import ContextCompiler

        scene_id = str(uuid.uuid4())
        char_id = str(uuid.uuid4())
        options = CompileOptions(
            novel_id=str(uuid.uuid4()),
            task="生成角色视角草稿",
            scope="chapter",
            chapter_index=2,
            scene_id=scene_id,
            character_ids=[char_id],
            reveal_mode="character",
            viewpoint_character_id=char_id,
        )
        bundle = StructureContextBundle(
            novel_id=options.novel_id,
            task=options.task,
            scope=options.scope,
            chapter_index=2,
            reveal_mode="character",
            viewpoint_character_id=char_id,
            characters=[
                {
                    "character_id": char_id,
                    "name": "秦岚",
                    "role": "调查员",
                    "current_goal": "确认警报来源",
                },
                {
                    "character_id": str(uuid.uuid4()),
                    "name": "林澈",
                    "role": "工程师",
                    "appearance": "袖口沾着黑色机油。",
                    "personality": "内心极度猜疑。",
                    "desire": "想夺取王位。",
                    "relationship_summary": "他是秦岚失散多年的兄长。",
                    "voice_style": "话少，常用短句。",
                },
            ],
            plot_threads=[
                {
                    "id": "thread-1",
                    "name": "警报调查线",
                    "summary": "作者完整谋划：林澈是真凶。",
                    "visible_goal": "找出警报的公开原因。",
                    "current_stage": "初步排查。",
                    "hidden_truth": "林澈故意触发警报。",
                    "author_known_state": "作者已知真凶。",
                }
            ],
            world_entities=[
                {
                    "entity_id": "entity-public",
                    "entity_type": "faction",
                    "name": "暗影组织",
                    "public_info": "公开信息：城中传闻有暗影组织活动。",
                    "summary": "作者摘要：国王秘密操纵暗影组织。",
                    "hidden_truth": "真实隐藏真相：首领是国王。",
                    "knowledge_level": "public_default",
                },
                {
                    "entity_id": "relation-secret",
                    "entity_type": "relation",
                    "name": "秘密同盟",
                    "description": "隐藏关系描述：秦岚暗中背叛林澈。",
                },
            ],
            scene={
                "scene_id": scene_id,
                "title": "主控室警报",
                "scene_index": 3,
                "pov_character_id": char_id,
                "goal": "作者目标：让秦岚发现线索。",
                "core_conflict": "作者冲突：林澈试图隐瞒。",
                "must_happen": "必须发生：发现林澈撒谎。",
                "must_not_happen": "不得发生：直接揭露凶手。",
                "atmosphere": "警报声刺耳。",
            },
            rag_chunks=[
                {
                    "chunk_id": "rag-a",
                    "scene_id": scene_id,
                    "text": "秦岚听见警报声，看见主控台闪烁。",
                    "summary": "隐藏摘要不应进入 source",
                },
                {
                    "chunk_id": "rag-b",
                    "scene_id": str(uuid.uuid4()),
                    "text": "未来 Scene 泄漏内容。",
                },
                {
                    "chunk_id": "rag-null",
                    "scene_id": None,
                    "text": "无 Scene 标注的章节 fallback 内容。",
                },
            ],
            memory_records=[
                {
                    "id": "memory-1",
                    "full_state": {"secret": "完整记忆快照隐藏内容"},
                    "summary": "不应直接渲染完整快照。",
                }
            ],
        )

        sections = ContextCompiler()._build_sections(bundle, options)
        keys = {section.key for section in sections}
        assert {
            "role_profile",
            "role_observed_characters",
            "role_visible_knowledge",
            "role_relationship_context",
            "safe_plotline_context",
            "role_scene_perception",
            "scene_director_constraints",
            "scene_time_boundary",
        }.issubset(keys)
        assert "scene_blueprint" not in keys
        assert "pov_knowledge" not in keys

        role_text = "\n".join(
            section.content
            for section in sections
            if section.key.startswith("role_") or section.key == "current_scene_evidence"
        )
        assert "公开信息：城中传闻有暗影组织活动。" in role_text
        assert "真实隐藏真相" not in role_text
        assert "国王秘密操纵" not in role_text
        assert "隐藏关系描述" not in role_text
        assert "必须发生" not in role_text
        assert "未来 Scene 泄漏内容" not in role_text
        assert "无 Scene 标注的章节 fallback 内容" not in role_text
        assert "袖口沾着黑色机油" in role_text
        assert "内心极度猜疑" not in role_text
        assert "想夺取王位" not in role_text
        assert "失散多年的兄长" not in role_text
        assert "工程师" not in role_text
        assert char_id not in role_text
        assert scene_id not in role_text

        time_boundary = next(s for s in sections if s.key == "scene_time_boundary")
        assert "当前 Scene 序号: 3" in time_boundary.content
        assert "当前 Scene 锚点: 已固定" in time_boundary.content
        assert char_id not in time_boundary.content
        assert scene_id not in time_boundary.content

        plotline = next(s for s in sections if s.key == "safe_plotline_context")
        assert plotline.status == "director_only"
        assert "警报调查线" in plotline.content
        assert "找出警报的公开原因" in plotline.content
        assert "初步排查" in plotline.content
        assert "林澈是真凶" not in plotline.content
        assert "林澈故意触发警报" not in plotline.content
        assert "作者已知真凶" not in plotline.content

        director = next(s for s in sections if s.key == "scene_director_constraints")
        assert director.status == "director_only"
        assert "DIRECTOR_ONLY" in director.content
        assert "必须发生：发现林澈撒谎" in director.content

        rendered = render_compiled_context(
            CompiledContext(sections=sections, total_tokens=1, budget_tokens=4000)
        )
        source_text = "\n".join(
            str(source) for section in sections for source in section.sources
        )
        assert "完整记忆快照隐藏内容" not in rendered
        assert "完整记忆快照隐藏内容" not in source_text
        assert "隐藏摘要不应进入 source" not in source_text

    def test_character_scene_keeps_proven_state_separate_from_belief(self) -> None:
        """Scene 实际状态、角色误信与当前正典不得互相回填。"""
        from modules.evidence.compilation.services.compiled_context import Tier
        from modules.evidence.compilation.services.context_compiler import ContextCompiler

        bridge_id = uuid.uuid4()
        options = CompileOptions(
            novel_id="project-1",
            task="生成倒叙 Scene",
            scope="chapter",
            consumer_action="writing.generate",
            chapter_index=4,
            scene_id="scene-4",
            entity_ids=[bridge_id.hex, "future-satellite"],
            character_ids=["pov"],
            reveal_mode="character",
            viewpoint_character_id="pov",
        )
        bundle = StructureContextBundle(
            novel_id=options.novel_id,
            task=options.task,
            scope=options.scope,
            characters=[{"character_id": "pov", "name": "秦岚"}],
            world_entities=[
                {
                    "entity_id": bridge_id.hex,
                    "name": "旧桥",
                    "knowledge_level": "false_belief",
                    "misconception": "秦岚相信旧桥已毁",
                },
                {
                    "entity_id": "future-satellite",
                    "name": "天基武器",
                    "knowledge_level": "unknown",
                    "hidden_truth": "当前正典的未来状态",
                },
            ],
            scene={"id": "scene-4", "pov_character_id": "pov"},
            scene_checkpoint_set={
                "coverage_status": "manual_required",
                "items": [
                    {
                        "id": "cp-entities",
                        "dimension": "entities",
                        "status": "ready",
                        "source": "system_generated",
                        "confirmed": False,
                        "state_json": {
                            "entities": {
                                str(bridge_id): {
                                    "name": "旧桥",
                                    "summary": "桥身仍然完好",
                                    "hidden_truth": "作者隐藏真相不在 allowlist",
                                }
                            }
                        },
                        "display_summary": "人物与对象 1 条",
                    },
                    {
                        "id": "cp-relations",
                        "dimension": "relations",
                        "status": "ready",
                        "source": "system_generated",
                        "confirmed": False,
                        "state_json": {
                            "relations": [
                                {
                                    "source_id": "pov",
                                    "target_id": str(bridge_id),
                                    "description": "守桥盟约仍然有效",
                                }
                            ]
                        },
                        "display_summary": "关系 1 条",
                    },
                    {
                        "id": "cp-locations",
                        "dimension": "locations",
                        "status": "ready",
                        "source": "system_generated",
                        "confirmed": False,
                        "state_json": {
                            "character_locations": {"pov": {"text_state": "位于旧桥东端"}}
                        },
                        "display_summary": "人物位置 1 条",
                    },
                    {
                        "id": "cp-knowledge",
                        "dimension": "knowledge",
                        "status": "ready",
                        "source": "system_generated",
                        "confirmed": False,
                        "state_json": {
                            "character_knowledge": ["checkpoint 知识不得覆盖 R13"]
                        },
                        "display_summary": "知识边界 1 条",
                    },
                    {
                        "id": "cp-map",
                        "dimension": "map",
                        "status": "ready",
                        "source": "system_generated",
                        "confirmed": False,
                        "state_json": {
                            "facts_by_key": {
                                "relevant": {
                                    "target_entity_id": str(bridge_id),
                                    "target_name": "旧桥",
                                    "evidence_text": "桥东端的路当时可通行",
                                },
                                "same-name-but-unrelated": {
                                    "target_entity_id": "another-bridge",
                                    "target_name": "旧桥",
                                    "evidence_text": "同名对象的未来状态不得进入",
                                },
                            }
                        },
                        "display_summary": "地图事实 2 条",
                    },
                ],
            },
        )

        sections = ContextCompiler()._build_sections(bundle, options)
        scene_state = next(item for item in sections if item.key == "scene_world_state")
        role_state = next(
            item for item in sections if item.key == "role_visible_knowledge"
        )

        assert scene_state.tier == Tier.P0
        assert scene_state.status == "director_only"
        assert scene_state.can_exclude is False
        assert "桥身仍然完好" in scene_state.content
        assert "守桥盟约仍然有效" in scene_state.content
        assert "位于旧桥东端" in scene_state.content
        assert "桥东端的路当时可通行" not in scene_state.content
        assert "同名对象的未来状态不得进入" not in scene_state.content
        assert "秦岚相信旧桥已毁" in role_state.content
        assert "秦岚相信旧桥已毁" not in scene_state.content
        assert "checkpoint 知识不得覆盖 R13" not in scene_state.content
        assert "未来地图状态不得进入" not in scene_state.content
        assert "当前正典的未来状态" not in scene_state.content
        assert {"label": "天基武器", "reason": "尚无时间锚"} in (
            scene_state.retrieval_metadata["omissions"]
        )
        assert {"label": "秦岚", "reason": "尚无时间锚"} in (
            scene_state.retrieval_metadata["omissions"]
        )
        assert not any(
            item["label"] == "旧桥"
            for item in scene_state.retrieval_metadata["omissions"]
        )
        assert (
            scene_state.activation_reason == "当前 Scene 四维 checkpoint 与相关对象对照"
        )
        assert [
            item["dimension"]
            for item in scene_state.retrieval_metadata["checkpoint_versions"]
        ] == list(SCENE_MEMORY_DIMENSIONS)

    def test_manual_scene_summary_does_not_hide_unanchored_objects(self) -> None:
        options = CompileOptions(
            novel_id="project-1",
            task="生成历史 Scene",
            scope="chapter",
            consumer_action="writing.generate",
            scene_id="scene-1",
            entity_ids=["unanchored"],
            reveal_mode="character",
            viewpoint_character_id="pov",
        )
        long_summary = "当时的已确认人物状态" * 200
        checkpoint = {
            "id": "manual-entities",
            "dimension": "entities",
            "status": "ready",
            "source": "manual",
            "confirmed": True,
            "state_json": {"manual_summary": long_summary},
            "display_summary": long_summary,
        }
        bundle = StructureContextBundle(
            novel_id=options.novel_id,
            task=options.task,
            scope=options.scope,
            characters=[{"character_id": "pov", "name": "秦岚"}],
            world_entities=[
                {
                    "entity_id": "unanchored",
                    "name": "未建立时间锚的塔",
                    "knowledge_level": "unknown",
                }
            ],
            scene={"id": "scene-1", "pov_character_id": "pov"},
            scene_checkpoint_set={
                "coverage_status": "ready",
                "items": [checkpoint],
            },
        )

        section = ContextCompiler._build_scene_world_state_section(bundle, options)

        assert {"label": "未建立时间锚的塔", "reason": "尚无时间锚"} in (
            section.retrieval_metadata["omissions"]
        )
        assert long_summary[:1200] in section.content
        assert long_summary[:1201] not in section.content

        checkpoint["state_json"] = {}
        checkpoint["display_summary"] = "已人工确认此阶段没有该维度事实"
        confirmed_empty = ContextCompiler._build_scene_world_state_section(
            bundle,
            options,
        )
        assert confirmed_empty.retrieval_metadata["omissions"] == []

    def test_scene_time_boundary_preserves_first_scene_indices(self) -> None:
        options = CompileOptions(
            novel_id="project-1",
            task="生成开场 Scene",
            scope="chapter",
            chapter_index=0,
            scene_id="scene-0",
            reveal_mode="character",
            viewpoint_character_id="pov",
        )
        bundle = StructureContextBundle(
            novel_id=options.novel_id,
            task=options.task,
            scope=options.scope,
            scene={"scene_index": 0},
        )

        content = ContextCompiler._format_scene_time_boundary(bundle, options)

        assert "当前章节: 0" in content
        assert "当前 Scene 序号: 0" in content


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
        from modules.evidence.compilation.schemas import ContextCompileRequest

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
        from modules.evidence.compilation.schemas import ContextCompileRequest

        req = ContextCompileRequest(
            novel_id="test-id",
            task="测试",
            scope="project",
        )
        assert req.reveal_mode == "author_safe"

    def test_render_request_valid(self) -> None:
        """渲染请求校验"""
        from modules.evidence.compilation.schemas import ContextRenderRequest

        req = ContextRenderRequest(
            novel_id="test-id",
            task="生成剧情线",
            scope="arc",
            arc_id="arc-1",
        )
        assert req.arc_id == "arc-1"

    def test_budget_used_item(self) -> None:
        """预算使用明细"""
        from modules.evidence.compilation.schemas import BudgetUsedItem

        item = BudgetUsedItem(category="core_entities", budget=8, used=3)
        assert item.category == "core_entities"
        assert item.budget == 8
        assert item.used == 3
