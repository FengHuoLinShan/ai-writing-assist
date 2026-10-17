"""确定性探索尺度推荐规则（P0 §8）：关键词与信号优先级钉死可单测。"""

from __future__ import annotations

from modules.story.exploration_recommend import (
    EVENT_SCALE,
    SANDBOX_SCALE,
    SCENE_LINE_SCALE,
    recommend_exploration_scale,
)


def test_selection_beats_every_keyword_signal():
    scale, reason = recommend_exploration_scale(
        "为什么面包师每天三点起床？",
        "如果重力减半会怎样",
        has_selection=True,
        project_has_content=True,
    )
    assert scale == SCENE_LINE_SCALE
    assert reason


def test_scene_keywords_win_over_event_and_sandbox():
    scale, _ = recommend_exploration_scale(
        "他会怎么回应这个消息？", project_has_content=True
    )
    assert scale == SCENE_LINE_SCALE


def test_event_keywords_beat_sandbox_and_default():
    scale, _ = recommend_exploration_scale("这里为什么说不通？", project_has_content=True)
    assert scale == EVENT_SCALE


def test_sandbox_keywords_recommend_hypothetical():
    scale, _ = recommend_exploration_scale(
        "如果重力减半，小镇会怎样？", project_has_content=True
    )
    assert scale == SANDBOX_SCALE


def test_task_hint_is_joined_into_signal_text():
    scale, _ = recommend_exploration_scale(
        "", task_hint="帮忙补桥", project_has_content=True
    )
    assert scale == EVENT_SCALE


def test_empty_project_without_signals_starts_from_sandbox():
    scale, reason = recommend_exploration_scale(
        "随便看看", project_has_content=False
    )
    assert scale == SANDBOX_SCALE
    assert "还没有正文" in reason


def test_no_signal_defaults_to_event_diagnose():
    scale, _ = recommend_exploration_scale("随便看看", project_has_content=True)
    assert scale == EVENT_SCALE
