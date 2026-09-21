"""演化推进编排内核：前序屏障与有限并行准入（V4 E04）。

- **前序屏障（T07）**：Scene N+1 的输入清单必须实际包含 Scene N 的
  已提交回执（attempt 身份与已提交前缀）。前序未提交时输入显式标记
  ``blocked``，绝不携带未提交的假结论——阻塞不扩大到无关范围，但也不
  绕过屏障编造继承状态。
- **有限并行准入**：编排只按依赖键分配批次——同一 Scene 内依赖键不相交
  的任务可同批并行；依赖键冲突或叙事顺序（Scene N+1 需 Scene N 的提交
  回执）强制分批。准入是确定性代码，不采信模型自称可并行（§4.2）。

游标与预算纪律：游标推进由 ``store.save_receipt`` 在回执落库的同一事务
内完成（E03c）；预算预留用 ``store.reserve_budget`` 的原子条件更新（T21）。
本模块不持有 provider、不发请求——采样与窄提交仍由 E03c 协议组合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from modules.evolution.contracts import CommittedPrefix
from modules.evolution.store import PostgresAttemptStore

DependencyStatus = Literal["committed", "blocked"]


class SceneInputManifest(BaseModel):
    """一个 Scene 的窄任务输入清单：前序理解必须显式在册。

    ``previous_scene_attempt_id`` / ``previous_committed_prefix`` 是 T07
    断言面——后一 Scene 的实际输入里必须真的带着前一 Scene 的已提交回执
    身份，而不是按序落库碰巧相邻。
    """

    model_config = ConfigDict(extra="forbid")

    run_key: str = Field(min_length=1)
    scene_index: int = Field(ge=0)
    source_manifest_hash: str = Field(min_length=32, max_length=64)
    dependency_status: DependencyStatus
    previous_scene_attempt_id: str | None = Field(default=None)
    previous_committed_prefix: CommittedPrefix | None = None
    blocked_reason: str | None = Field(default=None, max_length=500)


async def prepare_scene_input(
    store: PostgresAttemptStore,
    *,
    run_key: str,
    scene_index: int,
    source_manifest_hash: str,
) -> SceneInputManifest:
    """编译 Scene N 的输入清单：读取 run head，落实前序屏障。"""
    head = await store.load_head_receipt(run_key)
    if scene_index == 0:
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
    return SceneInputManifest(
        run_key=run_key,
        scene_index=scene_index,
        source_manifest_hash=source_manifest_hash,
        dependency_status="committed",
        previous_scene_attempt_id=head.attempt_id,
        previous_committed_prefix=head.committed_prefix,
    )


def manifest_includes_committed_predecessor(manifest: SceneInputManifest) -> bool:
    """T07 断言谓词：输入实际包含前序已提交回执。"""
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

    - 叙事顺序屏障：Scene N+1 的任务只能进 Scene N 任务之后的批次
      （它需要 N 的提交回执作为输入）；
    - 依赖键屏障：同批任务依赖键两两不相交；冲突任务分批。

    返回按执行顺序的批次列表；每批内部任务可并行执行。
    """
    ordered = sorted(tasks, key=lambda task: (task.scene_index, task.task_key))
    batches: list[list[SceneTask]] = []
    key_footprint: list[set[str]] = []
    scene_batch: dict[int, int] = {}
    for task in ordered:
        earliest = (
            scene_batch.get(task.scene_index - 1, -1) + 1 if task.scene_index else 0
        )
        placed = False
        for index in range(earliest, len(batches)):
            if not (task.dependency_keys & key_footprint[index]):
                batches[index].append(task)
                key_footprint[index].update(task.dependency_keys)
                scene_batch[task.scene_index] = index
                placed = True
                break
        if not placed:
            batches.append([task])
            key_footprint.append(set(task.dependency_keys))
            scene_batch[task.scene_index] = len(batches) - 1
    return batches
