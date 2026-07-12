"""Generate draft world objects from the generate-center chatbox."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from infrastructure.llm.agent_step_harness import (
    run_managed_generate,
    run_managed_structured,
)
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.world.llm_schemas import GeneratedObjectDraftOutput
from modules.world.schemas import (
    CoreEntityDraftSuggestionPayload,
    ObjectDraftChatRequest,
    ObjectDraftChatResponse,
    ObjectDraftGenerateRequest,
    ObjectDraftGenerateResponse,
    WorldBibleSourceRef,
)
from modules.world.services.common import parse_uuid
from modules.world.services.core.entity_service import WorldEntityService
from modules.world.services.worldbuilding.generation_prompt_template_service import (
    TEMPLATE_ENTITY_TYPES,
    GenerationPromptTemplateService,
    ResolvedGenerationTemplate,
    TemplateVersionConflictError,
)
from modules.world.services.worldbuilding.suggestion_queue_service import (
    SuggestionQueueService,
)

_QUALITY_MODELS = {
    "fast": "deepseek-v4-flash",
    "pro": "deepseek-v4-pro",
}


class ObjectDraftGenerationService:
    """Chat freely first; only create a DB draft when explicitly requested."""

    def __init__(
        self,
        *,
        entity_service: WorldEntityService | None = None,
        suggestion_service: SuggestionQueueService | None = None,
        llm_client: LLMClient | None = None,
        template_service: GenerationPromptTemplateService | None = None,
    ) -> None:
        self._entity_service = entity_service or WorldEntityService()
        self._suggestion_service = suggestion_service or SuggestionQueueService(
            entity_service=self._entity_service
        )
        self._llm_client = llm_client
        self._template_service = template_service or GenerationPromptTemplateService()

    async def chat(
        self,
        db: AsyncSession,
        data: ObjectDraftChatRequest,
    ) -> ObjectDraftChatResponse:
        parse_uuid(data.novel_id, "novel_id")
        chapters = await self._load_selected_chapters(
            db,
            data.novel_id,
            data.selected_chapter_indices,
        )
        template = await self._resolve_template(db, data)
        async with self._open_client(db, data.novel_id) as client:
            response = await run_managed_generate(
                client,
                LLMCallRequest(
                    model=self._model_for(data.quality_mode),
                    messages=self._chat_messages(data, chapters, template),
                    temperature=0.8,
                    max_tokens=2048,
                ),
                step_name="world.object_draft.chat.generate",
            )
        return ObjectDraftChatResponse(
            reply=response.content.strip(),
            model=response.model,
            provider=response.provider,
        )

    async def generate(
        self,
        db: AsyncSession,
        data: ObjectDraftGenerateRequest,
    ) -> ObjectDraftGenerateResponse:
        parse_uuid(data.novel_id, "novel_id")
        chapters = await self._load_selected_chapters(
            db,
            data.novel_id,
            data.selected_chapter_indices,
        )
        template = await self._resolve_template(db, data)
        async with self._open_client(db, data.novel_id) as client:
            response = await run_managed_structured(
                client,
                LLMCallRequest(
                    model=self._model_for(data.quality_mode),
                    messages=self._structured_messages(data, chapters, template),
                    temperature=0.35,
                    max_tokens=4096,
                ),
                GeneratedObjectDraftOutput,
                step_name="world.object_draft.generate.structured",
                max_fix_attempts=2,
            )
            provider = client.provider

        content_json = self._content_json(data, response, template)
        suggestion, entity = await self._suggestion_service.create_core_entity_suggestion(
            db,
            novel_id=data.novel_id,
            source_module="chatbox",
            review_group="generate_center",
            payload=CoreEntityDraftSuggestionPayload(
                entity_type=TEMPLATE_ENTITY_TYPES.get(
                    template.object_template,
                    "concept",
                ),
                name=response.name,
                summary=response.summary,
                public_info=response.public_info,
                hidden_truth=response.hidden_truth,
                content_json=content_json,
                importance_level=response.importance_level or "normal",
                reveal_level=response.reveal_level or "author_only",
                source_refs=[
                    WorldBibleSourceRef(
                        source_type="writing_chapter",
                        chapter_index=item["chapter_index"],
                        title=item["title"],
                    )
                    for item in chapters
                ],
            ),
            compatibility_status="draft",
            compatibility_created_by="ai_chatbox",
        )
        if entity is None:  # pragma: no cover - guarded by compatibility_status
            raise RuntimeError("object draft compatibility entity was not created")
        return ObjectDraftGenerateResponse(
            entity=entity,
            suggestion=suggestion,
            quality_mode=data.quality_mode,
            model=self._model_for(data.quality_mode),
            provider=provider,
        )

    @asynccontextmanager
    async def _open_client(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> AsyncIterator[LLMClient]:
        if self._llm_client is not None:
            yield self._llm_client
            return
        from modules.project.facade import open_project_llm_client

        async with open_project_llm_client(db, novel_id) as client:
            yield client

    @staticmethod
    def _model_for(quality_mode: str) -> str:
        return _QUALITY_MODELS.get(quality_mode, _QUALITY_MODELS["fast"])

    async def _resolve_template(
        self,
        db: AsyncSession,
        data: ObjectDraftChatRequest | ObjectDraftGenerateRequest,
    ) -> ResolvedGenerationTemplate:
        try:
            return await self._template_service.resolve_for_generation(
                db,
                novel_id=data.novel_id,
                template_id=data.template_id,
                template_version=data.template_version,
                template_variables=data.template_variables,
                legacy_data=data,
            )
        except TemplateVersionConflictError:
            raise
        except ValidationError:
            raise

    async def _load_selected_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_indices: list[int],
    ) -> list[dict[str, Any]]:
        requested = sorted({int(idx) for idx in chapter_indices if int(idx) > 0})
        if not requested:
            return []
        from modules.writing.facade import list_latest_drafts_for_chapters

        drafts = await list_latest_drafts_for_chapters(db, novel_id, requested)
        by_index = {draft.chapter_index: draft for draft in drafts}
        missing = [idx for idx in requested if idx not in by_index]
        if missing:
            raise ValidationError(f"selected chapters not found: {missing}")
        return [
            {
                "chapter_index": draft.chapter_index,
                "title": draft.title or f"第{draft.chapter_index}章",
                "excerpt": self._excerpt(draft.content or ""),
            }
            for draft in drafts
        ]

    @staticmethod
    def _excerpt(content: str, limit: int = 500) -> str:
        text = " ".join((content or "").split())
        return text[:limit]

    def _chat_messages(
        self,
        data: ObjectDraftChatRequest,
        chapters: list[dict[str, Any]],
        template: ResolvedGenerationTemplate,
    ) -> list[LLMMessage]:
        messages = [
            LLMMessage(
                role="system",
                content=(
                    "你是中文长篇小说的自由共创助手。当前阶段只聊天发散，"
                    "不要输出 JSON，不要声称已写入数据库，不要要求用户先导入正文。"
                    f"当前模板是：{template.label}。"
                    f"模板提示词：{template.rendered_prompt}"
                ),
            )
        ]
        context = self._reference_block(data.pasted_context, chapters)
        if context:
            messages.append(LLMMessage(role="user", content=context))
        for item in data.messages:
            messages.append(LLMMessage(role=item.role, content=item.content))
        if len(messages) == 1:
            messages.append(
                LLMMessage(role="user", content=f"帮我设计一个{template.label}。")
            )
        return messages

    def _structured_messages(
        self,
        data: ObjectDraftGenerateRequest,
        chapters: list[dict[str, Any]],
        template: ResolvedGenerationTemplate,
    ) -> list[LLMMessage]:
        transcript = (
            "\n".join(f"{item.role}: {item.content}" for item in data.messages)
            or "用户未提供站内聊天记录。"
        )
        reference = self._reference_block(data.pasted_context, chapters) or "无附加资料。"
        return [
            LLMMessage(
                role="system",
                content=(
                    "你是长篇小说结构化创作助手。请把用户已经聊清楚的内容"
                    f"收束为一个{template.label}数据库草稿对象。"
                    "只输出 JSON，字段必须符合 schema。"
                    "不要生成小说正文，不要把对象提升为正史。"
                    "summary 字段必填，不能留空、不能写 null、不能写占位符。"
                ),
            ),
            LLMMessage(
                role="user",
                content=(
                    f"对象模板：{template.label}\n\n"
                    f"模板提示词：\n{template.rendered_prompt}\n\n"
                    f"站内聊天记录：\n{transcript}\n\n"
                    f"附加资料：\n{reference}\n\n"
                    "请生成一个可入库的对象草稿。\n"
                    "硬性要求：summary 必须是 80-180 字中文概要，概括对象身份、"
                    "核心特征、冲突价值和剧情用途，可直接显示在对象库摘要列。\n"
                    "人物模板时，把动机、欲望、恐惧、秘密、"
                    "外貌、性格、关系钩子、声音风格等放入 character_card。"
                ),
            ),
        ]

    @staticmethod
    def _reference_block(
        pasted_context: str | None,
        chapters: list[dict[str, Any]],
    ) -> str:
        parts: list[str] = []
        if pasted_context and pasted_context.strip():
            parts.append("【用户粘贴的外部聊天内容】\n" + pasted_context.strip())
        if chapters:
            chapter_text = "\n\n".join(
                f"第 {item['chapter_index']} 章 {item['title']}\n{item['excerpt']}"
                for item in chapters
            )
            parts.append("【用户选择的章节摘录】\n" + chapter_text)
        return "\n\n".join(parts)

    @staticmethod
    def _content_json(
        data: ObjectDraftGenerateRequest,
        generated: GeneratedObjectDraftOutput,
        template: ResolvedGenerationTemplate,
    ) -> dict[str, Any]:
        content_json: dict[str, Any] = {
            "details": generated.details,
            "_meta": {
                "source": "chatbox_object_draft",
                "template": template.object_template,
                "template_name": template.label,
                "has_custom_template_prompt": bool(
                    data.template_prompt and data.template_prompt.strip()
                ),
                "template_id": template.template_id,
                "template_version": template.template_version,
                "template_hash": template.template_hash,
                "template_validation_state": template.validation_state,
                "quality_mode": data.quality_mode,
                "high_quality": data.quality_mode == "pro",
                "has_pasted_context": bool(
                    data.pasted_context and data.pasted_context.strip()
                ),
                "selected_chapter_indices": data.selected_chapter_indices,
                "generated_at": datetime.now(UTC).isoformat(),
            },
        }
        if template.object_template == "character":
            content_json["character_card"] = generated.character_card or generated.details
        return content_json
