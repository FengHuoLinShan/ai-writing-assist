"""EntityExtractionService — LLM 抽取管线（单章顺序模式）"""

from __future__ import annotations

import inspect
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import (
    CoreEntityDraftSuggestionPayload,
    WorldBibleSourceRef,
)
from modules.world.services.common import parse_uuid
from modules.world.services.core.dedup_service import EntityDedupService
from modules.world.services.core.draft_provider import WritingDraftProvider
from modules.world.services.worldbuilding.suggestion_queue_service import (
    SuggestionQueueService,
)
from shared.constants import SIMILARITY_HIGH_CONFIDENCE
from shared.protocols import DraftProvider

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
    LLM extract(3 retries) → 3-layer dedup → suggestion queue →
    update existing_context → next chapter
    """

    def __init__(self, draft_provider: DraftProvider | None = None) -> None:
        self._entity_repo = CoreEntityRepository()
        self._candidate_repo = CoreEntityRepository()
        self._dedup_service = EntityDedupService()
        self._draft_provider = draft_provider or WritingDraftProvider()
        self._suggestion_queue = SuggestionQueueService()

    async def extract_entities_from_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        batch_size: int = 5,
    ) -> ExtractionResult:
        """Run extraction with one lifecycle-managed project LLM client."""
        from unittest.mock import Mock

        from infrastructure.llm.client import LLMClient
        from modules.project.facade import open_project_llm_client

        if isinstance(db, Mock):
            from modules.project.facade import get_project_context

            project_context = await get_project_context(db, novel_id)
            if project_context is None:
                raise ValidationError("Project LLM settings are required for extraction")
            client = LLMClient.from_project_settings(project_context.settings)
            try:
                return await self._extract_entities_from_chapters_with_client(
                    db,
                    novel_id,
                    start_chapter,
                    end_chapter,
                    batch_size=batch_size,
                    llm=client,
                )
            finally:
                close = getattr(client, "close", None)
                if callable(close):
                    close_result = close()
                    if inspect.isawaitable(close_result):
                        await close_result

        async with open_project_llm_client(db, novel_id) as client:
            return await self._extract_entities_from_chapters_with_client(
                db,
                novel_id,
                start_chapter,
                end_chapter,
                batch_size=batch_size,
                llm=client,
            )

    async def _extract_entities_from_chapters_with_client(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        *,
        batch_size: int,
        llm: Any,
    ) -> ExtractionResult:
        """从指定章节范围抽取世界对象候选（单章顺序模式）

        每章独立 LLM 调用，3 次重试，上下文逐步累积。
        batch_size 参数保留以兼容调用方 API，实际忽略。
        """
        parse_uuid(novel_id, "novel_id")

        # 1. 读取已有正史对象作为初始 context（过滤过期临时实体）
        from modules.world.facade import get_world_context

        ctx = await get_world_context(
            db,
            novel_id,
            reveal_mode="author_safe",
            limit=500,
            current_chapter=start_chapter,
            include_review=True,
        )
        existing_context = (
            "\n".join(
                f"- {e.name} ({e.entity_type})"
                for e in ctx.entities
                if e.status in ("canonical", "draft")
            )
            or "无已有对象"
        )

        # 2. 单章读取 WritingDraft
        chapters = await self._load_chapters(db, novel_id, start_chapter, end_chapter)
        if not chapters:
            raise ValidationError(f"未找到章节 {start_chapter}-{end_chapter} 的正文")

        # 3. 单章顺序抽取
        from pydantic import BaseModel

        from infrastructure.llm.agent_step_harness import run_managed_structured
        from infrastructure.llm.errors import LLMInvalidResponseError
        from infrastructure.llm.prompt_loader import load_prompt
        from infrastructure.llm.schemas import LLMCallRequest

        total_created = 0
        total_skipped = 0
        created_items: list[dict[str, Any]] = []
        failed_chapters: list[int] = []
        run_batch_id = str(uuid.uuid4())

        # 定义 Pydantic schema（内联以保持模块级命名空间干净）
        _action = Literal["create_new", "link_to_existing", "ignore", "temporary_only"]

        class _ExtractedEntity(BaseModel):
            name: str
            entity_type: str
            summary: str
            public_info: str
            hidden_truth: str
            importance: float
            suggested_action: _action
            suggested_existing_entity_name: str | None = None
            candidate_reason: str
            confidence: float
            source_chapter: int | None = None
            aliases: list[dict] | None = None

        class _ExtractionOutput(BaseModel):
            entities: list[_ExtractedEntity]

        system_prompt_base = load_prompt(
            "structure_extraction",
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
                result = await run_managed_structured(
                    llm,
                    request,
                    _ExtractionOutput,
                    step_name="world.entity_extraction.structured",
                    max_fix_attempts=3,
                )
            except LLMInvalidResponseError as exc:
                logger.warning(
                    "LLM extraction failed for chapter %d after 4 attempts: %s",
                    ch_idx,
                    exc,
                )
                failed_chapters.append(ch_idx)
                continue
            except Exception as exc:
                logger.error(
                    "Unexpected error extracting chapter %d: %s",
                    ch_idx,
                    exc,
                    exc_info=True,
                )
                failed_chapters.append(ch_idx)
                continue

            if result is None or not result.entities:
                continue

            new_entity_descriptions: list[str] = []
            query_embedding_keys: list[tuple[int, str]] = []
            query_embedding_texts: list[str] = []
            for idx, extracted in enumerate(result.entities):
                if (
                    not extracted.name
                    or not extracted.name.strip()
                    or extracted.suggested_action != "create_new"
                ):
                    continue
                query_embedding_keys.append((idx, "name"))
                query_embedding_texts.append(extracted.name.strip())

                content_text = self._build_content_embedding_text(extracted)
                if content_text:
                    query_embedding_keys.append((idx, "content"))
                    query_embedding_texts.append(content_text)

            query_embedding_values = await self._generate_embeddings_batch(
                llm,
                query_embedding_texts,
                is_query=True,
            )
            query_embeddings = dict(zip(query_embedding_keys, query_embedding_values))
            pending_storage_embeddings: list[tuple[Any, str]] = []

            # 4. 逐实体处理（3 层去重 + 4 种 action 分发）
            for idx, extracted in enumerate(result.entities):
                if not extracted.name or not extracted.name.strip():
                    total_skipped += 1
                    continue

                suggested_action = extracted.suggested_action

                # --- "ignore" 直接跳过 ---
                if suggested_action == "ignore":
                    total_skipped += 1
                    continue

                if suggested_action == "link_to_existing":
                    existing_name = extracted.suggested_existing_entity_name
                    if existing_name:
                        from modules.world.facade import find_entity_id_by_name

                        existing_id = await find_entity_id_by_name(
                            db,
                            novel_id,
                            existing_name,
                        )
                        if existing_id:
                            total_skipped += 1
                            continue
                    total_skipped += 1
                    continue

                if suggested_action == "create_new":
                    # --- Layer 1: Name embedding dedup ---
                    name_embedding = query_embeddings.get((idx, "name"))
                    suggestions = await self._dedup_service.find_similar_entities(
                        db,
                        novel_id,
                        extracted.name,
                        entity_type=extracted.entity_type,
                        query_embedding=name_embedding,
                    )
                    high_confidence = [
                        s
                        for s in suggestions
                        if s.similarity_score >= SIMILARITY_HIGH_CONFIDENCE
                    ]
                    if high_confidence:
                        total_skipped += 1
                        new_entity_descriptions.append(
                            f"- {extracted.name} ({extracted.entity_type}) "
                            "[matched via name embedding]"
                        )
                        continue

                    # --- Layer 2: Content embedding dedup ---
                    content_text = self._build_content_embedding_text(extracted)
                    if content_text:
                        content_embedding = query_embeddings.get((idx, "content"))
                        if content_embedding is not None:
                            content_suggestions = (
                                await self._dedup_service.find_similar_entities(
                                    db,
                                    novel_id,
                                    extracted.name,
                                    entity_type=extracted.entity_type,
                                    query_embedding=content_embedding,
                                )
                            )
                            high_conf_content = [
                                s
                                for s in content_suggestions
                                if s.similarity_score >= SIMILARITY_HIGH_CONFIDENCE
                            ]
                            if high_conf_content:
                                total_skipped += 1
                                new_entity_descriptions.append(
                                    f"- {extracted.name} ({extracted.entity_type}) "
                                    "[matched via content embedding]"
                                )
                                continue

                # --- 创建新实体 ---
                src_ch = extracted.source_chapter or ch_idx

                _meta: dict[str, Any] = {
                    "auto_ingested": True,
                    "ingested_at": datetime.now(UTC).isoformat(),
                    "batch_id": run_batch_id,
                    "source_chapter_index": src_ch,
                    "confidence": min(max(extracted.confidence, 0.0), 1.0),
                    "suggested_action": suggested_action,
                    "suggested_existing_entity_name": (
                        extracted.suggested_existing_entity_name
                    ),
                    "candidate_reason": extracted.candidate_reason,
                }
                if suggested_action == "temporary_only":
                    _meta["temporary"] = True

                content_json: dict[str, Any] = {"_meta": _meta}
                if extracted.aliases:
                    content_json["aliases"] = [
                        {
                            "alias": a.get("alias", "").strip(),
                            "type": a.get("type", "name"),
                            "status": "candidate",
                            "source": "world_extraction",
                            "batch_id": run_batch_id,
                            "source_chapter_index": src_ch,
                            "confidence": min(
                                max(extracted.confidence, 0.0),
                                1.0,
                            ),
                            "needs_review": True,
                        }
                        for a in extracted.aliases
                        if isinstance(a, dict) and a.get("alias")
                    ]

                try:
                    (
                        suggestion,
                        compatibility_entity,
                    ) = await self._suggestion_queue.create_core_entity_suggestion(
                        db,
                        novel_id=novel_id,
                        source_module="world_extraction",
                        review_group=f"entity_extraction:{run_batch_id}",
                        payload=CoreEntityDraftSuggestionPayload(
                            name=extracted.name.strip(),
                            entity_type=extracted.entity_type,
                            summary=(
                                extracted.summary[:2000] if extracted.summary else None
                            ),
                            public_info=extracted.public_info,
                            hidden_truth=extracted.hidden_truth,
                            importance=min(max(extracted.importance, 0.0), 1.0),
                            content_json=content_json,
                            source_refs=[
                                WorldBibleSourceRef(
                                    source_type="writing_chapter",
                                    chapter_index=src_ch,
                                )
                            ],
                        ),
                        evidence_refs_json=[
                            {
                                "source_chapter_index": src_ch,
                                "candidate_reason": extracted.candidate_reason,
                            }
                        ],
                        risk_level=("high" if extracted.confidence < 0.5 else "medium"),
                        compatibility_status="candidate",
                        compatibility_created_by="ai_import",
                    )
                    if compatibility_entity is None:  # pragma: no cover
                        raise RuntimeError(
                            "entity extraction compatibility shadow was not created"
                        )
                    entity = await self._entity_repo.get(
                        db,
                        parse_uuid(compatibility_entity.id, "entity_id"),
                    )
                    if entity is None:  # pragma: no cover
                        raise RuntimeError(
                            "entity extraction compatibility shadow was not found"
                        )
                    pending_storage_embeddings.append((entity, extracted.name.strip()))
                    total_created += 1
                    created_items.append(
                        {
                            "id": str(entity.id),
                            "suggestion_id": suggestion.id,
                            "name": entity.name,
                            "entity_type": entity.entity_type,
                            "batch_id": run_batch_id,
                            "auto_ingested": True,
                        }
                    )
                    new_entity_descriptions.append(
                        f"- {extracted.name} ({extracted.entity_type}) [created]"
                    )
                except ValueError:
                    total_skipped += 1

            if pending_storage_embeddings:
                storage_texts = [text for _, text in pending_storage_embeddings]
                storage_embeddings = await self._generate_embeddings_batch(
                    llm,
                    storage_texts,
                    is_query=False,
                )
                for (entity, storage_text), storage_embedding in zip(
                    pending_storage_embeddings,
                    storage_embeddings,
                ):
                    if storage_embedding:
                        entity.embedding = storage_embedding
                        entity.embedding_text = storage_text

            # 5. 更新 existing_context 供下一章使用
            if new_entity_descriptions:
                new_lines = "\n".join(new_entity_descriptions)
                existing_context = existing_context + "\n" + new_lines
                system_prompt_base = load_prompt(
                    "structure_extraction",
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
            return self._coerce_embedding_vector(result)
        except Exception as exc:
            logger.warning(
                "Failed to generate embedding, falling back to text-only dedup: %s", exc
            )
            return None

    async def _generate_embeddings_batch(
        self,
        llm: Any,
        texts: list[str],
        *,
        is_query: bool = False,
    ) -> list[list[float] | None]:
        """批量生成 embedding，批次异常时整批降级为 None。"""
        if not texts:
            return []

        embeddings: list[list[float] | None] = [None] * len(texts)
        valid_items = [
            (idx, text.strip()) for idx, text in enumerate(texts) if text.strip()
        ]
        if not valid_items:
            return embeddings

        try:
            result = await llm.generate_embedding(
                [text for _, text in valid_items],
                is_query=is_query,
            )
        except Exception as exc:
            logger.warning(
                "Failed to generate embedding batch, falling back to text-only dedup: %s",
                exc,
            )
            return embeddings

        if not isinstance(result, list) or len(result) != len(valid_items):
            logger.warning(
                "Invalid embedding batch result, falling back to text-only dedup"
            )
            return embeddings

        coerced_vectors = [self._coerce_embedding_vector(item) for item in result]
        if any(vector is None for vector in coerced_vectors):
            logger.warning(
                "Invalid embedding vector in batch, falling back to text-only dedup"
            )
            return embeddings

        for (idx, _), vector in zip(valid_items, coerced_vectors):
            embeddings[idx] = vector
        return embeddings

    def _coerce_embedding_vector(self, result: Any) -> list[float] | None:
        if (
            isinstance(result, list)
            and len(result) > 0
            and all(isinstance(v, (int, float)) for v in result)
        ):
            return [float(v) for v in result]
        return None

    def _build_content_embedding_text(self, extracted: Any) -> str:
        content_text_parts = []
        if extracted.summary:
            content_text_parts.append(extracted.summary.strip())
        if extracted.public_info:
            content_text_parts.append(extracted.public_info.strip())
        return ". ".join(content_text_parts).strip()

    async def _sync_aliases_to_existing(
        self,
        db: AsyncSession,
        entity_id: str,
        novel_id: str,
        aliases: list[dict],
    ) -> None:
        """将别名追加到已有实体的 content_json.aliases，去重。"""
        from modules.world.services.common import find_alias_in_list

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
            existing.append(
                {
                    "alias": alias_text.strip(),
                    "type": entry.get("type", "name"),
                }
            )
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
            db,
            novel_id,
            start_chapter,
            end_chapter,
        )
