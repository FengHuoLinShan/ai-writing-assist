"""探索 API 层：推荐、gate 边界、start 幂等与守卫、比较与历史路由（P0 §6/§8）。"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from modules.account.settings_constants import LOCAL_OWNER_ID
from modules.evidence.contracts import Assumption, ProvisionalStart
from modules.story.exploration_budget import preview_exploration_budget
from modules.story.exploration_schemas import (
    SANDBOX_OUTPUT_KIND,
    ExplorationOutputEnvelope,
    SandboxOutputV1,
)
from modules.story.exploration_service import (
    create_exploration_root,
    pack_exploration_output,
)
from modules.story.world_progression_models import (
    StoryWorldProgressionRoot,
    StoryWorldProgressionStep,
)

OWNER_ID = str(LOCAL_OWNER_ID)
_QUESTION = "这个城镇每天只有一小时重力减半，面包师的一天会怎样？"


@pytest.fixture(autouse=True)
def _exploration_gate_off_by_default(monkeypatch):
    """默认关闭 gate 并清掉 settings 缓存；单测内自行 setenv+cache_clear 开启。"""
    from core.config import get_settings

    monkeypatch.setenv("STORY_EXPLORATION_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _enable_exploration(monkeypatch):
    from core.config import get_settings

    monkeypatch.setenv("STORY_EXPLORATION_ENABLED", "true")
    get_settings.cache_clear()
    get_settings.cache_clear()


def _provisional_start(question: str = _QUESTION) -> ProvisionalStart:
    return ProvisionalStart(
        kind="provisional",
        question=question,
        assumptions=[Assumption(kind="world_rule", text="每天只有一小时重力减半")],
        time_basis="assumed_now",
    )


def _sandbox_envelope() -> ExplorationOutputEnvelope:
    return ExplorationOutputEnvelope(
        output_kind=SANDBOX_OUTPUT_KIND,
        schema_version=1,
        payload=SandboxOutputV1.model_validate(
            {
                "question": "重力减半后面包师的一天？",
                "influence_chain": [
                    {
                        "condition": "揉面时间不变",
                        "mechanism": "重力降低让面团发酵更快",
                        "effect": "面包更松软",
                    }
                ],
            }
        ),
    )


async def _seed_sandbox_result(db_session, project_id):
    from datetime import UTC, datetime, timedelta

    from infrastructure.llm.workflow_budget import new_ai_run_envelope
    from modules.story.exploration_schemas import exploration_start_fingerprint

    start = _provisional_start()
    root, branch = await create_exploration_root(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        scale="sandbox",
        start=start,
        context_confirmation_id=str(uuid.uuid4()),
    )
    root.request_json = {
        **(root.request_json or {}),
        "exploration_scale": "sandbox",
        "exploration_start_fingerprint": exploration_start_fingerprint(
            start, "sandbox"
        ),
    }
    started_at = datetime.now(UTC)
    envelope = new_ai_run_envelope(
        operation_id=str(uuid.uuid4()),
        run_id=str(root.id),
        root_capability_id="story.exploration",
        novel_id=str(project_id),
        request_limit=1,
        budget_mode="bounded",
        token_limit=200_000,
        started_at=started_at,
        deadline_at=started_at + timedelta(hours=1),
    )
    root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
    step = StoryWorldProgressionStep(
        novel_id=root.novel_id,
        root_id=root.id,
        branch_id=branch.id,
        step_number=1,
        source_hash=root.source_hash,
        input_hash="a" * 64,
        output_hash="b" * 64,
        input_json={"mode": "start"},
        result_json=pack_exploration_output(_sandbox_envelope()),
        state_json={},
        metrics_json={"mode": "start", "exploration": True},
        basis_changed=False,
    )
    db_session.add(step)
    await db_session.flush()
    return root, branch, step, start


# ---------------------------------------------------------------------------
# preview：确定性推荐 + 名义预算
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_recommends_scale_and_nominal_budget(
    async_client, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    response = await async_client.post(
        "/api/story/exploration/preview",
        json={"novel_id": test_project_id, "question": "如果重力减半，会怎样？"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recommended_scale"] == "sandbox"
    assert body["budget"]["requests_max"] == 1
    assert body["budget"]["follow_up_max_requests"] == 1
    assert body["requires_confirmation"] is True
    assert body["recommendation"]["type"] == "story_exploration_recommendation"

    explicit = await async_client.post(
        "/api/story/exploration/preview",
        json={"novel_id": test_project_id, "scale": "scene_line"},
    )
    assert explicit.status_code == 200
    assert explicit.json()["recommended_scale"] == "scene_line"
    assert explicit.json()["recommendation"]["reason"] == ""


# ---------------------------------------------------------------------------
# gate 边界：执行类 503，历史/比较仍可读
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_blocks_execution_but_keeps_history_and_compare_readable(
    async_client, db_session, test_project_id, monkeypatch
):
    monkeypatch.delenv("STORY_EXPLORATION_ENABLED", raising=False)
    _root, _branch, step, _start = await _seed_sandbox_result(
        db_session, test_project_id
    )
    _root2, _branch2, step2, _start2 = await _seed_sandbox_result(
        db_session, test_project_id
    )

    execution_calls = [
        (
            "POST",
            "/api/story/exploration/preview",
            {"json": {"novel_id": test_project_id, "scale": "sandbox"}},
        ),
        (
            "POST",
            "/api/story/exploration/confirmation/preview",
            {
                "json": {
                    "novel_id": test_project_id,
                    "scale": "sandbox",
                    "action": "story.exploration.sandbox.generate",
                    "start": _provisional_start().model_dump(mode="json"),
                }
            },
        ),
        (
            "POST",
            "/api/story/exploration/start",
            {
                "json": _start_body(
                    test_project_id,
                    _provisional_start(),
                    operation_id=uuid.uuid4(),
                )
            },
        ),
        (
            "POST",
            f"/api/story/exploration/results/{step.id}/detail",
            {
                "json": {
                    "novel_id": test_project_id,
                    "operation_id": str(uuid.uuid4()),
                }
            },
        ),
        (
            "POST",
            f"/api/story/exploration/results/{step.id}/save-edit",
            {
                "json": {
                    "novel_id": test_project_id,
                    "base_output_kind": "story.exploration.sandbox",
                    "edited_payload": {
                        "question": "重力减半后面包师的一天？",
                        "influence_chain": [
                            {
                                "condition": "揉面时间不变",
                                "mechanism": "重力降低让面团发酵更快",
                                "effect": "作者改：面包更紧实",
                            }
                        ],
                    },
                }
            },
        ),
    ]
    for method, url, kwargs in execution_calls:
        response = await getattr(async_client, method.lower())(url, **kwargs)
        assert response.status_code == 503, (url, response.status_code)
        assert "独立探索尚未开启" in response.json()["detail"]

    history = await async_client.get(
        "/api/story/exploration/history", params={"novel_id": test_project_id}
    )
    assert history.status_code == 200
    assert history.json()["total"] >= 2

    compare = await async_client.post(
        "/api/story/exploration/compare",
        json={
            "novel_id": test_project_id,
            "first_result_id": str(step.id),
            "second_result_id": str(step2.id),
        },
    )
    assert compare.status_code == 200
    assert compare.json()["first"]["result_id"] == str(step.id)


# ---------------------------------------------------------------------------
# confirmation：经 Evidence facade 的预览与落确认
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmation_preview_and_confirm_round_trip(
    async_client, test_project_id, monkeypatch
):
    from modules.evidence import facade as evidence_facade
    from modules.evidence.contracts import ExplorationContextRequest
    from modules.story import exploration_api

    _enable_exploration(monkeypatch)
    seen = {}

    async def preview_context(db, request: ExplorationContextRequest):
        seen["request"] = request
        return {
            "context_fingerprint": "1" * 64,
            "selected_asset_ids": [],
            "sources": [],
            "blockers": [],
        }

    async def confirm_context(db, request: ExplorationContextRequest):
        seen["confirmed"] = request
        return SimpleNamespace(
            id="ctx-record-1",
            action=request.action,
            scope=request.scope,
            context_fingerprint="1" * 64,
            result_status="confirmed",
            stale_reasons=[],
            warnings=[],
        )

    monkeypatch.setattr(exploration_api, "preview_exploration_context", preview_context)
    monkeypatch.setattr(evidence_facade, "confirm_exploration_context", confirm_context)

    start = _provisional_start()
    preview_body = {
        "novel_id": test_project_id,
        "scale": "sandbox",
        "action": "story.exploration.sandbox.generate",
        "focus": "",
        "start": start.model_dump(mode="json"),
    }
    previewed = await async_client.post(
        "/api/story/exploration/confirmation/preview", json=preview_body
    )
    assert previewed.status_code == 200
    assert previewed.json()["context_fingerprint"] == "1" * 64
    assert seen["request"].scope == "project"

    confirmed = await async_client.post(
        "/api/story/exploration/confirmation",
        json={**preview_body, "expected_context_fingerprint": "1" * 64},
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["confirmation_id"] == "ctx-record-1"
    assert body["result_status"] == "confirmed"


# ---------------------------------------------------------------------------
# start：幂等 + 确认一致性 + 预算 hash 守卫
# ---------------------------------------------------------------------------


def _stub_confirmation(monkeypatch, start: ProvisionalStart, scale: str = "sandbox"):
    from modules.story import exploration_api

    async def fresh_confirmation(db, *, novel_id, action, confirmation_id):
        return SimpleNamespace(
            compile_options={
                "exploration_start": start.model_dump(mode="json"),
                "exploration_scale": scale,
                "exploration_focus": "",
            }
        )

    async def snapshot(db, novel_id):
        return {"novel_id": novel_id}

    async def attach_ref(
        db, *, novel_id, confirmation_id, result_type, result_id, status
    ):
        return None

    monkeypatch.setattr(
        exploration_api, "require_fresh_confirmation", fresh_confirmation
    )
    monkeypatch.setattr(
        exploration_api, "build_project_llm_execution_snapshot", snapshot
    )
    monkeypatch.setattr(exploration_api, "attach_result_ref", attach_ref)


def _start_body(
    test_project_id: str,
    start: ProvisionalStart,
    *,
    operation_id,
    hash_override=None,
):
    budget = preview_exploration_budget(
        novel_id=test_project_id, scale="sandbox", start=start, focus=""
    )
    return {
        "novel_id": test_project_id,
        "scale": "sandbox",
        "focus": "",
        "start": start.model_dump(mode="json"),
        "action": "story.exploration.sandbox.generate",
        "context_confirmation_id": str(uuid.uuid4()),
        "budget_preview_hash": hash_override or budget.preview_hash,
        "operation_id": str(operation_id),
    }


@pytest.mark.asyncio
async def test_start_enqueues_is_idempotent_and_persists_root(
    async_client, db_session, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    from infrastructure.tasks.models import AsyncTask

    start = _provisional_start()
    _stub_confirmation(monkeypatch, start)
    operation_id = uuid.uuid4()
    body = _start_body(test_project_id, start, operation_id=operation_id)

    first = await async_client.post("/api/story/exploration/start", json=body)
    assert first.status_code == 202, first.json()
    payload = first.json()
    assert payload["status"] == "pending"
    root_row = await db_session.get(
        StoryWorldProgressionRoot, uuid.UUID(payload["root_id"])
    )
    assert root_row is not None
    assert root_row.run_envelope_json
    assert root_row.current_task_id == uuid.UUID(payload["task_id"])
    task = await db_session.get(AsyncTask, uuid.UUID(payload["task_id"]))
    assert task.status == "pending"
    assert task.meta["exploration_root_id"] == payload["root_id"]
    assert task.meta["budget_preview_hash"] == body["budget_preview_hash"]

    again = await async_client.post("/api/story/exploration/start", json=body)
    assert again.status_code == 202
    assert again.json()["task_id"] == payload["task_id"]
    assert again.json()["root_id"] == payload["root_id"]


@pytest.mark.asyncio
async def test_start_rejects_stale_preview_hash_and_confirmation_mismatch(
    async_client, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    start = _provisional_start()
    _stub_confirmation(monkeypatch, start)

    stale_hash = await async_client.post(
        "/api/story/exploration/start",
        json=_start_body(
            test_project_id,
            start,
            operation_id=uuid.uuid4(),
            hash_override="0" * 64,
        ),
    )
    assert stale_hash.status_code == 409
    assert "重新预览预算" in stale_hash.json()["detail"]

    from modules.story import exploration_api

    async def mismatched_confirmation(db, *, novel_id, action, confirmation_id):
        return SimpleNamespace(
            compile_options={
                "exploration_start": start.model_dump(mode="json"),
                "exploration_scale": "event",
                "exploration_focus": "",
            }
        )

    monkeypatch.setattr(
        exploration_api, "require_fresh_confirmation", mismatched_confirmation
    )
    budget = preview_exploration_budget(
        novel_id=test_project_id, scale="sandbox", start=start, focus=""
    )
    mismatched = await async_client.post(
        "/api/story/exploration/start",
        json=_start_body(
            test_project_id,
            start,
            operation_id=uuid.uuid4(),
            hash_override=budget.preview_hash,
        ),
    )
    assert mismatched.status_code == 409
    assert "探索尺度" in mismatched.json()["detail"]


# ---------------------------------------------------------------------------
# detail / revise 路由契约
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revise_rejects_bad_path_and_unknown_entry(
    async_client, db_session, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    _root, _branch, step, _start = await _seed_sandbox_result(
        db_session, test_project_id
    )

    bad_format = await async_client.post(
        f"/api/story/exploration/results/{step.id}/revise",
        json={
            "novel_id": test_project_id,
            "operation_id": str(uuid.uuid4()),
            "item_path": "",
            "instruction": "改第一条",
        },
    )
    assert bad_format.status_code == 422

    unknown_entry = await async_client.post(
        f"/api/story/exploration/results/{step.id}/revise",
        json={
            "novel_id": test_project_id,
            "operation_id": str(uuid.uuid4()),
            "item_path": "chain:9",
            "instruction": "改第一条",
        },
    )
    assert unknown_entry.status_code == 409
    assert "可修订条目" in unknown_entry.json()["detail"]

    drifted = await async_client.post(
        f"/api/story/exploration/results/{step.id}/revise",
        json={
            "novel_id": test_project_id,
            "operation_id": str(uuid.uuid4()),
            "item_path": "chain:0",
            "item_text": "作者看到的是旧文案，已经对不上",
            "instruction": "改第一条",
        },
    )
    assert drifted.status_code == 409
    assert "内容已变化" in drifted.json()["detail"]


# ---------------------------------------------------------------------------
# save-edit：结构不匹配 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_edit_rejects_kind_mismatch(
    async_client, db_session, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    _root, _branch, step, _start = await _seed_sandbox_result(
        db_session, test_project_id
    )
    response = await async_client.post(
        f"/api/story/exploration/results/{step.id}/save-edit",
        json={
            "novel_id": test_project_id,
            "base_output_kind": "story.exploration.event",
            "edited_payload": {
                "mode": "diagnose",
                "original_excerpt": "面包师凌晨三点起床。",
                "gaps": [
                    {
                        "description": "缺少当天的订单量",
                        "why_needed": "订单量决定他是否加班",
                    }
                ],
            },
        },
    )
    assert response.status_code == 409
    assert "base_output_kind" in response.json()["detail"]


# ---------------------------------------------------------------------------
# history：平铺 items + novel 隔离
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_returns_flat_items_and_isolates_novel(
    async_client, db_session, test_project_id, project_factory, monkeypatch
):
    _enable_exploration(monkeypatch)
    _root, _branch, step, _start = await _seed_sandbox_result(
        db_session, test_project_id
    )
    other_project = str(await project_factory.create_project(title="另一本"))

    mine = await async_client.get(
        "/api/story/exploration/history", params={"novel_id": test_project_id}
    )
    assert mine.status_code == 200
    body = mine.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["result_id"] == str(step.id)
    assert item["chain"] == "progression"
    assert item["scale"] == "sandbox"
    assert item["output_kind"] == SANDBOX_OUTPUT_KIND
    assert item["payload"]["influence_chain"]

    others = await async_client.get(
        "/api/story/exploration/history", params={"novel_id": other_project}
    )
    assert others.status_code == 200
    assert others.json() == {"items": [], "total": 0}

    scoped = await async_client.get(
        "/api/story/exploration/history",
        params={"novel_id": test_project_id, "root_id": str(_root.id)},
    )
    assert scoped.status_code == 200
    assert scoped.json()["total"] == 1
