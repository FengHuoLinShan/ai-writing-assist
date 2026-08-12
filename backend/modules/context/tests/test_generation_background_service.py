"""Focused tests for the deep generation-background module."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

from modules.context.services.compiled_context import (
    CompiledContext,
    ContextSection,
    Tier,
)
from modules.context.services.generation_background import (
    GenerationBackgroundRequest,
    GenerationBackgroundService,
)


class _CapturingSnapshotWriter:
    def __init__(self) -> None:
        self.request = None

    async def open_context_snapshot(self, _db, request):
        self.request = request
        return SimpleNamespace(id="snapshot-1")


class _ProvenanceCompiler:
    def __init__(self, compiled: CompiledContext) -> None:
        self.compiled = compiled
        self.options = None
        self.options_history = []

    async def compile_with_tiers(self, _db, options, budget_tokens=None):
        assert budget_tokens == 4000
        self.options = options
        self.options_history.append(options)
        options.world_synopsis_revision_id = "synopsis-revision-1"
        options.world_synopsis_source_hash = "source-hash-1"
        options.world_synopsis_block_hash = "block-hash-1"
        options.activation_profile_version = 3
        options.activation_profile_rule_hash = "rule-hash-1"
        options.activation_source_hashes = ["activation-source-1"]
        options.activation_included_target_hashes = ["activation-target-1"]
        return self.compiled


class _UnresolvedProfileCompiler:
    def __init__(self, compiled: CompiledContext) -> None:
        self.compiled = compiled

    async def compile_with_tiers(self, _db, _options, budget_tokens=None):
        assert budget_tokens == 4000
        return self.compiled


async def test_service_owns_compilation_usage_and_snapshot_provenance() -> None:
    compiled = CompiledContext(
        sections=[
            ContextSection(
                key="world_bible_working_pages",
                tier=Tier.P1,
                content="working",
                token_count=2,
                sources=[
                    {
                        "type": "world_bible_draft",
                        "id": "draft-actual",
                    }
                ],
            ),
            ContextSection(
                key="world_bible_activation",
                tier=Tier.P1,
                content="activation",
                token_count=3,
            ),
            ContextSection(
                key="world_bible_synopsis",
                tier=Tier.P1,
                content="synopsis",
                token_count=5,
                sources=[
                    {
                        "type": "world_bible_synopsis",
                        "id": "synopsis-revision-1",
                    }
                ],
                retrieval_metadata={
                    "revision_id": "synopsis-revision-1",
                    "source_hash": "source-hash-1",
                    "block_hash": "block-hash-1",
                },
            ),
        ],
        total_tokens=10,
        budget_tokens=4000,
        warnings=["one warning"],
        selection_trace={"world_entities": {"included": []}},
        activation_trace={"profile": {"version": 3}},
    )
    compiler = _ProvenanceCompiler(compiled)
    snapshots = _CapturingSnapshotWriter()
    service = GenerationBackgroundService(
        compiler=compiler,
        renderer=lambda _compiled: "<rendered>",
        snapshot_writer=snapshots,
    )

    result = await service.compile(
        object(),
        GenerationBackgroundRequest(
            novel_id="00000000-0000-0000-0000-00000000c101",
            task="生成世界设定",
            include_world_synopsis=True,
            selected_world_bible_draft_ids=("draft-requested",),
            activation_profile_id="profile-1",
            operation="world.generation.core_entity",
            prompt_name="world.generation.core_entity.structured",
            focus_text="  北境   商路  ",
            reference_chapter_index=7,
            scene_id="scene-1",
            thread_ids=("thread-1",),
            character_ids=("character-1",),
            entity_ids=("entity-1",),
            source_snapshot={"kind": "project"},
        ),
    )

    assert compiler.options is not None
    assert compiler.options.task == "生成世界设定：北境 商路"
    assert compiler.options.scope == "generation_center"
    assert compiler.options.retrieval_purpose == "world_generation"
    assert result["rendered_context"] == "<rendered>"
    assert set(result) == {"rendered_context", "context_usage"}
    assert result["context_usage"]["context_snapshot_id"] == "snapshot-1"
    assert result["context_usage"]["revision_id"] == "synopsis-revision-1"
    assert result["context_usage"]["token_count"] == 10

    request = snapshots.request
    assert request is not None
    assert request.compile_options["task"] == "生成世界设定"
    assert (
        request.compile_options["focus_hash"]
        == hashlib.sha256("北境 商路".encode()).hexdigest()
    )
    assert "北境 商路" not in str(request.compile_options)
    assert request.compile_options["source_snapshot"] == {"kind": "project"}
    assert request.included_asset_ids["world_bible_draft"] == ["draft-actual"]
    assert request.included_asset_ids["world_bible_synopsis_revision"] == [
        "synopsis-revision-1"
    ]
    assert request.included_asset_ids["activation_profile"] == ["profile-1"]
    assert request.included_asset_ids["activation_target_hash"] == ["activation-target-1"]
    assert request.context_summary["actual_included_asset_ids"] == (
        request.included_asset_ids
    )
    assert "context_snapshot_id" not in request.context_summary["synopsis"]
    result["context_usage"]["warnings"].append("late mutation")
    result["context_usage"]["activation_source_hashes"].append("late source")
    assert request.context_summary["synopsis"]["warnings"] == ["one warning"]
    assert request.context_summary["synopsis"]["activation_source_hashes"] == [
        "activation-source-1"
    ]


async def test_service_preserves_none_and_empty_context_selection_shapes() -> None:
    compiled = CompiledContext(sections=[], budget_tokens=4000)
    compiler = _ProvenanceCompiler(compiled)
    service = GenerationBackgroundService(
        compiler=compiler,
        renderer=lambda _compiled: "",
        snapshot_writer=_CapturingSnapshotWriter(),
    )

    await service.compile(
        object(),
        GenerationBackgroundRequest(
            novel_id="00000000-0000-0000-0000-00000000c105",
            task="保留未指定上下文形态",
        ),
    )
    await service.compile(
        object(),
        GenerationBackgroundRequest(
            novel_id="00000000-0000-0000-0000-00000000c106",
            task="保留显式空上下文形态",
            thread_ids=(),
            character_ids=(),
            entity_ids=(),
        ),
    )

    absent, explicit_empty = compiler.options_history
    assert absent.thread_ids is None
    assert absent.character_ids is None
    assert absent.entity_ids is None
    assert explicit_empty.thread_ids == []
    assert explicit_empty.character_ids == []
    assert explicit_empty.entity_ids == []


async def test_new_world_workflows_keep_generation_scope_and_provenance() -> None:
    compiler = _ProvenanceCompiler(CompiledContext(sections=[], budget_tokens=4000))
    service = GenerationBackgroundService(
        compiler=compiler,
        renderer=lambda _compiled: "",
        snapshot_writer=_CapturingSnapshotWriter(),
    )

    for operation in (
        "world.generation.exploration",
        "world.generation.semantic_inspection",
    ):
        await service.compile(
            object(),
            GenerationBackgroundRequest(
                novel_id="00000000-0000-0000-0000-00000000c109",
                task="世界设定流程",
                operation=operation,
            ),
        )

    assert [options.scope for options in compiler.options_history] == [
        "generation_center",
        "generation_center",
    ]
    assert [options.retrieval_purpose for options in compiler.options_history] == [
        "world_generation",
        "world_generation",
    ]


async def test_facade_preserves_none_and_empty_context_selection_shapes(
    monkeypatch,
) -> None:
    from modules.context import facade as context_facade

    captured = []

    async def capture(_db, request):
        captured.append(request)
        return {"rendered_context": "", "context_usage": {}}

    monkeypatch.setattr(
        context_facade._generation_background_service,
        "compile",
        capture,
    )

    await context_facade.compile_generation_background(
        object(),
        novel_id="00000000-0000-0000-0000-00000000c107",
        task="未指定上下文",
    )
    await context_facade.compile_generation_background(
        object(),
        novel_id="00000000-0000-0000-0000-00000000c108",
        task="显式空上下文",
        thread_ids=[],
        character_ids=[],
        entity_ids=[],
    )

    absent, explicit_empty = captured
    assert absent.thread_ids is None
    assert absent.character_ids is None
    assert absent.entity_ids is None
    assert explicit_empty.thread_ids == ()
    assert explicit_empty.character_ids == ()
    assert explicit_empty.entity_ids == ()


async def test_snapshot_does_not_claim_budget_evicted_content_as_included() -> None:
    compiled = CompiledContext(
        sections=[
            ContextSection(
                key="style_assets",
                tier=Tier.P3,
                content="project style",
                token_count=2,
                sources=[{"type": "project", "id": "project-1"}],
            )
        ],
        total_tokens=2,
        budget_tokens=4000,
        evicted_keys=[
            "world_bible_working_pages",
            "world_bible_activation",
            "world_bible_synopsis",
        ],
    )
    compiler = _ProvenanceCompiler(compiled)
    snapshots = _CapturingSnapshotWriter()
    service = GenerationBackgroundService(
        compiler=compiler,
        renderer=lambda _compiled: "project style",
        snapshot_writer=snapshots,
    )

    result = await service.compile(
        object(),
        GenerationBackgroundRequest(
            novel_id="00000000-0000-0000-0000-00000000c102",
            task="生成世界设定",
            include_world_synopsis=True,
            selected_world_bible_draft_ids=("draft-evicted",),
            activation_profile_id="profile-1",
        ),
    )

    request = snapshots.request
    assert request is not None
    assert request.included_asset_ids["world_bible_draft"] == []
    assert request.included_asset_ids["world_bible_synopsis_revision"] == []
    assert request.included_asset_ids["activation_target_hash"] == []
    assert request.included_asset_ids["activation_profile"] == ["profile-1"]
    assert request.included_asset_ids["project"] == ["project-1"]
    assert result["context_usage"]["revision_id"] is None


async def test_snapshot_does_not_claim_unresolved_profile_as_included() -> None:
    snapshots = _CapturingSnapshotWriter()
    service = GenerationBackgroundService(
        compiler=_UnresolvedProfileCompiler(
            CompiledContext(sections=[], budget_tokens=4000)
        ),
        renderer=lambda _compiled: "",
        snapshot_writer=snapshots,
    )

    await service.compile(
        object(),
        GenerationBackgroundRequest(
            novel_id="00000000-0000-0000-0000-00000000c109",
            task="生成世界设定",
            activation_profile_id="profile-unresolved",
            activation_profile_version=7,
        ),
    )

    assert snapshots.request is not None
    assert snapshots.request.compile_options["activation_profile_id"] == (
        "profile-unresolved"
    )
    assert snapshots.request.compile_options["activation_profile_version"] == 7
    assert snapshots.request.compile_options["activation_profile_rule_hash"] is None
    assert snapshots.request.included_asset_ids["activation_profile"] == []
    assert (
        snapshots.request.context_summary["actual_included_asset_ids"][
            "activation_profile"
        ]
        == []
    )


async def test_snapshot_does_not_claim_truncated_content_as_included() -> None:
    compiled = CompiledContext(
        sections=[
            ContextSection(
                key="world_bible_working_pages",
                tier=Tier.P1,
                content="<WORLD_BIBLE_WORKING_PAGES_DATA>",
                token_count=2,
                sources=[{"type": "world_bible_draft", "id": "draft-truncated"}],
                truncated_reason="超过预算后保留前段摘要",
            ),
            ContextSection(
                key="world_bible_activation",
                tier=Tier.P1,
                content="<WORLD_BIBLE_ACTIVATION_DATA>",
                token_count=2,
                sources=[{"type": "world_bible_page", "id": "page-truncated"}],
                truncated_reason="超过预算后保留前段摘要",
            ),
            ContextSection(
                key="world_bible_synopsis",
                tier=Tier.P1,
                content="<WORLD_BIBLE_SYNOPSIS_DATA>",
                token_count=2,
                sources=[
                    {
                        "type": "world_bible_synopsis",
                        "id": "synopsis-revision-1",
                    }
                ],
                truncated_reason="超过预算后保留前段摘要",
            ),
        ],
        total_tokens=6,
        budget_tokens=4000,
        truncated_keys=[
            "world_bible_working_pages",
            "world_bible_activation",
            "world_bible_synopsis",
        ],
    )
    snapshots = _CapturingSnapshotWriter()
    service = GenerationBackgroundService(
        compiler=_ProvenanceCompiler(compiled),
        renderer=lambda _compiled: "<truncated>",
        snapshot_writer=snapshots,
    )

    await service.compile(
        object(),
        GenerationBackgroundRequest(
            novel_id="00000000-0000-0000-0000-00000000c104",
            task="生成世界设定",
            include_world_synopsis=True,
            selected_world_bible_draft_ids=("draft-truncated",),
            activation_profile_id="profile-1",
        ),
    )

    assert snapshots.request is not None
    assert snapshots.request.included_asset_ids["world_bible_draft"] == []
    assert snapshots.request.included_asset_ids["world_bible_synopsis_revision"] == []
    assert snapshots.request.included_asset_ids["activation_target_hash"] == []
    assert snapshots.request.included_asset_ids.get("world_bible_page", []) == []
    assert snapshots.request.included_asset_ids["activation_profile"] == ["profile-1"]


async def test_snapshot_deduplicates_generic_final_section_sources() -> None:
    compiled = CompiledContext(
        sections=[
            ContextSection(
                key="world_bible_pages",
                tier=Tier.P1,
                content="page one",
                token_count=2,
                sources=[
                    {"type": "world_bible_page", "id": "page-1"},
                    {"type": "world_bible_page", "id": "page-1"},
                ],
            ),
            ContextSection(
                key="retrieval_evidence_packs",
                tier=Tier.P2,
                content="evidence",
                token_count=3,
                sources=[
                    {"type": "world_bible_page", "id": "page-1"},
                    {"type": "rag_chunk", "id": "chunk-1"},
                ],
            ),
        ],
        total_tokens=5,
        budget_tokens=4000,
    )
    snapshots = _CapturingSnapshotWriter()
    service = GenerationBackgroundService(
        compiler=_ProvenanceCompiler(compiled),
        renderer=lambda _compiled: "<rendered>",
        snapshot_writer=snapshots,
    )

    await service.compile(
        object(),
        GenerationBackgroundRequest(
            novel_id="00000000-0000-0000-0000-00000000c103",
            task="生成世界设定",
        ),
    )

    assert snapshots.request is not None
    assert snapshots.request.included_asset_ids["world_bible_page"] == ["page-1"]
    assert snapshots.request.included_asset_ids["rag_chunk"] == ["chunk-1"]
