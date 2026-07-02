from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.outline.models import Scene
from modules.outline.repositories import SceneRepository
from modules.rag import facade as rag_facade
from modules.writing.facade import get_latest_draft_for_chapter
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)

SNIPPET_LIMIT = 900


class CrossChapterDecision(BaseModel):
    action: Literal["extend_scene", "keep_separate", "needs_review"] = "needs_review"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = ""


class CrossChapterDetectionService:
    """Find candidate multi-chapter scenes without mutating Scene rows."""

    def __init__(
        self,
        *,
        scene_repo: SceneRepository | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._scene_repo = scene_repo or SceneRepository()
        self._llm_client = llm_client

    async def detect(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
        max_chapter_span: int = 6,
        max_suggestions: int = 30,
        max_chain_calls: int = 6,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        scenes = await self._load_scenes(
            db,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        suggestions: list[dict[str, Any]] = []
        traces: list[dict[str, Any]] = []
        skipped_sources: set[str] = set()
        total_pairs = max(0, len(scenes) - 1)

        for index, scene in enumerate(scenes[:-1]):
            if len(suggestions) >= max_suggestions:
                break
            scene_id = str(scene.id)
            if scene_id in skipped_sources:
                continue
            chain = [scene]
            chain_trace: list[dict[str, Any]] = []
            stop_reason = "no_next_scene"
            calls = 0

            for next_scene in scenes[index + 1 :]:
                if calls >= max_chain_calls:
                    stop_reason = "max_window_reached"
                    break
                if _chapter_span(chain + [next_scene]) > max_chapter_span:
                    stop_reason = "max_window_reached"
                    break

                evidence, degraded_reason = await self._evidence_for_boundary(
                    db,
                    novel_id,
                    chain,
                    next_scene,
                )
                decision = await self._decide_boundary(
                    novel_id=novel_id,
                    chain=chain,
                    next_scene=next_scene,
                    evidence=evidence,
                )
                calls += 1
                step = {
                    "from_scene_id": str(chain[-1].id),
                    "next_scene_id": str(next_scene.id),
                    "action": decision.action,
                    "confidence": decision.confidence,
                    "reason": decision.reason[:300],
                    "degraded_reason": degraded_reason,
                }
                chain_trace.append(step)

                if decision.action != "extend_scene":
                    stop_reason = decision.action
                    break
                chain.append(next_scene)
                stop_reason = "extended_to_end"

            if len(chain) > 1:
                needs_review = stop_reason == "max_window_reached" or any(
                    step["action"] == "needs_review" for step in chain_trace
                )
                suggestion = self._build_suggestion(
                    chain,
                    chain_trace=chain_trace,
                    stop_reason=stop_reason,
                    needs_review=needs_review,
                )
                suggestions.append(suggestion)
                skipped_sources.update(suggestion["source_scene_ids"][1:])
            traces.append(
                {
                    "start_scene_id": scene_id,
                    "source_scene_ids": [str(item.id) for item in chain],
                    "stop_reason": stop_reason,
                    "steps": chain_trace,
                }
            )
            if progress_callback is not None and total_pairs:
                progress_callback(min(0.95, (index + 1) / total_pairs))

        return {
            "test_mode": "service",
            "task_type": "scene_cross_chapter_detection",
            "novel_id": novel_id,
            "total_scenes_scanned": len(scenes),
            "suggestion_count": len(suggestions),
            "suggestions": suggestions,
            "scan_trace": traces,
            "warnings": [],
            "summary": f"识别到 {len(suggestions)} 条跨章 Scene 建议",
        }

    async def _load_scenes(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        start_chapter: int | None,
        end_chapter: int | None,
    ) -> list[Scene]:
        nid = parse_uuid(novel_id, "novel_id")
        scenes = await self._scene_repo.get_by_novel_ordered(db, nid, limit=None)
        result: list[Scene] = []
        for scene in scenes:
            chapters = _scene_chapters(scene)
            if not chapters:
                continue
            if start_chapter is not None and max(chapters) < start_chapter:
                continue
            if end_chapter is not None and min(chapters) > end_chapter:
                continue
            result.append(scene)
        return result

    async def _evidence_for_boundary(
        self,
        db: AsyncSession,
        novel_id: str,
        chain: list[Scene],
        next_scene: Scene,
    ) -> tuple[list[dict[str, Any]], str | None]:
        chapters = sorted({*_scene_chapters(chain[-1]), *_scene_chapters(next_scene)})
        query = " ".join(
            filter(
                None,
                [
                    chain[-1].title,
                    chain[-1].goal,
                    next_scene.title,
                    next_scene.goal,
                ],
            )
        )[:500]
        evidence: list[dict[str, Any]] = []
        try:
            bundle = await rag_facade.retrieve(
                db,
                novel_id,
                query or "跨章 Scene 边界",
                top_k=6,
                reference_chapter_index=chapters[0] if chapters else None,
            )
            for chunk in bundle.chunks[:6]:
                evidence.append(
                    {
                        "source_type": "rag",
                        "rag_chunk_id": chunk.id,
                        "scene_id": chunk.scene_id,
                        "chapter_index": chunk.chapter_index,
                        "chunk_index": chunk.chunk_index,
                        "snippet": _clip(chunk.text),
                    }
                )
            if evidence:
                return evidence, "rag_degraded" if bundle.degraded else None
        except Exception:
            logger.info(
                "RAG evidence unavailable for cross-chapter detection",
                exc_info=True,
            )

        for chapter in chapters[:3]:
            draft = await get_latest_draft_for_chapter(db, novel_id, chapter)
            if draft is None:
                continue
            evidence.append(
                {
                    "source_type": "latest_draft",
                    "chapter_index": chapter,
                    "snippet": _clip(draft.content),
                }
            )
        return evidence, "draft_fallback"

    async def _decide_boundary(
        self,
        *,
        novel_id: str,
        chain: list[Scene],
        next_scene: Scene,
        evidence: list[dict[str, Any]],
    ) -> CrossChapterDecision:
        client = self._llm_client or LLMClient()
        settings = get_settings()
        payload = {
            "novel_id": novel_id,
            "current_scene": _scene_summary(chain),
            "next_scene": _scene_summary([next_scene]),
            "evidence": evidence[:8],
        }
        try:
            return await client.generate_structured(
                LLMCallRequest(
                    model=settings.llm_model,
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "你判断长篇小说相邻章节片段是否仍属于同一个 Scene。"
                                "只输出 JSON：action 为 extend_scene、keep_separate "
                                "或 needs_review；不要改写正文。"
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=json.dumps(payload, ensure_ascii=False),
                        ),
                    ],
                    temperature=0.1,
                    max_tokens=512,
                    response_format={"type": "json_object"},
                ),
                CrossChapterDecision,
                max_fix_attempts=1,
            )
        except Exception as exc:
            logger.warning("Cross-chapter LLM decision failed: %s", exc)
            return CrossChapterDecision(
                action="needs_review",
                confidence=0.0,
                reason="LLM decision failed; manual review required.",
            )

    def _build_suggestion(
        self,
        chain: list[Scene],
        *,
        chain_trace: list[dict[str, Any]],
        stop_reason: str,
        needs_review: bool,
    ) -> dict[str, Any]:
        chapters = sorted(
            {chapter for scene in chain for chapter in _scene_chapters(scene)}
        )
        source_ids = [str(scene.id) for scene in chain]
        proposed_scene = {
            "title": f"跨章融合：{chain[0].title or 'Scene'}",
            "goal": _join_unique(getattr(scene, "goal", None) for scene in chain),
            "core_conflict": _join_unique(
                getattr(scene, "core_conflict", None) for scene in chain
            ),
            "emotional_beat": _join_unique(
                getattr(scene, "emotional_beat", None) for scene in chain
            ),
            "must_happen": _join_unique(
                getattr(scene, "must_happen", None) for scene in chain
            ),
            "must_not_happen": _join_unique(
                getattr(scene, "must_not_happen", None) for scene in chain
            ),
            "chapter_ids": [str(chapter) for chapter in chapters],
            "scene_chunks": _merge_chunks(chain),
            "source": "manual_fusion",
            "status": "draft",
            "structure_meta": {
                "fusion_kind": "cross_chapter_llm_detection",
                "fused_from_scene_ids": source_ids,
                "scan_trace": chain_trace,
                "needs_review": True,
                "stop_reason": stop_reason,
            },
        }
        confidence_values = [
            float(step.get("confidence") or 0.0)
            for step in chain_trace
            if step.get("action") == "extend_scene"
        ]
        confidence = min(confidence_values) if confidence_values else 0.5
        return {
            "source_scene_ids": source_ids,
            "chapter_span": [chapters[0], chapters[-1]] if chapters else [],
            "proposed_scene": proposed_scene,
            "confidence": round(confidence, 3),
            "reason": "；".join(step.get("reason") or "" for step in chain_trace)[:500],
            "evidence_anchors": [
                {
                    "source_scene_id": step["from_scene_id"],
                    "next_scene_id": step["next_scene_id"],
                }
                for step in chain_trace
            ],
            "scan_trace": chain_trace,
            "stop_reason": stop_reason,
            "needs_review": needs_review,
        }


def _scene_chapters(scene: Scene) -> list[int]:
    chapters: set[int] = set()
    for chapter_id in scene.chapter_ids or []:
        if str(chapter_id).isdigit():
            chapters.add(int(chapter_id))
    for chunk in scene.scene_chunks or []:
        raw = chunk.get("chapter_index") or chunk.get("chapter_id")
        if raw is not None and str(raw).isdigit():
            chapters.add(int(raw))
    return sorted(chapters)


def _chapter_span(scenes: list[Scene]) -> int:
    chapters = sorted({chapter for scene in scenes for chapter in _scene_chapters(scene)})
    if not chapters:
        return 0
    return chapters[-1] - chapters[0] + 1


def _scene_summary(scenes: list[Scene]) -> dict[str, Any]:
    chapters = sorted({chapter for scene in scenes for chapter in _scene_chapters(scene)})
    return {
        "scene_ids": [str(scene.id) for scene in scenes],
        "titles": [scene.title for scene in scenes if scene.title],
        "goals": [scene.goal for scene in scenes if scene.goal],
        "chapter_ids": [str(chapter) for chapter in chapters],
    }


def _clip(value: str | None, limit: int = SNIPPET_LIMIT) -> str:
    text = (value or "").strip()
    return text[:limit]


def _join_unique(values: Any) -> str | None:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return "\n\n".join(result) if result else None


def _merge_chunks(scenes: list[Scene]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scene in scenes:
        for chunk in scene.scene_chunks or []:
            copied = dict(chunk)
            key = json.dumps(copied, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                chunks.append(copied)
        if not scene.scene_chunks:
            for chapter in _scene_chapters(scene):
                chunk = {
                    "chapter_index": chapter,
                    "start_paragraph": 0,
                    "end_paragraph": None,
                }
                key = json.dumps(chunk, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    chunks.append(chunk)
    return sorted(
        chunks,
        key=lambda item: int(item.get("chapter_index") or item.get("chapter_id") or 0),
    )
