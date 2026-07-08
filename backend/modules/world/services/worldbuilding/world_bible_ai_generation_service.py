"""World Bible scoped AI generation service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from infrastructure.llm.agent_step_harness import (
    run_managed_generate,
    run_managed_structured,
)
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.project.facade import get_project_context
from modules.world.llm_schemas import (
    GeneratedObjectDraftOutput,
    GeneratedWorldBibleNewPageOutput,
    GeneratedWorldBiblePagePatchOutput,
)
from modules.world.schemas import (
    CoreEntityDraftSuggestionPayload,
    CreationSuggestionCreate,
    ObjectDraftChatRequest,
    ObjectDraftQualityMode,
    WorldBibleAiGenerateRequest,
    WorldBibleAiGenerateResponse,
    WorldBibleAiSuggestionSummary,
    WorldBibleNewPageSuggestionPayload,
    WorldBiblePagePatchSuggestionPayload,
    WorldBibleSourceRef,
)
from modules.world.services.common import parse_uuid
from modules.world.services.worldbuilding.generation_prompt_template_service import (
    TEMPLATE_ENTITY_TYPES,
    GenerationPromptTemplateService,
    ResolvedGenerationTemplate,
)
from modules.world.services.worldbuilding.object_draft_generation_service import (
    ObjectDraftGenerationService,
)

if TYPE_CHECKING:
    from modules.world.services.worldbuilding.worldbuilding_service import (
        SuggestionQueueService,
        WorldBibleService,
    )

_QUALITY_MODELS = {
    "fast": "deepseek-v4-flash",
    "pro": "deepseek-v4-pro",
}


class WorldBibleAiGenerationService:
    """Generate World Bible scoped chat replies or reviewable suggestions."""

    def __init__(
        self,
        *,
        bible_service: WorldBibleService | None = None,
        suggestion_service: SuggestionQueueService | None = None,
        template_service: GenerationPromptTemplateService | None = None,
        draft_service: ObjectDraftGenerationService | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        from modules.world.services.worldbuilding import worldbuilding_service

        self._bible_service = bible_service or worldbuilding_service.WorldBibleService()
        self._suggestions = (
            suggestion_service or worldbuilding_service.SuggestionQueueService()
        )
        self._template_service = template_service or GenerationPromptTemplateService()
        self._draft_service = draft_service or ObjectDraftGenerationService()
        self._llm_client = llm_client

    async def generate(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        data: WorldBibleAiGenerateRequest,
    ) -> WorldBibleAiGenerateResponse:
        parse_uuid(novel_id, "novel_id")
        page = await self._bible_service.get_page(db, novel_id, page_id)
        project = await get_project_context(db, novel_id)
        if project is None:
            raise NotFoundError(f"Project {novel_id} not found")
        chapters = await self._draft_service._load_selected_chapters(  # noqa: SLF001
            db,
            novel_id,
            data.selected_chapter_indices,
        )
        template = await self._resolve_template(db, novel_id, data)
        client = self._client(project.settings)
        context = self._reference_block(
            page_title=page.title,
            page_text=page.free_text or "",
            include_current_page=data.include_current_page,
            chapters=chapters,
        )
        if data.output_target == "chat":
            response = await run_managed_generate(
                client,
                LLMCallRequest(
                    model=self._model_for(data.quality_mode),
                    messages=self._chat_messages(data, template, context),
                    temperature=0.75,
                    max_tokens=2048,
                ),
                step_name="world.world_bible.chat.generate",
            )
            return WorldBibleAiGenerateResponse(
                reply=response.content.strip(),
                model=response.model,
                provider=response.provider,
            )

        suggestion = await self._generate_suggestion(
            db,
            novel_id,
            page,
            data,
            template,
            client,
            context,
            chapters,
        )
        return WorldBibleAiGenerateResponse(
            suggestions=[suggestion],
            model=self._model_for(data.quality_mode),
            provider=client.provider,
        )

    async def _generate_suggestion(
        self,
        db: AsyncSession,
        novel_id: str,
        page,
        data: WorldBibleAiGenerateRequest,
        template: ResolvedGenerationTemplate,
        client: LLMClient,
        context: str,
        chapters: list[dict[str, Any]],
    ) -> WorldBibleAiSuggestionSummary:
        source_refs = self._source_refs(page, chapters)
        if data.output_target == "page_patch":
            generated = await run_managed_structured(
                client,
                LLMCallRequest(
                    model=self._model_for(data.quality_mode),
                    messages=self._structured_messages(
                        data,
                        template,
                        context,
                        "请整理为可追加到当前世界书页面末尾的一段正文。",
                    ),
                    temperature=0.35,
                    max_tokens=4096,
                ),
                GeneratedWorldBiblePagePatchOutput,
                step_name="world.world_bible.page_patch.structured",
                max_fix_attempts=2,
            )
            payload = WorldBiblePagePatchSuggestionPayload(
                page_id=page.id,
                append_text=generated.append_text,
                source_refs=source_refs,
                reason=generated.reason,
            )
            suggestion = await self._suggestions.create(
                db,
                CreationSuggestionCreate(
                    novel_id=novel_id,
                    source_module="world_bible",
                    review_group="world_bible_ai",
                    target_type="world_bible_page_patch",
                    action_schema="world_bible_ai.v1",
                    payload_json=payload.model_dump(),
                    evidence_refs_json=[item.model_dump() for item in source_refs],
                    risk_level="low",
                ),
            )
            return self._summary(suggestion.id, "world_bible_page_patch", page.title)

        if data.output_target == "new_page":
            generated = await run_managed_structured(
                client,
                LLMCallRequest(
                    model=self._model_for(data.quality_mode),
                    messages=self._structured_messages(
                        data,
                        template,
                        context,
                        "请整理为一个新的世界书页面。",
                    ),
                    temperature=0.35,
                    max_tokens=4096,
                ),
                GeneratedWorldBibleNewPageOutput,
                step_name="world.world_bible.new_page.structured",
                max_fix_attempts=2,
            )
            payload = WorldBibleNewPageSuggestionPayload(
                title=generated.title,
                page_type=generated.page_type,
                free_text=generated.free_text,
                source_refs=source_refs,
            )
            suggestion = await self._suggestions.create(
                db,
                CreationSuggestionCreate(
                    novel_id=novel_id,
                    source_module="world_bible",
                    review_group="world_bible_ai",
                    target_type="world_bible_page",
                    action_schema="world_bible_ai.v1",
                    payload_json=payload.model_dump(),
                    evidence_refs_json=[item.model_dump() for item in source_refs],
                    risk_level="low",
                ),
            )
            return self._summary(suggestion.id, "world_bible_page", generated.title)

        if data.output_target == "world_object_draft":
            generated = await run_managed_structured(
                client,
                LLMCallRequest(
                    model=self._model_for(data.quality_mode),
                    messages=self._structured_messages(
                        data,
                        template,
                        context,
                        "请整理为一个可入库的世界对象草稿建议。",
                    ),
                    temperature=0.35,
                    max_tokens=4096,
                ),
                GeneratedObjectDraftOutput,
                step_name="world.world_bible.object_draft.structured",
                max_fix_attempts=2,
            )
            content_json = {
                "details": generated.details,
                "_meta": {
                    "source": "world_bible_ai_generation",
                    "template": template.object_template,
                    "template_name": template.label,
                    "template_id": template.template_id,
                    "template_version": template.template_version,
                    "template_hash": template.template_hash,
                    "quality_mode": data.quality_mode,
                    "source_refs": [item.model_dump() for item in source_refs],
                    "selected_chapter_indices": data.selected_chapter_indices,
                    "page_id": page.id,
                },
            }
            if template.object_template == "character":
                content_json["character_card"] = (
                    generated.character_card or generated.details
                )
            payload = CoreEntityDraftSuggestionPayload(
                entity_type=TEMPLATE_ENTITY_TYPES.get(
                    template.object_template,
                    "concept",
                ),
                name=generated.name,
                summary=generated.summary,
                public_info=generated.public_info,
                hidden_truth=generated.hidden_truth,
                content_json=content_json,
                importance_level=generated.importance_level or "normal",
                reveal_level=generated.reveal_level or "author_only",
                source_refs=source_refs,
            )
            suggestion = await self._suggestions.create(
                db,
                CreationSuggestionCreate(
                    novel_id=novel_id,
                    source_module="world_bible",
                    review_group="world_bible_ai",
                    target_type="core_entity_draft",
                    action_schema="world_bible_ai.v1",
                    payload_json=payload.model_dump(),
                    evidence_refs_json=[item.model_dump() for item in source_refs],
                    risk_level="medium",
                ),
            )
            return self._summary(
                suggestion.id,
                "core_entity_draft",
                generated.name,
                generated.summary,
            )

        raise ValidationError(f"unsupported output_target: {data.output_target}")

    async def _resolve_template(
        self,
        db: AsyncSession,
        novel_id: str,
        data: WorldBibleAiGenerateRequest,
    ) -> ResolvedGenerationTemplate:
        request = ObjectDraftChatRequest(
            novel_id=novel_id,
            messages=data.messages,
            selected_chapter_indices=data.selected_chapter_indices,
            quality_mode=data.quality_mode,
            template_id=data.template_id,
            template_version=data.template_version,
            template_variables=data.template_variables,
        )
        return await self._template_service.resolve_for_generation(
            db,
            novel_id=novel_id,
            template_id=data.template_id,
            template_version=data.template_version,
            template_variables=data.template_variables,
            legacy_data=request,
        )

    def _client(self, project_settings: dict[str, Any] | None) -> LLMClient:
        if self._llm_client is not None:
            return self._llm_client
        return LLMClient.from_project_settings(project_settings or {})

    @staticmethod
    def _model_for(quality_mode: ObjectDraftQualityMode) -> str:
        return _QUALITY_MODELS.get(str(quality_mode), _QUALITY_MODELS["fast"])

    @staticmethod
    def _source_refs(page, chapters: list[dict[str, Any]]) -> list[WorldBibleSourceRef]:
        refs = [
            WorldBibleSourceRef(
                source_type="world_bible_page",
                page_id=page.id,
                title=page.title,
            )
        ]
        refs.extend(
            WorldBibleSourceRef(
                source_type="writing_chapter",
                chapter_index=item["chapter_index"],
                title=item["title"],
            )
            for item in chapters
        )
        return refs

    @staticmethod
    def _reference_block(
        *,
        page_title: str,
        page_text: str,
        include_current_page: bool,
        chapters: list[dict[str, Any]],
    ) -> str:
        parts: list[str] = []
        if include_current_page:
            parts.append(f"【当前世界书页面：{page_title}】\n{page_text[:6000]}")
        if chapters:
            chapter_text = "\n\n".join(
                f"第 {item['chapter_index']} 章 {item['title']}\n{item['excerpt']}"
                for item in chapters
            )
            parts.append("【用户选择的章节摘录】\n" + chapter_text)
        return "\n\n".join(part for part in parts if part.strip()) or "无附加资料。"

    @staticmethod
    def _transcript(data: WorldBibleAiGenerateRequest) -> str:
        return "\n".join(f"{item.role}: {item.content}" for item in data.messages).strip()

    def _chat_messages(
        self,
        data: WorldBibleAiGenerateRequest,
        template: ResolvedGenerationTemplate,
        context: str,
    ) -> list[LLMMessage]:
        messages = [
            LLMMessage(
                role="system",
                content=(
                    "你是中文长篇小说的世界书共创助手。当前阶段只聊天发散，"
                    "不要声称已写入数据库或正史。"
                    f"当前模板：{template.label}。模板提示词：{template.rendered_prompt}"
                ),
            ),
            LLMMessage(role="user", content=f"AI 参考资料：\n{context}"),
        ]
        messages.extend(
            LLMMessage(role=item.role, content=item.content)
            for item in data.messages
        )
        if not data.messages:
            messages.append(
                LLMMessage(
                    role="user",
                    content="请基于当前世界书页面提出创设建议。",
                )
            )
        return messages

    def _structured_messages(
        self,
        data: WorldBibleAiGenerateRequest,
        template: ResolvedGenerationTemplate,
        context: str,
        instruction: str,
    ) -> list[LLMMessage]:
        transcript = self._transcript(data) or "用户未提供站内聊天记录。"
        return [
            LLMMessage(
                role="system",
                content=(
                    "你是长篇小说结构化创作助手。只输出 JSON，字段必须符合 schema。"
                    "生成内容只是待审核建议，不要声称已写入正史。"
                ),
            ),
            LLMMessage(
                role="user",
                content=(
                    f"对象模板：{template.label}\n\n"
                    f"模板提示词：\n{template.rendered_prompt}\n\n"
                    f"站内聊天记录：\n{transcript}\n\n"
                    f"AI 参考资料：\n{context}\n\n"
                    f"{instruction}\n"
                    "要求：内容应可直接供作者审核，避免空泛占位。"
                ),
            ),
        ]

    @staticmethod
    def _summary(
        suggestion_id: str,
        target_type: str,
        title: str,
        summary: str = "",
    ) -> WorldBibleAiSuggestionSummary:
        return WorldBibleAiSuggestionSummary(
            id=suggestion_id,
            target_type=target_type,
            review_group="world_bible_ai",
            risk_level="medium" if target_type == "core_entity_draft" else "low",
            title=title,
            summary=summary,
        )
