from __future__ import annotations

from uuid import uuid4

import pytest

from modules.evidence.compilation.contracts import (
    CompileOptions,
    ConfirmedAIActionContext,
    StructureContextBundle,
)
from modules.evidence.compilation.facade import (
    freeze_director_reference_context,
    restore_director_reference_context,
)
from modules.evidence.compilation.knowledge.contracts import KnowledgeSubject
from modules.evidence.compilation.knowledge.policies import (
    ADOPTION_NONE,
    CAPABILITY_REGISTRY,
    CONFIRMATION_REQUIRED,
    DOMAIN_WRITING,
    OUTPUT_PROSE,
    SNAPSHOT_REQUIRED,
    CapabilityKnowledgePolicy,
)
from modules.evidence.compilation.knowledge.scope import build_scope_receipt
from modules.evidence.compilation.schemas import (
    ContextCompileRequest,
    ContextConfirmRequest,
)
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextItem,
    ContextSection,
    Tier,
)
from modules.evidence.compilation.services.confirmation_service import (
    ContextConfirmationService,
    _core_context_fingerprint,
)
from modules.evidence.compilation.services.director_reference_config import (
    DIRECTOR_REFERENCE_CAPABILITIES_ENV,
    enabled_director_reference_capabilities,
)
from modules.evidence.compilation.services.director_reference_sections import (
    DirectorReferenceSectionBuilder,
)
from modules.evidence.compilation.services.loaders.director_reference_loader import (
    DirectorReferenceLoader,
)
from modules.story.contracts import StoryDirectorReferencesForWritingContract


def _reference(reference_id: str | None = None) -> dict:
    reference_id = reference_id or str(uuid4())
    return {
        "reference_id": reference_id,
        "scene_id": str(uuid4()),
        "name": "雨夜门口",
        "content_copy": {
            "angle": {
                "label": "从林澈的视角",
                "viewpoint_kind": "character",
                "viewpoint_character_id": str(uuid4()),
                "narrative_distance": "close",
                "focus": "门外的脚步",
                "detail_and_pacing": "先写声响，再写反应",
                "material_ids": ["mat-visible"],
            },
            "materials": [
                {
                    "material_id": "mat-visible",
                    "category": "environment",
                    "content": "雨水打在窗沿上",
                    "perception_status": "known",
                    "perceiver_ids": ["pov-1"],
                    "senses": ["sound"],
                    "source_kind": "world_dossier",
                    "source_ids": ["revision-visible"],
                    "source_fingerprints": {"revision-visible": "a" * 64},
                    "conflict_status": "clear",
                },
                {
                    "material_id": "mat-hidden",
                    "category": "mood",
                    "content": "隔壁房间里有人藏着信",
                    "perception_status": "known",
                    "perceiver_ids": ["other-1"],
                    "senses": ["inner"],
                    "internal_character_id": "other-1",
                    "source_kind": "continuity",
                    "source_ids": ["checkpoint-hidden"],
                    "source_fingerprints": {"checkpoint-hidden": "b" * 64},
                    "conflict_status": "clear",
                },
                {
                    "material_id": "mat-candidate",
                    "category": "object",
                    "content": "门外可能多出一把伞",
                    "perception_status": "unknown",
                    "perceiver_ids": [],
                    "senses": ["sight"],
                    "candidate_only": True,
                    "source_kind": "candidate",
                    "source_ids": [],
                    "conflict_status": "unknown",
                },
            ],
            "performances": [
                {"character_id": "pov-1", "action": "侧身挡住门口"},
                {"character_id": "other-1", "action": "把信藏进袖中"},
            ],
        },
        "material_ids": ["mat-visible", "mat-hidden", "mat-candidate"],
        "angle": {},
        "annotation": "不要告诉主角信的来历",
        "source_round_id": str(uuid4()),
        "source_deleted": False,
        "source_basis_hash": "c" * 64,
        "source_changed": False,
        "current_basis_available": True,
        "warnings": [],
        "advisory_only": True,
        "adoption_status": "not_adopted",
    }


def test_director_reference_capability_is_default_off_and_allowlisted(monkeypatch):
    monkeypatch.delenv(DIRECTOR_REFERENCE_CAPABILITIES_ENV, raising=False)
    assert enabled_director_reference_capabilities() == frozenset()

    monkeypatch.setenv(
        DIRECTOR_REFERENCE_CAPABILITIES_ENV,
        "writing.generate, writing.targeted_revision",
    )
    assert enabled_director_reference_capabilities() == frozenset(
        {"writing.generate", "writing.targeted_revision"}
    )

    monkeypatch.setenv(DIRECTOR_REFERENCE_CAPABILITIES_ENV, "story.one_click.simulate")
    with pytest.raises(ValueError, match="unsupported capabilities"):
        enabled_director_reference_capabilities()


def test_director_references_only_compile_for_selected_writing_scene_actions():
    reference_id = str(uuid4())
    accepted = ContextCompileRequest(
        novel_id=str(uuid4()),
        task="写作",
        scope="chapter",
        action="writing.generate",
        scene_id=str(uuid4()),
        chapter_index=1,
        director_reference_ids=[reference_id],
    )
    assert accepted.director_reference_ids == [reference_id]

    with pytest.raises(ValueError, match="only available"):
        ContextCompileRequest(
            novel_id=str(uuid4()),
            task="模拟",
            scope="scene",
            action="story.one_click.simulate",
            scene_id=str(uuid4()),
            director_reference_ids=[reference_id],
        )
    with pytest.raises(ValueError, match="reader"):
        ContextConfirmRequest(
            novel_id=str(uuid4()),
            task="阅读",
            scope="chapter",
            action="writing.generate",
            chapter_index=1,
            scene_id=str(uuid4()),
            reveal_mode="reader",
            director_reference_ids=[reference_id],
        )


@pytest.mark.asyncio
async def test_reference_loader_is_default_off_and_pov_filters_hidden_copy(monkeypatch):
    monkeypatch.delenv(DIRECTOR_REFERENCE_CAPABILITIES_ENV, raising=False)
    reference = _reference()
    reference["content_copy"]["angle"]["viewpoint_character_id"] = "pov-1"
    scene_id = reference["scene_id"]
    read_calls = []

    async def read_references(_db, **kwargs):
        read_calls.append(kwargs)
        return StoryDirectorReferencesForWritingContract(
            items=[reference], omitted=[], warnings=[]
        )

    loader = DirectorReferenceLoader(reader=read_references)
    author_bundle = StructureContextBundle(
        novel_id=str(uuid4()), task="正文", scope="chapter"
    )
    options = CompileOptions(
        novel_id=author_bundle.novel_id,
        task="正文",
        scope="chapter",
        consumer_action="writing.generate",
        scene_id=scene_id,
        director_reference_ids=[reference["reference_id"]],
    )
    await loader.load(None, options, author_bundle)
    assert read_calls == []
    assert "未启用" in author_bundle.director_reference_brief["warnings"][0]

    monkeypatch.setenv(DIRECTOR_REFERENCE_CAPABILITIES_ENV, "writing.generate")
    character_bundle = StructureContextBundle(
        novel_id=author_bundle.novel_id, task="正文", scope="chapter"
    )
    role_options = options.__class__(
        **{
            **options.__dict__,
            "reveal_mode": "character",
            "viewpoint_character_id": "pov-1",
        }
    )
    await loader.load(None, role_options, character_bundle)
    assert len(read_calls) == 1
    projected = character_bundle.director_reference_brief["items"][0]
    copied = projected["content_copy"]
    assert [item["material_id"] for item in copied["materials"]] == ["mat-visible"]
    assert [item["character_id"] for item in copied["performances"]] == ["pov-1"]
    assert copied["angle"]["viewpoint_character_id"] == "pov-1"
    assert projected["annotation"] == ""


def test_reference_section_is_an_advisory_receipt_not_core_scope():
    reference = _reference()
    reference_id = reference["reference_id"]
    reference["content_copy"]["angle"]["viewpoint_character_id"] = "pov-1"
    bundle = StructureContextBundle(
        novel_id=str(uuid4()),
        task="正文",
        scope="chapter",
        director_reference_brief={"items": [reference], "omitted": [], "warnings": []},
    )
    section = DirectorReferenceSectionBuilder.build(bundle)[0]
    core = ContextSection(
        key="writing_objective",
        tier=Tier.P0,
        content="写正文",
        token_count=1,
        sources=[{"type": "task", "id": "objective"}],
    )
    omitted_item = ContextItem(
        key=f"director_reference:{reference_id}",
        content="",
        source={"type": "director_reference", "id": reference_id},
        selection_state="omitted",
        omission_reason="预算省略",
    )
    policy = CapabilityKnowledgePolicy(
        capability_id="test.director_reference",
        domain=DOMAIN_WRITING,
        title="test",
        subject_types=("author",),
        required_dimensions=(),
        advisory_dimensions=("director_reference",),
        confirmation_policy=CONFIRMATION_REQUIRED,
        snapshot_policy=SNAPSHOT_REQUIRED,
        output_permissions=(OUTPUT_PROSE,),
        adoption_gate=ADOPTION_NONE,
    )
    compiled = CompiledContext(
        sections=[core],
        omitted_items=[omitted_item],
    )
    receipt = build_scope_receipt(
        compiled,
        policy,
        KnowledgeSubject(subject_type="author"),
        novel_id=str(uuid4()),
    ).receipt
    assert receipt.scope_complete
    assert receipt.omitted == ()
    assert [(item.dimension, item.source_key) for item in receipt.advisory_omitted] == [
        ("director_reference", f"director_reference:{reference_id}")
    ]
    assert section.key == "director_reference"
    assert section.items[0].source["adoption_status"] == "not_adopted"


def test_confirmation_core_fingerprint_ignores_only_advisory_copy_changes():
    core = ContextSection(
        key="writing_objective",
        tier=Tier.P0,
        content="写作范围",
        token_count=2,
    )
    reference_a = ContextSection(
        key="director_reference",
        tier=Tier.P3,
        content="参考 A",
        token_count=2,
    )
    reference_b = reference_a.model_copy(update={"content": "参考 B"})
    compiled_a = CompiledContext(sections=[core, reference_a], total_tokens=4)
    compiled_b = CompiledContext(sections=[core, reference_b], total_tokens=4)
    assert _core_context_fingerprint(compiled_a) == _core_context_fingerprint(compiled_b)


def test_task_restores_the_confirmed_copy_and_warns_when_its_basis_changes():
    reference_id = str(uuid4())
    core = ContextSection(
        key="writing_objective",
        tier=Tier.P0,
        content="写作范围",
        token_count=2,
    )
    original_section = ContextSection(
        key="director_reference",
        tier=Tier.P3,
        content="确认时的表演素材",
        token_count=3,
        sources=[
            {
                "type": "director_reference",
                "id": reference_id,
                "label": "雨夜门口",
                "status": "saved_copy",
                "source_basis_hash": "a" * 64,
            }
        ],
        retrieval_metadata={"reference_ids": [reference_id]},
    )
    first = ConfirmedAIActionContext(
        confirmation=None,
        compiled=CompiledContext(sections=[core, original_section]),
        rendered_markdown="",
        compile_options={"director_reference_ids": [reference_id]},
        result_refs=[],
    )
    snapshot = freeze_director_reference_context(first)

    changed_section = original_section.model_copy(
        update={
            "content": "更新后的来源内容",
            "sources": [
                {
                    **original_section.sources[0],
                    "status": "source_changed",
                    "source_basis_hash": "b" * 64,
                }
            ],
        }
    )
    current = ConfirmedAIActionContext(
        confirmation=None,
        compiled=CompiledContext(sections=[core, changed_section]),
        rendered_markdown="",
        compile_options={"director_reference_ids": [reference_id]},
        result_refs=[],
    )
    usage = restore_director_reference_context(current, snapshot)
    restored = next(
        item for item in current.compiled.sections if item.key == "director_reference"
    )
    assert restored.content == "确认时的表演素材"
    assert usage["included_ids"] == [reference_id]
    assert any("来源依据已变化" in item for item in usage["warnings"])


def test_writing_policies_and_confirmation_store_the_advisory_dimension():
    assert (
        "director_reference"
        in CAPABILITY_REGISTRY["writing.generate"].advisory_dimensions
    )
    assert (
        "director_reference"
        in CAPABILITY_REGISTRY["writing.targeted_revision"].advisory_dimensions
    )
    assert (
        "director_reference"
        not in CAPABILITY_REGISTRY["writing.semantic_review"].advisory_dimensions
    )
    options = CompileOptions(
        novel_id=str(uuid4()),
        task="正文",
        scope="chapter",
        consumer_action="writing.generate",
        director_reference_ids=[str(uuid4())],
        scene_memory_contract_version=1,
    )
    saved = ContextConfirmationService._compile_options_json(options)
    assert saved["director_reference_ids"] == options.director_reference_ids
