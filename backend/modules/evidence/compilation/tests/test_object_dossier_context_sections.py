from types import SimpleNamespace

import pytest

from modules.evidence.compilation.contracts import CompileOptions, StructureContextBundle
from modules.evidence.compilation.services.context_compiler import ContextCompiler
from modules.evidence.compilation.services.loaders import object_dossier_loader
from modules.evidence.compilation.services.loaders.object_dossier_loader import (
    ObjectDossierLoader,
    enabled_object_reference_capabilities,
    object_dossier_capability,
)


def test_object_reference_switches_are_separate_and_default_off():
    assert enabled_object_reference_capabilities(SimpleNamespace()) == (set(), set())
    assert enabled_object_reference_capabilities(
        SimpleNamespace(
            object_dossier_enabled_capabilities=("writing.generate",),
            character_pattern_enabled_capabilities=("story.character_card",),
        )
    ) == ({"writing.generate"}, {"story.character_card"})
    assert (
        object_dossier_capability("story.character_card.generate")
        == "story.character_card"
    )
    assert object_dossier_capability("story.reaction.generate") == "story.reaction"


def test_character_projection_never_renders_pattern_even_if_provider_returns_one():
    entity_id = "00000000-0000-0000-0000-000000000001"
    brief = {
        "novel_id": "novel",
        "scene_id": "scene",
        "scene_index": 3,
        "coverage": "partial",
        "omitted_count": 0,
        "omissions": ["角色视角无法逐条证明台账来源"],
        "world_fingerprint": "world-fingerprint",
        "continuity_fingerprint": "continuity-fingerprint",
        "pattern_fingerprint": "pattern-fingerprint",
        "checkpoint_refs": [],
        "world_items": [
            {
                "kind": "world_dossier",
                "entity_id": entity_id,
                "entry_id": "entry-public",
                "revision_id": "revision-public",
                "content": "公开的潮门由铜栓固定",
                "visibility": "public",
            }
        ],
        "continuity_items": [
            {
                "kind": "story_state",
                "entity_id": entity_id,
                "dimension": "entities",
                "field": "state",
                "value": "铜栓仍在位",
                "layer": "fact",
                "checkpoint_id": "checkpoint-1",
                "source_refs": [{"draft_id": "draft-1", "start_offset": 10}],
            }
        ],
        "pattern_items": [
            {
                "entry_id": "pattern-secret",
                "revision_id": "pattern-revision",
                "statement": "SECRET：他会背叛守门人",
                "modality": "interpretation_only",
                "evidence_refs": [{"source": {"draft_id": "secret-draft"}}],
            }
        ],
    }
    bundle = StructureContextBundle(
        novel_id="novel",
        task="story.character_card.generate",
        scope="scene",
        object_dossier_brief=brief,
        object_reference_dimensions=["object_dossier", "character_pattern"],
    )
    options = CompileOptions(
        novel_id="novel",
        task="story.character_card.generate",
        scope="scene",
        scene_id="scene",
        consumer_action="story.character_card.generate",
        reveal_mode="character",
        viewpoint_character_id=entity_id,
    )

    sections = ContextCompiler._build_object_dossier_sections(bundle, options)
    assert {section.key for section in sections} == {
        "object_dossier",
        "character_pattern",
    }
    object_section = next(
        section for section in sections if section.key == "object_dossier"
    )
    pattern_section = next(
        section for section in sections if section.key == "character_pattern"
    )
    assert "铜栓仍在位" in object_section.content
    assert "SECRET" not in "\n".join(section.content for section in sections)
    assert pattern_section.retrieval_metadata["pattern_basis"] == []
    assert all(
        fact["layer"] in {"fact", "belief", "observation"}
        for fact in object_section.retrieval_metadata["fact_basis"]
    )


def test_author_projection_keeps_interpretation_modality_separate_from_facts():
    brief = {
        "novel_id": "novel",
        "scene_id": "scene",
        "scene_index": 3,
        "coverage": "complete",
        "world_items": [],
        "continuity_items": [],
        "pattern_items": [
            {
                "entry_id": "pattern-1",
                "revision_id": "pattern-revision-1",
                "statement": "遇到封锁时倾向先寻找替代通道",
                "modality": "probable_pattern",
                "evidence_refs": [{"scene_id": "source-scene", "scene_index": 1}],
            }
        ],
    }
    bundle = StructureContextBundle(
        novel_id="novel",
        task="story.character_card.generate",
        scope="scene",
        object_dossier_brief=brief,
        object_reference_dimensions=["character_pattern"],
    )
    options = CompileOptions(
        novel_id="novel",
        task="story.character_card.generate",
        scope="scene",
        scene_id="scene",
        reveal_mode="author_safe",
    )

    section = ContextCompiler._build_object_dossier_sections(bundle, options)[0]
    assert section.key == "character_pattern"
    assert "解释性倾向；不是事实；probable_pattern" in section.content
    assert section.retrieval_metadata["pattern_basis"][0]["pattern_id"] == (
        "pattern:pattern-1:pattern-revision-1"
    )


@pytest.mark.asyncio
async def test_object_loader_is_off_by_default_and_keeps_capability_switches_separate(
    monkeypatch,
):
    entity_id = "00000000-0000-0000-0000-000000000001"

    class Reader:
        def __init__(self):
            self.calls = []

        async def load(self, _db, options, *, entity_ids, include_patterns):
            self.calls.append((options, entity_ids, include_patterns))
            return {
                "scene_id": options.scene_id,
                "world_items": [{"content": "world"}],
                "continuity_items": [{"value": "state"}],
                "pattern_items": [{"statement": "pattern"}],
                "layers": ["world", "continuity", "evolution"],
            }

    reader = Reader()
    loader = ObjectDossierLoader(reader)
    options = CompileOptions(
        novel_id="novel",
        task="writing.generate",
        scope="scene",
        scene_id="scene",
        entity_ids=[entity_id],
        consumer_action="writing.generate",
    )
    bundle = StructureContextBundle(novel_id="novel", task="write", scope="scene")
    monkeypatch.setattr(
        object_dossier_loader,
        "get_settings",
        lambda: SimpleNamespace(),
    )

    await loader.load(object(), options, bundle)
    assert reader.calls == []
    assert bundle.object_dossier_brief is None

    monkeypatch.setattr(
        object_dossier_loader,
        "get_settings",
        lambda: SimpleNamespace(
            object_dossier_enabled_capabilities=("writing.generate",),
            character_pattern_enabled_capabilities=(),
        ),
    )
    await loader.load(object(), options, bundle)
    assert reader.calls[-1][2] is False
    assert bundle.object_reference_dimensions == ["object_dossier"]
    assert bundle.object_dossier_brief["world_items"]
    assert bundle.object_dossier_brief["pattern_items"] == []
