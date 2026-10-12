"""方向卡 LLM step（BR-5）：schema 约束、预算与超时边界、配置失败关闭。"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from pydantic import ValidationError as PydanticValidationError

from modules.assistant.guided_flow import direction_cards
from modules.assistant.guided_flow.direction_cards import (
    DirectionCard,
    DirectionCardBatch,
    draft_direction_cards,
)

OWNER_PROJECT = "00000000-0000-0000-0000-000000000001"


def _card(title: str = "潮汐都市") -> DirectionCard:
    return DirectionCard(
        title=title,
        genre_promise="城市奇幻",
        central_conflict="潮钟权柄之争",
        protagonist_goal="找回被收走的名字",
        world_tone="潮湿、明亮",
        reader_promise="每章解开一层规则",
        main_risk="设定密度偏高",
    )


def test_card_schema_bounds_fields():
    """六个字段都是必填且有限长；空串或超长失败关闭。"""
    with pytest.raises(PydanticValidationError):
        DirectionCard(
            title="",
            genre_promise="a",
            central_conflict="b",
            protagonist_goal="c",
            world_tone="d",
            reader_promise="e",
            main_risk="f",
        )
    with pytest.raises(PydanticValidationError):
        DirectionCard(
            title="t",
            genre_promise="x" * 301,
            central_conflict="b",
            protagonist_goal="c",
            world_tone="d",
            reader_promise="e",
            main_risk="f",
        )


def test_batch_schema_requires_two_or_three_cards():
    """一次调用固定出 2-3 张：1 张或 4 张都是格式失败（触发修复或报错）。"""
    assert DirectionCardBatch(cards=[_card("a"), _card("b")]).cards
    with pytest.raises(PydanticValidationError):
        DirectionCardBatch(cards=[_card("only")])
    with pytest.raises(PydanticValidationError):
        DirectionCardBatch(cards=[_card(str(index)) for index in range(4)])


def test_direction_card_budget_is_bounded():
    """预算收敛：单批一次调用、至多 1 次格式修复、每流程至多 3 批、超时有界。"""
    assert direction_cards._MAX_FIX_ATTEMPTS == 1
    assert direction_cards.MAX_BATCHES == 3
    assert 0 < direction_cards._TIMEOUT_SECONDS <= 600
    assert direction_cards._VISION_MAX_CHARS == 2000


def test_user_content_truncates_and_flags_later_batches():
    long_vision = "潮" * 5000
    content = direction_cards._user_content(long_vision, "奇幻", "长篇", batch=2)
    plain = direction_cards._user_content(long_vision, "", "", batch=1)
    assert len(plain) < len(content)
    assert "第 2 批" in content
    assert "题材意向：奇幻" in content
    assert long_vision not in content
    assert long_vision[:direction_cards._VISION_MAX_CHARS] in content


class _FakeClient:
    model_name = "fake-model"

    def __init__(self, calls: list, batch: DirectionCardBatch | Exception) -> None:
        self.calls = calls
        self.batch = batch

    async def generate_structured(self, request, schema, **kwargs):
        self.calls.append(
            {
                "schema": schema,
                "max_fix_attempts": kwargs.get("max_fix_attempts"),
                "timeout": kwargs.get("timeout"),
                "messages": [message.content for message in request.messages],
            }
        )
        if isinstance(self.batch, Exception):
            raise self.batch
        return self.batch

    async def close(self) -> None:
        return None


def _fake_client_context(client: _FakeClient):
    @asynccontextmanager
    async def _open(db, novel_id, **_kwargs):
        yield client

    return _open


async def test_draft_direction_cards_single_structured_call(
    monkeypatch,
):
    """一次结构化调用出 2-3 张卡；带 step 名与预算，输入被截断。"""
    calls: list = []
    client = _FakeClient(calls, DirectionCardBatch(cards=_cards()))
    monkeypatch.setattr(
        direction_cards, "open_project_llm_client", _fake_client_context(client)
    )
    cards = await draft_direction_cards(
        None, OWNER_PROJECT, vision="一句构想", genre_hint="奇幻", length_hint="长篇"
    )
    assert [card.title for card in cards] == ["潮汐都市", "守灯人"]
    assert len(calls) == 1
    record = calls[0]
    assert record["schema"] is DirectionCardBatch
    # 预算：格式修复至多 1 次；超时与批数上限由模块常量钉住（见预算测试）。
    assert record["max_fix_attempts"] == 1
    # 构想 + 意向进提示词；第二批提示只出现在 batch>1 的调用里。
    assert "一句构想" in record["messages"][-1]
    assert "题材意向：奇幻" in record["messages"][-1]


def _cards() -> list[DirectionCard]:
    return [_card("潮汐都市"), _card("守灯人")]


async def test_draft_direction_cards_model_failure_fails_closed(monkeypatch):
    """模型不可用/格式失败时异常向上传播，由流程停点展示，不产出伪卡片。"""
    client = _FakeClient([], RuntimeError("model unavailable"))
    monkeypatch.setattr(
        direction_cards, "open_project_llm_client", _fake_client_context(client)
    )
    with pytest.raises(RuntimeError, match="model unavailable"):
        await draft_direction_cards(None, OWNER_PROJECT, vision="构想")
