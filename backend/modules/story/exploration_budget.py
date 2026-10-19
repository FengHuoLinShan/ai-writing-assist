"""Author-visible request/token ranges for governed exploration.

每个生成单元经过知识导演、生成和独立审查，正常 3 次、最多 5 次物理请求
（含一次返修与复审）。多目标为 N 个单元，完整排演为 (N+1)×轮数 个单元；
跟进按实际条目追加授权。Token 是披露估算，实际累计用量由根账本硬限制。
"""

from __future__ import annotations

import json

from infrastructure.llm.collaboration import content_hash
from modules.evidence.contracts import Assumption, ExplorationStart, ProvisionalStart
from modules.story.exploration_schemas import (
    ExplorationBudgetPreview,
    ExplorationTokenEstimate,
    FullRehearsalRequest,
)

# 每尺度一个有界生成步骤的输出字符估算区间：
# B1 影响链与条件、B2 缺口/补桥路径、B3 一句对白。
_OUTPUT_LOW_CHARS_BY_SCALE = {"sandbox": 900, "event": 900, "scene_line": 300}
_OUTPUT_HIGH_CHARS_BY_SCALE = {"sandbox": 2600, "event": 2600, "scene_line": 900}

# 原生 Codex 包封与知识治理 Prompt 也占输入，沿用原生适配器的 32k 保守预留。
_PER_REQUEST_PROMPT_RESERVE_TOKENS = 32000
EXPLORATION_BUDGET_POLICY_VERSION = 2


def _start_input_chars(start: ExplorationStart) -> int:
    if isinstance(start, ProvisionalStart):
        # 临时起点输入包 = 问题 + 假设 + 候选与知识声明 + 作者私享 + 已读网页快照。
        packed = {
            "question": start.question,
            "assumptions": [item.model_dump(mode="json") for item in start.assumptions],
            "candidates": [item.model_dump(mode="json") for item in start.candidates],
            "canonical_refs": list(start.canonical_refs),
            "knowledge": [item.model_dump(mode="json") for item in start.knowledge],
            "scene_stimuli": [
                item.model_dump(mode="json") for item in start.scene_stimuli
            ],
            "author_private": list(start.author_private),
            "time_basis": start.time_basis,
            "web_refs": [item.model_dump(mode="json") for item in start.web_refs],
        }
    else:
        packed = start.model_dump(mode="json")
    return len(json.dumps(packed, ensure_ascii=False))


def _full_rehearsal_request_count(rehearsal: FullRehearsalRequest) -> int:
    """完整排演（M3-B）的请求计量：每轮 = 每目标一张表演卡 + 一次素材/状态统筹。

    与旧导演完整排演的 2N+2 预估（每参与者意图+表演卡两次、裁决一次、素材/
    角度推荐一次，见 ``director_budget.preview_director_budget``）不同：探索
    链每步是一次有界结构化生成，表演卡已含台词/动机/依据，裁决与素材推荐
    合并为每轮一次统筹步骤，因此按 (N+1)×轮次 计量，不沿用 2N+2。
    """

    return (len(rehearsal.targets) + 1) * rehearsal.rounds


def exploration_preview_identity(
    *,
    novel_id: str,
    scale: str,
    start: ExplorationStart,
    focus: str = "",
    counterfactual_of_result_id: str | None = None,
    changed_assumptions: list[Assumption] | None = None,
    event_mode_hint: str | None = None,
    multi_targets: list[str] | None = None,
    diagnostic_question: str | None = None,
    full_rehearsal: FullRehearsalRequest | None = None,
    budget_policy_version: int = EXPLORATION_BUDGET_POLICY_VERSION,
) -> dict:
    """预算预览身份：起点、尺度与焦点任一变化都会改变 preview_hash。

    反事实对照（M2）额外把基线结果 id 与 changed_assumptions 纳入身份，
    保证“同一起点改不同条件”得到不同的预算指纹，worker 可重算复核。
    事件模式提示（M2）同样纳入身份：信息差与导向路径是不同的任务变体。
    场景多目标（M2）与空间诊断问题（M2）也纳入身份：目标列表决定请求次数，
    诊断问题是不同的任务内容。
    完整排演（M3-B）把 targets/rounds/author_goal 内容纳入身份：目标集合、
    轮次或作者目标变化都是不同的任务内容，budget hash 随之改变。
    """

    identity: dict = {
        "novel_id": str(novel_id),
        "scale": scale,
        "focus": focus,
        "input_chars": _start_input_chars(start),
        "start": start.model_dump(mode="json"),
    }
    if budget_policy_version not in (1, EXPLORATION_BUDGET_POLICY_VERSION):
        raise ValueError("未知的探索预算策略版本")
    if budget_policy_version != 1:
        identity["budget_policy_version"] = budget_policy_version
    if event_mode_hint is not None:
        identity["event_mode_hint"] = str(event_mode_hint)
    if multi_targets:
        identity["multi_targets"] = [str(item) for item in multi_targets]
    if diagnostic_question is not None:
        identity["diagnostic_question"] = diagnostic_question
    if full_rehearsal is not None:
        identity["full_rehearsal"] = {
            "targets": [str(item) for item in full_rehearsal.targets],
            "rounds": int(full_rehearsal.rounds),
            "author_goal": full_rehearsal.author_goal or "",
        }
    if counterfactual_of_result_id is not None:
        identity["counterfactual_of_result_id"] = str(counterfactual_of_result_id)
        identity["changed_assumptions"] = [
            item.model_dump(mode="json") for item in (changed_assumptions or [])
        ]
    return identity


def preview_exploration_budget(
    *,
    novel_id: str,
    scale: str,
    start: ExplorationStart,
    focus: str = "",
    counterfactual_of_result_id: str | None = None,
    changed_assumptions: list[Assumption] | None = None,
    event_mode_hint: str | None = None,
    multi_targets: list[str] | None = None,
    diagnostic_question: str | None = None,
    full_rehearsal: FullRehearsalRequest | None = None,
) -> ExplorationBudgetPreview:
    if scale not in _OUTPUT_LOW_CHARS_BY_SCALE:
        raise ValueError(f"不支持的探索尺度：{scale}")
    # 先计生成单元，再乘导演、生成、审查及最多一次返修复审。
    if full_rehearsal is not None:
        request_count = _full_rehearsal_request_count(full_rehearsal)
    else:
        request_count = len(multi_targets) if multi_targets else 1
    chars = _start_input_chars(start) + len(focus)
    input_low = max(1, int(chars / 4.0))
    input_high = max(input_low, int(chars / 2.5))
    output_low = _OUTPUT_LOW_CHARS_BY_SCALE[scale] // 3 * request_count
    output_high = _OUTPUT_HIGH_CHARS_BY_SCALE[scale] // 3 * request_count
    tokens_min = (input_low + output_low) * 3
    tokens_max = (
        (input_high + _PER_REQUEST_PROMPT_RESERVE_TOKENS) * request_count + output_high
    ) * 5
    if full_rehearsal:
        tokens_max += output_high * max(0, full_rehearsal.rounds - 1)
    return ExplorationBudgetPreview(
        requests_min=request_count * 3,
        requests_max=request_count * 5,
        follow_up_max_requests=5,
        tokens_min=tokens_min,
        tokens_max=tokens_max,
        token_estimate=ExplorationTokenEstimate(
            minimum=tokens_min,
            maximum=tokens_max,
            method=(
                "按输入包字符长度及每请求 32k 包封/治理预留估算，实际用量以运行账本为准"
            ),
        ),
        preview_hash=content_hash(
            exploration_preview_identity(
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
        ),
    )
