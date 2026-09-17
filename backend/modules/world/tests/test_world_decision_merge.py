"""决定状态合并的矛盾消解回归（审计 RB-1）。

authority.constraints 有两类写入者：revise_world_design 把被否定决定的文本写入，
作者/RP 助手按"必须遵守的硬约束"语义直接写入 world_state。合并必须让同文条目
跟随决定本身的归属，其余约束只能作为锁定要求，且 confirmed 与 rejected 的
规范化交集恒为空。
"""

from infrastructure.llm.schemas import LLMMessage
from modules.world.llm_schemas import GeneratedWorldGenerationDecisionState
from modules.world.services.worldbuilding.world_generation_center_service import (
    WorldGenerationCenterService,
)


def _prepared(checkpoint, decision_state=None):
    return {
        "session_context": {"checkpoint": checkpoint},
        "conversation_messages": [LLMMessage(role="user", content="整理当前世界模型")],
        "decision_state": decision_state,
    }


def _checkpoint(decisions, constraints=()):
    return {
        "decisions": decisions,
        "world_state": {"authority": {"constraints": list(constraints)}},
    }


def _decision(key, text, disposition):
    return {
        "item_key": key,
        "text": text,
        "disposition": disposition,
        "source_keys": [],
    }


def test_authority_constraint_backing_locked_decision_stays_confirmed_only():
    prepared = _prepared(
        _checkpoint(
            decisions=[_decision("no-revival", "不得复活死者", "locked")],
            constraints=["不得复活死者"],
        )
    )
    state = WorldGenerationCenterService._merge_saved_decisions(prepared)
    assert "不得复活死者" in state.confirmed_requirements
    assert "不得复活死者" not in state.rejected_elements


def test_constraint_matching_rejected_decision_keeps_rejected_classification():
    prepared = _prepared(
        _checkpoint(
            decisions=[_decision("magic", "魔法体系", "rejected")],
            constraints=["魔法体系", "不得跨海贸易"],
        )
    )
    state = WorldGenerationCenterService._merge_saved_decisions(prepared)
    assert "魔法体系" in state.rejected_elements
    assert "魔法体系" not in state.confirmed_requirements
    assert "不得跨海贸易" in state.confirmed_requirements


def test_constraint_matching_open_decision_routes_to_unresolved():
    prepared = _prepared(
        _checkpoint(
            decisions=[_decision("open-1", "复活与否待定", "open")],
            constraints=["复活与否待定"],
        )
    )
    state = WorldGenerationCenterService._merge_saved_decisions(prepared)
    assert "复活与否待定" in state.unresolved_choices
    assert "复活与否待定" not in state.confirmed_requirements
    assert "复活与否待定" not in state.rejected_elements


def test_schema_validator_drops_rejected_overlap_normalized():
    state = GeneratedWorldGenerationDecisionState.model_validate(
        {
            "current_author_goal": "目标",
            "confirmed_requirements": ["不得 复活死者"],
            "rejected_elements": ["不得复活死者", "旧帝国"],
            "confidence": 1.0,
        }
    )
    assert state.confirmed_requirements == ["不得 复活死者"]
    assert state.rejected_elements == ["旧帝国"]
