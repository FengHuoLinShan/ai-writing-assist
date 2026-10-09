"""P2-C C2 消费登记写入端（构建与幂等合并；零 DB、零 LLM）。

C1 契约（``consumption.py``）把登记集内嵌进消费产物行 ``state_json``
（键 ``_consumption_registry``，沿 P2-A ``_field_provenance`` 先例：随产物
行一起 supersede 软删、生命周期一致、不加表）。本模块补**写入端**函数：

- ``register_consumption``：把一条登记幂等合并进产物行 state JSON——
  同 ``(novel_id, consumer)`` 定位的旧登记被替换（投影重建即重新登记，
  最新声明胜），返回写回后的登记列表（JSON 边界已是 ``model_dump`` 形态）。
- ``scene_checkpoint_registration``：从 Scene 锚 + 各章消费范围构建
  ``story_scene_checkpoint`` 类登记（供 story 投影侧接线调用；章节锚字段
  与 ``scene_projection._working_refs`` 同源——draft/version/source_hash
  能锚则锚，取不到的字段缺省、区间缺省=整章消费的诚实语义）。

**接线现状（C2 批）**：真实写入点 ``story/continuity/scene_projection.py``
``_project_dimension`` 在 story 模块（B 类接线，本批不越权改 story 文件）；
story→evolution 依赖边在 import-gate 冻结集合内，接线时经
``modules.evolution.contracts``/``facade`` 再出口本模块函数即可。失效侧
（``invalidation.apply_source_invalidation``）对无登记场景另以**锚定结构
事实合成登记**（见 ``invalidation._anchored_registrations``），保证无接线
时受影响列表仍可解释、失效行为与现状保守扩大逐位一致。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from modules.evolution.consumption import (
    CONSUMPTION_REGISTRY_STATE_KEY,
    BasisAnchor,
    ChapterConsumption,
    ConsumerKind,
    ConsumerRef,
    ConsumptionRecord,
    OffsetRange,
    SourceBinding,
    read_consumption_records,
)


def _consumer_key(record: ConsumptionRecord) -> tuple[Any, ...]:
    consumer = record.consumer
    return (
        record.novel_id,
        consumer.kind.value,
        consumer.scene_id,
        consumer.dimension,
        consumer.chapter_index,
        consumer.content_mode,
    )


def register_consumption(
    state: dict[str, Any],
    record: ConsumptionRecord,
) -> list[dict[str, Any]]:
    """把一条登记幂等合并进产物行 state JSON（就地更新，返回登记列表）。

    同定位登记替换（重建投影时最新声明胜，旧版本随行 supersede 消失）；
    跨定位追加。返回值即 ``state[CONSUMPTION_REGISTRY_STATE_KEY]`` 的新值
    （``model_dump(mode="json")`` 形态，直接可进 JSON 列）。调用方负责
    落库；本函数不触碰 DB。
    """
    records = list(read_consumption_records(state))
    replaced = False
    key = _consumer_key(record)
    for position, existing in enumerate(records):
        if _consumer_key(existing) == key:
            if existing.model_dump(exclude={"registered_at"}) != record.model_dump(
                exclude={"registered_at"}
            ):
                records[position] = record
            replaced = True
            break
    if not replaced:
        records.append(record)
    payload = [item.model_dump(mode="json") for item in records]
    state[CONSUMPTION_REGISTRY_STATE_KEY] = payload
    return payload


def scene_checkpoint_registration(
    novel_id: str,
    *,
    scene_id: str,
    scene_index: int,
    dimension: str,
    chapters: Sequence[Mapping[str, Any]],
    method_version: str,
    content_mode: str = "working",
    checkpoint_id: str | None = None,
) -> ConsumptionRecord:
    """构建 ``story_scene_checkpoint`` 类消费登记。

    ``chapters`` 每项 ``{chapter_index, draft_id?, version_number?,
    source_hash?, ranges?: [(start, end), ...]}``（``ranges`` 缺省=整章
    消费）。``checkpoint_id`` 给出时落 ``BasisAnchor(scene_checkpoint)``
    锚（重建派生状态时的重验引用）。
    """
    bindings = tuple(
        ChapterConsumption(
            chapter_index=int(item["chapter_index"]),
            draft_id=item.get("draft_id"),
            version_number=(
                int(item["version_number"])
                if item.get("version_number") is not None
                else None
            ),
            source_hash=item.get("source_hash"),
            ranges=tuple(
                OffsetRange(start_offset=int(start), end_offset=int(end))
                for start, end in (item.get("ranges") or ())
            ),
        )
        for item in chapters
    )
    return ConsumptionRecord(
        novel_id=novel_id,
        consumer=ConsumerRef(
            kind=ConsumerKind.story_scene_checkpoint,
            scene_id=scene_id,
            scene_index=scene_index,
            dimension=dimension,
        ),
        binding=SourceBinding(content_mode=content_mode, chapters=bindings),  # type: ignore[arg-type]
        basis=(
            BasisAnchor(anchor_kind="scene_checkpoint", ref_id=checkpoint_id)
            if checkpoint_id
            else None
        ),
        method_version=method_version,
        registered_at=datetime.now(UTC),
    )


__all__ = [
    "register_consumption",
    "scene_checkpoint_registration",
]
