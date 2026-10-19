"""Bounded, redacted display text for goal-run domain receipts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


def _safe_receipt_text(value: Any, *, limit: int = 320) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    text = re.sub(
        r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|密钥|令牌)\s*[:=]\s*)\S+",
        r"\1[已隐藏]",
        text,
    )
    text = re.sub(r"(?i)\b(?:sk|rk|pk)[_-][A-Za-z0-9_-]{16,}\b", "[已隐藏凭据]", text)
    text = re.sub(r"\bAIza[A-Za-z0-9_-]{24,}\b", "[已隐藏凭据]", text)
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [已隐藏凭据]", text)
    text = re.sub(
        r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        "[已隐藏标识]",
        text,
    )
    text = re.sub(r"(?i)\b[0-9a-f]{32,}\b", "[已隐藏标识]", text)
    return text[:limit]


def _receipt_preview_details(
    operation_id: str, receipt: Mapping[str, Any]
) -> tuple[str, list[str]]:
    details: list[str] = []
    if operation_id in {"writing.generate_candidate", "writing.targeted_revision"}:
        candidate = receipt.get("candidate")
        candidate = candidate if isinstance(candidate, Mapping) else {}
        title = _safe_receipt_text(candidate.get("title"), limit=180)
        chapter_index = candidate.get("chapter_index")
        if type(chapter_index) is int and chapter_index > 0:
            summary = f"第 {chapter_index} 章的正文候选已生成"
            if title:
                summary += f"：《{title}》"
        else:
            summary = "正文候选已生成"
            if title:
                summary += f"：《{title}》"
        details.append("候选仍需在写作工作台审阅；生成完成不代表已采用。")
        return summary[:500], details

    if operation_id == "project.scan_duplicates":
        summary = _safe_receipt_text(receipt.get("summary"), limit=360)
        scanned_counts = receipt.get("scanned_counts")
        if isinstance(scanned_counts, Mapping):
            total = sum(
                value
                for value in scanned_counts.values()
                if type(value) is int and 0 <= value <= 10_000_000
            )
            if total:
                details.append(f"本次扫描了 {total} 项资料。")
        group_count = receipt.get("group_count")
        if type(group_count) is int and 0 <= group_count <= 10_000_000:
            details.append(f"形成 {group_count} 组相似建议。")
        return (summary or "相似资料扫描已完成。"), details[:8]

    preview = receipt.get("preview")
    preview = preview if isinstance(preview, Mapping) else {}
    if operation_id == "story.character_card.generate":
        content = preview.get("content")
        content = content if isinstance(content, Mapping) else {}
        interpretations = content.get("interpretations")
        interpretations = interpretations if isinstance(interpretations, list) else []
        for item in interpretations[:6]:
            if not isinstance(item, Mapping):
                continue
            category = _safe_receipt_text(item.get("category"), limit=60)
            statement = _safe_receipt_text(item.get("statement"), limit=260)
            if statement:
                details.append(f"{f'{category}：' if category else ''}{statement}")
        warnings = preview.get("warnings")
        if isinstance(warnings, list):
            details.extend(
                f"提示：{value}"
                for item in warnings[:2]
                if (value := _safe_receipt_text(item, limit=260))
            )
        return (
            f"人物卡预览已生成，包含 {len(interpretations)} 条解释建议；尚未写入正史。",
            details[:8],
        )

    if operation_id == "story.reaction.generate":
        proposals = preview.get("proposals")
        proposals = proposals if isinstance(proposals, list) else []
        for index, proposal in enumerate(proposals[:4], start=1):
            if not isinstance(proposal, Mapping):
                continue
            performances = proposal.get("performances")
            if isinstance(performances, list):
                for performance in performances[:2]:
                    if not isinstance(performance, Mapping):
                        continue
                    motivation = _safe_receipt_text(
                        performance.get("motivation"), limit=90
                    )
                    action = _safe_receipt_text(performance.get("action"), limit=220)
                    if action:
                        prefix = f"第 {index} 组反应"
                        details.append(
                            f"{prefix}{f' · {motivation}' if motivation else ''}："
                            f"{action}"
                        )
            else:
                for key, label in (
                    ("goal", "目标"),
                    ("immediate_reaction", "即时反应"),
                    ("intended_action", "行动"),
                    ("internal_pressure", "内在压力"),
                ):
                    value = _safe_receipt_text(proposal.get(key), limit=220)
                    if value:
                        details.append(f"第 {index} 组反应 · {label}：{value}")
        return (
            f"人物反应预览已生成，包含 {len(proposals)} 组候选；尚未写入正史。",
            details[:8],
        )

    if operation_id in {
        "story.exploration.start",
        "story.exploration.detail",
        "story.exploration.revise",
    }:
        scale_labels = {
            "story.exploration.sandbox": "沙盘",
            "story.exploration.event": "事件",
            "story.exploration.scene_line": "场景一句对白",
            "story.exploration.full_rehearsal": "场景完整排演",
        }
        kind = str(receipt.get("output_kind") or "")
        payload = receipt.get("payload")
        payload = payload if isinstance(payload, Mapping) else {}
        label = scale_labels.get(kind, kind or "未知形态")
        summary = f"独立探索结果已生成（{label}）；只进探索历史，不写正史。"
        details: list[str] = []
        if kind == "story.exploration.sandbox":
            chain = payload.get("influence_chain")
            if isinstance(chain, list):
                details.append(f"影响链共 {min(len(chain), 12)} 个环节。")
            unknowns = payload.get("unknowns")
            if isinstance(unknowns, list) and unknowns:
                first = _safe_receipt_text(unknowns[0], limit=220)
                if first:
                    details.append(f"未知：{first}")
        elif kind == "story.exploration.event":
            gaps = payload.get("gaps")
            if isinstance(gaps, list):
                details.append(f"诊断缺口共 {min(len(gaps), 12)} 项。")
            bridges = payload.get("bridge_candidates")
            if isinstance(bridges, list) and bridges:
                first_bridge = bridges[0]
                first_bridge = first_bridge if isinstance(first_bridge, Mapping) else {}
                action = _safe_receipt_text(
                    str(first_bridge.get("action") or ""), limit=220
                )
                if action:
                    details.append(f"补桥行动：{action}")
        elif kind == "story.exploration.scene_line":
            text = _safe_receipt_text(payload.get("line"), limit=220)
            if text:
                details.append(f"对白：{text}")
            variants = payload.get("variants")
            if isinstance(variants, list) and variants:
                details.append(f"多目标共 {min(len(variants), 12)} 个变体。")
        elif kind == "story.exploration.full_rehearsal":
            rounds = payload.get("rounds")
            if isinstance(rounds, list):
                details.append(f"完整排演共 {min(len(rounds), 12)} 轮。")
        if receipt.get("result_id"):
            details.append("结果已保存到探索历史，可在原工作台继续编辑或比较。")
        return summary, details[:8]

    return "原领域回执已完成。", details
