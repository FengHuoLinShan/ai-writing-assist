"""EntityExtractionService — LLM 抽取管线（单章顺序模式）"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import CoreEntityCreate
from modules.world.services.dedup_service import EntityDedupService
from modules.world.services.draft_provider import DraftProvider, WritingDraftProvider
from modules.world.services.helpers import parse_uuid
from shared.constants import SIMILARITY_HIGH_CONFIDENCE

logger = logging.getLogger(__name__)


class ExtractionResult:
    """抽取结果统计"""
    total_chapters: int
    total_created: int
    total_skipped: int
    failed_chapters: list[int]
    items: list[dict[str, Any]]

    def __init__(
        self,
        *,
        total_chapters: int = 0,
        total_created: int = 0,
        total_skipped: int = 0,
        failed_chapters: list[int] | None = None,
        items: list[dict[str, Any]] | None = None,
    ) -> None:
        self.total_chapters = total_chapters
        self.total_created = total_created
        self.total_skipped = total_skipped
        self.failed_chapters = failed_chapters or []
        self.items = items or []


class EntityExtractionService:
    """从章节正文中抽取世界对象

    流程（单章顺序模式）：
    WritingDraft chapters → for each chapter sequentially →
    LLM extract(3 retries) → 3-layer dedup → persist →
    update existing_context → next chapter
    """

    def __init__(self, draft_provider: DraftProvider | None = None) -> None:
        self._entity_repo = CoreEntityRepository()
        self._candidate_repo = CoreEntityRepository()
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
        """从指定章节范围抽取世界对象候选（单章顺序模式）

        每章独立 LLM 调用，3 次重试，上下文逐步累积。
        batch_size 参数保留以兼容调用方 API，实际忽略。
        """
        nid = parse_uuid(novel_id, "novel_id")

        # 1. 读取已有正史对象作为初始 context（过滤过期临时实体）
        from modules.world.facade import get_world_context

        ctx = await get_world_context(
            db, novel_id, reveal_mode="author_safe", limit=500,
            current_chapter=start_chapter,
        )
        existing_context = "\n".join(
            f"- {e.name} ({e.entity_type})"
            for e in ctx.entities if e.status in ("canonical", "draft")
        ) or "无已有对象"

        # 2. 单章读取 WritingDraft
        chapters = await self._load_chapters(db, novel_id, start_chapter, end_chapter)
        if not chapters:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"未找到章节 {start_chapter}-{end_chapter} 的正文",
            )

        # 3. 单章顺序抽取
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.errors import LLMInvalidResponseError
        from infrastructure.llm.prompt_loader import load_prompt
        from infrastructure.llm.schemas import LLMCallRequest
        from pydantic import BaseModel

        llm = LLMClient()
        total_created = 0
        total_skipped = 0
        created_items: list[dict[str, Any]] = []
        failed_chapters: list[int] = []
        run_batch_id = str(uuid.uuid4())

        # 定义 Pydantic schema（内联以保持模块级命名空间干净）
        _Action = Literal["create_new", "link_to_existing", "ignore", "temporary_only"]

        class _ExtractedEntity(BaseModel):
            name: str
            entity_type: str
            summary: str
            public_info: str
            hidden_truth: str
            importance: float
            suggested_action: _Action
            suggested_existing_entity_name: str | None = None
            candidate_reason: str
            confidence: float
            source_chapter: int | None = None
            aliases: list[dict] | None = None

        class _ExtractionOutput(BaseModel):
            entities: list[_ExtractedEntity]

        system_prompt_base = load_prompt("structure_extraction",
            existing_entities_context=existing_context,
        )

        for ch in chapters:
            ch_idx = ch["chapter_index"]
            ch_text = f"--- 第{ch_idx}章: {ch['title']} ---\n{ch['content']}"

            request = LLMCallRequest(
                model=llm.model_name,
                messages=[
                    {"role": "system", "content": system_prompt_base},
                    {"role": "user", "content": ch_text},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            try:
                result = await llm.generate_structured(
                    request, _ExtractionOutput, max_fix_attempts=3,
                )
            except LLMInvalidResponseError as exc:
                logger.warning(
                    "LLM extraction failed for chapter %d after 4 attempts: %s",
                    ch_idx, exc,
                )
                failed_chapters.append(ch_idx)
                continue
            except Exception as exc:
                logger.error(
                    "Unexpected error extracting chapter %d: %s",
                    ch_idx, exc, exc_info=True,
                )
                failed_chapters.append(ch_idx)
                continue

            if result is None or not result.entities:
                continue

            new_entity_descriptions: list[str] = []

            # 4. 逐实体处理（3 层去重 + 4 种 action 分发）
            for extracted in result.entities:
                if not extracted.name or not extracted.name.strip():
                    total_skipped += 1
                    continue

                suggested_action = extracted.suggested_action

                # --- "ignore" 直接跳过 ---
                if suggested_action == "ignore":
                    total_skipped += 1
                    continue

                # --- Layer 3: LLM 指定的 link_to_existing ---
                linked = False
                if (
                    suggested_action == "link_to_existing"
                    and extracted.suggested_existing_entity_name
                ):
                    existing_id = await self._find_entity_by_name(
                        db, novel_id,
                        extracted.suggested_existing_entity_name,
                        extracted.entity_type,
                    )
                    if existing_id is not None:
                        if extracted.aliases:
                            await self._sync_aliases_to_existing(
                                db, existing_id, novel_id, extracted.aliases,
                            )
                        total_skipped += 1
                        linked = True
                        new_entity_descriptions.append(
                            f"- {extracted.name} ({extracted.entity_type}) [linked to existing]"
                        )

                if linked:
                    continue

                # --- Layer 1: Name embedding dedup ---
                name_embedding = await self._generate_embedding(llm, extracted.name, is_query=True)
                suggestions = await self._dedup_service.find_similar_entities(
                    db, novel_id, extracted.name,
                    entity_type=extracted.entity_type,
                    query_embedding=name_embedding,
                )
                high_confidence = [s for s in suggestions if s.similarity_score >= SIMILARITY_HIGH_CONFIDENCE]
                if high_confidence:
                    best = high_confidence[0]
                    if extracted.aliases:
                        await self._sync_aliases_to_existing(
                            db, best.existing_entity_id, novel_id, extracted.aliases,
                        )
                    total_skipped += 1
                    new_entity_descriptions.append(
                        f"- {extracted.name} ({extracted.entity_type}) [matched via name embedding]"
                    )
                    continue

                # --- Layer 2: Content embedding dedup ---
                content_text_parts = []
                if extracted.summary:
                    content_text_parts.append(extracted.summary.strip())
                if extracted.public_info:
                    content_text_parts.append(extracted.public_info.strip())
                content_text = ". ".join(content_text_parts).strip()
                if content_text:
                    content_embedding = await self._generate_embedding(llm, content_text, is_query=True)
                    if content_embedding is not None:
                        content_suggestions = await self._dedup_service.find_similar_entities(
                            db, novel_id, extracted.name,
                            entity_type=extracted.entity_type,
                            query_embedding=content_embedding,
                        )
                        high_conf_content = [
                            s for s in content_suggestions
                            if s.similarity_score >= SIMILARITY_HIGH_CONFIDENCE
                        ]
                        if high_conf_content:
                            best = high_conf_content[0]
                            if extracted.aliases:
                                await self._sync_aliases_to_existing(
                                    db, best.existing_entity_id, novel_id, extracted.aliases,
                                )
                            total_skipped += 1
                            new_entity_descriptions.append(
                                f"- {extracted.name} ({extracted.entity_type}) [matched via content embedding]"
                            )
                            continue

                # 若 LLM 指定 link_to_existing 但未能解析，跳过
                if suggested_action == "link_to_existing":
                    logger.warning(
                        "link_to_existing for '%s' (chapter %d) could not resolve; skipping",
                        extracted.name, ch_idx,
                    )
                    total_skipped += 1
                    continue

                # --- 创建新实体 ---
                src_ch = extracted.source_chapter or ch_idx

                _meta: dict[str, Any] = {
                    "auto_ingested": True,
                    "ingested_at": datetime.now(UTC).isoformat(),
                    "batch_id": run_batch_id,
                    "source_chapter_index": src_ch,
                    "confidence": min(max(extracted.confidence, 0.0), 1.0),
                }
                if suggested_action == "temporary_only":
                    _meta["temporary"] = True

                content_json: dict[str, Any] = {"_meta": _meta}
                if extracted.aliases:
                    content_json["aliases"] = [
                        {"alias": a.get("alias", "").strip(), "type": a.get("type", "name")}
                        for a in extracted.aliases
                        if isinstance(a, dict) and a.get("alias")
                    ]

                entity_data = CoreEntityCreate(
                    name=extracted.name.strip(),
                    entity_type=extracted.entity_type,
                    summary=extracted.summary[:2000] if extracted.summary else None,
                    public_info=extracted.public_info,
                    hidden_truth=extracted.hidden_truth,
                    importance=min(max(extracted.importance, 0.0), 1.0),
                    status="canonical",
                    created_by="ai_import",
                    content_json=content_json,
                )
                try:
                    entity = await self._entity_repo.create(db, nid, entity_data)
                    storage_embedding = await self._generate_embedding(llm, extracted.name, is_query=False)
                    if storage_embedding:
                        entity.embedding = storage_embedding
                        entity.embedding_text = extracted.name.strip()
                    total_created += 1
                    created_items.append({
                        "id": str(entity.id),
                        "name": entity.name,
                        "entity_type": entity.entity_type,
                        "batch_id": run_batch_id,
                        "auto_ingested": True,
                    })
                    new_entity_descriptions.append(
                        f"- {extracted.name} ({extracted.entity_type}) [created]"
                    )
                except ValueError:
                    total_skipped += 1

            # 5. 更新 existing_context 供下一章使用
            if new_entity_descriptions:
                new_lines = "\n".join(new_entity_descriptions)
                existing_context = existing_context + "\n" + new_lines
                system_prompt_base = load_prompt("structure_extraction",
                    existing_entities_context=existing_context,
                )

        await db.flush()
        return ExtractionResult(
            total_chapters=len(chapters),
            total_created=total_created,
            total_skipped=total_skipped,
            failed_chapters=failed_chapters,
            items=created_items,
        )

    async def _find_entity_by_name(
        self,
        db: AsyncSession,
        novel_id: str,
        name: str,
        entity_type: str | None = None,
    ) -> str | None:
        """按名称查找正史实体 ID"""
        from modules.world.facade import find_entity_id_by_name

        return await find_entity_id_by_name(db, novel_id, name, entity_type=entity_type)

    async def _generate_embedding(
        self,
        llm: Any,
        text: str,
        *,
        is_query: bool = False,
    ) -> list[float] | None:
        """生成文本 embedding，失败时返回 None（降级到纯文本匹配）"""
        if not text or not text.strip():
            return None
        try:
            result = await llm.generate_embedding(text, is_query=is_query)
            if isinstance(result, list) and len(result) > 0 and all(isinstance(v, (int, float)) for v in result):
                return [float(v) for v in result]
            return None
        except Exception as exc:
            logger.warning("Failed to generate embedding, falling back to text-only dedup: %s", exc)
            return None

    async def _sync_aliases_to_existing(
        self,
        db: AsyncSession,
        entity_id: str,
        novel_id: str,
        aliases: list[dict],
    ) -> None:
        """将别名追加到已有实体的 content_json.aliases，去重。"""
        from modules.world.services.helpers import find_alias_in_list

        eid = parse_uuid(entity_id, "entity_id")
        entity = await self._entity_repo.get(db, eid)
        if entity is None:
            return

        content = entity.content_json or {}
        existing = content.get("aliases", [])
        if not isinstance(existing, list):
            existing = []
        changed = False
        for entry in aliases:
            if not isinstance(entry, dict):
                continue
            alias_text = entry.get("alias", "")
            if not alias_text or not alias_text.strip():
                continue
            if find_alias_in_list(existing, alias_text.strip()):
                continue
            existing.append({
                "alias": alias_text.strip(),
                "type": entry.get("type", "name"),
            })
            changed = True

        if changed:
            content["aliases"] = existing
            entity.content_json = content
            await db.flush()

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
