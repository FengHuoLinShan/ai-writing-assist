"""引导流程运行层（ADR-0032 / BR-3）：注册与版本、产物推导、停点与恢复。

集成测试用假 suggest 操作与真实任务行驱动 advance，不调用任何模型；
领域门禁（复核、采用）仍由 Writing 既有路径负责，本文件只钉住编排语义。
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import BaseModel

from core.config import get_settings
from core.container import container_scope
from core.errors import ConflictError, ValidationError
from infrastructure.tasks.facade import enqueue_task
from infrastructure.tasks.models import AsyncTask
from modules.assistant.contracts import AssistantOperation
from modules.assistant.guided_flow import flows as guided_flows
from modules.assistant.guided_flow import runtime as guided_runtime
from modules.assistant.guided_flow.contracts import GuidedFlowSettings
from modules.assistant.guided_flow.registry import (
    FLOWS,
    FlowDefinition,
    StepDefinition,
    validate_flow,
)
from modules.evidence.compilation.models import ContextConfirmation
from modules.writing.models import WritingDraft
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import WritingDraftCreate

OWNER = "00000000-0000-0000-0000-000000000000"


async def test_guided_flow_http_start_active_view_and_abandon(
    async_client, test_project_id, project_factory, enabled
):
    response = await async_client.post(
        "/api/assistant/flows",
        json={
            "novel_id": test_project_id,
            "flow_id": "new_book_opening",
            "input": {"vision": "潮汐城市里寻找失踪的名字"},
        },
    )
    assert response.status_code == 201, response.text
    run_id = response.json()["run_id"]
    active = await async_client.get(
        "/api/assistant/flows/active", params={"novel_id": test_project_id}
    )
    assert active.status_code == 200, active.text
    assert active.json()["run_id"] == run_id
    other_project = await project_factory.create_project(title="隔离作品")
    hidden = await async_client.get(
        f"/api/assistant/flows/{run_id}", params={"novel_id": str(other_project)}
    )
    assert hidden.status_code == 404
    view = await async_client.get(
        f"/api/assistant/flows/{run_id}", params={"novel_id": test_project_id}
    )
    assert view.status_code == 200
    stopped = await async_client.post(
        f"/api/assistant/flows/{run_id}/abandon", params={"novel_id": test_project_id}
    )
    assert stopped.status_code == 200 and stopped.json()["status"] == "cancelled"
    active = await async_client.get(
        "/api/assistant/flows/active", params={"novel_id": test_project_id}
    )
    assert active.status_code == 200 and active.json() is None


def _settings(**overrides):
    base = {
        "assistant_enabled": True,
        "assistant_guided_flows_enabled": True,
        "guided_flow_project_allowlist": (),
    }
    return replace(get_settings(), **{**base, **overrides})


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(guided_runtime, "get_settings", lambda: _settings())


@pytest.fixture
def fake_semantic_review(monkeypatch):
    """独立语义审查走既有领域任务的替身：只入队，不触发真实提交。"""

    async def _submit(db, *, novel_id, draft_ids, operation_id=None):
        task_id = enqueue_task(
            db,
            "writing_semantic_review",
            novel_id=novel_id,
            meta={"draft_ids": draft_ids},
        )
        return {"task_id": task_id, "status": "pending"}

    monkeypatch.setattr(guided_flows, "submit_semantic_review", _submit)


class _GenerateArgs(BaseModel):
    chapter_index: int
    title: str | None = None
    instruction: str | None = None
    generation_mode: str = "draft"


def _fake_generate_operation(calls: list):
    async def prepare(db, novel_id, args, *, context=None):
        return {"chapter_index": args.chapter_index}

    async def apply(db, novel_id, args, preview, *, context=None):
        calls.append({"args": args, "operation_id": context.operation_id})
        task_id = enqueue_task(
            db,
            "writing_generate",
            novel_id=novel_id,
            meta={"chapter_index": args.chapter_index},
        )
        return {
            "type": "writing_generate",
            "id": task_id,
            "task_id": task_id,
            "task_type": "writing_generate",
        }

    return AssistantOperation(
        label="生成正文候选",
        schema=_GenerateArgs,
        prepare=prepare,
        apply=apply,
        permission="suggest",
    )


async def _create_draft(
    db,
    novel_id: str,
    *,
    status: str,
    chapter: int = 1,
    content: str = "正文",
    provenance: dict | None = None,
) -> WritingDraft:
    return await WritingDraftRepository().create_with_status(
        db,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=chapter,
            title=f"第 {chapter} 章",
            content=content,
            provenance_json=provenance or {},
        ),
        status=status,
    )


async def _create_confirmation(db, novel_id: str, *, chapter: int = 1):
    row = ContextConfirmation(
        novel_id=UUID(novel_id),
        action="writing.generate",
        task="生成正文候选",
        scope="chapter",
        compile_options={
            "novel_id": novel_id,
            "task": "生成正文候选",
            "scope": "chapter",
            "requested_chapter_index": chapter,
        },
    )
    db.add(row)
    await db.flush()
    return row


async def _mark_task(db, task_id: str, *, status: str, result: dict | None = None):
    task = await db.get(AsyncTask, UUID(task_id))
    task.status = status
    if result is not None:
        task.result = result
    await db.flush()


def _states(view: dict) -> dict:
    return {item["step_id"]: item["state"] for item in view["steps"]}


# ---------------------------------------------------------------------------
# 注册与版本
# ---------------------------------------------------------------------------


def test_flow_registry_shape_and_version():
    flow = FLOWS["continue_writing"]
    assert flow.version == 3
    kinds = {step.kind for step in flow.steps}
    assert kinds <= {"auto", "author_confirm", "author_choice"}
    assert kinds == {"auto", "author_confirm", "author_choice"}
    produces = [step.produces for step in flow.steps]
    assert len(produces) == len(set(produces)), "产物必须单一生产者"
    seen: set[str] = set()
    for step in flow.steps:
        assert set(step.requires) <= seen, "依赖只允许指向更早步骤（无环）"
        seen.add(step.step_id)
    # BR-6：滚动规划段挂在审阅之后，只在作者确认后推进。
    rolling_steps = [
        step.step_id for step in flow.steps if step.step_id.startswith("rolling")
    ]
    assert rolling_steps == [
        "rolling_offer",
        "rolling_threads",
        "rolling_arcs",
        "rolling_scenes",
        "rolling_review",
    ]


def test_flow_registry_covers_all_three_flows():
    """BR-4/5/6 集成尾部：三个流程注册在同一张表，版本各自递增。"""
    opening = FLOWS["new_book_opening"]
    editorial = FLOWS["editorial_revision"]
    assert opening.version == 1 and editorial.version == 1
    assert [step.step_id for step in opening.steps] == [
        "direction_cards",
        "choose_direction",
        "draft_skeleton",
        "adopt_skeleton",
        "skeleton_ready",
    ]
    assert [step.step_id for step in editorial.steps] == [
        "select_issues",
        "bridge_revision",
        "review_candidates",
        "post_recheck",
        "review_rechecks",
    ]
    for flow in (opening, editorial):
        produces = [step.produces for step in flow.steps]
        assert len(produces) == len(set(produces)), "产物必须单一生产者"
        seen: set[str] = set()
        for step in flow.steps:
            assert set(step.requires) <= seen
            seen.add(step.step_id)
    # 自动步骤只允许引用建议类操作或领域任务；骨架采用必须是作者确认。
    adopt = next(step for step in opening.steps if step.step_id == "adopt_skeleton")
    assert adopt.kind == "author_confirm" and adopt.operation is None


def test_flow_registry_rejects_cycles_duplicates_and_unknown_kind():
    def step(step_id, kind="auto", requires=(), produces=None):
        return StepDefinition(
            step_id=step_id,
            kind=kind,  # type: ignore[arg-type]
            title=step_id,
            produces=produces or step_id,
            requires=requires,
            operation="op" if kind == "auto" else None,
        )

    with pytest.raises(ValidationError, match="依赖"):
        validate_flow(
            FlowDefinition(
                flow_id="x",
                version=1,
                title="t",
                description="d",
                steps=(step("b", requires=("a",)), step("a")),
            )
        )
    with pytest.raises(ValidationError, match="单一生产者|生产者"):
        validate_flow(
            FlowDefinition(
                flow_id="x",
                version=1,
                title="t",
                description="d",
                steps=(step("a", produces="p"), step("b", produces="p")),
            )
        )
    with pytest.raises(ValidationError, match="未知类型"):
        validate_flow(
            FlowDefinition(
                flow_id="x",
                version=1,
                title="t",
                description="d",
                steps=(step("a", kind="model_decides"),),
            )
        )
    with pytest.raises(ValidationError, match="且只能引用"):
        validate_flow(
            FlowDefinition(
                flow_id="x",
                version=1,
                title="t",
                description="d",
                steps=(
                    StepDefinition(step_id="a", kind="auto", title="a", produces="p"),
                ),
            )
        )


def test_require_flow_validates_operation_against_catalog():
    flow = FLOWS["continue_writing"]
    available = {
        "writing.generate_candidate": SimpleNamespace(permission="suggest"),
        "story.plan_structure": SimpleNamespace(permission="suggest"),
    }
    assert guided_runtime and flow
    from modules.assistant.guided_flow.registry import require_flow

    assert require_flow("continue_writing", operations=available).flow_id == (
        "continue_writing"
    )
    missing = dict(available)
    missing["story.plan_structure"] = None
    with pytest.raises(ValidationError, match="未注册"):
        require_flow("continue_writing", operations=missing)
    with pytest.raises(ValidationError, match="建议类"):
        require_flow(
            "continue_writing",
            operations={
                "writing.generate_candidate": SimpleNamespace(permission="suggest"),
                "story.plan_structure": SimpleNamespace(permission="confirm"),
            },
        )
    with pytest.raises(ValidationError, match="不存在"):
        require_flow("no_such_flow", operations=available)
    # 新书开篇经目录校验 world 侧操作；Assistant 不得直接 import World。
    opening_available = {
        "world.draft_opening_skeleton": SimpleNamespace(permission="suggest"),
    }
    assert require_flow("new_book_opening", operations=opening_available) is not None
    with pytest.raises(ValidationError, match="未注册"):
        require_flow("new_book_opening", operations={})


# ---------------------------------------------------------------------------
# 开始：定位工作稿、幂等重入、每流程一个活动 run
# ---------------------------------------------------------------------------


async def test_start_requires_working_draft_and_enabled_switch(
    db_session, test_project_id, monkeypatch
):
    from modules.assistant.guided_flow.contracts import GuidedFlowStartRequest

    monkeypatch.setattr(guided_runtime, "get_settings", lambda: _settings())
    with pytest.raises(ValidationError, match="工作稿"):
        await guided_runtime.start(
            db_session,
            test_project_id,
            OWNER,
            GuidedFlowStartRequest(novel_id=test_project_id, chapter_index=3),
        )
    monkeypatch.setattr(
        guided_runtime,
        "get_settings",
        lambda: _settings(assistant_guided_flows_enabled=False),
    )
    with pytest.raises(ValidationError, match="尚未开启"):
        await guided_runtime.start(
            db_session,
            test_project_id,
            OWNER,
            GuidedFlowStartRequest(novel_id=test_project_id, chapter_index=1),
        )


async def test_start_stops_at_confirm_and_reenters_same_run(
    db_session, test_project_id, enabled
):
    await _create_draft(db_session, test_project_id, status="published")
    from modules.assistant.guided_flow.contracts import GuidedFlowStartRequest

    request = GuidedFlowStartRequest(novel_id=test_project_id, chapter_index=1)
    view = await guided_runtime.start(db_session, test_project_id, OWNER, request)
    assert view["status"] == "waiting_approval"
    assert view["stop"]["step_id"] == "confirm_reference"
    assert view["stop"]["kind"] == "author_confirm"
    assert _states(view)["confirm_reference"] == "active"
    assert view["settings"]["semantic_review"] is True

    reentry = await guided_runtime.start(db_session, test_project_id, OWNER, request)
    assert reentry["run_id"] == view["run_id"]

    await _create_draft(db_session, test_project_id, status="published", chapter=2)
    with pytest.raises(ConflictError, match="进行中的"):
        await guided_runtime.start(
            db_session,
            test_project_id,
            OWNER,
            GuidedFlowStartRequest(novel_id=test_project_id, chapter_index=2),
        )

    with pytest.raises(Exception, match="流程运行不存在"):
        await guided_runtime.view(db_session, test_project_id, view["run_id"], "f" * 32)


# ---------------------------------------------------------------------------
# 推导与推进：确认 → 生成 → 审查 → 可审阅；恢复与硬阻断
# ---------------------------------------------------------------------------


async def _start_flow(db, novel_id, *, chapter=1):
    from modules.assistant.guided_flow.contracts import GuidedFlowStartRequest

    return await guided_runtime.start(
        db,
        novel_id,
        OWNER,
        GuidedFlowStartRequest(novel_id=novel_id, chapter_index=chapter),
    )


async def test_confirm_staleness_recovers_without_hard_block(
    db_session, test_project_id, enabled, monkeypatch
):
    # 冻结/幂等/章节校验只依赖确认存在与编译选项；重编译本身是
    # Evidence 既有路径，不在此重复验收。
    async def fake_prepare(db, *, novel_id, action, confirmation_id):
        row = await db.get(ContextConfirmation, UUID(confirmation_id))
        assert row is not None and row.action == action
        return SimpleNamespace(
            confirmation=SimpleNamespace(excluded_asset_ids={}, context_fingerprint="fp"),
            compile_options=dict(row.compile_options),
        )

    monkeypatch.setattr(guided_flows, "prepare_confirmed_ai_action", fake_prepare)
    await _create_draft(db_session, test_project_id, status="draft")
    view = await _start_flow(db_session, test_project_id)
    confirmation = await _create_confirmation(db_session, test_project_id)
    run = await guided_runtime._require_run(
        db_session, test_project_id, view["run_id"], OWNER, lock=True
    )
    from modules.assistant.guided_flow.flows import apply_confirm_input

    artifacts: dict = {}
    changed = await apply_confirm_input(
        db_session,
        test_project_id,
        run,
        FLOWS["continue_writing"],
        artifacts,
        {"context_confirmation_id": str(confirmation.id)},
    )
    assert changed is True
    assert artifacts["context_confirmation"]["confirmation_id"] == str(confirmation.id)
    # 同一确认重复提交是幂等空操作。
    assert not await apply_confirm_input(
        db_session,
        test_project_id,
        run,
        FLOWS["continue_writing"],
        artifacts,
        {"context_confirmation_id": str(confirmation.id)},
    )
    # 章节不匹配的确认失败关闭。
    other = await _create_confirmation(db_session, test_project_id, chapter=9)
    with pytest.raises(ConflictError, match="目标章节"):
        await apply_confirm_input(
            db_session,
            test_project_id,
            run,
            FLOWS["continue_writing"],
            {},
            {"context_confirmation_id": str(other.id)},
        )

    # 确认失效 → 停回确认点，可恢复而不是硬失败。
    confirmation.stale_reasons = ["source_changed"]
    await db_session.flush()
    recovered = await guided_runtime.view(
        db_session, test_project_id, view["run_id"], OWNER
    )
    assert recovered["status"] == "waiting_approval"
    assert recovered["stop"]["step_id"] == "confirm_reference"
    assert _states(recovered)["confirm_reference"] == "active"

    # 失效确认可由作者的新确认替换；仍新鲜的确认不接受另一个 ID。
    replacement = await _create_confirmation(db_session, test_project_id)
    assert await apply_confirm_input(
        db_session,
        test_project_id,
        run,
        FLOWS["continue_writing"],
        artifacts,
        {"context_confirmation_id": str(replacement.id)},
    )
    assert artifacts["context_confirmation"]["confirmation_id"] == str(replacement.id)
    with pytest.raises(ConflictError, match="无需重复确认"):
        await apply_confirm_input(
            db_session,
            test_project_id,
            run,
            FLOWS["continue_writing"],
            artifacts,
            {"context_confirmation_id": str(confirmation.id)},
        )


async def test_advance_runs_generation_once_and_stops_for_review(
    db_session, test_project_id, enabled
):
    await _create_draft(db_session, test_project_id, status="published")
    calls: list = []
    operation = _fake_generate_operation(calls)
    operations = {
        "writing.generate_candidate": operation,
        "story.plan_structure": _fake_plan_operation(calls),
    }
    with container_scope({"assistant.operations": operations}):
        view = await _start_flow(db_session, test_project_id)
        confirmation = await _create_confirmation(db_session, test_project_id)
        first = await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {"context_confirmation_id": str(confirmation.id)},
        )
        assert first["stop"] is None
        assert first["status"] == "running"
        assert _states(first)["generate_candidate"] == "active"
        assert len(calls) == 1
        task_id = calls[0]["task_id"] if "task_id" in calls[0] else None

        # 生成在途时重复推进不产生第二个任务。
        again = await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
        assert len(calls) == 1
        assert again["stop"] is None

        run = await guided_runtime._require_run(
            db_session, test_project_id, view["run_id"], OWNER
        )
        artifacts = guided_runtime._artifacts(run)
        task_id = artifacts["candidate"]["task_id"]
        candidate = await _create_draft(
            db_session,
            test_project_id,
            status="candidate",
            provenance={
                "source": "writing_generate",
                "knowledge_review": {"status": "passed"},
            },
        )
        await _mark_task(
            db_session, task_id, status="done", result={"draft_id": str(candidate.id)}
        )

        reviewed: list = []

        async def fake_submit_review(db, *, novel_id, draft_ids, operation_id=None):
            reviewed.append({"draft_ids": draft_ids, "operation_id": operation_id})
            review_task = enqueue_task(
                db,
                "writing_semantic_review",
                novel_id=novel_id,
                meta={"draft_ids": draft_ids},
            )
            return {"task_id": review_task, "status": "pending"}

        import modules.assistant.guided_flow.flows as flows_module

        original = flows_module.submit_semantic_review
        flows_module.submit_semantic_review = fake_submit_review
        try:
            after_generate = await guided_runtime.advance(
                db_session, test_project_id, view["run_id"], OWNER, {}
            )
            assert _states(after_generate)["semantic_review"] == "active"
            assert len(reviewed) == 1
            # 审查在途重复推进：不重复提交。
            await guided_runtime.advance(
                db_session, test_project_id, view["run_id"], OWNER, {}
            )
            assert len(reviewed) == 1
            review_task_id = guided_runtime._artifacts(
                await guided_runtime._require_run(
                    db_session, test_project_id, view["run_id"], OWNER
                )
            )["semantic_review"]["task_id"]
            await _mark_task(db_session, review_task_id, status="done")
            candidate.provenance_json = {
                **candidate.provenance_json,
                "independent_review": {"verdict": "pass", "blocking_count": 0},
            }
            await db_session.flush()

            final = await guided_runtime.advance(
                db_session, test_project_id, view["run_id"], OWNER, {}
            )
        finally:
            flows_module.submit_semantic_review = original

    assert final["status"] == "waiting_approval"
    assert final["stop"]["step_id"] == "review_candidate"
    assert final["stop"]["kind"] == "author_choice"
    assert final["stop"]["reason"] == "可审阅，待作者采用"

    # 刷新或换设备回到同一停点。
    reread = await guided_runtime.view(db_session, test_project_id, view["run_id"], OWNER)
    assert reread["stop"] == final["stop"]
    assert reread["candidate"]["draft_id"] == str(candidate.id)

    # 采用后停在「规划接下来几章」：BR-6 只在流程内经作者确认触发。
    candidate.status = "deprecated"
    candidate.provenance_json = {
        **candidate.provenance_json,
        "adoption_result_draft_id": str(uuid.uuid4()),
    }
    await db_session.flush()
    offered = await guided_runtime.advance(
        db_session, test_project_id, view["run_id"], OWNER, {}
    )
    assert offered["status"] == "waiting_approval"
    assert offered["stop"]["step_id"] == "rolling_offer"
    assert offered["stop"]["kind"] == "author_choice"

    # 作者先不用：流程完成，不产生任何规划任务。
    completed = await guided_runtime.advance(
        db_session,
        test_project_id,
        view["run_id"],
        OWNER,
        {"choice": {"step_id": "rolling_offer", "action": "decline"}},
    )
    assert completed["status"] == "completed"
    assert completed["stop"] is None


async def test_generation_failure_is_hard_block_with_reason(
    db_session, test_project_id, enabled
):
    await _create_draft(db_session, test_project_id, status="published")
    calls: list = []
    with container_scope(
        {
            "assistant.operations": {
                "writing.generate_candidate": _fake_generate_operation(calls),
                "story.plan_structure": _fake_plan_operation(calls),
            }
        }
    ):
        view = await _start_flow(db_session, test_project_id)
        confirmation = await _create_confirmation(db_session, test_project_id)
        await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {"context_confirmation_id": str(confirmation.id)},
        )
        run = await guided_runtime._require_run(
            db_session, test_project_id, view["run_id"], OWNER
        )
        task_id = guided_runtime._artifacts(run)["candidate"]["task_id"]
        await _mark_task(db_session, task_id, status="failed")
        blocked = await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
    assert blocked["status"] == "failed"
    assert blocked["stop"]["kind"] == "blocked"
    assert "没有生成完成" in blocked["stop"]["reason"]
    with pytest.raises(ConflictError, match="已结束"):
        await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )


async def test_semantic_review_can_be_turned_off_before_generation(
    db_session, test_project_id, enabled
):
    await _create_draft(db_session, test_project_id, status="published")
    calls: list = []
    with container_scope(
        {
            "assistant.operations": {
                "writing.generate_candidate": _fake_generate_operation(calls),
                "story.plan_structure": _fake_plan_operation(calls),
            }
        }
    ):
        view = await _start_flow(db_session, test_project_id)
        await guided_runtime.save_settings(
            db_session, test_project_id, view["run_id"], OWNER, semantic_review=False
        )
        confirmation = await _create_confirmation(db_session, test_project_id)
        await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {"context_confirmation_id": str(confirmation.id)},
        )
        run = await guided_runtime._require_run(
            db_session, test_project_id, view["run_id"], OWNER
        )
        task_id = guided_runtime._artifacts(run)["candidate"]["task_id"]
        candidate = await _create_draft(
            db_session,
            test_project_id,
            status="candidate",
            provenance={"knowledge_review": {"status": "passed"}},
        )
        await _mark_task(
            db_session, task_id, status="done", result={"draft_id": str(candidate.id)}
        )
        stopped = await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
        # 生成开始后设置冻结。
        with pytest.raises(ConflictError, match="设置"):
            await guided_runtime.save_settings(
                db_session, test_project_id, view["run_id"], OWNER, semantic_review=True
            )
    assert _states(stopped)["semantic_review"] == "skipped"
    assert stopped["stop"]["step_id"] == "review_candidate"
    assert "未自动接独立审查" in stopped["stop"]["reason"]


async def test_abandon_cancels_and_prevents_restart_of_same_run(
    db_session, test_project_id, enabled
):
    await _create_draft(db_session, test_project_id, status="published")
    view = await _start_flow(db_session, test_project_id)
    stopped = await guided_runtime.abandon(
        db_session, test_project_id, view["run_id"], OWNER
    )
    assert stopped["status"] == "cancelled"
    with pytest.raises(ConflictError, match="已结束"):
        await guided_runtime.abandon(db_session, test_project_id, view["run_id"], OWNER)
    # 结束后同一输入可以重新开始（新 run）。
    fresh = await _start_flow(db_session, test_project_id)
    assert fresh["run_id"] != view["run_id"]


async def test_version_drift_fails_closed(
    db_session, test_project_id, enabled, monkeypatch
):
    await _create_draft(db_session, test_project_id, status="published")
    view = await _start_flow(db_session, test_project_id)
    monkeypatch.setitem(
        FLOWS,
        "continue_writing",
        replace(FLOWS["continue_writing"], version=FLOWS["continue_writing"].version + 1),
    )
    restored = await guided_runtime.active_run(db_session, test_project_id, OWNER)
    assert restored["stop"]["step_id"] == "version_changed"
    assert restored["stop"]["actions"][0]["action"] == "abandon_flow"
    with pytest.raises(ConflictError, match="流程定义已更新"):
        await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
    # 结束流程不依赖版本表，始终可行。
    stopped = await guided_runtime.abandon(
        db_session, test_project_id, view["run_id"], OWNER
    )
    assert stopped["status"] == "cancelled"


async def test_operation_id_is_deterministic_per_run_step_and_input(
    db_session, test_project_id, enabled
):
    await _create_draft(db_session, test_project_id, status="published")
    calls: list = []
    with container_scope(
        {
            "assistant.operations": {
                "writing.generate_candidate": _fake_generate_operation(calls),
                "story.plan_structure": _fake_plan_operation(calls),
            }
        }
    ):
        view = await _start_flow(db_session, test_project_id)
        confirmation = await _create_confirmation(db_session, test_project_id)
        await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {"context_confirmation_id": str(confirmation.id)},
        )
        assert len(calls) == 1
        first_id = calls[0]["operation_id"]
        # 换一个流程运行：不同运行产生不同 operation_id。
        candidate = await _create_draft(
            db_session,
            test_project_id,
            status="candidate",
            provenance={},
        )
        run = await guided_runtime._require_run(
            db_session, test_project_id, view["run_id"], OWNER
        )
        await _mark_task(
            db_session,
            guided_runtime._artifacts(run)["candidate"]["task_id"],
            status="done",
            result={"draft_id": str(candidate.id)},
        )
    from modules.assistant.guided_flow.flows import _flow_operation_id

    assert first_id == _flow_operation_id(
        run, FLOWS["continue_writing"], "generate_candidate", run.request_hash
    )


# ---------------------------------------------------------------------------
# 滚动规划（BR-6 流程侧）：采用后提窗、plan_structure、补窗、完成
# ---------------------------------------------------------------------------


class _PlanArgs(BaseModel):
    target: str
    mode: str = "create"
    instruction: str = ""
    start_chapter: int | None = None
    end_chapter: int | None = None


def _fake_plan_operation(calls: list):
    async def prepare(db, novel_id, args, *, context=None):
        return {"target": args.target, "start": args.start_chapter}

    async def apply(db, novel_id, args, preview, *, context=None):
        calls.append(
            {
                "target": args.target,
                "start": args.start_chapter,
                "end": args.end_chapter,
                "operation_id": context.operation_id,
            }
        )
        task_id = enqueue_task(
            db, "outline_generate", novel_id=novel_id, meta={"target": args.target}
        )
        return {"task_id": task_id}

    return AssistantOperation(
        label="规划结构",
        schema=_PlanArgs,
        prepare=prepare,
        apply=apply,
        permission="suggest",
    )


async def _adopt_candidate(db, novel_id: str, candidate: WritingDraft) -> None:
    candidate.status = "deprecated"
    candidate.provenance_json = {
        **candidate.provenance_json,
        "adoption_result_draft_id": str(uuid.uuid4()),
    }
    await db.flush()


@pytest.mark.parametrize("window", [1, 4, 5])
async def test_rolling_plan_passes_the_confirmed_end_chapter(
    db_session, test_project_id, window
):
    from dataclasses import replace
    from types import SimpleNamespace

    from modules.assistant.guided_flow.flows import _run_rolling_plan
    from modules.story.assistant_structure_workflow import PlanStructure

    calls = []
    operation = replace(_fake_plan_operation(calls), schema=PlanStructure)
    with container_scope({"assistant.operations": {"story.plan_structure": operation}}):
        await _run_rolling_plan(
            db_session,
            test_project_id,
            OWNER,
            SimpleNamespace(id=uuid.uuid4()),
            FLOWS["continue_writing"],
            {
                "rolling_decision": {"at_chapter": 1, "accepted": True, "window": window},
                "rolling_arcs_confirmation": {"confirmation_id": str(uuid.uuid4())},
            },
            "rolling_arcs",
            input_fingerprint="confirmed-input",
        )
    assert calls[0]["start"] == 2
    assert calls[0]["end"] == 1 + window


async def _run_to_review_stop(db, novel_id: str):
    """推到「可审阅」停点：确认 → 生成任务 → 候选完成（默认审查关闭由调用方定）。"""
    from modules.assistant.guided_flow.contracts import GuidedFlowStartRequest

    return await guided_runtime.start(
        db, novel_id, OWNER, GuidedFlowStartRequest(novel_id=novel_id, chapter_index=1)
    )


async def test_rolling_offer_backfill_reason_and_decline_completes(
    db_session, test_project_id, enabled, fake_semantic_review
):
    """采用第 1 章后提窗：前方无规划时提示补足；作者拒绝则完成、不产生任务。"""
    await _create_draft(db_session, test_project_id, status="published")
    calls: list = []
    with container_scope(
        {
            "assistant.operations": {
                "writing.generate_candidate": _fake_generate_operation(calls),
                "story.plan_structure": _fake_plan_operation(calls),
            }
        }
    ):
        view = await _start_flow(db_session, test_project_id)
        confirmation = await _create_confirmation(db_session, test_project_id)
        await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {"context_confirmation_id": str(confirmation.id)},
        )
        run = await guided_runtime._require_run(
            db_session, test_project_id, view["run_id"], OWNER
        )
        task_id = guided_runtime._artifacts(run)["candidate"]["task_id"]
        candidate = await _create_draft(
            db_session,
            test_project_id,
            status="candidate",
            provenance={"knowledge_review": {"status": "passed"}},
        )
        await _mark_task(
            db_session, task_id, status="done", result={"draft_id": str(candidate.id)}
        )
        await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
        await _adopt_candidate(db_session, test_project_id, candidate)
        offered = await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
        assert offered["stop"]["step_id"] == "rolling_offer"
        assert "不足 2 章" in offered["stop"]["reason"]
        assert offered["panel"]["rolling"]["window"] == {"start": 2, "end": 4}

        before = len(calls)
        completed = await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {"choice": {"step_id": "rolling_offer", "action": "decline"}},
        )
    assert completed["status"] == "completed"
    assert len(calls) == before, "拒绝规划不产生任何结构任务"


async def _confirm_rolling(db, novel_id, run_id, layer):
    run = await guided_runtime._require_run(db, novel_id, run_id, OWNER)
    decision = guided_runtime._artifacts(run)["rolling_decision"]
    start = decision["at_chapter"] + 1
    width = min(decision["window"], 2) if layer == "scenes" else decision["window"]
    row = ContextConfirmation(
        novel_id=UUID(novel_id),
        action="outline.generate",
        task="结构规划",
        scope="full",
        compile_options={
            "novel_id": novel_id,
            "task": "结构规划",
            "scope": "full",
            "budget_tokens": 0,
            "chapter_index": start,
            "planning_window_end": start + width - 1,
        },
    )
    db.add(row)
    await db.flush()
    return await guided_runtime.advance(
        db, novel_id, run_id, OWNER, {"context_confirmation_id": str(row.id)}
    )


async def test_rolling_plan_runs_once_and_stops_for_structure_review(
    db_session, test_project_id, enabled, fake_semantic_review
):
    """确认规划 → 一次提交剧情线与篇章两层（确定性回执）→ 停在候选审阅。"""
    await _create_draft(db_session, test_project_id, status="published")
    calls: list = []
    with container_scope(
        {
            "assistant.operations": {
                "writing.generate_candidate": _fake_generate_operation(calls),
                "story.plan_structure": _fake_plan_operation(calls),
            }
        }
    ):
        view = await _start_flow(db_session, test_project_id)
        confirmation = await _create_confirmation(db_session, test_project_id)
        await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {"context_confirmation_id": str(confirmation.id)},
        )
        run = await guided_runtime._require_run(
            db_session, test_project_id, view["run_id"], OWNER
        )
        task_id = guided_runtime._artifacts(run)["candidate"]["task_id"]
        candidate = await _create_draft(
            db_session,
            test_project_id,
            status="candidate",
            provenance={"knowledge_review": {"status": "passed"}},
        )
        await _mark_task(
            db_session, task_id, status="done", result={"draft_id": str(candidate.id)}
        )
        await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
        await _adopt_candidate(db_session, test_project_id, candidate)
        await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
        await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {"choice": {"step_id": "rolling_offer", "action": "plan_ahead"}},
        )
        run = await guided_runtime._require_run(
            db_session, test_project_id, view["run_id"], OWNER
        )
        assert "arc_proposals" not in guided_runtime._artifacts(run)
        for layer, key in (("threads", "thread_proposals"), ("arcs", "arc_proposals")):
            await _confirm_rolling(db_session, test_project_id, view["run_id"], layer)
            task_id = guided_runtime._artifacts(run)[key]["task_id"]
            await _mark_task(
                db_session,
                task_id,
                status="done",
                result={"draft_structure": {"result": "proposed"}},
            )
            await guided_runtime.advance(
                db_session, test_project_id, view["run_id"], OWNER, {}
            )
        await _confirm_rolling(db_session, test_project_id, view["run_id"], "scenes")
        plan_calls = [call for call in calls if "target" in call]
        assert sorted(call["target"] for call in plan_calls) == [
            "outline_arc",
            "planned_scene",
            "plot_thread",
        ]
        assert all(call["start"] == 2 for call in plan_calls)
        run = await guided_runtime._require_run(
            db_session, test_project_id, view["run_id"], OWNER
        )
        artifacts = guided_runtime._artifacts(run)
        thread_task = artifacts["thread_proposals"]["task_id"]
        arc_task = artifacts["arc_proposals"]["task_id"]
        scene_task = artifacts["scene_proposals"]["task_id"]

        # 在途重复推进：不产生第二个任务。
        await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
        plan_calls_after = [call for call in calls if "target" in call]
        assert len(plan_calls_after) == len(plan_calls)

        await _mark_task(
            db_session, thread_task, status="done", result={"apply_status": "applied"}
        )
        await _mark_task(
            db_session, arc_task, status="done", result={"apply_status": "applied"}
        )
        await _mark_task(db_session, scene_task, status="done", result={})
        review = await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
        assert review["status"] == "waiting_approval"
        assert review["stop"]["step_id"] == "review_rolling_scenes"
        assert review["stop"]["kind"] == "author_choice"

        finished = await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {"choice": {"step_id": "review_rolling_scenes", "action": "finish_flow"}},
        )
    assert finished["status"] == "completed"
    assert finished["stop"] is None


async def test_rolling_review_completes_when_window_covered(
    db_session, test_project_id, enabled, fake_semantic_review
):
    """作者在结构工作台采用覆盖窗口的篇章后，推导为完成，不需要手动收尾。"""
    from modules.story.outline_state.models import OutlineArc

    await _create_draft(db_session, test_project_id, status="published")
    calls: list = []
    with container_scope(
        {
            "assistant.operations": {
                "writing.generate_candidate": _fake_generate_operation(calls),
                "story.plan_structure": _fake_plan_operation(calls),
            }
        }
    ):
        view = await _start_flow(db_session, test_project_id)
        confirmation = await _create_confirmation(db_session, test_project_id)
        await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {"context_confirmation_id": str(confirmation.id)},
        )
        run = await guided_runtime._require_run(
            db_session, test_project_id, view["run_id"], OWNER
        )
        task_id = guided_runtime._artifacts(run)["candidate"]["task_id"]
        candidate = await _create_draft(
            db_session,
            test_project_id,
            status="candidate",
            provenance={"knowledge_review": {"status": "passed"}},
        )
        await _mark_task(
            db_session, task_id, status="done", result={"draft_id": str(candidate.id)}
        )
        await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
        await _adopt_candidate(db_session, test_project_id, candidate)
        await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
        await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {"choice": {"step_id": "rolling_offer", "action": "plan_ahead"}},
        )
        run = await guided_runtime._require_run(
            db_session, test_project_id, view["run_id"], OWNER
        )
        for layer, key in (
            ("threads", "thread_proposals"),
            ("arcs", "arc_proposals"),
            ("scenes", "scene_proposals"),
        ):
            await _confirm_rolling(db_session, test_project_id, view["run_id"], layer)
            artifacts = guided_runtime._artifacts(run)
            await _mark_task(
                db_session,
                artifacts[key]["task_id"],
                status="done",
                result={"apply_status": "applied"},
            )
            await guided_runtime.advance(
                db_session, test_project_id, view["run_id"], OWNER, {}
            )
        # 作者采用覆盖第 2-4 章的篇章（结构工作台既有路径，不经流程）。
        db_session.add(
            OutlineArc(
                novel_id=UUID(test_project_id),
                title="卷一",
                start_chapter=2,
                end_chapter=4,
                status="draft",
            )
        )
        await db_session.flush()
        completed = await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
    assert completed["status"] == "completed"
    assert completed["stop"] is None


async def test_rolling_planning_can_be_turned_off_before_generation(
    db_session, test_project_id, enabled, fake_semantic_review
):
    """流程设置关闭滚动规划：采用即完成（流程 2 v1 行为）。"""
    from modules.assistant.guided_flow.contracts import GuidedFlowStartRequest

    await _create_draft(db_session, test_project_id, status="published")
    calls: list = []
    with container_scope(
        {
            "assistant.operations": {
                "writing.generate_candidate": _fake_generate_operation(calls),
                "story.plan_structure": _fake_plan_operation(calls),
            }
        }
    ):
        view = await guided_runtime.start(
            db_session,
            test_project_id,
            OWNER,
            GuidedFlowStartRequest(
                novel_id=test_project_id,
                chapter_index=1,
                settings=GuidedFlowSettings(rolling_planning=False),
            ),
        )
        confirmation = await _create_confirmation(db_session, test_project_id)
        await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {"context_confirmation_id": str(confirmation.id)},
        )
        run = await guided_runtime._require_run(
            db_session, test_project_id, view["run_id"], OWNER
        )
        task_id = guided_runtime._artifacts(run)["candidate"]["task_id"]
        candidate = await _create_draft(
            db_session,
            test_project_id,
            status="candidate",
            provenance={"knowledge_review": {"status": "passed"}},
        )
        await _mark_task(
            db_session, task_id, status="done", result={"draft_id": str(candidate.id)}
        )
        await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
        await _adopt_candidate(db_session, test_project_id, candidate)
        completed = await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
    assert completed["status"] == "completed"
    assert completed["stop"] is None
    assert not [call for call in calls if "target" in call]


# ---------------------------------------------------------------------------
# 流程 1「新书开篇」：方向卡 → 骨架 → 采用 → 骨架可用
# ---------------------------------------------------------------------------


class _SkeletonArgs(BaseModel):
    vision: str
    direction_title: str | None = None
    direction: dict[str, str] | None = None


class _AdoptArgs(BaseModel):
    suggestion_id: str
    validation_run_id: str | None = None


def _fake_skeleton_operation(calls: list):
    async def prepare(db, novel_id, args, *, context=None):
        return {"vision": args.vision}

    async def apply(db, novel_id, args, preview, *, context=None):
        calls.append({"vision": args.vision, "title": args.direction_title})
        task_id = enqueue_task(db, "world_opening_skeleton", novel_id=novel_id, meta={})
        return {"task_id": task_id}

    return AssistantOperation(
        label="起草骨架",
        schema=_SkeletonArgs,
        prepare=prepare,
        apply=apply,
        permission="suggest",
    )


def _fake_adopt_operation(calls: list):
    async def prepare(db, novel_id, args, *, context=None):
        return {"suggestion_id": args.suggestion_id, "expected_preview_hash": "h" * 64}

    async def apply(db, novel_id, args, preview, *, context=None):
        calls.append({"suggestion_id": args.suggestion_id})
        return {"id": args.suggestion_id, "label": "已采用世界资料方案"}

    return AssistantOperation(
        label="采用骨架包",
        schema=_AdoptArgs,
        prepare=prepare,
        apply=apply,
        permission="confirm",
    )


def _cards_payload(batch: int = 1) -> list:
    from modules.assistant.guided_flow.direction_cards import DirectionCard

    return [
        DirectionCard(
            title=f"潮汐都市{batch}",
            genre_promise="城市奇幻",
            central_conflict="潮钟权柄之争",
            protagonist_goal="找回被收走的名字",
            world_tone="潮湿、明亮、规则透明",
            reader_promise="每章解开一层城市规则",
            main_risk="设定密度可能拖慢开篇",
        ),
        DirectionCard(
            title=f"守灯人{batch}",
            genre_promise="温情奇幻",
            central_conflict="灯塔熄灭倒计时",
            protagonist_goal="在天亮前续上灯油",
            world_tone="安静、克制",
            reader_promise="规则简单但情感厚重",
            main_risk="冲突尺度偏小",
        ),
    ]


async def _start_opening(db, novel_id: str):
    from modules.assistant.guided_flow.contracts import GuidedFlowStartRequest

    return await guided_runtime.start(
        db,
        novel_id,
        OWNER,
        GuidedFlowStartRequest(
            novel_id=novel_id, flow_id="new_book_opening", input={"vision": "潮汐城市"}
        ),
    )


async def test_opening_flow_happy_path_to_skeleton_ready(
    db_session, test_project_id, enabled, monkeypatch, fake_card_tasks
):
    """构想 → 方向卡 → 选定 → 骨架任务 → 采用 → 停在「骨架可用」。"""
    from modules.assistant.guided_flow import direction_cards

    card_calls: list = []

    async def fake_cards(db, novel_id, *, vision, genre_hint="", length_hint="", batch=1):
        card_calls.append({"vision": vision, "batch": batch})
        return _cards_payload(batch)

    monkeypatch.setattr(direction_cards, "draft_direction_cards", fake_cards)
    world_calls: list = []
    await _create_draft(db_session, test_project_id, status="published")
    with container_scope(
        {
            "assistant.operations": {
                "world.draft_opening_skeleton": _fake_skeleton_operation(world_calls),
                "world.adopt_package": _fake_adopt_operation(world_calls),
            }
        }
    ):
        view = await _start_opening(db_session, test_project_id)
        assert view["status"] == "running" and view["stop"] is None

        first = await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
        assert len(card_calls) == 1 and card_calls[0]["batch"] == 1
        assert first["stop"]["step_id"] == "choose_direction"
        assert len(first["panel"]["cards"]) == 2

        chosen = await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {
                "choice": {
                    "step_id": "choose_direction",
                    "action": "choose",
                    "card_index": 0,
                    "fields": {"central_conflict": "改后的冲突"},
                }
            },
        )
        assert chosen["status"] == "running"
        run = await guided_runtime._require_run(
            db_session, test_project_id, view["run_id"], OWNER
        )
        assert guided_runtime._artifacts(run)["chosen_direction"]["central_conflict"] == (
            "改后的冲突"
        )
        assert [call["vision"] for call in world_calls] == ["潮汐城市"]
        skeleton_task = guided_runtime._artifacts(run)["skeleton"]["task_id"]

        await _mark_task(
            db_session,
            skeleton_task,
            status="done",
            result={
                "_opening_skeleton_result": {
                    "package_suggestion_id": "pkg-1",
                    "knowledge_review_status": "passed",
                }
            },
        )
        ready = await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
        assert ready["status"] == "waiting_approval"
        assert ready["stop"]["step_id"] == "adopt_skeleton"
        assert ready["stop"]["kind"] == "author_confirm"
        assert ready["panel"]["package"]["package_suggestion_id"] == "pkg-1"

        done = await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {
                "choice": {
                    "step_id": "adopt_skeleton",
                    "action": "adopt_skeleton",
                    "expected_preview_hash": "h" * 64,
                }
            },
        )
    assert done["status"] == "completed"
    assert done["stop"]["step_id"] == "skeleton_ready"
    adopt_calls = [
        call.get("suggestion_id") for call in world_calls if "suggestion_id" in call
    ]
    assert adopt_calls == ["pkg-1"]
    # 流程终态失败关闭：不能继续推进。
    with pytest.raises(ConflictError, match="已结束"):
        await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {
                "choice": {
                    "step_id": "adopt_skeleton",
                    "action": "adopt_skeleton",
                    "expected_preview_hash": "h" * 64,
                }
            },
        )


async def test_opening_flow_more_cards_until_cap(
    db_session, test_project_id, enabled, monkeypatch, fake_card_tasks
):
    """都不满意可再要一批（新调用）；超过批数上限失败关闭。"""
    from core.errors import ConflictError
    from modules.assistant.guided_flow import direction_cards

    card_calls: list = []

    async def fake_cards(db, novel_id, *, vision, genre_hint="", length_hint="", batch=1):
        card_calls.append({"batch": batch})
        return _cards_payload(batch)

    monkeypatch.setattr(direction_cards, "draft_direction_cards", fake_cards)
    with container_scope(
        {
            "assistant.operations": {
                "world.draft_opening_skeleton": _fake_skeleton_operation([]),
                "world.adopt_package": _fake_adopt_operation([]),
            }
        }
    ):
        view = await _start_opening(db_session, test_project_id)
        await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
        await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {"choice": {"step_id": "choose_direction", "action": "more_cards"}},
        )
        second = await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
        assert len(card_calls) == 2 and card_calls[-1]["batch"] == 2
        assert second["panel"]["batch"] == 2
        await guided_runtime.advance(
            db_session,
            test_project_id,
            view["run_id"],
            OWNER,
            {"choice": {"step_id": "choose_direction", "action": "more_cards"}},
        )
        await guided_runtime.advance(
            db_session, test_project_id, view["run_id"], OWNER, {}
        )
        assert len(card_calls) == 3
        with pytest.raises(ConflictError, match="最多生成 3 批"):
            await guided_runtime.advance(
                db_session,
                test_project_id,
                view["run_id"],
                OWNER,
                {"choice": {"step_id": "choose_direction", "action": "more_cards"}},
            )


async def test_opening_flow_start_requires_vision(db_session, test_project_id, enabled):
    from modules.assistant.guided_flow.contracts import GuidedFlowStartRequest

    with pytest.raises(ValidationError, match="构想"):
        await guided_runtime.start(
            db_session,
            test_project_id,
            OWNER,
            GuidedFlowStartRequest(novel_id=test_project_id, flow_id="new_book_opening"),
        )
    with pytest.raises(ValidationError, match="章节"):
        await guided_runtime.start(
            db_session,
            test_project_id,
            OWNER,
            GuidedFlowStartRequest(
                novel_id=test_project_id,
                flow_id="new_book_opening",
                chapter_index=1,
                input={"vision": "x"},
            ),
        )
    with pytest.raises(ValidationError, match="开始输入"):
        await guided_runtime.start(
            db_session,
            test_project_id,
            OWNER,
            GuidedFlowStartRequest(
                novel_id=test_project_id, flow_id="editorial_revision", input={"x": "1"}
            ),
        )


# ---------------------------------------------------------------------------
# 流程 3「按审读意见定向修订」：选意见 → 桥接 → 候选审阅 → 改后复核
# ---------------------------------------------------------------------------


async def test_editorial_flow_happy_path_to_rechecks(
    db_session, test_project_id, enabled, monkeypatch
):
    """选意见 → 桥接任务 → 候选采用 → 自动改后复核 → 查看后完成。"""
    import modules.assistant.editorial_bridge as editorial_bridge
    from modules.assistant.guided_flow.contracts import GuidedFlowStartRequest

    bridge_calls: list = []

    async def fake_submit(db, data):
        bridge_calls.append(data)
        items = []
        for item in data.items:
            task_id = enqueue_task(
                db, "writing_comment_run", novel_id=str(data.novel_id), meta={}
            )
            items.append(
                {
                    "issue_id": str(item.issue_id),
                    "status": "queued",
                    "task_id": task_id,
                    "chapter_index": 1,
                }
            )
        return {"operation_id": str(data.operation_id), "items": items}

    recheck_calls: list = []

    async def fake_trigger(db, *, novel_id, issue_ids, adopted_draft_id):
        recheck_calls.append({"issues": list(issue_ids), "draft": adopted_draft_id})
        entries = []
        for issue_id in issue_ids:
            task_id = enqueue_task(
                db, "assistant_editorial_recheck", novel_id=novel_id, meta={}
            )
            entries.append({"issue_id": issue_id, "status": "queued", "task_id": task_id})
        return entries

    monkeypatch.setattr(editorial_bridge, "submit_issue_revision", fake_submit)
    monkeypatch.setattr(editorial_bridge, "trigger_post_adoption_rechecks", fake_trigger)
    issue_id = str(uuid.uuid4())
    view = await guided_runtime.start(
        db_session,
        test_project_id,
        OWNER,
        GuidedFlowStartRequest(novel_id=test_project_id, flow_id="editorial_revision"),
    )
    assert view["stop"]["step_id"] == "select_issues"

    bridged = await guided_runtime.advance(
        db_session,
        test_project_id,
        view["run_id"],
        OWNER,
        {
            "choice": {
                "step_id": "select_issues",
                "action": "select_issues",
                "items": [
                    {
                        "issue_id": issue_id,
                        "expected_version": 0,
                        "instruction": "按上下文改写这句",
                    }
                ],
            }
        },
    )
    assert len(bridge_calls) == 1
    # 修订任务在途：流程运行中，无停点。
    assert bridged["status"] == "running" and bridged["stop"] is None

    run = await guided_runtime._require_run(
        db_session, test_project_id, view["run_id"], OWNER
    )
    bridge_task = guided_runtime._artifacts(run)["bridge_items"]["items"][0]["task_id"]
    candidate = await _create_draft(
        db_session, test_project_id, status="candidate", provenance={}
    )
    await _mark_task(
        db_session,
        bridge_task,
        status="done",
        result={"candidate_draft_id": str(candidate.id)},
    )
    waiting = await guided_runtime.advance(
        db_session, test_project_id, view["run_id"], OWNER, {}
    )
    assert waiting["stop"]["step_id"] == "review_candidates"
    assert waiting["panel"]["items"][0]["candidate_draft_id"] == str(candidate.id)

    # 重复推进不重复桥接。
    await guided_runtime.advance(db_session, test_project_id, view["run_id"], OWNER, {})
    assert len(bridge_calls) == 1

    # 作者在写作页采用候选 → 流程自动请求改后复核。
    await _adopt_candidate(db_session, test_project_id, candidate)
    rechecked = await guided_runtime.advance(
        db_session, test_project_id, view["run_id"], OWNER, {}
    )
    assert (
        recheck_calls
        and recheck_calls[0]["draft"]
        and (recheck_calls[0]["issues"] == [issue_id])
    )
    assert rechecked["status"] == "running"
    assert rechecked["stop"] is None
    assert rechecked["panel"]["rechecks"][0]["status"] == "pending"
    recheck_task = guided_runtime._artifacts(run)["recheck_results"]["results"][0][
        "task_id"
    ]
    await _mark_task(db_session, recheck_task, status="running")
    running = await guided_runtime.advance(
        db_session, test_project_id, view["run_id"], OWNER, {}
    )
    assert running["status"] == "running" and running["stop"] is None
    assert len(recheck_calls) == 1
    await _mark_task(db_session, recheck_task, status="done")
    rechecked = await guided_runtime.advance(
        db_session, test_project_id, view["run_id"], OWNER, {}
    )
    assert rechecked["stop"]["step_id"] == "review_rechecks"

    finished = await guided_runtime.advance(
        db_session,
        test_project_id,
        view["run_id"],
        OWNER,
        {"choice": {"step_id": "review_rechecks", "action": "finish_flow"}},
    )
    assert finished["status"] == "completed"
    assert finished["stop"] is None


async def test_editorial_flow_unlocatable_items_skip_to_completion(
    db_session, test_project_id, enabled, monkeypatch
):
    """引文失效的意见不生成候选：逐条说明，复核为空，流程仍可完成。"""
    import modules.assistant.editorial_bridge as editorial_bridge
    from modules.assistant.guided_flow.contracts import GuidedFlowStartRequest

    async def fake_submit(db, data):
        items = []
        for item in data.items:
            items.append(
                {
                    "issue_id": str(item.issue_id),
                    "status": "unlocatable",
                    "chapter_index": 1,
                    "reason": "意见引文已不在当前稿中，无法定位",
                }
            )
        return {"operation_id": str(data.operation_id), "items": items}

    monkeypatch.setattr(editorial_bridge, "submit_issue_revision", fake_submit)
    view = await guided_runtime.start(
        db_session,
        test_project_id,
        OWNER,
        GuidedFlowStartRequest(novel_id=test_project_id, flow_id="editorial_revision"),
    )
    bridged = await guided_runtime.advance(
        db_session,
        test_project_id,
        view["run_id"],
        OWNER,
        {
            "choice": {
                "step_id": "select_issues",
                "action": "select_issues",
                "items": [
                    {
                        "issue_id": str(uuid.uuid4()),
                        "expected_version": 0,
                        "instruction": "处理",
                    }
                ],
            }
        },
    )
    assert bridged["panel"]["unlocatable_count"] == 1
    finished = await guided_runtime.advance(
        db_session,
        test_project_id,
        view["run_id"],
        OWNER,
        {"choice": {"step_id": "review_rechecks", "action": "finish_flow"}},
    )
    assert finished["status"] == "completed"


@pytest.fixture
def fake_card_tasks(monkeypatch):
    from infrastructure.tasks import facade as task_facade
    from modules.assistant.guided_flow import direction_cards

    original = task_facade.enqueue_operation_task

    async def snapshot(db, novel_id):
        return {"version": 1, "provider": "fake"}

    async def submit(db, **kwargs):
        result = await original(db, **kwargs)
        if kwargs["task_type"] == "assistant_direction_cards" and not result.reused:
            meta = kwargs["meta"]
            cards = await direction_cards.draft_direction_cards(
                db,
                kwargs["novel_id"],
                **{
                    name: meta["input"].get(name, "")
                    for name in ("vision", "genre_hint", "length_hint")
                },
                batch=meta["batch"],
            )
            await _mark_task(
                db,
                result.task_id,
                status="done",
                result={
                    "batch": meta["batch"],
                    "cards": [card.model_dump(mode="json") for card in cards],
                },
            )
        return result

    async def package(db, novel_id, artifact):
        task = (
            await db.get(AsyncTask, UUID(artifact["task_id"]))
            if artifact.get("task_id")
            else None
        )
        return (
            dict((task.result or {}).get("_opening_skeleton_result") or task.result or {})
            if task and task.status == "done"
            else {}
        )

    monkeypatch.setattr(guided_flows, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setattr(task_facade, "enqueue_operation_task", submit)
    monkeypatch.setattr(guided_flows, "_skeleton_package", package)


async def test_active_lookup_filters_before_limit(db_session, test_project_id, enabled):
    from modules.assistant.models import AssistantRun

    await _create_draft(db_session, test_project_id, status="published")
    original = await _start_flow(db_session, test_project_id)
    for index in range(51):
        db_session.add(
            AssistantRun(
                owner_id=UUID(OWNER),
                novel_id=UUID(test_project_id),
                status="running",
                request_hash=str(index),
                request_json={"protocol": "forecast_v1"},
            )
        )
    await db_session.flush()
    assert (await _start_flow(db_session, test_project_id))["run_id"] == original[
        "run_id"
    ]
    assert (await guided_runtime.active_run(db_session, test_project_id, OWNER))[
        "run_id"
    ] == original["run_id"]


async def test_latest_opening_recovers_completed_result_and_excludes_other_owner(
    db_session, test_project_id, enabled
):
    from modules.assistant.models import AssistantRun

    original = await _start_opening(db_session, test_project_id)
    run = await db_session.get(AssistantRun, UUID(original["run_id"]))
    run.status = "completed"
    await db_session.flush()
    assert (
        await guided_runtime.latest_run(
            db_session, test_project_id, OWNER, "new_book_opening"
        )
    )["run_id"] == original["run_id"]
    assert (
        await guided_runtime.latest_run(
            db_session, test_project_id, str(uuid.uuid4()), "new_book_opening"
        )
        is None
    )


async def test_rolling_confirmation_preserves_original_exclusions(
    db_session, test_project_id, enabled
):
    from modules.assistant.guided_flow.flows import apply_confirm_input

    with pytest.raises(ConflictError, match="排除项"):
        await apply_confirm_input(
            db_session,
            test_project_id,
            SimpleNamespace(),
            FLOWS["continue_writing"],
            {
                "context_confirmation": {
                    "excluded_asset_ids": {"entities": [str(uuid.uuid4())]}
                }
            },
            {
                "step_id": "confirm_rolling_threads",
                "context_confirmation_id": str(uuid.uuid4()),
            },
        )
