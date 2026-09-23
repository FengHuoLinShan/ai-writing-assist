"""演化推进编排内核：前序屏障与有限并行准入（V4 E04）。

- **前序屏障（T07，含顺序检查）**：Scene N 的输入清单必须实际包含
  Scene N-1 的已提交回执（attempt 身份与已提交前缀）。run head 的
  ``through_scene_index`` 必须恰好是 N-1——跳场（0 后直接 7）、倒序或
  重复推进都按 ``blocked`` 显式拒绝，绝不携带编造的继承状态。前序输入
  还携带**实际状态内容**（前序回执观察的有界摘要），采样 Prompt 据此
  注入真实理解，不靠回执 ID 冒充上下文。
- **有限并行准入**：编排只按依赖键分配批次——同一 Scene 内依赖键不相交
  的任务可同批并行；依赖键冲突或叙事顺序（Scene N+1 需 Scene N 的提交
  回执）强制分批。Scene 的批次位置取其全部任务的**最大**批次，后放的
  小批次不得回写覆盖。准入是确定性代码，不采信模型自称可并行（§4.2）。

游标与预算纪律：游标推进由 ``store.save_receipt`` 在回执落库的同一事务
内完成（E03c）；预算预留用 ``store.reserve_budget`` 的原子条件更新（T21）。
本模块不持有 provider、不发请求——采样与窄提交仍由 E03c 协议组合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from modules.evolution.contracts import CommittedPrefix
from modules.evolution.store import PostgresAttemptStore

DependencyStatus = Literal["committed", "blocked"]

PRIOR_OBSERVATION_WINDOW = 3
"""前序观察覆盖的已提交 Scene 窗口（A04）：不只看上一个 Scene，截断在
manifest 覆盖度里显式披露，未注入不等于不存在。"""

PRIOR_OBSERVATION_LIMIT = 20
"""每个 Scene 注入的前序观察有界条数：Prompt 携带真实理解但不无限膨胀。"""


class SceneInputManifest(BaseModel):
    """一个 Scene 的窄任务输入清单：前序理解必须显式在册。

    ``previous_scene_attempt_id`` / ``previous_committed_prefix`` /
    ``previous_observations`` 是 T07 断言面——后一 Scene 的实际输入里
    必须真的带着前一 Scene 的已提交回执身份**和**有界的前序状态内容，
    而不是按序落库碰巧相邻、也不是只传回执 ID 冒充理解。

    ``previous_observations`` 是结构化条目（A04）：保留 modality、主体、
    观察身份与来源 Scene——传闻/假设在输入里保持传闻/假设，不再压成
    裸谓词冒充已确认事实；``previous_observations_coverage`` 披露窗口与
    截断（未注入条数显式在册）。
    """

    model_config = ConfigDict(extra="forbid")

    run_key: str = Field(min_length=1)
    scene_index: int = Field(ge=0)
    source_manifest_hash: str = Field(min_length=32, max_length=64)
    dependency_status: DependencyStatus
    previous_scene_attempt_id: str | None = Field(default=None)
    previous_committed_prefix: CommittedPrefix | None = None
    previous_observations: list[dict[str, Any]] = Field(
        default_factory=list, max_length=64
    )
    previous_observations_coverage: dict[str, Any] | None = None
    blocked_reason: str | None = Field(default=None, max_length=500)


async def prepare_scene_input(
    store: PostgresAttemptStore,
    *,
    run_key: str,
    scene_index: int,
    source_manifest_hash: str,
) -> SceneInputManifest:
    """编译 Scene N 的输入清单：读取 run head，落实前序屏障与顺序检查。"""
    head = await store.load_head_receipt(run_key)
    if scene_index == 0:
        if head is not None:
            return SceneInputManifest(
                run_key=run_key,
                scene_index=scene_index,
                source_manifest_hash=source_manifest_hash,
                dependency_status="blocked",
                blocked_reason=("run 已提交过链头之后的回执，Scene 0 不能重复或倒序推进"),
            )
        return SceneInputManifest(
            run_key=run_key,
            scene_index=scene_index,
            source_manifest_hash=source_manifest_hash,
            dependency_status="committed",
        )
    if head is None:
        return SceneInputManifest(
            run_key=run_key,
            scene_index=scene_index,
            source_manifest_hash=source_manifest_hash,
            dependency_status="blocked",
            blocked_reason="前序 Scene 尚无已提交回执，不继承未提交的解释",
        )
    head_position = head.committed_prefix.through_scene_index
    if head_position != scene_index - 1:
        return SceneInputManifest(
            run_key=run_key,
            scene_index=scene_index,
            source_manifest_hash=source_manifest_hash,
            dependency_status="blocked",
            blocked_reason=(
                f"前序顺序不符：run head 已提交到 Scene {head_position}，"
                f"下一步只接受 Scene {head_position + 1}（收到 Scene {scene_index}）"
            ),
        )
    previous_observations, coverage = await store.load_prior_observations(
        run_key,
        max_scenes=PRIOR_OBSERVATION_WINDOW,
        per_scene_limit=PRIOR_OBSERVATION_LIMIT,
    )
    return SceneInputManifest(
        run_key=run_key,
        scene_index=scene_index,
        source_manifest_hash=source_manifest_hash,
        dependency_status="committed",
        previous_scene_attempt_id=head.attempt_id,
        previous_committed_prefix=head.committed_prefix,
        previous_observations=previous_observations,
        previous_observations_coverage=coverage,
    )


def manifest_includes_committed_predecessor(manifest: SceneInputManifest) -> bool:
    """T07 断言谓词：输入实际包含前序已提交回执与状态内容。"""
    return manifest.dependency_status == "committed" and (
        manifest.scene_index == 0
        or (
            manifest.previous_scene_attempt_id is not None
            and manifest.previous_committed_prefix is not None
        )
    )


@dataclass(frozen=True)
class SceneTask:
    """一个可调度的窄任务：所属 Scene 与它的依赖键（read-set 证明）。"""

    scene_index: int
    task_key: str
    dependency_keys: frozenset[str] = field(default_factory=frozenset)


def plan_parallel_batches(tasks: list[SceneTask]) -> list[list[SceneTask]]:
    """确定性批次规划：

    - 叙事顺序屏障：Scene N+1 的任务只能进 Scene N **全部任务**之后的
      批次（按 Scene N 的最大批次位置计算；它需要 N 的提交回执输入）；
    - 依赖键屏障：同批任务依赖键两两不相交；冲突任务分批。

    返回按执行顺序的批次列表；每批内部任务可并行执行。
    """
    ordered = sorted(tasks, key=lambda task: (task.scene_index, task.task_key))
    batches: list[list[SceneTask]] = []
    key_footprint: list[set[str]] = []
    scene_max_batch: dict[int, int] = {}

    def record(scene_index: int, batch_index: int) -> None:
        # 后放的小批次不得覆盖同 Scene 已占的最大批次位置。
        scene_max_batch[scene_index] = max(
            scene_max_batch.get(scene_index, -1), batch_index
        )

    for task in ordered:
        earliest = (
            scene_max_batch.get(task.scene_index - 1, -1) + 1 if task.scene_index else 0
        )
        placed = False
        for index in range(earliest, len(batches)):
            if not (task.dependency_keys & key_footprint[index]):
                batches[index].append(task)
                key_footprint[index].update(task.dependency_keys)
                record(task.scene_index, index)
                placed = True
                break
        if not placed:
            batches.append([task])
            key_footprint.append(set(task.dependency_keys))
            record(task.scene_index, len(batches) - 1)
    return batches
