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
