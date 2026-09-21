"""Versioned, code-owned capabilities; no model-controlled callables or URLs."""

import json
from pathlib import Path

from core.errors import ValidationError

CAPABILITIES = {
    item["capability_id"]: item
    for item in json.loads(Path(__file__).with_name("capabilities.json").read_text())[
        "capabilities"
    ]
}
SEMANTIC = frozenset(
    {
        "writing.next_beat.v1",
        "story.open_question.v1",
        "story.character_response.v1",
        "story.scene_transition.v1",
        "story.information_window.v1",
        "world.rule_decision.v1",
        "world.relationship_effect.v1",
        "evidence.next_query.v1",
        "assistant.discussion_next.v1",
        "interaction.visible_next_action.v1",
        "interaction.promise_consequence.v1",
    }
)


def rollout_available(novel_id, capability):
    from core.config import get_settings

    settings = get_settings()
    return capability not in settings.forecast_disabled_capabilities and (
        not settings.forecast_project_allowlist
        or str(novel_id) in settings.forecast_project_allowlist
    )


def require_rollout(novel_id, capabilities):
    if any(not rollout_available(novel_id, value) for value in capabilities):
        raise ValidationError(
            "这项能力已暂停或尚未向当前作品开放",
            code="CAPABILITY_UNAVAILABLE",
            status_code=503,
        )


def require_capabilities(values, *, persona="author"):
    selected = list(dict.fromkeys(values))
    if any(
        key not in CAPABILITIES or key.startswith("interaction.") != (persona == "rp")
        for key in selected
    ):
        raise ValidationError("当前入口不支持该前瞻能力", code="CAPABILITY_UNAVAILABLE")
    return selected


def defaults(page, *, persona="author"):
    if persona == "rp":
        return [
            "interaction.visible_next_action.v1",
            "interaction.promise_consequence.v1",
            "interaction.source_gap.v1",
        ]
    return {
        "writing": [
            "writing.next_beat.v1",
            "story.open_question.v1",
            "writing.recall_pack.v1",
        ],
        "scene": ["story.character_response.v1", "story.scene_transition.v1"],
        "world": ["world.rule_decision.v1", "world.rule_impact.v1"],
        "outline": ["story.information_window.v1", "story.structure_impact.v1"],
        "map": ["world.map_precondition.v1"],
        "rag": ["evidence.next_query.v1", "evidence.freshness_ready.v1"],
        "imports": [
            "imports.review_bottleneck.v1",
            "imports.next_stage.v1",
            "imports.recovery_next.v1",
        ],
        "assistant": ["assistant.discussion_next.v1", "assistant.cross_domain_root.v1"],
    }.get(
        page,
        ["project.resume.v1", "assistant.task_result_ready.v1", "account.readiness.v1"],
    )
