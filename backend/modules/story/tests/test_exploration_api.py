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
    assert body["budget"]["preview_hash"] == preview_exploration_budget(
        novel_id=test_project_id,
        scale="sandbox",
        start=expected_start,
        counterfactual_of_result_id=str(baseline.id),
        changed_assumptions=_changed_assumptions(),
    ).preview_hash
    # 普通起点的预算身份不含基线，两者不同
    assert body["budget"]["preview_hash"] != preview_exploration_budget(
        novel_id=test_project_id, scale="sandbox", start=expected_start
    ).preview_hash


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


def test_scene_follow_up_blocked_for_variants_and_diagnostic_results():
    """多目标/空间诊断结果不接受“说详细点”或局部修订：尽早失败关闭。"""
    from core.errors import ConflictError
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
    with pytest.raises(ConflictError):
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
    with pytest.raises(ConflictError):
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
