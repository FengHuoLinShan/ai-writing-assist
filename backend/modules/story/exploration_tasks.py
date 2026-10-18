"""Author-authorized multi-scale exploration workers (P0 §5/§7).

两个 task_handler 承担三档探索任务：
- ``story_exploration_progression_task``：B1 沙盘与 B2 事件（诊断/补桥），
  结果写 ``story_world_progression_steps``（零参与者紧凑步骤）。
- ``story_exploration_scene_task``：B3 场景一句对白（含多目标/空间诊断/
  M3-B 完整排演），结果写 ``story_scene_director_rounds``；canonical 目标
  生成后做 hidden guard 消费方校验，违规即失败不落库。

完整排演（M3-B）：worker 读取根与任务冻结的 ``full_rehearsal`` 意图，逐轮
对每个目标一次表演卡生成（各自知识/误信包），每轮末一次作者侧统筹调用
（素材/观察/状态），每轮后提交式检查点支持暂停续跑；候选目标不创建正式
角色或 Scene，作者私密目的只进作者统筹包。

骨架对齐 ``director_tasks`` / ``world_progression_tasks``：never_retry、
信封身份校验、冻结起点与任务 meta/根 request 比对、preview hash 重算、
provider 前后检查点（pending_step_json / pending_round_json）、预算暂停
paused_* 语义。detail/revise 由同一对 worker 承担（meta.mode）。
"""

from __future__ import annotations

import ast
import json
import uuid
from copy import deepcopy
from uuid import UUID

from sqlalchemy import func, select

from core.errors import ConflictError
from infrastructure.llm.agent_step_harness import run_managed_structured
from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from infrastructure.llm.workflow_budget import current_ai_run_envelope
from infrastructure.tasks.facade import (
    checkpoint_handler_session,
    require_task_checkpoint_session,
)
from infrastructure.tasks.registry import task_handler
from modules.evidence.contracts import (
    Assumption,
    ProvisionalStart,
    SceneAnchorStart,
    redact_hidden_phrases,
)
from modules.evidence.facade import (
    build_hidden_guard_context,
    prepare_confirmed_ai_action,
)
from modules.project.facade import open_project_snapshot_llm_client
from modules.story.director_budget import budget_stop_reason
from modules.story.director_service import get_director_branch, get_director_root
from modules.story.exploration_budget import preview_exploration_budget
from modules.story.exploration_feature import require_story_exploration_enabled
from modules.story.exploration_schemas import (
    AUTHOR_EDIT_OUTPUT_KIND,
    EVENT_HINT_REQUIRED_ACTION,
    EVENT_OUTPUT_KIND,
    EXPLORATION_CAPABILITY,
    EXPLORATION_OUTPUT_SCHEMA_VERSION,
    FULL_REHEARSAL_OUTPUT_KIND,
    FULL_REHEARSAL_ROUNDS_MIN,
    LOCK_SET_OUTPUT_KIND,
    MULTI_TARGETS_MAX,
    MULTI_TARGETS_MIN,
    SANDBOX_OUTPUT_KIND,
    SCENE_LINE_OUTPUT_KIND,
    EventOutputV1,
    ExplorationOutputEnvelope,
    FullRehearsalOutputV1,
    FullRehearsalPerformance,
    FullRehearsalRequest,
    FullRehearsalRound,
    FullRehearsalRoundOrchestration,
    SandboxOutputV1,
    SceneLineOutputV1,
    _normalize_base_kind,
    check_revision_target,
)
from modules.story.exploration_schemas import (
    revision_items as _revision_items,
)
from modules.story.exploration_service import (
    current_locked_items,
    pack_exploration_output,
    unpack_exploration_output,
)
from modules.story.models import StorySceneDirectorRoot, StorySceneDirectorRound
from modules.story.world_progression_models import (
    StoryWorldProgressionRoot,
    StoryWorldProgressionStep,
)
from modules.story.world_progression_service import (
    get_progression_branch,
    get_progression_root,
)

EXPLORATION_PROGRESSION_TASK = "story_exploration_progression_task"
EXPLORATION_SCENE_TASK = "story_exploration_scene_task"

# 分支续写基线（最新 AI 结果）回扫上限；单分支行数远小于该值。
_TIP_SCAN_CAP = 500

SANDBOX_ACTION = "story.exploration.sandbox.generate"
EVENT_DIAGNOSE_ACTION = "story.exploration.event.diagnose"
EVENT_BRIDGE_ACTION = "story.exploration.event.bridge"
SCENE_LINE_ACTION = "story.exploration.scene_line.generate"

STEP_NAME_BY_ACTION = {
    SANDBOX_ACTION: SANDBOX_ACTION,
    EVENT_DIAGNOSE_ACTION: EVENT_DIAGNOSE_ACTION,
    EVENT_BRIDGE_ACTION: EVENT_BRIDGE_ACTION,
    SCENE_LINE_ACTION: SCENE_LINE_ACTION,
}

PAYLOAD_MODEL_BY_ACTION = {
    SANDBOX_ACTION: SandboxOutputV1,
    EVENT_DIAGNOSE_ACTION: EventOutputV1,
    EVENT_BRIDGE_ACTION: EventOutputV1,
    SCENE_LINE_ACTION: SceneLineOutputV1,
}

OUTPUT_KIND_BY_ACTION = {
    SANDBOX_ACTION: SANDBOX_OUTPUT_KIND,
    EVENT_DIAGNOSE_ACTION: EVENT_OUTPUT_KIND,
    EVENT_BRIDGE_ACTION: EVENT_OUTPUT_KIND,
    SCENE_LINE_ACTION: SCENE_LINE_OUTPUT_KIND,
}

SCENE_LOCAL_STIMULUS_PREFIX = "场景本地假设（非正史）："

_SYSTEM_PROMPTS = {
    SANDBOX_ACTION: (
        "你是小说作者的独立沙盘推演器。只依据输入包里的作者问题、假设与已确认"
        "资料，回答“一条设定如果成立会怎样”。输出一条有条件的影响链（允许只有"
        "一环），每环写条件、机制、影响、受影响者（引用输入的候选 ref_id 或正式"
        "entity_id）、成立条件与未知；不要编造精确数字或生产率，缺条件就写 "
        "holds_when/unknown；不得读取章节正文，不得铺开全城人物表。"
    ),
    EVENT_DIAGNOSE_ACTION: (
        "你是小说作者的事件诊断器。只对输入的原始片段找因果缺口：每个缺口写描述、"
        "为什么需要它、可选的修复提示；不得替作者改写原案，不得给补桥路径，"
        "不自动创建事件或正文。信息不足以定位时如实写未知。"
    ),
    EVENT_BRIDGE_ACTION: (
        "你是小说作者的事件补桥器。针对给定缺口给出候选补桥路径：每条路径写有限"
        "步骤、所需条件与代价或风险，并标注 holds 是否自洽；作者指定结果禁止巧合"
        "时，无法成立就输出 unsolvable 并列出缺项，不要编造可信路径。不自动创建"
        "事件、Scene 或正文。"
    ),
    SCENE_LINE_ACTION: (
        "你是小说作者的场景对白试探器。只给目标角色写一句对白（可附一处动作）："
        "该角色只知道输入包里明确列出的可知信息，未声明的信息一律未知；作者私享"
        "信息绝不可出现在角色的话里。rationale 写依据与知识来源，withheld 写该"
        "角色知道但此刻不说出的内容。不生成其他角色、多角度或整场正文。"
    ),
}

# 事件模式提示（M2）的 system prompt 变体：按根冻结的 event_mode_hint 注入，
# 与动作严格配对（info_gap↔diagnose，goal↔bridge），其余动作不受影响。
EVENT_INFO_GAP_PROMPT = (
    "你是小说作者的事件信息差分析器。只对输入的原始片段逐个主体划分知识边界："
    "区分作者知道、人物知道与人物误信；每个主体写 knows/not_known，并标注缺失"
    "接触路径（missing_contact_path）；缺接触路径就如实列出缺失，不替角色补全"
    "未发生的信息，不得给补桥路径，不得改写原案。"
)
EVENT_GOAL_PROMPT = (
    "你是小说作者的事件导向路径规划器。针对作者指定结果给出最小行动—响应—后果"
    "链：每步写行动、成立条件、对方响应、后果与代价或风险；遵守作者给定的规则"
    "约束（如禁止巧合、禁止性格突变）；缺条件就返回 unsolvable 并列出缺项，"
    "不编造巧合或让角色突然改性格。不自动创建事件、Scene 或正文。"
)

_EVENT_HINT_PROMPT_BY_HINT = {
    "info_gap": EVENT_INFO_GAP_PROMPT,
    "goal": EVENT_GOAL_PROMPT,
}

# 场景空间诊断（M2）的 system prompt 变体：约束只允许引用已确认资料，
# 缺尺寸/路线列 unknowns；不把模型想象当物理证明。
SCENE_SPATIAL_DIAGNOSTIC_PROMPT = (
    "你是小说作者的场景空间诊断器。针对作者的动作问题，只依据输入包里已确认的"
    "空间/道具资料判断该动作是否有支持：spatial_assessment.supported 给出是/否/"
    "无法判断（无法判断置空）；constraints 逐条引用资料里可见的空间或道具约束"
    "（门、桌、距离、通道等）；缺尺寸、缺路线或资料未覆盖的部分一律写入 "
    "unknowns。没有空间资料时 constraints 必须为空，并在 unknowns 说明"
    "“缺尺寸/路线资料，无法核验”。不得把想象当物理证明，不得生成对白或正文。"
)

# 空间资料缺失时服务端补明的未知项（确定性事实，不依赖模型自觉）。
SPATIAL_UNKNOWN_DISCLOSURE = "缺尺寸/路线资料，无法核验"

_SPATIAL_ENTITY_TYPES = frozenset({"location", "item"})
_SPATIAL_MATERIAL_CHAR_CAP = 6000

# ---------------------------------------------------------------------------
# 完整排演（M3-B）：检查点模式、系统 prompt 与步骤名
# ---------------------------------------------------------------------------

# pending_round_json.mode 取值：完整排演有自己的检查点模式，避免“普通 start
# 任务误续跑排演分支”或反向混跑（_require_pending_mode 失败关闭）。
FULL_REHEARSAL_PENDING_MODE = "full_rehearsal"

# 表演卡沿用已注册动作 story.exploration.scene_line.generate（Evidence 能力
# 与确认校验不变）；统筹调用是不同的生成步骤，step 名仅供运行轨迹区分。
FULL_REHEARSAL_ORCHESTRATION_STEP = "story.exploration.full_rehearsal.orchestration"

FULL_REHEARSAL_CARD_PROMPT = (
    "你是小说作者的排演指导。为指定目标生成本轮的一张表演卡：line_or_beat 写"
    "该目标的一句台词或一个动作节拍，rationale 写动机与依据，basis_refs 逐条"
    "引用输入包里列出的可知信息。该角色只知道输入包明确列出的可知信息，未声明"
    "的信息一律未知；作者私享信息与作者的排演目的绝不可出现在台词、动机或依据"
    "里。只输出这一张表演卡，不生成其他目标、素材或整场正文。"
)

FULL_REHEARSAL_ORCHESTRATION_PROMPT = (
    "你是小说作者的排演统筹器。只依据本轮全部表演卡与已确认资料输出三类内容："
    "materials 场景素材（environment/object/crowd/mood/pacing/time 六类之一，"
    "标注感知者，感知者只能是本次排演目标）；observations 逐个目标写它本轮实际"
    "注意到的事（没有就留空，不替角色补充未观察的信息）；state_notes 用少量"
    "要点记录各目标的状态变化。不写台词，不创建角色或 Scene，不输出正文。"
)


def _event_mode_hint_for(root_request: dict, action: str) -> str | None:
    """读取根冻结的事件模式提示并校验与动作配对；未设置返回 None。

    值不在已知集合或与动作不配对即失败关闭，不静默降级为基础 prompt。
    """

    value = root_request.get("event_mode_hint")
    if not value:
        return None
    hint = str(value)
    expected = EVENT_HINT_REQUIRED_ACTION.get(hint)
    if expected is None:
        raise ValueError("未知的事件模式提示，失败关闭")
    if action != expected:
        raise ValueError("事件模式提示与本次动作不匹配，失败关闭")
    return hint


def _event_system_prompt(action: str, event_mode_hint: str | None) -> str:
    if event_mode_hint is not None:
        return _EVENT_HINT_PROMPT_BY_HINT[event_mode_hint]
    return _SYSTEM_PROMPTS[action]


class ExplorationPauseError(Exception):
    """预算或未知用量到达停止边界；保留检查点等待作者追加授权。"""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _meta(task) -> dict:
    return dict(task.meta or {})


def _request_limit(task) -> int:
    return int(_meta(task).get("exploration_authorized_requests") or 1)


def _token_limit(task) -> int:
    value = _meta(task).get("exploration_authorized_tokens")
    return int(value) if value is not None else 1


def _deadline_seconds(task) -> float:
    return float(_meta(task).get("exploration_deadline_seconds") or 3600)


def _stable_root_id(task) -> str:
    value = str(_meta(task).get("exploration_root_id") or "").strip()
    if not value:
        raise ValueError("探索任务缺少持久根身份")
    return value


def _monotonic_envelope(previous: dict, current: dict) -> None:
    for field in (
        "run_id",
        "root_capability_id",
        "novel_id",
        "started_at",
        "deadline_at",
    ):
        if field in previous and previous[field] != current.get(field):
            raise ValueError("探索预算检查点的根身份或时限发生变化")
    for field in (
        "requests_started",
        "requests_settled",
        "requests_unknown",
        "recent_attempts_overflow",
        "request_limit",
        "token_limit",
    ):
        old, new = previous.get(field), current.get(field)
        if old is not None and (new is None or int(new) < int(old)):
            raise ValueError("拒绝用旧预算快照覆盖探索累计账本")
    old_tokens = (previous.get("usage") or {}).get("total_tokens")
    new_tokens = (current.get("usage") or {}).get("total_tokens")
    if old_tokens is not None and (
        new_tokens is None or int(new_tokens) < int(old_tokens)
    ):
        raise ValueError("拒绝用旧 Token 快照覆盖探索累计账本")


async def _mirror_progression_envelope(session, task, payload):
    root = await session.scalar(
        select(StoryWorldProgressionRoot)
        .where(
            StoryWorldProgressionRoot.novel_id == task.novel_id,
            StoryWorldProgressionRoot.id
            == UUID(str(_meta(task).get("exploration_root_id"))),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if root is None:
        raise ValueError("探索预算根已不存在")
    previous = root.run_envelope_json or {}
    _monotonic_envelope(previous, payload)
    root.run_envelope_json = dict(payload)


async def _mirror_scene_envelope(session, task, payload):
    root = await session.scalar(
        select(StorySceneDirectorRoot)
        .where(
            StorySceneDirectorRoot.novel_id == task.novel_id,
            StorySceneDirectorRoot.id
            == UUID(str(_meta(task).get("exploration_root_id"))),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if root is None:
        raise ValueError("探索预算根已不存在")
    previous = root.run_envelope_json or {}
    _monotonic_envelope(previous, payload)
    root.run_envelope_json = dict(payload)


def _budget_guard(meta: dict) -> dict:
    return {
        "acknowledged_unknown": int(
            meta.get("exploration_acknowledged_unknown_requests") or 0
        ),
        "baseline_requests_started": int(
            meta.get("exploration_baseline_requests_started") or 0
        ),
        "baseline_recent_attempts_overflow": int(
            meta.get("exploration_baseline_recent_attempts_overflow") or 0
        ),
    }


def _check_envelope_identity(envelope, *, root_id: str, novel_id: str) -> None:
    if (
        envelope is None
        or envelope.run_id != root_id
        or envelope.root_capability_id != EXPLORATION_CAPABILITY
        or envelope.snapshot().novel_id != novel_id
    ):
        raise ValueError("探索根预算信封身份不匹配")


def _validate_start_dump(start_dump) -> SceneAnchorStart | ProvisionalStart:
    if not isinstance(start_dump, dict):
        raise ValueError("探索任务缺少合法起点载荷")
    if start_dump.get("kind") == "scene_anchor":
        return SceneAnchorStart.model_validate(start_dump)
    if start_dump.get("kind") == "provisional":
        return ProvisionalStart.model_validate(start_dump)
    raise ValueError("不支持的探索起点类型")


def _frozen_exploration(confirmed) -> dict:
    """确认重物化回传的冻结探索起点；缺失即失败关闭。"""
    trace = getattr(confirmed.compiled, "selection_trace", {}) or {}
    frozen = trace.get("exploration")
    if not isinstance(frozen, dict) or not frozen.get("exploration_start"):
        raise ValueError("资料确认缺少冻结的探索起点，请重新确认")
    return frozen


def _require_confirmation_matches(
    confirmed, *, scale: str, start_dump: dict, focus: str
) -> None:
    frozen = _frozen_exploration(confirmed)
    if (
        str(frozen.get("exploration_scale") or "") != scale
        or frozen.get("exploration_start") != start_dump
        or str(frozen.get("exploration_focus") or "") != str(focus or "")
    ):
        raise ValueError("冻结起点与本次任务不一致，失败关闭；请重新预览并确认")


def _counterfactual_request_params(root_request: dict) -> tuple[str | None, list]:
    """从根冻结 request_json 读反事实身份；缺失或畸形即失败关闭。"""
    counterfactual_of = root_request.get("counterfactual_of")
    if not counterfactual_of:
        return None, []
    raw = root_request.get("changed_assumptions")
    if not isinstance(raw, list) or not raw:
        raise ValueError("反事实探索根缺少 changed_assumptions，失败关闭")
    changed = [
        item if isinstance(item, Assumption) else Assumption.model_validate(item)
        for item in raw
    ]
    return str(counterfactual_of), changed


def _require_preview_hash(
    *,
    novel_id: str,
    scale: str,
    start,
    focus: str,
    expected: str,
    counterfactual_of_result_id: str | None = None,
    changed_assumptions: list | None = None,
    event_mode_hint: str | None = None,
    multi_targets: list[str] | None = None,
    diagnostic_question: str | None = None,
    full_rehearsal: FullRehearsalRequest | None = None,
) -> None:
    current = preview_exploration_budget(
        novel_id=novel_id,
        scale=scale,
        start=start,
        focus=focus,
        counterfactual_of_result_id=counterfactual_of_result_id,
        changed_assumptions=changed_assumptions,
        event_mode_hint=event_mode_hint,
        multi_targets=multi_targets,
        diagnostic_question=diagnostic_question,
        full_rehearsal=full_rehearsal,
    )
    if current.preview_hash != expected:
        raise ValueError("起点或焦点已变化，预算预览不一致，失败关闭")


def _require_pending_mode(pending: dict, mode: str) -> None:
    if pending and str(pending.get("mode") or "") != mode:
        raise ValueError("未完成检查点与本次任务模式不一致；请先处理暂停的探索")


# ---------------------------------------------------------------------------
# 输入包构造（P0 §2.5：作者包与角色包分离）
# ---------------------------------------------------------------------------


def _author_packet(*, start, focus: str, confirmed) -> dict:
    """作者侧输入包：问题、假设、作者私享与已读网页摘要；绝不含角色知识包。"""
    return {
        "question": start.question,
        "focus": focus,
        "assumptions": [
            {"kind": item.kind, "text": item.text} for item in start.assumptions
        ],
        "author_private": list(start.author_private),
        "web_refs": [
            {"url": item.url, "title": item.title, "excerpt": item.excerpt[:400]}
            for item in start.web_refs
        ],
        "time_basis": start.time_basis,
        "confirmed_material": confirmed.rendered_markdown or "",
    }


def _candidate_packets(start: ProvisionalStart) -> dict:
    """候选主体的可知包：只依据 KnowledgeEntry 明确声明，未声明一律未知。"""
    labels = {item.ref_id: item.label for item in start.candidates}
    return {
        entry.subject_ref: {
            "label": labels.get(entry.subject_ref, entry.subject_ref),
            "knows": list(entry.knows),
            "observed": list(entry.observed),
            "misbelieves": list(entry.misbelieves),
            "rule": "未声明的信息一律未知；不得推断补充。",
        }
        for entry in start.knowledge
        if entry.subject_ref in labels
    }


def _canonical_stimuli(start: ProvisionalStart, entity_id: str) -> list[str]:
    return [
        f"{SCENE_LOCAL_STIMULUS_PREFIX}{item.stimulus}"
        for item in start.scene_stimuli
        if item.subject_entity_id == entity_id
    ]


def _sandbox_event_user_data(
    *,
    start,
    focus: str,
    confirmed,
    mode: str,
    parent_payload: dict | None,
    instruction: str,
    bridge_target: str | None,
    single_item: bool,
) -> dict:
    """B1/B2 作者视角输入包：作者包 + 候选可知摘要。"""
    data: dict = {
        "mode": mode,
        "author_packet": _author_packet(start=start, focus=focus, confirmed=confirmed),
        "output_rule": (
            "局部修订时只输出被修订的那一条（influence_chain/gaps/"
            "bridge_candidates 各只给一条），其余内容会由服务端原样保留。"
            if single_item
            else "按完整输出结构返回。"
        ),
    }
    if isinstance(start, ProvisionalStart):
        data["candidate_summaries"] = _candidate_packets(start)
        data["canonical_refs"] = list(start.canonical_refs)
    if parent_payload is not None:
        data["previous_output"] = parent_payload
    if bridge_target:
        data["bridge_target"] = bridge_target
    if instruction:
        data["instruction"] = instruction
    return data


def _scene_line_user_data(
    *,
    start,
    focus: str,
    target_ref: str,
    confirmed,
    mode: str,
    parent_payload: dict | None,
    instruction: str,
) -> dict:
    """B3 单目标输入包：作者问题可作背景，作者私享与候选知识包互不混入。"""
    is_candidate = target_ref.startswith("c_")
    data = {
        "mode": mode,
        "focus": focus,
        "target": {
            "ref": target_ref,
            "kind": "candidate" if is_candidate else "canonical_character",
        },
    }
    if isinstance(start, ProvisionalStart):
        data["author_context"] = {
            "question": start.question,
            "assumptions": [
                {"kind": item.kind, "text": item.text} for item in start.assumptions
            ],
            "time_basis": start.time_basis,
        }
        if is_candidate:
            entry = next(
                (item for item in start.knowledge if item.subject_ref == target_ref),
                None,
            )
            data["target_knowledge"] = {
                "knows": list(entry.knows) if entry else [],
                "observed": list(entry.observed) if entry else [],
                "misbelieves": list(entry.misbelieves) if entry else [],
                "rule": "未声明的信息一律未知。",
            }
        else:
            stimuli = _canonical_stimuli(start, target_ref)
            if stimuli:
                data["target_scene_stimuli"] = stimuli
            data["target_dossier_note"] = (
                "正式角色资料只以作者确认的编译产物为准；隐藏真相不在你收到的资料里。"
            )
    data["confirmed_material"] = confirmed.rendered_markdown or ""
    if parent_payload is not None:
        data["previous_line"] = {
            "line": parent_payload.get("line"),
            "rationale": parent_payload.get("rationale"),
        }
    if instruction:
        data["instruction"] = instruction
    return data


def _scene_diagnostic_user_data(
    *,
    start,
    focus: str,
    confirmed,
    question: str,
    subject_ref: str | None,
    material: list[dict],
) -> dict:
    """空间诊断输入包：问题 + 可选主体 + 已确认空间资料；不含角色知识包与作者私享。"""
    data = {
        "mode": "diagnostic",
        "focus": focus,
        "question": question,
        "subject_ref": subject_ref,
        "spatial_material": material,
        "output_rule": (
            "spatial_assessment.constraints 只允许引用 spatial_material 或已确认资料中"
            "可见的空间/道具约束；资料缺失或尺寸/路线不明时写入 unknowns；supported "
            "无法判断时置空。不得把想象当物理证明。"
        ),
    }
    if isinstance(start, ProvisionalStart):
        data["author_context"] = {
            "assumptions": [
                {"kind": item.kind, "text": item.text} for item in start.assumptions
            ],
            "time_basis": start.time_basis,
        }
    data["confirmed_material"] = confirmed.rendered_markdown or ""
    return data


def _spatial_entity_entries(content: str) -> str:
    """从世界对象 section 行中过滤 location/item 条目。

    section 行是编译器自行序列化的对象字典，逐行安全解析后按 entity_type
    过滤；解析失败的行保守丢弃（宁可列未知，不猜内容）。
    """
    kept: list[str] = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = ast.literal_eval(line)
        except (ValueError, SyntaxError):
            continue
        if not isinstance(entry, dict):
            continue
        if str(entry.get("entity_type") or "") not in _SPATIAL_ENTITY_TYPES:
            continue
        name = str(entry.get("name") or "").strip()
        summary = str(entry.get("summary") or "").strip()
        if not name and not summary:
            continue
        kept.append(f"- {name}：{summary}" if summary else f"- {name}")
    return "\n".join(kept)


def _spatial_material_sections(confirmed) -> list[dict]:
    """提取本次确认编译产物中的空间/道具资料（M2 空间诊断资料来源）。

    只读已确认编译产物里已有的 section（map_spatial 空间简报、世界对象的
    location/item 条目），不新开 World 查询、不直读地图实现；起点既无
    canonical 资料也无场景锚点时返回空列表，由调用方强制列 unknowns。
    """
    compiled = getattr(confirmed, "compiled", None)
    material: list[dict] = []
    for section in getattr(compiled, "sections", None) or []:
        key = str(getattr(section, "key", "") or "")
        content = str(getattr(section, "content", "") or "")
        if key == "map_spatial":
            if content.strip():
                material.append(
                    {
                        "key": "map_spatial",
                        "content": content[:_SPATIAL_MATERIAL_CHAR_CAP],
                    }
                )
        elif key == "world_entities":
            entries = _spatial_entity_entries(content)
            if entries:
                material.append(
                    {
                        "key": "world_entities.location_item",
                        "content": entries[:_SPATIAL_MATERIAL_CHAR_CAP],
                    }
                )
    return material


def _finalize_spatial_assessment(
    output: SceneLineOutputV1, material: list[dict], *, subject_ref: str | None
) -> SceneLineOutputV1:
    """空间诊断落库前校验：无资料禁止虚构约束；unknowns 缺失由服务端补明。"""
    assessment = output.spatial_assessment
    if assessment is None:
        raise ValueError("空间诊断输出缺少 spatial_assessment，失败关闭")
    if not material and assessment.constraints:
        raise ValueError(
            "本次确认资料中没有空间/道具资料，不得给出空间约束（不把想象当物理证明）"
        )
    if not material and not assessment.unknowns:
        assessment = assessment.model_copy(
            update={"unknowns": [SPATIAL_UNKNOWN_DISCLOSURE]}
        )
    return output.model_copy(
        update={"spatial_assessment": assessment, "target_ref": subject_ref or ""}
    )


def _scene_multi_targets(request: dict, *, mode: str) -> list[str] | None:
    """读取根冻结请求里的多目标列表；只在 start 模式接受，畸形即失败关闭。"""
    raw = request.get("multi_targets")
    if raw is None:
        return None
    if mode != "start":
        raise ValueError("多目标对白只在 start 模式支持，失败关闭")
    targets = [str(item) for item in raw]
    if (
        not (MULTI_TARGETS_MIN <= len(targets) <= MULTI_TARGETS_MAX)
        or len(set(targets)) != len(targets)
    ):
        raise ValueError("multi_targets 必须是 2..4 个互不相同的目标，失败关闭")
    return targets


def _scene_full_rehearsal(
    request: dict, *, mode: str, root_request: dict | None = None
) -> FullRehearsalRequest | None:
    """读取根冻结请求里的完整排演意图（M3-B）。

    只在 start 模式接受；载荷畸形或与根 request_json 冻结的排演意图不一致
    即失败关闭（不退化为聚焦表演卡链路）。返回解析后的排演意图，无排演
    返回 None。预算已按 (目标数 + 1) × 轮次 冻结在任务 meta 与根信封。
    """
    raw = request.get("full_rehearsal")
    if raw is None:
        return None
    if mode != "start":
        raise ValueError("完整排演只在 start 模式支持，失败关闭")
    if not isinstance(raw, dict):
        raise ValueError("完整排演请求载荷畸形，失败关闭")
    rehearsal = FullRehearsalRequest.model_validate(raw)
    if root_request is not None and (
        (root_request or {}).get("full_rehearsal")
        != rehearsal.model_dump(mode="json")
    ):
        raise ValueError("任务排演意图与探索根冻结意图不一致，失败关闭")
    return rehearsal


# ---------------------------------------------------------------------------
# 完整排演（M3-B）：输入包构造与执行循环
# ---------------------------------------------------------------------------


def _rehearsal_scene_context(start) -> dict:
    """表演卡与统筹包共用的场景背景：问题、假设、时点。

    注意（M3-B 隐私边界）：这里刻意不含 ``author_private`` 与
    ``author_goal``——两者只允许出现在作者统筹包里，绝不进入任何目标角色包；
    由 ``test_full_rehearsal_author_goal_only_in_author_packets`` 断言。
    """
    return {
        "question": start.question,
        "assumptions": [
            {"kind": item.kind, "text": item.text} for item in start.assumptions
        ],
        "time_basis": start.time_basis,
    }


def _rehearsal_performance_packet(
    *,
    start,
    focus: str,
    target_ref: str,
    confirmed,
    round_number: int,
    previous_round: FullRehearsalRound | None,
) -> dict:
    """单目标角色包：各自知识/误信 + 上一轮观察回执，不含作者私密内容。

    候选目标只渲染其 KnowledgeEntry（未声明一律未知）；正式角色给已确认
    编译产物 + 带“场景本地假设”前缀的 scene_stimuli，隐藏真相不在资料里。
    """
    is_candidate = target_ref.startswith("c_")
    data: dict = {
        "mode": "full_rehearsal_performance",
        "round": round_number,
        "focus": focus,
        "target": {
            "ref": target_ref,
            "kind": "candidate" if is_candidate else "canonical_character",
        },
        "scene": _rehearsal_scene_context(start),
        "output_rule": (
            "只输出这张表演卡：target_ref 填你的目标 ref；line_or_beat 一句台词"
            "或一个动作节拍；rationale 写动机与依据；basis_refs 只引用输入包里"
            "列出的可知信息。"
        ),
    }
    if isinstance(start, ProvisionalStart):
        if is_candidate:
            entry = next(
                (item for item in start.knowledge if item.subject_ref == target_ref),
                None,
            )
            data["target_knowledge"] = {
                "knows": list(entry.knows) if entry else [],
                "observed": list(entry.observed) if entry else [],
                "misbelieves": list(entry.misbelieves) if entry else [],
                "rule": "未声明的信息一律未知；不得推断补充。",
            }
        else:
            stimuli = _canonical_stimuli(start, target_ref)
            if stimuli:
                data["target_scene_stimuli"] = stimuli
            data["target_dossier_note"] = (
                "正式角色资料只以作者确认的编译产物为准；隐藏真相不在你收到的资料里。"
            )
    data["confirmed_material"] = confirmed.rendered_markdown or ""
    if previous_round is not None:
        previous_card = next(
            (
                card
                for card in previous_round.performances
                if card.target_ref == target_ref
            ),
            None,
        )
        own_observations = [
            observation.observed
            for observation in previous_round.observations
            if observation.target_ref == target_ref
        ]
        data["previous_round"] = {
            "round_number": previous_round.round_number,
            **(
                {"own_performance": previous_card.model_dump(mode="json")}
                if previous_card is not None
                else {}
            ),
            "own_observations": own_observations,
        }
    return data


def _rehearsal_orchestration_packet(
    *,
    start,
    focus: str,
    confirmed,
    rehearsal: FullRehearsalRequest,
    round_number: int,
    round_cards: list[FullRehearsalPerformance],
    prior_rounds: list[FullRehearsalRound],
    prior_state_notes: list[str],
) -> dict:
    """作者统筹包：可含 author_goal 与作者私享；产出只回作者侧字段。

    ``author_goal``（作者私密目的）只允许出现在本包——统筹调用的输入里可含，
    绝不进任何目标角色包（见 ``_rehearsal_performance_packet`` 注释）。
    """
    author_goal = str(rehearsal.author_goal or "")
    data: dict = {
        "mode": "full_rehearsal_orchestration",
        "round": round_number,
        "targets": list(rehearsal.targets),
        "author_packet": {
            **_rehearsal_scene_context(start),
            "focus": focus,
            **({"author_goal": author_goal} if author_goal else {}),
            "author_private": list(getattr(start, "author_private", []) or []),
        },
        "round_performances": [
            card.model_dump(mode="json") for card in round_cards
        ],
        "output_rule": (
            "materials 每条标 kind 与感知者（感知者只能在本次排演目标里选）；"
            "observations 逐个目标写它本轮实际注意到的事，没有就留空；"
            "state_notes 记录各目标状态要点（每轮最多 4 条）。"
        ),
    }
    if isinstance(start, ProvisionalStart):
        data["author_packet"]["web_refs"] = [
            {"url": item.url, "title": item.title, "excerpt": item.excerpt[:400]}
            for item in start.web_refs
        ]
    if prior_rounds or prior_state_notes:
        data["prior_rounds"] = [
            {
                "round_number": round_item.round_number,
                "materials": [
                    item.model_dump(mode="json") for item in round_item.materials
                ],
                "observations": [
                    item.model_dump(mode="json") for item in round_item.observations
                ],
            }
            for round_item in prior_rounds
        ]
        if prior_state_notes:
            data["prior_state_notes"] = list(prior_state_notes)
    data["confirmed_material"] = confirmed.rendered_markdown or ""
    return data


def _assert_rehearsal_character_inputs_clean(
    orchestration: FullRehearsalRoundOrchestration,
    *,
    author_goal: str,
    author_private: list[str],
) -> None:
    """信任边界校验：素材/观察回执会进入下一轮角色包，作者私密内容混入即失败关闭。

    author_goal 与 author_private 只允许存在于作者统筹输入与作者侧 state_notes
    汇总；materials/observations 是下一轮角色包的直接来源，服务端逐字比对。
    """
    secrets = [item for item in [author_goal, *author_private] if item]
    if not secrets:
        return
    text = json.dumps(
        {
            "materials": [
                item.model_dump(mode="json") for item in orchestration.materials
            ],
            "observations": [
                item.model_dump(mode="json") for item in orchestration.observations
            ],
        },
        ensure_ascii=False,
    )
    for secret in secrets:
        if str(secret) in text:
            raise ValueError(
                "排演素材或观察回执混入了作者私密内容；本次结果不落库，请重试"
            )


def _scene_diagnostic_request(
    request: dict, *, mode: str
) -> tuple[str | None, str | None]:
    """读取根冻结请求里的空间诊断问题与可选主体；只在 start 模式接受。"""
    raw = request.get("diagnostic")
    if raw is None:
        return None, None
    if mode != "start":
        raise ValueError("空间诊断只在 start 模式支持，失败关闭")
    if not isinstance(raw, dict):
        raise ValueError("空间诊断请求载荷畸形，失败关闭")
    question = str(raw.get("question") or "").strip()
    if not question:
        raise ValueError("空间诊断缺少问题，失败关闭")
    subject = str(raw.get("subject_ref") or "").strip() or None
    return question, subject


# ---------------------------------------------------------------------------
# 修订目标定位（P0 §8.1：item_path + item_text，不用客户端摘要做定位键）
# ---------------------------------------------------------------------------

_BASE_KIND_BY_SCALE = {
    "sandbox": SANDBOX_OUTPUT_KIND,
    "event": EVENT_OUTPUT_KIND,
    "scene_line": SCENE_LINE_OUTPUT_KIND,
}


def _merge_revision(parent_payload: dict, output, base_kind: str, item_path: str):
    """只把被修订条目替换进父载荷；其余内容服务端原样拷贝。"""
    matches = [
        row
        for row in _revision_items(parent_payload, base_kind)
        if row["key"] == item_path
    ]
    if len(matches) != 1:
        raise ValueError(f"修订路径 {item_path} 不在父结果的可修订条目中")
    target = matches[0]
    merged = deepcopy(parent_payload)
    kind, _, raw_index = target["key"].partition(":")
    index = int(raw_index) if raw_index else 0
    if kind == "chain":
        if not output.influence_chain:
            raise ValueError("修订结果缺少被修订的影响链环节")
        merged["influence_chain"][index] = output.influence_chain[0].model_dump(
            mode="json"
        )
    elif kind == "bridge":
        if not output.bridge_candidates:
            raise ValueError("修订结果缺少被修订的补桥路径")
        merged["bridge_candidates"][index] = output.bridge_candidates[0].model_dump(
            mode="json"
        )
    elif kind == "gap":
        if not output.gaps:
            raise ValueError("修订结果缺少被修订的缺口")
        merged["gaps"][index] = output.gaps[0].model_dump(mode="json")
    else:
        for key in ("line", "action"):
            value = getattr(output, key, None)
            if value:
                merged[key] = value
    return type(output).model_validate(merged)


# ---------------------------------------------------------------------------
# 锁定项强制回填（M3-A：worker 落库前以父 payload 为准，不靠模型自觉）
# ---------------------------------------------------------------------------


def _resolve_revision_items(payload: dict, item_path: str, base_kind: str) -> list[dict]:
    return [
        row for row in _revision_items(payload, base_kind) if row["key"] == item_path
    ]


def _write_revision_item(payload: dict, item_path: str, item, base_kind: str) -> None:
    base_kind = _normalize_base_kind(base_kind)
    kind, _, raw_index = item_path.partition(":")
    index = int(raw_index) if raw_index else 0
    if base_kind == SANDBOX_OUTPUT_KIND:
        payload["influence_chain"][index] = item
    elif base_kind == EVENT_OUTPUT_KIND:
        payload["bridge_candidates" if kind == "bridge" else "gaps"][index] = item
    else:
        payload["line"] = item


def _enforce_locked_items(
    parent_payload: dict,
    new_payload: dict,
    locked_specs: list[tuple[str, str]],
    base_kind: str,
) -> tuple[dict, list[str]]:
    """生成结果落库前强制回填全部锁定项：内容以父 payload 为准逐字恢复。

    锁定项内容与父不一致只可能因父本身被改——以父 payload 为准回填；
    锁定路径在父中解析不到，或生成结果缺同一路径（如“说详细点”改变了
    结构）→ 报告冲突失败关闭，不偷偷解锁；此时任务失败、结果不落库。
    """

    enforced = deepcopy(new_payload)
    honored: list[str] = []
    for item_path, _pinned_hash in locked_specs:
        parent_rows = _resolve_revision_items(parent_payload, item_path, base_kind)
        if len(parent_rows) != 1:
            raise ValueError(
                f"锁定条目 {item_path} 与父结果不一致，无法保持锁定内容；"
                "请先解锁或重新锁定"
            )
        if len(_resolve_revision_items(enforced, item_path, base_kind)) != 1:
            raise ValueError(
                f"锁定条目 {item_path} 无法在生成结果中保持（结构已变化）；"
                "请调整请求或先解锁再试"
            )
        _write_revision_item(enforced, item_path, parent_rows[0]["item"], base_kind)
        honored.append(item_path)
    return enforced, honored


# ---------------------------------------------------------------------------
# 共享执行骨架
# ---------------------------------------------------------------------------


def _safe_error(error: Exception) -> str:
    name = type(error).__name__
    if name in {"AIRunBudgetExceededError", "AIRunDeadlineExceededError"}:
        return "运行预算或时限已达到"
    if name in {"ProjectLLMConfigurationError", "CodexConnectionUnavailableError"}:
        return "项目模型连接不可用"
    return "生成未完成；已确认的起点与输入仍可查看"


def _classify_stop(error: Exception, guard: dict, envelope) -> str | None:
    """异常归类为预算暂停原因；非预算异常返回 None（走失败关闭）。"""
    stop = budget_stop_reason(envelope, **guard)
    if stop in {"provider_result_unknown", "usage_incomplete"}:
        return "provider_result_unknown"
    return stop


async def _checkpoint(db, root, branch, *, error_message, extra=None):
    await checkpoint_handler_session(db, error_message=error_message)
    await db.refresh(root)
    await db.refresh(branch)
    if extra is not None:
        await db.refresh(extra)
    await db.commit()
    if db.in_transaction():
        raise RuntimeError(error_message)


def _task_receipt(status: str, *, root_id: str, branch_id: str, **extra) -> dict:
    return {
        "status": status,
        "root_id": root_id,
        "branch_id": branch_id,
        "needs_author_resume": status in {"paused_budget", "paused_unknown"},
        **extra,
    }


def _completed_receipt(
    *, row, envelope: ExplorationOutputEnvelope, root_id: str, branch_id: str
) -> dict:
    """任务终态结果信封：前端 pollTaskProgress 就地渲染（P0 §8/D）。"""
    return {
        "status": "completed",
        "root_id": root_id,
        "branch_id": branch_id,
        "result_id": str(row.id),
        "output_kind": envelope.output_kind,
        "payload": envelope.payload.model_dump(mode="json"),
    }


async def _load_parent_result(db, *, model, novel_id: str, branch, parent_id: str):
    parent_row = await db.scalar(
        select(model)
        .where(
            model.novel_id == UUID(novel_id),
            model.id == UUID(parent_id),
            model.branch_id == branch.id,
        )
        .with_for_update()
    )
    if parent_row is None:
        raise ValueError("来源结果不存在或不属于该探索分支")
    base_envelope = unpack_exploration_output(parent_row)
    if base_envelope is None:
        raise ValueError("来源结果不是探索结果")
    if base_envelope.output_kind == "story.exploration.author_edit":
        raise ValueError("作者编辑版本不能继续详略或修订；请回到原始 AI 结果")
    if base_envelope.output_kind == LOCK_SET_OUTPUT_KIND:
        raise ValueError("锁定记录不是可修订的探索结果；请回到 AI 结果")
    if base_envelope.output_kind == FULL_REHEARSAL_OUTPUT_KIND:
        # 完整排演（M3-B）整体落一行：不做增量修订，绕过 API 直接入队也失败关闭。
        raise ValueError("完整排演结果暂不支持增量修订，请新建任务")
    return parent_row, base_envelope.payload.model_dump(mode="json")


async def _generate_exploration_payload(
    *,
    client,
    action: str,
    user_data: dict,
    system_content: str | None = None,
):
    """按动作调用一次有界结构化生成；system_content 缺省用该动作基础 prompt。"""
    return await run_managed_structured(
        client,
        LLMCallRequest(
            model=client.model_name,
            messages=[
                LLMMessage(
                    role="system",
                    content=system_content or _SYSTEM_PROMPTS[action],
                ),
                LLMMessage(
                    role="user", content=json.dumps(user_data, ensure_ascii=False)
                ),
            ],
        ),
        PAYLOAD_MODEL_BY_ACTION[action],
        step_name=STEP_NAME_BY_ACTION[action],
        capability_id=EXPLORATION_CAPABILITY,
        max_fix_attempts=0,
        transport_retries=False,
    )


async def _hidden_guard_terms(db, confirmed) -> list:
    """canonical 目标生成后守卫的隐藏短语集合（每次任务最多构建一次）。"""
    return await build_hidden_guard_context(db, confirmed_context=confirmed)


def _assert_content_within_guard(data: dict, terms: list, *, message: str) -> None:
    """hidden truth 短语出现在载荷 JSON 里即失败关闭（消息按消费方定制）。"""
    text = json.dumps(data, ensure_ascii=False)
    if redact_hidden_phrases(text, [term.phrase for term in terms]) != text:
        raise ValueError(message)


def _assert_scene_output_within_guard(output: SceneLineOutputV1, terms: list) -> None:
    """hidden truth 短语出现在输出即失败不落库。"""
    _assert_content_within_guard(
        output.model_dump(mode="json"),
        terms,
        message=(
            "生成的一句对白触碰了该角色的隐藏信息边界；本次结果不落库，"
            "请调整目标角色或资料范围后重试"
        ),
    )


async def _validate_canonical_scene_line(
    db, confirmed, output: SceneLineOutputV1
) -> None:
    """canonical 目标的生成后守卫：逐次构建短语集合并校验（单目标路径复用）。"""
    terms = await _hidden_guard_terms(db, confirmed)
    _assert_scene_output_within_guard(output, terms)


async def _run_scene_generation(
    db,
    *,
    novel_id: str,
    root,
    branch,
    envelope,
    guard: dict,
    run_snapshot: dict,
    action: str,
    mode: str,
    start,
    focus: str,
    confirmed,
    instruction: str,
    target_ref: str,
    parent_payload: dict | None,
    item_path: str,
    multi_targets: list[str] | None,
    diagnostic_question: str | None,
    diagnostic_subject: str | None,
) -> SceneLineOutputV1:
    """场景一次任务的三种形态（共用预算停止检查与逐请求检查点）：

    - 多目标（M2 人物差异）：逐目标独立知识包各一次请求，variants 承载；
    - 空间诊断（M2）：一次请求，spatial_assessment 承载，资料只来自
      本次已确认编译产物，缺失即强制列 unknowns；
    - 单目标：原路径（含 detail/revise 的父载荷合并与 canonical 守卫）。
    """
    async with open_project_snapshot_llm_client(db, novel_id, run_snapshot) as client:
        if multi_targets:
            variants: list[SceneLineOutputV1] = []
            guard_terms: list | None = None
            for target in multi_targets:
                stop = budget_stop_reason(envelope, **guard)
                if stop:
                    raise ExplorationPauseError(stop)
                await _checkpoint(
                    db,
                    root,
                    branch,
                    error_message="探索 provider 请求需要先提交检查点",
                )
                output = await _generate_exploration_payload(
                    client=client,
                    action=action,
                    user_data=_scene_line_user_data(
                        start=start,
                        focus=focus,
                        target_ref=target,
                        confirmed=confirmed,
                        mode="start",
                        parent_payload=None,
                        instruction=instruction,
                    ),
                )
                if str(output.target_ref) != target:
                    raise ValueError("对白目标与请求目标不一致")
                if not target.startswith("c_"):
                    # canonical 目标：生成后 hidden guard 消费方校验，违规即失败不落库。
                    if guard_terms is None:
                        guard_terms = await _hidden_guard_terms(db, confirmed)
                    _assert_scene_output_within_guard(output, guard_terms)
                variants.append(output)
            return SceneLineOutputV1(
                target_ref="",
                line="",
                rationale=(
                    "同一情境按各目标独立知识包分别生成；差异来自各自目标、"
                    "性格与知情范围。"
                ),
                variants=variants,
            )
        if diagnostic_question:
            stop = budget_stop_reason(envelope, **guard)
            if stop:
                raise ExplorationPauseError(stop)
            await _checkpoint(
                db, root, branch, error_message="探索 provider 请求需要先提交检查点"
            )
            material = _spatial_material_sections(confirmed)
            output = await _generate_exploration_payload(
                client=client,
                action=action,
                user_data=_scene_diagnostic_user_data(
                    start=start,
                    focus=focus,
                    confirmed=confirmed,
                    question=diagnostic_question,
                    subject_ref=diagnostic_subject,
                    material=material,
                ),
                system_content=SCENE_SPATIAL_DIAGNOSTIC_PROMPT,
            )
            payload = _finalize_spatial_assessment(
                output, material, subject_ref=diagnostic_subject
            )
            if diagnostic_subject and not diagnostic_subject.startswith("c_"):
                await _validate_canonical_scene_line(db, confirmed, payload)
            return payload
        stop = budget_stop_reason(envelope, **guard)
        if stop:
            raise ExplorationPauseError(stop)
        await _checkpoint(
            db, root, branch, error_message="探索 provider 请求需要先提交检查点"
        )
        output: SceneLineOutputV1 = await _generate_exploration_payload(
            client=client,
            action=action,
            user_data=_scene_line_user_data(
                start=start,
                focus=focus,
                target_ref=target_ref,
                confirmed=confirmed,
                mode=mode,
                parent_payload=parent_payload,
                instruction=instruction,
            ),
        )
    if str(output.target_ref) != target_ref:
        raise ValueError("对白目标与请求目标不一致")
    if not target_ref.startswith("c_"):
        # canonical 目标：生成后 hidden guard 消费方校验，违规即失败不落库。
        await _validate_canonical_scene_line(db, confirmed, output)
    return (
        _merge_revision(parent_payload, output, SCENE_LINE_OUTPUT_KIND, item_path)
        if mode == "revise"
        else output
    )


# ---------------------------------------------------------------------------
# Worker 2 变体：临时起点完整排演（M3-B）
# ---------------------------------------------------------------------------


async def _generate_rehearsal_performance(
    client, *, user_data: dict
) -> FullRehearsalPerformance:
    """完整排演表演卡：一次有界结构化生成（沿用已注册动作的 step 名）。"""
    return await run_managed_structured(
        client,
        LLMCallRequest(
            model=client.model_name,
            messages=[
                LLMMessage(role="system", content=FULL_REHEARSAL_CARD_PROMPT),
                LLMMessage(
                    role="user", content=json.dumps(user_data, ensure_ascii=False)
                ),
            ],
        ),
        FullRehearsalPerformance,
        step_name=SCENE_LINE_ACTION,
        capability_id=EXPLORATION_CAPABILITY,
        max_fix_attempts=0,
        transport_retries=False,
    )


async def _generate_rehearsal_orchestration(
    client, *, user_data: dict
) -> FullRehearsalRoundOrchestration:
    """完整排演统筹：每轮一次，素材/观察/状态（作者侧输入包）。"""
    return await run_managed_structured(
        client,
        LLMCallRequest(
            model=client.model_name,
            messages=[
                LLMMessage(role="system", content=FULL_REHEARSAL_ORCHESTRATION_PROMPT),
                LLMMessage(
                    role="user", content=json.dumps(user_data, ensure_ascii=False)
                ),
            ],
        ),
        FullRehearsalRoundOrchestration,
        step_name=FULL_REHEARSAL_ORCHESTRATION_STEP,
        capability_id=EXPLORATION_CAPABILITY,
        max_fix_attempts=0,
        transport_retries=False,
    )


def _rehearsal_pending_state(
    pending: dict, rehearsal: FullRehearsalRequest
) -> tuple[int, list[FullRehearsalRound], list[str]]:
    """读取检查点里的续跑状态：畸形或与冻结意图不一致即失败关闭。

    返回 ``(起始轮, 已完成轮, 已累积状态要点)``；已完成轮在恢复时不重跑，
    中断轮（尚未进入 completed_rounds）整轮重来，与 provider 前检查点语义一致。
    """
    frozen = pending.get("full_rehearsal")
    if frozen != rehearsal.model_dump(mode="json"):
        raise ValueError("未完成排演检查点与本次排演意图不一致，失败关闭")
    start_round = pending.get("round_number")
    completed_raw = pending.get("completed_rounds")
    state_notes = pending.get("state_notes")
    if (
        not isinstance(start_round, int)
        or not (FULL_REHEARSAL_ROUNDS_MIN <= start_round <= rehearsal.rounds)
        or not isinstance(completed_raw, list)
        or len(completed_raw) != start_round - 1
        or not isinstance(state_notes, list)
        or not all(isinstance(item, str) for item in state_notes)
    ):
        raise ValueError("排演检查点状态畸形，失败关闭；请新建任务")
    return (
        start_round,
        [FullRehearsalRound.model_validate(item) for item in completed_raw],
        [str(item) for item in state_notes],
    )


async def _run_full_rehearsal(
    db,
    *,
    task,
    novel_id: str,
    root,
    branch,
    envelope,
    guard: dict,
    run_snapshot: dict,
    start,
    focus: str,
    confirmed,
    rehearsal: FullRehearsalRequest,
    pending: dict,
) -> FullRehearsalOutputV1:
    """逐轮执行完整排演（M3-B）：表演卡 → 每轮统筹 → 每轮后提交式检查点。

    预算按实际调用计量 ((目标数 + 1) × 轮次)；每次 provider 请求前先提交
    检查点，请求间预算到达即暂停（沿用 paused_* 语义）。轮内中断整轮重来，
    已完成轮由 ``completed_rounds`` 承载，恢复续跑不重跑。暂停用硬阈值检查
    （对齐旧导演逐请求检查）：软 80% 提示不中断有界排演的正常完成。
    """
    targets = list(rehearsal.targets)
    _start_round, completed_rounds, state_notes = _rehearsal_pending_state(
        pending, rehearsal
    )
    guard_terms: list | None = None

    def _commit_pending() -> None:
        # round_number 恒等于 1 + 已完成轮数：恢复续跑时同一不变量可复核
        # （_rehearsal_pending_state 要求 len(completed_rounds) == round_number - 1）。
        pending["round_number"] = 1 + len(completed_rounds)
        pending["completed_rounds"] = [
            item.model_dump(mode="json") for item in completed_rounds
        ]
        pending["state_notes"] = list(state_notes)
        # 每次赋新 dict：JSON 列重复赋同一对象不触发变更追踪。
        branch.pending_round_json = dict(pending)

    async with open_project_snapshot_llm_client(db, novel_id, run_snapshot) as client:
        while 1 + len(completed_rounds) <= rehearsal.rounds:
            round_number = 1 + len(completed_rounds)
            previous_round = completed_rounds[-1] if completed_rounds else None
            cards: list[FullRehearsalPerformance] = []
            for target_ref in targets:
                stop = budget_stop_reason(
                    envelope, check_soft_thresholds=False, **guard
                )
                if stop:
                    raise ExplorationPauseError(stop)
                _commit_pending()
                await _checkpoint(
                    db,
                    root,
                    branch,
                    error_message="探索 provider 请求需要先提交检查点",
                )
                card = await _generate_rehearsal_performance(
                    client=client,
                    user_data=_rehearsal_performance_packet(
                        start=start,
                        focus=focus,
                        target_ref=target_ref,
                        confirmed=confirmed,
                        round_number=round_number,
                        previous_round=previous_round,
                    ),
                )
                if str(card.target_ref) != target_ref:
                    raise ValueError("排演表演卡目标与请求目标不一致")
                if not target_ref.startswith("c_"):
                    # canonical 目标：生成后 hidden guard 消费方校验（对齐
                    # writing 消费方方式），违规即失败不落库。
                    if guard_terms is None:
                        guard_terms = await _hidden_guard_terms(db, confirmed)
                    _assert_content_within_guard(
                        card.model_dump(mode="json"),
                        guard_terms,
                        message=(
                            "生成的排演表演卡触碰了该角色的隐藏信息边界；"
                            "本次结果不落库，请调整目标角色或资料范围后重试"
                        ),
                    )
                cards.append(card)
            stop = budget_stop_reason(envelope, check_soft_thresholds=False, **guard)
            if stop:
                raise ExplorationPauseError(stop)
            _commit_pending()
            await _checkpoint(
                db, root, branch, error_message="探索 provider 请求需要先提交检查点"
            )
            orchestration = await _generate_rehearsal_orchestration(
                client=client,
                user_data=_rehearsal_orchestration_packet(
                    start=start,
                    focus=focus,
                    confirmed=confirmed,
                    rehearsal=rehearsal,
                    round_number=round_number,
                    round_cards=cards,
                    prior_rounds=list(completed_rounds),
                    prior_state_notes=list(state_notes),
                ),
            )
            # 信任边界：素材/观察回执进入下一轮角色包，作者私密内容混入即失败。
            _assert_rehearsal_character_inputs_clean(
                orchestration,
                author_goal=str(rehearsal.author_goal or ""),
                author_private=list(getattr(start, "author_private", []) or []),
            )
            completed_rounds.append(
                FullRehearsalRound(
                    round_number=round_number,
                    performances=cards,
                    materials=orchestration.materials,
                    observations=orchestration.observations,
                )
            )
            state_notes = list(
                dict.fromkeys([*state_notes, *orchestration.state_notes])
            )
            _commit_pending()
            await _checkpoint(
                db, root, branch, error_message="排演轮次检查点未保存"
            )
            task.update_progress(
                min(0.95, len(completed_rounds) / max(1, rehearsal.rounds) * 0.95)
            )

    output = FullRehearsalOutputV1(
        targets=targets,
        rounds=list(completed_rounds),
        state_notes=list(state_notes),
    )
    if len(output.rounds) != rehearsal.rounds:
        # 循环不变量：恰好完成全部轮次；FullRehearsalOutputV1 还会复核编号
        # 连续与每轮表演卡恰好覆盖全部目标。
        raise ValueError("完整排演轮次不完整，失败关闭")
    return output


def _request_context(meta: dict, root_request: dict) -> tuple[str, str, dict, str]:
    """读取任务模式、动作、起点与焦点，并与根冻结起点比对。"""
    request = dict(meta.get("request") or {})
    mode = str(request.get("mode") or "start")
    action = str(meta.get("action") or "")
    if action not in STEP_NAME_BY_ACTION:
        raise ValueError("探索任务缺少合法动作")
    start_dump = request.get("start")
    if start_dump is None:
        start_dump = (root_request or {}).get("exploration_start")
    start_dump = dict(start_dump or {})
    focus = str(
        request.get("focus")
        if request.get("focus") is not None
        else (root_request or {}).get("exploration_focus") or ""
    )
    return mode, action, start_dump, focus


def _require_run_snapshot(meta: dict, root, novel_id: str) -> dict:
    run_snapshot = meta.get("llm_execution_snapshot") or root.llm_execution_snapshot_json
    if (
        not isinstance(run_snapshot, dict)
        or str(run_snapshot.get("novel_id") or "") != novel_id
    ):
        raise ValueError("探索任务缺少匹配的项目模型快照")
    return run_snapshot


# ---------------------------------------------------------------------------
# Worker 1：B1 沙盘 / B2 事件（写推进步骤）
# ---------------------------------------------------------------------------


@task_handler(
    EXPLORATION_PROGRESSION_TASK,
    recovery_policy="never_retry",
    max_attempts=1,
    retry_transient_llm_errors=False,
    root_capability_id=EXPLORATION_CAPABILITY,
    run_request_limit=_request_limit,
    run_token_limit=_token_limit,
    run_deadline_seconds=_deadline_seconds,
    run_id=_stable_root_id,
    run_envelope_checkpoint=_mirror_progression_envelope,
)
async def handle_story_exploration_progression(db, task):
    require_task_checkpoint_session(db)
    require_story_exploration_enabled()
    meta = _meta(task)
    novel_id = str(task.novel_id)
    root_id = str(meta.get("exploration_root_id") or "")
    branch_id = str(meta.get("exploration_branch_id") or "")
    if not root_id or not branch_id:
        raise ValueError("探索任务缺少持久根或分支")
    mode, action, start_dump, focus = _request_context(meta, None)
    if action == SCENE_LINE_ACTION:
        raise ValueError("场景一句对白任务应由场景执行器处理")
    if isinstance(meta.get("request"), dict) and (
        meta["request"].get("multi_targets")
        or meta["request"].get("diagnostic")
        or meta["request"].get("full_rehearsal")
    ):
        raise ValueError(
            "multi_targets/diagnostic/full_rehearsal 仅支持场景一句对白，失败关闭"
        )

    root = await get_progression_root(db, novel_id, root_id, lock=True)
    branch = await get_progression_branch(db, novel_id, branch_id, lock=True)
    if str(branch.root_id) != root_id:
        raise ValueError("探索分支与运行根不匹配")
    if str(task.id) != str(root.current_task_id) or str(task.id) != str(
        branch.current_task_id
    ):
        raise ValueError("探索任务身份已失效")
    root_request = dict(root.request_json or {})
    if root_request.get("exploration_start") != start_dump:
        raise ValueError("任务起点与探索根冻结起点不一致，失败关闭")
    scale = str(
        meta.get("exploration_scale") or root_request.get("exploration_scale") or ""
    )
    if mode != "start" and mode not in {"detail", "revise"}:
        raise ValueError("不支持的探索任务模式")

    envelope = current_ai_run_envelope()
    _check_envelope_identity(envelope, root_id=root_id, novel_id=novel_id)
    guard = _budget_guard(meta)
    start = _validate_start_dump(start_dump)
    counterfactual_of, changed_assumptions = _counterfactual_request_params(
        root_request
    )
    event_mode_hint = _event_mode_hint_for(root_request, action)
    if mode == "start":
        _require_preview_hash(
            novel_id=novel_id,
            scale=scale,
            start=start,
            focus=focus,
            expected=str(meta.get("budget_preview_hash") or ""),
            counterfactual_of_result_id=counterfactual_of,
            changed_assumptions=changed_assumptions,
            event_mode_hint=event_mode_hint,
        )

    confirmed = await prepare_confirmed_ai_action(
        db,
        novel_id=novel_id,
        action=action,
        confirmation_id=str(root.context_confirmation_id),
    )
    _require_confirmation_matches(
        confirmed, scale=scale, start_dump=start_dump, focus=focus
    )

    parent_row = None
    parent_payload = None
    parent_id: str | None = None
    parent_output_hash: str | None = None
    item_path = ""
    item_content_hash: str | None = None
    locked_specs: list[tuple[str, str]] = []
    if mode in {"detail", "revise"}:
        parent_row, parent_payload = await _load_parent_result(
            db,
            model=StoryWorldProgressionStep,
            novel_id=novel_id,
            branch=branch,
            parent_id=str(meta.get("parent_result_id") or ""),
        )
        # 检查点会 expire 全部 ORM 对象；父结果标识须在首个检查点前取成纯值。
        parent_id = str(parent_row.id)
        parent_output_hash = str(parent_row.output_hash or "")
        if mode == "revise":
            raw_item_text = meta.get("item_text")
            target = check_revision_target(
                parent_payload,
                str(meta.get("item_path") or ""),
                None if raw_item_text is None else str(raw_item_text),
                scale,
            )
            item_path = target["key"]
            item_content_hash = target["item_content_hash"]
        # detail/revise 的 action 已由 API 按父 payload 模式映射（_generation_action），
        # worker 侧只需沿用 meta.action；误配会在确认校验处失败关闭。
        # 分支当前锁定集（纯值，检查点 expire 不受影响）；修订目标被锁定在
        # 提交前已拒绝，worker 内再权威校验一次（失败关闭，不产生模型调用）。
        locked_specs = [
            (item.item_path, item.item_content_hash)
            for item in await current_locked_items(
                db, novel_id=novel_id, branch_id=branch.id, chain="progression"
            )
        ]
        if mode == "revise" and any(item_path == locked for locked, _ in locked_specs):
            raise ValueError("该条目已锁定，请先解锁再修改")
        for locked_path, _pinned in locked_specs:
            if len(_resolve_revision_items(parent_payload, locked_path, scale)) != 1:
                raise ValueError(
                    f"锁定条目 {locked_path} 与父结果不一致，无法保持锁定内容；"
                    "请先解锁或重新锁定"
                )

    pending = dict(branch.pending_step_json or {})
    _require_pending_mode(pending, mode)
    root.status = "running"
    branch.status = "running"
    if not pending:
        pending = {
            "mode": mode,
            "parent_result_id": parent_id,
            "start": start_dump,
            "scale": scale,
            "focus": focus,
        }
        branch.pending_step_json = pending
    await _checkpoint(db, root, branch, error_message="探索检查点未保存，未开始模型请求")

    run_snapshot = _require_run_snapshot(meta, root, novel_id)
    bridge_target = (
        str(meta.get("bridge_target")) if meta.get("bridge_target") else None
    )
    user_data = _sandbox_event_user_data(
        start=start,
        focus=focus,
        confirmed=confirmed,
        mode=mode,
        parent_payload=parent_payload,
        instruction=str(meta.get("instruction") or ""),
        bridge_target=bridge_target,
        single_item=mode == "revise",
    )

    try:
        async with open_project_snapshot_llm_client(db, novel_id, run_snapshot) as client:
            stop = budget_stop_reason(envelope, **guard)
            if stop:
                raise ExplorationPauseError(stop)
            await _checkpoint(
                db, root, branch, error_message="探索 provider 请求需要先提交检查点"
            )
            output = await _generate_exploration_payload(
                client=client,
                action=action,
                user_data=user_data,
                system_content=_event_system_prompt(action, event_mode_hint),
            )
        payload_out = (
            _merge_revision(parent_payload, output, scale, item_path)
            if mode == "revise"
            else output
        )
        honored_locks: list[str] = []
        if mode in {"detail", "revise"} and locked_specs:
            # 服务端强制回填：锁定项按父 payload 逐字恢复，不靠模型自觉。
            merged_dict, honored_locks = _enforce_locked_items(
                parent_payload, payload_out.model_dump(mode="json"), locked_specs, scale
            )
            payload_out = PAYLOAD_MODEL_BY_ACTION[action].model_validate(merged_dict)
        envelope_out = ExplorationOutputEnvelope(
            output_kind=OUTPUT_KIND_BY_ACTION[action],
            schema_version=EXPLORATION_OUTPUT_SCHEMA_VERSION,
            payload=payload_out,
        )
        row = await _write_progression_result(
            db,
            root=root,
            branch=branch,
            parent_id=parent_id,
            parent_output_hash=parent_output_hash,
            envelope=envelope_out,
            mode=mode,
            envelope_run=envelope,
            item_path=item_path or None,
            item_content_hash=item_content_hash,
            honored_locks=honored_locks,
        )
    except ExplorationPauseError as pause:
        return await _pause_progression(
            db, root, branch, envelope, guard, pause.reason
        )
    except Exception as error:
        stop = _classify_stop(error, guard, envelope)
        if stop is not None:
            return await _pause_progression(db, root, branch, envelope, guard, stop)
        branch.status = "failed"
        root.status = "failed"
        root.current_task_id = None
        branch.current_task_id = None
        branch.pending_step_json = {
            **(branch.pending_step_json or {}),
            "safe_error": _safe_error(error),
        }
        await _checkpoint(db, root, branch, error_message="探索失败状态未保存")
        raise

    branch.pending_step_json = {}
    branch.parent_step_id = row.id
    branch.status = "complete"
    branch.stop_reason = None
    branch.current_task_id = None
    root.status = "ready"
    root.current_task_id = None
    root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
    await _checkpoint(db, root, branch, extra=row, error_message="探索结果未持久化")
    task.update_progress(1.0)
    return _completed_receipt(
        row=row, envelope=envelope_out, root_id=root_id, branch_id=branch_id
    )


async def _pause_progression(db, root, branch, envelope, guard, stop: str):
    status = "paused_unknown" if stop == "provider_result_unknown" else "paused_budget"
    root.status = branch.status = status
    branch.stop_reason = stop
    root.current_task_id = branch.current_task_id = None
    root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
    await _checkpoint(db, root, branch, error_message="探索预算暂停状态未保存")
    return _task_receipt(
        status, root_id=str(root.id), branch_id=str(branch.id), budget_stop=stop
    )


async def _counterfactual_baseline_provenance(
    db, *, novel_id, baseline_result_id: str
) -> dict:
    """基线行 start 指纹与输出哈希：实际读集与父版本可核对（M3-A 影响标记）。

    正常链路请求阶段已校验基线为同作品沙盘结果，行不可变；查询不到（异常
    数据）时返回空值如实披露，不编造指纹。
    """

    row = await db.scalar(
        select(StoryWorldProgressionStep).where(
            StoryWorldProgressionStep.novel_id == novel_id,
            StoryWorldProgressionStep.id == UUID(baseline_result_id),
        )
    )
    if row is None:
        return {"base_result_fingerprint": None, "parent_output_hash": None}
    baseline_root = await db.get(StoryWorldProgressionRoot, row.root_id)
    fingerprint = (
        (baseline_root.request_json or {}).get("exploration_start_fingerprint")
        if baseline_root is not None
        else None
    )
    return {
        "base_result_fingerprint": str(fingerprint) if fingerprint else None,
        "parent_output_hash": str(row.output_hash) if row.output_hash else None,
    }


async def _write_progression_result(
    db,
    *,
    root,
    branch,
    parent_id: str | None,
    parent_output_hash: str | None,
    envelope: ExplorationOutputEnvelope,
    mode: str,
    envelope_run,
    item_path: str | None,
    item_content_hash: str | None,
    honored_locks: list[str] | None = None,
):
    """写入结果步骤；parent 标识须在检查点前捕获，避免检查点 expire 后懒加载。

    完整性校验与 ``append_progression_step`` 对齐（父存在、属于本根、输出哈希
    未变），但“期望父步骤”只看 AI 结果行：author_edit 与 lock_set 行不算
    AI 结果（M3-A），不改变续写基线，因此锁定/编辑之后仍可在最新 AI 结果上
    续算；写入改为服务内直接落行，不再复用推进链的线性 append 不变量。
    """
    root_request = root.request_json or {}
    input_payload = {
        "mode": mode,
        "start_summary": {
            "kind": (root_request.get("exploration_start") or {}).get("kind"),
            "fingerprint": root_request.get("exploration_start_fingerprint"),
        },
        "parent_result_id": parent_id,
        "parent_output_hash": parent_output_hash,
        "item_path": item_path,
        "item_content_hash": item_content_hash,
    }
    if honored_locks:
        input_payload["honored_locks"] = [str(path) for path in honored_locks]
    if root_request.get("counterfactual_of"):
        # 反事实对照（M2）：结果行记录基线与变更条件文本，供对照比较校验链路。
        input_payload["counterfactual_of"] = str(root_request["counterfactual_of"])
        input_payload["changed_assumption_texts"] = [
            str(item.get("text") or "")
            for item in (root_request.get("changed_assumptions") or [])
            if isinstance(item, dict)
        ]
        # 影响与比较标记（M3-A）：补记基线行读集指纹与基线行输出版本，使
        # “实际读集与父版本”可核对；续算行已有 parent_output_hash（续算父），
        # 不覆盖，仅反事实起始行记录基线版本。
        provenance = await _counterfactual_baseline_provenance(
            db,
            novel_id=root.novel_id,
            baseline_result_id=str(root_request["counterfactual_of"]),
        )
        input_payload["base_result_fingerprint"] = provenance[
            "base_result_fingerprint"
        ]
        if not input_payload.get("parent_output_hash"):
            input_payload["parent_output_hash"] = provenance["parent_output_hash"]

    if parent_id:
        parent = await db.get(StoryWorldProgressionStep, UUID(parent_id))
        if parent is None or str(parent.root_id) != str(root.id):
            raise ConflictError("续跑步骤不属于当前推进根")
        if str(parent.output_hash or "") != str(parent_output_hash or ""):
            raise ConflictError("父步骤哈希已变化，不能续写推进历史")
    rows = (
        await db.scalars(
            select(StoryWorldProgressionStep)
            .where(
                StoryWorldProgressionStep.novel_id == root.novel_id,
                StoryWorldProgressionStep.branch_id == branch.id,
            )
            .order_by(StoryWorldProgressionStep.step_number.desc())
            .limit(_TIP_SCAN_CAP)
        )
    ).all()
    previous_ai = None
    for row in rows:
        row_envelope = unpack_exploration_output(row)
        if (
            row_envelope is None
            or row_envelope.output_kind
            not in {AUTHOR_EDIT_OUTPUT_KIND, LOCK_SET_OUTPUT_KIND}
        ):
            previous_ai = row
            break
    expected_parent = (
        str(previous_ai.id)
        if previous_ai is not None
        else (str(branch.parent_step_id) if branch.parent_step_id else None)
    )
    if expected_parent != (str(parent_id) if parent_id else None):
        raise ConflictError("推进分支的父步骤已变化，请从当前历史重新选择")
    number = int(rows[0].step_number) + 1 if rows else 1
    input_hash = content_hash(
        {
            "source_hash": branch.source_hash,
            "parent_step_id": parent_id,
            "parent_output_hash": input_payload.get("parent_output_hash"),
            "input": input_payload,
        }
    )
    output_payload = pack_exploration_output(envelope)
    row = StoryWorldProgressionStep(
        id=uuid.uuid4(),
        novel_id=root.novel_id,
        root_id=root.id,
        branch_id=branch.id,
        parent_step_id=UUID(parent_id) if parent_id else None,
        step_number=number,
        source_hash=branch.source_hash,
        input_hash=input_hash,
        output_hash=content_hash(
            {
                "input_hash": input_hash,
                "output": output_payload,
                "state": {},
            }
        ),
        input_json=input_payload,
        result_json=output_payload,
        state_json={},
        metrics_json={"mode": mode, "exploration": True},
        basis_changed=False,
    )
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# Worker 2：B3 场景一句对白（写导演回合）
# ---------------------------------------------------------------------------


@task_handler(
    EXPLORATION_SCENE_TASK,
    recovery_policy="never_retry",
    max_attempts=1,
    retry_transient_llm_errors=False,
    root_capability_id=EXPLORATION_CAPABILITY,
    run_request_limit=_request_limit,
    run_token_limit=_token_limit,
    run_deadline_seconds=_deadline_seconds,
    run_id=_stable_root_id,
    run_envelope_checkpoint=_mirror_scene_envelope,
)
async def handle_story_exploration_scene(db, task):
    require_task_checkpoint_session(db)
    require_story_exploration_enabled()
    meta = _meta(task)
    novel_id = str(task.novel_id)
    root_id = str(meta.get("exploration_root_id") or "")
    branch_id = str(meta.get("exploration_branch_id") or "")
    if not root_id or not branch_id:
        raise ValueError("探索任务缺少持久根或分支")
    action = SCENE_LINE_ACTION
    mode = str((meta.get("request") or {}).get("mode") or "start")
    if mode not in {"start", "detail", "revise"}:
        raise ValueError("不支持的探索任务模式")

    root = await get_director_root(db, novel_id, root_id, lock=True)
    branch = await get_director_branch(db, novel_id, branch_id, lock=True)
    if str(branch.root_id) != root_id:
        raise ValueError("探索分支与运行根不匹配")
    if str(task.id) != str(root.current_task_id) or str(task.id) != str(
        branch.current_task_id
    ):
        raise ValueError("探索任务身份已失效")
    root_request = dict(root.request_json or {})
    _mode, _action, start_dump, focus = _request_context(meta, root_request)
    if root_request.get("exploration_start") != start_dump:
        raise ValueError("任务起点与探索根冻结起点不一致，失败关闭")
    scale = str(
        meta.get("exploration_scale") or root_request.get("exploration_scale") or ""
    )

    envelope = current_ai_run_envelope()
    _check_envelope_identity(envelope, root_id=root_id, novel_id=novel_id)
    guard = _budget_guard(meta)
    start = _validate_start_dump(start_dump)
    scene_request = dict(meta.get("request") or {})
    multi_targets = _scene_multi_targets(scene_request, mode=mode)
    diagnostic_question, diagnostic_subject = _scene_diagnostic_request(
        scene_request, mode=mode
    )
    if multi_targets and diagnostic_question:
        raise ValueError("multi_targets 与 diagnostic 互斥，失败关闭")
    rehearsal = _scene_full_rehearsal(
        scene_request, mode=mode, root_request=root_request
    )
    if rehearsal is not None and (multi_targets or diagnostic_question):
        raise ValueError("完整排演与 multi_targets/diagnostic 互斥，失败关闭")
    if mode == "start":
        _require_preview_hash(
            novel_id=novel_id,
            scale=scale,
            start=start,
            focus=focus,
            expected=str(meta.get("budget_preview_hash") or ""),
            multi_targets=multi_targets,
            diagnostic_question=diagnostic_question,
            full_rehearsal=rehearsal,
        )

    confirmed = await prepare_confirmed_ai_action(
        db,
        novel_id=novel_id,
        action=action,
        confirmation_id=str(meta.get("context_confirmation_id") or ""),
    )
    _require_confirmation_matches(
        confirmed, scale=scale, start_dump=start_dump, focus=focus
    )

    parent_row = None
    parent_payload = None
    parent_id: str | None = None
    item_path = ""
    item_content_hash: str | None = None
    locked_specs: list[tuple[str, str]] = []
    if mode in {"detail", "revise"}:
        parent_row, parent_payload = await _load_parent_result(
            db,
            model=StorySceneDirectorRound,
            novel_id=novel_id,
            branch=branch,
            parent_id=str(meta.get("parent_result_id") or ""),
        )
        # 检查点会 expire 全部 ORM 对象；父结果标识须在首个检查点前取成纯值。
        parent_id = str(parent_row.id)
        if mode == "revise":
            raw_item_text = meta.get("item_text")
            target = check_revision_target(
                parent_payload,
                str(meta.get("item_path") or ""),
                None if raw_item_text is None else str(raw_item_text),
                SCENE_LINE_OUTPUT_KIND,
            )
            item_path = target["key"]
            item_content_hash = target["item_content_hash"]
        # 分支当前锁定集（纯值，检查点 expire 不受影响）；修订目标被锁定在
        # 提交前已拒绝，worker 内再权威校验一次（失败关闭，不产生模型调用）。
        locked_specs = [
            (item.item_path, item.item_content_hash)
            for item in await current_locked_items(
                db, novel_id=novel_id, branch_id=branch.id, chain="scene"
            )
        ]
        if mode == "revise" and any(item_path == locked for locked, _ in locked_specs):
            raise ValueError("该条目已锁定，请先解锁再修改")
        for locked_path, _pinned in locked_specs:
            resolved = _resolve_revision_items(
                parent_payload, locked_path, SCENE_LINE_OUTPUT_KIND
            )
            if len(resolved) != 1:
                raise ValueError(
                    f"锁定条目 {locked_path} 与父结果不一致，无法保持锁定内容；"
                    "请先解锁或重新锁定"
                )

    if rehearsal is not None:
        # 完整排演（M3-B）：目标由 full_rehearsal.targets 承载，无单目标。
        target_ref = ""
    elif mode == "start":
        if multi_targets or diagnostic_question:
            # 多目标由 variants 承载、空间诊断由 spatial_assessment 承载，无单目标。
            target_ref = ""
        else:
            target_ref = str(meta.get("target_ref") or "")
            if not target_ref:
                raise ValueError("场景一句对白必须指定目标角色")
    else:
        target_ref = str(
            meta.get("target_ref") or (parent_payload or {}).get("target_ref") or ""
        )
        if not target_ref:
            raise ValueError("场景一句对白必须指定目标角色")

    pending = dict(branch.pending_round_json or {})
    _require_pending_mode(
        pending, FULL_REHEARSAL_PENDING_MODE if rehearsal is not None else mode
    )
    root.status = "running"
    branch.status = "running"
    if not pending:
        if rehearsal is not None:
            pending = {
                "mode": FULL_REHEARSAL_PENDING_MODE,
                "parent_result_id": None,
                "start": start_dump,
                "scale": scale,
                "focus": focus,
                "full_rehearsal": rehearsal.model_dump(mode="json"),
                "round_number": 1,
                "completed_rounds": [],
                "state_notes": [],
            }
        else:
            pending = {
                "mode": mode,
                "parent_result_id": parent_id,
                "start": start_dump,
                "scale": scale,
                "focus": focus,
                "target_ref": target_ref,
                **({"multi_targets": multi_targets} if multi_targets else {}),
                **(
                    {"diagnostic_question": diagnostic_question}
                    if diagnostic_question
                    else {}
                ),
            }
        branch.pending_round_json = pending
    await _checkpoint(db, root, branch, error_message="探索检查点未保存，未开始模型请求")

    run_snapshot = _require_run_snapshot(meta, root, novel_id)

    try:
        if rehearsal is not None:
            # 完整排演（M3-B）：逐轮表演卡 + 每轮统筹，结果整体落一行。
            payload = await _run_full_rehearsal(
                db,
                task=task,
                novel_id=novel_id,
                root=root,
                branch=branch,
                envelope=envelope,
                guard=guard,
                run_snapshot=run_snapshot,
                start=start,
                focus=focus,
                confirmed=confirmed,
                rehearsal=rehearsal,
                pending=pending,
            )
            envelope_out = ExplorationOutputEnvelope(
                output_kind=FULL_REHEARSAL_OUTPUT_KIND,
                schema_version=EXPLORATION_OUTPUT_SCHEMA_VERSION,
                payload=payload,
            )
            row = await _write_scene_result(
                db,
                root=root,
                branch=branch,
                parent_id=None,
                envelope=envelope_out,
                mode=FULL_REHEARSAL_PENDING_MODE,
                envelope_run=envelope,
                item_path=None,
                item_content_hash=None,
                full_rehearsal=rehearsal,
            )
        else:
            payload = await _run_scene_generation(
                db,
                novel_id=novel_id,
                root=root,
                branch=branch,
                envelope=envelope,
                guard=guard,
                run_snapshot=run_snapshot,
                action=action,
                mode=mode,
                start=start,
                focus=focus,
                confirmed=confirmed,
                instruction=str(meta.get("instruction") or ""),
                target_ref=target_ref,
                parent_payload=parent_payload,
                item_path=item_path,
                multi_targets=multi_targets,
                diagnostic_question=diagnostic_question,
                diagnostic_subject=diagnostic_subject,
            )
            honored_locks: list[str] = []
            if mode in {"detail", "revise"} and locked_specs:
                # 服务端强制回填：锁定台词以父 payload 为准逐字恢复，不靠模型自觉。
                payload_dict, honored_locks = _enforce_locked_items(
                    parent_payload,
                    payload.model_dump(mode="json"),
                    locked_specs,
                    SCENE_LINE_OUTPUT_KIND,
                )
                payload = SceneLineOutputV1.model_validate(payload_dict)
            envelope_out = ExplorationOutputEnvelope(
                output_kind=SCENE_LINE_OUTPUT_KIND,
                schema_version=EXPLORATION_OUTPUT_SCHEMA_VERSION,
                payload=payload,
            )
            row = await _write_scene_result(
                db,
                root=root,
                branch=branch,
                parent_id=parent_id,
                envelope=envelope_out,
                mode=mode,
                envelope_run=envelope,
                item_path=item_path or None,
                item_content_hash=item_content_hash,
                honored_locks=honored_locks,
                multi_targets=multi_targets,
                diagnostic_question=diagnostic_question,
            )
    except ExplorationPauseError as pause:
        return await _pause_scene(db, root, branch, envelope, pause.reason)
    except Exception as error:
        stop = _classify_stop(error, guard, envelope)
        if stop is not None:
            return await _pause_scene(db, root, branch, envelope, stop)
        branch.status = "failed"
        root.status = "failed"
        root.current_task_id = None
        branch.current_task_id = None
        branch.pending_round_json = {
            **(branch.pending_round_json or {}),
            "safe_error": _safe_error(error),
        }
        await _checkpoint(db, root, branch, error_message="探索失败状态未保存")
        raise

    branch.pending_round_json = {}
    branch.status = "complete"
    branch.current_task_id = None
    root.status = "ready"
    root.current_task_id = None
    root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
    await _checkpoint(db, root, branch, extra=row, error_message="探索对白结果未持久化")
    task.update_progress(1.0)
    return _completed_receipt(
        row=row, envelope=envelope_out, root_id=root_id, branch_id=branch_id
    )


async def _pause_scene(db, root, branch, envelope, stop: str):
    status = "paused_unknown" if stop == "provider_result_unknown" else "paused_budget"
    root.status = branch.status = status
    root.current_task_id = branch.current_task_id = None
    root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
    await _checkpoint(db, root, branch, error_message="探索预算暂停状态未保存")
    return _task_receipt(
        status, root_id=str(root.id), branch_id=str(branch.id), budget_stop=stop
    )


async def _write_scene_result(
    db,
    *,
    root,
    branch,
    parent_id: str | None,
    envelope: ExplorationOutputEnvelope,
    mode: str,
    envelope_run,
    item_path: str | None,
    item_content_hash: str | None,
    honored_locks: list[str] | None = None,
    multi_targets: list[str] | None = None,
    diagnostic_question: str | None = None,
    full_rehearsal: FullRehearsalRequest | None = None,
):
    next_number = (
        await db.scalar(
            select(func.max(StorySceneDirectorRound.round_number)).where(
                StorySceneDirectorRound.novel_id == root.novel_id,
                StorySceneDirectorRound.branch_id == branch.id,
            )
        )
        or 0
    ) + 1
    root_request = root.request_json or {}
    input_json = {
        "mode": mode,
        "start_summary": {
            "kind": (root_request.get("exploration_start") or {}).get("kind"),
            "fingerprint": root_request.get("exploration_start_fingerprint"),
        },
        "parent_result_id": parent_id,
        "item_path": item_path,
        "item_content_hash": item_content_hash,
    }
    if honored_locks:
        input_json["honored_locks"] = [str(path) for path in honored_locks]
    if multi_targets:
        input_json["multi_targets"] = [str(item) for item in multi_targets]
    if diagnostic_question:
        input_json["diagnostic_question"] = str(diagnostic_question)
    if full_rehearsal is not None:
        # 完整排演（M3-B）：结果行记录排演身份（目标与轮次），与聚焦输出区分。
        input_json["targets"] = [str(item) for item in full_rehearsal.targets]
        input_json["rounds"] = int(full_rehearsal.rounds)
    row = StorySceneDirectorRound(
        novel_id=root.novel_id,
        root_id=root.id,
        branch_id=branch.id,
        round_number=next_number,
        parent_round_id=UUID(parent_id) if parent_id else None,
        source_hash=branch.source_hash,
        input_hash=content_hash(input_json),
        output_hash=content_hash(pack_exploration_output(envelope)),
        input_json=input_json,
        output_json=pack_exploration_output(envelope),
        state_json={},
        run_envelope_json=envelope_run.snapshot().model_dump(mode="json"),
    )
    db.add(row)
    await db.flush()
    return row
