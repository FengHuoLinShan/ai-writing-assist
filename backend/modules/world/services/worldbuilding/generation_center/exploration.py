"""探查阶段：世界缺口探查与会话决策状态合并。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, ValidationError
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.world.llm_schemas import (
    GeneratedWorldGenerationDecisionState,
    GeneratedWorldGenerationExplorationOutput,
    normalize_decision_text,
)
from modules.world.schemas import (
    CoreEntityDraftSuggestionPayload,
    CreationSuggestionResponse,
    WorldBiblePageDraftSuggestionPayload,
    WorldGenerationCoreEntityTarget,
    WorldGenerationExplorationRequest,
    WorldGenerationExplorationResponse,
    WorldGenerationExplorationSelection,
    WorldGenerationExplorationTarget,
    WorldGenerationNewPageTarget,
    WorldGenerationRequestBase,
    WorldGenerationSourceSnapshot,
    WorldGenerationSuggestionRequest,
)
from modules.world.services.worldbuilding.generation_center.shared import (
    _CONVERGENCE_CALL_INPUT_CHARS,
    _DECISION_STATE_SYSTEM_PROMPT,
    _EXPLORATION_SYSTEM_PROMPT,
    _WORLD_DESIGN_TASK_BRIEF_INSTRUCTION,
    WORLD_GENERATION_TIMEOUT_SECONDS,
)
from modules.world.services.worldbuilding.generation_prompt_template_service import (
    TEMPLATE_ENTITY_TYPES,
    ResolvedGenerationTemplate,
)
from modules.world.services.worldbuilding.knowledge_governance import (
    serialize_governed_output,
)
from modules.world.services.worldbuilding.structured_reference_retry import (
    run_structured_with_known_keys,
)


class _ExplorationStageMixin:
    async def explore(
        self,
        db: AsyncSession,
        data: WorldGenerationExplorationRequest,
    ) -> WorldGenerationExplorationResponse:
        """List at most three adjacent gaps without creating project assets."""
        execution_snapshot, model = await self._freeze_execution_snapshot(
            db,
            data.novel_id,
        )
        prepared = await self._prepare(
            db,
            data,
            operation="world.generation.exploration",
            model=model,
        )
        fingerprint = self._exploration_fingerprint(data, prepared)
        generated = GeneratedWorldGenerationExplorationOutput(
            targets=[],
            stop_reason="当前来源没有足够材料支持一条有后果的相邻探索。",
        )
        provider = ""
        knowledge_review: dict[str, Any] | None = None
        try:
            sources = self._convergence_sources(data, prepared)
            if sources:
                async with self._open_client(
                    db,
                    data.novel_id,
                    execution_snapshot=execution_snapshot,
                    high_quality=data.quality_mode == "pro",
                ) as client:
                    provider = str(client.provider)
                    async with asyncio.timeout(WORLD_GENERATION_TIMEOUT_SECONDS):
                        generated = await self._run_exploration_pass(
                            client,
                            data,
                            sources,
                            model=model,
                        )
                    _text, knowledge_review = await self._govern_text(
                        client,
                        capability="world.generation.exploration",
                        novel_id=data.novel_id,
                        prepared=prepared,
                        text=serialize_governed_output(generated),
                        task_instruction="列出最多三条有后果的相邻设定缺口，不虚构事实",
                    )
                    if knowledge_review.get("status") != "passed":
                        generated = GeneratedWorldGenerationExplorationOutput(
                            targets=[],
                            stop_reason=(
                                "探索结果未通过知识审查，已整体扣留；"
                                "请调整来源范围后重试。"
                            ),
                        )
                await self._revalidate_source(db, data, prepared)
        except Exception as exc:
            await self._finish_context_snapshot(
                db,
                data.novel_id,
                prepared["background"],
                error=exc,
            )
            raise
        await self._finish_context_snapshot(
            db,
            data.novel_id,
            prepared["background"],
            result_refs=[{"type": "world_generation_exploration", "id": fingerprint}],
        )
        return self._exploration_response(
            data,
            prepared,
            sources,
            generated,
            fingerprint=fingerprint,
            model=model,
            provider=provider,
            knowledge_review=knowledge_review,
        )


    @staticmethod
    def _validate_revision_parent(
        data: WorldGenerationSuggestionRequest,
        prepared: dict[str, Any],
        parent: CreationSuggestionResponse,
    ) -> None:
        if isinstance(data.target, WorldGenerationCoreEntityTarget):
            if parent.target_type not in {"core_entity", "core_entity_draft"}:
                raise ValidationError("The selected suggestion has a different target")
            payload = CoreEntityDraftSuggestionPayload.model_validate(parent.payload_json)
            template: ResolvedGenerationTemplate = prepared["object_template"]
            if payload.entity_type != TEMPLATE_ENTITY_TYPES.get(
                template.object_template,
                "concept",
            ):
                raise ValidationError("The selected suggestion has a different target")
            return

        if parent.target_type != "world_bible_page_draft":
            raise ValidationError("The selected suggestion has a different target")
        payload = WorldBiblePageDraftSuggestionPayload.model_validate(parent.payload_json)
        if isinstance(data.target, WorldGenerationNewPageTarget):
            if (
                payload.operation != "create_new"
                or payload.page.page_type != data.target.page_type
            ):
                raise ValidationError("The selected suggestion has a different target")
            return

        snapshot: WorldGenerationSourceSnapshot = prepared["source_snapshot"]
        baseline = payload.baseline
        if (
            payload.operation != "replace_existing"
            or payload.target_page_id != data.target.page_id
            or baseline is None
            or baseline.page_version != snapshot.page_version
            or baseline.draft_id != snapshot.draft_id
            or baseline.draft_updated_at != snapshot.draft_updated_at
            or baseline.content_hash != snapshot.content_hash
        ):
            raise ConflictError(
                "The selected suggestion was generated from a different page version"
            )

    def _validate_exploration_selection(
        self,
        data: WorldGenerationSuggestionRequest,
        prepared: dict[str, Any],
    ) -> None:
        selection = data.exploration_selection
        if selection is None:
            return
        if selection.request_fingerprint != self._exploration_fingerprint(data, prepared):
            raise ConflictError(
                "The world exploration source or author-selected context changed"
            )
        source_keys = {
            item["manifest"].key for item in self._convergence_sources(data, prepared)
        }
        if any(key not in source_keys for key in selection.source_keys):
            raise ConflictError("The selected world exploration evidence changed")

    @staticmethod
    def _merge_saved_decisions(prepared):
        checkpoint = (prepared.get("session_context") or {}).get("checkpoint") or {}
        authority = (checkpoint.get("world_state") or {}).get("authority") or {}
        decisions = checkpoint.get("decisions") or []
        state = prepared.get("decision_state")
        if not decisions and not any(
            authority.get(key)
            for key in (
                "constraints",
                "locked_decisions",
                "open_questions",
                "author_required",
            )
        ):
            return state
        goal = next(
            (
                item.content
                for item in reversed(prepared["conversation_messages"])
                if item.role == "user"
            ),
            "整理当前世界模型",
        )
        if state is None and len(goal) > 4000:
            raise ValidationError(
                "本轮目标过长，请把核心要求写短，并将长材料作为参考加入"
            )
        payload = (
            state.model_dump()
            if state
            else {"current_author_goal": goal, "confidence": 1.0}
        )
        decision_texts = {normalize_decision_text(item["text"]) for item in decisions}
        for field, disposition in (
            ("confirmed_requirements", "locked"),
            ("rejected_elements", "rejected"),
            ("unresolved_choices", "open"),
        ):
            durable = [
                item["text"] for item in decisions if item["disposition"] == disposition
            ]
            groups = {
                "confirmed_requirements": ("locked_decisions",),
                "unresolved_choices": ("open_questions", "author_required"),
            }.get(field, ())
            durable.extend(
                item["question"]
                for group in groups
                for item in authority.get(group, [])
                if item.get("status") != "deprecated"
            )
            if field == "confirmed_requirements":
                # authority.constraints 是作者权威区硬约束：与既有决定同文的条目已按
                # 决定本身归类；其余只能作为锁定要求，不得落入 rejected_elements
                # 与 confirmed 形成同一约束既要遵守又要拒绝的矛盾任务卡。
                durable.extend(
                    text
                    for text in (authority.get("constraints") or [])
                    if normalize_decision_text(text) not in decision_texts
                )
            payload[field] = list(dict.fromkeys([*durable, *payload.get(field, [])]))
        try:
            return GeneratedWorldGenerationDecisionState.model_validate(payload)
        except PydanticValidationError as exc:
            raise ValidationError(
                "本轮有效决定超出审查容量，请整理作用范围后继续；未丢弃任何决定"
            ) from exc

    @staticmethod
    def _merge_exploration_decision_state(
        state: GeneratedWorldGenerationDecisionState | None,
        selection: WorldGenerationExplorationSelection | None,
    ) -> GeneratedWorldGenerationDecisionState | None:
        if selection is None:
            return state
        scope = f"本次只探索「{selection.title}」：{selection.gap}"
        reverse = f"生成后只反查来源页这一点：{selection.reverse_check_focus}"
        if state is None:
            return GeneratedWorldGenerationDecisionState(
                current_author_goal=scope,
                confirmed_requirements=[scope, reverse],
                unresolved_choices=[selection.author_boundary],
                naming_policy="allowed",
                confidence=1.0,
            )
        payload = state.model_dump(mode="json")
        payload["current_author_goal"] = f"{state.current_author_goal}\n{scope}"[:4000]
        payload["confirmed_requirements"] = list(
            dict.fromkeys([*state.confirmed_requirements, scope, reverse])
        )[:64]
        payload["unresolved_choices"] = list(
            dict.fromkeys([*state.unresolved_choices, selection.author_boundary])
        )[:64]
        return GeneratedWorldGenerationDecisionState.model_validate(payload)

    @staticmethod
    def _exploration_fingerprint(
        data: WorldGenerationRequestBase,
        prepared: dict[str, Any],
    ) -> str:
        payload = data.model_dump(mode="json")
        for key in ("depth", "exploration_selection", "revises_suggestion_id"):
            payload.pop(key, None)
        payload["source_snapshot"] = prepared["source_snapshot"].model_dump(mode="json")
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    async def _compile_conversation_decision_state(
        self,
        client: LLMClient,
        data: WorldGenerationRequestBase,
        *,
        model: str,
        force: bool = False,
        design_task: bool = False,
    ) -> GeneratedWorldGenerationDecisionState | None:
        """Compile multi-turn author decisions before materializing a suggestion."""
        user_count = sum(item.role == "user" for item in data.messages)
        if not force and (
            user_count < 2 or not any(item.role == "assistant" for item in data.messages)
        ):
            return None
        conversation = [item.model_dump(mode="json") for item in data.messages]
        task_frame = {
            "action": getattr(data, "action", None),
            "focus_sections": data.world_state_sections,
        }
        return await self._run_structured_with_quality_review(
            client,
            LLMCallRequest(
                model=model,
                messages=[
                    LLMMessage(
                        role="system",
                        content=_DECISION_STATE_SYSTEM_PROMPT
                        + (
                            "\n" + _WORLD_DESIGN_TASK_BRIEF_INSTRUCTION
                            if design_task
                            else ""
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=(
                            "<UNTRUSTED_CONVERSATION_DATA>\n"
                            + json.dumps(
                                {"task_frame": task_frame, "conversation": conversation},
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                            + "\n</UNTRUSTED_CONVERSATION_DATA>\n"
                            "编译当前作者决策状态。保留未决项，明确列出已作废的专名和短语；"
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=self._output_contract_message(
                            GeneratedWorldGenerationDecisionState
                        ),
                    ),
                ],
                temperature=0.0,
            ),
            GeneratedWorldGenerationDecisionState,
            step_name="world.generation.conversation_decision_state",
            quality_mode=data.quality_mode,
        )


    def _exploration_request(
        self,
        data: WorldGenerationExplorationRequest,
        sources: list[dict[str, Any]],
        *,
        model: str,
    ) -> LLMCallRequest:
        manifest = [
            {
                **source["manifest"].model_dump(mode="json", exclude={"source_ref"}),
                "content": source["content"],
            }
            for source in sources
        ]
        encoded = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > _CONVERGENCE_CALL_INPUT_CHARS:
            raise ValidationError(
                "The selected exploration range is too large; reduce explicit context"
            )
        return LLMCallRequest(
            model=model,
            messages=[
                LLMMessage(
                    role="system",
                    content=f"{_EXPLORATION_SYSTEM_PROMPT}\n\n{self._target_brief(data)}",
                ),
                LLMMessage(
                    role="user",
                    content=(
                        "<SOURCE_MANIFEST>\n" + encoded + "\n</SOURCE_MANIFEST>\n"
                        "只列当前来源向一个相邻新世界书页的一跳缺口。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=self._output_contract_message(
                        GeneratedWorldGenerationExplorationOutput
                    ),
                ),
            ],
            temperature=0.2,
        )


    async def _run_exploration_pass(
        self,
        client: LLMClient,
        data: WorldGenerationExplorationRequest,
        sources: list[dict[str, Any]],
        *,
        model: str,
    ) -> GeneratedWorldGenerationExplorationOutput:
        request = self._exploration_request(data, sources, model=model)
        return await run_structured_with_known_keys(
            client,
            request,
            generate=lambda: self._run_structured_with_quality_review(
                client,
                request,
                GeneratedWorldGenerationExplorationOutput,
                step_name="world.generation.exploration.preview",
                quality_mode=data.quality_mode,
            ),
            known_keys={source["manifest"].key for source in sources},
            keys_of=lambda generated: (
                key for target in generated.targets for key in target.source_keys
            ),
            repair_note=(
                "上一轮引用了不存在的 source_key。只修正证据引用；"
                "不得新增目标。未知 key："
            ),
            error_message="World exploration returned unknown source keys",
        )

    def _exploration_response(
        self,
        data: WorldGenerationExplorationRequest,
        prepared: dict[str, Any],
        sources: list[dict[str, Any]],
        generated: GeneratedWorldGenerationExplorationOutput,
        *,
        fingerprint: str,
        model: str,
        provider: str,
        knowledge_review: dict[str, Any] | None = None,
    ) -> WorldGenerationExplorationResponse:
        by_key = {source["manifest"].key: source["manifest"] for source in sources}
        targets: list[WorldGenerationExplorationTarget] = []
        seen: set[tuple[str, str]] = set()
        for generated_target in generated.targets:
            identity = (
                " ".join(generated_target.title.split()).casefold(),
                " ".join(generated_target.gap.split()).casefold(),
            )
            if identity in seen:
                continue
            seen.add(identity)
            keys = list(dict.fromkeys(generated_target.source_keys))
            targets.append(
                WorldGenerationExplorationTarget(
                    item_id=f"E{len(targets) + 1}",
                    title=generated_target.title,
                    gap=generated_target.gap,
                    why_it_matters=generated_target.why_it_matters,
                    author_boundary=generated_target.author_boundary,
                    reverse_check_focus=generated_target.reverse_check_focus,
                    source_keys=keys,
                    evidence=[by_key[key] for key in keys],
                )
            )
        return WorldGenerationExplorationResponse(
            targets=targets,
            stop_reason=generated.stop_reason,
            request_fingerprint=fingerprint,
            model=model,
            provider=provider,
            context_usage=self._context_usage(prepared["background"]),
            source_snapshot=prepared["source_snapshot"],
            knowledge_review=knowledge_review,
        )
