"""Managed structured-output generation for Story previews."""

from __future__ import annotations

import hashlib
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
    ReactionPreview,
    ScriptPreview,
    StorySchema,
)


async def _noop_generate(_plan, _generator_keys) -> str:  # noqa: ANN001
    return ""


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

    async def _govern_preview(
        self,
        client: Any,
        *,
        capability: str,
        novel_id: str | None,
        context_markdown: str,
        scene_context: dict[str, Any],
        request: LLMCallRequest,
        schema: type[StorySchema],
        output: StorySchema,
    ) -> tuple[StorySchema, dict[str, Any]]:
        """全知审查预览输出（ADR-0025）：audit → ≤1 次同 schema 返修 → 复审。

        预览均为作者可编辑建议（preview_only）：blocked 时仍返回输出供作者
        参考，但 knowledge_review.status=blocked 供前端与采用路径判定；
        生成者包=编译上下文+场景上下文（服务端已裁剪），权威对照同源。
        """
        from modules.evidence.contracts import (
            REPAIR_INSTRUCTION_TEMPLATE,
            GovernedWorkflowHooks,
            KnowledgeDirectorDisposition,
            KnowledgeDirectorPlan,
            KnowledgeScopeBuild,
            KnowledgeScopeReceipt,
            KnowledgeSourceEntry,
            KnowledgeSubject,
            knowledge_review_payload,
            require_capability_policy,
            run_knowledge_audit,
        )

        policy = require_capability_policy(capability)
        context_digest = hashlib.sha256(context_markdown.encode("utf-8")).hexdigest()
        scene_digest = hashlib.sha256(
            json.dumps(scene_context, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        entries = (
            KnowledgeSourceEntry(
                source_key=f"compiled_context:{context_digest[:12]}",
                source_type="compiled_context",
                source_id="server",
                content_hash=context_digest,
                label="编译的权威上下文",
                dimensions=("world_rules", "scene_state"),
            ),
            KnowledgeSourceEntry(
                source_key=f"scene_context:{scene_digest[:12]}",
                source_type="scene_context",
                source_id=str(scene_context.get("scene_id") or "scene"),
                content_hash=scene_digest,
                label="场景执行上下文",
                dimensions=("scene_state", "character_knowledge"),
            ),
        )
        receipt = KnowledgeScopeReceipt(
            policy_version=1,
            capability=policy.capability_id,
            novel_id=str(novel_id or "story"),
            subject=KnowledgeSubject(subject_type="author"),
            included=entries,
            scope_complete=True,
            authority_fingerprint=f"{context_digest}{scene_digest}",
            generator_fingerprint=f"{context_digest}{scene_digest}",
        )
        plan = KnowledgeDirectorPlan(
            policy_version=1,
            capability=policy.capability_id,
            receipt_fingerprint=receipt.receipt_fingerprint(),
            dispositions=tuple(
                KnowledgeDirectorDisposition(
                    source_key=entry.source_key,
                    disposition="required_for_generation",
                )
                for entry in entries
            ),
        )
        plan.validate_against_receipt(receipt)
        scope_build = KnowledgeScopeBuild(
            receipt=receipt,
            generator_keys=tuple(entry.source_key for entry in entries),
            audit_only_keys=(),
        )
        holder: dict[str, Any] = {"output": output}
        review_context = "\n\n".join(
            f"【{message.role}】\n{message.content}" for message in request.messages
        )

        async def _audit(text: str):  # noqa: ANN202
            return await run_knowledge_audit(
                client,
                policy=policy,
                scope_build=scope_build,
                plan=plan,
                hooks=GovernedWorkflowHooks(
                    generate=_noop_generate,
                    task_instruction=f"生成 {policy.title} 预览，只用输入资料",
                    generator_context=review_context,
                    authority_context=review_context,
                ),
                output=text,
                step_prefix=capability,
            )

        def _serialize(item: Any) -> str:  # noqa: ANN401
            return json.dumps(
                item.model_dump(mode="json"), ensure_ascii=False, default=str
            )

        audit = await _audit(_serialize(output))
        if audit.verdict == "pass":
            return holder["output"], knowledge_review_payload(
                audit=audit, visible_keys=scope_build.generator_keys
            )

        async def _repair(findings_block: str) -> str:  # noqa: ANN202
            repair_request = request.model_copy(deep=True)
            repair_request.messages.extend(
                [
                    LLMMessage(role="assistant", content=_serialize(holder["output"])),
                    LLMMessage(
                        role="user",
                        content=REPAIR_INSTRUCTION_TEMPLATE.format(
                            findings_block=findings_block
                        ),
                    ),
                ]
            )
            repaired = await self._run(
                client,
                repair_request,
                schema,
                step_name=f"{capability}.knowledge.repair",
            )
            holder["output"] = repaired
            return _serialize(repaired)

        repaired = False
        if audit.verdict == "blocked":
            findings_block = "\n".join(
                f"- [{item.severity}] {item.kind}: {item.message}"
                for item in audit.findings
            )
            await _repair(findings_block)
            audit = await _audit(_serialize(holder["output"]))
            repaired = True
        review = knowledge_review_payload(
            audit=audit,
            repaired=repaired,
            visible_keys=scope_build.generator_keys,
        )
        return holder["output"], review

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
            "你是作者工作台中的受控小说规划助手"
            "。只依据输入资料和作者意图提出可编辑"
            "的预览，不把推断写成已采用事实，不"
            "修改任何资产。硬锚点优先于软目标；"
            "人物只能使用输入中明确提供的知识和性格，"
            "无法确定的内容放入 warnings 或"
            "unresolved_questio"
            "ns。严格只输出 JSON，不要解释。"
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
        request = self._request(
            client,
            purpose="character_card_preview",
            context_markdown=context_markdown,
            scene_context=scene_context,
            target=target,
            schema=_CardOutput,
        )
        output = await self._run(
            client,
            request,
            _CardOutput,
            step_name="story.character_card.generate.structured",
        )
        output, review = await self._govern_preview(
            client,
            capability="story.character_card",
            novel_id=str(scene_context.get("novel_id") or "") or None,
            context_markdown=context_markdown,
            scene_context=scene_context,
            request=request,
            schema=_CardOutput,
            output=output,
        )
        return CardPreview(
            character_id=character_id,
            content=output.content,
            warnings=output.warnings,
            knowledge_review=review,
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
        request = self._request(
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
        )
        output = await self._run(
            client,
            request,
            ReactionPreview,
            step_name="story.reaction.generate.structured",
        )
        output, review = await self._govern_preview(
            client,
            capability="story.reaction",
            novel_id=str(scene_context.get("novel_id") or "") or None,
            context_markdown=context_markdown,
            scene_context=scene_context,
            request=request,
            schema=ReactionPreview,
            output=output,
        )
        return output.model_copy(update={"knowledge_review": review})

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
        simulation_candidates: dict[str, Any] | None = None,
    ) -> ScriptPreview:
        request = self._request(
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
                **(
                    {
                        "simulation_candidates": simulation_candidates,
                        "candidate_authority": (
                            "仅本轮排演可用的候选，不是作者已接受的反应或正式事实"
                        ),
                    }
                    if simulation_candidates
                    else {}
                ),
            },
            schema=ScriptPreview,
        )
        output = await self._run(
            client,
            request,
            ScriptPreview,
            step_name="story.script.generate.structured",
        )
        output, review = await self._govern_preview(
            client,
            capability="story.script",
            novel_id=str(scene_context.get("novel_id") or "") or None,
            context_markdown=context_markdown,
            scene_context=scene_context,
            request=request,
            schema=ScriptPreview,
            output=output,
        )
        return output.model_copy(update={"knowledge_review": review})
