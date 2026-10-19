"""探索 API 层：推荐、gate 边界、start 幂等与守卫、比较与历史路由（P0 §6/§8）。"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from modules.account.settings_constants import LOCAL_OWNER_ID
from modules.evidence.contracts import Assumption, ProvisionalStart
from modules.story.exploration_budget import preview_exploration_budget
from modules.story.exploration_schemas import (
    EVENT_OUTPUT_KIND,
    SANDBOX_OUTPUT_KIND,
    SCENE_LINE_OUTPUT_KIND,
    EventOutputV1,
    ExplorationOutputEnvelope,
    SandboxOutputV1,
    apply_changed_assumptions,
    exploration_start_fingerprint,
    validate_start_dump,
)
from modules.story.exploration_service import (
    create_exploration_root,
    pack_exploration_output,
)
from modules.story.tests.exploration_test_support import full_rehearsal_card
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


def _event_envelope() -> ExplorationOutputEnvelope:
    return ExplorationOutputEnvelope(
        output_kind=EVENT_OUTPUT_KIND,
        schema_version=1,
        payload=EventOutputV1.model_validate(
            {
                "mode": "diagnose",
                "original_excerpt": "信使不知道地址，却当天把信送到了本人手里",
                "gaps": [
                    {
                        "description": "缺少信使获知收信人行踪的来源",
                        "why_needed": "解释为何能精准送达",
                    }
                ],
            }
        ),
    )


_ENVELOPE_BY_SCALE = {
    "sandbox": _sandbox_envelope,
    "event": _event_envelope,
}


async def _seed_sandbox_result(db_session, project_id, *, scale="sandbox"):
    from datetime import UTC, datetime, timedelta

    from infrastructure.llm.workflow_budget import new_ai_run_envelope

    start = _provisional_start()
    root, branch = await create_exploration_root(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        scale=scale,
        start=start,
        context_confirmation_id=str(uuid.uuid4()),
    )
    root.request_json = {
        **(root.request_json or {}),
        "exploration_scale": scale,
        "exploration_start_fingerprint": exploration_start_fingerprint(start, scale),
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
        result_json=pack_exploration_output(_ENVELOPE_BY_SCALE[scale]()),
        state_json={},
        metrics_json={"mode": "start", "exploration": True},
        basis_changed=False,
    )
    db_session.add(step)
    await db_session.flush()
    return root, branch, step, start


async def _add_progression_step(db_session, root, branch, *, input_json, step_number):
    """在同一分支上追加一条可定制的探索结果行（compare 反事实链测试用）。"""
    step = StoryWorldProgressionStep(
        novel_id=root.novel_id,
        root_id=root.id,
        branch_id=branch.id,
        step_number=step_number,
        source_hash=root.source_hash,
        input_hash="a" * 64,
        output_hash="b" * 64,
        input_json=input_json,
        result_json=pack_exploration_output(_sandbox_envelope()),
        state_json={},
        metrics_json={"mode": "start", "exploration": True},
        basis_changed=False,
    )
    db_session.add(step)
    await db_session.flush()
    return step


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
    assert body["budget"]["requests_max"] == 5
    assert body["budget"]["follow_up_max_requests"] == 5
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
    _root, _branch, step, _start = await _seed_sandbox_result(db_session, test_project_id)
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
@pytest.mark.parametrize(
    ("scale", "event_mode_hint", "action"),
    [
        ("sandbox", None, "story.exploration.sandbox.generate"),
        ("event", None, "story.exploration.event.diagnose"),
        ("event", "info_gap", "story.exploration.event.diagnose"),
        ("event", "goal", "story.exploration.event.bridge"),
    ],
)
async def test_confirmation_preview_and_confirm_round_trip(
    async_client, db_session, test_project_id, monkeypatch, scale, event_mode_hint, action
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
        "scale": scale,
        "focus": "",
        "start": start.model_dump(mode="json"),
    }
    if event_mode_hint:
        preview_body["event_mode_hint"] = event_mode_hint
    budget_preview = await async_client.post(
        "/api/story/exploration/preview", json=preview_body
    )
    assert budget_preview.status_code == 200, budget_preview.json()
    assert budget_preview.json()["action"] == action
    preview_body["action"] = budget_preview.json()["action"]
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
    assert seen["confirmed"].action == action

    _stub_confirmation(monkeypatch, start, scale=scale)
    started = await async_client.post(
        "/api/story/exploration/start",
        json={
            **preview_body,
            "context_confirmation_id": body["confirmation_id"],
            "budget_preview_hash": budget_preview.json()["budget"]["preview_hash"],
            "operation_id": str(uuid.uuid4()),
        },
    )
    assert started.status_code == 202, started.json()
    from infrastructure.tasks.models import AsyncTask

    task = await db_session.get(AsyncTask, uuid.UUID(started.json()["task_id"]))
    assert task.meta["action"] == action


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

    monkeypatch.setattr(exploration_api, "require_fresh_confirmation", fresh_confirmation)
    monkeypatch.setattr(exploration_api, "build_project_llm_execution_snapshot", snapshot)
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
    assert root_row.request_json["exploration_budget_policy_version"] == 2
    assert root_row.current_task_id == uuid.UUID(payload["task_id"])
    task = await db_session.get(AsyncTask, uuid.UUID(payload["task_id"]))
    assert task.status == "pending"
    assert task.meta["exploration_root_id"] == payload["root_id"]
    assert task.meta["budget_preview_hash"] == body["budget_preview_hash"]

    again = await async_client.post("/api/story/exploration/start", json=body)
    assert again.status_code == 202
    assert again.json()["task_id"] == payload["task_id"]
    assert again.json()["root_id"] == payload["root_id"]


async def test_new_start_rejects_legacy_budget_preview(
    async_client, test_project_id, monkeypatch
):
    from infrastructure.llm.collaboration import content_hash
    from modules.story.exploration_budget import exploration_preview_identity

    _enable_exploration(monkeypatch)
    start = _provisional_start()
    _stub_confirmation(monkeypatch, start)
    body = _start_body(test_project_id, start, operation_id=uuid.uuid4())
    body["budget_preview_hash"] = content_hash(
        exploration_preview_identity(
            novel_id=str(test_project_id),
            scale="sandbox",
            start=start,
            budget_policy_version=1,
        )
    )
    response = await async_client.post("/api/story/exploration/start", json=body)
    assert response.status_code == 409
    assert "重新预览预算" in response.json()["detail"]


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
    _root, _branch, step, _start = await _seed_sandbox_result(db_session, test_project_id)

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
    _root, _branch, step, _start = await _seed_sandbox_result(db_session, test_project_id)
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
    _root, _branch, step, _start = await _seed_sandbox_result(db_session, test_project_id)
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


# ---------------------------------------------------------------------------
# 反事实条件对照（M2 沙盘）：preview/start/compare
# ---------------------------------------------------------------------------


def _changed_assumptions() -> list[Assumption]:
    return [Assumption(kind="world_rule", text="重力变化时段从早晨改到傍晚")]


def _cloned_start() -> ProvisionalStart:
    return apply_changed_assumptions(_provisional_start(), _changed_assumptions())


def _cf_start_body(novel_id: str, baseline_id: str, *, hash_override=None):
    changed = _changed_assumptions()
    cloned = apply_changed_assumptions(_provisional_start(), changed)
    budget = preview_exploration_budget(
        novel_id=novel_id,
        scale="sandbox",
        start=cloned,
        counterfactual_of_result_id=baseline_id,
        changed_assumptions=changed,
    )
    return {
        "novel_id": novel_id,
        "scale": "sandbox",
        "focus": "",
        "start": None,
        "action": "story.exploration.sandbox.generate",
        "context_confirmation_id": str(uuid.uuid4()),
        "budget_preview_hash": hash_override or budget.preview_hash,
        "operation_id": str(uuid.uuid4()),
        "counterfactual_of_result_id": baseline_id,
        "changed_assumptions": [item.model_dump(mode="json") for item in changed],
    }


@pytest.mark.asyncio
async def test_counterfactual_preview_returns_derived_start_and_baseline_hash(
    async_client, db_session, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    _root, _branch, baseline, _start = await _seed_sandbox_result(
        db_session, test_project_id
    )
    response = await async_client.post(
        "/api/story/exploration/preview",
        json={
            "novel_id": test_project_id,
            "scale": "sandbox",
            "focus": "",
            "counterfactual_of_result_id": str(baseline.id),
            "changed_assumptions": [
                item.model_dump(mode="json") for item in _changed_assumptions()
            ],
        },
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    expected_start = _cloned_start()
    assert body["derived_start"] == expected_start.model_dump(mode="json")
    assert body["counterfactual_of_result_id"] == str(baseline.id)
    assert (
        body["budget"]["preview_hash"]
        == preview_exploration_budget(
            novel_id=test_project_id,
            scale="sandbox",
            start=expected_start,
            counterfactual_of_result_id=str(baseline.id),
            changed_assumptions=_changed_assumptions(),
        ).preview_hash
    )
    # 普通起点的预算身份不含基线，两者不同
    assert (
        body["budget"]["preview_hash"]
        != preview_exploration_budget(
            novel_id=test_project_id, scale="sandbox", start=expected_start
        ).preview_hash
    )


@pytest.mark.asyncio
async def test_counterfactual_start_rejects_missing_foreign_and_non_sandbox_baseline(
    async_client, db_session, test_project_id, project_factory, monkeypatch
):
    _enable_exploration(monkeypatch)
    _root, _branch, baseline, _start = await _seed_sandbox_result(
        db_session, test_project_id
    )
    other_project = str(await project_factory.create_project(title="另一本"))

    missing = await async_client.post(
        "/api/story/exploration/start",
        json=_cf_start_body(test_project_id, str(uuid.uuid4())),
    )
    assert missing.status_code == 404
    assert "探索结果不存在" in missing.json()["detail"]

    foreign = await async_client.post(
        "/api/story/exploration/start",
        json=_cf_start_body(other_project, str(baseline.id)),
    )
    assert foreign.status_code == 404

    _eroot, _ebranch, event_row, _estart = await _seed_sandbox_result(
        db_session, test_project_id, scale="event"
    )
    event_baseline = await async_client.post(
        "/api/story/exploration/start",
        json=_cf_start_body(test_project_id, str(event_row.id)),
    )
    assert event_baseline.status_code == 409
    assert "沙盘" in event_baseline.json()["detail"]


@pytest.mark.asyncio
async def test_counterfactual_start_clones_baseline_and_fails_closed_on_drift(
    async_client, db_session, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    _root, _branch, baseline, base_start = await _seed_sandbox_result(
        db_session, test_project_id
    )
    cloned = _cloned_start()
    _stub_confirmation(monkeypatch, cloned)
    response = await async_client.post(
        "/api/story/exploration/start",
        json=_cf_start_body(test_project_id, str(baseline.id)),
    )
    assert response.status_code == 202, response.json()
    payload = response.json()
    root_row = await db_session.get(
        StoryWorldProgressionRoot, uuid.UUID(payload["root_id"])
    )
    request_json = root_row.request_json
    assert request_json["exploration_start"] == cloned.model_dump(mode="json")
    assert request_json["exploration_start_fingerprint"] == (
        exploration_start_fingerprint(cloned, "sandbox")
    )
    assert request_json["counterfactual_of"] == str(baseline.id)
    assert request_json["changed_assumptions"] == [
        item.model_dump(mode="json") for item in _changed_assumptions()
    ]
    # 共同基底逐字保留，只改指定条件
    assert request_json["exploration_start"]["question"] == base_start.question
    assert request_json["exploration_start"]["time_basis"] == base_start.time_basis
    assert request_json["exploration_start"]["assumptions"] == [
        {"kind": "world_rule", "text": "重力变化时段从早晨改到傍晚"}
    ]

    # 确认冻结的是基线起点（未克隆）→ 失败关闭
    _stub_confirmation(monkeypatch, base_start)
    drifted_confirmation = await async_client.post(
        "/api/story/exploration/start",
        json=_cf_start_body(test_project_id, str(baseline.id)),
    )
    assert drifted_confirmation.status_code == 409
    assert "起点与本次请求不一致" in drifted_confirmation.json()["detail"]

    # 预算 hash 用普通身份（不含基线）重放 → 失败关闭
    _stub_confirmation(monkeypatch, cloned)
    plain_hash = preview_exploration_budget(
        novel_id=test_project_id, scale="sandbox", start=cloned
    ).preview_hash
    stale_hash = await async_client.post(
        "/api/story/exploration/start",
        json=_cf_start_body(test_project_id, str(baseline.id), hash_override=plain_hash),
    )
    assert stale_hash.status_code == 409
    assert "重新预览预算" in stale_hash.json()["detail"]


@pytest.mark.asyncio
async def test_compare_counterfactual_requires_link_and_returns_changed_conditions(
    async_client, db_session, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    root, branch, baseline, _start = await _seed_sandbox_result(
        db_session, test_project_id
    )
    variant = await _add_progression_step(
        db_session,
        root,
        branch,
        input_json={
            "mode": "start",
            "counterfactual_of": str(baseline.id),
            "changed_assumption_texts": ["重力变化时段从早晨改到傍晚"],
        },
        step_number=2,
    )
    other_root, other_branch, stranger, _stranger_start = await _seed_sandbox_result(
        db_session, test_project_id
    )

    def _compare(first, second, mode=None):
        body = {
            "novel_id": test_project_id,
            "first_result_id": str(first),
            "second_result_id": str(second),
        }
        if mode is not None:
            body["mode"] = mode
        return async_client.post("/api/story/exploration/compare", json=body)

    # 无反事实衍生关系的两行 → 409（不把两份无关长文当比较）
    unrelated = await _compare(baseline.id, stranger.id, mode="counterfactual")
    assert unrelated.status_code == 409
    assert "反事实衍生关系" in unrelated.json()["detail"]

    # same_start 模式行为不变：同根同指纹仍可比，不校验反事实链；
    # 两行无父子关系 → relation=same_start，无受影响项与父版本哈希
    legacy = await _compare(baseline.id, variant.id)
    assert legacy.status_code == 200
    assert legacy.json()["start_fingerprint"]
    assert "changed_conditions" not in legacy.json()
    assert legacy.json()["relation"] == "same_start"
    assert "affected_items" not in legacy.json()
    assert "parent_output_hash" not in legacy.json()["first"]

    # 基线 ↔ 衍生：changed_conditions 为衍生行文本；两侧 payload 同构相同
    # → 无受影响项，粒度如实标注 exact；衍生行回传记录的父版本哈希缺省 null
    derived = await _compare(baseline.id, variant.id, mode="counterfactual")
    assert derived.status_code == 200, derived.json()
    body = derived.json()
    assert body["mode"] == "counterfactual"
    assert body["start_fingerprint"] is None
    assert body["changed_conditions"] == ["重力变化时段从早晨改到傍晚"]
    assert body["affected_items"] == []
    assert body["affected_items_granularity"] == "exact"
    assert "relation" not in body
    assert body["first"]["parent_output_hash"] is None
    assert body["second"]["parent_output_hash"] is None

    # 共享基线：两条变体的对称差集（保持首现顺序）
    variant_a = await _add_progression_step(
        db_session,
        other_root,
        other_branch,
        input_json={
            "mode": "start",
            "counterfactual_of": str(baseline.id),
            "changed_assumption_texts": [
                "重力变化时段从早晨改到傍晚",
                "面包炉改为电炉",
            ],
        },
        step_number=2,
    )
    variant_b = await _add_progression_step(
        db_session,
        other_root,
        other_branch,
        input_json={
            "mode": "start",
            "counterfactual_of": str(baseline.id),
            "changed_assumption_texts": [
                "面包炉改为电炉",
                "城镇粮仓只够两周",
            ],
        },
        step_number=3,
    )
    shared = await _compare(variant_a.id, variant_b.id, mode="counterfactual")
    assert shared.status_code == 200, shared.json()
    assert shared.json()["changed_conditions"] == [
        "重力变化时段从早晨改到傍晚",
        "城镇粮仓只够两周",
    ]


# ---------------------------------------------------------------------------
# 事件信息差/导向（M2）：event_mode_hint 的尺度守卫、预算身份与根冻结
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_rejects_event_mode_hint_outside_event_scale(
    async_client, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    cross_scale = await async_client.post(
        "/api/story/exploration/preview",
        json={
            "novel_id": test_project_id,
            "scale": "sandbox",
            "event_mode_hint": "goal",
        },
    )
    assert cross_scale.status_code == 422
    assert "event_mode_hint" in str(cross_scale.json()["detail"])

    implicit_scale = await async_client.post(
        "/api/story/exploration/preview",
        json={"novel_id": test_project_id, "event_mode_hint": "info_gap"},
    )
    assert implicit_scale.status_code == 422

    ok = await async_client.post(
        "/api/story/exploration/preview",
        json={
            "novel_id": test_project_id,
            "scale": "event",
            "event_mode_hint": "goal",
        },
    )
    assert ok.status_code == 200, ok.json()
    assert ok.json()["recommended_scale"] == "event"


def _event_start_body(
    novel_id: str,
    start: ProvisionalStart,
    *,
    operation_id,
    event_mode_hint,
    hash_override=None,
):
    budget = preview_exploration_budget(
        novel_id=novel_id,
        scale="event",
        start=start,
        event_mode_hint=event_mode_hint,
    )
    body = {
        "novel_id": novel_id,
        "scale": "event",
        "focus": "",
        "start": start.model_dump(mode="json"),
        "action": (
            "story.exploration.event.diagnose"
            if event_mode_hint == "info_gap"
            else "story.exploration.event.bridge"
        ),
        "context_confirmation_id": str(uuid.uuid4()),
        "budget_preview_hash": hash_override or budget.preview_hash,
        "operation_id": str(operation_id),
    }
    if event_mode_hint is not None:
        body["event_mode_hint"] = event_mode_hint
    return body


@pytest.mark.asyncio
async def test_start_with_goal_hint_freezes_hint_and_binds_budget_hash(
    async_client, db_session, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    start = _provisional_start(question="信使怎么在不靠巧合的情况下当天送到？")
    _stub_confirmation(monkeypatch, start, scale="event")
    operation_id = uuid.uuid4()
    body = _event_start_body(
        test_project_id, start, operation_id=operation_id, event_mode_hint="goal"
    )
    response = await async_client.post("/api/story/exploration/start", json=body)
    assert response.status_code == 202, response.json()
    payload = response.json()
    root_row = await db_session.get(
        StoryWorldProgressionRoot, uuid.UUID(payload["root_id"])
    )
    assert root_row.request_json["event_mode_hint"] == "goal"

    # 不含 hint 的普通预算 hash 重放 → 409（预算身份含 hint）
    plain_hash = preview_exploration_budget(
        novel_id=test_project_id, scale="event", start=start
    ).preview_hash
    plain_replay = await async_client.post(
        "/api/story/exploration/start",
        json=_event_start_body(
            test_project_id,
            start,
            operation_id=uuid.uuid4(),
            event_mode_hint="goal",
            hash_override=plain_hash,
        ),
    )
    assert plain_replay.status_code == 409
    assert "重新预览预算" in plain_replay.json()["detail"]

    # 相同操作体重放幂等
    again = await async_client.post("/api/story/exploration/start", json=body)
    assert again.status_code == 202
    assert again.json()["task_id"] == payload["task_id"]


@pytest.mark.asyncio
async def test_start_rejects_hint_action_mismatch_before_enqueue(
    async_client, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    start = _provisional_start()
    _stub_confirmation(monkeypatch, start, scale="event")
    mismatched = await async_client.post(
        "/api/story/exploration/start",
        json={
            **_event_start_body(
                test_project_id,
                start,
                operation_id=uuid.uuid4(),
                event_mode_hint="goal",
            ),
            "action": "story.exploration.event.diagnose",
        },
    )
    assert mismatched.status_code == 422
    assert "event_mode_hint" in str(mismatched.json()["detail"])


def test_generation_action_keeps_goal_and_info_gap_on_event_actions():
    """goal 模式沿用 bridge 动作（复用 B2 链路），diagnose 保持 diagnose。"""
    from modules.story import exploration_api

    assert (
        exploration_api._generation_action(EVENT_OUTPUT_KIND, {"mode": "goal"})
        == exploration_api.EVENT_BRIDGE_ACTION
    )
    assert (
        exploration_api._generation_action(EVENT_OUTPUT_KIND, {"mode": "diagnose"})
        == exploration_api.EVENT_DIAGNOSE_ACTION
    )
    assert (
        exploration_api._generation_action(EVENT_OUTPUT_KIND, {"mode": "bridge"})
        == exploration_api.EVENT_BRIDGE_ACTION
    )


# ---------------------------------------------------------------------------
# 场景多目标与空间诊断（M2）：目标解析互斥、续算失败关闭
# ---------------------------------------------------------------------------


def _scene_start_data(**overrides):
    from modules.story.exploration_api import ExplorationStartApiRequest

    payload = {
        "novel_id": str(uuid.uuid4()),
        "scale": "scene_line",
        "action": "story.exploration.scene_line.generate",
        "start": {
            "kind": "provisional",
            "question": "雨夜站台，对方刚提完离职，各自会说什么？",
            "assumptions": [{"kind": "state", "text": "雨夜站台，两人共撑一伞"}],
            "candidates": [
                {"ref_id": "c_franks", "label": "坦率者", "role": "character"},
                {"ref_id": "c_evasive", "label": "回避者", "role": "character"},
            ],
            "time_basis": "assumed_now",
        },
        "context_confirmation_id": "ctx-m2",
        "budget_preview_hash": "f" * 64,
        "operation_id": str(uuid.uuid4()),
    }
    payload.update(overrides)
    return ExplorationStartApiRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({}, "多个可能目标"),
        ({"target_ref": "c_stranger"}, "不在本次探索"),
        (
            {"start": {"kind": "scene_anchor", "scene_id": str(uuid.uuid4())}},
            "正式角色 entity_id",
        ),
        (
            {
                "scale": "sandbox",
                "action": "story.exploration.sandbox.generate",
                "target_ref": "c_franks",
            },
            "只有场景一句对白",
        ),
        (
            {"target_ref": "c_franks", "multi_targets": ["c_franks", "c_evasive"]},
            "互斥",
        ),
        (
            {"target_ref": "c_franks", "diagnostic": {"question": "能从桌边走过吗？"}},
            "空间诊断",
        ),
        (
            {"target_ref": "c_franks", "full_rehearsal": {"targets": ["c_franks"]}},
            "互斥",
        ),
    ],
)
async def test_prepare_scene_start_rejects_target_before_confirmation(
    monkeypatch, overrides, message
):
    from app.assistant_operation_registry import story_exploration_operations
    from core.errors import ValidationError
    from modules.evidence import facade as evidence_facade
    from modules.story import exploration_operations

    _enable_exploration(monkeypatch)
    data = _scene_start_data(**overrides)
    operation = story_exploration_operations["story.exploration.start"]
    args = operation.schema.model_validate(
        data.model_dump(mode="json", exclude_none=True)
    )
    confirmations = []

    async def active(*_args):
        return None

    async def confirmation(_db, **kwargs):
        confirmations.append(kwargs)
        return SimpleNamespace(
            compile_options={
                "exploration_start": args.start,
                "exploration_scale": args.scale,
                "exploration_focus": args.focus,
            }
        )

    monkeypatch.setattr(exploration_operations, "require_active_project", active)
    monkeypatch.setattr(evidence_facade, "require_fresh_confirmation", confirmation)
    with pytest.raises(ValidationError, match=message):
        await operation.prepare(None, data.novel_id, args)
    assert confirmations == []


@pytest.mark.parametrize(
    "mode",
    [
        "explicit",
        "single_candidate",
        "single_canonical",
        "scene_anchor",
        "diagnostic",
        "multi",
        "full",
    ],
)
async def test_prepare_scene_start_accepts_supported_target_modes(monkeypatch, mode):
    from app.assistant_operation_registry import story_exploration_operations
    from modules.evidence import facade as evidence_facade
    from modules.story import exploration_operations

    _enable_exploration(monkeypatch)
    payload = _scene_start_data().model_dump(mode="json", exclude_none=True)
    if mode == "explicit":
        payload["target_ref"] = "c_franks"
    elif mode == "single_candidate":
        payload["start"]["candidates"] = payload["start"]["candidates"][:1]
    elif mode == "single_canonical":
        payload["start"]["candidates"] = []
        payload["start"]["canonical_refs"] = [str(uuid.uuid4())]
    elif mode == "scene_anchor":
        payload["start"] = {"kind": "scene_anchor", "scene_id": str(uuid.uuid4())}
        payload["target_ref"] = str(uuid.uuid4())
    elif mode == "diagnostic":
        payload["diagnostic"] = {
            "question": "能从桌边走过吗？",
            "subject_ref": "c_franks",
        }
    elif mode == "multi":
        payload["multi_targets"] = ["c_franks", "c_evasive"]
    else:
        payload["full_rehearsal"] = {"targets": ["c_franks", "c_evasive"]}
    operation = story_exploration_operations["story.exploration.start"]
    args = operation.schema.model_validate(payload)
    args.budget_preview_hash = preview_exploration_budget(
        novel_id=args.novel_id,
        scale=args.scale,
        start=validate_start_dump(args.start),
        focus=args.focus,
        event_mode_hint=args.event_mode_hint,
        multi_targets=args.multi_targets,
        diagnostic_question=args.diagnostic.question if args.diagnostic else None,
        full_rehearsal=args.full_rehearsal,
    ).preview_hash
    confirmations = []

    async def active(*_args):
        return None

    async def confirmation(_db, **kwargs):
        confirmations.append(kwargs)
        return SimpleNamespace(
            compile_options={
                "exploration_start": args.start,
                "exploration_scale": args.scale,
                "exploration_focus": args.focus,
            }
        )

    monkeypatch.setattr(exploration_operations, "require_active_project", active)
    monkeypatch.setattr(evidence_facade, "require_fresh_confirmation", confirmation)
    preview = await operation.prepare(None, payload["novel_id"], args)
    assert preview["confirmed"] is True
    assert len(confirmations) == 1
    assert confirmations[0]["novel_id"] == payload["novel_id"]
    expected_target = (
        "c_franks"
        if mode in {"explicit", "single_candidate"}
        else payload["start"]["canonical_refs"][0]
        if mode == "single_canonical"
        else payload["target_ref"]
        if mode == "scene_anchor"
        else None
    )
    from modules.story.exploration_api import (
        ExplorationStartApiRequest,
        _resolve_scene_target,
    )

    assert _resolve_scene_target(args) == expected_target
    assert (
        _resolve_scene_target(ExplorationStartApiRequest.model_validate(payload))
        == expected_target
    )


@pytest.mark.parametrize(
    "mismatch",
    [
        "confirmation_start",
        "confirmation_scale",
        "confirmation_focus",
        "budget_hash",
        "intent",
    ],
)
async def test_prepare_start_rejects_known_preflight_errors(monkeypatch, mismatch):
    from app.assistant_operation_registry import story_exploration_operations
    from core.errors import ValidationError
    from modules.evidence import facade as evidence_facade
    from modules.story import exploration_operations

    _enable_exploration(monkeypatch)
    start = _provisional_start()
    body = _start_body(str(uuid.uuid4()), start, operation_id=uuid.uuid4())
    operation = story_exploration_operations["story.exploration.start"]
    args = operation.schema.model_validate(body)
    options = {
        "exploration_start": start.model_dump(mode="json"),
        "exploration_scale": args.scale,
        "exploration_focus": args.focus,
    }
    context = None
    if mismatch == "confirmation_start":
        options["exploration_start"]["question"] = "另一个已确认的问题"
    elif mismatch == "confirmation_scale":
        options["exploration_scale"] = "event"
    elif mismatch == "confirmation_focus":
        options["exploration_focus"] = "另一个已确认的焦点"
    elif mismatch == "budget_hash":
        args.budget_preview_hash = "f" * 64
    else:
        context = SimpleNamespace(
            work=SimpleNamespace(
                exploration_intent=SimpleNamespace(
                    scale="event", focus=args.focus, question=""
                )
            )
        )
    confirmations = []

    async def active(*_args):
        return None

    async def confirmation(_db, **kwargs):
        confirmations.append(kwargs)
        return SimpleNamespace(compile_options=options)

    monkeypatch.setattr(exploration_operations, "require_active_project", active)
    monkeypatch.setattr(evidence_facade, "require_fresh_confirmation", confirmation)
    with pytest.raises(ValidationError):
        await operation.prepare(None, args.novel_id, args, context=context)
    assert len(confirmations) == (0 if mismatch == "intent" else 1)


def test_resolve_scene_target_rejects_multi_with_target_ref():
    """multi_targets 与 target_ref 互斥；目标必须落在候选/正式角色内。"""
    from modules.story.exploration_api import _resolve_scene_target

    data = _scene_start_data(
        target_ref="c_franks", multi_targets=["c_franks", "c_evasive"]
    )
    with pytest.raises(ValueError, match="互斥"):
        _resolve_scene_target(data)
    # 多目标成员越界拒绝
    outside = _scene_start_data(multi_targets=["c_franks", "c_stranger"])
    with pytest.raises(ValueError, match="不在本次探索"):
        _resolve_scene_target(outside)
    # 合法多目标：无单目标锁定
    ok = _scene_start_data(multi_targets=["c_franks", "c_evasive"])
    assert _resolve_scene_target(ok) is None


def test_resolve_scene_target_rejects_diagnostic_with_target_ref():
    from modules.story.exploration_api import _resolve_scene_target

    data = _scene_start_data(
        target_ref="c_franks",
        diagnostic={"question": "醉汉能一步从大门跨到桌边吗？"},
    )
    with pytest.raises(ValueError, match="空间诊断"):
        _resolve_scene_target(data)
    ok = _scene_start_data(
        diagnostic={
            "question": "醉汉能一步从大门跨到桌边吗？",
            "subject_ref": "c_franks",
        }
    )
    assert _resolve_scene_target(ok) is None
    outside = _scene_start_data(
        diagnostic={
            "question": "醉汉能一步从大门跨到桌边吗？",
            "subject_ref": "c_stranger",
        }
    )
    with pytest.raises(ValueError, match="不在本次探索"):
        _resolve_scene_target(outside)


def test_scene_follow_up_accepts_variants_and_diagnostic_results():
    """多目标/空间诊断结果不接受“说详细点”或局部修订：尽早失败关闭。"""
    from modules.story.exploration_api import require_scene_follow_up_supported
    from modules.story.exploration_schemas import (
        ExplorationOutputEnvelope,
        SceneLineOutputV1,
        SpatialAssessment,
    )

    variants_payload = SceneLineOutputV1.model_validate(
        {
            "rationale": "分别生成。",
            "variants": [
                {"target_ref": "c_a", "line": "好", "rationale": "r"},
                {"target_ref": "c_b", "line": "嗯", "rationale": "r"},
            ],
        }
    )
    require_scene_follow_up_supported(
        ExplorationOutputEnvelope(
            output_kind=SCENE_LINE_OUTPUT_KIND,
            schema_version=1,
            payload=variants_payload,
        )
    )
    diagnostic_payload = SceneLineOutputV1.model_validate(
        {
            "rationale": "空间诊断。",
            "spatial_assessment": SpatialAssessment(supported=None),
        }
    )
    require_scene_follow_up_supported(
        ExplorationOutputEnvelope(
            output_kind=SCENE_LINE_OUTPUT_KIND,
            schema_version=1,
            payload=diagnostic_payload,
        )
    )
    # 普通单目标结果不受影响
    single = SceneLineOutputV1.model_validate(
        {"target_ref": "c_a", "line": "好", "rationale": "r"}
    )
    require_scene_follow_up_supported(
        ExplorationOutputEnvelope(
            output_kind=SCENE_LINE_OUTPUT_KIND, schema_version=1, payload=single
        )
    )

    from modules.story.exploration_schemas import revision_items

    assert [
        item["key"]
        for item in revision_items(
            variants_payload.model_dump(mode="json"), SCENE_LINE_OUTPUT_KIND
        )
    ] == ["variant:0", "variant:1"]
    assert (
        revision_items(
            diagnostic_payload.model_dump(mode="json"), SCENE_LINE_OUTPUT_KIND
        )[0]["key"]
        == "spatial"
    )


def test_full_rehearsal_result_supports_typed_follow_up_and_lock():
    """完整排演结果（M3-B）不接受增量修订也不可锁定单条目：失败关闭。"""
    from modules.story.exploration_api import require_scene_follow_up_supported
    from modules.story.exploration_schemas import (
        FULL_REHEARSAL_OUTPUT_KIND,
        FullRehearsalOutputV1,
    )

    payload = FullRehearsalOutputV1.model_validate(
        {
            "targets": ["c_a", "c_b"],
            "rounds": [
                {
                    "round_number": 1,
                    "performances": [
                        full_rehearsal_card("c_a"),
                        full_rehearsal_card("c_b"),
                    ],
                }
            ],
        }
    )
    require_scene_follow_up_supported(
        ExplorationOutputEnvelope(
            output_kind=FULL_REHEARSAL_OUTPUT_KIND,
            schema_version=1,
            payload=payload,
        )
    )

    from modules.story.exploration_schemas import revision_items

    assert [
        item["key"]
        for item in revision_items(
            payload.model_dump(mode="json"), FULL_REHEARSAL_OUTPUT_KIND
        )
    ] == ["performance:0:0", "performance:0:1"]


# ---------------------------------------------------------------------------
# 临时起点完整排演（M3-B）：结果行的 detail/revise/save-edit/lock 全部 409
# ---------------------------------------------------------------------------


async def _seed_full_rehearsal_result(db_session, project_id):
    """落一条完整排演结果行（scene 链）：根冻结排演意图 + 一轮表演卡。"""
    from datetime import UTC, datetime, timedelta

    from infrastructure.llm.workflow_budget import new_ai_run_envelope
    from modules.story.exploration_schemas import (
        FULL_REHEARSAL_OUTPUT_KIND,
        FullRehearsalMaterial,
        FullRehearsalObservation,
        FullRehearsalOutputV1,
        FullRehearsalPerformance,
        FullRehearsalRequest,
        FullRehearsalRound,
    )
    from modules.story.models import StorySceneDirectorRound

    start = ProvisionalStart.model_validate(_rehearsal_start())
    rehearsal = FullRehearsalRequest(
        targets=["c_franks", "c_evasive"], rounds=1, author_goal="看立场差异"
    )
    root, branch = await create_exploration_root(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        scale="scene_line",
        start=start,
        full_rehearsal=rehearsal,
    )
    started_at = datetime.now(UTC)
    envelope = new_ai_run_envelope(
        operation_id=str(uuid.uuid4()),
        run_id=str(root.id),
        root_capability_id="story.exploration",
        novel_id=str(project_id),
        request_limit=2,
        budget_mode="bounded",
        token_limit=200_000,
        started_at=started_at,
        deadline_at=started_at + timedelta(hours=1),
    )
    root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
    output = ExplorationOutputEnvelope(
        output_kind=FULL_REHEARSAL_OUTPUT_KIND,
        schema_version=1,
        payload=FullRehearsalOutputV1(
            targets=["c_franks", "c_evasive"],
            rounds=[
                FullRehearsalRound(
                    round_number=1,
                    performances=[
                        FullRehearsalPerformance.model_validate(
                            full_rehearsal_card("c_franks")
                        ),
                        FullRehearsalPerformance.model_validate(
                            full_rehearsal_card("c_evasive")
                        ),
                    ],
                    materials=[
                        FullRehearsalMaterial(
                            kind="environment",
                            text="雨夜站台灯光昏黄。",
                            perceiver_refs=["c_franks", "c_evasive"],
                        )
                    ],
                    observations=[
                        FullRehearsalObservation(
                            target_ref="c_franks", observed="对方握紧了伞柄。"
                        )
                    ],
                )
            ],
            state_notes=["第1轮：双方立场未变。"],
        ),
    )
    row = StorySceneDirectorRound(
        novel_id=root.novel_id,
        root_id=root.id,
        branch_id=branch.id,
        round_number=1,
        parent_round_id=None,
        source_hash=branch.source_hash,
        input_hash="a" * 64,
        output_hash="b" * 64,
        input_json={
            "mode": "full_rehearsal",
            "targets": ["c_franks", "c_evasive"],
            "rounds": 1,
        },
        output_json=pack_exploration_output(output),
        state_json={},
        run_envelope_json={},
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_full_rehearsal_invalid_confirmation_path_and_shape_fail_closed(
    async_client, db_session, test_project_id, monkeypatch
):
    """完整排演结果的 detail/revise/lock 一律 409；save-edit 因 kind 并集拒绝。"""
    _enable_exploration(monkeypatch)
    row = await _seed_full_rehearsal_result(db_session, test_project_id)

    detail = await async_client.post(
        f"/api/story/exploration/results/{row.id}/detail",
        json={
            "novel_id": test_project_id,
            "operation_id": str(uuid.uuid4()),
            "focus": "第二轮更细",
        },
    )
    assert detail.status_code == 409
    assert "缺少可复用的资料确认" in detail.json()["detail"]

    revise = await async_client.post(
        f"/api/story/exploration/results/{row.id}/revise",
        json={
            "novel_id": test_project_id,
            "operation_id": str(uuid.uuid4()),
            "item_path": "rounds:0",
            "instruction": "改第一轮的基调",
        },
    )
    assert revise.status_code == 409
    assert "修订路径" in revise.json()["detail"]

    lock = await async_client.post(
        f"/api/story/exploration/results/{row.id}/lock",
        json={
            "novel_id": test_project_id,
            "operation_id": str(uuid.uuid4()),
            "lock": True,
            "item_path": "rounds:0",
        },
    )
    assert lock.status_code == 409
    assert "修订路径" in lock.json()["detail"]

    save_edit = await async_client.post(
        f"/api/story/exploration/results/{row.id}/save-edit",
        json={
            "novel_id": test_project_id,
            "base_output_kind": "story.exploration.scene_line",
            "edited_payload": {
                "target_ref": "c_franks",
                "line": "作者手改的一句",
                "rationale": "作者编辑",
            },
        },
    )
    assert save_edit.status_code == 409
    assert "base_output_kind" in save_edit.json()["detail"]

    # base_output_kind 并集保持不含 full_rehearsal：直接声明排演 kind → 422
    rehearsal_kind = await async_client.post(
        f"/api/story/exploration/results/{row.id}/save-edit",
        json={
            "novel_id": test_project_id,
            "base_output_kind": "story.exploration.full_rehearsal",
            "edited_payload": {"targets": ["c_franks"], "rounds": []},
        },
    )
    assert rehearsal_kind.status_code == 422


# ---------------------------------------------------------------------------
# 临时起点完整排演（M3-B）：预览披露、资格拒绝与启动冻结
# ---------------------------------------------------------------------------


def _rehearsal_start(**overrides):
    """带可知包的临时起点：两个候选各有一条 knows，另含一条正式角色引用。"""
    payload = {
        "kind": "provisional",
        "question": "雨夜站台，对方刚提完离职，各自会说什么？",
        "assumptions": [{"kind": "state", "text": "雨夜站台，两人共撑一伞"}],
        "candidates": [
            {"ref_id": "c_franks", "label": "坦率者", "role": "character"},
            {"ref_id": "c_evasive", "label": "回避者", "role": "character"},
        ],
        "knowledge": [
            {"subject_ref": "c_franks", "knows": ["对方今天提了离职"]},
            {"subject_ref": "c_evasive", "knows": ["站台风很大"]},
        ],
        "time_basis": "assumed_now",
    }
    payload.update(overrides)
    return payload


def _full_rehearsal_start_body(
    test_project_id: str,
    start,
    *,
    operation_id,
    targets=("c_franks", "c_evasive"),
    rounds=2,
    author_goal="看两人对离职话题的不同反应",
    hash_override=None,
):
    from modules.story.exploration_schemas import FullRehearsalRequest

    rehearsal = FullRehearsalRequest(
        targets=list(targets), rounds=rounds, author_goal=author_goal
    )
    budget = preview_exploration_budget(
        novel_id=test_project_id,
        scale="scene_line",
        start=start,
        focus="",
        full_rehearsal=rehearsal,
    )
    return {
        "novel_id": test_project_id,
        "scale": "scene_line",
        "focus": "",
        "action": "story.exploration.scene_line.generate",
        "start": start.model_dump(mode="json"),
        "context_confirmation_id": str(uuid.uuid4()),
        "budget_preview_hash": hash_override or budget.preview_hash,
        "operation_id": str(operation_id),
        "full_rehearsal": rehearsal.model_dump(mode="json"),
    }


@pytest.mark.asyncio
async def test_preview_full_rehearsal_discloses_work_steps_and_budget(
    async_client, test_project_id, monkeypatch
):
    """完整排演预览：披露与聚焦不同的工作步骤，预算按 (N+1)×轮次 分开计量。"""
    _enable_exploration(monkeypatch)
    response = await async_client.post(
        "/api/story/exploration/preview",
        json={
            "novel_id": test_project_id,
            "preview_full_rehearsal": {"targets": ["c_franks", "c_evasive"], "rounds": 2},
        },
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["recommended_scale"] == "scene_line"
    assert (body["budget"]["requests_min"], body["budget"]["requests_max"]) == (18, 30)
    work_steps = "\n".join(body["work_steps"])
    assert "逐目标表演卡 ×2/轮" in work_steps
    assert "素材与观察统筹 ×1/轮" in work_steps
    assert "预计 18–30 次模型请求" in work_steps
    assert body["full_rehearsal"] == {
        "targets": ["c_franks", "c_evasive"],
        "rounds": 2,
        "author_goal": "",
    }
    assert "30 次" in body["possible_charge"]
    # 聚焦预览不带 work_steps
    plain = await async_client.post(
        "/api/story/exploration/preview", json={"novel_id": test_project_id}
    )
    assert plain.status_code == 200
    assert "work_steps" not in plain.json()


@pytest.mark.asyncio
async def test_preview_full_rehearsal_rejects_conflicting_modes(
    async_client, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    with_multi = await async_client.post(
        "/api/story/exploration/preview",
        json={
            "novel_id": test_project_id,
            "multi_targets": ["c_a", "c_b"],
            "preview_full_rehearsal": {"targets": ["c_a"], "rounds": 1},
        },
    )
    assert with_multi.status_code == 422
    cross_scale = await async_client.post(
        "/api/story/exploration/preview",
        json={
            "novel_id": test_project_id,
            "scale": "sandbox",
            "preview_full_rehearsal": {"targets": ["c_a"], "rounds": 1},
        },
    )
    assert cross_scale.status_code == 422


@pytest.mark.asyncio
async def test_start_full_rehearsal_rejects_scene_anchor_start(
    async_client, test_project_id, monkeypatch
):
    """完整排演仅临时起点：场景锚点起点显式展开 → 409。"""
    _enable_exploration(monkeypatch)
    from modules.evidence.contracts import SceneAnchorStart

    start = SceneAnchorStart(kind="scene_anchor", scene_id=str(uuid.uuid4()))
    body = _full_rehearsal_start_body(test_project_id, start, operation_id=uuid.uuid4())
    response = await async_client.post("/api/story/exploration/start", json=body)
    assert response.status_code == 409
    assert "临时假设起点" in response.json()["detail"]


@pytest.mark.asyncio
async def test_start_full_rehearsal_canonical_target_missing_is_404(
    async_client, test_project_id, monkeypatch
):
    """目标正式角色不存在/非本作品：确认与启动前 404，不产生任何模型请求。"""
    _enable_exploration(monkeypatch)
    # 目标已声明进起点 canonical_refs（通过归属校验），但库里无此角色 → 404
    ghost = str(uuid.uuid4())
    start = _rehearsal_start(canonical_refs=[ghost])
    body = _full_rehearsal_start_body(
        test_project_id,
        ProvisionalStart.model_validate(start),
        operation_id=uuid.uuid4(),
        targets=(ghost,),
    )
    response = await async_client.post("/api/story/exploration/start", json=body)
    assert response.status_code == 404
    assert "不存在" in response.json()["detail"]


@pytest.mark.asyncio
async def test_start_full_rehearsal_without_knowledge_or_assumption_is_409(
    async_client, test_project_id, monkeypatch
):
    """候选没有可知包也没有身份假设：能力不足 409，紧凑聚焦路径不受影响。"""
    _enable_exploration(monkeypatch)
    start = _rehearsal_start(
        assumptions=[{"kind": "world_rule", "text": "雨夜站台"}],
        knowledge=[],
    )
    body = _full_rehearsal_start_body(
        test_project_id,
        ProvisionalStart.model_validate(start),
        operation_id=uuid.uuid4(),
    )
    response = await async_client.post("/api/story/exploration/start", json=body)
    assert response.status_code == 409
    assert "能力不足" in response.json()["detail"]

    # 有身份假设即可展开（无需可知包）：模型校验通过，资格校验不再拒绝
    with_identity = _rehearsal_start(
        knowledge=[],
        assumptions=[{"kind": "identity", "text": "坦率者习惯当面把话说开"}],
    )
    _stub_confirmation(
        monkeypatch,
        ProvisionalStart.model_validate(with_identity),
        scale="scene_line",
    )
    ok_body = _full_rehearsal_start_body(
        test_project_id,
        ProvisionalStart.model_validate(with_identity),
        operation_id=uuid.uuid4(),
        rounds=1,
    )
    ok = await async_client.post("/api/story/exploration/start", json=ok_body)
    assert ok.status_code == 202, ok.json()


@pytest.mark.asyncio
async def test_start_full_rehearsal_membership_violation_is_409(
    async_client, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    start = ProvisionalStart.model_validate(_rehearsal_start())
    body = _full_rehearsal_start_body(
        test_project_id,
        start,
        operation_id=uuid.uuid4(),
        targets=("c_franks", "c_stranger"),
    )
    response = await async_client.post("/api/story/exploration/start", json=body)
    assert response.status_code == 409
    assert "不在本次探索" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("author_goal", ["", "看两人对离职话题的不同反应"])
async def test_start_full_rehearsal_enqueues_with_frozen_rehearsal_and_budget(
    async_client, db_session, test_project_id, monkeypatch, author_goal
):
    """合法排演启动：根/任务冻结排演意图，预算信封按 (N+1)×轮次 授权。"""
    _enable_exploration(monkeypatch)
    from infrastructure.tasks.models import AsyncTask
    from modules.story.models import StorySceneDirectorRoot

    start = ProvisionalStart.model_validate(_rehearsal_start())
    _stub_confirmation(monkeypatch, start, scale="scene_line")
    body = _full_rehearsal_start_body(
        test_project_id,
        start,
        operation_id=uuid.uuid4(),
        rounds=2,
        author_goal=author_goal,
    )
    preview = await async_client.post(
        "/api/story/exploration/preview",
        json={
            "novel_id": test_project_id,
            "scale": "scene_line",
            "start": body["start"],
            "preview_full_rehearsal": body["full_rehearsal"],
        },
    )
    assert preview.status_code == 200, preview.json()
    body["budget_preview_hash"] = preview.json()["budget"]["preview_hash"]

    response = await async_client.post("/api/story/exploration/start", json=body)
    assert response.status_code == 202, response.json()
    payload = response.json()
    root_row = await db_session.get(StorySceneDirectorRoot, uuid.UUID(payload["root_id"]))
    assert root_row is not None
    # 排演意图冻结进根 request_json，worker 执行切片读取同一载荷
    assert root_row.request_json["full_rehearsal"] == {
        "targets": ["c_franks", "c_evasive"],
        "rounds": 2,
        "author_goal": author_goal,
    }
    envelope = root_row.run_envelope_json
    assert envelope["request_limit"] == (2 + 1) * 2 * 5
    task = await db_session.get(AsyncTask, uuid.UUID(payload["task_id"]))
    assert task.meta["request"]["full_rehearsal"]["rounds"] == 2
    assert task.meta["exploration_authorized_requests"] == 30
    assert task.meta["action"] == "story.exploration.scene_line.generate"

    # 幂等：同 operation 重放返回同一任务
    again = await async_client.post("/api/story/exploration/start", json=body)
    assert again.status_code == 202
    assert again.json()["task_id"] == payload["task_id"]


@pytest.mark.asyncio
async def test_start_full_rehearsal_rejects_target_ref_and_stale_hash(
    async_client, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    start = ProvisionalStart.model_validate(_rehearsal_start())
    _stub_confirmation(monkeypatch, start, scale="scene_line")
    body = _full_rehearsal_start_body(test_project_id, start, operation_id=uuid.uuid4())
    body["target_ref"] = "c_franks"
    conflict = await async_client.post("/api/story/exploration/start", json=body)
    assert conflict.status_code == 400
    assert "互斥" in conflict.json()["detail"]

    stale = _full_rehearsal_start_body(
        test_project_id,
        start,
        operation_id=uuid.uuid4(),
        hash_override="0" * 64,
    )
    stale_response = await async_client.post("/api/story/exploration/start", json=stale)
    assert stale_response.status_code == 409
    assert "重新预览预算" in stale_response.json()["detail"]
