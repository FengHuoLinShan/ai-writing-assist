"""SceneEntityExtractionService 单元/集成测试。

覆盖 Phase 2 的实体/关系持久化、auto_ingested 元数据、Delta 记录。
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.errors import LLMConnectionError, LLMInvalidResponseError
from modules.imports.entity_extraction import (
    scene_entity_extraction as scene_entity_extraction_module,
)
from modules.imports.entity_extraction.scene_entity_alias_relation import (
    _compact_entity_index_for_scene,
    _effective_alias_relation_total_timeout_seconds,
    _trim_phase2b_scene_text,
)
from modules.imports.entity_extraction.scene_entity_bulk import BulkSceneEntityExtractor
from modules.imports.entity_extraction.scene_entity_extraction import (
    SceneEntityExtractionService,
)
from modules.imports.entity_extraction.scene_entity_strategy import (
    SceneEntityExtractionStrategySelector,
)
from modules.imports.entity_extraction.scene_entity_text import (
    scene_chapter_ids,
    scene_chunks_by_chapter,
    scene_context_header,
    select_scene_text,
)
from modules.imports.llm_schemas import (
    AliasRelationExtractionOutput,
    DeltaEvent,
    ExtractedAlias,
    ExtractedEntity,
    ExtractedRelation,
    SceneCandidateOutput,
    SceneEntityExtractionOutput,
)
from modules.writing.contracts import WritingDraftContract


class _FakeSavepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeNestedDb:
    def begin_nested(self):
        return _FakeSavepoint()


async def _snapshot_rows(db_session: AsyncSession, novel_id: str):
    from modules.context.facade import list_context_snapshots

    return await list_context_snapshots(db_session, novel_id=novel_id)


@contextmanager
def _patched_phase2_summaries(svc: SceneEntityExtractionService):
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                svc,
                "_phase2_audit_summary",
                new_callable=AsyncMock,
                return_value={},
            )
        )
        stack.enter_context(
            patch.object(
                svc,
                "_phase2_snapshot_health_summary",
                new_callable=AsyncMock,
                return_value={},
            )
        )
        yield


def test_scene_entity_extraction_public_timeout_monkeypatch_is_dynamic(
    monkeypatch,
) -> None:
    import modules.imports.entity_extraction as public
    from modules.imports.entity_extraction.scene_entity_bulk import (
        small_sample_supplement_timeout_seconds,
    )

    monkeypatch.setattr(
        public,
        "PHASE2_SMALL_SAMPLE_SUPPLEMENT_TIMEOUT_SECONDS",
        0.5,
    )

    assert small_sample_supplement_timeout_seconds() == 0.5


@pytest.mark.parametrize(
    ("total_scenes", "has_checkpoints", "expected_strategy"),
    [
        (0, False, "empty"),
        (7, False, "bulk"),
        (8, False, "small_sample_parallel"),
        (12, False, "small_sample_parallel"),
        (13, False, "batched"),
        (8, True, "checkpoint_resume"),
    ],
)
def test_phase2_strategy_selector_preserves_existing_boundaries(
    total_scenes: int,
    has_checkpoints: bool,
    expected_strategy: str,
) -> None:
    route = SceneEntityExtractionStrategySelector.select(
        total_scenes=total_scenes,
        has_checkpoints=has_checkpoints,
        small_sample_min=8,
        bulk_max=12,
    )

    assert route.strategy == expected_strategy
    assert route.total_scenes == total_scenes
    assert route.has_checkpoints is has_checkpoints


def test_llm_schema_normalizes_common_score_strings() -> None:
    output = SceneEntityExtractionOutput.model_validate(
        {
            "entities": [
                {
                    "name": "克莱恩",
                    "entity_type": "character",
                    "summary": None,
                    "public_info": None,
                    "hidden_truth": None,
                    "candidate_reason": None,
                    "importance": "85%",
                    "confidence": "高",
                    "aliases": ["周明瑞", {"name": "克莱恩·莫雷蒂"}],
                }
            ],
            "relations": [
                {
                    "source_name": "克莱恩",
                    "target_name": "梅丽莎",
                    "relation_type": "sibling",
                    "strength": "中",
                }
            ],
            "delta_events": [],
        }
    )

    assert output.entities[0].importance == 0.85
    assert output.entities[0].confidence == 0.9
    assert output.entities[0].aliases == [
        {"alias": "周明瑞", "type": "name"},
        {"name": "克莱恩·莫雷蒂", "alias": "克莱恩·莫雷蒂", "type": "name"},
    ]
    assert output.entities[0].summary == ""
    assert output.entities[0].public_info == ""
    assert output.entities[0].hidden_truth == ""
    assert output.entities[0].candidate_reason == ""
    assert output.relations[0].strength == 0.6

    tolerant_output = SceneEntityExtractionOutput.model_validate(
        {
            "entities": None,
            "relations": None,
            "delta_events": None,
        }
    )
    assert tolerant_output.entities == []
    assert tolerant_output.relations == []
    assert tolerant_output.delta_events == []

    candidate = SceneCandidateOutput.model_validate(
        {
            "scenes": [{"title": "候选"}],
            "confidence": "较高",
            "evidence_anchors": ["第1章开头"],
            "split_hints": ["可按仪式前后拆分"],
        }
    )
    assert candidate.confidence == 0.8
    assert candidate.evidence_anchors == ["第1章开头"]
    assert candidate.split_hints == ["可按仪式前后拆分"]

    tolerant_candidate = SceneCandidateOutput.model_validate(
        {
            "scenes": [{"title": "候选"}],
            "boundary_status": {"type": "complete", "reason": "边界完整"},
            "evidence_anchors": {"chapter_index": 1, "quote": "锚点"},
            "merge_hints": "无需合并",
            "split_hints": None,
            "missing_or_uncertain_items": "无重大缺失",
        }
    )
    assert tolerant_candidate.boundary_status == "complete"
    assert tolerant_candidate.evidence_anchors == [{"chapter_index": 1, "quote": "锚点"}]
    assert tolerant_candidate.merge_hints == ["无需合并"]
    assert tolerant_candidate.split_hints == []
    assert tolerant_candidate.missing_or_uncertain_items == ["无重大缺失"]


def test_alias_relation_schema_normalizes_alias_type_and_scores() -> None:
    output = AliasRelationExtractionOutput.model_validate(
        {
            "aliases": [
                {
                    "entity_name": "克莱恩",
                    "alias": "周明瑞",
                    "alias_type": "",
                    "confidence": "85%",
                },
                {
                    "entity_name": "梅丽莎",
                    "alias": "妹妹",
                    "alias_type": None,
                    "confidence": "高",
                },
            ],
            "relations": [
                {
                    "source_name": "克莱恩",
                    "target_name": "梅丽莎",
                    "relation_type": "sibling",
                    "strength": "较高",
                }
            ],
        }
    )

    assert output.aliases[0].alias_type == "alias"
    assert output.aliases[0].confidence == 0.85
    assert output.aliases[1].alias_type == "alias"
    assert output.aliases[1].confidence == 0.9
    assert output.relations[0].strength == 0.8

    tolerant_output = AliasRelationExtractionOutput.model_validate(
        {"aliases": None, "relations": None}
    )
    assert tolerant_output.aliases == []
    assert tolerant_output.relations == []


def test_alias_relation_total_timeout_scales_for_large_scene_sets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PHASE2_ALIAS_RELATION_TOTAL_TIMEOUT_SECONDS", raising=False)

    timeout = _effective_alias_relation_total_timeout_seconds(
        scene_count=86,
        concurrency=4,
        configured_timeout_seconds=240,
    )

    assert timeout > 240


def test_alias_relation_total_timeout_env_keeps_explicit_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PHASE2_ALIAS_RELATION_TOTAL_TIMEOUT_SECONDS", "240")

    timeout = _effective_alias_relation_total_timeout_seconds(
        scene_count=86,
        concurrency=4,
        configured_timeout_seconds=240,
    )

    assert timeout == 240


def test_phase2b_compacts_entity_index_to_scene_relevant_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PHASE2_ALIAS_RELATION_ENTITY_INDEX_FALLBACK_LIMIT", "1")
    entity_index = "\n".join(
        [
            "## 可用对象索引",
            "- 克莱恩·莫雷蒂 (character)",
            "- 黑荆棘安保公司 (organization)",
            "- 无关地点 (location)",
            "- 无关物品 (item)",
        ]
    )

    compact = _compact_entity_index_for_scene(
        entity_index,
        "克莱恩进入黑荆棘安保公司。",
    )

    assert "- 克莱恩·莫雷蒂 (character)" in compact
    assert "- 黑荆棘安保公司 (organization)" in compact
    assert "- 无关地点 (location)" in compact
    assert "- 无关物品 (item)" not in compact
    assert "全量对象 4 个" in compact


def test_phase2b_trims_scene_text_with_head_and_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PHASE2_ALIAS_RELATION_SCENE_CHAR_LIMIT", "100")

    compact = _trim_phase2b_scene_text("A" * 100 + "B" * 100 + "C" * 100)

    assert compact.startswith("A")
    assert "Scene 中段已压缩" in compact
    assert compact.endswith("C" * 30)


@pytest.fixture
async def novel_with_drafts(db_session: AsyncSession):
    """创建一个项目并写入第 1、2 章 draft。"""
    from modules.project.schemas import ProjectCreate
    from modules.project.services import ProjectService
    from modules.writing.facade import create_draft_only

    project = await ProjectService().create_project(
        db_session,
        ProjectCreate(title="Scene Extraction Test", language="zh"),
    )
    novel_id = str(project.id)
    await create_draft_only(
        db_session,
        novel_id,
        chapter_index=1,
        title="第一章",
        content="主角克莱恩醒来。",
    )
    await create_draft_only(
        db_session,
        novel_id,
        chapter_index=2,
        title="第二章",
        content="他遇到了梅丽莎。",
    )
    return novel_id


@pytest.mark.asyncio
async def test_persist_entities_writes_auto_ingested_meta(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    entity = ExtractedEntity(
        name="克莱恩",
        entity_type="character",
        suggested_action="create_new",
        aliases=["周明瑞"],
        confidence=0.77,
    )

    with patch(
        "modules.world.facade.find_similar_entities",
        new_callable=AsyncMock,
        return_value={},
    ):
        created = await svc._persist_entities(
            db_session,
            novel_with_drafts,
            [entity],
            scene_index=1,
            source_chapter_index=1,
            workflow_id="wf-test-1",
        )

    assert created == 1
    from sqlalchemy import select

    from modules.world.models import CoreEntity
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_with_drafts, "novel_id")
    stmt = select(CoreEntity).where(CoreEntity.novel_id == nid)
    result = await db_session.execute(stmt)
    found = next((e for e in result.scalars() if e.name == "克莱恩"), None)
    assert found is not None
    assert found.status == "candidate"
    meta = (found.content_json or {}).get("_meta", {})
    assert meta.get("auto_ingested") is True
    assert meta.get("source_scene_index") == 1
    assert meta.get("source_chapter_index") == 1
    assert meta.get("batch_id") == "wf-test-1"
    assert meta.get("workflow_id") == "wf-test-1"
    assert meta.get("source") == "deep_import"
    assert meta.get("scene_id") is None
    assert meta.get("scene_provenance_key") == "wf-test-1:scene:1"
    assert meta.get("suggested_action") == "create_new"
    assert (found.content_json or {}).get("aliases") == [
        {
            "alias": "周明瑞",
            "type": "name",
            "status": "candidate",
            "source": "deep_import",
            "workflow_id": "wf-test-1",
            "scene_id": None,
            "scene_index": 1,
            "confidence": 0.77,
            "quote": None,
            "needs_review": True,
        }
    ]


@pytest.mark.asyncio
async def test_load_scene_chapters_prefers_scene_chunk_text(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    from modules.writing.facade import create_draft_only

    await create_draft_only(
        db_session,
        novel_with_drafts,
        chapter_index=3,
        title="第三章",
        content="段落0。\n\n段落1。\n\n段落2。\n\n段落3。",
    )

    svc = SceneEntityExtractionService()
    text = await svc._load_scene_chapters(
        db_session,
        {
            "novel_id": novel_with_drafts,
            "scene_index": 3,
            "title": "局部 Scene",
            "goal": "只抽取段落1到2",
            "core_conflict": "局部事件",
            "emotional_beat": "紧张",
            "chapter_ids": ["3"],
            "scene_chunks": [
                {
                    "chapter_index": 3,
                    "start_paragraph": 1,
                    "end_paragraph": 2,
                }
            ],
        },
    )

    assert "## Scene 上下文" in text
    assert "- 标题: 局部 Scene" in text
    assert "段落1。" in text
    assert "段落2。" in text
    assert "段落0。" not in text
    assert "段落3。" not in text


@pytest.mark.asyncio
async def test_load_scene_chapters_falls_back_to_full_chapter_without_chunks(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    text = await svc._load_scene_chapters(
        db_session,
        {
            "novel_id": novel_with_drafts,
            "scene_index": 1,
            "chapter_ids": ["1"],
            "scene_chunks": [],
        },
    )

    assert "## Scene 上下文" in text
    assert "主角克莱恩醒来。" in text


@pytest.mark.asyncio
async def test_process_scene_creates_context_snapshot_and_links_entity_meta(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    """每次成功 Scene LLM 调用应创建 snapshot 并写入实体元数据。"""
    svc = SceneEntityExtractionService()
    scene = {
        "id": "scene-1",
        "novel_id": novel_with_drafts,
        "scene_index": 7,
        "chapter_ids": ["1"],
    }
    extraction = Mock()
    extraction.entities = [
        ExtractedEntity(
            name="奥黛丽",
            entity_type="character",
            suggested_action="create_new",
        )
    ]
    extraction.relations = []
    extraction.delta_events = []

    with (
        patch.object(svc, "_call_llm_extraction", new_callable=AsyncMock) as llm_call,
        patch(
            "modules.world.facade.find_similar_entities",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch("modules.memory.facade.capture_snapshot", new_callable=AsyncMock),
    ):
        llm_call.return_value = extraction
        result = await svc._process_scene(
            db_session,
            novel_with_drafts,
            scene,
            0,
            "无已有对象",
            [],
            set(),
            workflow_id="wf-phase2",
        )

    assert result["created"] == 1
    snapshots = await _snapshot_rows(db_session, novel_with_drafts)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.workflow_id == "wf-phase2"
    assert snapshot.phase == "entity_extraction"
    assert snapshot.operation == "scene_entity_extraction"
    assert snapshot.status == "succeeded"
    assert snapshot.scene_index == 7
    assert snapshot.chapter_index == 1
    assert snapshot.context_summary["scene_index"] == 7
    assert len(snapshot.result_refs) == 1
    assert snapshot.result_refs[0]["type"] == "core_entity"
    assert snapshot.result_refs[0]["id"]

    from sqlalchemy import select

    from modules.world.models import CoreEntity
    from shared.utils import parse_uuid

    stmt = select(CoreEntity).where(
        CoreEntity.novel_id == parse_uuid(novel_with_drafts, "novel_id"),
        CoreEntity.name == "奥黛丽",
    )
    entity = (await db_session.execute(stmt)).scalar_one()
    meta = (entity.content_json or {}).get("_meta", {})
    assert meta["context_snapshot_id"] == str(snapshot.id)


@pytest.mark.asyncio
async def test_process_scene_creates_failed_context_snapshot_on_llm_error(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    """失败的 Scene LLM 调用也应留下 failed snapshot。"""
    svc = SceneEntityExtractionService()
    scene = {
        "id": "scene-2",
        "novel_id": novel_with_drafts,
        "scene_index": 8,
        "chapter_ids": ["1"],
    }

    with patch.object(
        svc,
        "_call_llm_extraction",
        new_callable=AsyncMock,
        side_effect=LLMConnectionError("connection dropped"),
    ):
        with pytest.raises(LLMConnectionError):
            await svc._process_scene(
                db_session,
                novel_with_drafts,
                scene,
                0,
                "无已有对象",
                [],
                set(),
                workflow_id="wf-failed-phase2",
            )

    snapshots = await _snapshot_rows(db_session, novel_with_drafts)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.status == "failed"
    assert snapshot.error_kind == "connection_error"
    assert "connection dropped" in snapshot.error_message
    assert snapshot.phase == "entity_extraction"


@pytest.mark.asyncio
async def test_phase2b_snapshot_helper_creates_alias_relation_snapshot(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    """Phase 2b snapshot helper should use the lifecycle request path."""
    from modules.imports.entity_extraction.scene_entity_snapshots import (
        create_phase2b_snapshot,
    )

    class _SnapshotServiceStub:
        def _scene_context_header(self, scene: dict) -> str:
            return f"Scene {scene.get('scene_index')}"

        def _scene_id(self, scene: dict) -> str:
            return str(scene["id"])

        def _scene_source_chapter_index(self, scene: dict) -> int:
            return 1

    scene = {
        "id": "scene-phase2b",
        "novel_id": novel_with_drafts,
        "scene_index": 12,
    }

    snapshot = await create_phase2b_snapshot(
        _SnapshotServiceStub(),
        db_session,
        novel_with_drafts,
        scene,
        "第 1 章正文",
        "entity-index",
        workflow_id="wf-phase2b",
    )

    rows = await _snapshot_rows(db_session, novel_with_drafts)
    assert len(rows) == 1
    stored = rows[0]
    assert stored.id == snapshot.id
    assert stored.workflow_id == "wf-phase2b"
    assert stored.operation == "alias_relation_extraction"
    assert stored.scene_id == "scene-phase2b"
    assert stored.scene_index == 12
    assert stored.chapter_index == 1
    assert stored.included_asset_ids == {}
    assert stored.context_summary["entity_index_chars"] == len("entity-index")
    assert stored.rendered_context is None

    from modules.context.models import ContextSnapshot

    raw_result = await db_session.execute(select(ContextSnapshot))
    raw_snapshot = raw_result.scalar_one()
    assert raw_snapshot.included_asset_ids == []
    assert raw_snapshot.section_metadata == [
        {"name": "entity_index", "chars": len("entity-index")},
        {
            "name": "scene_text",
            "chars": len("第 1 章正文"),
            "source_refs": [],
            "source_warning": "Invalid scene_id: scene-phase2b",
        },
    ]
    assert raw_snapshot.context_summary["source_ref_count"] == 0


@pytest.mark.asyncio
async def test_process_scene_marks_snapshot_failed_on_persist_error(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    """LLM 成功后持久化失败也应把 snapshot 标记为 failed。"""
    svc = SceneEntityExtractionService()
    scene = {
        "id": "scene-3",
        "novel_id": novel_with_drafts,
        "scene_index": 9,
        "chapter_ids": ["1"],
    }
    extraction = Mock()
    extraction.entities = [
        ExtractedEntity(
            name="佛尔思",
            entity_type="character",
            suggested_action="create_new",
        )
    ]
    extraction.relations = []
    extraction.delta_events = []

    with (
        patch.object(
            svc,
            "_call_llm_extraction",
            new_callable=AsyncMock,
            return_value=extraction,
        ),
        patch.object(
            svc,
            "_persist_entities",
            new_callable=AsyncMock,
            side_effect=RuntimeError("entity persist failed"),
        ),
    ):
        with pytest.raises(RuntimeError, match="entity persist failed"):
            await svc._process_scene(
                db_session,
                novel_with_drafts,
                scene,
                0,
                "无已有对象",
                [],
                set(),
                workflow_id="wf-persist-failed-phase2",
            )

    snapshots = await _snapshot_rows(db_session, novel_with_drafts)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.status == "failed"
    assert snapshot.error_kind == "RuntimeError"
    assert "entity persist failed" in snapshot.error_message


@pytest.mark.asyncio
async def test_persist_entities_keeps_temporary_and_link_candidates(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    temporary = ExtractedEntity(
        name="临时钥匙",
        entity_type="item",
        suggested_action="temporary_only",
        candidate_reason="只在当前 Scene 使用",
    )
    alias = ExtractedEntity(
        name="岚姐",
        entity_type="character",
        suggested_action="link_to_existing",
        suggested_existing_entity_name="林岚",
        candidate_reason="已有角色的新称呼",
    )

    with patch(
        "modules.world.facade.find_similar_entities",
        new_callable=AsyncMock,
        return_value={},
    ):
        created = await svc._persist_entities(
            db_session,
            novel_with_drafts,
            [temporary, alias],
            scene_index=1,
            source_chapter_index=1,
            workflow_id="wf-test-1",
        )

    assert created == 2
    from sqlalchemy import select

    from modules.world.models import CoreEntity
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_with_drafts, "novel_id")
    stmt = select(CoreEntity).where(CoreEntity.novel_id == nid)
    result = await db_session.execute(stmt)
    by_name = {e.name: e for e in result.scalars()}

    assert by_name["临时钥匙"].status == "candidate"
    temp_meta = (by_name["临时钥匙"].content_json or {}).get("_meta", {})
    assert temp_meta.get("suggested_action") == "temporary_only"
    assert temp_meta.get("temporary") is True

    assert by_name["岚姐"].status == "candidate"
    alias_meta = (by_name["岚姐"].content_json or {}).get("_meta", {})
    assert alias_meta.get("suggested_action") == "link_to_existing"
    assert alias_meta.get("suggested_existing_entity_name") == "林岚"


@pytest.mark.asyncio
async def test_persist_entities_skips_duplicate_names_in_phase() -> None:
    svc = SceneEntityExtractionService()
    entities = [
        ExtractedEntity(
            name="克莱恩",
            entity_type="character",
            suggested_action="create_new",
        ),
        ExtractedEntity(
            name=" 克莱恩 ",
            entity_type="character",
            suggested_action="create_new",
        ),
    ]

    with (
        patch(
            "modules.world.facade.find_similar_entities",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "modules.world.facade.create_entity",
            new_callable=AsyncMock,
            return_value={"id": "entity-1"},
        ) as create_entity,
        patch(
            "modules.imports.entity_extraction.scene_entity_persistence."
            "SceneEntityPersistenceGateway._record_quote_evidence",
            new_callable=AsyncMock,
        ),
    ):
        created = await svc._persist_entities(
            _FakeNestedDb(),
            "00000000-0000-0000-0000-000000000001",
            entities,
            scene_index=1,
            source_chapter_index=1,
            seen_entity_keys=set(),
        )

    assert created == 1
    create_entity.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_entities_rolls_back_single_entity_failure(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    """One DBAPI failure must not poison the session or block later entities."""
    svc = SceneEntityExtractionService()
    entities = [
        ExtractedEntity(
            name="坏实体",
            entity_type="character",
            suggested_action="create_new",
        ),
        ExtractedEntity(
            name="好实体",
            entity_type="character",
            suggested_action="create_new",
        ),
    ]

    from modules.world.facade import create_entity as real_create_entity

    async def create_entity_with_one_db_failure(db, novel_id, data):
        if data["name"] == "坏实体":
            await db.execute(text("SELECT * FROM missing_table_for_savepoint_test"))
        return await real_create_entity(db, novel_id, data)

    with (
        patch(
            "modules.world.facade.find_similar_entities",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "modules.world.facade.create_entity",
            side_effect=create_entity_with_one_db_failure,
        ),
    ):
        created = await svc._persist_entities(
            db_session,
            novel_with_drafts,
            entities,
            scene_index=1,
            source_chapter_index=1,
            workflow_id="wf-savepoint",
        )

    assert created == 1
    await db_session.flush()

    from sqlalchemy import select

    from modules.world.models import CoreEntity
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_with_drafts, "novel_id")
    stmt = select(CoreEntity).where(CoreEntity.novel_id == nid)
    result = await db_session.execute(stmt)
    names = {entity.name for entity in result.scalars()}
    assert "坏实体" not in names
    assert "好实体" in names


@pytest.mark.asyncio
async def test_persist_relations_links_existing_entities(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    from modules.world.facade import create_entity

    await create_entity(
        db_session,
        novel_with_drafts,
        {"name": "克莱恩", "entity_type": "character", "status": "canonical"},
    )
    await create_entity(
        db_session,
        novel_with_drafts,
        {"name": "梅丽莎", "entity_type": "character", "status": "canonical"},
    )

    relation = ExtractedRelation(
        source_name="克莱恩",
        target_name="梅丽莎",
        relation_type="sibling",
        description="兄妹",
    )
    created = await svc._persist_relations(
        db_session,
        novel_with_drafts,
        [relation],
        scene_index=1,
        workflow_id="wf-test-2",
    )

    assert created == 1
    from modules.world.facade import get_entity_relations

    rels, _ = await get_entity_relations(db_session, novel_with_drafts)
    relation = next(r for r in rels if r.relation_type == "sibling")
    assert relation.status == "candidate"


@pytest.mark.asyncio
async def test_persist_relations_links_candidate_entities(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    from modules.world.facade import create_entity, get_entity_relations

    await create_entity(
        db_session,
        novel_with_drafts,
        {"name": "克莱恩", "entity_type": "character", "status": "candidate"},
    )
    await create_entity(
        db_session,
        novel_with_drafts,
        {"name": "伦纳德", "entity_type": "character", "status": "candidate"},
    )

    created = await svc._persist_relations(
        db_session,
        novel_with_drafts,
        [
            ExtractedRelation(
                source_name="克莱恩",
                target_name="伦纳德",
                relation_type="colleague",
                description="同事",
            )
        ],
        scene_index=2,
        workflow_id="wf-candidate-rel",
    )

    assert created == 1
    rels, total = await get_entity_relations(db_session, novel_with_drafts)
    assert total == 1
    assert rels[0].relation_type == "colleague"


@pytest.mark.asyncio
async def test_persist_relations_resolves_entities_in_one_batch() -> None:
    svc = SceneEntityExtractionService()
    relation = ExtractedRelation(
        source_name="克莱恩",
        target_name="梅丽莎",
        relation_type="sibling",
        description="兄妹",
    )

    with (
        patch(
            "modules.world.facade.find_working_entity_ids_by_names",
            new_callable=AsyncMock,
            return_value={"克莱恩": "entity-1", "梅丽莎": "entity-2"},
        ) as mock_batch_resolve,
        patch(
            "modules.world.facade.find_working_entity_id_by_name",
            new_callable=AsyncMock,
            side_effect=AssertionError("relations should batch entity name resolution"),
        ) as mock_single_resolve,
        patch(
            "modules.world.facade.create_or_merge_relation",
            new_callable=AsyncMock,
            return_value={"action": "created", "relation": Mock(id="relation-1")},
        ),
        patch(
            "modules.imports.entity_extraction.scene_entity_persistence."
            "SceneEntityPersistenceGateway._record_quote_evidence",
            new_callable=AsyncMock,
        ),
    ):
        created = await svc._persist_relations(
            _FakeNestedDb(),
            "novel-1",
            [relation],
            scene_index=1,
            workflow_id="wf-test",
        )

    assert created == 1
    mock_batch_resolve.assert_awaited_once()
    assert set(mock_batch_resolve.await_args.args[2]) == {"克莱恩", "梅丽莎"}
    mock_single_resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_relations_records_relation_merge_stats() -> None:
    svc = SceneEntityExtractionService()
    stats = svc._empty_phase2_persistence_stats()
    relation = ExtractedRelation(
        source_name="克莱恩",
        target_name="梅丽莎",
        relation_type="sibling",
        description="兄妹",
    )

    with (
        patch(
            "modules.world.facade.find_working_entity_ids_by_names",
            new_callable=AsyncMock,
            return_value={"克莱恩": "entity-1", "梅丽莎": "entity-2"},
        ),
        patch(
            "modules.world.facade.create_or_merge_relation",
            new_callable=AsyncMock,
            return_value={"action": "merged", "relation": Mock(id="relation-1")},
        ),
        patch(
            "modules.imports.entity_extraction.scene_entity_persistence."
            "SceneEntityPersistenceGateway._record_quote_evidence",
            new_callable=AsyncMock,
        ),
    ):
        created = await svc._persist_relations(
            _FakeNestedDb(),
            "novel-1",
            [relation],
            scene_index=1,
            workflow_id="wf-test",
            persistence_stats=stats,
        )

    assert created == 0
    assert stats["dedup_counts"]["relation_merged"] == 1


@pytest.mark.asyncio
async def test_process_scene_persists_phase2a_relation_output(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    """Phase 2a relation output should land without waiting for Phase 2b."""
    svc = SceneEntityExtractionService()
    from modules.world.facade import create_entity, get_entity_relations

    await create_entity(
        db_session,
        novel_with_drafts,
        {"name": "克莱恩", "entity_type": "character", "status": "canonical"},
    )
    await create_entity(
        db_session,
        novel_with_drafts,
        {"name": "梅丽莎", "entity_type": "character", "status": "canonical"},
    )
    scene = {
        "id": "scene-phase2a",
        "novel_id": novel_with_drafts,
        "scene_index": 12,
        "chapter_ids": ["1"],
    }
    extraction = SceneEntityExtractionOutput(
        entities=[],
        relations=[
            ExtractedRelation(
                source_name="克莱恩",
                target_name="梅丽莎",
                relation_type="sibling",
                description="兄妹",
            )
        ],
        delta_events=[],
    )

    with (
        patch.object(
            svc,
            "_call_llm_extraction",
            new_callable=AsyncMock,
            return_value=extraction,
        ),
        patch("modules.memory.facade.capture_snapshot", new_callable=AsyncMock),
    ):
        result = await svc._process_scene(
            db_session,
            novel_with_drafts,
            scene,
            0,
            "无已有对象",
            [],
            set(),
            workflow_id="wf-phase2a-only",
        )

    assert result["relations"] == 1
    rels, total = await get_entity_relations(db_session, novel_with_drafts)
    assert total == 1
    assert rels[0].relation_type == "sibling"


@pytest.mark.asyncio
async def test_phase2b_links_candidate_entities_and_appends_alias_metadata(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    """Phase 2b can use candidate entities and stores aliases inline for review."""
    svc = SceneEntityExtractionService()
    from modules.world.facade import create_entity, get_entity_relations

    source = await create_entity(
        db_session,
        novel_with_drafts,
        {"name": "克莱恩", "entity_type": "character", "status": "candidate"},
    )
    target = await create_entity(
        db_session,
        novel_with_drafts,
        {"name": "梅丽莎", "entity_type": "character", "status": "candidate"},
    )
    output = AliasRelationExtractionOutput(
        aliases=[
            ExtractedAlias(
                entity_name="克莱恩",
                alias="周明瑞",
                alias_type="name",
                confidence=0.91,
                quote="周明瑞醒来时发现自己成了克莱恩。",
            )
        ],
        relations=[
            ExtractedRelation(
                source_name="克莱恩",
                target_name="梅丽莎",
                relation_type="sibling",
                description="兄妹",
                strength=0.8,
            )
        ],
    )

    result = await svc._persist_alias_relation_output(
        db_session,
        novel_with_drafts,
        output,
        scene_index=3,
        workflow_id="wf-phase2b",
        scene_id="scene-3",
    )

    assert result == {"aliases": 1, "relations": 1}
    rels, total = await get_entity_relations(db_session, novel_with_drafts)
    assert total == 1
    assert rels[0].source_id == source["id"]
    assert rels[0].target_id == target["id"]
    assert rels[0].status == "candidate"

    from sqlalchemy import select

    from modules.world.models import CoreEntity
    from shared.utils import parse_uuid

    stmt = select(CoreEntity).where(
        CoreEntity.id == parse_uuid(source["id"], "entity_id")
    )
    entity = (await db_session.execute(stmt)).scalar_one()
    aliases = (entity.content_json or {}).get("aliases", [])
    assert aliases == [
        {
            "alias": "周明瑞",
            "type": "name",
            "status": "candidate",
            "source": "deep_import",
            "workflow_id": "wf-phase2b",
            "scene_id": "scene-3",
            "scene_index": 3,
            "confidence": 0.91,
            "quote": "周明瑞醒来时发现自己成了克莱恩。",
            "needs_review": True,
        }
    ]

    from modules.context.models import EvidenceLink

    evidence = list(
        (
            await db_session.execute(
                select(EvidenceLink).where(
                    EvidenceLink.novel_id
                    == parse_uuid(
                        novel_with_drafts,
                        "novel_id",
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(evidence) == 2
    assert {item.status for item in evidence} == {"needs_review"}
    assert {item.precision for item in evidence} == {"unresolved"}
    assert {item.provenance["review_reason"] for item in evidence} == {
        "invalid_scene_id",
        "missing_quote",
    }


@pytest.mark.asyncio
async def test_phase2b_persistence_resolves_working_entities_in_one_batch() -> None:
    svc = SceneEntityExtractionService()
    output = AliasRelationExtractionOutput(
        aliases=[
            ExtractedAlias(entity_name="克莱恩", alias="周明瑞", confidence=0.91),
        ],
        relations=[
            ExtractedRelation(
                source_name="克莱恩",
                target_name="梅丽莎",
                relation_type="sibling",
                description="兄妹",
            )
        ],
    )
    relation = Mock(id="relation-1")

    with (
        patch(
            "modules.world.facade.find_working_entity_ids_by_names",
            new_callable=AsyncMock,
            return_value={"克莱恩": "entity-1", "梅丽莎": "entity-2"},
        ) as mock_batch_resolve,
        patch(
            "modules.world.facade.find_working_entity_id_by_name",
            new_callable=AsyncMock,
            side_effect=AssertionError("phase2b should batch entity name resolution"),
        ) as mock_single_resolve,
        patch(
            "modules.world.facade.append_candidate_alias",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "modules.world.facade.create_or_merge_relation",
            new_callable=AsyncMock,
            return_value={"action": "created", "relation": relation},
        ),
        patch(
            "modules.imports.entity_extraction.scene_entity_persistence."
            "SceneEntityPersistenceGateway._record_quote_evidence",
            new_callable=AsyncMock,
        ),
    ):
        result = await svc._persist_alias_relation_output(
            _FakeNestedDb(),
            "novel-1",
            output,
            scene_index=3,
            workflow_id="wf-phase2b",
            scene_id="scene-3",
        )

    assert result == {"aliases": 1, "relations": 1}
    mock_batch_resolve.assert_awaited_once()
    assert set(mock_batch_resolve.await_args.args[2]) == {"克莱恩", "梅丽莎"}
    mock_single_resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_phase2b_alias_append_is_idempotent_and_novel_scoped(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    from modules.project.schemas import ProjectCreate
    from modules.project.services import ProjectService
    from modules.world.facade import create_entity

    entity = await create_entity(
        db_session,
        novel_with_drafts,
        {"name": "克莱恩", "entity_type": "character", "status": "candidate"},
    )
    other_project = await ProjectService().create_project(
        db_session,
        ProjectCreate(title="Other Novel", language="zh"),
    )
    await create_entity(
        db_session,
        str(other_project.id),
        {"name": "跨项目对象", "entity_type": "character", "status": "candidate"},
    )
    output = AliasRelationExtractionOutput(
        aliases=[
            ExtractedAlias(entity_name="克莱恩", alias="周明瑞", confidence=0.8),
            ExtractedAlias(entity_name="克莱恩", alias=" 周明瑞 ", confidence=0.7),
            ExtractedAlias(entity_name="跨项目对象", alias="不应写入", confidence=0.9),
        ],
        relations=[],
    )

    first = await svc._persist_alias_relation_output(
        db_session,
        novel_with_drafts,
        output,
        scene_index=3,
        workflow_id="wf-phase2b",
        scene_id="scene-3",
    )
    second = await svc._persist_alias_relation_output(
        db_session,
        novel_with_drafts,
        output,
        scene_index=3,
        workflow_id="wf-phase2b",
        scene_id="scene-3",
    )

    assert first == {"aliases": 1, "relations": 0}
    assert second == {"aliases": 0, "relations": 0}

    from sqlalchemy import select

    from modules.world.models import CoreEntity
    from shared.utils import parse_uuid

    stmt = select(CoreEntity).where(
        CoreEntity.id == parse_uuid(entity["id"], "entity_id")
    )
    found = (await db_session.execute(stmt)).scalar_one()
    aliases = (found.content_json or {}).get("aliases", [])
    assert [a.get("alias") for a in aliases] == ["周明瑞"]


@pytest.mark.asyncio
async def test_phase2b_entity_index_only_includes_working_statuses(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    from modules.world.facade import create_entity

    for name, status in [
        ("正史对象", "canonical"),
        ("草稿对象", "draft"),
        ("候选对象", "candidate"),
        ("废弃对象", "deprecated"),
        ("忽略对象", "ignored"),
    ]:
        await create_entity(
            db_session,
            novel_with_drafts,
            {"name": name, "entity_type": "character", "status": status},
        )

    index = await svc._build_alias_relation_entity_index(
        db_session,
        novel_with_drafts,
    )

    assert "正史对象" in index
    assert "草稿对象" in index
    assert "候选对象" in index
    assert "废弃对象" not in index
    assert "忽略对象" not in index


@pytest.mark.asyncio
async def test_phase2b_scene_failure_degrades_without_raising(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    snapshot = Mock(id=None)

    with (
        patch.object(
            svc,
            "_load_scene_chapters",
            new_callable=AsyncMock,
            return_value="Scene 正文",
        ),
        patch.object(
            svc,
            "_build_alias_relation_entity_index",
            new_callable=AsyncMock,
            return_value="## 可用对象索引",
        ),
        patch.object(
            svc,
            "_create_phase2b_snapshot",
            new_callable=AsyncMock,
            return_value=snapshot,
        ),
        patch.object(
            svc,
            "_call_alias_relation_extraction",
            new_callable=AsyncMock,
            side_effect=RuntimeError("schema mismatch"),
        ),
    ):
        result = await svc._run_alias_relation_phase(
            db_session,
            novel_with_drafts,
            [{"scene_index": 7, "id": "scene-7"}],
            workflow_id="wf-phase2b",
        )

    assert result["total_aliases"] == 0
    assert result["total_relations"] == 0
    assert result["alias_relation_scenes"] == 0
    assert result["alias_relation_failed_scenes"] == [7]
    assert result["degraded"] is True
    assert result["error_kind"] == "RuntimeError"
    assert result["error_message"] == "schema mismatch"


@pytest.mark.asyncio
async def test_phase2b_total_timeout_budget_degrades_remaining_scenes(
    db_session: AsyncSession,
    novel_with_drafts: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()
    snapshot = Mock(id=None)

    async def slow_alias_relation_call(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        return AliasRelationExtractionOutput(aliases=[], relations=[])

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_alias_relation."
        "phase2_alias_relation_total_timeout_seconds",
        lambda: 0.01,
    )
    with (
        patch.object(
            svc,
            "_load_scene_chapters",
            new_callable=AsyncMock,
            return_value="Scene 正文",
        ),
        patch.object(
            svc,
            "_build_alias_relation_entity_index",
            new_callable=AsyncMock,
            return_value="## 可用对象索引",
        ),
        patch.object(
            svc,
            "_create_phase2b_snapshot",
            new_callable=AsyncMock,
            return_value=snapshot,
        ),
        patch.object(
            svc,
            "_call_alias_relation_extraction",
            new_callable=AsyncMock,
            side_effect=slow_alias_relation_call,
        ),
    ):
        result = await svc._run_alias_relation_phase(
            db_session,
            novel_with_drafts,
            [
                {"scene_index": 7, "id": "scene-7"},
                {"scene_index": 8, "id": "scene-8"},
            ],
            workflow_id="wf-phase2b",
        )

    assert result["total_aliases"] == 0
    assert result["total_relations"] == 0
    assert result["alias_relation_scenes"] == 0
    assert result["alias_relation_failed_scenes"] == [7, 8]
    assert result["degraded"] is True
    assert result["error_kind"] == "timeout"
    assert result["alias_relation_total_timeout_s"] == 0.01
    assert result["alias_relation_elapsed_s"] >= 0


@pytest.mark.asyncio
async def test_phase2b_runs_llm_calls_concurrently_before_serial_persistence(
    db_session: AsyncSession,
    novel_with_drafts: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()
    snapshot = Mock(id=None)
    both_started = asyncio.Event()
    started_calls = 0

    async def concurrent_alias_relation_call(*_args, **_kwargs):
        nonlocal started_calls
        started_calls += 1
        if started_calls == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.2)
        return AliasRelationExtractionOutput(aliases=[], relations=[])

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_alias_relation."
        "phase2_alias_relation_concurrency",
        lambda: 2,
    )
    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_alias_relation."
        "phase2_alias_relation_total_timeout_seconds",
        lambda: 1,
    )
    with (
        patch.object(
            svc,
            "_load_scene_chapters",
            new_callable=AsyncMock,
            return_value="Scene 正文",
        ),
        patch.object(
            svc,
            "_build_alias_relation_entity_index",
            new_callable=AsyncMock,
            return_value="## 可用对象索引",
        ) as build_entity_index,
        patch.object(
            svc,
            "_create_phase2b_snapshot",
            new_callable=AsyncMock,
            return_value=snapshot,
        ),
        patch.object(
            svc,
            "_call_alias_relation_extraction",
            new=concurrent_alias_relation_call,
        ),
        patch.object(
            svc,
            "_persist_alias_relation_output",
            new_callable=AsyncMock,
            return_value={"aliases": 0, "relations": 0},
        ) as persist_output,
    ):
        result = await svc._run_alias_relation_phase(
            db_session,
            novel_with_drafts,
            [
                {"scene_index": 7, "id": "scene-7"},
                {"scene_index": 8, "id": "scene-8"},
            ],
            workflow_id="wf-phase2b",
        )

    assert started_calls == 2
    assert result["alias_relation_scenes"] == 2
    assert result["alias_relation_failed_scenes"] == []
    assert result["alias_relation_concurrency"] == 2
    assert build_entity_index.await_count == 1
    assert persist_output.await_count == 2


@pytest.mark.asyncio
async def test_phase2b_records_checkpoints_and_progress(
    db_session: AsyncSession,
    novel_with_drafts: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()
    snapshot = Mock(id=None)
    progress_events: list[tuple[int, int]] = []

    async def on_progress(completed: int, total: int) -> None:
        progress_events.append((completed, total))

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_alias_relation."
        "phase2_alias_relation_total_timeout_seconds",
        lambda: 1,
    )
    with (
        patch.object(
            svc,
            "_load_scene_chapters",
            new_callable=AsyncMock,
            return_value="Scene 正文",
        ),
        patch.object(
            svc,
            "_build_alias_relation_entity_index",
            new_callable=AsyncMock,
            return_value="## 可用对象索引",
        ),
        patch.object(
            svc,
            "_create_phase2b_snapshot",
            new_callable=AsyncMock,
            return_value=snapshot,
        ),
        patch.object(
            svc,
            "_call_alias_relation_extraction",
            new_callable=AsyncMock,
            return_value=AliasRelationExtractionOutput(aliases=[], relations=[]),
        ),
        patch.object(
            svc,
            "_persist_alias_relation_output",
            new_callable=AsyncMock,
            return_value={"aliases": 1, "relations": 2},
        ),
    ):
        result = await svc._run_alias_relation_phase(
            db_session,
            novel_with_drafts,
            [{"scene_index": 7, "id": "scene-7"}],
            workflow_id="wf-phase2b",
            on_scene_progress=on_progress,
        )

    assert progress_events[0] == (0, 1)
    assert progress_events[-1] == (1, 1)
    checkpoints = result["alias_relation_checkpoints"]["phase2b"]["scenes"]
    assert checkpoints == [
        {
            "scene_id": "scene-7",
            "scene_index": 7,
            "position": 7,
            "status": "done",
            "aliases": 1,
            "relations": 2,
            "retry_count": 0,
            "fallback": False,
            "source": "deep_import",
            "auto_ingested": True,
        }
    ]


@pytest.mark.parametrize("checkpoint_status", ["done", "skipped"])
@pytest.mark.asyncio
async def test_phase2b_existing_checkpoint_skips_scene(
    db_session: AsyncSession,
    novel_with_drafts: str,
    checkpoint_status: str,
) -> None:
    svc = SceneEntityExtractionService()
    progress_events: list[tuple[int, int]] = []

    async def on_progress(completed: int, total: int) -> None:
        progress_events.append((completed, total))

    with patch.object(
        svc,
        "_call_alias_relation_extraction",
        new_callable=AsyncMock,
    ) as call_alias_relation:
        result = await svc._run_alias_relation_phase(
            db_session,
            novel_with_drafts,
            [{"scene_index": 7, "id": "new-scene-7"}],
            workflow_id="wf-phase2b",
            existing_checkpoints={
                "phase2b": {
                    "scenes": [
                        {
                            "scene_id": "new-scene-7",
                            "scene_index": 7,
                            "status": checkpoint_status,
                            "aliases": 3,
                            "relations": 4,
                            "retry_count": 0,
                        }
                    ]
                }
            },
            on_scene_progress=on_progress,
        )

    assert call_alias_relation.await_count == 0
    assert result["alias_relation_scenes"] == 0
    assert result["alias_relation_skipped_scenes"] == 1
    assert result["alias_relation_failed_scenes"] == []
    assert progress_events == [(0, 1), (1, 1)]
    checkpoint = result["alias_relation_checkpoints"]["phase2b"]["scenes"][0]
    assert checkpoint["scene_id"] == "new-scene-7"
    assert checkpoint["status"] == "skipped"
    assert checkpoint["aliases"] == 3
    assert checkpoint["relations"] == 4
    assert checkpoint["fallback"] is False


@pytest.mark.asyncio
async def test_phase2b_invalid_json_falls_back_to_empty_result(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    snapshot = Mock(id=None)

    with (
        patch.object(
            svc,
            "_load_scene_chapters",
            new_callable=AsyncMock,
            return_value="Scene 正文",
        ),
        patch.object(
            svc,
            "_build_alias_relation_entity_index",
            new_callable=AsyncMock,
            return_value="## 可用对象索引\n- 克莱恩 (character)",
        ),
        patch.object(
            svc,
            "_create_phase2b_snapshot",
            new_callable=AsyncMock,
            return_value=snapshot,
        ),
        patch.object(
            svc,
            "_call_alias_relation_extraction",
            new_callable=AsyncMock,
            side_effect=LLMInvalidResponseError("truncated json"),
        ),
    ):
        result = await svc._run_alias_relation_phase(
            db_session,
            novel_with_drafts,
            [{"scene_index": 7, "id": "scene-7"}],
            workflow_id="wf-phase2b",
        )

    assert result["alias_relation_scenes"] == 1
    assert result["alias_relation_failed_scenes"] == []
    assert result["alias_relation_fallback_scenes"] == [7]
    assert result["degraded"] is False
    assert result["error_kind"] is None
    checkpoint = result["alias_relation_checkpoints"]["phase2b"]["scenes"][0]
    assert checkpoint["status"] == "done"
    assert checkpoint["fallback"] is True
    assert checkpoint["error_kind"] == "LLMInvalidResponseError"


@pytest.mark.asyncio
async def test_phase2b_watchdog_timeout_returns_degraded_result(
    db_session: AsyncSession,
    novel_with_drafts: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()

    async def stuck_alias_relation_run(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        return {
            "total_aliases": 1,
            "total_relations": 1,
            "alias_relation_scenes": 1,
            "alias_relation_failed_scenes": [],
        }

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_extraction."
        "_phase2_config.phase2_alias_relation_total_timeout_seconds",
        lambda: 0.01,
    )
    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_extraction."
        "PHASE2_SCENE_TIMEOUT_GRACE_SECONDS",
        0,
    )
    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_extraction.AliasRelationExtractor.run",
        stuck_alias_relation_run,
    )

    result = await svc._run_alias_relation_phase(
        db_session,
        novel_with_drafts,
        [
            {"scene_index": 7, "id": "scene-7"},
            {"scene_index": 8, "id": "scene-8"},
        ],
        workflow_id="wf-phase2b-watchdog",
    )

    assert result["total_aliases"] == 0
    assert result["total_relations"] == 0
    assert result["alias_relation_scenes"] == 0
    assert result["alias_relation_failed_scenes"] == [7, 8]
    assert result["degraded"] is True
    assert result["error_kind"] == "timeout"
    assert result["alias_relation_total_timeout_s"] == 0.01
    assert result["alias_relation_concurrency"] == 4


@pytest.mark.asyncio
async def test_phase2b_watchdog_uses_dynamic_timeout_for_large_scene_sets(
    db_session: AsyncSession,
    novel_with_drafts: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()

    async def quick_alias_relation_run(*_args, **_kwargs):
        return {
            "total_aliases": 0,
            "total_relations": 0,
            "alias_relation_scenes": 84,
            "alias_relation_failed_scenes": [],
            "alias_relation_total_timeout_s": 2895,
            "alias_relation_concurrency": 4,
        }

    monkeypatch.delenv("PHASE2_ALIAS_RELATION_TOTAL_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_extraction.AliasRelationExtractor.run",
        quick_alias_relation_run,
    )

    result = await svc._run_alias_relation_phase(
        db_session,
        novel_with_drafts,
        [{"scene_index": index, "id": f"scene-{index}"} for index in range(1, 85)],
        workflow_id="wf-phase2b-dynamic-watchdog",
    )

    assert result["alias_relation_scenes"] == 84
    assert result["alias_relation_failed_scenes"] == []


@pytest.mark.asyncio
async def test_optional_phase2b_skips_supplement_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()
    monkeypatch.delenv("PHASE2_ALIAS_RELATION_SUPPLEMENT_ENABLED", raising=False)

    with patch.object(
        svc,
        "_run_alias_relation_phase",
        new_callable=AsyncMock,
    ) as run_alias_relation:
        result = await svc._run_optional_alias_relation_phase(
            Mock(),
            "novel-1",
            [{"scene_index": 1}],
            workflow_id="wf-optional-skip",
        )

    assert run_alias_relation.await_count == 0
    assert result["alias_relation_skipped"] is True
    assert result["alias_relation_failed_scenes"] == []
    assert result["degraded"] is False


@pytest.mark.asyncio
async def test_phase2a_only_alias_relation_result_skips_phase2b_even_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()
    monkeypatch.setenv("PHASE2_ALIAS_RELATION_SUPPLEMENT_ENABLED", "1")

    with patch.object(
        svc,
        "_run_alias_relation_phase",
        new_callable=AsyncMock,
    ) as run_alias_relation:
        result = await svc._phase2_alias_relation_result(
            Mock(),
            "novel-1",
            [{"scene_index": 1}],
            workflow_id="wf-phase2a-skip",
            include_alias_relations=False,
        )

    assert run_alias_relation.await_count == 0
    assert result["total_aliases"] == 0
    assert result["total_relations"] == 0
    assert result["alias_relation_scenes"] == 0
    assert result["alias_relation_failed_scenes"] == []
    assert result["alias_relation_skipped"] is True
    assert result["alias_relation_skip_reason"] == "phase2a_only"


@pytest.mark.asyncio
async def test_optional_phase2b_runs_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()
    monkeypatch.setenv("PHASE2_ALIAS_RELATION_SUPPLEMENT_ENABLED", "1")

    with patch.object(
        svc,
        "_run_alias_relation_phase",
        new_callable=AsyncMock,
        return_value={
            "total_aliases": 1,
            "total_relations": 1,
            "alias_relation_scenes": 1,
            "alias_relation_failed_scenes": [],
            "degraded": False,
        },
    ) as run_alias_relation:
        result = await svc._run_optional_alias_relation_phase(
            Mock(),
            "novel-1",
            [{"scene_index": 1}],
            workflow_id="wf-optional-run",
        )

    assert run_alias_relation.await_count == 1
    assert result["total_aliases"] == 1
    assert result["total_relations"] == 1


@pytest.mark.asyncio
async def test_phase2b_snapshot_preparation_timeout_degrades_scene(
    db_session: AsyncSession,
    novel_with_drafts: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()

    async def slow_snapshot(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        return Mock(id="snapshot-7")

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_alias_relation."
        "phase2_postprocess_timeout_seconds",
        lambda: 0.01,
    )
    with (
        patch.object(
            svc,
            "_load_scene_chapters",
            new_callable=AsyncMock,
            return_value="Scene 正文",
        ),
        patch.object(
            svc,
            "_build_alias_relation_entity_index",
            new_callable=AsyncMock,
            return_value="## 可用对象索引",
        ),
        patch.object(svc, "_create_phase2b_snapshot", new=slow_snapshot),
        patch.object(
            svc,
            "_call_alias_relation_extraction",
            new_callable=AsyncMock,
            return_value=AliasRelationExtractionOutput(aliases=[], relations=[]),
        ) as alias_call,
    ):
        result = await svc._run_alias_relation_phase(
            db_session,
            novel_with_drafts,
            [{"scene_index": 7, "id": "scene-7"}],
            workflow_id="wf-phase2b-snapshot-timeout",
        )

    assert result["total_aliases"] == 0
    assert result["total_relations"] == 0
    assert result["alias_relation_scenes"] == 0
    assert result["alias_relation_failed_scenes"] == [7]
    assert result["degraded"] is True
    assert result["error_kind"] == "timeout"
    alias_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_phase2_postprocess_summary_timeout_returns_degraded(
    db_session: AsyncSession,
    novel_with_drafts: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()

    async def slow_summary(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        return {"ok": True}

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_extraction."
        "_phase2_config.phase2_postprocess_timeout_seconds",
        lambda: 0.01,
    )
    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_extraction.phase2_snapshot_health_summary",
        slow_summary,
    )

    result = await svc._phase2_snapshot_health_summary(
        db_session,
        novel_with_drafts,
        workflow_id="wf-summary-timeout",
    )

    assert result["degraded"] is True
    assert result["error_kind"] == "timeout"
    assert "snapshot_health_summary" in result["error_message"]


@pytest.mark.asyncio
async def test_phase2_flush_timeout_returns_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()

    class SlowFlushDB:
        async def flush(self):
            await asyncio.sleep(0.05)

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_extraction."
        "_phase2_config.phase2_postprocess_timeout_seconds",
        lambda: 0.01,
    )

    result = await svc._phase2_flush_with_timeout(SlowFlushDB())

    assert result["degraded"] is True
    assert result["error_kind"] == "timeout"
    assert "db.flush" in result["error_message"]


@pytest.mark.asyncio
async def test_record_deltas_creates_delta_log(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    deltas = [
        DeltaEvent(
            category="ENTITY_CREATED",
            field="summary",
            old=None,
            new="summary text",
            meta={"source": "test"},
        )
    ]
    count = await svc._record_deltas(
        db_session,
        novel_with_drafts,
        deltas,
        scene_index=2,
        workflow_id="wf-delta",
        scene_id="00000000-0000-0000-0000-000000000002",
        scene_provenance_key="wf-delta:scene:2",
    )
    assert count == 1

    from sqlalchemy import select

    from modules.memory.models import DeltaLog
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_with_drafts, "novel_id")
    stmt = select(DeltaLog).where(DeltaLog.novel_id == nid, DeltaLog.scene_index == 2)
    result = await db_session.execute(stmt)
    items = result.scalars().all()
    assert len(items) == 1
    assert items[0].category == "ENTITY_CREATED"
    assert items[0].source == "deep_import"
    assert items[0].meta["workflow_id"] == "wf-delta"
    assert items[0].meta["scene_id"] == "00000000-0000-0000-0000-000000000002"
    assert items[0].meta["scene_provenance_key"] == "wf-delta:scene:2"
    assert items[0].meta["auto_ingested"] is True

    from modules.world.map_models import MapObservation

    obs_stmt = select(MapObservation).where(MapObservation.novel_id == nid)
    obs_result = await db_session.execute(obs_stmt)
    observations = obs_result.scalars().all()
    assert len(observations) == 1
    assert observations[0].review_state == "candidate"
    assert observations[0].dynamic_type == "entity_created"
    assert observations[0].scene_index == 2
    assert observations[0].source_ref["source"] == "deep_import_delta_event"
    assert observations[0].source_ref["delta_log_id"] == str(items[0].id)
    assert observations[0].source_ref["workflow_id"] == "wf-delta"
    assert observations[0].source_ref["scene_provenance_key"] == "wf-delta:scene:2"


@pytest.mark.asyncio
async def test_process_scene_captures_memory_snapshot(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    scene = {
        "id": "scene-1",
        "novel_id": novel_with_drafts,
        "scene_index": 1,
        "chapter_ids": ["1"],
    }

    with (
        patch.object(
            svc,
            "_call_llm_extraction",
            return_value=Mock(
                entities=[
                    ExtractedEntity(
                        name="克莱恩",
                        entity_type="character",
                        suggested_action="create_new",
                    )
                ],
                relations=[],
                delta_events=[],
            ),
        ),
        patch(
            "modules.memory.facade.capture_snapshot",
            new_callable=AsyncMock,
        ) as mock_snapshot,
        patch(
            "modules.world.facade.find_similar_entities",
            new_callable=AsyncMock,
            return_value={},
        ),
    ):
        result = await svc._process_scene(
            db_session,
            novel_with_drafts,
            scene,
            scene_idx=0,
            existing_context="",
            accumulated_memory=[],
            seen_entity_keys=set(),
            workflow_id="wf-test-3",
        )

    assert result["created"] == 1
    mock_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_extract_by_scenes_empty_route_skips_world_context() -> None:
    svc = SceneEntityExtractionService()
    db = Mock()

    with (
        patch.object(svc, "_get_scenes", new_callable=AsyncMock, return_value=[]),
        patch(
            "modules.world.facade.get_world_context",
            new_callable=AsyncMock,
        ) as world_context,
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
        )

    world_context.assert_not_awaited()
    assert result["total_scenes"] == 0
    assert result["checkpoints"] == {"phase2": {"scenes": []}}


@pytest.mark.asyncio
async def test_extract_by_scenes_continues_after_single_transport_failure() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {"novel_id": "novel-1", "scene_index": 1, "chapter_ids": ["1"]},
        {"novel_id": "novel-1", "scene_index": 2, "chapter_ids": ["2"]},
    ]
    db = Mock()
    db.flush = AsyncMock()

    async def process_scene(*args, **kwargs):
        scene = args[2]
        if scene["scene_index"] == 1:
            raise LLMConnectionError("connection failed")
        return {
            "created": 1,
            "relations": 0,
            "deltas": 0,
            "created_entity_ids": ["entity-scene-2"],
            "created_relation_ids": [],
            "created_delta_ids": [],
            "updated_context": "updated",
            "updated_memory": [{"scene_index": 2, "entities": 1}],
        }

    with (
        patch.object(svc, "_get_scenes", new_callable=AsyncMock, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            new_callable=AsyncMock,
            return_value=Mock(entities=[]),
        ) as world_context,
        patch.object(
            svc,
            "_process_scene",
            new_callable=AsyncMock,
            side_effect=process_scene,
        ) as process_scene,
        _patched_phase2_summaries(svc),
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            existing_checkpoints={"unrelated-scene": {"status": "done"}},
        )

    assert result["total_created"] == 1
    assert result["total_scenes"] == 2
    assert result["degraded"] is True
    assert result["error_kind"] == "connection_error"
    assert result["failed_scene_indices"] == [1]
    assert result["completed_scenes"] == 1
    assert result["skipped_scenes"] == 0
    assert result["stopped_early"] is False
    assert process_scene.await_count == 2
    world_context.assert_awaited_once_with(
        db,
        "00000000-0000-0000-0000-000000000001",
        reveal_mode="author_safe",
        limit=500,
        include_review=True,
    )


@pytest.mark.asyncio
async def test_extract_by_scenes_stops_after_repeated_transport_failures() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {"novel_id": "novel-1", "scene_index": 1, "chapter_ids": ["1"]},
        {"novel_id": "novel-1", "scene_index": 2, "chapter_ids": ["2"]},
        {"novel_id": "novel-1", "scene_index": 3, "chapter_ids": ["3"]},
        {"novel_id": "novel-1", "scene_index": 4, "chapter_ids": ["4"]},
    ]
    db = Mock()
    db.flush = AsyncMock()

    with (
        patch.object(svc, "_get_scenes", new_callable=AsyncMock, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            new_callable=AsyncMock,
            return_value=Mock(entities=[]),
        ),
        patch.object(
            svc,
            "_process_scene",
            new_callable=AsyncMock,
            side_effect=LLMConnectionError("connection failed"),
        ) as process_scene,
        _patched_phase2_summaries(svc),
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            existing_checkpoints={"unrelated-scene": {"status": "done"}},
        )

    assert result["total_created"] == 0
    assert result["total_scenes"] == 4
    assert result["degraded"] is True
    assert result["error_kind"] == "connection_error"
    assert result["failed_scene_indices"] == [1, 2, 3]
    assert result["completed_scenes"] == 0
    assert result["skipped_scenes"] == 1
    assert result["stopped_early"] is True
    assert process_scene.await_count == 3


@pytest.mark.asyncio
async def test_phase2_records_checkpoint_for_each_successful_scene() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": "scene-a",
            "novel_id": "novel-1",
            "scene_index": 1,
            "chapter_ids": ["1"],
        },
        {
            "id": "scene-b",
            "novel_id": "novel-1",
            "scene_index": 2,
            "chapter_ids": ["2"],
        },
    ]
    db = Mock()
    db.flush = AsyncMock()

    async def process_scene(*args, **kwargs):
        scene = args[2]
        scene_idx = args[3]
        return {
            "created": 1,
            "relations": 1,
            "deltas": 1,
            "created_entity_ids": [f"entity-{scene['id']}"],
            "created_relation_ids": [f"relation-{scene['id']}"],
            "created_delta_ids": [f"delta-{scene['id']}"],
            "updated_context": "updated",
            "updated_memory": [{"scene_index": scene_idx, "entities": 1}],
        }

    with (
        patch.object(svc, "_get_scenes", new_callable=AsyncMock, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            new_callable=AsyncMock,
            return_value=Mock(entities=[]),
        ),
        patch.object(
            svc,
            "_process_scene",
            new_callable=AsyncMock,
            side_effect=process_scene,
        ),
        _patched_phase2_summaries(svc),
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_id="wf-phase2-checkpoint",
            existing_checkpoints={"unrelated-scene": {"status": "done"}},
        )

    checkpoints = result["checkpoints"]["phase2"]["scenes"]
    assert [checkpoint["scene_id"] for checkpoint in checkpoints] == [
        "scene-a",
        "scene-b",
    ]
    assert all(checkpoint["status"] == "done" for checkpoint in checkpoints)
    assert checkpoints[0]["created_entity_ids"] == ["entity-scene-a"]
    assert checkpoints[0]["created_relation_ids"] == ["relation-scene-a"]
    assert checkpoints[0]["created_delta_ids"] == ["delta-scene-a"]
    assert checkpoints[0]["workflow_id"] == "wf-phase2-checkpoint"
    assert checkpoints[0]["source"] == "deep_import"
    assert checkpoints[0]["auto_ingested"] is True


@pytest.mark.asyncio
async def test_phase2_small_sample_uses_bulk_extraction_with_scene_checkpoints() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": "scene-a",
            "novel_id": "novel-1",
            "scene_index": 1,
            "chapter_ids": ["1"],
        },
        {
            "id": "scene-b",
            "novel_id": "novel-1",
            "scene_index": 2,
            "chapter_ids": ["2"],
        },
    ]
    db = Mock()
    db.flush = AsyncMock()

    with (
        patch.object(svc, "_get_scenes", new_callable=AsyncMock, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            new_callable=AsyncMock,
            return_value=Mock(entities=[]),
        ),
        patch.object(
            svc,
            "_process_scenes_bulk",
            new_callable=AsyncMock,
            return_value={
                "created": 2,
                "relations": 1,
                "deltas": 1,
                "created_entity_ids": ["entity-a", "entity-b"],
                "created_relation_ids": ["relation-a"],
                "created_delta_ids": ["delta-a"],
            },
        ) as bulk,
        patch.object(svc, "_process_scene", new_callable=AsyncMock) as process_scene,
        _patched_phase2_summaries(svc),
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_id="wf-phase2-bulk",
        )

    bulk.assert_awaited_once()
    process_scene.assert_not_awaited()
    assert result["total_created"] == 2
    assert result["completed_scenes"] == 2
    checkpoints = result["checkpoints"]["phase2"]["scenes"]
    assert [checkpoint["scene_id"] for checkpoint in checkpoints] == [
        "scene-a",
        "scene-b",
    ]
    assert all(checkpoint["status"] == "done" for checkpoint in checkpoints)
    assert checkpoints[0]["created_entity_ids"] == ["entity-a", "entity-b"]


@pytest.mark.asyncio
async def test_phase2_small_sample_prefers_parallel_scene_llm() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"scene-{index}",
            "novel_id": "novel-1",
            "scene_index": index,
            "chapter_ids": [str(index)],
        }
        for index in range(1, 9)
    ]
    db = Mock()
    db.flush = AsyncMock()
    parallel_result = {
        "total_created": 24,
        "total_relations": 0,
        "total_deltas": 0,
        "total_scenes": 8,
        "degraded": False,
        "error_kind": None,
        "error_message": None,
        "failed_scene_indices": [],
        "completed_scenes": 8,
        "skipped_scenes": 0,
        "rerun_scenes": 0,
        "stopped_early": False,
        "checkpoints": {"phase2": {"scenes": []}},
        "parallel_llm_fallback": True,
        "bulk_error_kind": "small_sample_parallel_default",
    }

    with (
        patch.object(svc, "_get_scenes", new_callable=AsyncMock, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            new_callable=AsyncMock,
            return_value=Mock(entities=[]),
        ),
        patch.object(
            svc,
            "_process_scenes_parallel_llm",
            new_callable=AsyncMock,
            return_value=parallel_result,
        ) as parallel,
        patch.object(svc, "_process_scenes_bulk", new_callable=AsyncMock) as bulk,
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_id="wf-phase2-parallel-default",
        )

    parallel.assert_awaited_once()
    bulk.assert_not_awaited()
    assert result["total_created"] == 24
    assert result["bulk_error_kind"] == "small_sample_parallel_default"


@pytest.mark.asyncio
async def test_phase2_large_without_checkpoints_uses_batched_route() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"scene-{index}",
            "novel_id": "novel-1",
            "scene_index": index,
            "chapter_ids": [str(index)],
        }
        for index in range(1, 14)
    ]
    db = Mock()
    db.flush = AsyncMock()
    batched_result = {
        "total_created": 13,
        "total_relations": 0,
        "total_aliases": 0,
        "total_deltas": 0,
        "total_scenes": 13,
        "degraded": False,
        "error_kind": None,
        "error_message": None,
        "failed_scene_indices": [],
        "completed_scenes": 13,
        "skipped_scenes": 0,
        "rerun_scenes": 0,
        "stopped_early": False,
        "checkpoints": {"phase2": {"scenes": []}},
    }

    with (
        patch.object(svc, "_get_scenes", new_callable=AsyncMock, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            new_callable=AsyncMock,
            return_value=Mock(entities=[]),
        ),
        patch.object(
            svc,
            "_process_scenes_batched",
            new_callable=AsyncMock,
            return_value=batched_result,
        ) as batched,
        patch.object(
            svc,
            "_process_scenes_parallel_llm",
            new_callable=AsyncMock,
        ) as parallel,
        patch.object(svc, "_process_scenes_bulk", new_callable=AsyncMock) as bulk,
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_id="wf-phase2-batched-route",
        )

    batched.assert_awaited_once()
    parallel.assert_not_awaited()
    bulk.assert_not_awaited()
    assert result["total_created"] == 13


@pytest.mark.asyncio
async def test_phase2_bulk_failure_uses_parallel_llm_fallback() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": "scene-a",
            "novel_id": "novel-1",
            "scene_index": 1,
            "chapter_ids": ["1"],
        }
    ]
    db = Mock()
    db.flush = AsyncMock()

    parallel_result = {
        "total_created": 3,
        "total_relations": 0,
        "total_deltas": 0,
        "total_scenes": 1,
        "degraded": False,
        "error_kind": None,
        "error_message": None,
        "failed_scene_indices": [],
        "completed_scenes": 1,
        "skipped_scenes": 0,
        "rerun_scenes": 0,
        "stopped_early": False,
        "checkpoints": {"phase2": {"scenes": []}},
        "parallel_llm_fallback": True,
        "bulk_error_kind": "timeout",
    }

    with (
        patch.object(svc, "_get_scenes", new_callable=AsyncMock, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            new_callable=AsyncMock,
            return_value=Mock(entities=[]),
        ),
        patch.object(
            svc,
            "_process_scenes_bulk",
            new_callable=AsyncMock,
            side_effect=TimeoutError("bulk timeout"),
        ) as bulk,
        patch.object(
            svc,
            "_process_scenes_parallel_llm",
            new_callable=AsyncMock,
            return_value=parallel_result,
        ) as parallel,
        patch.object(
            svc,
            "_phase2_alias_relation_result",
            new_callable=AsyncMock,
            return_value={"total_aliases": 2},
        ) as alias_result,
        patch.object(
            svc,
            "_merge_alias_relation_result",
            return_value={**parallel_result, "total_aliases": 2},
        ) as merge_alias,
        patch.object(svc, "_process_scene", new_callable=AsyncMock) as process_scene,
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_id="wf-phase2-parallel",
        )

    bulk.assert_awaited_once()
    parallel.assert_awaited_once()
    alias_result.assert_awaited_once()
    merge_alias.assert_called_once()
    process_scene.assert_not_awaited()
    assert result["parallel_llm_fallback"] is True
    assert result["bulk_error_kind"] == "timeout"
    assert result["total_aliases"] == 2


@pytest.mark.asyncio
async def test_persistent_phase2_scene_threads_end_chapter_into_activation() -> None:
    svc = SceneEntityExtractionService()
    scene_id = str(uuid.uuid4())
    scenes = [
        {
            "id": scene_id,
            "novel_id": "00000000-0000-0000-0000-000000000001",
            "scene_index": 7,
            "chapter_ids": ["78", "79", "80", "81"],
        }
    ]
    expected = {
        "total_created": 0,
        "total_relations": 0,
        "total_aliases": 0,
        "total_deltas": 0,
        "total_scenes": 1,
        "degraded": False,
        "error_kind": None,
        "error_message": None,
        "failed_scene_indices": [],
        "completed_scenes": 1,
        "skipped_scenes": 0,
        "rerun_scenes": 0,
        "stopped_early": False,
        "checkpoints": {"phase2": {"scenes": []}},
    }

    with (
        patch.object(svc, "_get_scenes", new_callable=AsyncMock, return_value=scenes),
        patch.object(
            svc,
            "_process_scenes_parallel_llm",
            new_callable=AsyncMock,
            return_value=expected,
        ) as activated,
    ):
        result = await svc.extract_by_scenes(
            Mock(),
            "00000000-0000-0000-0000-000000000001",
            end_chapter=80,
        )

    assert result is expected
    assert activated.await_args.kwargs["visible_until_chapter"] == 80
    assert activated.await_args.args[2] == scenes


@pytest.mark.asyncio
async def test_parallel_llm_fallback_extracts_before_serial_persistence() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"scene-{index}",
            "novel_id": "novel-1",
            "scene_index": index,
            "chapter_ids": [str(index)],
            "title": f"Scene {index}",
        }
        for index in (1, 2)
    ]
    db = Mock()
    db.flush = AsyncMock()
    events: list[str] = []

    async def load_scene(_db, scene):
        return f"正文 {scene['scene_index']}"

    async def create_snapshot(*_args, **_kwargs):
        scene = _args[2]
        return Mock(id=f"snapshot-{scene['scene_index']}")

    async def call_llm(chapters_text: str, *_args, **_kwargs):
        events.append(f"llm-{chapters_text[-1]}")
        await asyncio.sleep(0.01)
        return SceneEntityExtractionOutput(
            entities=[
                ExtractedEntity(
                    name=f"实体{chapters_text[-1]}",
                    entity_type="character",
                    suggested_action="create_new",
                )
            ],
            relations=[],
            delta_events=[],
        )

    async def persist_entities(*_args, **kwargs):
        result_refs = kwargs["result_refs"]
        scene_index = kwargs["scene_index"]
        events.append(f"persist-{scene_index}")
        result_refs.append({"type": "core_entity", "id": f"entity-{scene_index}"})
        return 1

    with (
        patch.object(svc, "_load_scene_chapters", new=load_scene),
        patch.object(svc, "_create_phase2_snapshot", new=create_snapshot),
        patch.object(svc, "_call_llm_extraction", new=call_llm),
        patch.object(svc, "_persist_entities", new=persist_entities),
        patch.object(
            svc,
            "_persist_relations",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch.object(
            svc,
            "_record_deltas",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch.object(
            svc,
            "_supplement_small_sample_entities",
            new_callable=AsyncMock,
            return_value={
                "created": 0,
                "created_entity_ids": [],
                "supplemental_llm_created": 0,
                "fallback_created": 0,
                "supplemental_error_kind": None,
            },
        ),
        _patched_phase2_summaries(svc),
        patch("modules.context.facade.succeed_context_snapshot", AsyncMock()),
        patch("modules.memory.facade.capture_snapshot", AsyncMock()),
    ):
        result = await svc._process_scenes_parallel_llm(
            db,
            "00000000-0000-0000-0000-000000000001",
            scenes,
            "无已有对象",
            workflow_id="wf-phase2-parallel",
            on_scene_progress=None,
            bulk_error_kind="schema_error",
        )

    first_persist_index = min(
        index for index, event in enumerate(events) if event.startswith("persist-")
    )
    assert all(event.startswith("llm-") for event in events[:first_persist_index])
    assert result["parallel_llm_fallback"] is True
    assert result["bulk_error_kind"] == "schema_error"
    assert result["total_created"] == 2
    checkpoints = result["checkpoints"]["phase2"]["scenes"]
    assert [checkpoint["created_entity_ids"] for checkpoint in checkpoints] == [
        ["entity-1"],
        ["entity-2"],
    ]


@pytest.mark.asyncio
async def test_phase2_batched_progress_callback_uses_db_lock() -> None:
    svc = SceneEntityExtractionService()
    db = Mock()
    db_lock = asyncio.Lock()
    progress_lock = asyncio.Lock()
    progress_lock_states: list[bool] = []
    scenes = [
        {
            "id": f"scene-{index}",
            "novel_id": "novel-1",
            "scene_index": index,
            "chapter_ids": [str(index)],
        }
        for index in (1, 2)
    ]

    async def process_scene(*_args, **kwargs):
        assert kwargs["db_lock"] is db_lock
        return {
            "created": 1,
            "relations": 0,
            "deltas": 0,
            "created_entity_ids": [],
            "created_relation_ids": [],
            "created_delta_ids": [],
            "updated_context": "updated",
            "updated_memory": [],
        }

    async def on_scene_progress(_completed: int, _total: int) -> None:
        progress_lock_states.append(db_lock.locked())

    with patch.object(
        svc,
        "_process_scene",
        new_callable=AsyncMock,
        side_effect=process_scene,
    ):
        result = await svc._process_scene_batch_serial(
            db,
            "00000000-0000-0000-0000-000000000001",
            scenes,
            batch_index=0,
            existing_context="无已有对象",
            workflow_id="wf-phase2-lock",
            completed_counter={"value": 0},
            progress_lock=progress_lock,
            db_lock=db_lock,
            total_scenes=len(scenes),
            on_scene_progress=on_scene_progress,
        )

    assert result["created"] == 2
    assert progress_lock_states == [True, True]


@pytest.mark.asyncio
async def test_phase2_batched_failed_batch_records_scene_ids_and_fallback_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PHASE2_BATCH_SIZE_SCENES", "12")
    monkeypatch.setenv("PHASE2_BATCH_CONCURRENCY", "6")
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"scene-{index}",
            "novel_id": "novel-1",
            "scene_index": 0,
            "chapter_ids": [str(index)],
        }
        for index in range(1, 14)
    ]
    db = Mock()

    async def process_batch(*_args, **kwargs):
        if kwargs["batch_index"] == 0:
            raise RuntimeError("session state changed")
        return {
            "created": 1,
            "relations": 0,
            "deltas": 0,
            "failed_scene_indices": [],
            "failed_scene_ids": [],
            "checkpoints": [],
            "degraded": False,
            "error_kind": None,
            "error_message": None,
            "persistence_stats": svc._empty_phase2_persistence_stats(),
        }

    with (
        patch.object(
            svc,
            "_process_scene_batch_serial",
            new_callable=AsyncMock,
            side_effect=process_batch,
        ),
        patch.object(
            svc,
            "_run_boundary_supplements",
            new_callable=AsyncMock,
            return_value={
                "phase2_boundary_windows_total": 1,
                "phase2_boundary_windows_completed": 0,
                "phase2_boundary_supplement_counts": {
                    "created": 0,
                    "aliases": 0,
                    "relations": 0,
                    "link_suggestions": 0,
                    "conflicts": 0,
                    "failed": 0,
                },
                "degraded": False,
                "error_kind": None,
                "error_message": None,
            },
        ),
        patch.object(
            svc,
            "_phase2_flush_with_timeout",
            new_callable=AsyncMock,
            return_value={"degraded": False, "error_kind": None, "error_message": None},
        ),
        _patched_phase2_summaries(svc),
        patch.object(
            svc,
            "_phase2_alias_relation_result",
            new_callable=AsyncMock,
            return_value=svc._skipped_alias_relation_result(13, reason="test"),
        ),
    ):
        result = await svc._process_scenes_batched(
            db,
            "00000000-0000-0000-0000-000000000001",
            scenes,
            "无已有对象",
            workflow_id="wf-phase2-failed-batch",
            on_scene_progress=None,
        )

    assert result["phase2_failed_batches"] == [0]
    assert result["failed_scene_indices"] == list(range(1, 13))
    assert result["failed_scene_ids"] == [f"scene-{index}" for index in range(1, 13)]


@pytest.mark.asyncio
async def test_bulk_llm_extractions_keep_successful_groups_when_one_group_fails() -> None:
    svc = SceneEntityExtractionService()
    output = SceneEntityExtractionOutput(
        entities=[
            ExtractedEntity(
                name="克莱恩",
                entity_type="character",
                suggested_action="create_new",
            )
        ],
        relations=[],
        delta_events=[],
    )

    async def call_llm(chapters_text: str, *_args, **_kwargs):
        if "Scene 4" in chapters_text:
            raise TimeoutError("slow group")
        return output

    with patch.object(
        svc,
        "_call_llm_extraction",
        new_callable=AsyncMock,
        side_effect=call_llm,
    ):
        results = await svc._call_bulk_llm_extractions(
            [f"Scene {index}" for index in range(1, 7)],
            "无已有对象",
            "批量上下文",
        )

    assert len(results) == 5
    assert all(result == output for result in results)


@pytest.mark.asyncio
async def test_bulk_llm_extractions_use_fast_no_retry_calls() -> None:
    svc = SceneEntityExtractionService()
    output = SceneEntityExtractionOutput(
        entities=[],
        relations=[],
        delta_events=[],
    )
    calls: list[dict] = []

    async def call_llm(_chapters_text: str, *_args, **kwargs):
        calls.append(kwargs)
        return output

    with patch.object(
        svc,
        "_call_llm_extraction",
        new_callable=AsyncMock,
        side_effect=call_llm,
    ):
        await svc._call_bulk_llm_extractions(
            ["Scene 1"],
            "无已有对象",
            "批量上下文",
        )

    assert calls == [
        {
            "max_tokens": scene_entity_extraction_module.PHASE2_BULK_MAX_TOKENS,
            "client_timeout": (
                scene_entity_extraction_module.PHASE2_BULK_PROVIDER_TIMEOUT_SECONDS
            ),
            "max_fix_attempts": 0,
            "transport_retries": False,
            "diagnostics": [],
        }
    ]


@pytest.mark.asyncio
async def test_bulk_scene_entity_extractor_prefetches_scene_drafts_once() -> None:
    scenes = [
        {
            "id": "scene-1",
            "novel_id": "novel-1",
            "scene_index": 1,
            "chapter_ids": ["1", "2"],
        },
        {
            "id": "scene-2",
            "novel_id": "novel-1",
            "scene_index": 2,
            "chapter_ids": ["2", "3"],
        },
    ]
    calls: list[tuple[str, list[int]]] = []

    async def list_latest_drafts_for_chapters(_db, novel_id, chapter_indices):
        calls.append((novel_id, list(chapter_indices)))
        return [
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=index,
                title=f"第{index}章",
                content=f"第{index}章正文",
            )
            for index in chapter_indices
        ]

    service = Mock()
    service._scene_source_chapter_index.return_value = 1
    service._scene_chunks_by_chapter.side_effect = scene_chunks_by_chapter
    service._scene_chapter_ids.side_effect = scene_chapter_ids
    service._select_scene_text.side_effect = select_scene_text
    service._scene_context_header.side_effect = scene_context_header
    service._bulk_entity_memory_context.return_value = "批量上下文"
    service._create_phase2_snapshot = AsyncMock(return_value=Mock(id="snapshot-1"))
    service._call_bulk_llm_extractions = AsyncMock(
        return_value=[SceneEntityExtractionOutput()]
    )
    service._persist_entities = AsyncMock(return_value=0)
    service._persist_relations = AsyncMock(return_value=0)
    service._record_deltas = AsyncMock(return_value=0)
    service._scene_id.return_value = "scene-1"
    service._scene_provenance_key.return_value = "wf:scene-1"
    service._result_ref_ids.return_value = []
    service._load_scene_chapters = AsyncMock(
        side_effect=AssertionError("bulk extractor should prefetch drafts once")
    )

    with (
        patch(
            "modules.writing.facade.list_latest_drafts_for_chapters",
            new=list_latest_drafts_for_chapters,
        ),
        patch("modules.context.facade.succeed_context_snapshot", new=AsyncMock()),
        patch("modules.memory.facade.capture_snapshot", new=AsyncMock()),
    ):
        result = await BulkSceneEntityExtractor(service).run(
            Mock(),
            "novel-1",
            scenes,
            "无已有对象",
            workflow_id="wf-bulk",
        )

    assert result["created"] == 0
    assert calls == [("novel-1", [1, 2, 3])]
    service._load_scene_chapters.assert_not_awaited()
    service._call_bulk_llm_extractions.assert_awaited_once()
    scene_texts = service._call_bulk_llm_extractions.await_args.args[0]
    assert "第1章正文" in scene_texts[0]
    assert "第2章正文" in scene_texts[0]
    assert "第2章正文" in scene_texts[1]
    assert "第3章正文" in scene_texts[1]


@pytest.mark.asyncio
async def test_small_sample_bulk_supplements_low_entity_count() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"scene-{index}",
            "scene_index": index,
            "title": f"关键 Scene {index}",
        }
        for index in range(8)
    ]
    created_payloads: list[dict] = []

    async def create_entity(_db, _novel_id, payload):
        created_payloads.append(payload)
        return {"id": f"entity-{len(created_payloads)}"}

    class FakeSavepoint:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeDb:
        def begin_nested(self):
            return FakeSavepoint()

    with (
        patch(
            "modules.world.facade.create_entity",
            new=create_entity,
        ),
        patch.object(
            svc,
            "_supplement_small_sample_entities_with_llm",
            new_callable=AsyncMock,
            return_value={"created": 0, "created_entity_ids": []},
        ),
    ):
        result = await svc._supplement_small_sample_entities(
            db=FakeDb(),
            nid="00000000-0000-0000-0000-000000000001",
            scenes=scenes,
            current_count=16,
            workflow_id="wf-phase2",
        )

    assert result == {
        "created": 2,
        "created_entity_ids": ["entity-1", "entity-2"],
        "supplemental_llm_created": 0,
        "fallback_created": 2,
        "supplemental_error_kind": None,
    }
    assert created_payloads[0]["content_json"]["_meta"]["needs_review"] is True
    assert (
        created_payloads[0]["content_json"]["_meta"]["fallback"]
        == "small_sample_entity_minimum"
    )
    assert created_payloads[0]["status"] == "candidate"


@pytest.mark.asyncio
async def test_small_sample_bulk_uses_llm_supplement_before_fallback() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"scene-{index}",
            "scene_index": index,
            "title": f"关键 Scene {index}",
            "chapter_ids": [str(index)],
            "novel_id": "novel-1",
        }
        for index in range(1, 9)
    ]

    with patch.object(
        svc,
        "_supplement_small_sample_entities_with_llm",
        new_callable=AsyncMock,
        return_value={
            "created": 13,
            "created_entity_ids": [f"llm-entity-{index}" for index in range(13)],
        },
    ) as llm_supplement:
        result = await svc._supplement_small_sample_entities(
            db=Mock(),
            nid="00000000-0000-0000-0000-000000000001",
            scenes=scenes,
            current_count=16,
            workflow_id="wf-phase2",
        )

    llm_supplement.assert_awaited_once()
    assert result["created"] == 13
    assert result["supplemental_llm_created"] == 13
    assert result["fallback_created"] == 0
    assert result["created_entity_ids"][0] == "llm-entity-0"


@pytest.mark.asyncio
async def test_small_sample_supplement_includes_review_entities_for_dedup() -> None:
    svc = SceneEntityExtractionService()
    svc._load_small_sample_chapters_text = AsyncMock(return_value="chapter text")
    svc._call_llm_extraction = AsyncMock(return_value=SimpleNamespace(entities=[]))
    svc._persist_entities = AsyncMock(return_value=0)
    world_context = AsyncMock(return_value=SimpleNamespace(entities=[]))
    nid = uuid.uuid4()
    db = Mock()

    with patch(
        "modules.world.facade.get_world_context",
        world_context,
    ):
        result = await BulkSceneEntityExtractor(svc).supplement_with_llm(
            db,
            nid,
            [{"chapter_ids": ["1"]}],
            needed=3,
            workflow_id="wf-review-dedup",
        )

    assert result == {"created": 0, "created_entity_ids": []}
    world_context.assert_awaited_once_with(
        db,
        str(nid),
        reveal_mode="author_safe",
        limit=500,
        include_review=True,
    )


@pytest.mark.asyncio
async def test_small_sample_supplement_timeout_falls_back(monkeypatch) -> None:
    import modules.imports.entity_extraction as public_module

    monkeypatch.setattr(
        public_module,
        "PHASE2_SMALL_SAMPLE_SUPPLEMENT_TIMEOUT_SECONDS",
        0.01,
    )
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"scene-{index}",
            "scene_index": index,
            "title": f"关键 Scene {index}",
            "chapter_ids": [str(index)],
            "novel_id": "novel-1",
        }
        for index in range(1, 9)
    ]
    created_payloads: list[dict] = []

    async def slow_supplement(*_args, **_kwargs):
        await asyncio.sleep(1)
        return {"created": 1, "created_entity_ids": ["too-late"]}

    async def create_entity(_db, _novel_id, payload):
        created_payloads.append(payload)
        return {"id": f"entity-{len(created_payloads)}"}

    class FakeSavepoint:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeDb:
        def begin_nested(self):
            return FakeSavepoint()

    with (
        patch.object(
            svc,
            "_supplement_small_sample_entities_with_llm",
            new=slow_supplement,
        ),
        patch("modules.world.facade.create_entity", new=create_entity),
    ):
        result = await svc._supplement_small_sample_entities(
            db=FakeDb(),
            nid="00000000-0000-0000-0000-000000000001",
            scenes=scenes,
            current_count=16,
            workflow_id="wf-phase2",
        )

    assert result["supplemental_llm_created"] == 0
    assert result["fallback_created"] == 2
    assert result["supplemental_error_kind"] == "timeout"
    assert result["created_entity_ids"] == ["entity-1", "entity-2"]
    assert created_payloads[0]["content_json"]["_meta"]["needs_review"] is True


def test_trim_supplement_chapter_text_keeps_head_and_tail() -> None:
    text = "A" * 5000 + "MIDDLE" + "Z" * 5000

    trimmed = SceneEntityExtractionService._trim_supplement_chapter_text(text)

    assert len(trimmed) < len(text)
    assert trimmed.startswith("A" * 100)
    assert trimmed.endswith("Z" * 100)
    assert "章节中段已压缩" in trimmed


def test_bulk_entity_memory_context_adds_1_to_7_recall_guidance() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"scene-{index}",
            "scene_index": index,
            "chapter_ids": [str(index)],
        }
        for index in range(1, 8)
    ]

    context = svc._bulk_entity_memory_context(scenes)

    assert "整体目标应接近 24-32 个长期资产" in context
    assert "主要人物及别名" in context
    assert "神秘学概念/力量体系" in context


def test_bulk_entity_memory_context_keeps_generic_guidance_for_other_ranges() -> None:
    svc = SceneEntityExtractionService()
    context = svc._bulk_entity_memory_context(
        [
            {
                "id": "scene-10",
                "scene_index": 10,
                "chapter_ids": ["10"],
            }
        ]
    )

    assert "小样本批量实体提取" in context
    assert "整体目标应接近 24-32 个长期资产" not in context


@pytest.mark.asyncio
async def test_phase2_recovery_skips_successful_scene_and_reruns_failed_scene() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": "scene-a",
            "novel_id": "novel-1",
            "scene_index": 1,
            "chapter_ids": ["1"],
        },
        {
            "id": "scene-b",
            "novel_id": "novel-1",
            "scene_index": 2,
            "chapter_ids": ["2"],
        },
    ]
    db = Mock()
    db.flush = AsyncMock()

    with (
        patch.object(svc, "_get_scenes", new_callable=AsyncMock, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            new_callable=AsyncMock,
            return_value=Mock(entities=[]),
        ),
        patch.object(
            svc,
            "_process_scene",
            new_callable=AsyncMock,
            return_value={
                "created": 1,
                "relations": 0,
                "deltas": 0,
                "created_entity_ids": ["entity-scene-b"],
                "created_relation_ids": [],
                "created_delta_ids": [],
                "updated_context": "updated",
                "updated_memory": [{"scene_index": 2, "entities": 1}],
            },
        ) as process_scene,
        patch.object(svc, "_process_scenes_bulk", new_callable=AsyncMock) as bulk,
        patch.object(
            svc,
            "_process_scenes_parallel_llm",
            new_callable=AsyncMock,
        ) as parallel,
        patch.object(svc, "_process_scenes_batched", new_callable=AsyncMock) as batched,
        _patched_phase2_summaries(svc),
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_id="wf-phase2-recovery",
            existing_checkpoints={
                "phase2": {
                    "scenes": [
                        {"scene_id": "scene-a", "status": "done", "retry_count": 0},
                        {"scene_id": "scene-b", "status": "failed", "retry_count": 0},
                    ]
                }
            },
        )

    assert result["skipped_scenes"] == 1
    assert result["rerun_scenes"] == 1
    assert process_scene.await_count == 1
    bulk.assert_not_awaited()
    parallel.assert_not_awaited()
    batched.assert_not_awaited()
    processed_scene = process_scene.await_args.args[2]
    assert processed_scene["id"] == "scene-b"
    checkpoints = result["checkpoints"]["phase2"]["scenes"]
    assert checkpoints[0]["scene_id"] == "scene-a"
    assert checkpoints[0]["status"] == "skipped"
    assert checkpoints[1]["scene_id"] == "scene-b"
    assert checkpoints[1]["status"] == "done"
    assert checkpoints[1]["retry_count"] == 1


@pytest.mark.asyncio
async def test_phase2_failed_scene_checkpoint_contains_error_status() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": "scene-failed",
            "novel_id": "novel-1",
            "scene_index": 5,
            "chapter_ids": ["5"],
        }
    ]
    db = Mock()
    db.flush = AsyncMock()

    with (
        patch.object(svc, "_get_scenes", new_callable=AsyncMock, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            new_callable=AsyncMock,
            return_value=Mock(entities=[]),
        ),
        patch.object(
            svc,
            "_process_scene",
            new_callable=AsyncMock,
            side_effect=RuntimeError("phase2 boom"),
        ),
        _patched_phase2_summaries(svc),
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_id="wf-phase2-failed",
            existing_checkpoints={"unrelated-scene": {"status": "done"}},
        )

    checkpoint = result["checkpoints"]["phase2"]["scenes"][0]
    assert checkpoint["scene_id"] == "scene-failed"
    assert checkpoint["status"] == "failed"
    assert checkpoint["error_kind"] == "RuntimeError"
    assert checkpoint["error"] == "phase2 boom"
