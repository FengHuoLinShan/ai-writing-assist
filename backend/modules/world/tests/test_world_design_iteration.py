"""Continuation preserves state and author authority across every action."""

import copy
import uuid

import pytest

from core.errors import ValidationError
from modules.world.schemas import WorldDesignCheckpointPayload, WorldDesignRevisionRequest
from modules.world.services.worldbuilding.world_design_iteration import (
    revise_world_design,
)
from modules.world.tests.test_adoption_package import _world_design_state


def _parent():
    state = _world_design_state()
    state["project"]["id"] = str(uuid.uuid4())
    state["rules"] = [
        {
            "id": "rule:tide",
            "name": "潮门",
            "status": "proposed",
            "capability": "输送货物",
            "impossibility": "不能运送生命",
            "costs": ["每次耗盐"],
            "knowledge_layer": "author_truth",
            "evidence": ["author:1"],
        }
    ]
    state["pressure_tests"][0].update(
        status="pass", result="原测试结果", evidence=["author:1"]
    )
    state["dependencies"] = [
        {"from": "T01", "to": "rule:tide", "kind": "requires", "status": "active"}
    ]
    state["fiction_core"]["prose"].update(status="valid", artifacts=["rule:tide"])
    state["actors"] = [
        {
            "id": "actor:1",
            "name": "盐商",
            "status": "proposed",
            "summary": "维护潮门",
            "evidence": ["author:1"],
        }
    ]
    state["authority"]["constraints"] = ["不得复活死者"]
    return WorldDesignCheckpointPayload(
        schema_version="world_design_checkpoint.v1",
        depth="seed",
        round_no=3,
        action="consolidate",
        source_manifest_hash="a" * 64,
        world_state=state,
        decisions=[
            {
                "item_key": "no-revival",
                "text": "不得复活死者",
                "disposition": "rejected",
                "source_keys": ["author:1"],
            }
        ],
    )


def _request(parent, **updates):
    return WorldDesignRevisionRequest.model_validate(
        {
            "novel_id": parent.world_state.project.id,
            "session_id": str(uuid.uuid4()),
            "parent_checkpoint_id": str(uuid.uuid4()),
            "expected_checkpoint_id": None,
            "action": "expand",
            "summary": "补充耗盐代价",
            "changes": {},
            **updates,
        }
    )


@pytest.mark.parametrize("action", ["expand", "connect", "pressure", "consolidate"])
def test_four_actions_preserve_parent_and_invalidate_only_dependents(action):
    parent = _parent()
    original = parent.model_dump(mode="json", by_alias=True)
    rule = parent.world_state.rules[0].model_dump()
    rule["costs"] = ["每次耗盐两袋"]
    result = revise_world_design(
        parent, _request(parent, action=action, changes={"rules": [rule]})
    )
    assert parent.model_dump(mode="json", by_alias=True) == original
    state = result.world_state.model_dump(mode="json", by_alias=True)
    for key, value in original["world_state"].items():
        if key not in {
            "rules",
            "pressure_tests",
            "fiction_core",
            "audit",
            "change_log",
            "extensions",
        }:
            assert state[key] == value, key
    assert result.world_state.rules[0].id == "rule:tide"
    assert result.world_state.pressure_tests[0].status == "not-run"
    assert result.world_state.pressure_tests[0].result == "原测试结果"
    assert result.world_state.fiction_core.prose.status == "needs-review"
    assert result.decisions == parent.decisions
    assert result.round_no == 4


def test_explicit_decision_replacement_preserves_other_constraints():
    parent = _parent()
    parent.world_state.authority.constraints.append("不得改变已采用地理")
    result = revise_world_design(
        parent,
        _request(
            parent,
            decisions=[
                {
                    "item_key": "no-revival",
                    "text": "复活仍待作者决定",
                    "disposition": "open",
                    "source_keys": ["author:1"],
                }
            ],
        ),
    )
    assert result.world_state.authority.constraints == ["不得改变已采用地理"]
    assert result.world_state.authority.open_questions[0].question == "复活仍待作者决定"
    assert parent.decisions[0].disposition == "rejected"


def test_duplicate_unknown_source_and_canon_promotion_fail_closed():
    parent = _parent()
    rule = parent.world_state.rules[0].model_dump()
    variants = [
        [rule, copy.deepcopy(rule)],
        [{**rule, "evidence": ["invented"]}],
        [{**rule, "status": "canon"}],
    ]
    for rules in variants:
        with pytest.raises(ValidationError):
            revise_world_design(parent, _request(parent, changes={"rules": rules}))


def test_depth_requires_real_content_and_does_not_imply_canon():
    parent = _parent()
    with pytest.raises(ValidationError, match="候选阶段"):
        revise_world_design(parent, _request(parent, depth="candidate"))
    changes = {
        "situated_tests": {
            "ordinary_tuesday": {
                "status": "partial",
                "scenario": "盐商轮班维护潮门",
                "evidence": ["author:1"],
            }
        }
    }
    candidate = revise_world_design(
        parent, _request(parent, changes=changes, depth="candidate")
    )
    instance = revise_world_design(candidate, _request(candidate, depth="instance"))
    assert instance.depth == "instance"
    assert instance.world_state.rules[0].status == "proposed"
    assert instance.world_state.audit.valid is None


def test_partial_rule_update_inherits_omitted_fields_but_explicit_clear_is_respected():
    parent = _parent()
    partial = {
        "id": "rule:tide",
        "name": "潮门",
        "status": "proposed",
        "capability": "输送货物",
        "impossibility": "不能运送生命",
        "knowledge_layer": "author_truth",
        "maintenance": ["双人轮值"],
    }
    result = revise_world_design(parent, _request(parent, changes={"rules": [partial]}))
    rule = result.world_state.rules[0]
    assert rule.costs == ["每次耗盐"]
    assert rule.impossibility == "不能运送生命"
    assert rule.evidence == ["author:1"]
    assert rule.maintenance == ["双人轮值"]
    cleared = revise_world_design(
        parent, _request(parent, changes={"rules": [{**partial, "costs": []}]})
    )
    assert cleared.world_state.rules[0].costs == []
    assert parent.world_state.rules[0].maintenance == []


def test_new_knowledge_identity_and_knower_reference_are_materialized_together():
    parent = _parent()
    result = revise_world_design(
        parent,
        _request(
            parent,
            changes={
                "actors": [{"id": "new:keeper", "name": "值守者", "status": "proposed"}],
                "knowledge_layers": {
                    "public_beliefs": [
                        {
                            "id": "new:alarm-belief",
                            "claim": "旗色表示闸门故障",
                            "status": "proposed",
                            "known_by": ["new:keeper"],
                            "evidence": ["author:1"],
                        }
                    ]
                },
            },
        ),
    )
    keeper = next(item for item in result.world_state.actors if item.name == "值守者")
    belief = result.world_state.knowledge_layers.public_beliefs[0]
    assert belief.known_by == [keeper.id]
    assert not belief.id.startswith("new:")


def test_fixed_test_name_is_metadata_while_revised_content_is_preserved():
    parent = _parent()
    original = parent.world_state.pressure_tests[-1]
    update = original.model_dump()
    update.update(
        name="三年窗口（十年后保持未运行）",
        result="前三年的变化与剩余七年缺口",
        status="not-run",
    )
    result = revise_world_design(
        parent, _request(parent, changes={"pressure_tests": [update]})
    )
    test = result.world_state.pressure_tests[-1]
    assert test.name == original.name
    assert test.result == update["result"]


def test_repair_keeps_previous_new_entries_and_accepts_explicit_field_clear():
    from modules.world.schemas import WorldDesignChanges
    from modules.world.services.worldbuilding.world_design_iteration import (
        merge_world_design_changes,
    )

    previous = WorldDesignChanges.model_validate(
        {
            "actors": [
                {
                    "id": "actors:watch",
                    "name": "值守者",
                    "status": "proposed",
                    "summary": "驻守码头",
                    "evidence": ["author:1"],
                }
            ],
            "knowledge_layers": {
                "public_beliefs": [
                    {
                        "id": "knowledge:alarm",
                        "claim": "旗色表示故障",
                        "status": "proposed",
                        "known_by": ["actors:watch"],
                    }
                ]
            },
        }
    )
    repair = WorldDesignChanges.model_validate(
        {
            "actors": [
                {
                    "id": "actors:watch",
                    "name": "值守者",
                    "status": "proposed",
                    "summary": "",
                    "evidence": [],
                }
            ],
        }
    )
    merged = merge_world_design_changes(previous, repair)
    assert merged.knowledge_layers == previous.knowledge_layers
    assert merged.actors[0].summary == ""
    assert merged.actors[0].evidence == []


def test_new_entry_references_are_resolved_and_external_model_identity_is_preserved():
    parent = _parent()
    parent.world_state.project.id = "world:synthetic"
    rule = parent.world_state.rules[0].model_dump()
    rule.update(id="new:salt-tax", name="盐税", capability="为维护筹资")
    request = _request(
        parent,
        novel_id=str(uuid.uuid4()),
        changes={
            "rules": [rule],
            "dependencies": [
                {
                    "from": "T02",
                    "to": "new:salt-tax",
                    "kind": "requires",
                    "status": "proposed",
                }
            ],
        },
    )
    first, second = (
        revise_world_design(parent, request),
        revise_world_design(parent, request),
    )
    identity = first.world_state.rules[-1].id
    assert identity == second.world_state.rules[-1].id and not identity.startswith("new:")
    assert first.world_state.dependencies[-1].to == identity
    assert first.world_state.project.id == "world:synthetic"
    assert first.world_core is None and first.decision_state is None


def test_revision_persists_task_brief_and_compact_review_reference():
    parent = _parent()
    decision_state = {
        "current_author_goal": "补足潮门维护闭环",
        "working_assumptions": ["盐由港务机构统一配给"],
        "checkable_commitments": ["说明资源来源与故障后果"],
        "confidence": 0.8,
    }
    reference = {
        "schema_version": "world_design_review_ref.v1",
        "status": "passed",
        "origin_task_id": str(uuid.uuid4()),
        "receipt_hash": "b" * 64,
    }
    result = revise_world_design(
        parent,
        _request(parent),
        decision_state=decision_state,
        review_reference=reference,
    )
    assert result.decision_state.current_author_goal == "补足潮门维护闭环"
    assert result.world_state.extensions["verified_counterexample_review"] == reference
