"""Prompt contract tests for RP story generation."""

import pytest

from modules.interaction.prompts import story_system_prompt


def test_story_system_prompt_enabled_options_requests_best_effort_suggestions() -> None:
    prompt = story_system_prompt(
        see_sea_enabled=False,
        action_options_enabled=True,
        request_kind="message",
    )

    assert "尽量给出 1 到 3 个有实质差异的行动建议" in prompt
    assert "只有无法可靠提出时才使用空列表或省略尾块" in prompt
    assert "不能为了凑数编造剧透或无意义行动" in prompt
    assert "0 到 3 个适合下一步的行动建议" not in prompt


@pytest.mark.parametrize(
    ("see_sea_enabled", "action_options_enabled"),
    [(True, True), (False, False)],
)
def test_story_system_prompt_unavailable_options_does_not_request_suggestions(
    see_sea_enabled: bool,
    action_options_enabled: bool,
) -> None:
    prompt = story_system_prompt(
        see_sea_enabled=see_sea_enabled,
        action_options_enabled=action_options_enabled,
        request_kind="message",
    )

    assert "不要给出行动建议。" in prompt
    assert "尽量给出 1 到 3 个有实质差异的行动建议" not in prompt
