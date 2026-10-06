"""LLM 运行管道：质量复核、知识治理、决策护栏与消息装配。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from core.errors import ValidationError
from infrastructure.llm.agent_step_harness import run_managed_structured
from infrastructure.llm.client import LLMClient
from infrastructure.llm.errors import LLMInvalidResponseError
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.world.llm_schemas import (
    GeneratedObjectDraftOutput,
    GeneratedWorldGenerationDecisionAudit,
    GeneratedWorldGenerationDecisionState,
)
from modules.world.schemas import (
    WorldGenerationRequestBase,
    WorldGenerationSuggestionRequest,
)
from modules.world.services.worldbuilding.generation_center.shared import (
    _DECISION_AUDIT_SYSTEM_PROMPT,
    _QUALITY_REVIEW_INSTRUCTION,
    WORLD_GENERATION_TIMEOUT_SECONDS,
)


class _LlmRunStageMixin:
    async def _run_structured_with_quality_review(
        self,
        client: LLMClient,
        request: LLMCallRequest,
        schema: type[Any],
        *,
        step_name: str,
        quality_mode: str,
    ) -> Any:
        generated = await run_managed_structured(
            client,
            request,
            schema,
            step_name=step_name,
            max_fix_attempts=2,
            timeout=WORLD_GENERATION_TIMEOUT_SECONDS,
        )
        if quality_mode != "pro":
            return generated
        payload = (
            generated.model_dump(mode="json")
            if hasattr(generated, "model_dump")
            else generated
        )
        review_request = request.model_copy(deep=True)
        review_request.messages.extend(
            [
                LLMMessage(
                    role="assistant",
                    content=json.dumps(payload, ensure_ascii=False, default=str),
                ),
                LLMMessage(role="user", content=_QUALITY_REVIEW_INSTRUCTION),
            ]
        )
        return await run_managed_structured(
            client,
            review_request,
            schema,
            step_name=f"{step_name}.quality_review",
            max_fix_attempts=2,
            timeout=WORLD_GENERATION_TIMEOUT_SECONDS,
        )

    async def _govern_structured(
        self,
        client: LLMClient,
        *,
        capability: str,
        novel_id: str,
        prepared: dict[str, Any],
        generated: Any,
        request: LLMCallRequest,
        schema: type[Any],
        decision_state: GeneratedWorldGenerationDecisionState | None,
        step_name: str,
        quality_mode: str,
        task_instruction: str,
        normalize: Callable[[Any, Any | None], Any] | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        """全知审查结构化提案（+≤1 次同 schema 返修 → 复审）。

        返回 (最终提案, knowledge_review)。blocked 时最终提案为最后一次受审
        输出：调用方仍可保存为不可采用 candidate，但不得当作已审查通过。
        quality_mode=fast 只省略 pro 润色，知识审查不可跳（ADR-0025）。
        """
        from modules.evidence.contracts import REPAIR_INSTRUCTION_TEMPLATE
        from modules.world.services.worldbuilding.knowledge_governance import (
            govern_world_output,
            serialize_governed_output,
        )

        validation_error = None
        if normalize is not None:
            try:
                generated = normalize(generated, None)
            except (ValidationError, PydanticValidationError) as exc:
                validation_error = (
                    json.dumps(
                        exc.errors(
                            include_input=False, include_context=False, include_url=False
                        ),
                        ensure_ascii=False,
                    )
                    if isinstance(exc, PydanticValidationError)
                    else str(exc)
                )
        holder: dict[str, Any] = {"output": generated}

        async def _repair(findings_block: str) -> str:
            repair_request = request.model_copy(deep=True)
            repair_request.messages.extend(
                [
                    LLMMessage(
                        role="assistant",
                        content=serialize_governed_output(holder["output"]),
                    ),
                    LLMMessage(
                        role="user",
                        content=REPAIR_INSTRUCTION_TEMPLATE.format(
                            findings_block=findings_block
                        ),
                    ),
                ]
            )
            if normalize is not None:
                repair_request.messages.append(
                    LLMMessage(
                        role="user",
                        content="按上一份提案提交修正字段；未提及条目保留，"
                        "清空字段须显式给空值，弃用条目标 deprecated。"
                        "修改前提、数量或规则时，同步所有受影响的字段、情境、"
                        "压力测试和计算；省略的旧结论仍会保留，不能只改规则。"
                        "先核对库存、消耗与持续时间的计算，再统一各处结论。"
                        "summary 只概括修正后内容，不声称执行了保存、审查"
                        "或并未实际发生的状态变更。",
                    )
                )
            repaired = await self._run_structured_with_decision_guard(
                client,
                repair_request,
                schema,
                decision_state=decision_state,
                step_name=f"{step_name}.knowledge.repair",
                quality_mode=quality_mode,
            )
            if normalize is not None:
                repaired = normalize(repaired, holder["output"])
            holder["output"] = repaired
            return serialize_governed_output(repaired)

        if validation_error is not None:
            # Use the same single repair allowance for a deterministic boundary
            # failure; a bad repair fails closed before the knowledge audit.
            await _repair("输出未通过服务端变化校验：" + validation_error)
        result = await govern_world_output(
            client,
            capability=capability,
            novel_id=novel_id,
            source_refs=prepared["source_refs"],
            rendered_context=self._knowledge_context(prepared),
            output=serialize_governed_output(holder["output"]),
            task_instruction=task_instruction,
            author_requirements=self._author_requirements_projection(prepared),
            repair=_repair if validation_error is None else None,
            step_prefix=step_name,
        )
        if validation_error is not None:
            result["review"]["repaired"] = True
        return holder["output"], result["review"]

    async def _govern_text(
        self,
        client: LLMClient,
        *,
        capability: str,
        novel_id: str,
        prepared: dict[str, Any],
        text: str,
        task_instruction: str,
        repair: Callable[[str], Awaitable[str]] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """全知审查自由文本（chat 等展示类；不可修复的直接阻断）。

        返回 (最终正文, knowledge_review)；blocked 时正文为面向作者的阻断说明，
        不包含任何生成内容。
        """
        from modules.world.services.worldbuilding.knowledge_governance import (
            govern_world_output,
            knowledge_blocked_reply,
        )

        result = await govern_world_output(
            client,
            capability=capability,
            novel_id=novel_id,
            source_refs=prepared["source_refs"],
            rendered_context=self._knowledge_context(prepared),
            output=text,
            task_instruction=task_instruction,
            author_requirements=self._author_requirements_projection(prepared),
            repair=repair,
        )
        if result["status"] == "passed":
            return result["text"], result["review"]
        return knowledge_blocked_reply(), result["review"]

    async def _run_structured_with_decision_guard(
        self,
        client: LLMClient,
        request: LLMCallRequest,
        schema: type[Any],
        *,
        decision_state: GeneratedWorldGenerationDecisionState | None,
        step_name: str,
        quality_mode: str,
    ) -> Any:
        request.messages.append(
            LLMMessage(
                role="user",
                content=self._output_contract_message(schema),
            )
        )
        for guard_attempt in range(2):
            generated = await self._run_structured_with_quality_review(
                client,
                request,
                schema,
                step_name=step_name,
                quality_mode=quality_mode,
            )
            violations = self._decision_state_violations(
                generated,
                decision_state,
            )
            if not violations and decision_state is not None:
                audit = await self._audit_proposal_decisions(
                    client,
                    request,
                    generated,
                    decision_state,
                    step_name=step_name,
                )
                if audit.verdict == "revise":
                    violations.extend(audit.violations or ["提案越过作者决策边界"])
            if not violations:
                return generated
            if guard_attempt == 0:
                request.messages.append(
                    LLMMessage(
                        role="user",
                        content=(
                            "上一份提案违反了 AUTHOR_DECISION_STATE，不能进入待处理队列。"
                            "请从当前作者决策重新生成，不要解释修复过程。违反项："
                            + json.dumps(violations, ensure_ascii=False)
                        ),
                    )
                )
                continue
            raise LLMInvalidResponseError(
                "World generation proposal violated the compiled author decisions",
                provider=str(client.provider),
                model=request.model,
                raw_response=json.dumps(violations, ensure_ascii=False),
            )
        raise AssertionError("unreachable decision guard state")

    async def _audit_proposal_decisions(
        self,
        client: LLMClient,
        source_request: LLMCallRequest,
        generated: Any,
        decision_state: GeneratedWorldGenerationDecisionState,
        *,
        step_name: str,
    ) -> GeneratedWorldGenerationDecisionAudit:
        payload = (
            generated.model_dump(mode="json")
            if hasattr(generated, "model_dump")
            else generated
        )
        return await run_managed_structured(
            client,
            LLMCallRequest(
                model=source_request.model,
                messages=[
                    LLMMessage(role="system", content=_DECISION_AUDIT_SYSTEM_PROMPT),
                    LLMMessage(
                        role="user",
                        content=(
                            self._author_decision_state_block(decision_state)
                            + "\n<CANDIDATE_PROPOSAL>\n"
                            + json.dumps(
                                payload,
                                ensure_ascii=False,
                                indent=2,
                                default=str,
                            )
                            + "\n</CANDIDATE_PROPOSAL>"
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=self._output_contract_message(
                            GeneratedWorldGenerationDecisionAudit
                        ),
                    ),
                ],
                temperature=0.0,
            ),
            GeneratedWorldGenerationDecisionAudit,
            step_name=f"{step_name}.author_decision_audit",
            max_fix_attempts=2,
            timeout=WORLD_GENERATION_TIMEOUT_SECONDS,
        )

    @staticmethod
    def _output_contract_message(schema: type[Any]) -> str:
        return (
            "<OUTPUT_CONTRACT>\n"
            + json.dumps(
                schema.model_json_schema(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n</OUTPUT_CONTRACT>\n"
            "直接输出一个匹配该 schema 的 JSON 对象；不要添加外层包装。"
        )

    @staticmethod
    def _author_decision_state_block(
        decision_state: GeneratedWorldGenerationDecisionState,
    ) -> str:
        """与生成器同源的作者决定冻结投影；生成、决策审计与知识审查共用。"""
        return (
            "<AUTHOR_DECISION_STATE>\n"
            + json.dumps(
                decision_state.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            )
            + "\n</AUTHOR_DECISION_STATE>"
        )

    @classmethod
    def _author_requirements_projection(cls, prepared: dict[str, Any]) -> str:
        conversation = prepared.get("conversation_messages") or []
        parts = (
            [
                "<AUTHOR_CONVERSATION>\n"
                + json.dumps(
                    [item.model_dump(mode="json") for item in conversation],
                    ensure_ascii=False,
                )
                + "\n</AUTHOR_CONVERSATION>\n助手消息仍是建议，不能充当作者已确认事实。"
            ]
            if conversation
            else []
        )
        decision_state = prepared.get("decision_state")
        if decision_state is not None:
            parts.append(cls._author_decision_state_block(decision_state))
        return "\n\n".join(parts)

    @staticmethod
    def _knowledge_context(prepared: dict[str, Any]) -> str:
        return prepared.get(
            "knowledge_context", str(prepared["background"].get("rendered_context") or "")
        )

    @staticmethod
    def _decision_state_violations(
        generated: Any,
        decision_state: GeneratedWorldGenerationDecisionState | None,
    ) -> list[str]:
        if decision_state is None:
            return []
        if hasattr(generated, "model_dump"):
            payload = generated.model_dump(mode="json")
        else:
            payload = generated
        rendered = json.dumps(payload, ensure_ascii=False, default=str).casefold()
        violations = [
            f"提案重新使用已作废内容：{term}"
            for term in decision_state.forbidden_exact_terms
            if term.casefold() in rendered
        ]
        if (
            isinstance(generated, GeneratedObjectDraftOutput)
            and decision_state.naming_policy in {"unnamed_placeholder", "uncertain"}
            and not generated.name.strip().startswith(("未命名", "暂未命名"))
        ):
            violations.append("作者尚未允许命名，name 必须使用未命名占位符")
        return violations


    def _structured_messages(
        self,
        data: WorldGenerationSuggestionRequest,
        prepared: dict[str, Any],
        *,
        system_prompt: str,
        final_instruction: str,
    ) -> list[LLMMessage]:
        messages = [
            LLMMessage(
                role="system", content=system_prompt + "\n\n" + self._target_brief(data)
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
        decision_state: GeneratedWorldGenerationDecisionState | None = prepared.get(
            "decision_state"
        )
        if decision_state is None:
            messages.extend(
                LLMMessage(role=item.role, content=item.content)
                for item in prepared.get("conversation_messages", data.messages)
            )
        else:
            messages.append(
                LLMMessage(
                    role="user",
                    content=(
                        self._author_decision_state_block(decision_state)
                        + "\n这是完整对话编译后的当前作者边界。只使用已确认要求和受支持的"
                        "发展；不得恢复已否定内容，不替作者解决未决选择，也不得越过"
                        "知识与表达边界。"
                    ),
                )
            )
        if data.exploration_selection is not None:
            messages.append(
                LLMMessage(
                    role="user",
                    content=(
                        "<AUTHOR_SELECTED_EXPLORATION>\n"
                        + json.dumps(
                            data.exploration_selection.model_dump(mode="json"),
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n</AUTHOR_SELECTED_EXPLORATION>\n"
                        "作者只选择了这一项。生成一个独立的新页面建议，不得继续下一跳，"
                        "也不得引入未选择的探索项。"
                    ),
                )
            )
        messages.append(LLMMessage(role="user", content=final_instruction))
        return messages

    def _reference_message(
        self,
        data: WorldGenerationRequestBase,
        prepared: dict[str, Any],
    ) -> str:
        reference: dict[str, Any] = {
            "saved_author_workspace": (prepared.get("session_context") or {}).get(
                "model_context"
            ),
            "source_world_bible_page": self._source_page_for_prompt(prepared),
            "page_layout_reference": self._page_template_for_prompt(prepared),
            "allowed_page_types": prepared["allowed_page_types"],
            "existing_page_catalog": prepared["page_catalog"],
            "available_asset_references": prepared["assets"]["items"],
            "selected_chapters": prepared["chapters"],
            "world_background": prepared["background"].get("rendered_context", ""),
            "author_reference": data.pasted_context,
        }
        return (
            "<UNTRUSTED_REFERENCE_DATA>\n"
            + json.dumps(reference, ensure_ascii=False, default=str, indent=2)
            + "\n</UNTRUSTED_REFERENCE_DATA>"
        )

    @staticmethod
    def _source_page_for_prompt(prepared: dict[str, Any]) -> dict[str, Any] | None:
        source = prepared.get("source_page_data")
        if not source:
            return None
        hash_to_key = prepared["assets"]["hash_to_key"]
        sections = []
        for index, raw in enumerate(source["sections_json"]):
            section = dict(raw)
            sections.append(
                {
                    "source_section_key": f"S{index + 1}",
                    "section_type": section.get("section_type", "markdown"),
                    "title": section.get("title", ""),
                    "body_markdown": section.get("body_markdown", ""),
                    "linked_asset_keys": [
                        hash_to_key[str(item).removeprefix("sha256:")]
                        for item in section.get("linked_asset_ref_hashes") or []
                        if str(item).removeprefix("sha256:") in hash_to_key
                    ],
                }
            )
        return {
            "title": source["title"],
            "page_type": source["page_type"],
            "overview": source["free_text"],
            "sections": sections,
            "linked_asset_keys": list(prepared["assets"]["by_key"]),
        }

    @staticmethod
    def _page_template_for_prompt(prepared: dict[str, Any]) -> dict[str, Any] | None:
        template = prepared.get("page_template")
        if template is None:
            return None
        return {
            "name": template.name,
            "description": template.description,
            "category_key_hint": template.category_key_hint,
            "sections_schema": template.sections_schema_json,
            "default_sections": [
                item.model_dump(mode="json") for item in template.default_sections_json
            ],
        }
