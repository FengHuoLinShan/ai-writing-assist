"""稳定观察身份推导（V4 E01，对应 01-EVOLUTION §2.2 / 验收 T06）。

事件/观察身份 = 来源范围 + 观察语义 + 观察契约版本。

- 不含输出位置：同一批次重新排序、合并或分批，观察身份不变；
- 不含 producer_run_id：另一个 run 在同一冻结来源上按同一契约版本得到同一
  断言，得到同一观察身份（观察去重），旧产物按 disposition 处置而不是重建；
- 含 observer_contract_version：方法演进后同一文本产生新一代观察，
  旧观察保留可对照，不静默改写。

文本保持逐字精确，不做空白或别名归一——归一化属于解释层，进入身份键
会让"引用了什么"变得不可审计。
"""

from __future__ import annotations

from infrastructure.llm.collaboration import content_hash
from modules.evolution.contracts import (
    ObservationModality,
    SourceRevisionRef,
)

_OBSERVATION_ID_NAMESPACE = "novelcraft.evolution.observation.v1"


def observation_semantic_fingerprint(
    *,
    source_ref: SourceRevisionRef,
    predicate_or_description: str,
    modality: ObservationModality,
    observer_contract_version: int,
) -> str:
    """观察语义指纹：同一来源范围上"出现了什么说法"，与运行和顺序无关。"""
    return content_hash(
        {
            "namespace": _OBSERVATION_ID_NAMESPACE,
            "novel_id": source_ref.novel_id,
            "source_kind": source_ref.source_kind,
            "draft_id": source_ref.draft_id,
            "content_hash": source_ref.content_hash,
            "start_offset": source_ref.start_offset,
            "end_offset": source_ref.end_offset,
            "source_revision": source_ref.source_revision,
            "segmentation_version": source_ref.segmentation_version,
            "predicate_or_description": predicate_or_description,
            "modality": modality,
            "observer_contract_version": observer_contract_version,
        }
    )


def derive_observation_id(
    *,
    source_ref: SourceRevisionRef,
    predicate_or_description: str,
    modality: ObservationModality,
    observer_contract_version: int,
) -> str:
    """稳定观察 ID（sha256 hex64）。语义即身份，输出顺序不是身份。"""
    return observation_semantic_fingerprint(
        source_ref=source_ref,
        predicate_or_description=predicate_or_description,
        modality=modality,
        observer_contract_version=observer_contract_version,
    )


_MENTION_ID_NAMESPACE = "novelcraft.evolution.mention.v1"


def derive_mention_id(
    *,
    observation_id: str,
    surface: str,
    ordinal: int,
    entity_type: str | None = None,
) -> str:
    """宿主侧稳定提及 ID：观察身份 + 表面名 + 序位。

    模型输出只有表面名（禁止编造实体 UUID，也不指定提及身份）；提及
    身份由宿主按真实来源范围派生的观察身份生成——同一观察内同一表面
    名按出现序位区分，批次重排不改变身份。
    """
    return content_hash(
        {
            "namespace": _MENTION_ID_NAMESPACE,
            "observation_id": observation_id,
            "surface": surface,
            "ordinal": ordinal,
            "entity_type": entity_type,
        }
    )
