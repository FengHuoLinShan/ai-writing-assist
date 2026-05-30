"""EntityExtractionService — LLM 抽取管线"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import EntityCandidateRepository, CoreEntityRepository
from modules.world.schemas import EntityCandidateCreate
from modules.world.services.dedup_service import EntityDedupService
from modules.world.services.draft_provider import DraftProvider, WritingDraftProvider
from modules.world.services.helpers import parse_uuid


class ExtractionResult:
    """抽取结果统计"""
    total_chapters: int
    total_created: int
    total_skipped: int
    items: list[dict[str, Any]]

    def __init__(
        self,
        *,
        total_chapters: int = 0,
        total_created: int = 0,
        total_skipped: int = 0,
        items: list[dict[str, Any]] | None = None,
    ) -> None:
        self.total_chapters = total_chapters
        self.total_created = total_created
        self.total_skipped = total_skipped
        self.items = items or []


class EntityExtractionService:
    """从章节正文中抽取世界对象候选

    流程：
    WritingDraft chapters → batch group(5章/批) → LLM extract →
    dedup → EntityCandidate
    """

    def __init__(self, draft_provider: DraftProvider | None = None) -> None:
        self._entity_repo = CoreEntityRepository()
        self._candidate_repo = EntityCandidateRepository()
        self._dedup_service = EntityDedupService()
        self._draft_provider = draft_provider or WritingDraftProvider()

    async def extract_entities_from_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        batch_size: int = 5,
    ) -> ExtractionResult:
        """从指定章节范围抽取世界对象候选"""
        nid = parse_uuid(novel_id, "novel_id")

        # 1. 读取已有正史对象作为 context
        all_entities, _ = await self._entity_repo.get_by_novel(db, nid, limit=500)
        existing_context = "\n".join(
            f"- {e.name} ({e.entity_type})"
            for e in all_entities if e.status in ("canonical", "draft")
        ) or "无已有对象"

        # 2. 分批读取 WritingDraft
        chapters = await self._load_chapters(db, novel_id, start_chapter, end_chapter)
        if not chapters:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"未找到章节 {start_chapter}-{end_chapter} 的正文",
            )

        # 3. 分批调用 LLM
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.schemas import LLMCallRequest

        llm = LLMClient()
        total_created = 0
        total_skipped = 0
        created_items: list[dict[str, Any]] = []
        batches = [chapters[i:i + batch_size] for i in range(0, len(chapters), batch_size)]

        for batch_idx, batch in enumerate(batches):
            batch_text = "\n\n".join(
                f"--- 第{c['chapter_index']}章: {c['title']} ---\n{c['content']}"
                for c in batch
            )

            from infrastructure.llm.prompt_loader import load_prompt

            system_prompt = load_prompt("structure_extraction",
                existing_entities_context=existing_context,
            )

            from core.config import get_settings
            _settings = get_settings()
            request = LLMCallRequest(
                model=_settings.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": batch_text},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            try:
                from pydantic import BaseModel

                class _ExtractedEntity(BaseModel):
                    name: str
                    entity_type: str
                    summary: str
                    public_info: str
                    hidden_truth: str
                    importance: float
                    suggested_action: str
                    suggested_existing_entity_name: str | None = None
                    candidate_reason: str
                    confidence: float
                    source_chapter: int | None = None

                class _ExtractionOutput(BaseModel):
                    entities: list[_ExtractedEntity]

                result = await llm.generate_structured(request, _ExtractionOutput)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "LLM extraction failed for batch %d: %s", batch_idx, exc,
                )
                continue

            # 4. 对每个结果：去重 + 创建候选
            for extracted in result.entities:
                if not extracted.name or not extracted.name.strip():
                    total_skipped += 1
                    continue

                suggestions = await self._dedup_service.find_similar_entities(
                    db, novel_id, extracted.name,
                    entity_type=extracted.entity_type,
                )

                high_confidence = [s for s in suggestions if s.similarity_score >= 0.88]
                if high_confidence:
                    total_skipped += 1
                    continue

                src_ch = extracted.source_chapter or batch[0]["chapter_index"]

                candidate_data = EntityCandidateCreate(
                    name=extracted.name.strip(),
                    entity_type=extracted.entity_type,
                    summary=extracted.summary[:2000] if extracted.summary else None,
                    source_text=extracted.summary[:500] or None,
                    source_chapter_index=src_ch,
                    importance_score=min(max(extracted.importance, 0.0), 1.0),
                    confidence=min(max(extracted.confidence, 0.0), 1.0),
                    candidate_reason=extracted.candidate_reason[:500] if extracted.candidate_reason else None,
                    suggested_action=extracted.suggested_action,
                    suggested_existing_entity_id=(
                        suggestions[0].existing_entity_id if suggestions else None
                    ),
                )
                try:
                    candidate = await self._candidate_repo.create(db, nid, candidate_data)
                    total_created += 1
                    created_items.append({
                        "candidate_id": str(candidate.id),
                        "name": candidate.name,
                        "entity_type": candidate.entity_type,
                        "suggested_action": candidate.suggested_action,
                    })
                except ValueError:
                    total_skipped += 1

        await db.flush()
        return ExtractionResult(
            total_chapters=len(chapters),
            total_created=total_created,
            total_skipped=total_skipped,
            items=created_items,
        )

    async def _load_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> list[dict[str, Any]]:
        """通过 DraftProvider 读取指定范围的 WritingDraft"""
        return await self._draft_provider.load_chapters(
            db, novel_id, start_chapter, end_chapter,
        )
