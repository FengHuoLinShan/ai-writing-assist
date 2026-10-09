"""流程 2 v1「继续写下一场」：服务端注册的步骤表与产物推导（ADR-0032）。

从首页「继续第 N 章」进入：定位工作稿 → 写作页就地核对目标并完成资料确认
（复用既有确认协议与批次重验）→ 生成候选（已注册 suggest 操作，uuid5 幂等）
→ 自动接独立语义审查（既有领域任务，作者可在流程设置中关闭）→ 停在「可审阅」。
不新增 AI 能力；所有推导只读领域产物，不写回、不重复判断领域门禁。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.errors import ValidationError
from modules.assistant.guided_flow.registry import (
    FlowDefinition,
    StepDefinition,
    register,
)
from modules.evidence.facade import (
    get_confirmation_staleness,
    prepare_confirmed_ai_action,
)
from modules.writing.facade import (
    get_draft,
    get_latest_draft_for_chapter,
    submit_semantic_review,
)

FLOW_ID = "continue_writing"
FLOW_VERSION = 1

WORKING_DRAFT_STATUSES = {"draft", "published"}
_REVIEW_TASK_TYPE = "writing_semantic_review"
_GENERATE_TASK_TYPE = "writing_generate"

# 产物 → 既有领域任务类型：终态查询与已完成任务的结果引用解析使用。
ARTIFACT_TASK_TYPES = {
    "candidate": _GENERATE_TASK_TYPE,
    "semantic_review": _REVIEW_TASK_TYPE,
}

CONTINUE_WRITING = FlowDefinition(
    flow_id=FLOW_ID,
    version=FLOW_VERSION,
    title="继续写下一场",
    description=(
        "从本章工作稿继续：确认本章资料后生成正文候选，自动接独立语义审查，"
        "停在可审阅；采用与返修由你决定。"
    ),
    settings_defaults={"semantic_review": True},
    steps=(
        StepDefinition(
            step_id="confirm_reference",
            kind="author_confirm",
            title="确认本章资料",
            stop_reason=(
                "需要你确认本章资料后才能生成；可在本页就地核对或修改本章目标，"
                "再按这份资料继续。"
            ),
            produces="context_confirmation",
        ),
        StepDefinition(
            step_id="generate_candidate",
            kind="auto",
            operation="writing.generate_candidate",
            title="生成正文候选",
            produces="candidate",
            requires=("confirm_reference",),
        ),
        StepDefinition(
            step_id="semantic_review",
            kind="auto",
            domain_task=_REVIEW_TASK_TYPE,
            gated_on="semantic_review",
            title="独立语义审查",
            produces="semantic_review",
            requires=("generate_candidate",),
        ),
        StepDefinition(
            step_id="review_candidate",
            kind="author_choice",
            title="审阅候选",
            stop_reason="可审阅，待作者采用",
            produces="author_decision",
            requires=("generate_candidate", "semantic_review"),
        ),
    ),
)

register(CONTINUE_WRITING)


@dataclass
class FlowDerived:
    """一次推导的结果：步骤状态、停点与流程运行状态建议。"""

    steps: list[dict[str, Any]] = field(default_factory=list)
    stop: dict[str, Any] | None = None
    run_status: str = "running"
    candidate: dict[str, Any] | None = None
    working_draft: dict[str, Any] | None = None


def chapter_label(chapter_index: int | None) -> str:
    return f"第 {chapter_index} 章" if chapter_index else "本章"


def _satisfied(states: dict[str, str], requires: tuple[str, ...]) -> bool:
    return all(states.get(name) in {"done", "skipped"} for name in requires)


def _actions(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"action": action, "label": label} for action, label in pairs]


async def derive_continue_writing(
    db,
    novel_id: str,
    *,
    chapter_index: int,
    artifacts: dict[str, Any],
    settings: dict[str, Any],
    lifecycle: dict[str, Any],
) -> FlowDerived:
    """由领域产物的存在性与新鲜度推导步骤状态，不存当前步骤索引。

    ``lifecycle`` 是任务状态查询结果（任务 id → {status}），由运行层传入，
    保持本函数只读、无副作用。
    """
    derived = FlowDerived()
    states: dict[str, str] = {}
    details: dict[str, str] = {}

    working = await get_latest_draft_for_chapter(db, novel_id, chapter_index)
    working_ok = working is not None and working.status in WORKING_DRAFT_STATUSES
    if working is not None and working_ok:
        derived.working_draft = {
            "draft_id": str(working.id or ""),
            "status": working.status,
        }

    # confirm_reference：作者确认产物 = 既有资料确认，新鲜度只读失效信号。
    confirmation = artifacts.get("context_confirmation") or {}
    confirmation_id = str(confirmation.get("confirmation_id") or "")
    if not working_ok:
        states["confirm_reference"] = "blocked"
    elif not confirmation_id:
        states["confirm_reference"] = "active"
    else:
        record = (
            await get_confirmation_staleness(
                db,
                novel_id=novel_id,
                confirmation_ids=[confirmation_id],
            )
        ).get(confirmation_id)
        if record is None or record.get("stale"):
            # 已确认资料失效可由作者就地重新确认恢复，不判硬性阻断。
            states["confirm_reference"] = "active"
            details["confirm_reference"] = "已确认的资料有变化，请重新确认"
        else:
            states["confirm_reference"] = "done"

    # generate_candidate：产物 = 生成任务 + 候选草稿行。任务完成后候选
    # 引用从任务结果解析；产物只补引用，不改已冻结的任务回执。
    candidate = artifacts.get("candidate") or {}
    candidate_task_id = str(candidate.get("task_id") or "")
    candidate_task = lifecycle.get(candidate_task_id) or {}
    candidate_status = str(candidate_task.get("status") or "")
    candidate_contract = None
    candidate_info: dict[str, Any] = {}
    if states.get("confirm_reference") != "done":
        states["generate_candidate"] = "pending"
    elif not candidate_task_id:
        states["generate_candidate"] = "pending"
    elif candidate_status in {"", "pending", "running"}:
        states["generate_candidate"] = "active"
        details["generate_candidate"] = "正在生成正文候选"
    elif candidate_status in {"failed", "cancelled"}:
        states["generate_candidate"] = "blocked"
    else:
        result = candidate_task.get("result") or {}
        draft_id = str(candidate.get("draft_id") or result.get("draft_id") or "")
        candidate_contract = await get_draft(db, novel_id, draft_id) if draft_id else None
        adopted = _adoption_result(candidate_contract)
        if candidate_contract is None:
            states["generate_candidate"] = "blocked"
        elif adopted:
            states["generate_candidate"] = "done"
            candidate_info = {
                "draft_id": draft_id,
                "adopted_draft_id": adopted,
            }
        elif candidate_contract.status != "candidate":
            states["generate_candidate"] = "blocked"
        else:
            states["generate_candidate"] = "done"
            candidate_info = {
                "draft_id": draft_id,
                "chapter_index": candidate_contract.chapter_index,
                "title": candidate_contract.title or "",
            }
    derived.candidate = candidate_info or None

    # semantic_review：产物 = 候选 provenance 里的独立审查回执；
    # 流程设置只决定是否自动提交，作者手动完成的审查同样让该步完成。
    independent = _independent_review(candidate_contract)
    review_task_id = str((artifacts.get("semantic_review") or {}).get("task_id") or "")
    review_status = str((lifecycle.get(review_task_id) or {}).get("status") or "")
    if independent is not None:
        states["semantic_review"] = "done"
    elif not bool(settings.get("semantic_review", True)):
        states["semantic_review"] = "skipped"
    elif states.get("generate_candidate") == "done":
        if review_status in {"failed", "cancelled"}:
            states["semantic_review"] = "blocked"
        elif review_status in {"", "pending", "running"} and review_task_id:
            states["semantic_review"] = "active"
            details["semantic_review"] = "正在进行独立语义审查"
        else:
            states["semantic_review"] = "pending"
    elif states.get("generate_candidate") == "blocked":
        states["semantic_review"] = "pending"
    else:
        states["semantic_review"] = "pending"

    # review_candidate：终局作者决定（采用/返修）；采用由候选状态推导。
    if candidate_info.get("adopted_draft_id"):
        states["review_candidate"] = "done"
    elif _satisfied(states, ("generate_candidate", "semantic_review")):
        states["review_candidate"] = "active"
    elif "blocked" in (
        states.get("generate_candidate"),
        states.get("semantic_review"),
    ):
        states["review_candidate"] = "blocked"
    else:
        states["review_candidate"] = "pending"

    derived.steps = [
        {
            "step_id": step.step_id,
            "title": step.title,
            "state": states.get(step.step_id, "pending"),
            "detail": details.get(step.step_id, ""),
        }
        for step in CONTINUE_WRITING.steps
    ]
    _apply_stop(derived, states, candidate_contract, chapter_index)
    return derived


def _adoption_result(contract: object) -> str | None:
    provenance = getattr(contract, "provenance_json", None) or {}
    adopted = str(provenance.get("adoption_result_draft_id") or "")
    return adopted or None


def _independent_review(contract: object) -> dict | None:
    provenance = getattr(contract, "provenance_json", None) or {}
    review = provenance.get("independent_review")
    return review if isinstance(review, dict) and review else None


def _apply_stop(
    derived: FlowDerived,
    states: dict[str, str],
    candidate_contract: object,
    chapter_index: int,
) -> None:
    """停点只在：硬性阻断、作者确认（扩大授权）、作者选择（真实决定）。"""
    if states.get("review_candidate") == "done":
        derived.run_status = "completed"
        derived.stop = None
        return
    if states.get("generate_candidate") == "blocked":
        derived.stop = {
            "step_id": "generate_candidate",
            "kind": "blocked",
            "reason": "正文候选没有生成完成；已生成内容不会丢失，"
                "可结束本流程后重新开始。",
            "actions": _actions(
                ("open_candidate", "查看候选"), ("abandon_flow", "结束流程")
            ),
        }
        derived.run_status = "failed"
        return
    if states.get("semantic_review") == "blocked":
        derived.stop = {
            "step_id": "semantic_review",
            "kind": "blocked",
            "reason": "独立语义审查没有完成；可在候选内重新发起审查，或结束流程。",
            "actions": _actions(
                ("open_candidate", "查看候选"), ("abandon_flow", "结束流程")
            ),
        }
        derived.run_status = "failed"
        return
    if states.get("confirm_reference") == "blocked":
        derived.stop = {
            "step_id": "confirm_reference",
            "kind": "blocked",
            "reason": f"{chapter_label(chapter_index)}还没有可继续的工作稿；"
                "请先在写作页保存或采用本章正文，再重新开始流程。",
            "actions": _actions(("open_writing", "打开写作页")),
        }
        derived.run_status = "failed"
        return
    if states.get("confirm_reference") == "active":
        derived.stop = {
            "step_id": "confirm_reference",
            "kind": "author_confirm",
            "reason": CONTINUE_WRITING.steps[0].stop_reason,
            "actions": _actions(("confirm_reference", "确认本章资料")),
        }
        derived.run_status = "waiting_approval"
        return
    if states.get("review_candidate") == "active":
        derived.stop = {
            "step_id": "review_candidate",
            "kind": "author_choice",
            "reason": _review_stop_reason(candidate_contract, states),
            "actions": _actions(
                ("open_candidate", "查看候选"), ("abandon_flow", "结束流程")
            ),
        }
        derived.run_status = "waiting_approval"
        return
    derived.stop = None
    derived.run_status = "running"


def _review_stop_reason(contract: object, states: dict[str, str]) -> str:
    if states.get("semantic_review") == "skipped":
        return "正文候选已生成；本次未自动接独立审查，采用前请先在候选内完成审查。"
    review = _independent_review(contract) or {}
    blocking = int(review.get("blocking_count") or 0)
    verdict = str(review.get("verdict") or "")
    if blocking or verdict == "needs_revision":
        return f"独立审查发现 {blocking} 个必须先处理的问题；可在候选内定向返修。"
    if verdict == "incomplete":
        return "独立审查部分完成，暂不能采用；可继续审查或定向返修。"
    return CONTINUE_WRITING.steps[-1].stop_reason


async def apply_confirm_input(
    db,
    novel_id: str,
    run,
    flow: FlowDefinition,
    artifacts: dict[str, Any],
    step_input: dict[str, Any],
) -> bool:
    """作者确认输入：复用既有资料确认协议与新鲜度重验，冻结确认产物。

    返回是否写入了新产物；同一确认的重复推进是幂等空操作。已冻结确认失效时
    （推导会把停点退回确认点），作者的新确认替换旧引用，不判冲突。
    """
    from core.errors import ConflictError

    confirmation_id = str(step_input.get("context_confirmation_id") or "")
    if not confirmation_id:
        return False
    frozen = artifacts.get("context_confirmation") or {}
    frozen_id = str(frozen.get("confirmation_id") or "")
    if frozen_id == confirmation_id:
        return False
    if frozen_id:
        record = (
            await get_confirmation_staleness(
                db,
                novel_id=novel_id,
                confirmation_ids=[frozen_id],
            )
        ).get(frozen_id)
        if record is not None and not record.get("stale"):
            raise ConflictError(
                "本章资料已确认且仍有效，无需重复确认",
                code="guided_flow_confirmation_mismatch",
            )
    confirmed = await prepare_confirmed_ai_action(
        db,
        novel_id=novel_id,
        action="writing.generate",
        confirmation_id=confirmation_id,
    )
    options = dict(confirmed.compile_options or {})
    requested = options.get("requested_chapter_index", options.get("chapter_index"))
    chapter_index = int((run.request_json.get("input") or {}).get("chapter_index") or 0)
    if requested != chapter_index:
        raise ConflictError(
            "原确认不属于本流程的目标章节，请在本章重新确认资料",
            code="guided_flow_confirmation_mismatch",
        )
    artifacts["context_confirmation"] = {
        "confirmation_id": confirmation_id,
        "context_fingerprint": confirmed.confirmation.context_fingerprint,
    }
    return True


def _flow_operation_id(run, flow: FlowDefinition, step_id: str, input_fingerprint: str):
    """（流程运行、步骤、输入指纹）确定的 operation_id；重复推进不产生第二个任务。"""
    from uuid import UUID, uuid5

    return str(
        uuid5(
            UUID(str(run.id)),
            f"{flow.flow_id}:v{flow.version}:{step_id}:{input_fingerprint}",
        )
    )


async def run_auto_step(
    db,
    novel_id: str,
    owner_id: str,
    run,
    flow: FlowDefinition,
    artifacts: dict[str, Any],
    step_id: str,
    *,
    input_fingerprint: str,
) -> dict[str, Any] | None:
    """执行一个就绪的自动步骤，返回要冻结的产物片段；未就绪返回 None。"""
    if step_id == "generate_candidate":
        return await _run_generate(
            db, novel_id, owner_id, run, flow, artifacts, input_fingerprint
        )
    if step_id == "semantic_review":
        return await _run_semantic_review(
            db, novel_id, owner_id, run, flow, artifacts, input_fingerprint
        )
    raise ValidationError(f"流程 {flow.flow_id} 没有可执行的自动步骤 {step_id}")


async def _run_generate(
    db,
    novel_id: str,
    owner_id: str,
    run,
    flow: FlowDefinition,
    artifacts: dict[str, Any],
    input_fingerprint: str,
) -> dict[str, Any] | None:
    """经已注册 suggest 操作生成候选：prepare/apply 与 uuid5 幂等执行
    复用 assistant 运行协议的既有路径，不新增确认协议或预算协议。"""
    from uuid import UUID

    from core.container import get
    from core.service_keys import ASSISTANT_OPERATIONS
    from modules.assistant.contracts import AssistantOperationContext
    from modules.assistant.schemas import WorkContext

    if artifacts.get("candidate"):
        return None
    confirmation = artifacts.get("context_confirmation") or {}
    confirmation_id = str(confirmation.get("confirmation_id") or "")
    if not confirmation_id:
        return None
    chapter_index = int((run.request_json.get("input") or {}).get("chapter_index") or 0)
    working = await get_latest_draft_for_chapter(db, novel_id, chapter_index)
    continue_mode = working is not None and working.status in WORKING_DRAFT_STATUSES
    operation = get(ASSISTANT_OPERATIONS)["writing.generate_candidate"]
    arguments = {
        "chapter_index": chapter_index,
        "generation_mode": "continue" if continue_mode else "draft",
        "title": (working.title if continue_mode and working else None)
        or f"第 {chapter_index} 章",
    }
    args = operation.schema.model_validate(arguments)
    work = WorkContext(
        page="writing",
        chapter_index=chapter_index,
        scene_id=_option_uuid(confirmation.get("scene_id")),
        draft_id=UUID(str(working.id)) if continue_mode and working else None,
        context_confirmation_id=UUID(confirmation_id),
        context_confirmation_action="writing.generate",
    )
    base_context = AssistantOperationContext(str(run.id), owner_id, work)
    preview = await operation.prepare(db, novel_id, args, context=base_context)
    context = AssistantOperationContext(
        str(run.id),
        owner_id,
        work,
        operation_id=_flow_operation_id(
            run, flow, "generate_candidate", input_fingerprint
        ),
    )
    reference = await operation.apply(db, novel_id, args, preview, context=context)
    return {"task_id": str(reference["task_id"]), "draft_id": None}


async def _run_semantic_review(
    db,
    novel_id: str,
    owner_id: str,
    run,
    flow: FlowDefinition,
    artifacts: dict[str, Any],
    input_fingerprint: str,
) -> dict[str, Any] | None:
    """自动接独立语义审查：既有领域任务 writing_semantic_review，operation_id
    幂等；作者在流程设置中关闭时本步整体跳过（不提交、不计费）。"""
    if artifacts.get("semantic_review") or not bool(
        (run.checkpoint_json or {}).get("settings", {}).get("semantic_review", True)
    ):
        return None
    candidate = artifacts.get("candidate") or {}
    draft_id = str(candidate.get("draft_id") or "")
    if not draft_id:
        return None
    draft = await get_draft(db, novel_id, draft_id)
    if draft is None or draft.status != "candidate":
        return None
    receipt = await submit_semantic_review(
        db,
        novel_id=novel_id,
        draft_ids=[draft_id],
        operation_id=_flow_operation_id(
            run, flow, "semantic_review", f"{input_fingerprint}:{draft.content_hash}"
        ),
    )
    return {"task_id": str(receipt["task_id"])}


def _option_uuid(value: object):
    from uuid import UUID

    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


# 运行层派发表：新流程注册自己的推导、确认输入与自动执行（BR-4/5/6 按同一机制追加）。
DERIVERS = {FLOW_ID: derive_continue_writing}
CONFIRM_INPUT = {FLOW_ID: apply_confirm_input}
AUTO_STEPS = {FLOW_ID: run_auto_step}
