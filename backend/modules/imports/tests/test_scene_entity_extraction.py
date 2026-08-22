"""SceneEntityExtractionService 单元/集成测试。

覆盖 Phase 2 的实体/关系持久化、auto_ingested 元数据、Delta 记录。
"""

from __future__ import annotations

import json
from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.errors import LLMConnectionError
from modules.imports.context_snapshot_helpers import build_phase2_snapshot_payload
from modules.imports.entity_extraction.scene_entity_alias_relation import (
    _compact_entity_index_for_scene,
    _effective_alias_relation_total_timeout_seconds,
    _trim_phase2b_scene_text,
)
from modules.imports.entity_extraction.scene_entity_checkpoint import (
    phase2a_input_fingerprint,
    scene_input_fingerprint,
)
from modules.imports.entity_extraction.scene_entity_config import (
    PHASE2A_PROMPT_CONTRACT_VERSION,
)
from modules.imports.entity_extraction.scene_entity_extraction import (
    SceneEntityExtractionService,
)
from modules.imports.entity_extraction.scene_entity_strategy import (
    SceneEntityExtractionStrategySelector,
)
from modules.imports.llm_schemas import (
    AliasRelationExtractionOutput,
    ExtractedAlias,
    ExtractedEntity,
    ExtractedRelation,
    Phase2bRelationObservation,
    SceneCandidateOutput,
    SceneEntityExtractionOutput,
)


def test_phase2_runtime_protocol_remains_import_compatible() -> None:
    from modules.imports.entity_extraction import SceneEntityExtractionRuntime
    from modules.imports.entity_extraction.scene_entity_runtime import (
        SceneEntityExtractionRuntime as RuntimeFromModule,
    )

    assert SceneEntityExtractionRuntime is RuntimeFromModule


def test_phase2a_snapshot_replays_prompt_context_but_keeps_source_ids_audit_only() -> (
    None
):
    payload = build_phase2_snapshot_payload(
        scene={"id": "scene-1", "scene_index": 1, "chapter_ids": ["1"]},
        source_chapter_index=1,
        existing_context="legacy existing",
        memory_context="legacy memory",
        chapters_text="完整 Scene 正文",
        accumulated_memory=[],
        model="fixture-model",
        max_tokens=1024,
        temperature=0.3,
        activation={
            "activation_version": "import-context-v2",
            "prompt_contract_version": PHASE2A_PROMPT_CONTRACT_VERSION,
            "context_fingerprint": "context-fingerprint",
            "scene_card": {"title": "锁定 Scene"},
            "outline_context": {"plot_threads": [{"name": "主线"}]},
            "identity_candidates": [{"prompt_ref": "entity-001", "name": "沈砚"}],
            "previous_scene_briefs": [{"title": "前序摘要"}],
            "previous_scene_evidence": [{"text": "前序证据"}],
            "current_scene_sources": [{"draft_id": "private-draft-id"}],
            "sources": [
                {
                    "type": "world_entity",
                    "id": "private-entity-id",
                    "prompt_ref": "entity-001",
                }
            ],
        },
    )

    rendered = json.loads(payload["rendered_context"])
    assert rendered["current_scene_text"] == "完整 Scene 正文"
    assert rendered["previous_scene_briefs"] == [{"title": "前序摘要"}]
    assert rendered["previous_scene_evidence"] == [{"text": "前序证据"}]
    assert "private-draft-id" not in payload["rendered_context"]
    assert "private-entity-id" not in payload["rendered_context"]
    assert payload["included_asset_ids"]["existing_entities"] == ["private-entity-id"]
    assert payload["section_metadata"]["activation"]["current_scene_sources"] == [
        {"draft_id": "private-draft-id"}
    ]


class _FakeSavepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeNestedDb:
    def begin_nested(self):
        return _FakeSavepoint()


async def _snapshot_rows(db_session: AsyncSession, novel_id: str):
    from modules.evidence.facade import list_context_snapshots

    return await list_context_snapshots(db_session, novel_id=novel_id)


@contextmanager
def _patched_phase2_summaries(svc: SceneEntityExtractionService):
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                svc,
                "_phase2_audit_summary",
                autospec=True,
                return_value={},
            )
        )
        stack.enter_context(
            patch.object(
                svc,
                "_phase2_snapshot_health_summary",
                autospec=True,
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


def test_phase2_result_merges_phase2b_checkpoints_into_common_checkpoint_tree() -> None:
    svc = SceneEntityExtractionService()
    phase2_checkpoint = {"scene_id": "scene-1", "status": "done"}
    phase2b_checkpoint = {
        "scene_id": "scene-1",
        "status": "done",
        "input_fingerprint": "fingerprint-1",
    }

    merged = svc._merge_alias_relation_result(
        {
            "total_relations": 0,
            "checkpoints": {"phase2": {"scenes": [phase2_checkpoint]}},
        },
        {
            "total_aliases": 0,
            "total_relations": 0,
            "alias_relation_checkpoints": {"phase2b": {"scenes": [phase2b_checkpoint]}},
        },
    )

    assert merged["checkpoints"] == {
        "phase2": {"scenes": [phase2_checkpoint]},
        "phase2b": {"scenes": [phase2b_checkpoint]},
    }


@pytest.mark.asyncio
async def test_parallel_phase2_skips_only_matching_completed_checkpoint() -> None:
    svc = SceneEntityExtractionService()
    scene = {"novel_id": "novel-1", "scene_index": 1, "chapter_ids": ["1"]}
    scene_text = "Scene 正文"
    fingerprint = phase2a_input_fingerprint(scene, scene_text)
    db = Mock()
    db.flush = AsyncMock()

    with (
        patch.object(svc, "_load_scene_chapters", autospec=True, return_value=scene_text),
        patch.object(svc, "_call_llm_extraction", autospec=True) as call_llm,
        patch.object(
            svc,
            "_phase2_flush_with_timeout",
            autospec=True,
            return_value={"degraded": False, "error_kind": None, "error_message": None},
        ),
        _patched_phase2_summaries(svc),
    ):
        result = await svc._process_scenes_parallel_llm(
            db,
            "00000000-0000-0000-0000-000000000001",
            [scene],
            "无已有对象",
            workflow_id="wf-fingerprint",
            on_scene_progress=None,
            bulk_error_kind="test",
            include_alias_relations=False,
            existing_checkpoints={
                "scene_index:1": {
                    "status": "done",
                    "input_fingerprint": fingerprint,
                    "created_entity_ids": ["entity-1"],
                }
            },
        )

    call_llm.assert_not_awaited()
    assert result["rerun_scenes"] == 0
    checkpoint = result["checkpoints"]["phase2"]["scenes"][0]
    assert checkpoint["status"] == "skipped"
    assert checkpoint["input_fingerprint"] == fingerprint


@pytest.mark.parametrize("previous_fingerprint", [None, "stale-fingerprint"])
@pytest.mark.asyncio
async def test_parallel_phase2_reruns_untrusted_completed_checkpoint(
    previous_fingerprint: str | None,
) -> None:
    svc = SceneEntityExtractionService()
    scene = {"novel_id": "novel-1", "scene_index": 1, "chapter_ids": ["1"]}
    db = Mock()
    db.flush = AsyncMock()

    with (
        patch.object(svc, "_load_scene_chapters", autospec=True, return_value=""),
        patch.object(
            svc,
            "_phase2_flush_with_timeout",
            autospec=True,
            return_value={"degraded": False, "error_kind": None, "error_message": None},
        ),
        _patched_phase2_summaries(svc),
    ):
        result = await svc._process_scenes_parallel_llm(
            db,
            "00000000-0000-0000-0000-000000000001",
            [scene],
            "无已有对象",
            workflow_id="wf-fingerprint",
            on_scene_progress=None,
            bulk_error_kind="test",
            include_alias_relations=False,
            existing_checkpoints={
                "scene_index:1": {
                    "status": "done",
                    "input_fingerprint": previous_fingerprint,
                }
            },
        )

    assert result["rerun_scenes"] == 1
    checkpoint = result["checkpoints"]["phase2"]["scenes"][0]
    assert checkpoint["input_fingerprint"] == phase2a_input_fingerprint(scene, "")


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
                    "entity_ref": "entity-001",
                    "alias": "周明瑞",
                    "alias_kind": "name",
                    "alias_type": "本名",
                    "identity_scope": "durable",
                    "identity_basis": "明确自称",
                    "evidence_quotes": ["我叫周明瑞"],
                    "confidence": "85%",
                },
                {
                    "entity_ref": "entity-002",
                    "alias": "妹妹",
                    "alias_kind": "title",
                    "alias_type": "亲属称谓",
                    "identity_scope": "context_bound",
                    "identity_basis": "亲属称呼",
                    "evidence_quotes": ["妹妹梅丽莎"],
                    "confidence": "高",
                },
            ],
            "relations": [
                {
                    "source_ref": "entity-001",
                    "target_ref": "entity-002",
                    "relation_kind": "social",
                    "relation_type": "sibling",
                    "persistence_scope": "enduring",
                    "directionality": "symmetric",
                    "claim_status": "established",
                    "description": "兄妹",
                    "strength": "较高",
                    "basis": "亲属称呼",
                    "evidence_quotes": ["妹妹梅丽莎"],
                    "confidence": "85%",
                }
            ],
        }
    )

    assert output.aliases[0].alias_kind == "name"
    assert output.aliases[0].alias_type == "本名"
    assert output.aliases[0].confidence == 0.85
    assert output.aliases[1].alias_kind == "title"
    assert output.aliases[1].alias_type == "亲属称谓"
    assert output.aliases[1].confidence == 0.9
    assert output.relations[0].relation_kind == "social"
    assert output.relations[0].strength == 0.8

    tolerant_output = AliasRelationExtractionOutput.model_validate(
        {"aliases": None, "relations": None, "uncertain_items": None}
    )
    assert tolerant_output.aliases == []
    assert tolerant_output.relations == []
    assert tolerant_output.uncertain_items == []


def test_alias_relation_schema_keeps_kinds_nullable_for_legacy_outputs() -> None:
    alias = ExtractedAlias(
        entity_ref="entity-001",
        alias="青姐",
        alias_type="昵称",
        identity_scope="durable",
        identity_basis="正文明确指向",
        evidence_quotes=["人们都叫她青姐"],
        confidence=0.9,
    )
    relation = Phase2bRelationObservation(
        source_ref="entity-001",
        target_ref="entity-002",
        relation_type="ally_of",
        persistence_scope="enduring",
        directionality="symmetric",
        claim_status="established",
        description="双方结盟",
        basis="正文明确结盟",
        evidence_quotes=["两人结为盟友"],
        confidence=0.9,
    )

    assert alias.alias_kind is None
    assert relation.relation_kind is None


@pytest.mark.parametrize("alias_type", ["", "超" * 21])
def test_alias_relation_schema_rejects_invalid_custom_alias_type(
    alias_type: str,
) -> None:
    with pytest.raises(ValidationError):
        ExtractedAlias(
            entity_ref="entity-001",
            alias="青姐",
            alias_kind="name",
            alias_type=alias_type,
            identity_scope="durable",
            identity_basis="正文明确指向",
            evidence_quotes=["人们都叫她青姐"],
            confidence=0.9,
        )


def test_alias_relation_schema_rejects_unknown_minimal_kinds() -> None:
    with pytest.raises(ValidationError):
        ExtractedAlias(
            entity_ref="entity-001",
            alias="青姐",
            alias_kind="semantic_variant",  # type: ignore[arg-type]
            alias_type="昵称",
            identity_scope="durable",
            identity_basis="正文明确指向",
            evidence_quotes=["人们都叫她青姐"],
            confidence=0.9,
        )
    with pytest.raises(ValidationError):
        Phase2bRelationObservation(
            source_ref="entity-001",
            target_ref="entity-002",
            relation_kind="neutral",  # type: ignore[arg-type]
            relation_type="ally_of",
            persistence_scope="enduring",
            directionality="symmetric",
            claim_status="established",
            description="双方结盟",
            basis="正文明确结盟",
            evidence_quotes=["两人结为盟友"],
            confidence=0.9,
        )


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


@pytest_asyncio.fixture
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
        aliases=["变量", "variable", "周明瑞"],
        confidence=0.77,
    )

    with patch(
        "modules.world.facade.find_similar_entities",
        autospec=True,
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
        patch.object(svc, "_call_llm_extraction", autospec=True) as llm_call,
        patch(
            "modules.world.facade.find_similar_entities",
            autospec=True,
            return_value={},
        ),
        patch("modules.memory.facade.replace_scene_memory_events", autospec=True),
        patch("modules.memory.facade.ensure_scene_checkpoints", autospec=True),
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
    assert result["input_fingerprint"] == scene_input_fingerprint(
        scene,
        llm_call.await_args.args[0],
    )
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
        autospec=True,
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

    from modules.evidence.compilation.models import ContextSnapshot

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


@pytest.mark.asyncio
async def test_phase2b_v2_snapshot_stores_full_prompt_payload_and_audit_sources(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    from modules.imports.entity_extraction.scene_entity_phase2b_context import (
        render_phase2b_user_payload,
    )
    from modules.imports.entity_extraction.scene_entity_snapshots import (
        create_phase2b_snapshot,
    )

    class _SnapshotServiceStub:
        @staticmethod
        def _scene_context_header(_scene: dict) -> str:
            return "unused"

        @staticmethod
        def _scene_id(scene: dict) -> str:
            return str(scene["id"])

        @staticmethod
        def _scene_source_chapter_index(_scene: dict) -> int:
            return 1

    scene = {
        "id": "scene-phase2b-v2",
        "novel_id": novel_with_drafts,
        "scene_index": 13,
    }
    full_text = "全文起点" + ("正文" * 3_000) + "全文终点"
    bundle = {
        "prompt_contract_version": "alias-relation-extraction-v4",
        "context_fingerprint": "context-fingerprint",
        "identity_candidates": [
            {"prompt_ref": "entity-001", "name": "克莱恩", "aliases": []}
        ],
        "relation_candidates": [],
        "_current_scene_sources": [
            {"type": "source_range", "id": "draft-range-1", "content_hash": "h1"}
        ],
        "_included_sources": [{"type": "world_entity", "id": "private-entity-id"}],
        "_omitted_sources": [{"type": "world_entity", "id": "omitted-entity-id"}],
        "_entity_ref_map": {"entity-001": "private-entity-id"},
    }

    await create_phase2b_snapshot(
        _SnapshotServiceStub(),
        db_session,
        novel_with_drafts,
        scene,
        full_text,
        "",
        workflow_id="wf-phase2b-v2",
        context_bundle=bundle,
    )

    from modules.evidence.compilation.models import ContextSnapshot

    raw_result = await db_session.execute(select(ContextSnapshot))
    raw_snapshot = raw_result.scalar_one()
    assert "全文终点" in raw_snapshot.rendered_context
    assert "entity-001" in raw_snapshot.rendered_context
    assert "private-entity-id" not in raw_snapshot.rendered_context
    assert raw_snapshot.rendered_context == render_phase2b_user_payload(
        bundle,
        full_text,
    )
    assert raw_snapshot.included_asset_ids == {"world_entity": ["private-entity-id"]}
    assert raw_snapshot.excluded_asset_ids == {"world_entity": ["omitted-entity-id"]}
    assert raw_snapshot.context_summary["source_ref_count"] == 1


@pytest.mark.asyncio
async def test_phase2_snapshot_profile_matches_active_project_client_summary(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    from infrastructure.llm.profiles import resolve_llm_profile
    from modules.imports.entity_extraction.scene_entity_config import (
        phase2_project_settings_context,
    )
    from modules.imports.entity_extraction.scene_entity_snapshots import (
        create_phase2_snapshot,
    )

    project_settings = {
        "llm": {
            "provider_id": "openai-compatible",
            "label": "Project fixture",
            "api_key": "snapshot-secret-must-not-appear",
            "base_url": "https://project-profile.example.test/v1?token=secret",
            "model": "project-model",
            "timeout": 77,
            "max_tokens": 9000,
        }
    }
    expected = resolve_llm_profile(project_settings).sanitized_summary()
    expected.update(
        {
            "profile_model": "project-model",
            "request_model": "project-model",
        }
    )
    scene = {
        "id": "scene-profile-summary",
        "novel_id": novel_with_drafts,
        "scene_index": 3,
        "chapter_ids": ["1"],
    }

    with phase2_project_settings_context(project_settings):
        snapshot = await create_phase2_snapshot(
            object(),
            db_session,
            novel_with_drafts,
            scene,
            1,
            "第 1 章正文",
            "已有对象",
            "前序记忆",
            [],
            workflow_id="wf-profile-summary",
        )

    from modules.evidence.compilation.models import ContextSnapshot

    raw_result = await db_session.execute(
        select(ContextSnapshot).where(ContextSnapshot.id == snapshot.id)
    )
    stored = raw_result.scalar_one()
    assert stored.model == "project-model"
    assert stored.token_metadata["max_tokens"] == 32_768
    assert stored.compile_options["llm_runtime"] == expected
    assert "snapshot-secret-must-not-appear" not in str(stored.compile_options)
    assert stored.compile_options["llm_runtime"]["base_url_host"] == (
        "project-profile.example.test"
    )


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
            autospec=True,
            return_value=extraction,
        ),
        patch.object(
            svc,
            "_persist_entities",
            autospec=True,
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
    from modules.world.facade import create_entity

    canonical_target = await create_entity(
        db_session,
        novel_with_drafts,
        {
            "name": "林岚",
            "entity_type": "character",
            "status": "canonical",
            "created_by": "user",
        },
    )
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
        autospec=True,
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
    assert alias_meta.get("suggested_existing_entity_id") == canonical_target["id"]


@pytest.mark.asyncio
async def test_persist_entities_does_not_target_pending_entity_as_existing(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    pending = ExtractedEntity(
        name="黑荆棘安保公司",
        entity_type="faction",
        suggested_action="link_to_existing",
        suggested_existing_entity_name="黑荆棘安保公司",
    )

    created = await svc._persist_entities(
        db_session,
        novel_with_drafts,
        [pending],
        scene_index=20,
        source_chapter_index=26,
        workflow_id="wf-pending-target",
    )

    assert created == 1
    from sqlalchemy import select

    from modules.world.models import CoreEntity

    result = await db_session.execute(
        select(CoreEntity).where(CoreEntity.name == "黑荆棘安保公司")
    )
    stored = result.scalar_one()
    meta = (stored.content_json or {}).get("_meta", {})
    assert stored.status == "candidate"
    assert meta.get("suggested_existing_entity_name") == "黑荆棘安保公司"
    assert meta.get("suggested_existing_entity_id") is None


@pytest.mark.asyncio
async def test_persist_entities_reuses_exact_working_identity_across_workflows(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    from sqlalchemy import func, select

    from modules.world.facade import create_entity
    from modules.world.models import CoreEntity
    from shared.utils import parse_uuid

    existing = await create_entity(
        db_session,
        novel_with_drafts,
        {
            "name": "塔罗占卜",
            "entity_type": "rule",
            "status": "candidate",
            "created_by": "ai_import",
            "content_json": {
                "_meta": {
                    "source": "deep_import",
                    "workflow_id": "wf-cancelled",
                    "auto_ingested": True,
                }
            },
        },
    )
    extracted = ExtractedEntity(
        name="塔罗占卜",
        entity_type="rule",
        suggested_action="link_to_existing",
        suggested_existing_entity_name="塔罗占卜",
        evidence_quotes=["她摆出了塔罗牌。"],
    )
    stats = svc._empty_phase2_persistence_stats()
    result_refs: list[dict[str, str]] = []

    with patch.object(svc, "_record_quote_evidence", autospec=True) as evidence:
        created = await svc._persist_entities(
            db_session,
            novel_with_drafts,
            [extracted],
            scene_index=2,
            source_chapter_index=4,
            workflow_id="wf-rerun",
            scene_id="scene-2",
            persistence_stats=stats,
            result_refs=result_refs,
        )

    count = await db_session.scalar(
        select(func.count(CoreEntity.id)).where(
            CoreEntity.novel_id == parse_uuid(novel_with_drafts, "novel_id"),
            CoreEntity.name == "塔罗占卜",
            CoreEntity.entity_type == "rule",
        )
    )
    assert created == 0
    assert count == 1
    assert result_refs == [{"type": "core_entity", "id": existing["id"]}]
    assert stats["dedup_counts"]["skipped"] == 1
    evidence.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_entities_reuses_exact_working_identity_even_when_model_says_new(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    from sqlalchemy import func, select

    from modules.world.facade import create_entity
    from modules.world.models import CoreEntity
    from shared.utils import parse_uuid

    existing = await create_entity(
        db_session,
        novel_with_drafts,
        {
            "name": "黑色郁金香号",
            "entity_type": "item",
            "status": "candidate",
            "created_by": "ai_import",
        },
    )
    extracted = ExtractedEntity(
        name="黑色郁金香号",
        entity_type="item",
        suggested_action="create_new",
        evidence_quotes=["黑色郁金香号驶入港口。"],
    )
    stats = svc._empty_phase2_persistence_stats()
    result_refs: list[dict[str, str]] = []

    with patch.object(svc, "_record_quote_evidence", autospec=True) as evidence:
        created = await svc._persist_entities(
            db_session,
            novel_with_drafts,
            [extracted],
            scene_index=3,
            source_chapter_index=5,
            workflow_id="wf-rerun-new-action",
            scene_id="scene-3",
            persistence_stats=stats,
            result_refs=result_refs,
        )

    count = await db_session.scalar(
        select(func.count(CoreEntity.id)).where(
            CoreEntity.novel_id == parse_uuid(novel_with_drafts, "novel_id"),
            CoreEntity.name == "黑色郁金香号",
            CoreEntity.entity_type == "item",
        )
    )
    assert created == 0
    assert count == 1
    assert result_refs == [{"type": "core_entity", "id": existing["id"]}]
    assert stats["action_counts"]["create_new"] == 1
    assert stats["dedup_counts"]["skipped"] == 1
    evidence.assert_awaited_once()


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
            "modules.world.facade.find_working_entity_id_by_name",
            autospec=True,
            return_value=None,
        ),
        patch(
            "modules.world.facade.find_similar_entities",
            autospec=True,
            return_value={},
        ),
        patch(
            "modules.world.facade.create_entity",
            autospec=True,
            return_value={"id": "entity-1"},
        ) as create_entity,
        patch(
            "modules.imports.entity_extraction.scene_entity_extraction."
            "SceneEntityExtractionService._record_quote_evidence",
            autospec=True,
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
            autospec=True,
            return_value={},
        ),
        patch(
            "modules.world.facade.create_entity",
            side_effect=create_entity_with_one_db_failure,
            autospec=True,
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
            autospec=True,
            return_value={"克莱恩": "entity-1", "梅丽莎": "entity-2"},
        ) as mock_batch_resolve,
        patch(
            "modules.world.facade.find_working_entity_id_by_name",
            autospec=True,
            side_effect=AssertionError("relations should batch entity name resolution"),
        ) as mock_single_resolve,
        patch(
            "modules.world.facade.create_or_merge_relation",
            autospec=True,
            return_value={"action": "created", "relation": Mock(id="relation-1")},
        ),
        patch(
            "modules.imports.entity_extraction.scene_entity_extraction."
            "SceneEntityExtractionService._record_quote_evidence",
            autospec=True,
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
            autospec=True,
            return_value={"克莱恩": "entity-1", "梅丽莎": "entity-2"},
        ),
        patch(
            "modules.world.facade.create_or_merge_relation",
            autospec=True,
            return_value={"action": "merged", "relation": Mock(id="relation-1")},
        ),
        patch(
            "modules.imports.entity_extraction.scene_entity_extraction."
            "SceneEntityExtractionService._record_quote_evidence",
            autospec=True,
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
            autospec=True,
            return_value=extraction,
        ),
        patch("modules.memory.facade.replace_scene_memory_events", autospec=True),
        patch("modules.memory.facade.ensure_scene_checkpoints", autospec=True),
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
                entity_ref="entity-001",
                alias="变量",
                alias_type="name",
                identity_scope="durable",
                identity_basis="模型误判",
                evidence_quotes=["模型误把字段占位词当成别名。"],
                confidence=0.99,
            ),
            ExtractedAlias(
                entity_ref="entity-001",
                alias="周明瑞",
                alias_type="name",
                identity_scope="durable",
                identity_basis="正文明确说明身份",
                evidence_quotes=["周明瑞醒来时发现自己成了克莱恩。"],
                confidence=0.91,
            ),
        ],
        relations=[
            Phase2bRelationObservation(
                source_ref="entity-001",
                target_ref="entity-002",
                relation_type="sibling",
                persistence_scope="enduring",
                directionality="symmetric",
                claim_status="established",
                description="兄妹",
                strength=0.8,
                basis="正文称二人为兄妹",
                evidence_quotes=["克莱恩与梅丽莎是兄妹。"],
                confidence=0.9,
            )
        ],
    )
    scene_text = (
        "模型误把字段占位词当成别名。"
        "周明瑞醒来时发现自己成了克莱恩。"
        "克莱恩与梅丽莎是兄妹。"
    )
    context_bundle = {
        "identity_candidates": [
            {"prompt_ref": "entity-001", "name": "克莱恩", "aliases": []},
            {"prompt_ref": "entity-002", "name": "梅丽莎", "aliases": []},
        ],
        "_entity_ref_map": {
            "entity-001": source["id"],
            "entity-002": target["id"],
        },
        "_relation_ref_map": {},
        "context_fingerprint": "fingerprint",
    }

    result = await svc._persist_alias_relation_output(
        db_session,
        novel_with_drafts,
        output,
        scene_index=3,
        workflow_id="wf-phase2b",
        scene_id="scene-3",
        context_bundle=context_bundle,
        current_scene_text=scene_text,
    )

    assert result["aliases"] == 1
    assert result["relations"] == 1
    assert result["uncertain_count"] == 1
    rels, total = await get_entity_relations(db_session, novel_with_drafts)
    assert total == 1
    assert [rels[0].source_id, rels[0].target_id] == sorted([source["id"], target["id"]])
    assert rels[0].status == "candidate"

    from sqlalchemy import select

    from modules.world.models import CoreEntity
    from shared.utils import parse_uuid

    stmt = select(CoreEntity).where(
        CoreEntity.id == parse_uuid(source["id"], "entity_id")
    )
    entity = (await db_session.execute(stmt)).scalar_one()
    aliases = (entity.content_json or {}).get("aliases", [])
    assert len(aliases) == 1
    assert aliases[0]["alias"] == "周明瑞"
    assert aliases[0]["status"] == "candidate"
    assert aliases[0]["review_meta"]["identity_scope"] == "durable"
    assert aliases[0]["review_meta"]["identity_basis"] == "正文明确说明身份"

    from modules.evidence.compilation.models import EvidenceLink

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
    assert {item.provenance["review_reason"] for item in evidence} == {"invalid_scene_id"}


@pytest.mark.asyncio
async def test_phase2b_persistence_uses_frozen_refs_and_validates_novel_scope() -> None:
    svc = SceneEntityExtractionService()
    output = AliasRelationExtractionOutput(
        aliases=[
            ExtractedAlias(
                entity_ref="entity-001",
                alias="周明瑞",
                identity_scope="durable",
                identity_basis="正文明确说明身份",
                evidence_quotes=["周明瑞就是克莱恩"],
                confidence=0.91,
            ),
        ],
        relations=[
            Phase2bRelationObservation(
                source_ref="entity-001",
                target_ref="entity-002",
                relation_type="sibling",
                persistence_scope="enduring",
                directionality="directed",
                claim_status="established",
                description="兄妹",
                basis="正文关系说明",
                evidence_quotes=["克莱恩照顾妹妹梅丽莎"],
                confidence=0.9,
            )
        ],
    )
    relation = Mock(id="relation-1")

    with (
        patch(
            "modules.world.facade.list_entities",
            autospec=True,
            return_value=[{"id": "entity-1"}, {"id": "entity-2"}],
        ) as mock_scope_entities,
        patch(
            "modules.world.facade.append_candidate_alias",
            autospec=True,
            return_value=True,
        ),
        patch(
            "modules.world.facade.create_or_merge_relation",
            autospec=True,
            return_value={"action": "created", "relation": relation},
        ),
        patch(
            "modules.imports.entity_extraction.scene_entity_extraction."
            "SceneEntityExtractionService._record_quote_evidence",
            autospec=True,
        ),
    ):
        result = await svc._persist_alias_relation_output(
            _FakeNestedDb(),
            "novel-1",
            output,
            scene_index=3,
            workflow_id="wf-phase2b",
            scene_id="scene-3",
            current_scene_text=("周明瑞就是克莱恩。克莱恩照顾妹妹梅丽莎。"),
            context_bundle={
                "identity_candidates": [
                    {"prompt_ref": "entity-001", "name": "克莱恩", "aliases": []},
                    {"prompt_ref": "entity-002", "name": "梅丽莎", "aliases": []},
                ],
                "_entity_ref_map": {
                    "entity-001": "entity-1",
                    "entity-002": "entity-2",
                },
                "_relation_ref_map": {},
            },
        )

    assert result["aliases"] == 1
    assert result["relations"] == 1
    assert result["uncertain_count"] == 0
    mock_scope_entities.assert_awaited_once()


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
    other_entity = await create_entity(
        db_session,
        str(other_project.id),
        {"name": "跨项目对象", "entity_type": "character", "status": "candidate"},
    )
    output = AliasRelationExtractionOutput(
        aliases=[
            ExtractedAlias(
                entity_ref="entity-001",
                alias="周明瑞",
                identity_scope="durable",
                identity_basis="正文明确说明身份",
                evidence_quotes=["周明瑞就是克莱恩"],
                confidence=0.8,
            ),
            ExtractedAlias(
                entity_ref="entity-001",
                alias=" 周明瑞 ",
                identity_scope="durable",
                identity_basis="正文重复说明身份",
                evidence_quotes=["周明瑞就是克莱恩"],
                confidence=0.7,
            ),
            ExtractedAlias(
                entity_ref="entity-002",
                alias="不应写入",
                identity_scope="durable",
                identity_basis="恶意跨项目引用",
                evidence_quotes=["跨项目对象又叫不应写入"],
                confidence=0.9,
            ),
        ],
        relations=[],
    )
    context_bundle = {
        "identity_candidates": [
            {"prompt_ref": "entity-001", "name": "克莱恩", "aliases": []},
            {"prompt_ref": "entity-002", "name": "跨项目对象", "aliases": []},
        ],
        "_entity_ref_map": {
            "entity-001": entity["id"],
            "entity-002": other_entity["id"],
        },
        "_relation_ref_map": {},
    }
    scene_text = "周明瑞就是克莱恩。跨项目对象又叫不应写入。"

    first = await svc._persist_alias_relation_output(
        db_session,
        novel_with_drafts,
        output,
        scene_index=3,
        workflow_id="wf-phase2b",
        scene_id="scene-3",
        context_bundle=context_bundle,
        current_scene_text=scene_text,
    )
    second = await svc._persist_alias_relation_output(
        db_session,
        novel_with_drafts,
        output,
        scene_index=3,
        workflow_id="wf-phase2b",
        scene_id="scene-3",
        context_bundle=context_bundle,
        current_scene_text=scene_text,
    )

    assert first["aliases"] == 1
    assert first["relations"] == 0
    assert first["uncertain_count"] == 1
    assert second["aliases"] == 0
    assert second["relations"] == 0
    assert second["uncertain_count"] == 1

    from sqlalchemy import select

    from modules.world.models import CoreEntity
    from shared.utils import parse_uuid

    stmt = select(CoreEntity).where(
        CoreEntity.id == parse_uuid(entity["id"], "entity_id")
    )
    found = (await db_session.execute(stmt)).scalar_one()
    aliases = (found.content_json or {}).get("aliases", [])
    assert [a.get("alias") for a in aliases] == ["周明瑞"]
