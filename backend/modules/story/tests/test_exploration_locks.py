"""满意内容锁定（M3-A 切片 1）：lock_set 行、锁定遵守、比较与历史契约。

冻结契约（P0-M3A §1-§6）：锁定承载 = 特殊结果行（output_kind=
story.exploration.lock_set）；当前锁定集取分支最新 lock_set 行；修订/作者
编辑遵守锁定；lock_set 不参与比较与历史 AI 列表（过滤方案，测试钉住）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from modules.account.settings_constants import LOCAL_OWNER_ID
from modules.evidence.contracts import Assumption, ProvisionalStart, SceneAnchorStart
from modules.story.exploration_schemas import (
    LOCK_SET_OUTPUT_KIND,
    SANDBOX_OUTPUT_KIND,
    SCENE_LINE_OUTPUT_KIND,
    ExplorationOutputEnvelope,
    SandboxOutputV1,
    SceneLineOutputV1,
)
from modules.story.exploration_service import (
    compare_exploration_results,
    create_exploration_root,
    current_locked_items,
    pack_exploration_output,
    save_exploration_author_edit,
    set_exploration_item_lock,
)
from modules.story.models import StorySceneDirectorRound
from modules.story.world_progression_models import StoryWorldProgressionStep

OWNER_ID = str(LOCAL_OWNER_ID)
_QUESTION = "这个城镇每天只有一小时重力减半，面包师的一天会怎样？"


@pytest.fixture(autouse=True)
def _exploration_gate_off_by_default(monkeypatch):
    from core.config import get_settings

    monkeypatch.setenv("STORY_EXPLORATION_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _enable_exploration(monkeypatch):
    from core.config import get_settings

    monkeypatch.setenv("STORY_EXPLORATION_ENABLED", "true")
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
                    },
                    {
                        "condition": "出炉提前",
                        "mechanism": "清晨顾客变多",
                        "effect": "面包师更累",
                    },
                ],
            }
        ),
    )


def _chain_items(envelope: ExplorationOutputEnvelope) -> list[dict]:
    return envelope.payload.model_dump(mode="json")["influence_chain"]


async def _seed_sandbox_result(db_session, project_id):
    """带两环影响链的沙盘结果；分支携带可复用的确认字段（修订 202 用）。"""
    from datetime import UTC, datetime, timedelta

    from infrastructure.llm.workflow_budget import new_ai_run_envelope

    start = _provisional_start()
    root, branch = await create_exploration_root(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        scale="sandbox",
        start=start,
        context_confirmation_id=str(uuid.uuid4()),
        branch_request_json={
            "context_confirmation_id": "ctx-lock-" + str(uuid.uuid4()),
            "confirmation_action": "story.exploration.sandbox.generate",
        },
    )
    started_at = datetime.now(UTC)
    envelope = new_ai_run_envelope(
        operation_id=str(uuid.uuid4()),
        run_id=str(root.id),
        root_capability_id="story.exploration",
        novel_id=str(project_id),
        request_limit=3,
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
    return root, branch, step


async def _seed_scene_line_result(db_session, project_id):
    start = SceneAnchorStart(kind="scene_anchor", scene_id=str(uuid.uuid4()))
    root, branch = await create_exploration_root(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        scale="scene_line",
        start=start,
    )
    envelope = ExplorationOutputEnvelope(
        output_kind=SCENE_LINE_OUTPUT_KIND,
        schema_version=1,
        payload=SceneLineOutputV1.model_validate(
            {
                "target_ref": "c_b",
                "line": "你要是累了就先回去吧。",
                "rationale": "B 只看见 A 疲惫。",
            }
        ),
    )
    row = StorySceneDirectorRound(
        novel_id=root.novel_id,
        root_id=root.id,
        branch_id=branch.id,
        round_number=1,
        source_hash=root.source_hash,
        input_hash="c" * 64,
        output_hash="d" * 64,
        input_json={"mode": "start"},
        output_json=pack_exploration_output(envelope),
        state_json={},
        run_envelope_json={},
    )
    db_session.add(row)
    await db_session.flush()
    return root, branch, row, envelope


def _lock_body(project_id: str, *, lock: bool, item_path: str, **extra) -> dict:
    return {
        "novel_id": str(project_id),
        "operation_id": str(uuid.uuid4()),
        "lock": lock,
        "item_path": item_path,
        **extra,
    }


def _stub_follow_up_confirmation(monkeypatch):
    """修订 202 需要的确认与回执桩：锁定预检发生在这些依赖之前。"""
    from modules.story import exploration_api

    async def fresh_confirmation(db, *, novel_id, action, confirmation_id):
        return SimpleNamespace(compile_options={})

    async def attach_ref(
        db, *, novel_id, confirmation_id, result_type, result_id, status
    ):
        return None

    monkeypatch.setattr(exploration_api, "require_fresh_confirmation", fresh_confirmation)
    monkeypatch.setattr(exploration_api, "attach_result_ref", attach_ref)


# ---------------------------------------------------------------------------
# lock 端点：lock_set 行生成、追加/解除、幂等与失败关闭
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lock_creates_lock_set_row_and_repeats_idempotently(
    async_client, db_session, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    _root, _branch, step = await _seed_sandbox_result(db_session, test_project_id)
    effect = _chain_items(_sandbox_envelope())[0]["effect"]

    body = _lock_body(test_project_id, lock=True, item_path="chain:0", item_text=effect)
    first = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock", json=body
    )
    assert first.status_code == 200, first.json()
    payload = first.json()
    assert payload["output_kind"] == LOCK_SET_OUTPUT_KIND
    assert payload["locked_items"] == ["chain:0"]
    locked_item = payload["payload"]["locked_items"][0]
    assert locked_item["item_path"] == "chain:0"
    assert len(locked_item["item_content_hash"]) == 64
    assert locked_item["label"] == effect

    rows = (
        await db_session.scalars(
            select(StoryWorldProgressionStep).where(
                StoryWorldProgressionStep.root_id == _root.id
            )
        )
    ).all()
    lock_rows = [row for row in rows if row.id != step.id]
    assert len(lock_rows) == 1
    lock_row = lock_rows[0]
    assert lock_row.parent_step_id == step.id
    assert lock_row.input_json["mode"] == "lock_set"
    assert lock_row.input_json["lock"] is True
    assert lock_row.input_json["item_path"] == "chain:0"
    assert str(payload["result_id"]) == str(lock_row.id)

    # 幂等键 (novel_id, base_result_id, lock, item_path)：同键重放返回同一行
    again = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock", json=body
    )
    assert again.status_code == 200
    assert again.json()["result_id"] == payload["result_id"]

    # 已锁定项重复加锁（新 operation_id）按分支状态幂等，不追加重复条目
    duplicate = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock",
        json=_lock_body(
            test_project_id, lock=True, item_path="chain:0", item_text=effect
        ),
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["result_id"] == payload["result_id"]
    assert (
        duplicate.json()["payload"]["locked_items"] == payload["payload"]["locked_items"]
    )


@pytest.mark.asyncio
async def test_lock_unknown_path_and_text_drift_rejected(
    async_client, db_session, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    _root, _branch, step = await _seed_sandbox_result(db_session, test_project_id)

    unknown = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock",
        json=_lock_body(test_project_id, lock=True, item_path="chain:9"),
    )
    assert unknown.status_code == 409
    assert "可修订条目" in unknown.json()["detail"]

    drifted = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock",
        json=_lock_body(
            test_project_id,
            lock=True,
            item_path="chain:0",
            item_text="作者看到的是旧文案，已经对不上",
        ),
    )
    assert drifted.status_code == 409
    assert "内容已变化" in drifted.json()["detail"]


@pytest.mark.asyncio
async def test_unlock_removes_item_and_unlocking_unlocked_item_rejected(
    async_client, db_session, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    _root, _branch, step = await _seed_sandbox_result(db_session, test_project_id)
    effect = _chain_items(_sandbox_envelope())[0]["effect"]

    locked = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock",
        json=_lock_body(
            test_project_id, lock=True, item_path="chain:0", item_text=effect
        ),
    )
    assert locked.status_code == 200

    unlocked = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock",
        json=_lock_body(test_project_id, lock=False, item_path="chain:0"),
    )
    assert unlocked.status_code == 200, unlocked.json()
    assert unlocked.json()["locked_items"] == []
    assert unlocked.json()["payload"]["note"] is None

    # 幂等键重放：同样的解除请求返回同一行
    replay = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock",
        json=_lock_body(test_project_id, lock=False, item_path="chain:0"),
    )
    assert replay.status_code == 200
    assert replay.json()["result_id"] == unlocked.json()["result_id"]

    # 解除未锁定项 → 409
    stale = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock",
        json=_lock_body(test_project_id, lock=False, item_path="chain:1"),
    )
    assert stale.status_code == 409
    assert "未锁定" in stale.json()["detail"]


@pytest.mark.asyncio
async def test_lock_rejects_cross_novel_result(
    async_client, db_session, test_project_id, project_factory, monkeypatch
):
    _enable_exploration(monkeypatch)
    _root, _branch, step = await _seed_sandbox_result(db_session, test_project_id)
    other_project = str(await project_factory.create_project(title="另一本"))

    response = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock",
        json=_lock_body(other_project, lock=True, item_path="chain:0"),
    )
    assert response.status_code == 404
    assert "探索结果不存在" in response.json()["detail"]


@pytest.mark.asyncio
async def test_lock_accepts_author_edit_and_rejects_lock_set_rows(
    async_client, db_session, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    _root, _branch, step = await _seed_sandbox_result(db_session, test_project_id)
    edited = _sandbox_envelope().payload.model_copy(deep=True)
    edit_row, _env = await save_exploration_author_edit(
        db_session,
        novel_id=str(test_project_id),
        owner_id=OWNER_ID,
        base_result_id=str(step.id),
        edited_payload=edited,
    )

    on_edit = await async_client.post(
        f"/api/story/exploration/results/{edit_row.id}/lock",
        json=_lock_body(test_project_id, lock=True, item_path="chain:0"),
    )
    assert on_edit.status_code == 200
    assert on_edit.json()["locked_items"] == ["chain:0"]

    # 先在 AI 行上锁一条，再尝试把 lock_set 行本身当锁定目标
    locked = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock",
        json=_lock_body(test_project_id, lock=True, item_path="chain:0"),
    )
    assert locked.status_code == 200
    on_lock = await async_client.post(
        f"/api/story/exploration/results/{locked.json()['result_id']}/lock",
        json=_lock_body(test_project_id, lock=True, item_path="chain:1"),
    )
    assert on_lock.status_code == 409
    assert "不是可继续的探索结果" in on_lock.json()["detail"]


@pytest.mark.asyncio
async def test_lock_requires_exploration_gate(async_client, db_session, test_project_id):
    _root, _branch, step = await _seed_sandbox_result(db_session, test_project_id)
    response = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock",
        json=_lock_body(test_project_id, lock=True, item_path="chain:0"),
    )
    assert response.status_code == 503
    assert "独立探索尚未开启" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 修订/作者编辑遵守锁定
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revise_locked_item_rejected_but_other_item_passes_precheck(
    async_client, db_session, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    _root, _branch, step = await _seed_sandbox_result(db_session, test_project_id)
    items = _chain_items(_sandbox_envelope())
    locked = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock",
        json=_lock_body(
            test_project_id,
            lock=True,
            item_path="chain:0",
            item_text=items[0]["effect"],
        ),
    )
    assert locked.status_code == 200
    _stub_follow_up_confirmation(monkeypatch)

    blocked = await async_client.post(
        f"/api/story/exploration/results/{step.id}/revise",
        json={
            "novel_id": str(test_project_id),
            "operation_id": str(uuid.uuid4()),
            "item_path": "chain:0",
            "item_text": items[0]["effect"],
            "instruction": "把锁定项改掉",
        },
    )
    assert blocked.status_code == 409
    assert "已锁定" in blocked.json()["detail"]

    # 未锁定条目不受影响：预检通过并入队（锁定集不改变 AI 结果指针）
    ok = await async_client.post(
        f"/api/story/exploration/results/{step.id}/revise",
        json={
            "novel_id": str(test_project_id),
            "operation_id": str(uuid.uuid4()),
            "item_path": "chain:1",
            "item_text": items[1]["effect"],
            "instruction": "把第二环改保守",
        },
    )
    assert ok.status_code == 202, ok.json()
    assert ok.json()["root_id"] == str(_root.id)


@pytest.mark.asyncio
async def test_save_edit_touching_locked_item_conflicts_until_unlock(
    async_client, db_session, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    _root, _branch, step = await _seed_sandbox_result(db_session, test_project_id)
    items = _chain_items(_sandbox_envelope())
    locked = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock",
        json=_lock_body(
            test_project_id,
            lock=True,
            item_path="chain:0",
            item_text=items[0]["effect"],
        ),
    )
    assert locked.status_code == 200

    edited_payload = _sandbox_envelope()
    edited_payload.payload.influence_chain[0].effect = "作者改：面包更紧实"

    blocked = await async_client.post(
        f"/api/story/exploration/results/{step.id}/save-edit",
        json={
            "novel_id": str(test_project_id),
            "base_output_kind": "story.exploration.sandbox",
            "edited_payload": edited_payload.payload.model_dump(mode="json"),
        },
    )
    assert blocked.status_code == 409
    assert "已锁定" in blocked.json()["detail"]

    unlocked = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock",
        json=_lock_body(test_project_id, lock=False, item_path="chain:0"),
    )
    assert unlocked.status_code == 200
    allowed = await async_client.post(
        f"/api/story/exploration/results/{step.id}/save-edit",
        json={
            "novel_id": str(test_project_id),
            "base_output_kind": "story.exploration.sandbox",
            "edited_payload": edited_payload.payload.model_dump(mode="json"),
        },
    )
    assert allowed.status_code == 200, allowed.json()
    assert allowed.json()["output_kind"] == "story.exploration.author_edit"


@pytest.mark.asyncio
async def test_save_edit_removing_locked_item_conflicts(db_session, project_factory):
    """作者编辑删掉锁定条目同样 409（结构不一致失败关闭）。"""
    from core.errors import ConflictError

    project_id = await project_factory.create_project()
    _root, _branch, step = await _seed_sandbox_result(db_session, project_id)
    await set_exploration_item_lock(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        base_result_id=str(step.id),
        lock=True,
        item_path="chain:0",
    )
    stripped = SandboxOutputV1.model_validate(
        {
            "question": "重力减半后面包师的一天？",
            "influence_chain": [_chain_items(_sandbox_envelope())[1]],
        }
    )
    with pytest.raises(ConflictError):
        await save_exploration_author_edit(
            db_session,
            novel_id=str(project_id),
            owner_id=OWNER_ID,
            base_result_id=str(step.id),
            edited_payload=stripped,
        )


# ---------------------------------------------------------------------------
# 比较与历史：locked_items 展示、lock_set 不参与
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_reports_locked_items_per_side(
    async_client, db_session, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    _root, _branch, step = await _seed_sandbox_result(db_session, test_project_id)
    _other_root, _other_branch, other_step = await _seed_sandbox_result(
        db_session, test_project_id
    )
    locked = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock",
        json=_lock_body(test_project_id, lock=True, item_path="chain:0"),
    )
    assert locked.status_code == 200

    compared = await async_client.post(
        "/api/story/exploration/compare",
        json={
            "novel_id": str(test_project_id),
            "first_result_id": str(step.id),
            "second_result_id": str(other_step.id),
        },
    )
    assert compared.status_code == 200
    body = compared.json()
    assert body["first"]["locked_items"] == ["chain:0"]
    assert body["second"]["locked_items"] == []


@pytest.mark.asyncio
async def test_compare_rejects_lock_set_row(db_session, project_factory):
    from core.errors import ConflictError

    project_id = await project_factory.create_project()
    _root, _branch, step = await _seed_sandbox_result(db_session, project_id)
    lock_row, _envelope = await set_exploration_item_lock(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        base_result_id=str(step.id),
        lock=True,
        item_path="chain:0",
    )
    with pytest.raises(ConflictError):
        await compare_exploration_results(
            db_session,
            novel_id=str(project_id),
            owner_id=OWNER_ID,
            first_result_id=str(lock_row.id),
            second_result_id=str(step.id),
        )


@pytest.mark.asyncio
async def test_history_filters_lock_set_rows(
    async_client, db_session, test_project_id, monkeypatch
):
    _enable_exploration(monkeypatch)
    _root, _branch, step = await _seed_sandbox_result(db_session, test_project_id)
    locked = await async_client.post(
        f"/api/story/exploration/results/{step.id}/lock",
        json=_lock_body(test_project_id, lock=True, item_path="chain:0"),
    )
    assert locked.status_code == 200

    history = await async_client.get(
        "/api/story/exploration/history", params={"novel_id": str(test_project_id)}
    )
    assert history.status_code == 200
    body = history.json()
    result_ids = {item["result_id"] for item in body["items"]}
    assert str(step.id) in result_ids
    assert locked.json()["result_id"] not in result_ids
    assert body["total"] == 1
    assert all(item["output_kind"] != LOCK_SET_OUTPUT_KIND for item in body["items"])


# ---------------------------------------------------------------------------
# 场景链（导演回合）与当前锁定集读取
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scene_line_lock_persists_and_gates_author_edit(
    db_session, project_factory
):
    from core.errors import ConflictError

    project_id = await project_factory.create_project()
    _root, branch, row, envelope = await _seed_scene_line_result(db_session, project_id)
    lock_row, lock_envelope = await set_exploration_item_lock(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        base_result_id=str(row.id),
        lock=True,
        item_path="line",
    )
    assert isinstance(lock_row, StorySceneDirectorRound)
    assert lock_row.round_number == row.round_number + 1
    assert lock_row.parent_round_id == row.id
    assert lock_envelope.payload.locked_items[0].item_path == "line"
    locked_paths = [
        item.item_path
        for item in await current_locked_items(
            db_session, novel_id=str(project_id), branch_id=branch.id, chain="scene"
        )
    ]
    assert locked_paths == ["line"]

    edited = envelope.payload.model_copy(update={"line": "你先回去吧，别硬撑。"})
    with pytest.raises(ConflictError):
        await save_exploration_author_edit(
            db_session,
            novel_id=str(project_id),
            owner_id=OWNER_ID,
            base_result_id=str(row.id),
            edited_payload=edited,
        )

    await set_exploration_item_lock(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        base_result_id=str(row.id),
        lock=False,
        item_path="line",
    )
    assert (
        await current_locked_items(
            db_session, novel_id=str(project_id), branch_id=branch.id, chain="scene"
        )
        == []
    )
    _edit_row, edit_envelope = await save_exploration_author_edit(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        base_result_id=str(row.id),
        edited_payload=edited,
    )
    assert edit_envelope.payload.edited_payload.line == "你先回去吧，别硬撑。"


@pytest.mark.asyncio
async def test_current_locked_items_reads_latest_lock_set_row(
    db_session, project_factory
):
    project_id = await project_factory.create_project()
    _root, branch, step = await _seed_sandbox_result(db_session, project_id)
    assert (
        await current_locked_items(
            db_session,
            novel_id=str(project_id),
            branch_id=branch.id,
            chain="progression",
        )
        == []
    )
    await set_exploration_item_lock(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        base_result_id=str(step.id),
        lock=True,
        item_path="chain:0",
    )
    await set_exploration_item_lock(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        base_result_id=str(step.id),
        lock=True,
        item_path="chain:1",
    )
    paths = [
        item.item_path
        for item in await current_locked_items(
            db_session,
            novel_id=str(project_id),
            branch_id=branch.id,
            chain="progression",
        )
    ]
    assert paths == ["chain:0", "chain:1"]


async def test_historical_author_edit_cannot_replace_current_locked_version(
    db_session, test_project_id
):
    from core.errors import ConflictError

    _root, branch, original = await _seed_sandbox_result(db_session, test_project_id)
    changed = _sandbox_envelope().payload.model_copy(deep=True)
    changed.influence_chain[0].effect = "作者确认的新内容"
    latest, _ = await save_exploration_author_edit(
        db_session,
        novel_id=str(test_project_id),
        owner_id=OWNER_ID,
        base_result_id=str(original.id),
        edited_payload=changed,
    )
    await set_exploration_item_lock(
        db_session,
        novel_id=str(test_project_id),
        owner_id=OWNER_ID,
        base_result_id=str(latest.id),
        lock=True,
        item_path="chain:0",
    )
    historical = _sandbox_envelope().payload.model_copy(deep=True)
    historical.influence_chain[1].effect = "只编辑历史版本的第二条"
    with pytest.raises(ConflictError, match="已锁定"):
        await save_exploration_author_edit(
            db_session,
            novel_id=str(test_project_id),
            owner_id=OWNER_ID,
            base_result_id=str(original.id),
            edited_payload=historical,
        )
    locks = await current_locked_items(
        db_session,
        novel_id=str(test_project_id),
        branch_id=branch.id,
        chain="progression",
    )
    assert [item.item_path for item in locks] == ["chain:0"]
