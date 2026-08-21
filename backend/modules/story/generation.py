"""Managed structured-output generation for Story previews."""

from __future__ import annotations

import json
from typing import Any

from infrastructure.llm.agent_step_harness import (
    AgentPermissionLevel,
    ContextBudget,
    run_managed_structured,
)
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.story.schemas import (
    CardPreview,
    CharacterCardContent,
    OneClickOutput,
    ReactionPreview,
    ScriptPreview,
    StorySchema,
)

STORY_CHARACTER_CARD_ACTION = "story.character_card.generate"
STORY_REACTION_ACTION = "story.reaction.generate"
STORY_SCRIPT_ACTION = "story.script.generate"
STORY_ONE_CLICK_ACTION = "story.one_click.simulate"

STORY_CARD_TASK = "story_character_card_generate"
STORY_REACTION_TASK = "story_reaction_propose"
STORY_SCRIPT_TASK = "story_scene_script_generate"
STORY_ONE_CLICK_TASK = "story_one_click"

STORY_GENERATION_TIMEOUT_SECONDS = 1800
STORY_INPUT_MAX_CHARS = 96_000
STORY_OUTPUT_MAX_CHARS = 48_000


class _CardOutput(StorySchema):
    content: CharacterCardContent
    warnings: list[str] = []


class StoryGenerationService:
    """Build deterministic prompts and run one strict, read-only LLM step."""

    @staticmethod
    def _data_block(name: str, value: Any) -> str:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        return f"<{name}>\n{encoded}\n</{name}>"

    @classmethod
    def _request(
        cls,
        client: Any,
        *,
        purpose: str,
        context_markdown: str,
        scene_context: dict[str, Any],
        target: dict[str, Any],
        schema: type[StorySchema],
    ) -> LLMCallRequest:
        bounded_context = context_markdown[:STORY_INPUT_MAX_CHARS]
        system = (
            "你是作者工作台中的受控小说规划助手。只依据输入资料和作者意图提出可编辑"
            "的预览，不把推断写成已采用事实，不修改任何资产。硬锚点优先于软目标；"
            "人物只能使用输入中明确提供的知识和性格，无法确定的内容放入 warnings 或"
            "unresolved_questions。严格只输出 JSON，不要解释。"
        )
        user = "\n".join(
            [
                f"PURPOSE: {purpose}",
                cls._data_block("AUTHORITATIVE_SCENE_CONTEXT", scene_context),
                cls._data_block("COMPILED_CONTEXT", bounded_context),
                cls._data_block("REQUESTED_TARGET", target),
                cls._data_block("OUTPUT_SCHEMA", schema.model_json_schema()),
            ]
        )
        return LLMCallRequest(
            model=client.model_name,
            messages=[
                LLMMessage(role="system", content=system),
                LLMMessage(role="user", content=user),
            ],
            temperature=0.45,
            response_format={"type": "json_object"},
        )

    @staticmethod
    async def _run(
        client: Any,
        request: LLMCallRequest,
        schema: type[StorySchema],
        *,
        step_name: str,
    ) -> StorySchema:
        return await run_managed_structured(
            client,
            request,
            schema,
            step_name=step_name,
            max_fix_attempts=2,
            format_repair_attempts=1,
            permission_level=AgentPermissionLevel.suggest,
            read_only=True,
            timeout=STORY_GENERATION_TIMEOUT_SECONDS,
            context_budget=ContextBudget(
                max_input_chars=STORY_INPUT_MAX_CHARS,
                max_output_chars=STORY_OUTPUT_MAX_CHARS,
            ),
        )

    async def card_preview(
        self,
        client: Any,
        *,
        context_markdown: str,
        scene_context: dict[str, Any],
        character_id: str,
        additional_notes: str | None = None,
    ) -> CardPreview:
        target = {
            "character_id": character_id,
            "additional_notes": additional_notes or "",
        }
        output = await self._run(
            client,
            self._request(
                client,
                purpose="character_card_preview",
                context_markdown=context_markdown,
                scene_context=scene_context,
                target=target,
                schema=_CardOutput,
            ),
            _CardOutput,
            step_name="story.character_card.generate.structured",
        )
        return CardPreview(
            character_id=character_id,
            content=output.content,
            warnings=output.warnings,
        )

    async def reaction_preview(
        self,
        client: Any,
        *,
        context_markdown: str,
        scene_context: dict[str, Any],
        character_ids: list[str],
        additional_notes: str | None = None,
    ) -> ReactionPreview:
        output = await self._run(
            client,
            self._request(
                client,
                purpose="per_character_reaction_proposals",
                context_markdown=context_markdown,
                scene_context=scene_context,
                target={
                    "scene_id": scene_context.get("scene_id"),
                    "character_ids": character_ids,
                    "additional_notes": additional_notes or "",
                },
                schema=ReactionPreview,
            ),
            ReactionPreview,
            step_name="story.reaction.generate.structured",
        )
        return output

    async def script_preview(
        self,
        client: Any,
        *,
        context_markdown: str,
        scene_context: dict[str, Any],
        character_ids: list[str],
        additional_notes: str | None = None,
        accepted_reactions: list[dict[str, Any]] | None = None,
        accepted_beats: list[dict[str, Any]] | None = None,
    ) -> ScriptPreview:
        output = await self._run(
            client,
            self._request(
                client,
                purpose="scene_script_preview",
                context_markdown=context_markdown,
                scene_context=scene_context,
                target={
                    "scene_id": scene_context.get("scene_id"),
                    "character_ids": character_ids,
                    "additional_notes": additional_notes or "",
                    "accepted_reactions": accepted_reactions or [],
                    "accepted_beats": accepted_beats or [],
                },
                schema=ScriptPreview,
            ),
            ScriptPreview,
            step_name="story.script.generate.structured",
        )
        return output

    async def one_click_preview(
        self,
        client: Any,
        *,
        context_markdown: str,
        scene_context: dict[str, Any],
        character_ids: list[str],
        additional_notes: str | None = None,
        accepted_reactions: list[dict[str, Any]] | None = None,
        accepted_beats: list[dict[str, Any]] | None = None,
    ) -> OneClickOutput:
        output = await self._run(
            client,
            self._request(
                client,
                purpose="full_scene_one_click_preview",
                context_markdown=context_markdown,
                scene_context=scene_context,
                target={
                    "scene_id": scene_context.get("scene_id"),
                    "character_ids": character_ids,
                    "additional_notes": additional_notes or "",
                    "accepted_reactions": accepted_reactions or [],
                    "accepted_beats": accepted_beats or [],
                },
                schema=OneClickOutput,
            ),
            OneClickOutput,
            step_name="story.one_click.structured",
        )
        return output
