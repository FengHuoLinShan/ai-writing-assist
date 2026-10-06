"""生成中心聊天阶段：对话回复与消息组装。"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.agent_step_harness import run_managed_generate
from infrastructure.llm.client import LLMClient
from infrastructure.llm.errors import LLMInvalidResponseError
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.world.llm_schemas import GeneratedWorldGenerationChatOutput
from modules.world.schemas import WorldGenerationChatRequest, WorldGenerationChatResponse
from modules.world.services.worldbuilding.generation_center.shared import (
    _CHAT_SYSTEM_PROMPT,
    _QUALITY_REVIEW_INSTRUCTION,
    _WORLD_CORE_CHAT_BOUNDARY,
    WORLD_GENERATION_TIMEOUT_SECONDS,
    _cocreation_step_capability,
)


class _ChatStageMixin:
    async def chat(
        self,
        db: AsyncSession,
        data: WorldGenerationChatRequest,
        *,
        llm_execution_snapshot: dict[str, Any] | None = None,
    ) -> WorldGenerationChatResponse:
        if llm_execution_snapshot is None:
            execution_snapshot, model = await self._freeze_execution_snapshot(
                db, data.novel_id
            )
        else:
            execution_snapshot = llm_execution_snapshot
            model = str(execution_snapshot["profile"]["model"])
        prepared = await self._prepare(
            db,
            data,
            operation="world.generation.chat",
            model=model,
        )
        try:
            async with self._open_client(
                db,
                data.novel_id,
                execution_snapshot=execution_snapshot,
                high_quality=data.quality_mode == "pro",
            ) as client:
                request = LLMCallRequest(
                    model=model,
                    messages=self._chat_messages(data, prepared),
                    temperature=0.8,
                )
                async with asyncio.timeout(WORLD_GENERATION_TIMEOUT_SECONDS):
                    response = await self._generate_chat_reply(client, request)
                    if data.quality_mode == "pro":
                        review_request = request.model_copy(deep=True)
                        review_request.messages.extend(
                            [
                                LLMMessage(role="assistant", content=response.reply),
                                LLMMessage(
                                    role="user",
                                    content=_QUALITY_REVIEW_INSTRUCTION,
                                ),
                            ]
                        )
                        response = await self._generate_chat_reply(
                            client,
                            review_request,
                        )

                    async def repair_chat(findings: str) -> str:
                        from modules.evidence.contracts import REPAIR_INSTRUCTION_TEMPLATE

                        repair_request = request.model_copy(deep=True)
                        repair_request.messages.extend(
                            [
                                LLMMessage(role="assistant", content=response.reply),
                                LLMMessage(
                                    role="user",
                                    content=REPAIR_INSTRUCTION_TEMPLATE.format(
                                        findings_block=findings
                                    ),
                                ),
                            ]
                        )
                        repaired = await self._generate_chat_reply(
                            client,
                            repair_request,
                            step_name="world.generation.chat.knowledge.repair",
                        )
                        return repaired.reply

                    reply_text, knowledge_review = await self._govern_text(
                        client,
                        capability="world.generation.chat",
                        novel_id=data.novel_id,
                        prepared=prepared,
                        text=response.reply,
                        task_instruction="回答作者关于当前世界设定的创作问题",
                        repair=repair_chat,
                    )
                    response = GeneratedWorldGenerationChatOutput(reply=reply_text)
                provider = str(client.provider)
            await self._revalidate_source(db, data, prepared)
        except Exception as exc:
            await self._finish_context_snapshot(
                db, data.novel_id, prepared["background"], error=exc
            )
            raise
        await self._finish_context_snapshot(
            db,
            data.novel_id,
            prepared["background"],
            result_refs=[
                {
                    "type": "world_generation_chat",
                    "id": self._context_snapshot_id(prepared["background"])
                    or "ephemeral",
                }
            ],
        )
        return WorldGenerationChatResponse(
            reply=response.reply,
            model=model,
            provider=provider,
            context_usage=self._context_usage(prepared["background"]),
            source_snapshot=prepared["source_snapshot"],
            knowledge_review=knowledge_review,
        )

    @staticmethod
    async def _generate_chat_reply(
        client: LLMClient,
        request: LLMCallRequest,
        *,
        step_name: str = "world.generation.chat.reply",
    ) -> GeneratedWorldGenerationChatOutput:
        """Generate natural chat text without DeepSeek's lossy JSON mode."""
        async with asyncio.timeout(WORLD_GENERATION_TIMEOUT_SECONDS):
            for attempt in range(2):
                # 受管入口：自由问答的真实 provider 请求也要能归属到运行信封
                # 的显式 step；无信封时受管包装是透传。
                response = await run_managed_generate(
                    client,
                    request,
                    step_name=step_name,
                    capability_id=_cocreation_step_capability("world.generation.chat"),
                )
                try:
                    return GeneratedWorldGenerationChatOutput(reply=response.content)
                except PydanticValidationError as exc:
                    if attempt == 1:
                        raise LLMInvalidResponseError(
                            "World generation chat returned no usable "
                            "natural-language reply",
                            provider=str(client.provider),
                        ) from exc
                    request.messages.append(
                        LLMMessage(
                            role="user",
                            content=(
                                "上一轮没有返回可见的自然语言内容。请直接回应作者当前的"
                                "创作问题，不要输出 JSON、空白或协议包装。"
                            ),
                        )
                    )


    def _chat_messages(
        self,
        data: WorldGenerationChatRequest,
        prepared: dict[str, Any],
    ) -> list[LLMMessage]:
        messages = [
            LLMMessage(
                role="system",
                content=(
                    f"{_CHAT_SYSTEM_PROMPT}\n\n{self._target_brief(data)}"
                    + (
                        f"\n\n{_WORLD_CORE_CHAT_BOUNDARY}"
                        if data.workflow_preset == "world_core"
                        else ""
                    )
                ),
            )
        ]
        if prepared.get("object_template") is not None:
            template = prepared["object_template"]
            messages.append(
                LLMMessage(
                    role="user",
                    content=(
                        "<AUTHOR_OBJECT_TEMPLATE_INSTRUCTION>\n"
                        f"对象模板：{template.label}\n{template.rendered_prompt}\n"
                        "</AUTHOR_OBJECT_TEMPLATE_INSTRUCTION>"
                    ),
                )
            )
        messages.append(
            LLMMessage(role="user", content=self._reference_message(data, prepared))
        )
        messages.extend(
            LLMMessage(role=item.role, content=item.content)
            for item in prepared.get("conversation_messages", data.messages)
        )
        if not data.messages:
            messages.append(
                LLMMessage(
                    role="user",
                    content="请根据当前目标和资料，先给出一个具体、可评价的切入方案。",
                )
            )
        return messages
