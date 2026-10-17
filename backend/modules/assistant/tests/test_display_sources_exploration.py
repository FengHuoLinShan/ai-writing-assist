"""display_sources 对两类探索 domain_reference 的按类型键白名单（P0 §8/D）。"""

from __future__ import annotations

from modules.assistant.service import (
    _DOMAIN_REFERENCE_BASE_KEYS,
    _DOMAIN_REFERENCE_KEYS_BY_TYPE,
    display_sources,
)


def _ref(domain_reference: dict) -> dict:
    return {
        "title": "探索结果",
        "snippet": "影响链一行",
        "domain_reference": domain_reference,
    }


def test_exploration_result_keeps_type_specific_keys_and_drops_unknowns():
    ref = _ref(
        {
            "type": "story_exploration_result",
            "task_id": "task-1",
            "task_type": "story_exploration_progression_task",
            "root_id": "root-1",
            "branch_id": "branch-1",
            "result_id": "result-1",
            "scale": "sandbox",
            "output_kind": "story.exploration.sandbox",
            "payload": {"influence_chain": []},
            "raw_internal": "should-not-leak",
        }
    )
    result = display_sources({"ev-1": ref}, ["ev-1"])
    domain = result[0]["domain_reference"]
    allowed = _DOMAIN_REFERENCE_KEYS_BY_TYPE["story_exploration_result"]
    assert set(domain) <= allowed
    assert {
        "task_id",
        "task_type",
        "root_id",
        "branch_id",
        "result_id",
        "scale",
        "output_kind",
        "payload",
    } <= set(domain)
    assert domain["root_id"] == "root-1"
    assert domain["payload"] == {"influence_chain": []}
    assert "raw_internal" not in domain


def test_exploration_recommendation_whitelist_is_narrow():
    ref = _ref(
        {
            "type": "story_exploration_recommendation",
            "scale": "event",
            "focus_hint": "订单量",
            "reason": "问题指向因果缺口",
            "payload": {"should": "not-persist"},
        }
    )
    result = display_sources({"ev-2": ref}, ["ev-2"])
    domain = result[0]["domain_reference"]
    allowed = _DOMAIN_REFERENCE_KEYS_BY_TYPE["story_exploration_recommendation"]
    assert set(domain) <= allowed
    assert {"scale", "focus_hint", "reason"} <= set(domain)
    assert "payload" not in domain


def test_unknown_domain_type_falls_back_to_base_keys():
    ref = _ref({"type": "totally_new_type", "payload": {"x": 1}, "task_id": "t-9"})
    result = display_sources({"ev-3": ref}, ["ev-3"])
    domain = result[0]["domain_reference"]
    assert set(domain) <= _DOMAIN_REFERENCE_BASE_KEYS
    assert domain["task_id"] == "t-9"
    assert domain["type"] == "totally_new_type"
    assert "payload" not in domain
