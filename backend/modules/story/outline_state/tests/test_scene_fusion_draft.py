from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest import mock

import pytest
from pydantic import ValidationError

from modules.story.outline_state.models import SceneSpan
from modules.story.outline_state.repositories import SceneRepository
from modules.story.outline_state.scene_draft_review import mapping_scope_warnings
from modules.story.outline_state.scene_fusion_draft import (
    SceneFusionDraftGenerator,
    SceneFusionEvidence,
    SceneFusionEvidenceLoader,
    SceneFusionEvidenceResult,
    SceneFusionGenerationResult,
    SceneFusionSemanticOutput,
    _prompt_payload,
)
from modules.story.outline_state.scene_workbench import SceneWorkbenchService
from modules.story.outline_state.schemas import (
    SceneCreate,
    SceneFusionPreviewRequest,
    SceneFusionSaveRequest,
    SceneMergeRequest,
)
from modules.writing.facade import create_draft_only, create_published_draft_only


class _FakeEvidenceLoader:
    async def load(self, _db, *, novel_id, scenes):
        assert novel_id
        return SceneFusionEvidenceResult(
            items=[
                SceneFusionEvidence(
                    scene_id=str(scene.id),
                    content_mode="working",
                    text=f"正文:{scene.title}",
                )
                for scene in scenes
            ]
        )


class _FakeLLMClient:
    model_name = "test-model"

    def __init__(self, payload=None, exc: Exception | None = None) -> None:
        self.payload = payload
        self.exc = exc
        self.request = None

    async def generate_structured(self, request, schema, **_kwargs):
        self.request = request
        if self.exc is not None:
            raise self.exc
        return schema.model_validate(self.payload)


class _SequentialFakeLLMClient(_FakeLLMClient):
    def __init__(self, payloads: list[dict]) -> None:
        super().__init__()
        self.payloads = list(payloads)
        self.requests = []

    async def generate_structured(self, request, schema, **_kwargs):
        self.requests.append(request)
        return schema.model_validate(self.payloads.pop(0))


async def _create_scene(db, novel_id: str, *, index: int, title: str):
    return await SceneRepository().create(
        db,
        uuid.UUID(novel_id),
        SceneCreate(
            scene_index=index,
            title=title,
            goal=f"目标:{title}",
            chapter_ids=[str(index + 1)],
            status="draft",
        ),
    )


@pytest.mark.asyncio
async def test_generator_uses_structured_project_client_and_manuscript(
    db_session,
    test_project_id,
) -> None:
    first = await _create_scene(db_session, test_project_id, index=0, title="潜入")
    second = await _create_scene(db_session, test_project_id, index=1, title="撤离")
    client = _FakeLLMClient(
        {
            "title": "潜入与撤离",
            "goal": "取得密信后脱身",
            "core_conflict": None,
            "core_conflict_status": "not_applicable",
            "confidence": 0.86,
            "basis": "两个 Scene 共享同一连续目标。",
        }
    )
    generator = SceneFusionDraftGenerator(
        llm_client=client,
        evidence_loader=_FakeEvidenceLoader(),  # type: ignore[arg-type]
    )

    result = await generator.generate(
        db_session,
        novel_id=test_project_id,
        sources=[first, second],
        primary_scene_id=str(first.id),
        deterministic_draft={"title": "规则标题"},
    )

    assert result.semantic_fields["title"] == "潜入与撤离"
    assert result.semantic_fields["goal"] == "取得密信后脱身"
    assert result.semantic_fields["core_conflict"] is None
    assert result.semantic_meta["core_conflict_status"] == "not_applicable"
    assert result.confidence == 0.86
    assert result.degraded is False
    assert client.request.temperature == 0.2
    assert client.request.max_tokens is None
    assert client.request.response_format == {"type": "json_object"}
    system_prompt = client.request.messages[0].content
    assert "公平考虑每个 Scene" in system_prompt
    assert "primary Scene 只在多个" in system_prompt
    assert "全部选中 Scene 的正文映射都会被保留" in system_prompt
    assert "must_happen 与 must_not_happen 受原 Scene" in system_prompt
    assert "以主 Scene 为骨架" not in system_prompt
    prompt = client.request.messages[1].content
    assert "正文:潜入" in prompt
    assert '"role": "primary"' in prompt
    assert "narrative_function" in prompt
    assert "不得输出数组" in prompt
    assert "不可信资料" in prompt
    assert "pov_character_id" in prompt


@pytest.mark.asyncio
async def test_generator_uses_confirmed_context_instead_of_unconfirmed_overlay(
    db_session,
    test_project_id,
) -> None:
    first = await _create_scene(db_session, test_project_id, index=0, title="潜入")
    second = await _create_scene(db_session, test_project_id, index=1, title="撤离")
    client = _FakeLLMClient(
        {
            "title": "融合",
            "goal": "完成任务",
            "core_conflict": None,
            "core_conflict_status": "not_applicable",
            "confidence": 0.8,
            "basis": "依据已确认资料。",
        }
    )
    confirmed = SimpleNamespace(
        confirmation=SimpleNamespace(context_fingerprint="f" * 64),
        rendered_markdown="只使用作者确认后的 Context",
    )

    with mock.patch(
        "modules.story.outline_state.scene_fusion_draft._load_related_context",
        autospec=True,
    ) as load_related:
        await SceneFusionDraftGenerator(
            llm_client=client,
            evidence_loader=_FakeEvidenceLoader(),  # type: ignore[arg-type]
        ).generate(
            db_session,
            novel_id=test_project_id,
            sources=[first, second],
            primary_scene_id=str(first.id),
            deterministic_draft={"title": "规则标题"},
            confirmed_context=confirmed,
        )

    load_related.assert_not_awaited()
    prompt = client.request.messages[1].content
    assert "只使用作者确认后的 Context" in prompt
    assert "f" * 64 in prompt


def test_scene_fusion_requires_exact_pinned_scene_selection() -> None:
    first = str(uuid.uuid4())
    second = str(uuid.uuid4())
    confirmed = SimpleNamespace(
        compile_options={
            "pinned_refs": [
                {
                    "kind": "target",
                    "target_ref": {
                        "target_type": "outline_scene",
                        "target_id": scene_id,
                        "target_path": "",
                    },
                }
                for scene_id in (first, second)
            ]
        }
    )
    request = SceneFusionPreviewRequest(
        source_scene_ids=[first, second],
        primary_scene_id=first,
    )

    SceneWorkbenchService._require_confirmed_fusion_sources(confirmed, request)
    request.source_scene_ids = [first, str(uuid.uuid4())]
    with pytest.raises(ValueError, match="source selection changed"):
        SceneWorkbenchService._require_confirmed_fusion_sources(confirmed, request)


@pytest.mark.asyncio
async def test_generator_revises_primary_authority_claim_and_normalizes_text_lists(
    db_session,
    test_project_id,
) -> None:
    first = await _create_scene(db_session, test_project_id, index=0, title="甲")
    second = await _create_scene(db_session, test_project_id, index=1, title="乙")
    client = _SequentialFakeLLMClient(
        [
            {
                "title": "错误草稿",
                "goal": "错误目标",
                "core_conflict": None,
                "core_conflict_status": "not_applicable",
                "must_happen": ["保留甲", "保留乙"],
                "confidence": 0.8,
                "basis": "融合时以 primary scene 的结构骨架为准。",
            },
            {
                "title": "公平融合",
                "goal": "同时完成甲乙目标",
                "core_conflict": None,
                "core_conflict_status": "not_applicable",
                "must_happen": ["保留甲", "保留乙"],
                "confidence": 0.9,
                "basis": "两个 Scene 的证据共同决定结果；primary 偏好没有改变本次判断。",
            },
        ]
    )
    generator = SceneFusionDraftGenerator(
        llm_client=client,
        evidence_loader=_FakeEvidenceLoader(),  # type: ignore[arg-type]
    )

    result = await generator.generate(
        db_session,
        novel_id=test_project_id,
        sources=[first, second],
        primary_scene_id=str(first.id),
        deterministic_draft={"title": "规则标题"},
    )

    assert len(client.requests) == 2
    assert result.semantic_fields["title"] == "公平融合"
    assert result.semantic_fields["must_happen"] == "保留甲；保留乙"
    assert "不得只改 basis" in client.requests[1].messages[1].content


@pytest.mark.asyncio
async def test_generator_revises_stale_source_boundary_constraint(
    db_session,
    test_project_id,
) -> None:
    first = await _create_scene(db_session, test_project_id, index=0, title="准备")
    second = await _create_scene(db_session, test_project_id, index=1, title="聚会")
    client = _SequentialFakeLLMClient(
        [
            {
                "title": "准备与聚会",
                "goal": "完成聚会",
                "core_conflict": None,
                "core_conflict_status": "not_applicable",
                "must_happen": "进入灰雾并开始聚会。",
                "must_not_happen": (
                    "不能在此场景中进入灰雾或开始聚会；必须停留在即将开始的节点。"
                ),
                "confidence": 0.8,
                "basis": "准备与实施连续。",
            },
            {
                "title": "准备与聚会",
                "goal": "完成聚会",
                "core_conflict": None,
                "core_conflict_status": "not_applicable",
                "must_happen": "进入灰雾并开始聚会。",
                "must_not_happen": "不能省略准备阶段的安全判断。",
                "confidence": 0.9,
                "basis": "已按融合后的完整边界重写约束。",
            },
        ]
    )

    result = await SceneFusionDraftGenerator(
        llm_client=client,
        evidence_loader=_FakeEvidenceLoader(),  # type: ignore[arg-type]
    ).generate(
        db_session,
        novel_id=test_project_id,
        sources=[first, second],
        primary_scene_id=str(second.id),
        deterministic_draft={"title": "规则标题"},
    )

    assert len(client.requests) == 2
    assert result.semantic_fields["must_not_happen"] == ("不能省略准备阶段的安全判断。")
    assert "original_scene_boundary_constraint_not_reconciled" in (
        client.requests[1].messages[1].content
    )


def test_structured_output_joins_multi_clause_text_without_python_repr() -> None:
    output = SceneFusionSemanticOutput.model_validate(
        {
            "title": "融合 Scene",
            "goal": "完成融合",
            "core_conflict": None,
            "core_conflict_status": "not_applicable",
            "must_happen": ["第一项。", "第二项；"],
            "confidence": 0.8,
        }
    )

    assert output.must_happen == "第一项；第二项"


@pytest.mark.asyncio
async def test_generator_uses_and_releases_project_runtime_client(
    db_session,
    test_project_id,
    monkeypatch,
) -> None:
    first = await _create_scene(db_session, test_project_id, index=0, title="甲")
    second = await _create_scene(db_session, test_project_id, index=1, title="乙")
    client = _FakeLLMClient(
        {
            "title": "项目运行时草稿",
            "goal": "项目运行时目标",
            "core_conflict": None,
            "core_conflict_status": "not_applicable",
            "confidence": 0.8,
            "basis": "项目运行时已生效。",
        }
    )
    events: list[str] = []

    async def fake_build(db, novel_id):
        assert db is db_session
        assert novel_id == test_project_id
        return {"snapshot": True}

    async def fake_restore(db, novel_id, snapshot):
        assert db is db_session
        assert novel_id == test_project_id
        assert snapshot == {"snapshot": True}
        return {"llm": {"model": "test-model"}}

    def fake_create(settings, *, timeout_override=None, novel_id=None):
        assert settings == {"llm": {"model": "test-model"}}
        assert timeout_override == 1800
        assert novel_id == test_project_id
        events.append("opened")
        return client

    async def fake_close():
        events.append("closed")

    client.close = fake_close

    monkeypatch.setattr(
        "modules.project.facade.build_project_llm_execution_snapshot",
        fake_build,
    )
    monkeypatch.setattr(
        "modules.project.facade.restore_project_llm_execution_settings",
        fake_restore,
    )
    monkeypatch.setattr(
        "modules.project.facade.create_project_snapshot_llm_client",
        fake_create,
    )
    generator = SceneFusionDraftGenerator(
        evidence_loader=_FakeEvidenceLoader(),  # type: ignore[arg-type]
    )

    result = await generator.generate(
        db_session,
        novel_id=test_project_id,
        sources=[first, second],
        primary_scene_id=str(first.id),
        deterministic_draft={"title": "规则标题"},
    )

    assert result.semantic_fields["title"] == "项目运行时草稿"
    assert events == ["opened", "closed"]


@pytest.mark.asyncio
async def test_generator_degrades_without_exposing_provider_error(
    db_session,
    test_project_id,
    caplog,
) -> None:
    first = await _create_scene(db_session, test_project_id, index=0, title="甲")
    second = await _create_scene(db_session, test_project_id, index=1, title="乙")
    client = _FakeLLMClient(exc=RuntimeError("secret provider payload"))
    generator = SceneFusionDraftGenerator(
        llm_client=client,
        evidence_loader=_FakeEvidenceLoader(),  # type: ignore[arg-type]
    )

    result = await generator.generate(
        db_session,
        novel_id=test_project_id,
        sources=[first, second],
        primary_scene_id=str(first.id),
        deterministic_draft={"title": "确定性草稿", "status": "draft"},
    )

    assert result.semantic_fields == {"title": "确定性草稿"}
    assert result.confidence is None
    assert result.degraded is True
    assert result.warnings[-1] == ("AI 融合调用失败，已返回确定性融合草稿，请人工复核。")
    assert "secret provider payload" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_structured_output_rejects_system_owned_fields() -> None:
    with pytest.raises(ValidationError):
        SceneFusionSemanticOutput.model_validate(
            {
                "title": "伪造",
                "goal": "伪造目标",
                "confidence": 0.9,
                "basis": "伪造系统字段",
                "status": "canonical",
                "chapter_ids": ["999"],
            }
        )


@pytest.mark.asyncio
async def test_evidence_loader_prefers_working_then_falls_back_to_canonical(
    db_session,
    test_project_id,
) -> None:
    canonical_text = "已发布正文证据"
    working_text = "当前工作稿正文证据"
    canonical = await create_published_draft_only(
        db_session,
        test_project_id,
        1,
        content=canonical_text,
    )
    working = await create_draft_only(
        db_session,
        test_project_id,
        1,
        content=working_text,
    )
    scene = await _create_scene(db_session, test_project_id, index=0, title="证据 Scene")
    working_span = SceneSpan(
        novel_id=uuid.UUID(test_project_id),
        scene_id=scene.id,
        chapter_index=1,
        content_mode="working",
        source_draft_id=uuid.UUID(working.id or ""),
        source_content_hash=working.content_hash,
        start_offset=0,
        end_offset=len(working_text),
        part_no=0,
        mapping_status="exact",
        status="draft",
    )
    canonical_span = SceneSpan(
        novel_id=uuid.UUID(test_project_id),
        scene_id=scene.id,
        chapter_index=1,
        content_mode="canonical",
        source_draft_id=uuid.UUID(canonical.id or ""),
        source_content_hash=canonical.content_hash,
        start_offset=0,
        end_offset=len(canonical_text),
        part_no=0,
        mapping_status="exact",
        status="draft",
    )
    db_session.add_all([working_span, canonical_span])
    await db_session.flush()
    loader = SceneFusionEvidenceLoader()

    result = await loader.load(
        db_session,
        novel_id=test_project_id,
        scenes=[scene],
    )
    assert result.items[0].content_mode == "working"
    assert result.items[0].text == working_text

    await create_draft_only(
        db_session,
        test_project_id,
        1,
        content="更新后的当前工作稿",
    )
    fallback = await loader.load(
        db_session,
        novel_id=test_project_id,
        scenes=[scene],
    )
    assert fallback.items[0].content_mode == "canonical"
    assert fallback.items[0].text == canonical_text


def test_fusion_request_limits_source_scene_count() -> None:
    with pytest.raises(ValidationError):
        SceneFusionPreviewRequest(
            source_scene_ids=[str(uuid.uuid4()) for _ in range(21)],
            primary_scene_id=str(uuid.uuid4()),
        )


@pytest.mark.asyncio
async def test_prompt_payload_preserves_complete_scene_cards_and_manuscript(
    db_session,
    test_project_id,
) -> None:
    scenes = []
    evidence = []
    for index in range(20):
        scene = await SceneRepository().create(
            db_session,
            uuid.UUID(test_project_id),
            SceneCreate(
                scene_index=index,
                title=f"Scene {index}" + "甲" * 200,
                goal="乙" * 4000,
                core_conflict="丙" * 4000,
                chapter_ids=[str(index + 1)],
                status="draft",
            ),
        )
        scenes.append(scene)
        evidence.append(
            SceneFusionEvidence(
                scene_id=str(scene.id),
                content_mode="working",
                text="正文" * 2000,
            )
        )

    payload, trimmed = _prompt_payload(
        scenes,
        primary_scene_id=str(scenes[0].id),
        evidence=evidence,
    )

    assert len(json.dumps(payload, ensure_ascii=False)) > 31_000
    assert trimmed is False
    assert payload["scenes"][0]["goal"] == "乙" * 4000
    assert payload["scenes"][0]["manuscript"] == "正文" * 2000


@pytest.mark.asyncio
async def test_evidence_loader_ignores_imprecise_spans(
    db_session,
    test_project_id,
) -> None:
    text = "不应进入 prompt 的整章内容"
    draft = await create_draft_only(
        db_session,
        test_project_id,
        1,
        content=text,
    )
    scene = await _create_scene(db_session, test_project_id, index=0, title="仅章映射")
    db_session.add(
        SceneSpan(
            novel_id=uuid.UUID(test_project_id),
            scene_id=scene.id,
            chapter_index=1,
            content_mode="working",
            source_draft_id=uuid.UUID(draft.id or ""),
            source_content_hash=draft.content_hash,
            start_offset=0,
            end_offset=len(text),
            part_no=0,
            mapping_status="chapter_only",
            status="draft",
        )
    )
    await db_session.flush()

    result = await SceneFusionEvidenceLoader().load(
        db_session,
        novel_id=test_project_id,
        scenes=[scene],
    )

    assert result.items[0].text == ""
    assert "仅使用 Scene 卡字段" in result.warnings[0]


@pytest.mark.asyncio
async def test_workbench_applies_only_generated_semantics(
    db_session,
    test_project_id,
) -> None:
    first = await _create_scene(db_session, test_project_id, index=0, title="甲")
    second = await _create_scene(db_session, test_project_id, index=1, title="乙")
    generator = mock.AsyncMock()
    generator.generate.return_value = SceneFusionGenerationResult(
        semantic_fields={"title": "AI 融合标题", "goal": "AI 融合目标"},
        confidence=0.91,
        reason="语义连续",
    )
    service = SceneWorkbenchService(fusion_draft_generator=generator)

    preview = await service.preview_llm_fusion(
        db_session,
        test_project_id,
        SceneFusionPreviewRequest(
            source_scene_ids=[str(first.id), str(second.id)],
            primary_scene_id=str(first.id),
        ),
    )

    assert preview.draft_scene is not None
    assert preview.draft_scene.title == "AI 融合标题"
    assert preview.draft_scene.goal == "AI 融合目标"
    assert preview.draft_scene.chapter_ids == ["1", "2"]
    assert preview.draft_scene.status == "draft"
    assert preview.draft_scene.source == "manual_fusion"
    assert preview.draft_scene.structure_meta is not None
    assert (
        preview.draft_scene.structure_meta["fusion_strategy"] == "project_llm_structured"
    )
    assert preview.confidence == 0.91
    assert preview.reason == "语义连续"
    payload = generator.generate.await_args.kwargs["deterministic_draft"]
    assert payload["chapter_ids"] == ["1", "2"]
    assert json.loads(json.dumps(payload))["status"] == "draft"

    saved = await service.save_llm_fusion(
        db_session,
        test_project_id,
        SceneFusionSaveRequest(
            source_scene_ids=[str(first.id), str(second.id)],
            primary_scene_id=str(first.id),
            mode="keep_originals",
        ),
    )
    assert saved.fused_scene is not None
    assert (
        saved.fused_scene.structure_meta["fusion_strategy"] == "author_reviewed_preview"
    )


@pytest.mark.asyncio
async def test_workbench_warns_when_one_scene_mapping_strictly_contains_another(
    db_session,
    test_project_id,
) -> None:
    outer = await _create_scene(db_session, test_project_id, index=0, title="外层")
    inner = await _create_scene(db_session, test_project_id, index=1, title="内层")
    outer.chapter_ids = ["1", "2", "3"]
    inner.chapter_ids = ["2", "3"]
    generator = mock.AsyncMock()
    generator.generate.return_value = SceneFusionGenerationResult(
        semantic_fields={"title": "融合", "goal": "融合目标"},
        confidence=0.8,
        reason="综合证据",
    )
    service = SceneWorkbenchService(fusion_draft_generator=generator)

    preview = await service.preview_llm_fusion(
        db_session,
        test_project_id,
        SceneFusionPreviewRequest(
            source_scene_ids=[str(outer.id), str(inner.id)],
            primary_scene_id=str(inner.id),
        ),
    )

    assert any("严格包含" in warning for warning in preview.warnings)
    assert any("先拆分或替换" in warning for warning in preview.warnings)

    mechanical_preview = await service.preview_merge(
        db_session,
        test_project_id,
        SceneMergeRequest(
            target_scene_id=str(inner.id),
            source_scene_ids=[str(outer.id)],
        ),
    )
    assert any("严格包含" in warning for warning in mechanical_preview.warnings)
    assert any("先拆分或替换" in warning for warning in mechanical_preview.warnings)


@pytest.mark.asyncio
async def test_adjacent_same_chapter_chunks_are_not_reported_as_containment(
    db_session,
    test_project_id,
) -> None:
    preparation = await _create_scene(
        db_session,
        test_project_id,
        index=57,
        title="聚会准备",
    )
    meeting = await _create_scene(
        db_session,
        test_project_id,
        index=58,
        title="塔罗聚会",
    )
    preparation.chapter_ids = ["58"]
    preparation.scene_chunks = [
        {"chapter_index": 58, "start_offset": 0, "end_offset": 1982}
    ]
    meeting.chapter_ids = ["58", "59", "60"]
    meeting.scene_chunks = [
        {"chapter_index": 58, "start_offset": 1982, "end_offset": 3354},
        {"chapter_index": 59, "start_offset": 0, "end_offset": 3448},
    ]

    assert mapping_scope_warnings([preparation, meeting]) == []

    generator = mock.AsyncMock()
    generator.generate.return_value = SceneFusionGenerationResult(
        semantic_fields={"title": "准备与聚会", "goal": "完成塔罗聚会"},
        confidence=0.9,
        reason="准备与实施连续。",
    )
    preview = await SceneWorkbenchService(
        fusion_draft_generator=generator
    ).preview_llm_fusion(
        db_session,
        test_project_id,
        SceneFusionPreviewRequest(
            source_scene_ids=[str(preparation.id), str(meeting.id)],
            primary_scene_id=str(meeting.id),
        ),
    )

    assert preview.draft_scene is not None
    assert preview.draft_scene.scene_chunks == [
        {"chapter_index": 58, "start_offset": 0, "end_offset": 1982},
        {"chapter_index": 58, "start_offset": 1982, "end_offset": 3354},
        {"chapter_index": 59, "start_offset": 0, "end_offset": 3448},
    ]
    assert not any("严格包含" in warning for warning in preview.warnings)
