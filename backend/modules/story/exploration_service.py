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
from modules.evidence.contracts import (
    Assumption,
    ExplorationStart,
    ProvisionalStart,
    SceneAnchorStart,
)
from modules.project import facade as project_facade
from modules.story.exploration_schemas import (
    AUTHOR_EDIT_OUTPUT_KIND,
    EVENT_MODE_HINTS,
    EVENT_OUTPUT_KIND,
    PAYLOAD_MODELS_BY_BASE_KIND,
    SANDBOX_OUTPUT_KIND,
    AuthorEditPayloadV1,
    ExplorationOutputEnvelope,
    apply_changed_assumptions,
    exploration_start_fingerprint,
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
) -> tuple[Any, Any]:
    """为一次探索创建根与初始分支；返回 ``(root, branch)``。

    沙盘/事件写推进链，场景对白写导演链。``provisional`` 起点强制无场景，
    ``scene_anchor`` 起点强制携带场景；推进链一律要求非空确认（临时起点为
    空资料集确认）。反事实对照（M2）时把基线结果 id 与 changed_assumptions
    一并冻结进根 request_json，worker 读取同一承载记录到结果 input_json。
    事件模式提示（M2）同样冻结进根 request_json：worker 据此注入信息差/
    导向 prompt 变体，仅事件尺度接受。
    """
    chain = EXPLORATION_CHAIN_BY_SCALE.get(scale)
    if chain is None:
        raise DomainError(f"不支持的探索尺度：{scale}")
    if event_mode_hint is not None:
        if scale != "event":
            raise DomainError("event_mode_hint 仅支持事件尺度")
        if event_mode_hint not in EVENT_MODE_HINTS:
            raise DomainError("未知的事件模式提示")
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


async def _root_for_chain(db, novel_id: str, root_id: Any, chain: str):
    if chain == "scene":
        from modules.story.director_service import get_director_root

        return await get_director_root(db, novel_id, str(root_id))
    from modules.story.world_progression_service import get_progression_root

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


async def compare_exploration_results(
    db,
    *,
    novel_id: str,
    owner_id: str,
    first_result_id: str,
    second_result_id: str,
    mode: str = "same_start",
) -> dict:
    """两结果比较：same_start 指纹不同或缺失即失败关闭（409）；
    counterfactual 要求反事实衍生或共享基线，成功回传 changed_conditions。"""

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
    changed_conditions: list[str] | None = None
    if mode == "counterfactual":
        changed_conditions = _counterfactual_link_condition(located[0][0], located[1][0])
        start_fingerprint = None
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
    return result


# ---------------------------------------------------------------------------
# 作者编辑保存（零模型调用；P0 §3.1/§5）
# ---------------------------------------------------------------------------


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
        from modules.story.director_service import get_director_branch

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
        from modules.story.world_progression_service import get_progression_branch

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
    return str(payload.get("line") or "")[:120]


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
