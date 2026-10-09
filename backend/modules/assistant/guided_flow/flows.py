"""服务端注册的引导流程：流程 2「继续写下一场」v2（含滚动规划）、
流程 1「新书开篇」v1、流程 3「按审读意见定向修订」v1（ADR-0032 / BR-3/4/5/6）。

三个流程的步骤表、产物推导、确认/选择输入与自动执行都在本文件注册。
推导只读领域产物的存在性与新鲜度，不存当前步骤索引；运行记录只冻结
版本、输入指纹、授权范围与停点原因。停点只在：真实选择、扩大授权、
硬性阻断。AI 输出一律是候选：方向卡只存运行检查点，骨架/规划/批注
修订都停在作者确认或既有采用门禁上。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select

from core.errors import ValidationError
from modules.assistant.editorial_contracts import (
    IssueRevisionItem,
    IssueRevisionRequest,
)
from modules.assistant.editorial_models import EditorialIssue
from modules.assistant.guided_flow.direction_cards import (
    MAX_BATCHES,
    DirectionCard,
)
from modules.assistant.guided_flow.registry import (
    FlowDefinition,
    StepDefinition,
    register,
)
from modules.assistant.schemas import StrictModel
from modules.evidence.facade import (
    get_confirmation_staleness,
    prepare_confirmed_ai_action,
)
from modules.story.facade import get_planned_chapter_coverage
from modules.writing.facade import (
    get_draft,
    get_latest_draft_for_chapter,
    submit_semantic_review,
)

# ---------------------------------------------------------------------------
# 流程 2 v2「继续写下一场」：…… → 可审阅 →（作者确认）滚动规划后续章节
# ---------------------------------------------------------------------------

FLOW_ID = "continue_writing"
FLOW_VERSION = 2

WORKING_DRAFT_STATUSES = {"draft", "published"}
_REVIEW_TASK_TYPE = "writing_semantic_review"
_GENERATE_TASK_TYPE = "writing_generate"

# 产物 → 既有领域任务类型：终态查询与已完成任务的结果引用解析使用。
ARTIFACT_TASK_TYPES = {
    "candidate": _GENERATE_TASK_TYPE,
    "semantic_review": _REVIEW_TASK_TYPE,
    "skeleton": "world_opening_skeleton",
    "thread_proposals": "outline_generate",
    "arc_proposals": "outline_generate",
    "bridge_items": "writing_comment_run",
    "recheck_results": "assistant_editorial_recheck",
}

CONTINUE_WRITING = FlowDefinition(
    flow_id=FLOW_ID,
    version=FLOW_VERSION,
    title="继续写下一场",
    description=(
        "从本章工作稿继续：确认本章资料后生成正文候选，自动接独立语义审查，"
        "停在可审阅；采用后可按你的确认滚动规划接下来几章的走向"
        "（只到剧情线与篇章候选，不生成后续正文）。"
    ),
    settings_defaults={
        "semantic_review": True,
        "rolling_planning": True,
        "planning_window": 3,
    },
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
        StepDefinition(
            step_id="rolling_offer",
            kind="author_choice",
            gated_on="rolling_planning",
            title="规划接下来几章",
            stop_reason="本章已采用。接下来几章的走向是否现在规划，由你决定。",
            produces="rolling_decision",
            requires=("review_candidate",),
        ),
        StepDefinition(
            step_id="rolling_threads",
            kind="auto",
            operation="story.plan_structure",
            title="提出后续剧情线候选",
            produces="thread_proposals",
            requires=("rolling_offer",),
        ),
        StepDefinition(
            step_id="rolling_arcs",
            kind="auto",
            operation="story.plan_structure",
            title="提出后续篇章候选",
            produces="arc_proposals",
            requires=("rolling_offer",),
        ),
        StepDefinition(
            step_id="rolling_review",
            kind="author_choice",
            title="审阅后续章节候选",
            stop_reason="后续章节候选可审阅，待作者在结构工作台逐条取舍并采用",
            produces="rolling_completion",
            requires=("rolling_threads", "rolling_arcs"),
        ),
    ),
)

register(CONTINUE_WRITING)

# ---------------------------------------------------------------------------
# 流程 1 v1「新书开篇」：一句构想 → 方向卡 → 世界观骨架 → 骨架可用
# ---------------------------------------------------------------------------

OPENING_FLOW_ID = "new_book_opening"
OPENING_FLOW_VERSION = 1

# 方向卡可编辑字段（作者选定后可修改；校验复用方向卡 schema）。
DIRECTION_FIELDS = (
    "genre_promise",
    "central_conflict",
    "protagonist_goal",
    "world_tone",
    "reader_promise",
    "main_risk",
)
# 方向卡不是注册操作，而是 Assistant 侧的定向 LLM step（direction_cards.py）；
# registry 对 domain_task 只做结构引用，不做目录校验。
_DIRECTION_CARDS_TASK = "assistant_direction_cards"

NEW_BOOK_OPENING = FlowDefinition(
    flow_id=OPENING_FLOW_ID,
    version=OPENING_FLOW_VERSION,
    title="新书开篇",
    description=(
        "从一句构想开始：生成方向卡供你挑选，再按选定方向一次生成世界观骨架；"
        "逐条取舍并采用后停在「骨架可用」，之后是否写第一章由你决定。"
    ),
    settings_defaults={},
    steps=(
        StepDefinition(
            step_id="direction_cards",
            kind="auto",
            domain_task=_DIRECTION_CARDS_TASK,
            title="生成方向卡",
            produces="direction_cards",
        ),
        StepDefinition(
            step_id="choose_direction",
            kind="author_choice",
            title="选择方向",
            stop_reason="从方向卡里选一张，可直接修改字段；都不满意可以再要一批",
            produces="chosen_direction",
            requires=("direction_cards",),
        ),
        StepDefinition(
            step_id="draft_skeleton",
            kind="auto",
            operation="world.draft_opening_skeleton",
            title="起草世界观骨架",
            produces="skeleton",
            requires=("choose_direction",),
        ),
        StepDefinition(
            step_id="adopt_skeleton",
            kind="author_confirm",
            title="确认骨架",
            stop_reason="骨架已生成，待逐条取舍与采用",
            produces="adopted_skeleton",
            requires=("draft_skeleton",),
        ),
        StepDefinition(
            step_id="skeleton_ready",
            kind="author_choice",
            title="骨架可用",
            stop_reason="世界观骨架已可用；是否继续写第一章由你决定",
            produces="next_steps",
            requires=("adopt_skeleton",),
        ),
    ),
)

register(NEW_BOOK_OPENING)

# ---------------------------------------------------------------------------
# 流程 3 v1「按审读意见定向修订」：选意见 → 桥接批注修订 → 候选审阅 → 改后复核
# ---------------------------------------------------------------------------

EDITORIAL_FLOW_ID = "editorial_revision"
EDITORIAL_FLOW_VERSION = 1

EDITORIAL_REVISION = FlowDefinition(
    flow_id=EDITORIAL_FLOW_ID,
    version=EDITORIAL_FLOW_VERSION,
    title="按审读意见定向修订",
    description=(
        "从审读台选中的意见开始：按意见的原文依据定位选区并发起批注修订，"
        "停在候选可审阅；采用后自动请求改后复核。意见仍是编辑建议，"
        "由你决定是否处理。"
    ),
    settings_defaults={},
    steps=(
        StepDefinition(
            step_id="select_issues",
            kind="author_choice",
            title="选择意见并说明处置",
            stop_reason="在审读台勾选要处理的意见，并为每条填写处置说明",
            produces="selected_issues",
        ),
        StepDefinition(
            step_id="bridge_revision",
            kind="auto",
            domain_task="writing_comment_run",
            title="发起批注修订",
            produces="bridge_items",
            requires=("select_issues",),
        ),
        StepDefinition(
            step_id="review_candidates",
            kind="author_choice",
            title="审阅替换候选",
            stop_reason="替换候选可审阅，待作者在写作页采用",
            produces="revision_decision",
            requires=("bridge_revision",),
        ),
        StepDefinition(
            step_id="post_recheck",
            kind="auto",
            domain_task="assistant_editorial_recheck",
            title="请求改后复核",
            produces="recheck_results",
            requires=("review_candidates",),
        ),
        StepDefinition(
            step_id="review_rechecks",
            kind="author_choice",
            title="查看改后复核",
            stop_reason="改后复核结果已就绪，看完即可结束本流程",
            produces="final_decision",
            requires=("post_recheck",),
        ),
    ),
)

register(EDITORIAL_REVISION)


# ---------------------------------------------------------------------------
# 共享 helpers
# ---------------------------------------------------------------------------


class OpeningStartInput(StrictModel):
    """新书开篇的开始输入：一句构想 + 可选题材/篇幅意向。"""

    vision: str = Field(min_length=1, max_length=2000)
    genre_hint: str = Field(default="", max_length=200)
    length_hint: str = Field(default="", max_length=200)


@dataclass
class FlowDerived:
    """一次推导的结果：步骤状态、停点、流程运行状态建议与作者面板。"""

    steps: list[dict[str, Any]] = field(default_factory=list)
    stop: dict[str, Any] | None = None
    run_status: str = "running"
    candidate: dict[str, Any] | None = None
    panel: dict[str, Any] | None = None


def chapter_label(chapter_index: int | None) -> str:
    return f"第 {chapter_index} 章" if chapter_index else "本章"


def _satisfied(states: dict[str, str], requires: tuple[str, ...]) -> bool:
    return all(states.get(name) in {"done", "skipped"} for name in requires)


def _actions(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"action": action, "label": label} for action, label in pairs]


def _steps_view(flow: FlowDefinition, states: dict[str, str], details: dict[str, str]):
    return [
        {
            "step_id": step.step_id,
            "title": step.title,
            "state": states.get(step.step_id, "pending"),
            "detail": details.get(step.step_id, ""),
        }
        for step in flow.steps
    ]


def _flow_operation_id(run, flow: FlowDefinition, step_id: str, input_fingerprint: str):
    """（流程运行、步骤、输入指纹）确定的 operation_id；重复推进不产生第二个任务。"""
    from uuid import uuid5

    return str(
        uuid5(
            UUID(str(run.id)),
            f"{flow.flow_id}:v{flow.version}:{step_id}:{input_fingerprint}",
        )
    )


def _option_uuid(value: object):
    from uuid import UUID as _UUID

    try:
        return _UUID(str(value)) if value else None
    except ValueError:
        return None


def _planning_window(settings: dict[str, Any]) -> int:
    try:
        window = int(settings.get("planning_window") or 3)
    except (TypeError, ValueError):
        return 3
    return min(5, max(1, window))


def _rolling_window(chapter_index: int, settings: dict[str, Any]) -> tuple[int, int]:
    """滚动规划窗口：第 N+1 至 N+K 章（K 默认 3、上限 5，BR-6）。"""
    start = chapter_index + 1
    return start, start + _planning_window(settings) - 1


def _run_input(run) -> dict[str, Any]:
    return dict((run.request_json or {}).get("input") or {})


async def _skeleton_package(db, novel_id: str, skeleton_artifact: dict) -> dict:
    """骨架任务完成后解析包引用与知识审查状态（只读任务结果）。"""
    task_id = str(skeleton_artifact.get("task_id") or "")
    if not task_id:
        return {}
    from infrastructure.tasks.facade import get_completed_task_payload

    task = await get_completed_task_payload(
        db,
        task_id=task_id,
        task_type="world_opening_skeleton",
        novel_id=novel_id,
    )
    if task is None:
        return {}
    result = dict(task.result or {})
    receipt = result.get("_opening_skeleton_result")
    if not isinstance(receipt, dict):
        receipt = result
    return {
        "package_suggestion_id": str(receipt.get("package_suggestion_id") or ""),
        "knowledge_review_status": receipt.get("knowledge_review_status"),
        "counts": {
            key: receipt.get(key)
            for key in (
                "created_entities",
                "fill_existing",
                "reference_existing",
                "attached_aliases",
                "relations",
            )
        },
    }


def _adoption_result(contract: object) -> str | None:
    provenance = getattr(contract, "provenance_json", None) or {}
    adopted = str(provenance.get("adoption_result_draft_id") or "")
    return adopted or None


# ---------------------------------------------------------------------------
# 流程 2：推导、确认输入与自动执行
# ---------------------------------------------------------------------------


async def derive_continue_writing(
    db,
    novel_id: str,
    *,
    flow_input: dict[str, Any],
    artifacts: dict[str, Any],
    settings: dict[str, Any],
    lifecycle: dict[str, Any],
) -> FlowDerived:
    """由领域产物的存在性与新鲜度推导步骤状态，不存当前步骤索引。

    ``lifecycle`` 是任务状态查询结果（任务 id → {status, result}），由运行
    层传入，保持本函数只读、无副作用。
    """
    derived = FlowDerived()
    states: dict[str, str] = {}
    details: dict[str, str] = {}
    chapter_index = int(flow_input.get("chapter_index") or 0)

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

    # review_candidate：本章终局作者决定（采用/返修）；采用由候选状态推导。
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

    # 滚动规划段：覆盖查询只在已采用或已确认规划后才需要（避免轮询空转）。
    need_coverage = bool(artifacts.get("rolling_decision")) or (
        states.get("review_candidate") == "done"
    )
    derived.panel = await _rolling_panel(
        db,
        novel_id,
        chapter_index,
        artifacts,
        settings,
        need_coverage=need_coverage,
    )
    _derive_rolling(
        chapter_index,
        artifacts,
        settings,
        lifecycle,
        states,
        details,
        derived,
    )

    derived.steps = _steps_view(CONTINUE_WRITING, states, details)
    _apply_stop(
        derived,
        states,
        candidate_contract,
        chapter_index,
        flow_completed=bool(artifacts.get("flow_completion")),
    )
    return derived


async def _rolling_panel(
    db,
    novel_id: str,
    chapter_index: int,
    artifacts: dict[str, Any],
    settings: dict[str, Any],
    *,
    need_coverage: bool,
) -> dict[str, Any] | None:
    """滚动规划段的作者面板：窗口、前方已规划章数（含补窗提示）与任务引用。"""
    if not chapter_index:
        return None
    decision = artifacts.get("rolling_decision") or {}
    window_start, window_end = _rolling_window(chapter_index, settings)
    covered: list[int] = []
    if need_coverage:
        coverage = await get_planned_chapter_coverage(
            db,
            novel_id,
            start_chapter=window_start,
            end_chapter=window_end,
        )
        covered = list(coverage.get("chapters") or [])
    return {
        "rolling": {
            "chapter_index": chapter_index,
            "window": {"start": window_start, "end": window_end},
            "window_size": _planning_window(settings),
            "accepted": bool(decision.get("accepted")),
            "planned_chapters": len(covered),
            "covered_chapters": covered,
            "proposals": {
                key: str((artifacts.get(key) or {}).get("task_id") or "")
                for key in ("thread_proposals", "arc_proposals")
            },
        }
    }


def _derive_rolling(
    chapter_index: int,
    artifacts: dict[str, Any],
    settings: dict[str, Any],
    lifecycle: dict[str, Any],
    states: dict[str, str],
    details: dict[str, str],
    derived: FlowDerived,
) -> None:
    """滚动规划段的状态推导；只读产物与任务生命周期，不写任何状态。"""
    decision = artifacts.get("rolling_decision") or {}
    rolling_on = bool(settings.get("rolling_planning", True))
    flow_completed = bool(artifacts.get("flow_completion"))

    if decision.get("accepted") is True:
        states["rolling_offer"] = "done"
    elif not rolling_on or flow_completed:
        states["rolling_offer"] = (
            "skipped" if states.get("review_candidate") == "done" else "pending"
        )
    elif decision.get("accepted") is False:
        states["rolling_offer"] = "skipped"
    elif states.get("review_candidate") == "done":
        states["rolling_offer"] = "active"
    else:
        states["rolling_offer"] = "pending"

    if states.get("rolling_offer") != "done":
        for step_id in ("rolling_threads", "rolling_arcs", "rolling_review"):
            states[step_id] = (
                "skipped" if states.get("rolling_offer") == "skipped" else "pending"
            )
        return

    for step_id, key in (
        ("rolling_threads", "thread_proposals"),
        ("rolling_arcs", "arc_proposals"),
    ):
        artifact = artifacts.get(key) or {}
        task_id = str(artifact.get("task_id") or "")
        status = str((lifecycle.get(task_id) or {}).get("status") or "")
        if not task_id:
            states[step_id] = "pending"
        elif status in {"pending", "running"}:
            states[step_id] = "active"
            details[step_id] = "正在生成候选"
        elif status in {"failed", "cancelled"}:
            states[step_id] = "blocked"
        else:
            states[step_id] = "done"

    if "blocked" in (states.get("rolling_threads"), states.get("rolling_arcs")):
        states["rolling_review"] = "blocked"
        return
    if not _satisfied(states, ("rolling_threads", "rolling_arcs")):
        states["rolling_review"] = "pending"
        return
    if flow_completed:
        states["rolling_review"] = "skipped"
        return
    covered = set(_window_coverage(derived.panel))
    window_start, window_end = _rolling_window(chapter_index, settings)
    if set(range(window_start, window_end + 1)) <= covered:
        states["rolling_review"] = "done"
    else:
        states["rolling_review"] = "active"


def _window_coverage(panel: dict[str, Any] | None) -> list[int]:
    rolling = (panel or {}).get("rolling") or {}
    return list(rolling.get("covered_chapters") or [])


def _apply_stop(
    derived: FlowDerived,
    states: dict[str, str],
    candidate_contract: object,
    chapter_index: int,
    *,
    flow_completed: bool = False,
) -> None:
    """停点只在：硬性阻断、作者确认（扩大授权）、作者选择（真实决定）。"""
    rolling = (derived.panel or {}).get("rolling") or {}
    if flow_completed:
        derived.run_status = "completed"
        derived.stop = None
        return
    if states.get("rolling_review") == "done":
        derived.run_status = "completed"
        derived.stop = None
        return
    if states.get("rolling_offer") == "skipped" and states.get(
        "review_candidate"
    ) == "done":
        derived.run_status = "completed"
        derived.stop = None
        return
    if states.get("rolling_review") == "active":
        window = rolling.get("window") or {}
        derived.stop = {
            "step_id": "rolling_review",
            "kind": "author_choice",
            "reason": (
                f"第 {window.get('start')} 至 {window.get('end')} 章的剧情线与"
                "篇章候选已生成；请在结构工作台逐条取舍并采用，"
                "采用齐全后本流程完成，也可以直接结束。"
            ),
            "actions": _actions(
                ("open_outline", "打开结构工作台"),
                ("finish_flow", "完成流程"),
                ("abandon_flow", "结束流程"),
            ),
        }
        derived.run_status = "waiting_approval"
        return
    if (
        states.get("rolling_threads") == "blocked"
        or states.get("rolling_arcs") == "blocked"
    ):
        derived.stop = {
            "step_id": (
                "rolling_threads"
                if states.get("rolling_threads") == "blocked"
                else "rolling_arcs"
            ),
            "kind": "blocked",
            "reason": "后续章节的规划候选没有生成完成；已写正文与已有规划不受影响，"
                "可结束本流程后从结构工作台重新规划。",
            "actions": _actions(
                ("finish_flow", "完成流程"), ("abandon_flow", "结束流程")
            ),
        }
        derived.run_status = "failed"
        return
    if states.get("rolling_offer") == "active":
        derived.stop = {
            "step_id": "rolling_offer",
            "kind": "author_choice",
            "reason": _rolling_offer_reason(rolling, chapter_index),
            "actions": _actions(
                ("plan_ahead", "规划接下来几章"),
                ("decline", "先不用"),
                ("abandon_flow", "结束流程"),
            ),
        }
        derived.run_status = "waiting_approval"
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


def _rolling_offer_reason(rolling: dict[str, Any], chapter_index: int) -> str:
    planned = int(rolling.get("planned_chapters") or 0)
    window = rolling.get("window") or {}
    size = int(rolling.get("window_size") or 3)
    base = (
        f"第 {chapter_index} 章已采用。"
        f"接下来的第 {window.get('start')} 至 {window.get('end')} 章，"
        "可以生成剧情线与篇章候选（每层一次模型调用，只到大纲级，不生成正文）。"
    )
    if planned < 2:
        return base + f"后方已规划 {planned} 章，不足 2 章；建议现在补足到 {size} 章。"
    return base + f"后方已有 {planned} 章规划。"


def _independent_review(contract: object) -> dict | None:
    provenance = getattr(contract, "provenance_json", None) or {}
    review = provenance.get("independent_review")
    return review if isinstance(review, dict) and review else None


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
    return CONTINUE_WRITING.steps[3].stop_reason


async def apply_continue_choice(
    db,
    novel_id: str,
    run,
    flow: FlowDefinition,
    artifacts: dict[str, Any],
    settings: dict[str, Any],
    choice: dict[str, Any],
) -> bool:
    """流程 2 的作者选择：是否滚动规划接下来几章、完成流程。"""
    action = str(choice.get("action") or "")
    if action in {"plan_ahead", "decline"}:
        if artifacts.get("rolling_decision"):
            return False
        chapter_index = int(_run_input(run).get("chapter_index") or 0)
        if not chapter_index:
            raise ValidationError("本流程没有目标章节，不能滚动规划")
        artifacts["rolling_decision"] = {
            "accepted": action == "plan_ahead",
            "at_chapter": chapter_index,
            "window": _planning_window(settings),
        }
        return True
    if action == "finish_flow":
        artifacts["flow_completion"] = {"step_id": str(choice.get("step_id") or "")}
        return True
    raise ValidationError("这个停点不接受该选择")


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
    chapter_index = int(_run_input(run).get("chapter_index") or 0)
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
    if step_id in {"rolling_threads", "rolling_arcs"}:
        return await _run_rolling_plan(
            db,
            novel_id,
            owner_id,
            run,
            flow,
            artifacts,
            step_id,
            input_fingerprint=input_fingerprint,
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
    from uuid import UUID as _UUID

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
    chapter_index = int(_run_input(run).get("chapter_index") or 0)
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
        draft_id=_UUID(str(working.id)) if continue_mode and working else None,
        context_confirmation_id=_UUID(confirmation_id),
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


_ROLLING_TARGETS = {
    "rolling_threads": "plot_thread",
    "rolling_arcs": "outline_arc",
}


def _rolling_instruction(chapter_index: int, window_start: int, window_end: int) -> str:
    return (
        f"滚动规划：作者刚采用第 {chapter_index} 章，"
        f"请规划第 {window_start} 至 {window_end} 章的走向。"
        "只提出这个窗口需要的条目，保持克制；"
        "不得把已写成正文的章节当成未来规划。"
    )


async def _run_rolling_plan(
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
    """滚动规划层任务：经已注册的 story.plan_structure（rolling_window）提交。

    只在作者于 rolling_offer 停点确认后到达；确定性回执由（作品、窗口、层）
    决定（story 侧 _window_operation_id），同一窗口重复推进不产生第二个任务。
    已有已采用篇章覆盖窗口时由 story 侧改为修订建议，不重复新建。
    """
    from core.container import get
    from core.service_keys import ASSISTANT_OPERATIONS
    from modules.assistant.contracts import AssistantOperationContext
    from modules.assistant.schemas import WorkContext

    produces = "thread_proposals" if step_id == "rolling_threads" else "arc_proposals"
    if artifacts.get(produces):
        return None
    decision = artifacts.get("rolling_decision") or {}
    chapter_index = int(decision.get("at_chapter") or 0)
    if not chapter_index or not decision.get("accepted"):
        # 作者拒绝或尚未确认：这一步整体不执行，也不提交任何任务。
        return None
    window_start = chapter_index + 1
    window_end = window_start + int(decision.get("window") or 3) - 1
    operation = get(ASSISTANT_OPERATIONS)["story.plan_structure"]
    args = operation.schema.model_validate(
        {
            "target": _ROLLING_TARGETS[step_id],
            "mode": "create",
            "instruction": _rolling_instruction(
                chapter_index, window_start, window_end
            ),
            "start_chapter": window_start,
        }
    )
    context = AssistantOperationContext(
        str(run.id),
        owner_id,
        WorkContext(page="outline", scope="project"),
        operation_id=_flow_operation_id(
            run, flow, step_id, f"{input_fingerprint}:{window_start}:{window_end}"
        ),
    )
    preview = await operation.prepare(db, novel_id, args, context=context)
    reference = await operation.apply(db, novel_id, args, preview, context=context)
    return {"task_id": str(reference["task_id"])}


# ---------------------------------------------------------------------------
# 流程 1：推导、选择输入与自动执行
# ---------------------------------------------------------------------------


async def derive_new_book_opening(
    db,
    novel_id: str,
    *,
    flow_input: dict[str, Any],
    artifacts: dict[str, Any],
    settings: dict[str, Any],
    lifecycle: dict[str, Any],
) -> FlowDerived:
    derived = FlowDerived()
    states: dict[str, str] = {}
    details: dict[str, str] = {}

    cards = artifacts.get("direction_cards") or {}
    if cards:
        states["direction_cards"] = "done"
    else:
        states["direction_cards"] = "active"
        details["direction_cards"] = "正在生成方向卡"

    chosen = artifacts.get("chosen_direction") or {}
    if chosen:
        states["choose_direction"] = "done"
    elif cards:
        states["choose_direction"] = "active"
    else:
        states["choose_direction"] = "pending"

    skeleton = artifacts.get("skeleton") or {}
    skeleton_task_id = str(skeleton.get("task_id") or "")
    skeleton_status = str((lifecycle.get(skeleton_task_id) or {}).get("status") or "")
    if artifacts.get("adopted_skeleton"):
        states["draft_skeleton"] = "done"
    elif not chosen:
        states["draft_skeleton"] = "pending"
    elif skeleton_status in {"failed", "cancelled"}:
        states["draft_skeleton"] = "blocked"
    elif skeleton_status in {"", "pending", "running"}:
        states["draft_skeleton"] = "active"
        details["draft_skeleton"] = "正在生成世界观骨架"
    else:
        states["draft_skeleton"] = "done"

    package: dict[str, Any] = {}
    if skeleton_status == "done" or artifacts.get("adopted_skeleton"):
        package = await _skeleton_package(db, novel_id, skeleton)

    if artifacts.get("adopted_skeleton"):
        states["adopt_skeleton"] = "done"
        states["skeleton_ready"] = "done"
    elif states.get("draft_skeleton") == "done":
        if str(package.get("knowledge_review_status") or "") == "blocked":
            states["adopt_skeleton"] = "blocked"
            details["adopt_skeleton"] = "知识审查未通过，包不能采用"
        else:
            states["adopt_skeleton"] = "active"
            states["skeleton_ready"] = "pending"
    elif states.get("draft_skeleton") == "blocked":
        states["adopt_skeleton"] = "blocked"
        states["skeleton_ready"] = "pending"
    else:
        states["adopt_skeleton"] = "pending"
        states["skeleton_ready"] = "pending"

    derived.panel = {
        "vision": str(flow_input.get("vision") or ""),
        "cards": list(cards.get("cards") or []),
        "batch": int(cards.get("batch") or 1),
        "more_allowed": int(cards.get("batch") or 1) < MAX_BATCHES,
        "chosen": chosen or None,
        "package": package or None,
        "adopted": artifacts.get("adopted_skeleton") or None,
    }
    derived.steps = _steps_view(NEW_BOOK_OPENING, states, details)
    _apply_opening_stop(derived, states, package)
    return derived


def _apply_opening_stop(
    derived: FlowDerived, states: dict[str, str], package: dict[str, Any]
) -> None:
    if states.get("skeleton_ready") == "done":
        derived.run_status = "completed"
        derived.stop = {
            "step_id": "skeleton_ready",
            "kind": "author_choice",
            "reason": "世界观骨架已可用（已逐条取舍并采用）；"
                "接下来可以生成故事总纲建议、继续深化世界观，或开始写第一章。",
            "actions": _actions(
                ("open_outline_suggestion", "生成故事总纲建议"),
                ("open_world_deepen", "继续深化世界观"),
                ("start_first_chapter", "开始写第一章"),
            ),
        }
        return
    if states.get("adopt_skeleton") == "blocked":
        blocked_review = str((package or {}).get("knowledge_review_status") or "") == (
            "blocked"
        )
        derived.stop = {
            "step_id": "adopt_skeleton",
            "kind": "blocked",
            "reason": (
                "骨架包的知识审查未通过：包可以查看但不能采用，请结束流程后"
                "重新开始并生成新骨架。"
                if blocked_review
                else "世界观骨架没有生成完成；已生成内容不会丢失，可结束流程后重试。"
            ),
            "actions": _actions(
                ("open_package", "查看骨架包"), ("abandon_flow", "结束流程")
            ),
        }
        derived.run_status = "failed"
        return
    if states.get("draft_skeleton") == "blocked":
        derived.stop = {
            "step_id": "draft_skeleton",
            "kind": "blocked",
            "reason": "世界观骨架没有生成完成；已生成内容不会丢失，可结束流程后重试。",
            "actions": _actions(("abandon_flow", "结束流程")),
        }
        derived.run_status = "failed"
        return
    if states.get("adopt_skeleton") == "active":
        derived.stop = {
            "step_id": "adopt_skeleton",
            "kind": "author_confirm",
            "reason": NEW_BOOK_OPENING.steps[3].stop_reason
            + "；可先在世界书页逐条取舍（排除、改名、简介，冲突逐条标出），"
            "再采用所选条目。",
            "actions": _actions(
                ("open_package", "逐条查看与取舍"),
                ("adopt_skeleton", "采用所选条目"),
                ("abandon_flow", "结束流程"),
            ),
        }
        derived.run_status = "waiting_approval"
        return
    if states.get("choose_direction") == "active":
        derived.stop = {
            "step_id": "choose_direction",
            "kind": "author_choice",
            "reason": NEW_BOOK_OPENING.steps[1].stop_reason
            + "（再要一批会产生一次模型调用）。",
            "actions": _actions(
                ("more_cards", "再要一批方向卡"), ("abandon_flow", "结束流程")
            ),
        }
        derived.run_status = "waiting_approval"
        return
    derived.stop = None
    derived.run_status = "running"


async def apply_opening_choice(
    db,
    novel_id: str,
    run,
    flow: FlowDefinition,
    artifacts: dict[str, Any],
    settings: dict[str, Any],
    choice: dict[str, Any],
) -> bool:
    """新书开篇的作者选择：选方向卡、再要一批、采用骨架、完成流程。"""
    from core.errors import ConflictError

    action = str(choice.get("action") or "")
    if action == "more_cards":
        cards = artifacts.get("direction_cards") or {}
        batch = int(cards.get("batch") or 1)
        if batch >= MAX_BATCHES:
            raise ConflictError(
                f"方向卡最多生成 {MAX_BATCHES} 批；请从现有方向里挑选或结束流程"
            )
        artifacts.pop("direction_cards", None)
        artifacts["direction_request"] = {"batch": batch + 1}
        return True
    if action == "choose":
        cards = list((artifacts.get("direction_cards") or {}).get("cards") or [])
        try:
            index = int(choice.get("card_index", -1))
        except (TypeError, ValueError):
            index = -1
        if not cards or not 0 <= index < len(cards):
            raise ValidationError("请从当前方向卡里选择一张")
        merged = {**cards[index], **(choice.get("fields") or {})}
        card = DirectionCard.model_validate(merged)
        artifacts["chosen_direction"] = card.model_dump(mode="json")
        return True
    if action == "adopt_skeleton":
        return await _apply_adopt_skeleton(db, novel_id, run, flow, artifacts)
    if action == "finish_flow":
        artifacts["flow_completion"] = {"step_id": str(choice.get("step_id") or "")}
        return True
    raise ValidationError("这个停点不接受该选择")


async def _apply_adopt_skeleton(
    db, novel_id: str, run, flow: FlowDefinition, artifacts: dict[str, Any]
) -> bool:
    """作者确认采用骨架：经既有 confirm 操作 world.adopt_package，
    prepare/apply 复验采用范围与知识门禁；同一包重复确认是幂等空操作。"""
    from core.container import get
    from core.service_keys import ASSISTANT_OPERATIONS
    from modules.assistant.contracts import AssistantOperationContext
    from modules.assistant.schemas import WorkContext

    if artifacts.get("adopted_skeleton"):
        return False
    package = await _skeleton_package(db, novel_id, artifacts.get("skeleton") or {})
    suggestion_id = str(package.get("package_suggestion_id") or "")
    if not suggestion_id:
        raise ValidationError("骨架包还没有生成完成，不能采用")
    operation = get(ASSISTANT_OPERATIONS)["world.adopt_package"]
    args = operation.schema.model_validate({"suggestion_id": suggestion_id})
    context = AssistantOperationContext(
        str(run.id),
        str(run.owner_id),
        WorkContext(page="world", scope="project"),
        operation_id=_flow_operation_id(
            run, flow, "adopt_skeleton", str(run.request_hash)
        ),
    )
    preview = await operation.prepare(db, novel_id, args, context=context)
    reference = await operation.apply(db, novel_id, args, preview, context=context)
    artifacts["adopted_skeleton"] = {
        "package_id": str(reference.get("id") or suggestion_id),
    }
    return True


async def run_opening_auto_step(
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
    if step_id == "direction_cards":
        return await _run_direction_cards(db, novel_id, run, artifacts)
    if step_id == "draft_skeleton":
        return await _run_draft_skeleton(
            db, novel_id, owner_id, run, flow, artifacts, input_fingerprint
        )
    raise ValidationError(f"流程 {flow.flow_id} 没有可执行的自动步骤 {step_id}")


async def _run_direction_cards(
    db, novel_id, run, artifacts: dict[str, Any]
) -> dict[str, Any] | None:
    """方向卡 step：一次结构化调用；卡片只存运行检查点，不是资产。"""
    from modules.assistant.guided_flow import direction_cards

    if artifacts.get("direction_cards"):
        return None
    flow_input = _run_input(run)
    request = artifacts.get("direction_request") or {}
    batch = int(request.get("batch") or 1)
    cards = await direction_cards.draft_direction_cards(
        db,
        novel_id,
        vision=str(flow_input.get("vision") or ""),
        genre_hint=str(flow_input.get("genre_hint") or ""),
        length_hint=str(flow_input.get("length_hint") or ""),
        batch=batch,
    )
    return {
        "batch": batch,
        "cards": [card.model_dump(mode="json") for card in cards],
    }


async def _run_draft_skeleton(
    db,
    novel_id: str,
    owner_id: str,
    run,
    flow: FlowDefinition,
    artifacts: dict[str, Any],
    input_fingerprint: str,
) -> dict[str, Any] | None:
    """世界观骨架：经已注册 suggest 操作 world.draft_opening_skeleton 入队
    World 自有任务；operation_id 由（运行、步骤、输入指纹）确定。"""
    from core.container import get
    from core.service_keys import ASSISTANT_OPERATIONS
    from modules.assistant.contracts import AssistantOperationContext
    from modules.assistant.schemas import WorkContext

    if artifacts.get("skeleton"):
        return None
    chosen = artifacts.get("chosen_direction") or {}
    if not chosen:
        return None
    flow_input = _run_input(run)
    operation = get(ASSISTANT_OPERATIONS)["world.draft_opening_skeleton"]
    args = operation.schema.model_validate(
        {
            "vision": str(flow_input.get("vision") or ""),
            "direction_title": str(chosen.get("title") or ""),
            "direction": {
                field_name: str(chosen.get(field_name) or "")
                for field_name in DIRECTION_FIELDS
            },
        }
    )
    context = AssistantOperationContext(
        str(run.id),
        owner_id,
        WorkContext(page="today", scope="project"),
        operation_id=_flow_operation_id(run, flow, "draft_skeleton", input_fingerprint),
    )
    preview = await operation.prepare(db, novel_id, args, context=context)
    reference = await operation.apply(db, novel_id, args, preview, context=context)
    return {"task_id": str(reference["task_id"])}


# ---------------------------------------------------------------------------
# 流程 3：推导、选择输入与自动执行
# ---------------------------------------------------------------------------


async def derive_editorial_revision(
    db,
    novel_id: str,
    *,
    flow_input: dict[str, Any],
    artifacts: dict[str, Any],
    settings: dict[str, Any],
    lifecycle: dict[str, Any],
) -> FlowDerived:
    derived = FlowDerived()
    states: dict[str, str] = {}
    details: dict[str, str] = {}

    selected = artifacts.get("selected_issues") or {}
    items = list(selected.get("items") or [])
    if items:
        states["select_issues"] = "done"
    else:
        states["select_issues"] = "active"

    bridge = artifacts.get("bridge_items") or {}
    bridge_items = list(bridge.get("items") or [])
    unlocatable_count = 0
    if bridge_items:
        queued = [item for item in bridge_items if item.get("status") == "queued"]
        unlocatable_count = sum(
            1 for item in bridge_items if item.get("status") == "unlocatable"
        )
        in_flight = any(
            str((lifecycle.get(str(item.get("task_id"))) or {}).get("status") or "")
            in {"pending", "running"}
            for item in queued
        )
        failed = [
            item
            for item in queued
            if str((lifecycle.get(str(item.get("task_id"))) or {}).get("status") or "")
            in {"failed", "cancelled"}
        ]
        if in_flight:
            states["bridge_revision"] = "active"
            details["bridge_revision"] = "批注修订进行中"
        elif queued and len(failed) == len(queued):
            states["bridge_revision"] = "blocked"
        else:
            states["bridge_revision"] = "done"
    elif items:
        states["bridge_revision"] = "active"
        details["bridge_revision"] = "正在发起批注修订"
    else:
        states["bridge_revision"] = "pending"

    tracked = await _revision_items_status(db, novel_id, bridge_items, lifecycle)
    decision = artifacts.get("revision_decision") or {}
    ready = [item for item in tracked if item["kind"] == "ready"]
    if states.get("bridge_revision") != "done":
        states["review_candidates"] = "pending"
    elif decision.get("proceed") or not ready or not tracked:
        states["review_candidates"] = "done"
    else:
        states["review_candidates"] = "active"

    if artifacts.get("recheck_results"):
        states["post_recheck"] = "done"
    elif states.get("review_candidates") == "done":
        states["post_recheck"] = "active"
        details["post_recheck"] = "正在请求改后复核"
    else:
        states["post_recheck"] = "pending"

    if artifacts.get("flow_completion"):
        states["review_rechecks"] = "skipped"
    elif states.get("post_recheck") == "done":
        states["review_rechecks"] = "active"
    else:
        states["review_rechecks"] = "pending"

    derived.panel = {
        "items": tracked,
        "unlocatable_count": unlocatable_count,
        "rechecks": await _recheck_view(
            db,
            novel_id,
            list(
                (artifacts.get("recheck_results") or {}).get("results") or []
            ),
            lifecycle,
        ),
    }
    derived.steps = _steps_view(EDITORIAL_REVISION, states, details)
    _apply_editorial_stop(derived, states, tracked)
    return derived


async def _revision_items_status(
    db, novel_id: str, bridge_items: list[dict[str, Any]], lifecycle: dict[str, Any]
) -> list[dict[str, Any]]:
    """把桥接回执解析成作者面板条目：就绪 / 已采用 / 未生成 / 失败 / 未定位。"""
    tracked: list[dict[str, Any]] = []
    for item in bridge_items:
        entry = {
            "issue_id": str(item.get("issue_id") or ""),
            "status": str(item.get("status") or ""),
            "chapter_index": item.get("chapter_index"),
            "reason": str(item.get("reason") or ""),
            "candidate_draft_id": "",
            "kind": item.get("status"),
        }
        task_id = str(item.get("task_id") or "")
        if task_id and entry["status"] == "queued":
            task = lifecycle.get(task_id) or {}
            status = str(task.get("status") or "")
            result = task.get("result") or {}
            draft_id = str(result.get("candidate_draft_id") or "")
            if status == "done" and draft_id:
                entry["candidate_draft_id"] = draft_id
                contract = await get_draft(db, novel_id, draft_id)
                if contract is not None and _adoption_result(contract):
                    entry["kind"] = "adopted"
                else:
                    entry["kind"] = "ready"
            elif status == "done":
                entry["kind"] = "empty"
                entry["reason"] = (
                    entry["reason"] or "这次没有生成替换候选（正文可能在修订期间又变化）"
                )
            elif status in {"failed", "cancelled"}:
                entry["kind"] = "failed"
                entry["reason"] = entry["reason"] or "修订任务未完成"
            else:
                entry["kind"] = "running"
        tracked.append(entry)
    return tracked


async def _recheck_view(
    db,
    novel_id: str,
    entries: list[dict[str, Any]],
    lifecycle: dict[str, Any],
) -> list[dict[str, Any]]:
    """改后复核结果的作者视图：任务终态 + 意见上最近一次复核结论。"""
    if not entries:
        return []
    issue_ids = [_option_uuid(entry.get("issue_id")) for entry in entries]
    known = [value for value in issue_ids if value is not None]
    rows: dict[str, EditorialIssue] = {}
    if known:
        found = (
            await db.scalars(
                select(EditorialIssue).where(
                    EditorialIssue.novel_id == UUID(novel_id),
                    EditorialIssue.id.in_(known),
                )
            )
        ).all()
        rows = {str(row.id): row for row in found}
    verdict_labels = {
        "still": "仍在",
        "possibly_improved": "可能改善",
        "unknown": "无法判断",
    }
    view = []
    for entry in entries:
        task_id = str(entry.get("task_id") or "")
        status = str(entry.get("status") or "")
        if task_id:
            status = str((lifecycle.get(task_id) or {}).get("status") or status)
        verdict = ""
        reason = str(entry.get("reason") or "")
        row = rows.get(str(entry.get("issue_id") or ""))
        if row is not None and row.recheck_json:
            latest = row.recheck_json[-1] or {}
            verdict = str(latest.get("verdict") or "")
            reason = reason or str(latest.get("reason") or "")
        view.append(
            {
                "issue_id": str(entry.get("issue_id") or ""),
                "status": status,
                "verdict": verdict,
                "verdict_label": verdict_labels.get(verdict, ""),
                "reason": reason,
            }
        )
    return view


def _apply_editorial_stop(
    derived: FlowDerived,
    states: dict[str, str],
    tracked: list[dict[str, Any]],
) -> None:
    if states.get("review_rechecks") in {"done", "skipped"}:
        derived.run_status = "completed"
        derived.stop = None
        return
    if states.get("review_rechecks") == "active":
        derived.stop = {
            "step_id": "review_rechecks",
            "kind": "author_choice",
            "reason": "改后复核结果已就绪；结论只有「仍在 / 可能改善 / 无法判断」，"
                "供你决定下一步，不会自动改稿。",
            "actions": _actions(
                ("finish_flow", "完成流程"), ("abandon_flow", "结束流程")
            ),
        }
        derived.run_status = "waiting_approval"
        return
    if states.get("post_recheck") == "active":
        derived.run_status = "running"
        derived.stop = None
        return
    if states.get("review_candidates") == "active":
        ready = [item for item in tracked if item["kind"] == "ready"]
        adopted = [item for item in tracked if item["kind"] == "adopted"]
        failed = [
            item for item in tracked if item["kind"] in {"failed", "empty"}
        ]
        unlocatable = [item for item in tracked if item["status"] == "unlocatable"]
        reason = (
            f"已生成 {len(ready)} 个替换候选，待你在写作页审阅采用；"
            f"已采用 {len(adopted)} 个。"
        )
        if failed:
            reason += f" {len(failed)} 个修订没有生成候选。"
        if unlocatable:
            reason += f" {len(unlocatable)} 条意见的引文已不在当前稿，未生成候选。"
        derived.stop = {
            "step_id": "review_candidates",
            "kind": "author_choice",
            "reason": reason + " 采用后自动请求改后复核。",
            "actions": _actions(
                ("open_candidate", "去审阅候选"),
                ("proceed", "对已采用的发起改后复核"),
                ("abandon_flow", "结束流程"),
            ),
        }
        derived.run_status = "waiting_approval"
        return
    if states.get("bridge_revision") == "blocked":
        derived.stop = {
            "step_id": "bridge_revision",
            "kind": "blocked",
            "reason": "批注修订没有完成（正文可能在修订期间又变化）；"
                "意见与正文都不受影响，可结束流程后重新审读、重新发起。",
            "actions": _actions(("abandon_flow", "结束流程")),
        }
        derived.run_status = "failed"
        return
    if states.get("select_issues") == "active":
        derived.stop = {
            "step_id": "select_issues",
            "kind": "author_choice",
            "reason": EDITORIAL_REVISION.steps[0].stop_reason
            + "；发起修订会产生模型调用费用。",
            "actions": _actions(("abandon_flow", "结束流程")),
        }
        derived.run_status = "waiting_approval"
        return
    derived.stop = None
    derived.run_status = "running"


async def apply_editorial_choice(
    db,
    novel_id: str,
    run,
    flow: FlowDefinition,
    artifacts: dict[str, Any],
    settings: dict[str, Any],
    choice: dict[str, Any],
) -> bool:
    """流程 3 的作者选择：选中意见、对已采用候选进入复核、完成流程。"""
    from core.errors import ConflictError

    action = str(choice.get("action") or "")
    if action == "select_issues":
        if artifacts.get("selected_issues"):
            raise ConflictError("本流程已选定意见，不能重复选择")
        raw_items = choice.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise ValidationError("请至少选择一条意见")
        parsed = [IssueRevisionItem.model_validate(item) for item in raw_items[:20]]
        artifacts["selected_issues"] = {
            "items": [item.model_dump(mode="json") for item in parsed],
        }
        return True
    if action == "proceed":
        if artifacts.get("revision_decision"):
            return False
        artifacts["revision_decision"] = {"proceed": True}
        return True
    if action == "finish_flow":
        artifacts["flow_completion"] = {"step_id": str(choice.get("step_id") or "")}
        return True
    raise ValidationError("这个停点不接受该选择")


async def run_editorial_auto_step(
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
    if step_id == "bridge_revision":
        return await _run_bridge_revision(
            db, novel_id, run, flow, artifacts, input_fingerprint
        )
    if step_id == "post_recheck":
        return await _run_post_recheck(db, novel_id, run, flow, artifacts)
    raise ValidationError(f"流程 {flow.flow_id} 没有可执行的自动步骤 {step_id}")


async def _run_bridge_revision(
    db, novel_id, run, flow, artifacts: dict[str, Any], input_fingerprint: str
) -> dict[str, Any] | None:
    """桥接批注修订：复用 BR-4 既有入口；引文失效/hash 漂移沿用其失败关闭。"""
    from modules.assistant.editorial_bridge import submit_issue_revision

    if artifacts.get("bridge_items"):
        return None
    selected = artifacts.get("selected_issues") or {}
    raw_items = list(selected.get("items") or [])
    if not raw_items:
        return None
    receipt = await submit_issue_revision(
        db,
        IssueRevisionRequest(
            novel_id=novel_id,
            operation_id=_flow_operation_id(
                run, flow, "bridge_revision", input_fingerprint
            ),
            items=[IssueRevisionItem.model_validate(item) for item in raw_items],
        ),
    )
    items = [
        {
            "issue_id": item["issue_id"],
            "status": item["status"],
            "task_id": str(item.get("task_id") or ""),
            "chapter_index": item.get("chapter_index"),
            "reason": str(item.get("reason") or ""),
        }
        for item in receipt["items"]
    ]
    return {
        "operation_id": str(receipt.get("operation_id") or ""),
        "items": items,
        "task_ids": [item["task_id"] for item in items if item["task_id"]],
    }


async def _run_post_recheck(
    db, novel_id, run, flow, artifacts: dict[str, Any]
) -> dict[str, Any] | None:
    """候选采用后的改后复核：复用 BR-4 既有 request_recheck 机制；
    请求标识由（意见、采用稿）确定，同一候选重复采用命中同一轮复核。"""
    from modules.assistant.editorial_bridge import trigger_post_adoption_rechecks

    if artifacts.get("recheck_results"):
        return None
    grouped: dict[str, list[str]] = {}
    for item in (artifacts.get("bridge_items") or {}).get("items") or []:
        if item.get("status") != "queued" or not item.get("task_id"):
            continue
        result = await _comment_run_result(db, novel_id, str(item["task_id"]))
        draft_id = str((result or {}).get("candidate_draft_id") or "")
        if not draft_id:
            continue
        contract = await get_draft(db, novel_id, draft_id)
        adopted = _adoption_result(contract) if contract is not None else None
        if not adopted:
            continue
        grouped.setdefault(str(adopted), []).append(str(item["issue_id"]))
    results: list[dict[str, Any]] = []
    for adopted_draft_id, issue_ids in grouped.items():
        results.extend(
            await trigger_post_adoption_rechecks(
                db,
                novel_id=novel_id,
                issue_ids=issue_ids,
                adopted_draft_id=adopted_draft_id,
            )
        )
    return {
        "results": results,
        "task_ids": [
            str(entry.get("task_id")) for entry in results if entry.get("task_id")
        ],
    }


async def _comment_run_result(db, novel_id: str, task_id: str) -> dict | None:
    from infrastructure.tasks.facade import get_completed_task_payload

    payload = await get_completed_task_payload(
        db,
        task_id=task_id,
        task_type="writing_comment_run",
        novel_id=novel_id,
    )
    return dict(payload.result or {}) if payload else None


# ---------------------------------------------------------------------------
# 开始校验与派发表
# ---------------------------------------------------------------------------


async def _start_continue_writing(db, novel_id: str, data) -> None:
    """输入期定位工作稿：不让必败流程落地。"""
    if not data.chapter_index:
        raise ValidationError("请先选择要继续的章节", code="guided_flow_no_chapter")
    working = await get_latest_draft_for_chapter(db, novel_id, data.chapter_index)
    if working is None or working.status not in WORKING_DRAFT_STATUSES:
        raise ValidationError(
            f"第 {data.chapter_index} 章还没有可继续的工作稿；"
            "请先在写作页保存或采用本章正文。",
            code="guided_flow_no_working_draft",
        )


async def _start_new_book_opening(db, novel_id: str, data) -> None:
    try:
        OpeningStartInput.model_validate(data.input)
    except PydanticValidationError as exc:
        raise ValidationError(
            "请先写下一句构想（可附题材与篇幅意向），再开始新书开篇流程",
            code="guided_flow_opening_vision_required",
        ) from exc
    if data.chapter_index:
        raise ValidationError(
            "新书开篇流程不针对具体章节", code="guided_flow_opening_chapter"
        )


async def _start_editorial_revision(db, novel_id: str, data) -> None:
    if data.chapter_index or data.input:
        raise ValidationError(
            "按审读意见修订流程从审读台选择意见开始，不需要开始输入",
            code="guided_flow_editorial_input",
        )


START_CHECKS = {
    FLOW_ID: _start_continue_writing,
    OPENING_FLOW_ID: _start_new_book_opening,
    EDITORIAL_FLOW_ID: _start_editorial_revision,
}

# 运行层派发表：每个流程注册自己的推导、确认/选择输入与自动执行。
DERIVERS = {
    FLOW_ID: derive_continue_writing,
    OPENING_FLOW_ID: derive_new_book_opening,
    EDITORIAL_FLOW_ID: derive_editorial_revision,
}
CONFIRM_INPUT = {FLOW_ID: apply_confirm_input}
CHOICE_INPUT = {
    FLOW_ID: apply_continue_choice,
    OPENING_FLOW_ID: apply_opening_choice,
    EDITORIAL_FLOW_ID: apply_editorial_choice,
}
AUTO_STEPS = {
    FLOW_ID: run_auto_step,
    OPENING_FLOW_ID: run_opening_auto_step,
    EDITORIAL_FLOW_ID: run_editorial_auto_step,
}
