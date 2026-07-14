"""LLM-backed Scene fusion drafts with validated manuscript evidence."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.agent_step_harness import ContextBudget, run_managed_structured
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.outline.models import Scene
from modules.outline.repositories import SceneRepository

logger = logging.getLogger(__name__)

MANUSCRIPT_CHARACTER_BUDGET = 24_000
SCENE_CARD_CHARACTER_BUDGET = 6_000
MAX_PROMPT_PAYLOAD_CHARACTERS = 31_000
TRUNCATION_MARKER = "\n\n……[正文证据已按预算截断]……\n\n"
CARD_TRUNCATION_MARKER = "…[字段截断]…"
SEMANTIC_FIELDS = (
    "title",
    "goal",
    "core_conflict",
    "emotional_beat",
    "must_happen",
    "must_not_happen",
    "narrative_tag",
)


class SceneFusionSemanticOutput(BaseModel):
    """Only author-reviewable semantic fields may come from the LLM."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, max_length=255)
    goal: str | None = None
    core_conflict: str | None = None
    emotional_beat: str | None = None
    must_happen: str | None = None
    must_not_happen: str | None = None
    narrative_tag: str | None = Field(None, max_length=32)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=2000)


@dataclass(frozen=True)
class SceneFusionEvidence:
    scene_id: str
    content_mode: str | None
    text: str


@dataclass(frozen=True)
class SceneFusionEvidenceResult:
    items: list[SceneFusionEvidence]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SceneFusionGenerationResult:
    semantic_fields: dict[str, Any]
    confidence: float | None
    reason: str
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False


class SceneFusionEvidenceLoader:
    """Load hash-validated exact Scene text without widening to whole chapters."""

    def __init__(self, *, budget: int = MANUSCRIPT_CHARACTER_BUDGET) -> None:
        self._repo = SceneRepository()
        self._budget = max(0, int(budget))

    async def load(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scenes: list[Scene],
    ) -> SceneFusionEvidenceResult:
        raw_items: list[SceneFusionEvidence] = []
        warnings: list[str] = []
        for scene in scenes:
            item = await self._load_scene(db, novel_id=novel_id, scene=scene)
            raw_items.append(item)
            if not item.text:
                warnings.append(
                    f"Scene「{scene.title or str(scene.id)}」缺少可校验的精确正文映射，"
                    "本次仅使用 Scene 卡字段。"
                )

        texts = [item.text for item in raw_items]
        allocated = _allocate_character_budget(texts, self._budget)
        items: list[SceneFusionEvidence] = []
        truncated = False
        for item, limit in zip(raw_items, allocated, strict=True):
            text = item.text
            if len(text) > limit:
                text = _truncate_middle(text, limit)
                truncated = True
            items.append(
                SceneFusionEvidence(
                    scene_id=item.scene_id,
                    content_mode=item.content_mode,
                    text=text,
                )
            )
        if truncated:
            warnings.append("正文证据已按 24000 字符预算截断。")
        return SceneFusionEvidenceResult(items=items, warnings=warnings)

    async def _load_scene(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene: Scene,
    ) -> SceneFusionEvidence:
        for content_mode in ("working", "canonical"):
            text = await self._load_mode(
                db,
                novel_id=novel_id,
                scene=scene,
                content_mode=content_mode,
            )
            if text:
                return SceneFusionEvidence(
                    scene_id=str(scene.id),
                    content_mode=content_mode,
                    text=text,
                )
        return SceneFusionEvidence(
            scene_id=str(scene.id),
            content_mode=None,
            text="",
        )

    async def _load_mode(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene: Scene,
        content_mode: str,
    ) -> str:
        from modules.writing.facade import (
            build_manuscript_range_ref,
            list_manuscript_sources,
            read_manuscript_range,
        )

        spans = await self._repo.get_scene_spans_for_scene(
            db,
            uuid.UUID(str(novel_id)),
            scene.id,
            content_mode=content_mode,
        )
        precise = sorted(
            (
                span
                for span in spans
                if span.mapping_status in {"exact", "reanchored"}
                and span.source_draft_id is not None
                and span.source_content_hash
                and span.start_offset is not None
                and span.end_offset is not None
                and span.end_offset > span.start_offset
            ),
            key=lambda span: (
                span.chapter_index,
                span.part_no,
                span.start_offset or 0,
                str(span.id),
            ),
        )
        current_sources = await list_manuscript_sources(
            db,
            novel_id,
            sorted({span.chapter_index for span in precise}),
            content_mode=content_mode,
        )
        current_by_chapter = {source.chapter_index: source for source in current_sources}
        excerpts: list[str] = []
        seen_ranges: set[tuple[str, int, int, str]] = set()
        for span in precise:
            current = current_by_chapter.get(span.chapter_index)
            if (
                current is None
                or current.id != str(span.source_draft_id)
                or current.content_hash != span.source_content_hash
            ):
                continue
            range_key = (
                str(span.source_draft_id),
                int(span.start_offset),
                int(span.end_offset),
                str(span.source_content_hash),
            )
            if range_key in seen_ranges:
                continue
            try:
                ref = await build_manuscript_range_ref(
                    db,
                    novel_id,
                    draft_id=str(span.source_draft_id),
                    start_offset=int(span.start_offset),
                    end_offset=int(span.end_offset),
                    content_mode=content_mode,
                )
                if ref.source_hash != span.source_content_hash:
                    continue
                if (
                    ref.draft_id != current.id
                    or ref.version_number != current.version_number
                    or ref.source_hash != current.content_hash
                ):
                    continue
                read = await read_manuscript_range(
                    db,
                    novel_id,
                    ref,
                    before=0,
                    after=0,
                )
            except Exception:
                continue
            seen_ranges.add(range_key)
            excerpts.append(read.text)
        return "\n\n".join(excerpts)


class SceneFusionDraftGenerator:
    """Generate a semantic Scene fusion draft and degrade to deterministic input."""

    def __init__(
        self,
        *,
        llm_client: LLMClient | None = None,
        evidence_loader: SceneFusionEvidenceLoader | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._evidence_loader = evidence_loader or SceneFusionEvidenceLoader()

    @asynccontextmanager
    async def _open_llm_client(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> AsyncIterator[LLMClient]:
        if self._llm_client is not None:
            yield self._llm_client
            return

        from modules.project.facade import open_project_llm_client

        async with open_project_llm_client(
            db,
            novel_id,
            timeout_override=90,
        ) as client:
            yield client

    async def generate(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        sources: list[Scene],
        primary_scene_id: str,
        deterministic_draft: dict[str, Any],
    ) -> SceneFusionGenerationResult:
        evidence = await self._evidence_loader.load(
            db,
            novel_id=novel_id,
            scenes=sources,
        )
        payload, prompt_trimmed = _prompt_payload(
            sources,
            primary_scene_id=primary_scene_id,
            evidence=evidence.items,
        )
        payload_json = json.dumps(payload, ensure_ascii=False)
        generation_warnings = list(evidence.warnings)
        if prompt_trimmed:
            generation_warnings.append("正文证据已按完整 Prompt 输入预算进一步截断。")
        try:
            async with self._open_llm_client(db, novel_id) as client:
                output = await run_managed_structured(
                    client,
                    LLMCallRequest(
                        model=client.model_name,
                        messages=[
                            LLMMessage(
                                role="system",
                                content=(
                                    "你是长篇小说 Scene 结构融合助手。"
                                    "你的任务是综合所有选中 Scene 的结构卡"
                                    "和可用正文证据，"
                                    "生成一个连贯、完整、去重的融合版 Scene。"
                                    "必须公平考虑每个选中 Scene，不得因 role=source "
                                    "而忽略或弱化其有证据支持的重要事件、目标、冲突和约束。"
                                    "primary Scene 只是偏好信号，"
                                    "不是骨架或必须保留的模板："
                                    "仅当多个方案同样有证据支持，或冲突无法同时保留时，"
                                    "才优先延续 primary Scene 的意图、"
                                    "叙事重心和表达取向。"
                                    "合并可兼容信息，消除重复，显式解决矛盾，"
                                    "并在 reason 中说明取舍。"
                                    "不得新增无来源的重大设定，不改写正文，只输出 JSON。"
                                ),
                            ),
                            LLMMessage(
                                role="user",
                                content=(
                                    "payload="
                                    f"{payload_json}\n\n"
                                    "只允许输出 title、goal、core_conflict、"
                                    "emotional_beat、must_happen、must_not_happen、"
                                    "narrative_tag、confidence、reason。"
                                    "confidence 必须在 0 到 1 之间。"
                                    "reason 必须概括如何兼顾所有 Scene，"
                                    "以及遇到冲突时如何使用 primary 偏好做决定。"
                                ),
                            ),
                        ],
                        temperature=0.2,
                        response_format={"type": "json_object"},
                    ),
                    SceneFusionSemanticOutput,
                    step_name="outline.scene_fusion.draft.structured",
                    max_fix_attempts=1,
                    format_repair_attempts=1,
                    timeout=90,
                    context_budget=ContextBudget(max_input_chars=32_000),
                )
            values = output.model_dump(exclude_none=True)
            confidence = float(values.pop("confidence"))
            reason = str(values.pop("reason"))
            return SceneFusionGenerationResult(
                semantic_fields={
                    key: value
                    for key, value in values.items()
                    if key in SEMANTIC_FIELDS and value not in (None, "")
                },
                confidence=confidence,
                reason=reason,
                warnings=generation_warnings,
            )
        except Exception as exc:
            logger.warning("Scene fusion LLM failed: %s", type(exc).__name__)
            return SceneFusionGenerationResult(
                semantic_fields={
                    key: deterministic_draft.get(key)
                    for key in SEMANTIC_FIELDS
                    if deterministic_draft.get(key) not in (None, "")
                },
                confidence=None,
                reason="AI 调用未完成，当前结果由确定性融合规则生成。",
                warnings=[
                    *generation_warnings,
                    "AI 融合调用失败，已返回确定性融合草稿，请人工复核。",
                ],
                degraded=True,
            )


def _prompt_payload(
    scenes: list[Scene],
    *,
    primary_scene_id: str,
    evidence: list[SceneFusionEvidence],
) -> tuple[dict[str, Any], bool]:
    evidence_by_scene = {item.scene_id: item for item in evidence}
    card_values = [
        str(getattr(scene, field) or "") for scene in scenes for field in SEMANTIC_FIELDS
    ]
    clipped_card_values = _clip_values_to_budget(
        card_values,
        SCENE_CARD_CHARACTER_BUDGET,
    )
    value_index = 0
    scene_payloads: list[dict[str, Any]] = []
    for scene in scenes:
        semantic_payload: dict[str, str | None] = {}
        for field_name in SEMANTIC_FIELDS:
            original = getattr(scene, field_name)
            clipped = clipped_card_values[value_index]
            value_index += 1
            semantic_payload[field_name] = clipped if original not in (None, "") else None
        item = evidence_by_scene.get(
            str(scene.id),
            SceneFusionEvidence(str(scene.id), None, ""),
        )
        scene_payloads.append(
            {
                "scene_id": str(scene.id),
                "role": ("primary" if str(scene.id) == primary_scene_id else "source"),
                **semantic_payload,
                "chapter_ids": list(scene.chapter_ids or []),
                "manuscript": item.text,
                "manuscript_mode": item.content_mode,
            }
        )
    payload = {
        "primary_scene_id": primary_scene_id,
        "scenes": scene_payloads,
    }
    return _shrink_manuscript_to_payload_budget(
        payload,
        MAX_PROMPT_PAYLOAD_CHARACTERS,
    )


def _clip_values_to_budget(values: list[str], budget: int) -> list[str]:
    non_empty_count = sum(bool(value) for value in values)
    if non_empty_count == 0 or budget <= 0:
        return ["" for _ in values]
    per_value = max(1, budget // non_empty_count)
    return [
        _truncate_middle(value, per_value, marker=CARD_TRUNCATION_MARKER) if value else ""
        for value in values
    ]


def _shrink_manuscript_to_payload_budget(
    payload: dict[str, Any],
    budget: int,
) -> tuple[dict[str, Any], bool]:
    trimmed = False
    while len(json.dumps(payload, ensure_ascii=False)) > budget:
        scenes = list(payload.get("scenes") or [])
        candidates = [scene for scene in scenes if scene.get("manuscript")]
        if not candidates:
            raise ValueError("Scene fusion card payload exceeds the input budget")
        target = max(candidates, key=lambda scene: len(str(scene["manuscript"])))
        overflow = len(json.dumps(payload, ensure_ascii=False)) - budget
        current = str(target["manuscript"])
        target["manuscript"] = _truncate_middle(
            current,
            max(0, len(current) - overflow - 32),
        )
        trimmed = True
    return payload, trimmed


def _allocate_character_budget(texts: list[str], budget: int) -> list[int]:
    if not texts or budget <= 0:
        return [0 for _ in texts]
    share = budget // len(texts)
    allocations = [min(len(value), share) for value in texts]
    remaining = budget - sum(allocations)
    for index, value in enumerate(texts):
        if remaining <= 0:
            break
        extra = min(max(0, len(value) - allocations[index]), remaining)
        allocations[index] += extra
        remaining -= extra
    return allocations


def _truncate_middle(
    value: str,
    limit: int,
    *,
    marker: str = TRUNCATION_MARKER,
) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    if limit <= len(marker):
        return value[:limit]
    available = limit - len(marker)
    head = (available + 1) // 2
    tail = available - head
    suffix = value[-tail:] if tail else ""
    return f"{value[:head]}{marker}{suffix}"
