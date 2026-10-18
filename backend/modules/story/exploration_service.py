"""Story-owned persistence for director multi-scale exploration (P1 骨架).

职责（P0 §11 Wave P1-S）：探索根/分支创建（起点判别强制）、探索历史读取、
作者编辑保存（零模型调用）、同起点比较门与结果行探索载荷读写。
任务执行（worker）、operations 目录与 API 路由由后续批次接入。

存储承载（P0 §3.1）：沙盘/事件 → ``story_world_progression_*``；场景对白 →
``story_scene_director_*``。结果行 payload 经 ``ExplorationOutputEnvelope``
包装（含 ``output_kind``）；旧载荷不含该键，读取方据此 fail-closed 区分。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select

from core.errors import ConflictError, DomainError, NotFoundError
from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.schemas import read_ai_run_envelope
from modules.evidence.contracts import (
    Assumption,
    CandidateRef,
    ExplorationStart,
    HandoffRef,
    ProvisionalStart,
    SceneAnchorStart,
)
from modules.project import facade as project_facade
from modules.story.director_service import (
    get_director_branch,
    get_director_root,
)
from modules.story.exploration_schemas import (
    AFFECTED_ITEM_EXCERPT_MAX_LENGTH,
    AFFECTED_ITEMS_MAX,
    AUTHOR_EDIT_OUTPUT_KIND,
    EVENT_MODE_HINTS,
    EVENT_OUTPUT_KIND,
    EXPLORATION_OUTPUT_SCHEMA_VERSION,
    FULL_REHEARSAL_OUTPUT_KIND,
    LOCK_SET_OUTPUT_KIND,
    PAYLOAD_MODELS_BY_BASE_KIND,
    SANDBOX_OUTPUT_KIND,
    SCENE_LINE_OUTPUT_KIND,
    AffectedItem,
    AuthorEditPayloadV1,
    ExplorationOutputEnvelope,
    FullRehearsalRequest,
    LockedItem,
    LockSetPayloadV1,
    apply_changed_assumptions,
    exploration_start_fingerprint,
)
from modules.story.exploration_schemas import (
    EXPLORATION_CAPABILITY as EXPLORATION_CAPABILITY,
)
from modules.story.exploration_schemas import (
    check_revision_target as check_revision_target,
)
from modules.story.exploration_schemas import (
    exploration_entry_display_text as exploration_entry_display_text,
)
from modules.story.models import (
    StorySceneDirectorBranch,
    StorySceneDirectorRoot,
    StorySceneDirectorRound,
)
from modules.story.world_progression_models import (
    StoryWorldProgressionBranch,
    StoryWorldProgressionRoot,
    StoryWorldProgressionStep,
)
from modules.story.world_progression_service import (
    get_progression_branch,
    get_progression_root,
)

EXPLORATION_CHAIN_BY_SCALE: dict[str, str] = {
    "sandbox": "progression",
    "event": "progression",
    "scene_line": "scene",
}

SCENE_SOURCE_KIND = "scene"
PROVISIONAL_SOURCE_KIND = "provisional"

# 历史合并分页前每条链的读取上限；单作品根数量远小于该值，防止无界查询。
_HISTORY_SCAN_CAP = 500

_SAVE_EDIT_MODE = "save_edit"


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


async def _require_project(
    db, novel_id: str, owner_id: str, *, for_update: bool = False
) -> None:
    """owner+novel 归属校验：项目缺失或不属于该作者一律 404，不泄露存在性。"""
    context = await project_facade.get_any_project_context(
        db,
        novel_id,
        **({"for_update": True} if for_update else {}),
    )
    if context is None or context.owner_id is None:
        raise NotFoundError("项目不存在")
    if str(context.owner_id) != str(_uuid(owner_id)):
        raise NotFoundError("项目不存在")


# ---------------------------------------------------------------------------
# 结果行 payload 读写助手
# ---------------------------------------------------------------------------


def pack_exploration_output(envelope: ExplorationOutputEnvelope) -> dict:
    """把探索输出信封序列化为结果行 JSON 载荷。"""

    return envelope.model_dump(mode="json")


def unpack_exploration_output(row: Any) -> ExplorationOutputEnvelope | None:
    """从结果行读回探索输出信封；无 ``output_kind`` 的旧载荷返回 None。"""

    data = getattr(row, "output_json", None)
    if not isinstance(data, dict) or "output_kind" not in data:
        data = getattr(row, "result_json", None)
    if not isinstance(data, dict) or "output_kind" not in data:
        return None
    return ExplorationOutputEnvelope.model_validate(data)


def _base_payload_kind(envelope: ExplorationOutputEnvelope) -> str:
    """作者编辑可叠加在既有编辑版本上：回溯到最近一个 AI 输出尺度。"""

    payload = envelope.payload
    if envelope.output_kind == AUTHOR_EDIT_OUTPUT_KIND:
        return payload.base_output_kind
    return envelope.output_kind


# ---------------------------------------------------------------------------
# 根/分支创建（P0 §3.3：显式校验，不靠 ORM 默认值侥幸）
# ---------------------------------------------------------------------------


async def create_exploration_root(
    db,
    *,
    novel_id: str,
    owner_id: str,
    scale: str,
    start: ExplorationStart,
    scene_id: str | None = None,
    context_confirmation_id: str | None = None,
    run_envelope_json: dict | None = None,
    source_snapshot_json: dict | None = None,
    llm_execution_snapshot_json: dict | None = None,
    status: str = "queued",
    branch_request_json: dict | None = None,
    counterfactual_of: str | None = None,
    changed_assumptions: list[Assumption] | None = None,
    event_mode_hint: str | None = None,
    full_rehearsal: FullRehearsalRequest | None = None,
) -> tuple[Any, Any]:
    """为一次探索创建根与初始分支；返回 ``(root, branch)``。

    沙盘/事件写推进链，场景对白写导演链。``provisional`` 起点强制无场景，
    ``scene_anchor`` 起点强制携带场景；推进链一律要求非空确认（临时起点为
    空资料集确认）。反事实对照（M2）时把基线结果 id 与 changed_assumptions
    一并冻结进根 request_json，worker 读取同一承载记录到结果 input_json。
    事件模式提示（M2）同样冻结进根 request_json：worker 据此注入信息差/
    导向 prompt 变体，仅事件尺度接受。
    完整排演意图（M3-B）也冻结进根 request_json（仅临时起点 + 场景一句对白
    尺度），worker 下一执行切片据此展开逐轮表演卡/素材/观察统筹。
    """
    chain = EXPLORATION_CHAIN_BY_SCALE.get(scale)
    if chain is None:
        raise DomainError(f"不支持的探索尺度：{scale}")
    if event_mode_hint is not None:
        if scale != "event":
            raise DomainError("event_mode_hint 仅支持事件尺度")
        if event_mode_hint not in EVENT_MODE_HINTS:
            raise DomainError("未知的事件模式提示")
    if full_rehearsal is not None:
        if scale != "scene_line":
            raise DomainError("full_rehearsal 仅支持场景一句对白尺度")
        if not isinstance(start, ProvisionalStart):
            raise DomainError("full_rehearsal 仅支持临时假设起点")
    await _require_project(db, novel_id, owner_id, for_update=True)

    if isinstance(start, ProvisionalStart):
        source_kind = PROVISIONAL_SOURCE_KIND
        if scene_id is not None:
            raise DomainError("临时起点探索不允许绑定场景")
        resolved_scene_id = None
    elif isinstance(start, SceneAnchorStart):
        source_kind = SCENE_SOURCE_KIND
        if scene_id is not None and str(scene_id) != str(start.scene_id):
            raise ConflictError("请求场景与起点锚点场景不一致")
        resolved_scene_id = _uuid(start.scene_id)
    else:  # pragma: no cover - 判别联合已穷尽，防御保留
        raise DomainError("不支持的探索起点类型")

    fingerprint = exploration_start_fingerprint(start, scale)
    request_json = {
        "exploration_scale": scale,
        "exploration_source_kind": source_kind,
        "exploration_start_fingerprint": fingerprint,
        "exploration_start": start.model_dump(mode="json"),
    }
    if counterfactual_of is not None:
        request_json["counterfactual_of"] = str(counterfactual_of)
        request_json["changed_assumptions"] = [
            item.model_dump(mode="json") for item in (changed_assumptions or [])
        ]
    if event_mode_hint is not None:
        request_json["event_mode_hint"] = str(event_mode_hint)
    if full_rehearsal is not None:
        request_json["full_rehearsal"] = full_rehearsal.model_dump(mode="json")
    root_id, branch_id = uuid.uuid4(), uuid.uuid4()
    branch_request = {
        "mode": "start",
        "exploration_scale": scale,
        **(branch_request_json or {}),
    }
    if chain == "progression":
        if not context_confirmation_id:
            raise DomainError("探索推进链必须携带上下文确认（空资料集为空资料确认）")
        root = StoryWorldProgressionRoot(
            id=root_id,
            novel_id=_uuid(novel_id),
            source_kind=source_kind,
            scene_id=resolved_scene_id,
            source_hash=fingerprint,
            request_json=request_json,
            source_snapshot_json=source_snapshot_json or {},
            llm_execution_snapshot_json=llm_execution_snapshot_json or {},
            run_envelope_json=run_envelope_json or {},
            context_confirmation_id=str(context_confirmation_id),
            status=status,
        )
        branch = StoryWorldProgressionBranch(
            id=branch_id,
            novel_id=root.novel_id,
            root_id=root_id,
            branch_kind="start",
            source_hash=fingerprint,
            request_json=branch_request,
            source_snapshot_json=source_snapshot_json or {},
            pending_step_json={},
            status=status,
        )
    else:
        root = StorySceneDirectorRoot(
            id=root_id,
            novel_id=_uuid(novel_id),
            source_kind=source_kind,
            scene_id=resolved_scene_id,
            source_hash=fingerprint,
            request_json=request_json,
            llm_execution_snapshot_json=llm_execution_snapshot_json or {},
            run_envelope_json=run_envelope_json or {},
            status=status,
        )
        branch = StorySceneDirectorBranch(
            id=branch_id,
            novel_id=root.novel_id,
            root_id=root_id,
            branch_kind="start",
            source_hash=fingerprint,
            request_json=branch_request,
            pending_round_json={},
            status=status,
        )
    db.add_all([root, branch])
    await db.flush()
    return root, branch


# ---------------------------------------------------------------------------
# 旧路径 fail-closed（P0 §7）：带 output_kind 的行与临时起点根不得进入旧解释逻辑
# ---------------------------------------------------------------------------

_LEGACY_EXPLORATION_ROW_MESSAGE = "该分支包含紧凑探索结果，请在对应任务上继续"
_PROVISIONAL_ROOT_MESSAGE = "临时起点探索根不能进入旧推进路径，请在对应任务上继续"


def require_legacy_director_round(row) -> None:
    """导演 continue/advance/resume：来源回合带探索输出即拒绝。"""
    if unpack_exploration_output(row) is not None:
        raise ConflictError(_LEGACY_EXPLORATION_ROW_MESSAGE)


def require_legacy_progression_root(root, step=None) -> None:
    """推进 advance/resume/hooks/continuous：临时起点根或探索步骤即拒绝。"""
    if getattr(root, "source_kind", SCENE_SOURCE_KIND) == PROVISIONAL_SOURCE_KIND:
        raise ConflictError(_PROVISIONAL_ROOT_MESSAGE)
    if step is not None and unpack_exploration_output(step) is not None:
        raise ConflictError(_LEGACY_EXPLORATION_ROW_MESSAGE)


def require_legacy_reference_source(root, row) -> None:
    """save_director_reference：临时起点根或探索输出回合不能存为参考剧本。"""
    if getattr(root, "source_kind", SCENE_SOURCE_KIND) == PROVISIONAL_SOURCE_KIND:
        raise ConflictError(
            "临时起点探索没有场景依据，不能存为正式参考剧本"
        )
    if unpack_exploration_output(row) is not None:
        raise ConflictError(
            "探索结果不能存为参考剧本；请在对应任务上继续或先保存编辑版本"
        )


def require_legacy_transfer_source(row) -> None:
    """transfer_world_candidate：探索输出回合不能转入 World 候选。"""
    if unpack_exploration_output(row) is not None:
        raise ConflictError(
            "探索结果不能转入 World 待审核候选；请在对应任务上继续"
        )


# ---------------------------------------------------------------------------
# 结果行定位与比较
# ---------------------------------------------------------------------------


async def locate_exploration_result(
    db, novel_id: str, result_id: str, *, lock: bool = False
) -> tuple[Any, str]:
    """定位探索结果行的稳定入口：按 ID 在两条链上查找并返回 ``(row, chain)``。"""
    return await _locate_result_row(db, novel_id, result_id, lock=lock)


async def root_for_chain(db, novel_id: str, root_id: Any, chain: str):
    """按链路读取探索根的稳定入口。"""
    return await _root_for_chain(db, novel_id, root_id, chain)


async def require_project_owner(db, novel_id: str, owner_id: str) -> None:
    """owner+novel 归属校验的稳定入口（不锁定）。"""
    await _require_project(db, novel_id, owner_id)


async def _locate_result_row(
    db, novel_id: str, result_id: str, *, lock: bool = False
) -> tuple[Any, str]:
    """按 ID 在两条链上定位探索结果行；跨链同 ID 冲突失败关闭。"""

    rid = _uuid(result_id)
    round_query = select(StorySceneDirectorRound).where(
        StorySceneDirectorRound.novel_id == _uuid(novel_id),
        StorySceneDirectorRound.id == rid,
    )
    step_query = select(StoryWorldProgressionStep).where(
        StoryWorldProgressionStep.novel_id == _uuid(novel_id),
        StoryWorldProgressionStep.id == rid,
    )
    if lock:
        round_query = round_query.with_for_update()
        step_query = step_query.with_for_update()
    round_row = await db.scalar(round_query)
    step_row = await db.scalar(step_query)
    if round_row is not None and step_row is not None:
        raise ConflictError("结果标识冲突，无法定位唯一探索结果")
    if round_row is not None:
        return round_row, "scene"
    if step_row is not None:
        return step_row, "progression"
    raise NotFoundError("探索结果不存在")


async def _locate_exploration_result(
    db, *, novel_id: str, result_id: str, lock: bool = False
):
    """定位探索结果行并校验其属于本作品的独立探索运行（api/operations 共用）。"""
    row, chain = await locate_exploration_result(
        db, novel_id=novel_id, result_id=result_id, lock=lock
    )
    envelope = unpack_exploration_output(row)
    if envelope is None:
        raise ConflictError("所选结果不是探索结果")
    root = await _root_for_chain(db, novel_id, row.root_id, chain)
    request_json = getattr(root, "request_json", None) or {}
    raw = read_ai_run_envelope(getattr(root, "run_envelope_json", None))
    capability = raw.root_capability_id if raw is not None else None
    if (
        not request_json.get("exploration_start_fingerprint")
        or capability != EXPLORATION_CAPABILITY
    ):
        raise ConflictError("所选结果不属于独立探索运行")
    return row, chain, root


async def _root_for_chain(db, novel_id: str, root_id: Any, chain: str):
    if chain == "scene":
        return await get_director_root(db, novel_id, str(root_id))
    return await get_progression_root(db, novel_id, str(root_id))


async def _result_start_fingerprint(
    db, novel_id: str, row: Any, chain: str
) -> str | None:
    root = await _root_for_chain(db, novel_id, row.root_id, chain)
    fingerprint = (root.request_json or {}).get("exploration_start_fingerprint")
    if not fingerprint:
        return None
    return str(fingerprint)


async def _baseline_root_start_dump(db, novel_id: str, row: Any, chain: str) -> dict:
    """基线结果根上冻结的完整起点（既有承载：根 request_json，不新造存储）。"""
    root = await _root_for_chain(db, novel_id, row.root_id, chain)
    return dict((root.request_json or {}).get("exploration_start") or {})


async def resolve_counterfactual_start(
    db,
    *,
    novel_id: str,
    result_id: str,
    scale: str,
    changed_assumptions: list[Assumption],
) -> tuple[ProvisionalStart, str]:
    """反事实基线解析：定位基线结果行，校验沙盘同源后克隆并只改指定条件。

    基线不存在/异作品 → NotFoundError；非沙盘 AI 结果或起点与指纹不符 →
    ConflictError（失败关闭）。返回 ``(克隆起点, 基线结果 id)``。
    """

    row, chain = await _locate_result_row(db, novel_id, result_id)
    envelope = unpack_exploration_output(row)
    if envelope is None or envelope.output_kind != SANDBOX_OUTPUT_KIND:
        raise ConflictError("反事实条件对照的基线必须是沙盘探索结果")
    root = await _root_for_chain(db, novel_id, row.root_id, chain)
    root_request = dict(root.request_json or {})
    baseline_scale = str(root_request.get("exploration_scale") or "")
    if baseline_scale != "sandbox" or scale != "sandbox":
        raise ConflictError("反事实条件对照只支持沙盘尺度")
    start_dump = await _baseline_root_start_dump(db, novel_id, row, chain)
    if not start_dump or start_dump.get("kind") != "provisional":
        raise ConflictError("反事实条件对照的基线必须是临时假设起点")
    start = ProvisionalStart.model_validate(start_dump)
    stored_fingerprint = root_request.get("exploration_start_fingerprint")
    if (
        not stored_fingerprint
        or str(stored_fingerprint) != exploration_start_fingerprint(start, "sandbox")
    ):
        raise ConflictError("基线结果的冻结起点与指纹不一致，无法反事实克隆")
    cloned = apply_changed_assumptions(start, list(changed_assumptions))
    return cloned, str(row.id)


def _changed_assumption_texts(row: Any) -> list[str]:
    data = getattr(row, "input_json", None)
    if not isinstance(data, dict):
        return []
    return [str(item) for item in (data.get("changed_assumption_texts") or [])]


def _counterfactual_link_condition(first: Any, second: Any) -> list[str]:
    """反事实链校验：互为衍生或共享基线，否则失败关闭；通过则回传差集。"""

    def _cf(row: Any) -> str | None:
        data = getattr(row, "input_json", None)
        value = data.get("counterfactual_of") if isinstance(data, dict) else None
        return str(value) if value else None

    first_cf, second_cf = _cf(first), _cf(second)
    first_id, second_id = str(first.id), str(second.id)
    derives = first_cf == second_id or second_cf == first_id
    shared_baseline = (
        first_cf is not None and second_cf is not None and first_cf == second_cf
    )
    if not (derives or shared_baseline):
        raise ConflictError("两个结果没有反事实衍生关系，不能做条件对照")
    return _changed_conditions(
        _changed_assumption_texts(first), _changed_assumption_texts(second)
    )


def _changed_conditions(first_texts: list[str], second_texts: list[str]) -> list[str]:
    """两行 changed_assumption_texts 的对称差集，保持首现顺序并去重。"""

    first_unique = list(dict.fromkeys(first_texts))
    second_unique = list(dict.fromkeys(second_texts))
    second_set, first_set = set(second_unique), set(first_unique)
    return [text for text in first_unique if text not in second_set] + [
        text for text in second_unique if text not in first_set
    ]


# ---------------------------------------------------------------------------
# 影响与比较标记（M3-A 切片 2）：结构化受影响项 + 实际读集与父版本披露
# ---------------------------------------------------------------------------

_AFFECTED_GRANULARITY_EXACT = "exact"
_AFFECTED_GRANULARITY_CONSERVATIVE = "conservative"

# 结构化 diff 遍历的列表族：路径语法与修订/锁定一致；line 单独比较。
_AFFECTED_LIST_FAMILIES: tuple[tuple[str, str], ...] = (
    ("chain", "influence_chain"),
    ("gap", "gaps"),
    ("bridge", "bridge_candidates"),
)


def _diff_payload_dict(envelope: ExplorationOutputEnvelope) -> tuple[dict, str]:
    """参与 diff 的载荷字典与基类 kind；作者编辑解析到被编辑的基础载荷。"""

    payload = envelope.payload
    if envelope.output_kind == AUTHOR_EDIT_OUTPUT_KIND:
        payload = payload.edited_payload
    return payload.model_dump(mode="json"), _base_payload_kind(envelope)


def _affected_granularity(
    base_dict: dict, derived_dict: dict, base_kind: str, derived_kind: str
) -> str:
    """粒度判定：两侧不同构、形态未知或路径语法不可表达 → 保守披露。

    事件导向（goal_path）与多目标/空间诊断（variants/spatial_assessment）
    不在冻结路径语法内，逐项对比会漏报，宁可置空也不伪称精确。
    """

    if base_kind != derived_kind or base_kind not in PAYLOAD_MODELS_BY_BASE_KIND:
        return _AFFECTED_GRANULARITY_CONSERVATIVE
    for payload in (base_dict, derived_dict):
        if base_kind == EVENT_OUTPUT_KIND and payload.get("mode") == "goal":
            return _AFFECTED_GRANULARITY_CONSERVATIVE
        if base_kind == SCENE_LINE_OUTPUT_KIND and (
            payload.get("variants") is not None
            or payload.get("spatial_assessment") is not None
        ):
            return _AFFECTED_GRANULARITY_CONSERVATIVE
    return _AFFECTED_GRANULARITY_EXACT


def compute_affected_items(
    base_envelope: ExplorationOutputEnvelope,
    derived_envelope: ExplorationOutputEnvelope,
) -> tuple[list[dict], str]:
    """两行 payload 的同构结构化 diff：受影响项列表与粒度（M3-A）。

    按冻结路径语法（chain:N/gap:N/bridge:N/line）按索引对比：内容哈希不同
    即 changed，索引只在一侧为 added/removed；上限 ``AFFECTED_ITEMS_MAX``
    条，超出一律截断。粒度保守时置空列表并返回 "conservative"。
    """

    base_dict, base_kind = _diff_payload_dict(base_envelope)
    derived_dict, derived_kind = _diff_payload_dict(derived_envelope)
    granularity = _affected_granularity(
        base_dict, derived_dict, base_kind, derived_kind
    )
    if granularity == _AFFECTED_GRANULARITY_CONSERVATIVE:
        return [], granularity
    items: list[AffectedItem] = []
    for family, key in _AFFECTED_LIST_FAMILIES:
        base_items = base_dict.get(key)
        derived_items = derived_dict.get(key)
        base_items = base_items if isinstance(base_items, list) else []
        derived_items = derived_items if isinstance(derived_items, list) else []
        for index in range(max(len(base_items), len(derived_items))):
            base_item = base_items[index] if index < len(base_items) else None
            derived_item = (
                derived_items[index] if index < len(derived_items) else None
            )
            if derived_item is None:
                status = "removed"
            elif base_item is None:
                status = "added"
            elif content_hash(base_item) != content_hash(derived_item):
                status = "changed"
            else:
                continue
            path = f"{family}:{index}"
            items.append(
                AffectedItem(
                    item_path=path,
                    status=status,
                    base_excerpt=exploration_entry_display_text(path, base_item)[
                        :AFFECTED_ITEM_EXCERPT_MAX_LENGTH
                    ],
                    derived_excerpt=exploration_entry_display_text(
                        path, derived_item
                    )[:AFFECTED_ITEM_EXCERPT_MAX_LENGTH],
                )
            )
            if len(items) >= AFFECTED_ITEMS_MAX:
                return [item.model_dump(mode="json") for item in items], granularity
    base_line = str(base_dict.get("line") or "")
    derived_line = str(derived_dict.get("line") or "")
    if (base_line or derived_line) and base_line != derived_line:
        if not base_line:
            status = "added"
        elif not derived_line:
            status = "removed"
        else:
            status = "changed"
        items.append(
            AffectedItem(
                item_path="line",
                status=status,
                base_excerpt=base_line[:AFFECTED_ITEM_EXCERPT_MAX_LENGTH],
                derived_excerpt=derived_line[:AFFECTED_ITEM_EXCERPT_MAX_LENGTH],
            )
        )
    return [item.model_dump(mode="json") for item in items], granularity


def _counterfactual_base_side(first: Any, second: Any) -> int:
    """基线侧索引：一行为另一行反事实衍生时指向基线；共享基线按请求顺序。

    链路已由 ``_counterfactual_link_condition`` 校验；共享基线的两行互不
    衍生，base/derived 只是“请求第一行/第二行”的稳定命名。
    """

    data = getattr(first, "input_json", None)
    value = data.get("counterfactual_of") if isinstance(data, dict) else None
    if value and str(value) == str(second.id):
        return 1
    return 0


def _recorded_parent_output_hash(row: Any) -> str | None:
    """结果行 input_json 记录的父版本哈希：反事实行为基线行输出版本。"""

    data = getattr(row, "input_json", None)
    value = data.get("parent_output_hash") if isinstance(data, dict) else None
    return str(value) if value else None


def _row_parent_id(row: Any, chain: str) -> str | None:
    value = row.parent_step_id if chain == "progression" else row.parent_round_id
    return str(value) if value is not None else None


async def compare_exploration_results(
    db,
    *,
    novel_id: str,
    owner_id: str,
    first_result_id: str,
    second_result_id: str,
    mode: str = "same_start",
) -> dict:
    """两结果比较：same_start 指纹不同或缺失即失败关闭（409），同根父子一跳
    标记 relation=parent_child 并给出相对差异；counterfactual 要求反事实衍生
    或共享基线，成功回传 changed_conditions 与 affected_items（粒度不足时
    保守披露）。反事实侧同时回传行内记录的 parent_output_hash。"""

    if mode not in {"same_start", "counterfactual"}:
        raise DomainError(f"不支持的比较模式：{mode}")
    await _require_project(db, novel_id, owner_id)
    located: list[tuple[Any, str]] = []
    for result_id in (first_result_id, second_result_id):
        row, chain = await _locate_result_row(db, novel_id, result_id)
        located.append((row, chain))
    envelopes = [unpack_exploration_output(row) for row, _chain in located]
    if any(envelope is None for envelope in envelopes):
        raise ConflictError("所选结果不是探索结果，无法比较")
    if any(envelope.output_kind == LOCK_SET_OUTPUT_KIND for envelope in envelopes):
        raise ConflictError("锁定记录不参与比较，请选择探索结果")
    changed_conditions: list[str] | None = None
    relation: str | None = None
    affected_items: list[dict] = []
    affected_granularity: str | None = None
    if mode == "counterfactual":
        changed_conditions = _counterfactual_link_condition(located[0][0], located[1][0])
        start_fingerprint = None
        base_index = _counterfactual_base_side(located[0][0], located[1][0])
        affected_items, affected_granularity = compute_affected_items(
            envelopes[base_index], envelopes[1 - base_index]
        )
    else:
        fingerprints = [
            await _result_start_fingerprint(db, novel_id, row, chain)
            for row, chain in located
        ]
        if (
            not fingerprints[0]
            or not fingerprints[1]
            or fingerprints[0] != fingerprints[1]
        ):
            raise ConflictError("两个结果的起点不同，不能直接比较")
        start_fingerprint = fingerprints[0]
        relation = "same_start"
        ancestor_index: int | None = None
        if located[0][0].root_id == located[1][0].root_id:
            if _row_parent_id(located[0][0], located[0][1]) == str(located[1][0].id):
                ancestor_index = 1
            elif _row_parent_id(located[1][0], located[1][1]) == str(located[0][0].id):
                ancestor_index = 0
        if ancestor_index is not None:
            relation = "parent_child"
            affected_items, affected_granularity = compute_affected_items(
                envelopes[ancestor_index], envelopes[1 - ancestor_index]
            )
    sides = []
    for (row, chain), envelope in zip(located, envelopes):
        sides.append(
            {
                "result_id": str(row.id),
                "chain": chain,
                "root_id": str(row.root_id),
                "branch_id": str(row.branch_id),
                "created_at": (
                    row.created_at.isoformat() if row.created_at else None
                ),
                "envelope": envelope,
                "parent_output_hash": _recorded_parent_output_hash(row),
                "locked_items": [
                    item.item_path
                    for item in await current_locked_items(
                        db, novel_id=novel_id, branch_id=row.branch_id, chain=chain
                    )
                ],
            }
        )
    result: dict = {
        "start_fingerprint": start_fingerprint,
        "left": sides[0],
        "right": sides[1],
    }
    if changed_conditions is not None:
        result["mode"] = "counterfactual"
        result["changed_conditions"] = changed_conditions
        result["affected_items"] = affected_items
        result["affected_items_granularity"] = affected_granularity
    if relation is not None:
        result["relation"] = relation
        if relation == "parent_child":
            result["affected_items"] = affected_items
            result["affected_items_granularity"] = affected_granularity
    return result


# ---------------------------------------------------------------------------
# 作者编辑保存（零模型调用；P0 §3.1/§5）
# ---------------------------------------------------------------------------


async def _require_edit_respects_locks(
    db,
    *,
    novel_id: str,
    base_row: Any,
    chain: str,
    base_envelope: ExplorationOutputEnvelope,
    edited_payload: Any,
) -> None:
    """作者编辑也不能动锁定内容（M3-A）：与所在结果不一致即 409，防误操作。

    锁定项在分支上逐字保持，因此“与编辑基行一致”等价于“与锁定内容一致”；
    解锁后可改。
    """

    locked_items = await current_locked_items(
        db, novel_id=novel_id, branch_id=base_row.branch_id, chain=chain
    )
    if not locked_items:
        return
    base_payload = base_envelope.payload
    if base_envelope.output_kind == AUTHOR_EDIT_OUTPUT_KIND:
        base_payload = base_payload.edited_payload
    base_dict = base_payload.model_dump(mode="json")
    edited_dict = edited_payload.model_dump(mode="json")
    base_kind = _base_payload_kind(base_envelope)
    for item in locked_items:
        try:
            base_target = check_revision_target(
                base_dict, item.item_path, None, base_kind
            )
            edited_target = check_revision_target(
                edited_dict, item.item_path, None, base_kind
            )
        except ValueError as error:
            raise ConflictError(
                f"锁定条目 {item.item_path} 与结果结构不一致：{error}"
            ) from error
        if edited_target["item"] != base_target["item"]:
            raise ConflictError(f"条目 {item.item_path} 已锁定，请先解锁再修改")


async def save_exploration_author_edit(
    db,
    *,
    novel_id: str,
    owner_id: str,
    base_result_id: str,
    edited_payload: Any,
    edit_note: str | None = None,
) -> tuple[Any, ExplorationOutputEnvelope]:
    """把作者编辑保存为新结果行；不可变行不修改，重复保存幂等返回同一行。"""

    await _require_project(db, novel_id, owner_id, for_update=True)
    base_row, chain = await _locate_result_row(db, novel_id, base_result_id, lock=True)
    base_envelope = unpack_exploration_output(base_row)
    if base_envelope is None:
        raise ConflictError("所选结果不是探索结果，无法保存编辑")
    if base_envelope.output_kind == LOCK_SET_OUTPUT_KIND:
        raise ConflictError("锁定记录不能被编辑；请回到探索结果")
    await _require_edit_respects_locks(
        db,
        novel_id=novel_id,
        base_row=base_row,
        chain=chain,
        base_envelope=base_envelope,
        edited_payload=edited_payload,
    )

    base_kind = _base_payload_kind(base_envelope)
    expected_model = PAYLOAD_MODELS_BY_BASE_KIND.get(base_kind)
    if expected_model is None or not isinstance(edited_payload, expected_model):
        raise ConflictError("edited_payload 与基础结果结构不一致，无法保存编辑")
    new_envelope = ExplorationOutputEnvelope(
        output_kind=AUTHOR_EDIT_OUTPUT_KIND,
        payload=AuthorEditPayloadV1(
            base_output_kind=base_kind,  # type: ignore[arg-type]
            base_result_id=str(base_row.id),
            edited_payload=edited_payload,
            edit_note=edit_note,
        ),
    )
    edit_content_hash = content_hash(
        {
            "base_result_id": str(base_row.id),
            "edited_payload": edited_payload.model_dump(mode="json"),
            "edit_note": edit_note,
        }
    )
    input_json = {
        "mode": _SAVE_EDIT_MODE,
        "save_edit": {
            "base_result_id": str(base_row.id),
            "edit_content_hash": edit_content_hash,
        },
    }

    if chain == "scene":
        branch = await get_director_branch(
            db, novel_id, str(base_row.branch_id), lock=True
        )
        next_number = (
            await db.scalar(
                select(func.max(StorySceneDirectorRound.round_number)).where(
                    StorySceneDirectorRound.novel_id == _uuid(novel_id),
                    StorySceneDirectorRound.branch_id == branch.id,
                )
            )
            or 0
        ) + 1
        existing = await db.scalar(
            select(StorySceneDirectorRound).where(
                StorySceneDirectorRound.novel_id == _uuid(novel_id),
                StorySceneDirectorRound.branch_id == branch.id,
                StorySceneDirectorRound.parent_round_id == base_row.id,
                StorySceneDirectorRound.input_hash == edit_content_hash,
            )
        )
        if existing is not None:
            return existing, unpack_exploration_output(existing)  # type: ignore[return-value]
        row = StorySceneDirectorRound(
            id=uuid.uuid4(),
            novel_id=base_row.novel_id,
            root_id=base_row.root_id,
            branch_id=base_row.branch_id,
            round_number=next_number,
            parent_round_id=base_row.id,
            source_hash=branch.source_hash,
            input_hash=edit_content_hash,
            output_hash=content_hash(pack_exploration_output(new_envelope)),
            input_json=input_json,
            output_json=pack_exploration_output(new_envelope),
            state_json={},
            run_envelope_json={},
        )
    else:
        branch = await get_progression_branch(
            db, novel_id, str(base_row.branch_id), lock=True
        )
        next_number = (
            await db.scalar(
                select(func.max(StoryWorldProgressionStep.step_number)).where(
                    StoryWorldProgressionStep.novel_id == _uuid(novel_id),
                    StoryWorldProgressionStep.branch_id == branch.id,
                )
            )
            or 0
        ) + 1
        existing = await db.scalar(
            select(StoryWorldProgressionStep).where(
                StoryWorldProgressionStep.novel_id == _uuid(novel_id),
                StoryWorldProgressionStep.branch_id == branch.id,
                StoryWorldProgressionStep.parent_step_id == base_row.id,
                StoryWorldProgressionStep.input_hash == edit_content_hash,
            )
        )
        if existing is not None:
            return existing, unpack_exploration_output(existing)  # type: ignore[return-value]
        row = StoryWorldProgressionStep(
            id=uuid.uuid4(),
            novel_id=base_row.novel_id,
            root_id=base_row.root_id,
            branch_id=base_row.branch_id,
            parent_step_id=base_row.id,
            step_number=next_number,
            source_hash=branch.source_hash,
            input_hash=edit_content_hash,
            output_hash=content_hash(pack_exploration_output(new_envelope)),
            input_json=input_json,
            result_json=pack_exploration_output(new_envelope),
            state_json={},
            metrics_json={},
            basis_changed=False,
        )
    db.add(row)
    await db.flush()
    return row, new_envelope


# ---------------------------------------------------------------------------
# 满意内容锁定（M3-A）：lock_set 结果行 + 分支当前锁定集（零模型调用）
# ---------------------------------------------------------------------------

_LOCK_SET_MODE = "lock_set"


def _lock_set_payload_of(row: Any) -> LockSetPayloadV1 | None:
    envelope = unpack_exploration_output(row)
    if envelope is not None and envelope.output_kind == LOCK_SET_OUTPUT_KIND:
        return envelope.payload
    return None


async def _branch_rows_desc(
    db, novel_id: str, branch_id: Any, chain: str
) -> list[Any]:
    """分支结果行按序号倒序（有界扫描）；锁定集读取与幂等查找共用。"""

    nid = _uuid(novel_id)
    bid = _uuid(branch_id)
    if chain == "progression":
        query = (
            select(StoryWorldProgressionStep)
            .where(
                StoryWorldProgressionStep.novel_id == nid,
                StoryWorldProgressionStep.branch_id == bid,
            )
            .order_by(StoryWorldProgressionStep.step_number.desc())
        )
    else:
        query = (
            select(StorySceneDirectorRound)
            .where(
                StorySceneDirectorRound.novel_id == nid,
                StorySceneDirectorRound.branch_id == bid,
            )
            .order_by(StorySceneDirectorRound.round_number.desc())
        )
    return list((await db.scalars(query.limit(_HISTORY_SCAN_CAP * 4))).all())


async def _latest_lock_set_row(
    db, novel_id: str, branch_id: Any, chain: str
) -> Any | None:
    for row in await _branch_rows_desc(db, novel_id, branch_id, chain):
        if _lock_set_payload_of(row) is not None:
            return row
    return None


async def current_locked_items(
    db, *, novel_id: str, branch_id: Any, chain: str
) -> list[LockedItem]:
    """分支当前锁定集：该分支最新一条 lock_set 行的 locked_items；无锁定返回空。

    author_edit 与 lock_set 都不算 AI 结果；本函数只认 lock_set 行。
    """

    latest = await _latest_lock_set_row(db, novel_id, branch_id, chain)
    if latest is None:
        return []
    payload = _lock_set_payload_of(latest)
    return list(payload.locked_items)


async def set_exploration_item_lock(
    db,
    *,
    novel_id: str,
    owner_id: str,
    base_result_id: str,
    lock: bool,
    item_path: str,
    item_text: str | None = None,
    note: str | None = None,
) -> tuple[Any, ExplorationOutputEnvelope]:
    """对指定 AI 结果行追加/解除一条锁定，生成新 lock_set 结果行。

    内容 = 该分支当前全部锁定项 ± 本条；零模型调用、无预算。
    item_content_hash 由服务端按该结果行对应条目内容计算（item_text 防漂移
    复用 check_revision_target 的解析，漂移 409）。幂等键
    ``(novel_id, base_result_id, lock, item_path)``：同键重复提交返回同一行；
    已锁定项重复加锁按分支状态幂等返回当前 lock_set 行；解除未锁定项 409。
    """

    await _require_project(db, novel_id, owner_id, for_update=True)
    base_row, chain = await _locate_result_row(db, novel_id, base_result_id, lock=True)
    base_envelope = unpack_exploration_output(base_row)
    if base_envelope is None:
        raise ConflictError("所选结果不是探索结果，无法设置锁定")
    if base_envelope.output_kind == AUTHOR_EDIT_OUTPUT_KIND:
        raise ConflictError("作者编辑版本不能设置锁定；请回到原始 AI 结果")
    if base_envelope.output_kind == LOCK_SET_OUTPUT_KIND:
        raise ConflictError("锁定记录不能作为锁定目标")
    try:
        target = check_revision_target(
            base_envelope.payload.model_dump(mode="json"),
            item_path,
            item_text,
            _base_payload_kind(base_envelope),
        )
    except ValueError as error:
        raise ConflictError(str(error)) from error

    lock_op_key = content_hash(
        {
            "mode": _LOCK_SET_MODE,
            "novel_id": str(_uuid(novel_id)),
            "base_result_id": str(base_row.id),
            "lock": bool(lock),
            "item_path": str(item_path),
        }
    )
    nid = _uuid(novel_id)
    row_model = (
        StoryWorldProgressionStep if chain == "progression" else StorySceneDirectorRound
    )
    existing = await db.scalar(
        select(row_model).where(
            row_model.novel_id == nid,
            row_model.branch_id == base_row.branch_id,
            row_model.input_hash == lock_op_key,
        )
    )
    if existing is not None and _lock_set_payload_of(existing) is not None:
        return existing, unpack_exploration_output(existing)  # type: ignore[return-value]

    current = await current_locked_items(
        db, novel_id=novel_id, branch_id=base_row.branch_id, chain=chain
    )
    paths = {item.item_path for item in current}
    if lock:
        if item_path in paths:
            # 分支状态幂等：内容不变，不重复追加同一锁定。
            latest = await _latest_lock_set_row(db, novel_id, base_row.branch_id, chain)
            if latest is not None:
                return latest, unpack_exploration_output(latest)  # type: ignore[return-value]
        locked_items = list(current)
        locked_items.append(
            LockedItem(
                item_path=item_path,
                item_content_hash=target["item_content_hash"],
                label=str(target.get("label") or ""),
            )
        )
    else:
        if item_path not in paths:
            raise ConflictError("该条目未锁定，无法解除")
        locked_items = [item for item in current if item.item_path != item_path]
    new_envelope = ExplorationOutputEnvelope(
        output_kind=LOCK_SET_OUTPUT_KIND,
        schema_version=EXPLORATION_OUTPUT_SCHEMA_VERSION,
        payload=LockSetPayloadV1(locked_items=locked_items, note=note),
    )
    input_json = {
        "mode": _LOCK_SET_MODE,
        "lock": bool(lock),
        "item_path": str(item_path),
        "item_content_hash": target["item_content_hash"],
        "base_result_id": str(base_row.id),
    }

    if chain == "scene":
        branch = await get_director_branch(
            db, novel_id, str(base_row.branch_id), lock=True
        )
        next_number = (
            await db.scalar(
                select(func.max(StorySceneDirectorRound.round_number)).where(
                    StorySceneDirectorRound.novel_id == nid,
                    StorySceneDirectorRound.branch_id == base_row.branch_id,
                )
            )
            or 0
        ) + 1
        row = StorySceneDirectorRound(
            id=uuid.uuid4(),
            novel_id=base_row.novel_id,
            root_id=base_row.root_id,
            branch_id=base_row.branch_id,
            round_number=next_number,
            parent_round_id=base_row.id,
            source_hash=branch.source_hash,
            input_hash=lock_op_key,
            output_hash=content_hash(pack_exploration_output(new_envelope)),
            input_json=input_json,
            output_json=pack_exploration_output(new_envelope),
            state_json={},
            run_envelope_json={},
        )
    else:
        branch = await get_progression_branch(
            db, novel_id, str(base_row.branch_id), lock=True
        )
        next_number = (
            await db.scalar(
                select(func.max(StoryWorldProgressionStep.step_number)).where(
                    StoryWorldProgressionStep.novel_id == nid,
                    StoryWorldProgressionStep.branch_id == base_row.branch_id,
                )
            )
            or 0
        ) + 1
        row = StoryWorldProgressionStep(
            id=uuid.uuid4(),
            novel_id=base_row.novel_id,
            root_id=base_row.root_id,
            branch_id=base_row.branch_id,
            parent_step_id=base_row.id,
            step_number=next_number,
            source_hash=branch.source_hash,
            input_hash=lock_op_key,
            output_hash=content_hash(pack_exploration_output(new_envelope)),
            input_json=input_json,
            result_json=pack_exploration_output(new_envelope),
            state_json={},
            metrics_json={},
            basis_changed=False,
        )
    db.add(row)
    await db.flush()
    return row, new_envelope


# ---------------------------------------------------------------------------
# 明确选择后的跨尺度移交（M4-A 切片 1）：派生临时起点（零模型调用）
# ---------------------------------------------------------------------------

# 源摘录在问题与假设文本中的截选上限（问题模板自带说明，合计远小于 4000）。
HANDOFF_SOURCE_EXCERPT_MAX = 400

HANDOFF_SCALES: tuple[str, ...] = ("sandbox", "event", "scene_line")

_SCALE_BY_BASE_OUTPUT_KIND: dict[str, str] = {
    SANDBOX_OUTPUT_KIND: "sandbox",
    EVENT_OUTPUT_KIND: "event",
    SCENE_LINE_OUTPUT_KIND: "scene_line",
}

_SOURCE_SCALE_LABEL = {
    "sandbox": "沙盘",
    "event": "事件",
    "scene_line": "场景",
}

# 目标尺度的移交问题模板：携带源摘录（≤400）与来源语境，作者可改。
_HANDOFF_QUESTION_TEMPLATES = {
    "sandbox": (
        "沙盘追因：在既定前提下，「{excerpt}」背后的成因、成立条件与"
        "更广影响是什么？（本起点由{source}探索移交生成，可修改）"
    ),
    "event": (
        "事件展开：以「{excerpt}」为既定情节，给出把它落到具体事件的最小"
        "行动—条件—后果链与缺口。（本起点由{source}探索移交生成，可修改）"
    ),
    "scene_line": (
        "场景聚焦：在「{excerpt}」的情境下，写人物的一句真实回应。"
        "（本起点由{source}探索移交生成，可修改）"
    ),
}


def _uuid_text(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _handoff_excerpt(text: str) -> str:
    return " ".join(str(text or "").split())[:HANDOFF_SOURCE_EXCERPT_MAX]


def _sandbox_link_excerpt(link: dict) -> str:
    return _handoff_excerpt(
        f"{link.get('effect') or ''}（机制：{link.get('mechanism') or ''}）"
    )


def _sandbox_item_excerpt(payload: dict, item_path: str) -> tuple[str, dict]:
    """沙盘源的锚定条目：chain:N 或整结果时的首要影响（chain:0，可预期）。"""
    chain = list(payload.get("influence_chain") or [])
    index = int(item_path.partition(":")[2]) if item_path else 0
    link = chain[index]
    return _sandbox_link_excerpt(link), link


def _event_item_excerpt(payload: dict, item_path: str) -> tuple[str, dict | None]:
    """事件源的锚定摘录：gap:N / bridge:N；整结果给事件摘录或导向摘要。"""
    mode = str(payload.get("mode") or "")
    if not item_path:
        if mode == "goal":
            goal = payload.get("goal_path") or {}
            steps = " → ".join(
                str(step.get("action") or "") for step in goal.get("steps") or []
            )
            return _handoff_excerpt(
                f"{payload.get('original_excerpt') or ''}"
                f"（导向目标：{goal.get('goal') or ''}；路径：{steps}）"
            ), goal
        return _handoff_excerpt(payload.get("original_excerpt") or ""), None
    kind, _, raw_index = item_path.partition(":")
    index = int(raw_index)
    if kind == "gap":
        gap = (payload.get("gaps") or [])[index]
        why = gap.get("why_needed") or ""
        text = f"{gap.get('description') or ''}（需要解释：{why}）"
        if gap.get("possible_fix_hint"):
            text += f"（候选解释：{gap['possible_fix_hint']}，待验证）"
        return _handoff_excerpt(text), gap
    bridge = (payload.get("bridge_candidates") or [])[index]
    steps = " → ".join(str(step) for step in bridge.get("steps") or [])
    conditions = "；".join(str(item) for item in bridge.get("required_conditions") or [])
    text = f"补桥路径：{steps}"
    if conditions:
        text += f"（前提：{conditions}）"
    return _handoff_excerpt(text), bridge


def _scene_line_excerpt(payload: dict, labels: dict[str, str]) -> str:
    target = str(payload.get("target_ref") or "")
    speaker = labels.get(target, target or "人物")
    text = f"{speaker}说：「{payload.get('line') or ''}」"
    if payload.get("action"):
        text += f"（动作：{payload['action']}）"
    return _handoff_excerpt(text)


def _candidate_labels(source_start: ProvisionalStart | None) -> dict[str, str]:
    if source_start is None:
        return {}
    return {item.ref_id: item.label for item in source_start.candidates}


def _migrate_subjects(
    source_start: ProvisionalStart | None,
    refs: list[str],
) -> tuple[list[CandidateRef], list[str], list]:
    """只迁移被选条目涉及的主体（候选身份与可知包），顺序保持、去重。

    源起点未声明且不是 UUID 的引用保守跳过，不伪造身份；正文/知识逐字复制。
    """
    wanted = list(dict.fromkeys(str(ref) for ref in refs if ref))
    candidates: list[CandidateRef] = []
    canonical: list[str] = []
    for ref in wanted:
        match = (
            next(
                (item for item in source_start.candidates if item.ref_id == ref),
                None,
            )
            if source_start is not None
            else None
        )
        if match is not None:
            candidates.append(match.model_copy(deep=True))
        elif _uuid_text(ref):
            canonical.append(ref)
        # 其余引用（如自由文本）无法安全映射为身份，保守省略。
    knowledge = [
        entry.model_copy(deep=True)
        for entry in (source_start.knowledge if source_start is not None else [])
        if entry.subject_ref in set(wanted)
    ]
    return candidates, canonical, knowledge


def _sandbox_affected_refs(payload: dict, item_path: str) -> list[str]:
    chain = list(payload.get("influence_chain") or [])
    if item_path:
        index = int(item_path.partition(":")[2])
        links = [chain[index]]
    else:
        links = chain
    refs: list[str] = []
    for link in links:
        refs.extend(str(ref) for ref in link.get("affected_refs") or [])
    return refs


async def build_handoff_start(
    db,
    novel_id: str,
    owner_id: str,
    source_result_id: str,
    target_scale: str,
    item_path: str,
    selector: str,
    reason: str,
) -> tuple[ProvisionalStart, str]:
    """把一次明确选择的 AI 探索结果派生为目标尺度的临时起点（M4-A 切片 1）。

    只迁移被选条目涉及的假设与主体（``item_path`` 过滤；空=整结果才全量），
    未选分支不进入派生起点；``derived_from`` 只记直接父（一跳）。
    返回 ``(派生起点, 源起点指纹)``；随后作者走既有 confirmation
    preview/confirm/start，``derived_from`` 随起点冻结进确认 compile_options。
    """

    if target_scale not in HANDOFF_SCALES:
        raise DomainError(f"不支持的移交目标尺度：{target_scale}")
    if selector not in ("author", "assistant"):
        raise DomainError(f"未知的选择者：{selector}")
    if selector == "assistant" and not str(reason or "").strip():
        raise DomainError("助手移交必须记录选择理由", status_code=422)
    await _require_project(db, novel_id, owner_id)
    row, chain = await _locate_result_row(db, novel_id, source_result_id)
    envelope = unpack_exploration_output(row)
    if envelope is None:
        raise ConflictError("所选结果不是探索结果，无法移交")
    if envelope.output_kind in (AUTHOR_EDIT_OUTPUT_KIND, LOCK_SET_OUTPUT_KIND):
        raise ConflictError("只有 AI 探索结果可以移交；作者编辑与锁定记录不能作为移交源")
    if envelope.output_kind == FULL_REHEARSAL_OUTPUT_KIND:
        raise ConflictError("完整排演结果暂不支持跨尺度移交；请回到聚焦结果")
    source_scale = _SCALE_BY_BASE_OUTPUT_KIND.get(envelope.output_kind)
    if source_scale is None:
        raise ConflictError("所选结果不是可移交的探索结果")
    if source_scale == target_scale:
        raise ConflictError(
            "源尺度与目标尺度相同；同层请继续使用“说详细点”/局部修订/同起点重来"
        )

    payload = envelope.payload.model_dump(mode="json")
    if source_scale == "scene_line" and (
        payload.get("variants") is not None
        or payload.get("spatial_assessment") is not None
    ):
        raise ConflictError(
            "多目标对白与空间诊断结果没有单一移交条目，暂不支持跨尺度移交"
        )

    item_path = str(item_path or "").strip()
    if item_path:
        try:
            check_revision_target(payload, item_path, None, envelope.output_kind)
        except ValueError as error:
            raise ConflictError(str(error)) from error

    root = await _root_for_chain(db, novel_id, row.root_id, chain)
    root_request = dict(root.request_json or {})
    source_fingerprint = str(root_request.get("exploration_start_fingerprint") or "")
    start_dump = dict(root_request.get("exploration_start") or {})
    source_start: ProvisionalStart | None = None
    if start_dump.get("kind") == "provisional":
        source_start = ProvisionalStart.model_validate(start_dump)

    labels = _candidate_labels(source_start)
    assumptions, candidates, canonical_refs, knowledge = _handoff_derived_inputs(
        source_scale,
        target_scale,
        payload,
        item_path,
        source_start,
        labels,
    )
    excerpt = _handoff_source_excerpt(source_scale, payload, item_path, labels)
    question = _HANDOFF_QUESTION_TEMPLATES[target_scale].format(
        excerpt=excerpt,
        source=_SOURCE_SCALE_LABEL[source_scale],
    )
    if source_start is not None:
        time_basis = source_start.time_basis
    else:
        time_basis = (
            f"沿用源场景探索的 Scene 锚点时点（scene_id={start_dump.get('scene_id')}）"
        )
    derived = ProvisionalStart(
        kind="provisional",
        question=question,
        assumptions=assumptions,
        candidates=candidates,
        canonical_refs=canonical_refs,
        knowledge=knowledge,
        time_basis=time_basis,
        derived_from=HandoffRef(
            source_result_id=str(row.id),
            source_scale=source_scale,  # type: ignore[arg-type]
            item_path=item_path,
            selector=selector,  # type: ignore[arg-type]
            reason=str(reason or "").strip(),
        ),
    )
    return derived, source_fingerprint


def _handoff_source_excerpt(
    source_scale: str,
    payload: dict,
    item_path: str,
    labels: dict[str, str],
) -> str:
    if source_scale == "sandbox":
        text, _link = _sandbox_item_excerpt(payload, item_path)
        return text
    if source_scale == "event":
        text, _item = _event_item_excerpt(payload, item_path)
        return text
    return _scene_line_excerpt(payload, labels)


def _handoff_derived_inputs(
    source_scale: str,
    target_scale: str,
    payload: dict,
    item_path: str,
    source_start: ProvisionalStart | None,
    labels: dict[str, str],
) -> tuple[list[Assumption], list[CandidateRef], list[str], list]:
    """按六方向语义派生假设与主体（计划 §5 M4-A：条件/身份/时间/知识完整）。"""

    inherited = list(source_start.assumptions) if source_start is not None else []

    if source_scale == "sandbox":
        text, _link = _sandbox_item_excerpt(payload, item_path)
        # 被选影响链条目的 effect/mechanism 并为一条 state 假设置顶；
        # 源起点假设（前提集）全量继承，未选链条条目不进入。
        assumptions = [_state(f"源沙盘探索的既定影响：{text}")]
        assumptions.extend(inherited)
        refs = _sandbox_affected_refs(payload, item_path)
        candidates, canonical, knowledge = _migrate_subjects(source_start, refs)
        return assumptions, candidates, canonical, knowledge

    if source_scale == "event":
        if target_scale == "scene_line":
            text, item = _event_item_excerpt(payload, item_path)
            # 源事件摘录（或被选条目）为 state 假设；主体迁移按被选条目过滤。
            assumptions = [_state(f"源事件探索的既定情节：{text}")]
            refs = _event_item_refs(payload, item_path, item)
        else:
            # 追因：被选缺口/路径的前提转 world_rule/state 假设。
            assumptions = _event_premise_assumptions(payload, item_path)
            refs = []
        return assumptions, *_migrate_subjects(source_start, refs)

    # scene_line 源：对白/动作与其依据转 state 假设；目标主体迁移。
    text = _scene_line_excerpt(payload, labels)
    target = str(payload.get("target_ref") or "")
    speaker = labels.get(target, target or "人物")
    basis = str(payload.get("rationale") or "")
    knowledge_basis = [str(item) for item in payload.get("knowledge_basis") or []]
    if knowledge_basis:
        basis = "；".join([basis, *knowledge_basis])
    moment = f"源场景探索的已发生时刻：{text}（依据：{basis}）"
    if target_scale == "event":
        # 追因：对白/动作与其依据转 state 假设 + identity 假设（动机待探）。
        assumptions = [
            _state(moment),
            _identity(
                f"{speaker} 在该情境下的动机尚待探明"
                "（以上对白/动作只作已发生记录，不预设动机）"
            ),
        ]
    else:
        # 看影响：情境假设继承 + 已发生时刻置顶。
        assumptions = [_state(f"{moment}；观察它的后续影响"), *inherited]
    candidates, canonical, knowledge = _migrate_subjects(
        source_start, [target] if target else []
    )
    return assumptions, candidates, canonical, knowledge


def _event_item_refs(payload: dict, item_path: str, item: dict | None) -> list[str]:
    """事件条目涉及的主体：整结果取全部主体；单条目按文本包含保守匹配。

    事件载荷的结构化主体只在 ``info_boundary.subject_ref`` 上；单条目
    （gap/bridge）没有结构化主体引用，用主体 ID 是否出现在条目展示文本
    中做保守匹配——匹配不到就不迁移，不伪造涉及关系。
    """

    refs = _payload_candidate_refs(payload)
    if not item_path:
        return refs
    if item is None:
        return []
    text = exploration_entry_display_text(item_path, item)
    return [ref for ref in refs if ref in text]


def _payload_candidate_refs(payload: dict) -> list[str]:
    refs = [
        str(entry.get("subject_ref") or "")
        for entry in payload.get("info_boundary") or []
    ]
    return [ref for ref in refs if ref]


def _event_premise_assumptions(payload: dict, item_path: str) -> list[Assumption]:
    """事件→沙盘追因：被选条目的前提转假设；未选缺口/路径不进入。

    事件 rule_constraints 是规则 → world_rule；缺口与事实前提 → state。
    """
    mode = str(payload.get("mode") or "")
    if not item_path:
        if mode == "goal":
            return _goal_premise_assumptions(payload)
        rows = (
            list(payload.get("gaps") or [])
            if mode == "diagnose"
            else list(payload.get("bridge_candidates") or [])
        )
        prefix = "gap" if mode == "diagnose" else "bridge"
        assumptions: list[Assumption] = []
        for index in range(len(rows)):
            assumptions.extend(_event_premise_assumptions(payload, f"{prefix}:{index}"))
        return assumptions
    kind, _, raw_index = item_path.partition(":")
    index = int(raw_index)
    if kind == "gap":
        gap = (payload.get("gaps") or [])[index]
        text = f"源事件缺口「{gap.get('description') or ''}」待追因；"
        text += f"它要成立需要：{gap.get('why_needed') or ''}"
        if gap.get("possible_fix_hint"):
            text += f"（候选解释：{gap['possible_fix_hint']}，待沙盘验证）"
        return [_state(text)]
    bridge = (payload.get("bridge_candidates") or [])[index]
    steps = " → ".join(str(step) for step in bridge.get("steps") or [])
    result: list[Assumption] = [_state(f"源事件探索选定的补桥路径：{steps}")]
    for condition in bridge.get("required_conditions") or []:
        result.append(_state(f"源补桥路径的待核实前提：{condition}"))
    return result


def _goal_premise_assumptions(payload: dict) -> list[Assumption]:
    goal = payload.get("goal_path") or {}
    assumptions = [
        _rule(f"源事件导向的既定约束：{constraint}")
        for constraint in goal.get("rule_constraints") or []
    ]
    unsolvable = goal.get("unsolvable")
    if unsolvable:
        missing = "；".join(str(item) for item in unsolvable.get("missing") or [])
        assumptions.append(
            _state(
                f"目标「{goal.get('goal') or ''}」在源探索中无法达成；"
                f"缺项：{missing or unsolvable.get('reason') or ''}"
            )
        )
        return assumptions
    steps = " → ".join(str(step.get("action") or "") for step in goal.get("steps") or [])
    assumptions.append(
        _state(f"源事件探索选定的导向路径：{goal.get('goal') or ''}（{steps}）")
    )
    return assumptions


def _state(text: str) -> Assumption:
    return Assumption(kind="state", text=text[:2000])


def _rule(text: str) -> Assumption:
    return Assumption(kind="world_rule", text=text[:2000])


def _identity(text: str) -> Assumption:
    return Assumption(kind="identity", text=text[:2000])


# ---------------------------------------------------------------------------
# 探索历史（P0 §7.6：provisional 与带探索输出的 Scene 根，不与旧 Scene 历史混排）
# ---------------------------------------------------------------------------


def _root_summary(root: Any, chain: str) -> dict:
    request_json = root.request_json or {}
    return {
        "root_id": str(root.id),
        "chain": chain,
        "source_kind": getattr(root, "source_kind", SCENE_SOURCE_KIND),
        "scale": request_json.get("exploration_scale"),
        "scene_id": str(root.scene_id) if root.scene_id is not None else None,
        "start_fingerprint": request_json.get("exploration_start_fingerprint"),
        "status": root.status,
        "created_at": root.created_at.isoformat() if root.created_at else None,
    }


def _has_output_kind(payload: Any) -> bool:
    return isinstance(payload, dict) and "output_kind" in payload


async def _exploration_root_ids(
    db,
    novel_id: uuid.UUID,
    *,
    chain: str,
) -> set[uuid.UUID]:
    """带探索输出的根 ID 集合：output_kind 键在 Python 侧判断。

    JSON 键存在性没有跨 SQLite/PG 的可移植谓词（SQLite 下标语法语义不符），
    且两表每作品行数有界，这里做有界扫描后在 Python 判别。
    """
    if chain == "progression":
        rows = await db.execute(
            select(
                StoryWorldProgressionStep.root_id,
                StoryWorldProgressionStep.result_json,
            )
            .where(StoryWorldProgressionStep.novel_id == novel_id)
            .limit(_HISTORY_SCAN_CAP * 8)
        )
    else:
        rows = await db.execute(
            select(StorySceneDirectorRound.root_id, StorySceneDirectorRound.output_json)
            .where(StorySceneDirectorRound.novel_id == novel_id)
            .limit(_HISTORY_SCAN_CAP * 8)
        )
    return {root_id for root_id, payload in rows if _has_output_kind(payload)}


async def list_exploration_history_results(
    db,
    *,
    novel_id: str,
    owner_id: str,
    root_id: str | None = None,
    scale: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """历史端点的平铺结果行（P0 §8）：``items[]`` 每行一个探索结果。

    只列探索输出行（带 ``output_kind``）或临时起点根下的输出行；owner+novel
    过滤，按 ``created_at`` 倒序稳定分页。gate 关闭后仍可读。
    """

    if scale is not None and scale not in EXPLORATION_CHAIN_BY_SCALE:
        raise DomainError(f"不支持的探索尺度：{scale}")
    await _require_project(db, novel_id, owner_id)
    nid = _uuid(novel_id)
    wanted_root = _uuid(root_id) if root_id else None
    chains = (
        [EXPLORATION_CHAIN_BY_SCALE[scale]]
        if scale is not None
        else ["progression", "scene"]
    )
    items: list[dict] = []
    for chain in chains:
        exploration_root_ids = await _exploration_root_ids(db, nid, chain=chain)
        if chain == "progression":
            root_model = StoryWorldProgressionRoot
            row_model = StoryWorldProgressionStep
        else:
            root_model = StorySceneDirectorRoot
            row_model = StorySceneDirectorRound
        root_query = select(root_model).where(
            root_model.novel_id == nid,
            or_(
                root_model.source_kind == PROVISIONAL_SOURCE_KIND,
                root_model.id.in_(exploration_root_ids),
            ),
        )
        if wanted_root is not None:
            root_query = root_query.where(root_model.id == wanted_root)
        roots = (await db.scalars(root_query.limit(_HISTORY_SCAN_CAP))).all()
        if not roots:
            continue
        rows = (
            await db.scalars(
                select(row_model)
                .where(
                    row_model.novel_id == nid,
                    row_model.root_id.in_([root.id for root in roots]),
                )
                .limit(_HISTORY_SCAN_CAP * 8)
            )
        ).all()
        roots_by_id = {root.id: root for root in roots}
        for row in rows:
            root = roots_by_id.get(row.root_id)
            if root is None:
                continue
            envelope = unpack_exploration_output(row)
            if envelope is None:
                continue
            if envelope.output_kind == LOCK_SET_OUTPUT_KIND:
                # lock_set 是锁定记录，不算 AI 结果：历史 AI 列表过滤（M3-A 契约）。
                continue
            items.append(
                {
                    "root_id": str(row.root_id),
                    "branch_id": str(row.branch_id),
                    "result_id": str(row.id),
                    "chain": chain,
                    "scale": (root.request_json or {}).get("exploration_scale"),
                    "output_kind": envelope.output_kind,
                    "label": _result_label(envelope),
                    "start_fingerprint": (root.request_json or {}).get(
                        "exploration_start_fingerprint"
                    ),
                    "created_at": row.created_at.isoformat()
                    if row.created_at
                    else None,
                    "payload": envelope.payload.model_dump(mode="json"),
                }
            )
    if scale is not None:
        items = [item for item in items if item.get("scale") == scale]
    items.sort(
        key=lambda item: (
            (item["created_at"] is not None, item["created_at"]),
            item["result_id"],
        ),
        reverse=True,
    )
    total = len(items)
    return {"items": items[offset : offset + limit], "total": total}


def _result_label(envelope: ExplorationOutputEnvelope) -> str:
    payload = envelope.payload
    if envelope.output_kind == AUTHOR_EDIT_OUTPUT_KIND:
        inner = payload.edited_payload.model_dump(mode="json")
        base = payload.base_output_kind
        return f"作者编辑版：{_result_label_of_kind(base, inner)}"
    return _result_label_of_kind(
        envelope.output_kind, payload.model_dump(mode="json")
    )


def _result_label_of_kind(output_kind: str, payload: dict) -> str:
    if output_kind == SANDBOX_OUTPUT_KIND:
        return str(payload.get("question") or "")[:120]
    if output_kind == EVENT_OUTPUT_KIND:
        return str(payload.get("original_excerpt") or "")[:120]
    if output_kind == FULL_REHEARSAL_OUTPUT_KIND:
        # 完整排演（M3-B）：以首轮第一张表演卡为摘要，空则给稳定占位文本。
        rounds = payload.get("rounds") or []
        first_card = ((rounds or [{}])[0].get("performances") or [{}])[0]
        return (str(first_card.get("line_or_beat") or "") or "（完整排演）")[:120]
    line = str(payload.get("line") or "")
    if not line:
        variants = payload.get("variants") or []
        if variants:
            line = str((variants[0] or {}).get("line") or "")
    if not line and payload.get("spatial_assessment") is not None:
        line = "（空间诊断结论）"
    return line[:120]


async def read_exploration_history(
    db,
    *,
    novel_id: str,
    owner_id: str,
    scale: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """列出临时起点根与带探索输出的 Scene 根；owner+novel 过滤，稳定排序。"""

    if scale is not None and scale not in EXPLORATION_CHAIN_BY_SCALE:
        raise DomainError(f"不支持的探索尺度：{scale}")
    await _require_project(db, novel_id, owner_id)
    chains = (
        [EXPLORATION_CHAIN_BY_SCALE[scale]]
        if scale is not None
        else ["progression", "scene"]
    )
    nid = _uuid(novel_id)
    summaries: list[tuple[Any, str]] = []
    for chain in chains:
        exploration_root_ids = await _exploration_root_ids(db, nid, chain=chain)
        if chain == "progression":
            query = select(StoryWorldProgressionRoot).where(
                StoryWorldProgressionRoot.novel_id == nid,
                or_(
                    StoryWorldProgressionRoot.source_kind == PROVISIONAL_SOURCE_KIND,
                    StoryWorldProgressionRoot.id.in_(exploration_root_ids),
                ),
            )
        else:
            query = select(StorySceneDirectorRoot).where(
                StorySceneDirectorRoot.novel_id == nid,
                or_(
                    StorySceneDirectorRoot.source_kind == PROVISIONAL_SOURCE_KIND,
                    StorySceneDirectorRoot.id.in_(exploration_root_ids),
                ),
            )
        rows = (await db.scalars(query.limit(_HISTORY_SCAN_CAP))).all()
        summaries.extend((row, chain) for row in rows)
    if scale is not None:
        summaries = [
            item
            for item in summaries
            if (item[0].request_json or {}).get("exploration_scale") == scale
        ]
    def _sort_key(item: tuple[Any, str]):
        created = item[0].created_at
        # created_at 理论上可为空：先按“有值 > 无值”分组，组内按时间与 ID 稳定排序。
        return ((created is not None, created), str(item[0].id))

    summaries.sort(key=_sort_key, reverse=True)
    total = len(summaries)
    page = summaries[offset : offset + limit]
    return {
        "items": [_root_summary(root, chain) for root, chain in page],
        "total": total,
    }
