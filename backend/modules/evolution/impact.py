"""P2-C C2 失效影响组装层（登记读取 + 锚定合成 + 回执视图投影）。

模块拓扑：``consumption`` 契约（C1 冻结）顶层 import ``invalidation``
（``UNSUPPORTED_CONSUMERS``/``InvalidationReceipt``/``SourceChange``），
本模块反向依赖两者——只能由 ``invalidation`` 在**使用点函数内** import
（顶层互引即部分初始化环）。``facade``/组合根可顶层 import 本模块。

职责（``invalidation.apply_source_invalidation`` 的细化扩展）：

1. ``load_scene_consumption_records``：读各 Scene current checkpoint 行
   ``state_json`` 内嵌的真实消费登记（写入端接线归 story 侧 B 类，
   ``registration.register_consumption``；接线前恒为空集）。
2. ``anchored_registrations``：为锚定变更章、且该 ``(scene, dimension)``
   无真实登记的投影合成结构登记——Scene 锚定该章是 outline 的确定性
   事实，合成保证无接线时受影响列表仍可解释（known=锚定命中），且评估
   窗口与现状保守扩大逐位一致（合成登记恒判整章命中 → 不收窄窗口）。
3. ``attach_impact_view``：把 ``assess_source_impact`` 的评估投影为回执
   增量字段（``affected``/``unknown_scope``/``receipt_id``/
   ``recompute_options`` + 内嵌 assessment 供视图重投影）。
4. ``receipt_view``：DI 键 ``EVOLUTION_INVALIDATION_RECEIPT_VIEW`` 的实现
   ——回执 → 作者语言完整视图（writing 层 C3 经组合根消费）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DomainError
from modules.evolution.consumption import (
    ChapterConsumption,
    ConsumerKind,
    ConsumerRef,
    ConsumptionRecord,
    ImpactAssessment,
    SourceBinding,
    affected_view_entries,
    derive_recompute_options,
    read_consumption_records,
    receipt_fingerprint,
    receipt_public_view,
)
from modules.evolution.invalidation import (
    InvalidationReceipt,
    _scene_chapter_indices,
)
from modules.story.continuity.contracts import SCENE_MEMORY_DIMENSIONS
from modules.story.continuity.facade import get_scene_checkpoints

#: 锚定结构合成登记的方法版本标识（区别于 story 侧接线的真实登记；
#: 结构事实升级（锚定口径变化）时递增，登记随产物行 supersede 失效）。
ANCHORED_SCENE_IMPLICIT_METHOD_VERSION = "anchored-scene-implicit-v1"


async def load_scene_consumption_records(
    db: AsyncSession,
    novel_id: str,
    scenes: Sequence[dict[str, Any]],
) -> list[ConsumptionRecord]:
    """读各 Scene current checkpoint 行内嵌的消费登记集（接线前恒空）。

    经 story continuity facade 逐场景只读（``get_scene`` 不触发重建）；
    旧格式行（无 ``_consumption_registry`` 键）按契约返回空集，行为退化
    为纯保守，与现状一致。必须在 supersede 之前调用（current 行随失效
    消失）。场景级读取失败按该场景无登记保守处理，不阻断失效传播。
    """
    records: list[ConsumptionRecord] = []
    for scene in scenes:
        scene_id = scene.get("id")
        if not scene_id:
            continue
        try:
            checkpoint_set = await get_scene_checkpoints(db, novel_id, str(scene_id))
        except DomainError:
            continue
        for item in checkpoint_set.items:
            records.extend(read_consumption_records(item.state_json))
    return records


def anchored_registrations(
    novel_id: str,
    *,
    chapter_index: int,
    scenes: Sequence[dict[str, Any]],
    real_records: Sequence[ConsumptionRecord],
) -> list[ConsumptionRecord]:
    """为锚定变更章、且该 ``(scene, dimension)`` 无真实登记的投影合成登记。

    合成依据是 outline 的确定性结构事实（Scene 锚定该章 → 其投影消费该章
    事件流），binding 按整章消费（``ranges=()``）、无稿锚——评估恒判
    ``anchored_chapter_edited`` 命中，方向只可能保守。真实登记（含更细
    区间与 draft/version 锚）存在时**不合成**——登记是权威声明，优先于
    结构事实。合成登记参与评估后：

    - 无真实登记场景：全部保守窗口内场景要么锚定（known 命中）要么无
      任何事实（``scenes_without_registration`` 非空 → 保守），评估窗口
      ``from == earliest``，与现状保守扩大逐位一致。
    - 真实登记完备场景：合成不发生（或仅补锚定缺口），窗口按登记收窄。
    """
    real_keys = {
        (record.consumer.scene_id, record.consumer.dimension)
        for record in real_records
        if record.consumer.kind is ConsumerKind.story_scene_checkpoint
    }
    synthesized: list[ConsumptionRecord] = []
    for scene in scenes:
        if chapter_index not in _scene_chapter_indices(scene):
            continue
        scene_id = scene.get("id")
        if not scene_id:
            continue
        try:
            scene_index = int(scene["scene_index"])
        except (KeyError, TypeError, ValueError):
            continue
        for dimension in SCENE_MEMORY_DIMENSIONS:
            if (str(scene_id), dimension) in real_keys:
                continue
            synthesized.append(
                ConsumptionRecord(
                    novel_id=novel_id,
                    consumer=ConsumerRef(
                        kind=ConsumerKind.story_scene_checkpoint,
                        scene_id=str(scene_id),
                        scene_index=scene_index,
                        dimension=dimension,
                    ),
                    binding=SourceBinding(
                        content_mode="working",
                        chapters=(ChapterConsumption(chapter_index=chapter_index),),
                    ),
                    method_version=ANCHORED_SCENE_IMPLICIT_METHOD_VERSION,
                    registered_at=datetime.now(UTC),
                )
            )
    return synthesized


def attach_impact_view(
    receipt: InvalidationReceipt,
    assessment: ImpactAssessment,
) -> None:
    """把影响评估投影为回执增量字段（就地更新；幂等重算安全）。"""
    receipt.impact_assessment = assessment
    receipt.affected = affected_view_entries(receipt, assessment=assessment)
    receipt.unknown_scope = bool(assessment.unknown_scope.conservative) or bool(
        receipt.unsupported_consumers
    )
    receipt.recompute_options = derive_recompute_options(receipt, assessment=assessment)
    receipt.receipt_id = receipt_fingerprint(receipt)


def receipt_view(
    receipt: InvalidationReceipt,
    *,
    assessment: ImpactAssessment | None = None,
) -> dict[str, Any]:
    """DI 键 ``EVOLUTION_INVALIDATION_RECEIPT_VIEW`` 的实现。

    缺省用回执内嵌的 ``impact_assessment`` 重投影完整作者视图（scene 级
    ``affected``/``unknown_scope``/``recompute_options``）；显式传入
    assessment 或手写回执（无内嵌评估）时退化为 ``receipt_public_view``
    的确定性键形态。writing 层经 DI 消费，不 import evolution 类型
    （receipt 鸭子类型传入即可，只要暴露同名字段）。
    """
    resolved = assessment if assessment is not None else receipt.impact_assessment
    return receipt_public_view(receipt, assessment=resolved)


__all__ = [
    "ANCHORED_SCENE_IMPLICIT_METHOD_VERSION",
    "anchored_registrations",
    "attach_impact_view",
    "load_scene_consumption_records",
    "receipt_view",
]
