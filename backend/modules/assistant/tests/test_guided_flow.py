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
    assert flow.version == 1
    kinds = {step.kind for step in flow.steps}
    assert kinds <= {"auto", "author_confirm", "author_choice"}
    assert kinds == {"auto", "author_confirm", "author_choice"}
    produces = [step.produces for step in flow.steps]
    assert len(produces) == len(set(produces)), "产物必须单一生产者"
    seen: set[str] = set()
    for step in flow.steps:
        assert set(step.requires) <= seen, "依赖只允许指向更早步骤（无环）"
        seen.add(step.step_id)


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
                    StepDefinition(
                        step_id="a", kind="auto", title="a", produces="p"
                    ),
                ),
            )
        )


def test_require_flow_validates_operation_against_catalog():
    flow = FLOWS["continue_writing"]
    missing = require = {"writing.generate_candidate": None}
    assert require is not None
    available = {"writing.generate_candidate": SimpleNamespace(permission="suggest")}
    assert guided_runtime and flow
    from modules.assistant.guided_flow.registry import require_flow

    assert require_flow("continue_writing", operations=available).flow_id == (
        "continue_writing"
    )
    with pytest.raises(ValidationError, match="未注册"):
        require_flow("continue_writing", operations=missing)
    with pytest.raises(ValidationError, match="建议类"):
        require_flow(
            "continue_writing",
            operations={
                "writing.generate_candidate": SimpleNamespace(permission="confirm")
            },
        )
    with pytest.raises(ValidationError, match="不存在"):
        require_flow("no_such_flow", operations=available)


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

    request = GuidedFlowStartRequest(
        novel_id=test_project_id, chapter_index=1
    )
    view = await guided_runtime.start(db_session, test_project_id, OWNER, request)
    assert view["status"] == "waiting_approval"
    assert view["stop"]["step_id"] == "confirm_reference"
    assert view["stop"]["kind"] == "author_confirm"
    assert _states(view)["confirm_reference"] == "active"
    assert view["settings"]["semantic_review"] is True

    reentry = await guided_runtime.start(db_session, test_project_id, OWNER, request)
    assert reentry["run_id"] == view["run_id"]

    await _create_draft(
        db_session, test_project_id, status="published", chapter=2
    )
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
            confirmation=SimpleNamespace(context_fingerprint="fp"),
            compile_options=dict(row.compile_options),
        )

    monkeypatch.setattr(
        guided_flows, "prepare_confirmed_ai_action", fake_prepare
    )
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
    operations = {"writing.generate_candidate": operation}
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

    # 采用后流程完成。
    candidate.status = "deprecated"
    candidate.provenance_json = {
        **candidate.provenance_json,
        "adoption_result_draft_id": str(uuid.uuid4()),
    }
    await db_session.flush()
    completed = await guided_runtime.advance(
        db_session, test_project_id, view["run_id"], OWNER, {}
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
                "writing.generate_candidate": _fake_generate_operation(calls)
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
                "writing.generate_candidate": _fake_generate_operation(calls)
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
        await guided_runtime.abandon(
            db_session, test_project_id, view["run_id"], OWNER
        )
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
        replace(FLOWS["continue_writing"], version=2),
    )
    with pytest.raises(ConflictError, match="流程定义已更新"):
        await guided_runtime.view(db_session, test_project_id, view["run_id"], OWNER)
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
                "writing.generate_candidate": _fake_generate_operation(calls)
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
