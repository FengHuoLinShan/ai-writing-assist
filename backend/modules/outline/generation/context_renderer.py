"""Pure Markdown rendering helpers for outline generation context."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

_DEFAULT_DYNAMIC_TEXT_LIMIT = 4000
_CHAPTER_TEXT_LIMIT = 12000
_RAG_CHUNK_TEXT_LIMIT = 2400
_SHORT_DYNAMIC_TEXT_LIMIT = 800
_SCENE_SUMMARY_TEXT_LIMIT = 1200

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_previous_instructions",
        re.compile(
            r"\b(?:ignore|disregard)\s+(?:all\s+)?(?:previous|prior|above)\s+"
            r"instructions?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt",
        re.compile(r"\b(?:system\s+prompt|system\s+message)\b", re.IGNORECASE),
    ),
    (
        "developer_message",
        re.compile(
            r"\bdeveloper\s+(?:message|instruction|instructions)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ignore_above_instructions_zh",
        re.compile(r"忽略(?:以上|上述|之前|前面).{0,12}(?:指令|说明|规则)"),
    ),
    ("system_prompt_zh", re.compile(r"(?:系统提示词|系统消息|系统指令)")),
    ("developer_message_zh", re.compile(r"(?:开发者消息|开发者指令)")),
)


@dataclass
class _PromptTextGuard:
    """Wrap dynamic prompt text and record hygiene warnings."""

    warnings: list[str]
    _counter: int = 0

    def block(
        self,
        label: str,
        value: Any,
        *,
        max_chars: int = _DEFAULT_DYNAMIC_TEXT_LIMIT,
    ) -> str:
        text = self._stringify(value)
        for pattern_name, pattern in _INJECTION_PATTERNS:
            if pattern.search(text):
                self._append_warning(
                    f"动态文本可能包含 prompt injection 模式：{label} / {pattern_name}"
                )
        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars].rstrip()
            truncated = True
            self._append_warning(f"动态文本已截断：{label} 超过 {max_chars} 字符")

        self._counter += 1
        boundary_id = self._boundary_id(label, text, self._counter)
        return (
            "[[[AIAWA_DYNAMIC_TEXT_START "
            f"label={label} id={boundary_id} chars={len(text)} "
            f"truncated={str(truncated).lower()}]]]\n"
            f"{text}\n"
            f"[[[AIAWA_DYNAMIC_TEXT_END id={boundary_id}]]]"
        )

    def _append_warning(self, warning: str) -> None:
        if warning not in self.warnings:
            self.warnings.append(warning)

    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict | list | tuple):
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        return str(value).strip()

    @staticmethod
    def _boundary_id(label: str, text: str, counter: int) -> str:
        safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "-", label).strip("-") or "text"
        digest = hashlib.sha256(f"{safe_label}\0{text}".encode()).hexdigest()
        return f"{safe_label}-{counter}-{digest[:12]}"


def render_bundle_to_markdown(
    bundle: object,
    *,
    guard: _PromptTextGuard | None = None,
) -> str:
    """Render a StructureContextBundle-like object into guarded Markdown."""
    guard = guard or _PromptTextGuard(warnings=[])
    context_md = ""
    if bundle.project:
        context_md += "## 项目\n" f"{guard.block('project', bundle.project)}\n\n"
    if bundle.world_entities:
        context_md += "## 世界对象\n"
        for entity in bundle.world_entities:
            entity_text = {
                "name": entity.get("name", "?"),
                "entity_type": entity.get("entity_type", "?"),
                "summary": entity.get("summary", ""),
            }
            context_md += "- 世界对象：\n" f"{guard.block('world_entity', entity_text)}\n"
    if bundle.characters:
        context_md += "\n## 人物\n"
        for character in bundle.characters:
            character_text = {
                "name": character.get("name", "?"),
                "role": character.get("role", "?"),
                "desire": character.get("desire", ""),
            }
            context_md += "- 人物：\n" f"{guard.block('character', character_text)}\n"
    if bundle.rag_chunks:
        context_md += "\n## RAG 检索证据\n"
        for chunk in bundle.rag_chunks:
            if isinstance(chunk, dict):
                chunk_text = {
                    "source_type": chunk.get("source_type", "?"),
                    "chapter_index": chunk.get("chapter_index"),
                    "text": chunk.get("text", ""),
                }
            else:
                chunk_text = chunk
            wrapped_chunk = guard.block(
                "rag_chunk",
                chunk_text,
                max_chars=_RAG_CHUNK_TEXT_LIMIT,
            )
            context_md += "- RAG 片段：\n" f"{wrapped_chunk}\n"
    if bundle.warnings:
        context_md += render_warnings_to_markdown(
            "上下文警告",
            bundle.warnings,
            guard,
        )
    return context_md


def render_warnings_to_markdown(
    title: str,
    warnings: list[str],
    guard: _PromptTextGuard,
) -> str:
    context_md = f"\n## {title}\n"
    for warning in warnings:
        wrapped_warning = guard.block(
            "context_warning",
            warning,
            max_chars=_SHORT_DYNAMIC_TEXT_LIMIT,
        )
        context_md += "- 警告：\n" f"{wrapped_warning}\n"
    return context_md


def render_chapter_text_sections(
    chapter_texts: list[tuple[int, str]],
    *,
    guard: _PromptTextGuard,
) -> str:
    """Render chapter source text sections, preserving truncation semantics."""
    if not chapter_texts:
        return ""

    context_md = "\n## 章节原文\n"
    for chapter_index, raw_text in chapter_texts:
        is_truncated = len(raw_text) > _CHAPTER_TEXT_LIMIT
        prompt_text = raw_text[:_CHAPTER_TEXT_LIMIT]
        wrapped = guard.block(
            "chapter_original_text",
            prompt_text,
            max_chars=_CHAPTER_TEXT_LIMIT,
        )
        context_md += f"\n### 第{chapter_index}章\n{wrapped}\n"
        if is_truncated:
            context_md += "\n（本章内容已截断）\n"
    return context_md


def render_scene_summary_line(
    scene: object,
    chapter_indices: list[int],
    *,
    guard: _PromptTextGuard,
) -> str:
    scene_id = getattr(scene, "id", None)
    scene_index = getattr(scene, "scene_index", 0)
    chapter_label = (
        f"第{min(chapter_indices)}-{max(chapter_indices)}章"
        if chapter_indices
        else "章节未知"
    )
    summary_parts = [
        getattr(scene, "goal", None),
        getattr(scene, "core_conflict", None),
        getattr(scene, "emotional_beat", None),
    ]
    summary = "；".join(str(part).strip() for part in summary_parts if part)
    scene_label = (
        f"{scene_id} / S{scene_index}" if scene_id is not None else f"S{scene_index}"
    )
    summary_text = (
        f"{scene_label} {chapter_label}"
        f"《{getattr(scene, 'title', None) or '未命名'}》"
        f"：{summary}"
    )
    wrapped_summary = guard.block(
        "existing_scene_summary",
        summary_text,
        max_chars=_SCENE_SUMMARY_TEXT_LIMIT,
    )
    return "- Scene 摘要：\n" f"{wrapped_summary}"


def render_scene_summary_card(scene: object, chapter_indices: list[int]) -> dict:
    scene_id = getattr(scene, "id", None)
    scene_index = getattr(scene, "scene_index", 0)
    return {
        "scene_id": str(scene_id or scene_index),
        "scene_index": scene_index,
        "title": getattr(scene, "title", None) or "",
        "goal": getattr(scene, "goal", None) or "",
        "core_conflict": getattr(scene, "core_conflict", None) or "",
        "emotional_beat": getattr(scene, "emotional_beat", None) or "",
        "must_happen": getattr(scene, "must_happen", None) or "",
        "must_not_happen": getattr(scene, "must_not_happen", None) or "",
        "narrative_tag": getattr(scene, "narrative_tag", None) or "",
        "start_chapter": min(chapter_indices) if chapter_indices else None,
        "end_chapter": max(chapter_indices) if chapter_indices else None,
    }
