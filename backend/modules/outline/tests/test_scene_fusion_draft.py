from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from unittest import mock

import pytest
from pydantic import ValidationError

from modules.outline.models import SceneSpan
from modules.outline.repositories import SceneRepository
from modules.outline.scene_fusion_draft import (
    MANUSCRIPT_CHARACTER_BUDGET,
    MAX_PROMPT_PAYLOAD_CHARACTERS,
    TRUNCATION_MARKER,
    SceneFusionDraftGenerator,
    SceneFusionEvidence,
    SceneFusionEvidenceLoader,
    SceneFusionEvidenceResult,
    SceneFusionGenerationResult,
    SceneFusionSemanticOutput,
    _allocate_character_budget,
    _prompt_payload,
    _truncate_middle,
)
from modules.outline.scene_workbench import SceneWorkbenchService
from modules.outline.schemas import (
    SceneCreate,
    SceneFusionPreviewRequest,
    SceneFusionSaveRequest,
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
            "confidence": 0.86,
            "reason": "两个 Scene 共享同一连续目标。",
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

    assert result.semantic_fields == {
        "title": "潜入与撤离",
        "goal": "取得密信后脱身",
    }
    assert result.confidence == 0.86
    assert result.degraded is False
    assert client.request.temperature == 0.2
    assert client.request.max_tokens == 2500
    assert client.request.response_format == {"type": "json_object"}
    system_prompt = client.request.messages[0].content
    assert "公平考虑每个选中 Scene" in system_prompt
    assert "primary Scene 只是偏好信号，不是骨架" in system_prompt
    assert "以主 Scene 为骨架" not in system_prompt
    prompt = client.request.messages[1].content
    assert "正文:潜入" in prompt
    assert '"role": "primary"' in prompt
    assert "如何兼顾所有 Scene" in prompt
    assert "如何使用 primary 偏好做决定" in prompt
    assert "pov_character_id" not in prompt


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
            "confidence": 0.8,
            "reason": "项目运行时已生效。",
        }
    )
    events: list[str] = []

    @asynccontextmanager
    async def fake_open_project_llm_client(db, novel_id, *, timeout_override=None):
        assert db is db_session
        assert novel_id == test_project_id
        assert timeout_override == 90
        events.append("opened")
        try:
            yield client
        finally:
            events.append("closed")

    monkeypatch.setattr(
        "modules.project.facade.open_project_llm_client",
        fake_open_project_llm_client,
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
                "confidence": 0.9,
                "reason": "伪造系统字段",
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
async def test_prompt_payload_bounds_scene_cards_and_manuscript(
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

    assert len(json.dumps(payload, ensure_ascii=False)) <= (MAX_PROMPT_PAYLOAD_CHARACTERS)
    assert trimmed is True
    assert (
        sum(
            len(str(item.get(field) or ""))
            for item in payload["scenes"]
            for field in (
                "title",
                "goal",
                "core_conflict",
                "emotional_beat",
                "must_happen",
                "must_not_happen",
                "narrative_tag",
            )
        )
        <= 6000
    )


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


def test_character_budget_is_fair_and_middle_truncation_is_bounded() -> None:
    texts = ["a" * 30_000, "b" * 1_000, "c" * 30_000]
    allocations = _allocate_character_budget(texts, MANUSCRIPT_CHARACTER_BUDGET)

    assert allocations == [15_000, 1_000, 8_000]
    assert sum(allocations) == MANUSCRIPT_CHARACTER_BUDGET
    truncated = _truncate_middle(texts[0], allocations[0])
    assert len(truncated) == allocations[0]
    assert TRUNCATION_MARKER in truncated
    assert truncated.startswith("a") and truncated.endswith("a")


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
