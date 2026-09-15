"""能力知识策略注册表测试：自洽性、域覆盖与基础设施豁免约束。"""

from __future__ import annotations

import pytest

from modules.evidence.compilation.knowledge.contracts import (
    KnowledgeContractError,
)
from modules.evidence.compilation.knowledge.policies import (
    CAPABILITY_REGISTRY,
    capability_ids,
    get_capability_policy,
    iter_capabilities,
    require_capability_policy,
    validate_registry,
)

EXPECTED_CAPABILITIES = (
    # Writing
    "writing.generate",
    "writing.semantic_review",
    "writing.targeted_revision",
    "writing.conflict_check.ai_review",
    "writing.conflict_check.ai_suggestion",
    # World
    "world.generation.chat",
    "world.generation.design_iteration",
    "world.generation.cocreation",
    "world.generation.convergence",
    "world.generation.exploration",
    "world.generation.semantic_inspection",
    "world.generation.suggestion",
    "world.ask",
    "world.world_bible.synopsis",
    "world.validation",
    "world.entity_fusion",
    "world.alias_relations.extract",
    "world.map_structure.generate",
    "world.map_atlas.plan",
    "world.map_image_prompt",
    "world.map_image.generate",
    # Story
    "story.story_outline.generate",
    "story.outline.p20",
    "story.outline.analyze",
    "story.character_card",
    "story.reaction",
    "story.script",
    "story.one_click",
    "story.scene_fusion",
    "story.structure_dedup",
    # Imports
    "imports.scene_plan",
    "imports.scene_slicing",
    "imports.scene_enrichment",
    "imports.scene_fusion",
    "imports.entity_extraction",
    "imports.structure_analysis",
    "imports.review_resolution",
    "imports.targeted_completion",
    # Interaction
    "interaction.story_generate",
    "interaction.summary_refresh",
    "interaction.continuity_review",
    "interaction.anonymous_story",
    # Assistant
    "assistant.turn",
    # 基础设施豁免
    "infrastructure.rag_query_planner",
    "infrastructure.reranker",
    "infrastructure.format_repair",
    "infrastructure.embedding",
    "infrastructure.account_connection_test",
)


def test_registry_is_self_consistent() -> None:
    assert validate_registry() == []


def test_registry_covers_expected_capabilities() -> None:
    for capability_id in EXPECTED_CAPABILITIES:
        assert capability_id in CAPABILITY_REGISTRY, capability_id
    assert len(CAPABILITY_REGISTRY) == len(EXPECTED_CAPABILITIES)


def test_registry_covers_all_domains() -> None:
    domains = {policy.domain for policy in iter_capabilities()}
    assert domains == {
        "writing",
        "world",
        "story",
        "imports",
        "interaction",
        "assistant",
        "infrastructure",
    }


def test_require_capability_policy_fails_closed() -> None:
    assert get_capability_policy("no.such.capability") is None
    with pytest.raises(KnowledgeContractError, match="not registered"):
        require_capability_policy("no.such.capability")


def test_infrastructure_exemptions_cannot_adopt_or_answer() -> None:
    for policy in iter_capabilities(domain="infrastructure"):
        assert policy.infrastructure is True
        assert policy.adoption_gate == "none"
        assert policy.output_permissions == ("internal",)
        assert policy.required_dimensions == ()


def test_writing_generate_requires_confirmation_and_dual_gate() -> None:
    policy = require_capability_policy("writing.generate")
    assert policy.confirmation_policy == "required"
    assert policy.adoption_gate == "adopt_requires_pass_and_review"
    assert "character_knowledge" in policy.required_dimensions
    assert "reader_reveal" in policy.required_dimensions


def test_rp_capabilities_declare_held_release_notes() -> None:
    story = require_capability_policy("interaction.story_generate")
    assert "release_state=held" in story.notes
    anonymous = require_capability_policy("interaction.anonymous_story")
    assert "失败关闭" in anonymous.notes


def test_capability_ids_sorted_and_unique() -> None:
    ids = capability_ids()
    assert ids == tuple(sorted(set(ids)))
