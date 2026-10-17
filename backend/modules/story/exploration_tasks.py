"""Author-authorized multi-scale exploration workers (P0 §5/§7).

两个 task_handler 承担三档探索任务：
- ``story_exploration_progression_task``：B1 沙盘与 B2 事件（诊断/补桥），
  结果写 ``story_world_progression_steps``（零参与者紧凑步骤）。
- ``story_exploration_scene_task``：B3 场景一句对白，结果写
  ``story_scene_director_rounds``；canonical 目标生成后做 hidden guard
  消费方校验，违规即失败不落库。

骨架对齐 ``director_tasks`` / ``world_progression_tasks``：never_retry、
信封身份校验、冻结起点与任务 meta/根 request 比对、preview hash 重算、
provider 前后检查点（pending_step_json / pending_round_json）、预算暂停
paused_* 语义。detail/revise 由同一对 worker 承担（meta.mode）。
"""

from __future__ import annotations

import json
from copy import deepcopy
from uuid import UUID

from sqlalchemy import func, select

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
)
from modules.evidence.facade import (
    build_hidden_guard_context,
    prepare_confirmed_ai_action,
)
from modules.project.facade import open_project_snapshot_llm_client
from modules.story.director_budget import budget_stop_reason
from modules.story.exploration_budget import preview_exploration_budget
from modules.story.exploration_feature import require_story_exploration_enabled
from modules.story.exploration_schemas import (
    EVENT_OUTPUT_KIND,
    EXPLORATION_OUTPUT_SCHEMA_VERSION,
    SANDBOX_OUTPUT_KIND,
    SCENE_LINE_OUTPUT_KIND,
    EventOutputV1,
    ExplorationOutputEnvelope,
    SandboxOutputV1,
    SceneLineOutputV1,
)
from modules.story.exploration_service import (
    pack_exploration_output,
    unpack_exploration_output,
)
from modules.story.models import StorySceneDirectorRoot, StorySceneDirectorRound
from modules.story.world_progression_models import (
    StoryWorldProgressionRoot,
    StoryWorldProgressionStep,
)
from modules.story.world_progression_service import (
    append_progression_step,
    get_progression_branch,
    get_progression_root,
)

EXPLORATION_PROGRESSION_TASK = "story_exploration_progression_task"
EXPLORATION_SCENE_TASK = "story_exploration_scene_task"
EXPLORATION_CAPABILITY = "story.exploration"

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
) -> None:
    current = preview_exploration_budget(
        novel_id=novel_id,
        scale=scale,
        start=start,
        focus=focus,
        counterfactual_of_result_id=counterfactual_of_result_id,
        changed_assumptions=changed_assumptions,
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


# ---------------------------------------------------------------------------
# 修订目标定位（P0 §8.1：item_path + item_text，不用客户端摘要做定位键）
# ---------------------------------------------------------------------------

_BASE_KIND_BY_SCALE = {
    "sandbox": SANDBOX_OUTPUT_KIND,
    "event": EVENT_OUTPUT_KIND,
    "scene_line": SCENE_LINE_OUTPUT_KIND,
}


def _normalize_base_kind(kind_or_scale: str) -> str:
    return _BASE_KIND_BY_SCALE.get(kind_or_scale, kind_or_scale)


def _revision_items(payload: dict, base_kind: str) -> list[dict]:
    """可修订条目枚举：与前端卡片同构（sandbox 链环 / event 缺口或补桥 / 整句）。"""
    base_kind = _normalize_base_kind(base_kind)
    if base_kind == SANDBOX_OUTPUT_KIND:
        return [
            {"key": f"chain:{index}", "item": item}
            for index, item in enumerate(payload.get("influence_chain") or [])
        ]
    if base_kind == EVENT_OUTPUT_KIND:
        bridge = payload.get("mode") == "bridge"
        rows = (
            payload.get("bridge_candidates") if bridge else payload.get("gaps")
        ) or []
        prefix = "bridge" if bridge else "gap"
        return [
            {"key": f"{prefix}:{index}", "item": item}
            for index, item in enumerate(rows)
        ]
    return [{"key": "line", "item": payload.get("line")}]


def _revision_entry_text(key: str, item) -> str:
    """条目当前展示文本；与前端卡片渲染口径一致，用于防漂移比对。"""
    kind = str(key or "").partition(":")[0]
    if kind == "line":
        return str(item or "")
    if kind == "chain":
        return str((item or {}).get("effect") or "")
    if kind == "gap":
        return str((item or {}).get("description") or "")
    return "\n".join(str(step) for step in (item or {}).get("steps") or [])


def check_revision_target(
    parent_payload: dict, item_path: str, item_text: str | None, base_kind: str
) -> dict:
    """按冻结路径语法（chain:N/gap:N/bridge:N/line）定位父条目并做防漂移比对。

    解析不到、路径越界或 item_text 与父内容不一致即失败关闭；返回
    ``{"key", "item", "item_content_hash"}``，内容哈希由服务端计算。
    """

    path = str(item_path or "").strip()
    matches = [
        row for row in _revision_items(parent_payload, base_kind) if row["key"] == path
    ]
    if len(matches) != 1:
        raise ValueError(
            f"修订路径 {path or '(空)'} 不在父结果的可修订条目中；请刷新结果后重选"
        )
    target = matches[0]
    if item_text is not None and str(item_text) != _revision_entry_text(
        target["key"], target["item"]
    ):
        raise ValueError("所选条目内容已变化，请刷新结果后再提交修订")
    return {
        "key": target["key"],
        "item": target["item"],
        "item_content_hash": content_hash(target["item"]),
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
    return parent_row, base_envelope.payload.model_dump(mode="json")


async def _generate_exploration_payload(*, client, action: str, user_data: dict):
    return await run_managed_structured(
        client,
        LLMCallRequest(
            model=client.model_name,
            messages=[
                LLMMessage(role="system", content=_SYSTEM_PROMPTS[action]),
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


async def _validate_canonical_scene_line(
    db, confirmed, output: SceneLineOutputV1
) -> None:
    """canonical 目标的生成后守卫：hidden truth 短语出现在输出即失败不落库。"""
    from modules.evidence.compilation.knowledge import redact_hidden_phrases

    terms = await build_hidden_guard_context(db, confirmed_context=confirmed)
    text = json.dumps(output.model_dump(mode="json"), ensure_ascii=False)
    if redact_hidden_phrases(text, [term.phrase for term in terms]) != text:
        raise ValueError(
            "生成的一句对白触碰了该角色的隐藏信息边界；本次结果不落库，"
            "请调整目标角色或资料范围后重试"
        )


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
    if mode == "start":
        _require_preview_hash(
            novel_id=novel_id,
            scale=scale,
            start=start,
            focus=focus,
            expected=str(meta.get("budget_preview_hash") or ""),
            counterfactual_of_result_id=counterfactual_of,
            changed_assumptions=changed_assumptions,
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
        elif mode == "detail" and scale == EVENT_OUTPUT_KIND:
            # 详略保持原模式：诊断仍诊断，补桥仍补桥。
            action = (
                EVENT_BRIDGE_ACTION
                if parent_payload.get("mode") == "bridge"
                else EVENT_DIAGNOSE_ACTION
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
                client=client, action=action, user_data=user_data
            )
        envelope_out = ExplorationOutputEnvelope(
            output_kind=OUTPUT_KIND_BY_ACTION[action],
            schema_version=EXPLORATION_OUTPUT_SCHEMA_VERSION,
            payload=(
                _merge_revision(parent_payload, output, scale, item_path)
                if mode == "revise"
                else output
            ),
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
):
    """写入结果步骤；parent 标识须在检查点前捕获，避免检查点 expire 后懒加载。"""
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
    if root_request.get("counterfactual_of"):
        # 反事实对照（M2）：结果行记录基线与变更条件文本，供对照比较校验链路。
        input_payload["counterfactual_of"] = str(root_request["counterfactual_of"])
        input_payload["changed_assumption_texts"] = [
            str(item.get("text") or "")
            for item in (root_request.get("changed_assumptions") or [])
            if isinstance(item, dict)
        ]
    return await append_progression_step(
        db,
        novel_id=str(root.novel_id),
        root=root,
        branch=branch,
        parent_step_id=parent_id,
        source_hash=branch.source_hash,
        input_payload=input_payload,
        output_payload=pack_exploration_output(envelope),
        state={},
        metrics={"mode": mode, "exploration": True},
        basis_changed=False,
    )


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
    from modules.story.director_service import get_director_branch, get_director_root

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
    if mode == "start":
        _require_preview_hash(
            novel_id=novel_id,
            scale=scale,
            start=start,
            focus=focus,
            expected=str(meta.get("budget_preview_hash") or ""),
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

    target_ref = str(
        meta.get("target_ref") or (parent_payload or {}).get("target_ref") or ""
    )
    if not target_ref:
        raise ValueError("场景一句对白必须指定目标角色")

    pending = dict(branch.pending_round_json or {})
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
            "target_ref": target_ref,
        }
        branch.pending_round_json = pending
    await _checkpoint(db, root, branch, error_message="探索检查点未保存，未开始模型请求")

    run_snapshot = _require_run_snapshot(meta, root, novel_id)
    user_data = _scene_line_user_data(
        start=start,
        focus=focus,
        target_ref=target_ref,
        confirmed=confirmed,
        mode=mode,
        parent_payload=parent_payload,
        instruction=str(meta.get("instruction") or ""),
    )

    try:
        async with open_project_snapshot_llm_client(db, novel_id, run_snapshot) as client:
            stop = budget_stop_reason(envelope, **guard)
            if stop:
                raise ExplorationPauseError(stop)
            await _checkpoint(
                db, root, branch, error_message="探索 provider 请求需要先提交检查点"
            )
            output: SceneLineOutputV1 = await _generate_exploration_payload(
                client=client, action=action, user_data=user_data
            )
        if str(output.target_ref) != target_ref:
            raise ValueError("对白目标与请求目标不一致")
        if not target_ref.startswith("c_"):
            # canonical 目标：生成后 hidden guard 消费方校验，违规即失败不落库。
            await _validate_canonical_scene_line(db, confirmed, output)
        payload = (
            _merge_revision(parent_payload, output, SCENE_LINE_OUTPUT_KIND, item_path)
            if mode == "revise"
            else output
        )
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
