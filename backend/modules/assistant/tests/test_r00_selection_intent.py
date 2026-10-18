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
TEMP_DRAFT_ID = "22222222-2222-4222-8222-222222222222"


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


class TestWorldFocusContext:
    def test_entity_dossier_and_relation_refs_are_typed(self) -> None:
        entity_ref = {
            "kind": "entity",
            "entity_id": DRAFT_ID,
            "updated_at": "2026-10-18T08:00:00Z",
        }
        work = WorkContext(
            page="world",
            target={"target_type": "world_entity", "target_id": DRAFT_ID},
            focus_ref=entity_ref,
            focus_label="对象：白石城",
        )
        assert work.focus_ref.kind == "entity"
        assert "focus_label" not in work.model_dump_json(exclude={"focus_label"})
        assert work.focus_ref.updated_at.isoformat() == "2026-10-18T08:00:00+00:00"

        dossier = WorkContext(
            page="world",
            target={"target_type": "world_entity", "target_id": DRAFT_ID},
            focus_ref={
                "kind": "dossier_entry",
                "entity_id": DRAFT_ID,
                "entry_group_id": TEMP_DRAFT_ID,
                "revision_id": "33333333-3333-4333-8333-333333333333",
            },
        )
        relation = WorkContext(
            page="world",
            target={"target_type": "world_entity", "target_id": DRAFT_ID},
            focus_ref={
                "kind": "relation",
                "entity_id": DRAFT_ID,
                "relation_id": TEMP_DRAFT_ID,
                "updated_at": "2026-10-18T08:00:00Z",
            },
        )
        assert dossier.focus_ref.kind == "dossier_entry"
        assert relation.focus_ref.kind == "relation"

    def test_focus_must_belong_to_current_world_object_page(self) -> None:
        focus_ref = {
            "kind": "entity",
            "entity_id": DRAFT_ID,
            "updated_at": "2026-10-18T08:00:00Z",
        }
        with pytest.raises(ValidationError, match="只能来自世界对象页"):
            _context(
                page="writing",
                target={"target_type": "world_entity", "target_id": DRAFT_ID},
                focus_ref=focus_ref,
            )
        with pytest.raises(ValidationError, match="必须属于当前对象"):
            WorkContext(
                page="world",
                target={
                    "target_type": "world_entity",
                    "target_id": TEMP_DRAFT_ID,
                },
                focus_ref=focus_ref,
            )
        with pytest.raises(ValidationError, match="对应的对象"):
            WorkContext(page="world", focus_ref=focus_ref)

    def test_world_focus_cannot_mix_with_draft_or_selection(self) -> None:
        focus_ref = {
            "kind": "entity",
            "entity_id": DRAFT_ID,
            "updated_at": "2026-10-18T08:00:00Z",
        }
        with pytest.raises(ValidationError, match="不能混入正文草稿"):
            WorkContext(
                page="world",
                target={"target_type": "world_entity", "target_id": DRAFT_ID},
                focus_ref=focus_ref,
                draft_id=DRAFT_ID,
            )


class TestTemporaryDraftContext:
    def test_temporary_context_does_not_bind_to_saved_draft(self) -> None:
        work = _context(draft_id=None, temporary_draft_id=TEMP_DRAFT_ID)
        assert work.temporary_draft_id == uuid.UUID(TEMP_DRAFT_ID)
        assert work.draft_id is None
        assert work.selection_start is None
        assert work.selection_end is None

    def test_temporary_context_rejects_saved_source_and_confirmations(self) -> None:
        with pytest.raises(ValidationError, match="冒充已保存正文"):
            _context(temporary_draft_id=TEMP_DRAFT_ID, source_hash="a" * 64)
        with pytest.raises(ValidationError, match="不能沿用已确认资料"):
            _context(
                draft_id=None,
                temporary_draft_id=TEMP_DRAFT_ID,
                context_confirmation_id=TEMP_DRAFT_ID,
                context_confirmation_action="writing.review",
            )
        with pytest.raises(ValidationError, match="只能来自写作页"):
            _context(page="world", temporary_draft_id=TEMP_DRAFT_ID)


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

    def test_explicit_world_focus_requires_materialization_and_stays_author_only(
        self,
    ) -> None:
        focus = WorkContext(
            page="world",
            target={"target_type": "world_entity", "target_id": DRAFT_ID},
            focus_ref={
                "kind": "entity",
                "entity_id": DRAFT_ID,
                "updated_at": "2026-10-18T08:00:00Z",
            },
            focus_label="UI-only label",
        )
        directive = work_directive(focus)
        assert "inspect_current" in directive
        assert "作者视角" in directive
        assert "UI-only label" not in directive

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

    def test_turn_create_accepts_temporary_context_without_saved_source(self) -> None:
        from modules.assistant.schemas import TurnCreate

        context = _context(draft_id=None, temporary_draft_id=TEMP_DRAFT_ID).model_dump(
            mode="json"
        )
        payload = TurnCreate(
            novel_id=uuid.uuid4(),
            operation_id=uuid.uuid4(),
            message="讨论当前选区",
            context=context,
        )
        assert payload.context.temporary_draft_id == uuid.UUID(TEMP_DRAFT_ID)
        assert payload.context.draft_id is None

    def test_unset_temp_marker_preserves_turn_idempotency(self) -> None:
        from modules.assistant.service import _legacy_compatible_request_hash

        legacy_payload = {
            "message": "只讨论选区",
            "context": {"draft_id": DRAFT_ID, "selection": "白石城"},
        }
        additive_payload = {
            **legacy_payload,
            "context": {
                **legacy_payload["context"],
                "temporary_draft_id": None,
                "focus_ref": None,
            },
        }
        unbound_payload = {
            "message": "只讨论选区",
            "context": {"selection": "白石城"},
        }
        temporary_payload = {
            **unbound_payload,
            "context": {
                **unbound_payload["context"],
                "temporary_draft_id": TEMP_DRAFT_ID,
            },
        }
        focused_payload = {
            **unbound_payload,
            "context": {
                **unbound_payload["context"],
                "focus_ref": {
                    "kind": "entity",
                    "entity_id": DRAFT_ID,
                    "updated_at": "2026-10-18T08:00:00Z",
                },
            },
        }
        focused_with_label = {
            **focused_payload,
            "context": {**focused_payload["context"], "focus_label": "对象甲"},
        }

        assert _legacy_compatible_request_hash(additive_payload) == (
            _legacy_compatible_request_hash(legacy_payload)
        )
        assert _legacy_compatible_request_hash(temporary_payload) != (
            _legacy_compatible_request_hash(unbound_payload)
        )
        assert _legacy_compatible_request_hash(focused_payload) != (
            _legacy_compatible_request_hash(unbound_payload)
        )
        assert _legacy_compatible_request_hash(focused_with_label) == (
            _legacy_compatible_request_hash(focused_payload)
        )

    def test_work_json_dump_includes_new_fields_for_prompt(self) -> None:
        # execute() 把 work.model_dump_json 注入最终 user 消息——
        # 新字段必须出现在这份模型输入里（R00 一致传递）。
        dumped = _context(
            task_hint="polish", selection_start=6, selection_end=9
        ).model_dump_json()
        assert "polish" in dumped
        assert '"selection_start":6' in dumped
