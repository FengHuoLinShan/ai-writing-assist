"""W3-A：Story 域任务运行信封声明的回归。

覆盖：
1. 生产注册的 9 个 story / outline task type 都显式声明 canonical root
   capability 与冻结请求额度（L0）；
2. deadline 只从既有代码来源推导：单链任务用其阶段预算，多链串行任务
   （reaction / one_click）按冻结的 character_ids 推导总时限；
3. 一条真实链：TaskWorker.run_once → story_character_card_generate handler →
   真实 LLMClient（provider 替身），断言任务 done、信封只写 meta 私有键、
   请求计数与该链预期一致、公开投影不含 `_ai_run_envelope`。
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from infrastructure.llm.limits import reset_llm_limiter_for_tests
from infrastructure.llm.schemas import LLMCallResponse, read_ai_run_envelope
from infrastructure.tasks.api import _public_task_meta
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry
from infrastructure.tasks.worker import TaskWorker


class _ChainProvider:
    """provider 传输层替身：按请求顺序返回 JSON 正文并计数。"""

    name = "fake"

    def __init__(self, payloads: list[str]) -> None:
        self._payloads = list(payloads)
        self.calls = 0

    async def generate(self, request) -> LLMCallResponse:
        self.calls += 1
        index = min(self.calls - 1, len(self._payloads) - 1)
        return LLMCallResponse(
            content=self._payloads[index],
            finish_reason="stop",
            model="deepseek-flash",
            provider="fake",
        )


class _NullLimiter:
    def run(self, call, *, limiter_scope=None):
        return call()

    @asynccontextmanager
    async def scope(self, *, limiter_scope=None):
        yield


def _chain_client(monkeypatch: pytest.MonkeyPatch, provider: _ChainProvider):
    from infrastructure.llm.client import LLMClient

    reset_llm_limiter_for_tests()
    client = LLMClient()
    client._provider = provider  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "infrastructure.llm.client.get_llm_limiter", lambda: _NullLimiter()
    )
    return client


class _TaskManager:
    def __init__(self, engine: Any, sessions: Any) -> None:
        self.engine = engine
        self.session_factory = sessions


async def _run_once(test_engine, sessions) -> AsyncTask | None:
    return await TaskWorker(
        db_manager=_TaskManager(test_engine, sessions),
        heartbeat_interval=60.0,
    ).run_once()


async def _enqueue(
    sessions: Any,
    task_type: str,
    *,
    meta: dict[str, Any],
    novel_id: str | None,
) -> uuid.UUID:
    async with sessions.begin() as db:
        return uuid.UUID(
            enqueue_task(db, task_type, meta=meta, novel_id=novel_id)
        )


async def _cleanup(sessions: Any, task_ids: list[uuid.UUID | None]) -> None:
    ids = [item for item in task_ids if item is not None]
    if not ids:
        return
    async with sessions.begin() as db:
        await db.execute(delete(AsyncTask).where(AsyncTask.id.in_(ids)))


# ---------------------------------------------------------------------------
# 1. 声明冻结：root capability / L0 / deadline
# ---------------------------------------------------------------------------


def _production_registry_with_story() -> TaskRegistry:
    import modules.story.outline_state.tasks  # noqa: F401  生产 handler 注册
    import modules.story.tasks  # noqa: F401  生产 handler 注册

    return TaskRegistry()


@pytest.mark.parametrize(
    ("task_type", "capability", "limit"),
    [
        ("story_outline_generate", "story.story_outline.generate", 64),
        ("outline_analyze", "story.outline.analyze", 2),
        ("outline_generate", "story.outline.p20", 64),
        ("scene_fusion_preview", "story.scene_fusion", 12),
        ("story_character_card_generate", "story.character_card", 28),
        ("story_reaction_propose", "story.reaction", 672),
        ("story_scene_script_generate", "story.script", 28),
        ("story_one_click", "story.one_click", 1372),
    ],
)
def test_story_tasks_declare_canonical_root_and_frozen_limit(
    task_type: str, capability: str, limit: int
) -> None:
    registry = _production_registry_with_story()
    assert registry.get_root_capability(task_type) == capability
    assert (
        registry.resolve_run_request_limit(task_type, SimpleNamespace(meta={}))
        == limit
    )


@pytest.mark.parametrize(
    ("task_type", "deadline"),
    [
        ("story_outline_generate", 1800.0),
        # outline_analyze 链路没有任何 step/阶段超时来源，不硬编码（报告已标注）。
        ("outline_analyze", None),
        ("outline_generate", 1800.0),
        ("scene_fusion_preview", 1800.0),
        ("story_character_card_generate", 1800.0),
        ("story_scene_script_generate", 1800.0),
    ],
)
def test_story_tasks_declare_deadline_with_code_source(
    task_type: str, deadline: float | None
) -> None:
    registry = _production_registry_with_story()
    assert (
        registry.resolve_run_deadline_seconds(task_type, SimpleNamespace(meta={}))
        == deadline
    )


@pytest.mark.parametrize(
    ("task_type", "resolver"),
    [
        ("story_reaction_propose", "reaction"),
        ("story_one_click", "one_click"),
    ],
)
def test_multi_chain_story_deadlines_derive_from_frozen_character_ids(
    task_type: str, resolver: str
) -> None:
    registry = _production_registry_with_story()
    flat = SimpleNamespace(meta={"character_ids": ["a", "b", "c"]})
    nested = SimpleNamespace(
        meta={"request": {"character_ids": ["a", "b", "c"]}},
    )
    expected_chains = 3 if resolver == "reaction" else 2 * 3 + 1
    assert registry.resolve_run_deadline_seconds(task_type, flat) == (
        1800.0 * expected_chains
    )
    assert registry.resolve_run_deadline_seconds(task_type, nested) == (
        1800.0 * expected_chains
    )
    # 没有冻结人物时按单链保守推导，不放大授权。
    empty = SimpleNamespace(meta={})
    assert registry.resolve_run_deadline_seconds(task_type, empty) == 1800.0 * (
        1 if resolver == "reaction" else 2 * 0 + 1
    )


# ---------------------------------------------------------------------------
# 2. 真实链：worker → handler → 真实 LLMClient（provider 替身）
# ---------------------------------------------------------------------------


def _card_payload() -> str:
    return json.dumps(
        {
            "content": {
                "version": "character_card.v1",
                "personality": "沉静、克制",
            },
            "warnings": [],
        },
        ensure_ascii=False,
    )


_AUDIT_PASS_PAYLOAD = json.dumps({"verdict": "pass", "findings": [], "dimensions": []})


def _stub_scene_context(novel_id: str, scene_id: str, character_id: str):
    payload = {
        "scene_id": scene_id,
        "novel_id": novel_id,
        "character_cards": [{"character_id": character_id, "title": "旧卡"}],
        "script_files": [{"id": "script-1"}],
        "outline_bundle": {"story_assets": ["asset-1"]},
    }
    return SimpleNamespace(
        context_hash="ctx-hash-1",
        model_dump=lambda *, mode=None: payload,
    )


@pytest.mark.asyncio
async def test_story_character_card_chain_builds_envelope_through_worker(
    test_engine,
    monkeypatch,
) -> None:
    """真实 worker → story_character_card_generate handler → LLMClient 单入口。"""
    import modules.story.tasks as story_tasks

    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    novel_id = str(uuid.uuid4())
    scene_id = str(uuid.uuid4())
    character_id = str(uuid.uuid4())

    provider = _ChainProvider([_card_payload(), _AUDIT_PASS_PAYLOAD])
    stub_compiled = SimpleNamespace(
        sections=[],
        warnings=[],
        budget_tokens=0,
        total_tokens=0,
    )

    async def stub_prepare_confirmed(db, *, novel_id, action, confirmation_id):
        del db, novel_id, action, confirmation_id
        return SimpleNamespace(compiled=stub_compiled, compile_options={})

    async def stub_compile_with_tiers(db, novel_id_arg, **_kwargs):
        del db, novel_id_arg
        return SimpleNamespace(blockers=[], sections=[], warnings=[], budget_tokens=0)

    def stub_render_compiled_context(_compiled):
        return ""

    async def stub_get_scene_story_context(db, *, novel_id, scene_id, character_ids):
        del db, character_ids
        return _stub_scene_context(novel_id, scene_id, character_id or "")

    async def stub_create_context_snapshot(db, **_kwargs):
        del db
        return SimpleNamespace(id=str(uuid.uuid4()))

    async def stub_restore_settings(db, novel_id_arg, snapshot):
        del db, novel_id_arg, snapshot
        return {"llm": {"provider_id": "deepseek", "model": "deepseek-flash"}}

    def fake_snapshot_client(settings, *, novel_id, **_kwargs):
        del settings, novel_id
        return _chain_client(monkeypatch, provider)

    monkeypatch.setattr(
        story_tasks, "prepare_confirmed_ai_action", stub_prepare_confirmed
    )
    monkeypatch.setattr(story_tasks, "compile_with_tiers", stub_compile_with_tiers)
    monkeypatch.setattr(
        story_tasks, "render_compiled_context", stub_render_compiled_context
    )
    monkeypatch.setattr(
        story_tasks, "get_scene_story_context", stub_get_scene_story_context
    )
    monkeypatch.setattr(
        story_tasks, "create_context_snapshot", stub_create_context_snapshot
    )
    monkeypatch.setattr(
        story_tasks,
        "restore_project_llm_execution_settings",
        stub_restore_settings,
    )
    monkeypatch.setattr(
        story_tasks, "create_project_snapshot_llm_client", fake_snapshot_client
    )

    task_id = await _enqueue(
        sessions,
        "story_character_card_generate",
        meta={
            "action": story_tasks.STORY_CHARACTER_CARD_ACTION,
            "request": {
                "novel_id": novel_id,
                "scene_id": scene_id,
                "character_id": character_id,
                "context_confirmation_id": "confirmation-1",
                "confirmed": True,
            },
            "llm_execution_snapshot": {
                "novel_id": novel_id,
                "profile": {"model": "deepseek-flash"},
                "llm": {"model": "deepseek-flash"},
            },
        },
        novel_id=novel_id,
    )
    try:
        returned = await _run_once(test_engine, sessions)

        assert returned is not None and returned.status == "done"
        # 一条 card 链 = 1 次结构化生成 + 1 次知识审查。
        assert provider.calls == 2
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            result = stored.result or {}
            assert result.get("preview_only") is True
            assert result.get("writes") == []
            assert (result.get("preview") or {}).get("content", {}).get(
                "personality"
            ) == "沉静、克制"
            envelope = read_ai_run_envelope(
                (stored.meta or {}).get("_ai_run_envelope")
            )
            assert envelope is not None
            assert envelope.root_capability_id == "story.character_card"
            assert envelope.requests_started == 2
            assert envelope.requests_settled == 2
            assert envelope.requests_unknown == 0
            assert envelope.request_limit == 28
            assert envelope.deadline_at is not None
            deadline_seconds = (
                envelope.deadline_at - envelope.started_at
            ).total_seconds()
            # 同一时刻读取存在亚毫秒漂移，冻结的预算就是 1800s。
            assert 1799 < deadline_seconds <= 1800
            step_names = {step.step_name for step in envelope.steps}
            # 稳定 step 名：结构化生成 + 知识审查各一条，不含调用序数。
            assert step_names == {
                "story.character_card.generate.structured",
                "story.character_card.verdict",
            }
            # 信封是 meta 私有键：公开投影剥离，result 不写信封。
            assert "_ai_run_envelope" not in _public_task_meta(stored.meta)
            assert "_ai_run_envelope" not in (stored.result or {})
    finally:
        await _cleanup(sessions, [task_id])
