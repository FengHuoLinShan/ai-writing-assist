"""RP source-context pre-budget material and per-budget compile (M1 契约 S3/S4)。

S3 输出 :class:`InteractionSourceMaterial`（完整预算前材料），S4
:func:`compile_source_material` 按本次预算做必需项优先的确定性裁剪与渲染。
两段均为纯数据/纯函数：检索、原文回读、snapshot 与门禁留在
``InteractionStoryContextService.compile``。方法版本进入切片 3 的缓存 key，
行为变更时必须 bump。契约见
``docs/plans/2026-10-07-rp-retrieval-refactor-m1-contract.md``。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from infrastructure.llm.token_estimation import estimate_token_count

INTERACTION_MATERIAL_METHOD_VERSION = "interaction-material-v1"
"""S3 材料物化方法版本（含激活、回读、可见性证明与 warnings 语义）。"""

INTERACTION_RENDER_METHOD_VERSION = "interaction-render-v1"
"""S4 按预算编译方法版本（含必需项优先级、裁剪次序与渲染格式）。"""


@dataclass(frozen=True)
class InteractionSourceMaterial:
    """S3 输出：完整预算前材料。

    只承载与预算无关的确定结果；预算、tokenizer 与渲染决策由 S4 按次执行。
    ``reference_*`` 映射按 ``reference_order`` 全量收录激活项，供不同预算复用。
    """

    identity_block: str
    reference_order: tuple[str, ...]
    """激活 key 的候选次序（玩家/固定→名称命中→原文关联→相关关系）"""
    mandatory_keys: frozenset[str]
    reference_blocks: dict[str, str]
    reference_reasons: dict[str, str]
    reference_labels: dict[str, str]
    knowledge_block: str
    """玩家角色知识块；空串表示无可用知识块"""
    mandatory_reads: tuple[dict, ...]
    """必需项证明 reads（按激活次序去重后）"""
    excerpt_reads: tuple[dict, ...]
    """全部原文证据 reads（S3 排定次序）"""
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CompiledSourcePacket:
    """S4 输出：一次预算下的编译正文与来源清单。"""

    rendered: str
    included_refs: tuple[dict[str, str], ...]
    source_refs: tuple[dict, ...]
    blockers: tuple[str, ...]


def compile_source_material(
    material: InteractionSourceMaterial,
    *,
    budget_tokens: int,
) -> CompiledSourcePacket:
    """按本次预算从完整材料裁剪并渲染（必需项优先，可裁剪项确定性让位）。"""

    mandatory = material.mandatory_keys
    blocks: list[str] = [
        material.identity_block,
        *(
            material.reference_blocks[key]
            for key in material.reference_order
            if key in mandatory
        ),
    ]
    included_keys = [key for key in material.reference_order if key in mandatory]
    included_reads: list[dict] = list(material.mandatory_reads)
    blocks.extend(excerpt_block(read) for read in material.mandatory_reads)
    if material.knowledge_block:
        blocks.append(material.knowledge_block)
    if estimate_token_count("\n\n".join(blocks)) > budget_tokens:
        return CompiledSourcePacket(
            rendered="",
            included_refs=(),
            source_refs=(),
            blockers=("已固定的作品资料超出可用篇幅，请减少固定项",),
        )

    for key in material.reference_order:
        if key in mandatory:
            continue
        candidate = material.reference_blocks[key]
        if estimate_token_count("\n\n".join([*blocks, candidate])) > budget_tokens:
            continue
        blocks.append(candidate)
        included_keys.append(key)
    for read in material.excerpt_reads:
        if read in included_reads:
            continue
        candidate = excerpt_block(read)
        if estimate_token_count("\n\n".join([*blocks, candidate])) > budget_tokens:
            break
        blocks.append(candidate)
        included_reads.append(read)

    included_refs: list[dict[str, str]] = [
        {
            "reference_key": key,
            "label": material.reference_labels[key],
            "reason": material.reference_reasons[key],
        }
        for key in included_keys
    ]
    included_refs.extend(
        {
            "reference_key": stable_hash(read.get("source_ref") or {}),
            "label": str(read.get("title") or "原文片段"),
            "reason": "原文片段关联",
        }
        for read in included_reads
    )
    return CompiledSourcePacket(
        rendered=render_source_blocks(blocks),
        included_refs=tuple(included_refs),
        source_refs=tuple(dict(read["source_ref"]) for read in included_reads),
        blockers=(),
    )


def identity_block(anchor: dict, player_identity: dict) -> str:
    player = sanitize_source_text(
        str(player_identity.get("label") or player_identity.get("name") or "未命名玩家")
    )
    description = str(player_identity.get("description") or "").strip()
    return "\n".join(
        filter(
            None,
            [
                "## 不可越过的剧情边界",
                "- 剧情进度："
                f"{sanitize_source_text(str(anchor.get('chapter_title') or ''))}"
                f" · {sanitize_source_text(str(anchor.get('label') or ''))}",
                f"- 玩家身份：{player}",
                f"- 原创身份说明：{description}" if description else "",
                "- 只能使用该进度之前的事实和角色知识。",
            ],
        )
    )


def reference_block(item: dict, reason: str) -> str:
    return "\n".join(
        [
            f"## {sanitize_source_text(str(item.get('label') or ''))}"
            f" （{item.get('entity_type')}）",
            f"- 激活原因：{reason}",
        ]
    )


def excerpt_block(read: dict) -> str:
    source = read.get("source_ref") or {}
    return "\n".join(
        [
            "## 原文证据："
            f"{sanitize_source_text(str(read.get('title') or '未命名章节'))}",
            f"- 位置：第 {source.get('chapter_index')} 章",
            sanitize_source_text(str(read.get("text") or "")),
        ]
    )


def knowledge_block(item: dict, cutoff_chapter: int) -> str:
    lines = ["## 玩家角色在当前进度实际知道的事"]
    for entry in item.get("knowledge") or []:
        learned = entry.get("source_chapter_index")
        if not entry.get("is_public_baseline") and (
            not isinstance(learned, int) or learned >= cutoff_chapter
        ):
            continue
        target = entry.get("target_name") or entry.get("target_type") or "某对象"
        level = entry.get("knowledge_level")
        if level == "unknown":
            lines.append(f"- 对「{target}」并不知情。")
        elif level in {"false_belief", "misunderstood"}:
            if entry.get("misconception"):
                lines.append(f"- 对「{target}」的误解：{entry['misconception']}")
        elif entry.get("known_content"):
            qualifier = "传闻或局部认知" if level in {"rumor", "partial"} else "已知"
            lines.append(f"- {qualifier}「{target}」：{entry['known_content']}")
    return "\n".join(lines) if len(lines) > 1 else ""


_FENCE_CLOSE = "</SOURCE_REFERENCE_DATA>"


def sanitize_source_text(value: str) -> str:
    """Neutralize imported text that could close the reference-data fence."""

    return value.replace(_FENCE_CLOSE, "</原文引用结束>")


def render_source_blocks(blocks: list[str]) -> str:
    return (
        "<SOURCE_REFERENCE_DATA>\n"
        + sanitize_source_text("\n\n".join(blocks))
        + "\n</SOURCE_REFERENCE_DATA>"
    )


def stable_hash(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
