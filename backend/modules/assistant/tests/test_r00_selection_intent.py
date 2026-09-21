"""R00 选区/intent 数据链：WorkContext 偏移语义、服务端一致性重验与
意图进入模型输入（V4 G3+/U 系列 · R00）。

对应验收（05-TRACEABILITY R00 行）：前端选中范围、服务器 SourceRange
与实际模型输入一致；"只润色"意图不主动扩大情节（前瞻侧能力收窄由
runtime 既有逻辑承接，本文件验证意图封闭集与指令渲染）。
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from modules.assistant.schemas import (
    TASK_HINT_DIRECTIVES,
    TASK_HINTS,
    WorkContext,
    verify_selection_range,
    work_directive,
)

DRAFT_ID = "11111111-1111-4111-8111-111111111111"


def _context(**overrides) -> WorkContext:
    base = {
        "page": "writing",
        "chapter_index": 1,
        "draft_id": DRAFT_ID,
        "selection": "白石城",
    }
    base.update(overrides)
    return WorkContext(**base)


class TestSelectionRangeContract:
    def test_offsets_require_pair_and_draft_and_selection(self) -> None:
        with pytest.raises(ValidationError, match="成对"):
            _context(selection_start=1)
        with pytest.raises(ValidationError, match="非空选区"):
            _context(selection="", selection_start=0, selection_end=0)
        with pytest.raises(ValidationError, match="绑定正文草稿"):
            WorkContext(
                page="writing", selection="白石城", selection_start=0, selection_end=3
            )

    def test_offsets_length_must_match_selection_points(self) -> None:
        with pytest.raises(ValidationError, match="长度不一致"):
            _context(selection_start=0, selection_end=2)  # 3 码点选区 ≠ 2 偏移跨度

    def test_valid_offsets_pass(self) -> None:
        work = _context(selection_start=4, selection_end=7)
        assert work.selection_start == 4


class TestVerifySelectionRange:
    def test_exact_substring_passes(self) -> None:
        content = "林舟与青竹在白石城重逢。"
        work = _context(selection="白石城", selection_start=6, selection_end=9)
        verify_selection_range(content, work)

    def test_drifted_source_fails_closed(self) -> None:
        # 服务端草稿已变（同长度修改）：旧选区偏移不再对应原文。
        content = "林舟与青竹在黑石镇重逢。"
        work = _context(selection="白石城", selection_start=6, selection_end=9)
        with pytest.raises(ValueError, match="不一致"):
            verify_selection_range(content, work)

    def test_out_of_range_fails(self) -> None:
        content = "短文"
        work = _context(selection="白石城", selection_start=0, selection_end=3)
        with pytest.raises(ValueError):
            verify_selection_range(content, work)

    def test_no_offsets_is_noop(self) -> None:
        verify_selection_range("任意正文", _context(selection="无关文本"))


class TestTaskHintDirective:
    def test_closed_set_shared_with_forecast(self) -> None:
        from modules.assistant.forecast.contracts import FocusRequest

        forecast_hints = set(FocusRequest.model_fields["task_hint"].annotation.__args__)
        assert forecast_hints == set(TASK_HINTS)

    def test_directive_reaches_model_input_line(self) -> None:
        polish = _context(task_hint="polish")
        directive = work_directive(polish)
        assert directive.startswith("作者意图：")
        assert "不得扩大情节" in directive
        assert work_directive(_context(task_hint="unknown")) == ""

    def test_unknown_hint_is_default(self) -> None:
        assert WorkContext().task_hint == "unknown"
        assert set(TASK_HINT_DIRECTIVES) < set(TASK_HINTS)


class TestTurnRequestCarriesChain:
    def test_turn_create_accepts_intent_and_offsets(self) -> None:
        from modules.assistant.schemas import TurnCreate

        payload = TurnCreate(
            novel_id=uuid.uuid4(),
            operation_id=uuid.uuid4(),
            message="只润色选区",
            context=_context(
                task_hint="polish", selection_start=6, selection_end=9
            ).model_dump(mode="json"),
        )
        assert payload.context.task_hint == "polish"
        assert payload.context.selection_start == 6

    def test_work_json_dump_includes_new_fields_for_prompt(self) -> None:
        # execute() 把 work.model_dump_json 注入最终 user 消息——
        # 新字段必须出现在这份模型输入里（R00 一致传递）。
        dumped = _context(
            task_hint="polish", selection_start=6, selection_end=9
        ).model_dump_json()
        assert "polish" in dumped
        assert '"selection_start":6' in dumped
