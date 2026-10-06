"""建议生成阶段：核心实体/既有页/新页提案与页建议落库。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 运行时由 service.py 在类创建后回填本模块级名字（见 service.py 尾部）。
    from modules.world.services.worldbuilding.generation_center.service import (
        WorldGenerationCenterService,
    )

import asyncio
import hashlib
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest
from infrastructure.stable_hash import stable_hash
from modules.world.llm_schemas import (
    GeneratedObjectDraftOutput,
    GeneratedWorldBibleNewPageProposal,
    GeneratedWorldBiblePageProposal,
    GeneratedWorldGenerationDecisionState,
)
from modules.world.schemas import (
    CoreEntityDraftSuggestionPayload,
    CreationSuggestionCreate,
    WorldBiblePageDraftSuggestionPayload,
    WorldBiblePageProposalContent,
    WorldBibleSection,
    WorldBibleSourceRef,
    WorldGenerationCoreEntityResult,
    WorldGenerationCoreEntityTarget,
    WorldGenerationExistingPageTarget,
    WorldGenerationNewPageTarget,
    WorldGenerationPageBaseline,
    WorldGenerationPageResult,
    WorldGenerationRequestBase,
    WorldGenerationSourceSnapshot,
    WorldGenerationSuggestionRequest,
    WorldGenerationSuggestionResponse,
)
from modules.world.services.worldbuilding.generation_center.shared import (
    _AUTHOR_OPEN_QUESTIONS_SECTION_ID,
    _CORE_ENTITY_BRIEF,
    _CORE_ENTITY_SYSTEM_PROMPT,
    _EXISTING_PAGE_BRIEF,
    _NEW_PAGE_BRIEF,
    _NEW_PAGE_SYSTEM_PROMPT,
    _PAGE_SYSTEM_PROMPT,
    WORLD_GENERATION_TIMEOUT_SECONDS,
)
from modules.world.services.worldbuilding.generation_prompt_template_service import (
    TEMPLATE_ENTITY_TYPES,
    ResolvedGenerationTemplate,
)


class _SuggestionStageMixin:
    async def generate_suggestion(
        self,
        db: AsyncSession,
        data: WorldGenerationSuggestionRequest,
    ) -> WorldGenerationSuggestionResponse:
        return await self._generate_suggestion(db, data)

    async def generate_suggestion_for_task(
        self,
        db: AsyncSession,
        data: WorldGenerationSuggestionRequest,
        *,
        llm_execution_snapshot: dict[str, Any],
        task_id: str,
    ) -> WorldGenerationSuggestionResponse:
        return await self._generate_suggestion(
            db,
            data,
            llm_execution_snapshot=llm_execution_snapshot,
            task_id=task_id,
        )

    async def _generate_suggestion(
        self,
        db: AsyncSession,
        data: WorldGenerationSuggestionRequest,
        *,
        llm_execution_snapshot: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> WorldGenerationSuggestionResponse:
        operation = self._operation_for_target(data)
        if llm_execution_snapshot is None:
            execution_snapshot, model = await self._freeze_execution_snapshot(
                db,
                data.novel_id,
            )
        else:
            execution_snapshot = llm_execution_snapshot
            model = str(llm_execution_snapshot["profile"]["model"])
        prepared = await self._prepare(
            db,
            data,
            operation=operation,
            model=model,
        )
        source_revision: WorldGenerationPageResult | None = None
        try:
            self._validate_exploration_selection(data, prepared)
            if data.revises_suggestion_id:
                parent = await self._suggestions.require_generation_revision_parent(
                    db,
                    novel_id=data.novel_id,
                    suggestion_id=data.revises_suggestion_id,
                )
                self._validate_revision_parent(data, prepared, parent)
            async with self._open_client(
                db,
                data.novel_id,
                execution_snapshot=execution_snapshot,
                high_quality=data.quality_mode == "pro",
            ) as client:
                async with asyncio.timeout(WORLD_GENERATION_TIMEOUT_SECONDS):
                    prepared[
                        "decision_state"
                    ] = await self._compile_conversation_decision_state(
                        client,
                        data.model_copy(
                            update={"messages": prepared["conversation_messages"]}
                        ),
                        model=model,
                    )
                    prepared["decision_state"] = self._merge_exploration_decision_state(
                        prepared.get("decision_state"),
                        data.exploration_selection,
                    )
                    prepared["decision_state"] = self._merge_saved_decisions(prepared)
                    if isinstance(data.target, WorldGenerationCoreEntityTarget):
                        result = await self._generate_core_entity(
                            db,
                            data,
                            prepared,
                            client,
                            model=model,
                        )
                    elif isinstance(data.target, WorldGenerationExistingPageTarget):
                        result = await self._generate_existing_page(
                            db,
                            data,
                            prepared,
                            client,
                            model=model,
                        )
                    else:
                        result, source_revision = await self._generate_new_page(
                            db,
                            data,
                            prepared,
                            client,
                            model=model,
                        )
                    if data.revises_suggestion_id:
                        result.suggestion = (
                            await self._suggestions.supersede_generation_suggestion(
                                db,
                                novel_id=data.novel_id,
                                predecessor_suggestion_id=data.revises_suggestion_id,
                                successor_suggestion_id=result.suggestion.id,
                            )
                        )
                provider = str(client.provider)
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
                {"type": "creation_suggestion", "id": item.suggestion.id}
                for item in [result, source_revision]
                if item is not None
            ]
            + ([{"type": "task", "id": task_id}] if task_id else []),
        )
        return WorldGenerationSuggestionResponse(
            result=result,
            source_revision=source_revision,
            decision_state=prepared.get("decision_state"),
            model=model,
            provider=provider,
            context_usage=self._context_usage(prepared["background"]),
            source_snapshot=prepared["source_snapshot"],
            knowledge_review=result.proposal.knowledge_review,
        )

    async def _generate_core_entity(
        self,
        db: AsyncSession,
        data: WorldGenerationSuggestionRequest,
        prepared: dict[str, Any],
        client: LLMClient,
        *,
        model: str,
    ) -> WorldGenerationCoreEntityResult:
        final_instruction = (
            "请根据目前的共创结果生成一个具体的世界对象建议。实现作者当前"
            "支持最充分的方向，使对象的创意核心和内在逻辑清楚成立。"
        )
        request = LLMCallRequest(
            model=model,
            messages=self._structured_messages(
                data,
                prepared,
                system_prompt=_CORE_ENTITY_SYSTEM_PROMPT,
                final_instruction=final_instruction,
            ),
            temperature=0.35,
        )
        generated = await self._run_structured_with_decision_guard(
            client,
            request,
            GeneratedObjectDraftOutput,
            decision_state=prepared.get("decision_state"),
            step_name="world.generation.core_entity.structured",
            quality_mode=data.quality_mode,
        )
        generated, knowledge_review = await self._govern_structured(
            client,
            capability="world.generation.suggestion",
            novel_id=data.novel_id,
            prepared=prepared,
            generated=generated,
            request=request,
            schema=GeneratedObjectDraftOutput,
            decision_state=prepared.get("decision_state"),
            step_name="world.generation.core_entity",
            quality_mode=data.quality_mode,
            task_instruction=final_instruction,
        )
        await self._revalidate_source(db, data, prepared)
        template: ResolvedGenerationTemplate = prepared["object_template"]
        content_json: dict[str, Any] = {
            "details": generated.details,
            "_meta": {
                "source": "ai_generated",
                "generation_source": "world_generation_center",
                "template": template.object_template,
                "template_name": template.label,
                "template_id": template.template_id,
                "template_version": template.template_version,
                "template_hash": template.template_hash,
                "template_validation_state": template.validation_state,
                "quality_mode": data.quality_mode,
                "conversation_hash": self._conversation_hash(data),
                "author_decision_state": (
                    prepared["decision_state"].model_dump(mode="json")
                    if prepared.get("decision_state") is not None
                    else None
                ),
                "source_snapshot": prepared["source_snapshot"].model_dump(mode="json"),
                "context_usage": prepared["background"].get("context_usage"),
                "review_notes": generated.review_notes,
            },
        }
        if template.object_template == "character":
            content_json["character_card"] = generated.character_card or generated.details
        payload = CoreEntityDraftSuggestionPayload(
            entity_type=TEMPLATE_ENTITY_TYPES.get(template.object_template, "concept"),
            name=generated.name,
            summary=generated.summary,
            public_info=generated.public_info,
            hidden_truth=generated.hidden_truth,
            content_json=content_json,
            importance_level=generated.importance_level,
            reveal_level=generated.reveal_level,
            source_refs=prepared["source_refs"],
            knowledge_review=knowledge_review,
        )
        suggestion, _shadow = await self._suggestions.create_core_entity_suggestion(
            db,
            novel_id=data.novel_id,
            source_module="world",
            review_group="generation_center",
            payload=payload,
            evidence_refs_json=[
                item.model_dump(mode="json") for item in prepared["source_refs"]
            ],
            action_schema="world_generation.core_entity.v1",
            compatibility_status="candidate",
            compatibility_created_by="ai_world_generation_center",
        )
        return WorldGenerationCoreEntityResult(
            suggestion=suggestion,
            proposal=payload,
            review_notes=generated.review_notes,
        )

    async def _generate_existing_page(
        self,
        db: AsyncSession,
        data: WorldGenerationSuggestionRequest,
        prepared: dict[str, Any],
        client: LLMClient,
        *,
        model: str,
    ) -> WorldGenerationPageResult:
        final_instruction = (
            "请根据作者当前意图生成完整的世界书页面提案。输出整页最终形态，"
            "不要输出追加补丁。"
        )
        request = LLMCallRequest(
            model=model,
            messages=self._structured_messages(
                data,
                prepared,
                system_prompt=_PAGE_SYSTEM_PROMPT,
                final_instruction=final_instruction,
            ),
            temperature=0.35,
        )
        generated = await self._run_structured_with_decision_guard(
            client,
            request,
            GeneratedWorldBiblePageProposal,
            decision_state=prepared.get("decision_state"),
            step_name="world.generation.world_bible_page.structured",
            quality_mode=data.quality_mode,
        )
        generated, knowledge_review = await self._govern_structured(
            client,
            capability="world.generation.suggestion",
            novel_id=data.novel_id,
            prepared=prepared,
            generated=generated,
            request=request,
            schema=GeneratedWorldBiblePageProposal,
            decision_state=prepared.get("decision_state"),
            step_name="world.generation.world_bible_page",
            quality_mode=data.quality_mode,
            task_instruction=final_instruction,
        )
        await self._revalidate_source(db, data, prepared)
        page_content = self._map_existing_page_proposal(generated, prepared)
        page_content = self._preserve_author_open_questions(page_content, prepared)
        snapshot: WorldGenerationSourceSnapshot = prepared["source_snapshot"]
        payload = WorldBiblePageDraftSuggestionPayload(
            operation="replace_existing",
            target_page_id=snapshot.page_id,
            baseline=WorldGenerationPageBaseline(
                page_id=str(snapshot.page_id),
                page_version=int(snapshot.page_version or 1),
                draft_id=snapshot.draft_id,
                draft_updated_at=snapshot.draft_updated_at,
                content_hash=str(snapshot.content_hash),
            ),
            page=page_content,
            design_rationale=generated.design_rationale,
            review_notes=generated.review_notes,
            source_refs=prepared["source_refs"],
            decision_state=prepared.get("decision_state"),
            knowledge_review=knowledge_review,
        )
        suggestion = await self._create_page_suggestion(db, data, payload)
        return WorldGenerationPageResult(
            kind="world_bible_page",
            suggestion=suggestion,
            proposal=payload,
        )

    async def _generate_new_page(
        self,
        db: AsyncSession,
        data: WorldGenerationSuggestionRequest,
        prepared: dict[str, Any],
        client: LLMClient,
        *,
        model: str,
    ) -> tuple[WorldGenerationPageResult, WorldGenerationPageResult | None]:
        exploration_instruction = (
            " 这是作者选中的一次深度 1 相邻探索。若新页面的具体设计确实要求来源页改写，"
            "source_revision 返回来源页完整替换提案；"
            "能够并存或只有泛泛影响时必须为 null。"
            if data.exploration_selection is not None
            else " 本次不是相邻探索，source_revision 必须为 null。"
        )
        final_instruction = (
            "请根据作者当前意图生成完整的新世界书页面提案。页面应拥有明确"
            "的主题和独立用途，不要把来源资料简单拼接成页面。" + exploration_instruction
        )
        request = LLMCallRequest(
            model=model,
            messages=self._structured_messages(
                data,
                prepared,
                system_prompt=_NEW_PAGE_SYSTEM_PROMPT,
                final_instruction=final_instruction,
            ),
            temperature=0.35,
        )
        generated = await self._run_structured_with_decision_guard(
            client,
            request,
            GeneratedWorldBibleNewPageProposal,
            decision_state=prepared.get("decision_state"),
            step_name="world.generation.world_bible_new_page.structured",
            quality_mode=data.quality_mode,
        )
        generated, knowledge_review = await self._govern_structured(
            client,
            capability="world.generation.suggestion",
            novel_id=data.novel_id,
            prepared=prepared,
            generated=generated,
            request=request,
            schema=GeneratedWorldBibleNewPageProposal,
            decision_state=prepared.get("decision_state"),
            step_name="world.generation.world_bible_new_page",
            quality_mode=data.quality_mode,
            task_instruction=final_instruction,
        )
        await self._revalidate_source(db, data, prepared)
        page_content = self._map_new_page_proposal(generated, prepared)
        page_content = self._preserve_author_open_questions(page_content, prepared)
        payload = WorldBiblePageDraftSuggestionPayload(
            operation="create_new",
            template_key=(
                prepared["page_template"].template_key
                if prepared.get("page_template") is not None
                else None
            ),
            template_version=(
                prepared["page_template"].version_number
                if prepared.get("page_template") is not None
                else None
            ),
            page=page_content,
            design_rationale=generated.design_rationale,
            review_notes=generated.review_notes,
            source_refs=prepared["source_refs"],
            decision_state=prepared.get("decision_state"),
            knowledge_review=knowledge_review,
        )
        suggestion = await self._create_page_suggestion(db, data, payload)
        result = WorldGenerationPageResult(
            kind="world_bible_new_page",
            suggestion=suggestion,
            proposal=payload,
        )
        source_revision: WorldGenerationPageResult | None = None
        if (
            data.exploration_selection is not None
            and generated.source_revision is not None
        ):
            revision_page = self._map_existing_page_proposal(
                generated.source_revision,
                prepared,
            )
            if self._page_content_changed(revision_page, prepared):
                snapshot: WorldGenerationSourceSnapshot = prepared["source_snapshot"]
                candidate_hash = stable_hash(
                    payload.page.model_dump(mode="json"), stringify_unknown=False
                )
                reverse_payload = WorldBiblePageDraftSuggestionPayload(
                    operation="replace_existing",
                    target_page_id=snapshot.page_id,
                    baseline=WorldGenerationPageBaseline(
                        page_id=str(snapshot.page_id),
                        page_version=int(snapshot.page_version or 1),
                        draft_id=snapshot.draft_id,
                        draft_updated_at=snapshot.draft_updated_at,
                        content_hash=str(snapshot.content_hash),
                    ),
                    page=revision_page,
                    design_rationale=generated.source_revision.design_rationale,
                    review_notes=generated.source_revision.review_notes,
                    source_refs=[
                        *prepared["source_refs"],
                        WorldBibleSourceRef(
                            source_type="creation_suggestion",
                            source_id=suggestion.id,
                            source_hash=candidate_hash,
                            title=payload.page.title,
                        ),
                    ],
                    decision_state=prepared.get("decision_state"),
                )
                reverse_suggestion = await self._create_page_suggestion(
                    db,
                    data,
                    reverse_payload,
                )
                source_revision = WorldGenerationPageResult(
                    kind="world_bible_page",
                    suggestion=reverse_suggestion,
                    proposal=reverse_payload,
                )
        return result, source_revision

    async def _create_page_suggestion(
        self,
        db: AsyncSession,
        data: WorldGenerationSuggestionRequest,
        payload: WorldBiblePageDraftSuggestionPayload,
    ):
        return await self._suggestions.create(
            db,
            CreationSuggestionCreate(
                novel_id=data.novel_id,
                source_module="world",
                review_group="generation_center",
                target_type="world_bible_page_draft",
                action_schema="world_generation.page_draft.v1",
                payload_json=payload.model_dump(mode="json"),
                evidence_refs_json=[
                    item.model_dump(mode="json") for item in payload.source_refs
                ],
                risk_level="low",
            ),
        )

    def _map_existing_page_proposal(
        self,
        generated: GeneratedWorldBiblePageProposal,
        prepared: dict[str, Any],
    ) -> WorldBiblePageProposalContent:
        self._validate_page_type(generated.page_type, prepared)
        source_sections = {
            f"S{index + 1}": dict(item)
            for index, item in enumerate(prepared["source_page_data"]["sections_json"])
        }
        sections: list[WorldBibleSection] = []
        reused_section_keys: set[str] = set()
        for index, item in enumerate(generated.sections):
            existing = None
            if item.source_section_key is not None:
                if item.source_section_key in reused_section_keys:
                    raise ValidationError(
                        f"Duplicate source section key: {item.source_section_key}"
                    )
                existing = source_sections.get(item.source_section_key)
                if existing is None:
                    raise ValidationError(
                        f"Unknown source section key: {item.source_section_key}"
                    )
                reused_section_keys.add(item.source_section_key)
            sections.append(
                self._page_section(
                    item,
                    index=index,
                    prepared=prepared,
                    existing=existing,
                )
            )
        refs = self._proposal_asset_refs(
            generated.linked_asset_keys,
            [item.linked_asset_keys for item in generated.sections],
            prepared,
        )
        return WorldBiblePageProposalContent(
            title=generated.title,
            page_type=generated.page_type,
            free_text=generated.overview,
            sections_json=sections,
            linked_asset_refs_json=refs,
        )

    @staticmethod
    def _page_content_changed(
        candidate: WorldBiblePageProposalContent,
        prepared: dict[str, Any],
    ) -> bool:
        source = prepared["source_page_data"]
        current = WorldBiblePageProposalContent(
            title=source["title"],
            page_type=source["page_type"],
            free_text=source.get("free_text"),
            sections_json=source.get("sections_json") or [],
            linked_asset_refs_json=source.get("linked_asset_refs_json") or [],
        )
        return candidate.model_dump(mode="json") != current.model_dump(mode="json")

    def _map_new_page_proposal(
        self,
        generated: GeneratedWorldBibleNewPageProposal,
        prepared: dict[str, Any],
    ) -> WorldBiblePageProposalContent:
        self._validate_page_type(generated.page_type, prepared)
        target = prepared.get("request_target")
        if (
            isinstance(target, WorldGenerationNewPageTarget)
            and target.page_type is not None
            and generated.page_type != target.page_type
        ):
            raise ValidationError(
                "Generated World Bible page type does not match the author-selected type"
            )
        sections = [
            self._page_section(item, index=index, prepared=prepared, existing=None)
            for index, item in enumerate(generated.sections)
        ]
        refs = self._proposal_asset_refs(
            generated.linked_asset_keys,
            [item.linked_asset_keys for item in generated.sections],
            prepared,
        )
        return WorldBiblePageProposalContent(
            title=generated.title,
            page_type=generated.page_type,
            free_text=generated.overview,
            sections_json=sections,
            linked_asset_refs_json=refs,
        )

    @staticmethod
    def _preserve_author_open_questions(
        page: WorldBiblePageProposalContent,
        prepared: dict[str, Any],
    ) -> WorldBiblePageProposalContent:
        decision_state: GeneratedWorldGenerationDecisionState | None = prepared.get(
            "decision_state"
        )
        questions = list(
            dict.fromkeys(
                " ".join(str(item).split())
                for item in (decision_state.unresolved_choices if decision_state else [])
                if str(item).strip()
            )
        )
        sections = list(page.sections_json)
        current = next(
            (
                item
                for item in sections
                if item.section_id == _AUTHOR_OPEN_QUESTIONS_SECTION_ID
            ),
            None,
        )
        source = next(
            (
                item
                for item in (
                    (prepared.get("source_page_data") or {}).get("sections_json") or []
                )
                if item.get("section_id") == _AUTHOR_OPEN_QUESTIONS_SECTION_ID
            ),
            None,
        )
        if current is None and source is None and not questions:
            return page
        if current is None and source is None and len(sections) >= 64:
            raise ValidationError(
                "World Bible page has no section slot for unresolved author choices"
            )

        lines: list[str] = []
        for body in (
            current.body_markdown if current is not None else "",
            str(source.get("body_markdown") or "") if source is not None else "",
        ):
            for raw_line in body.splitlines():
                line = raw_line.rstrip()
                if line and line not in lines:
                    lines.append(line)
        listed_questions = {
            re.sub(r"^\s*[-*]\s+\[[ xX]\]\s*", "", line).strip() for line in lines
        }
        lines.extend(
            f"- [ ] {question}"
            for question in questions
            if question not in listed_questions
        )
        body_markdown = "\n".join(lines)
        if len(body_markdown) > 30_000:
            raise ValidationError("Unresolved author choices exceed the section limit")

        if current is not None:
            sort_order = current.sort_order
            title = current.title
        elif source is not None:
            sort_order = int(source.get("sort_order") or 0)
            title = str(source.get("title") or "仍待作者决定")
        else:
            sort_order = min(
                100_000,
                max((item.sort_order for item in sections), default=-10) + 10,
            )
            title = "仍待作者决定"
        preserved = WorldBibleSection(
            section_id=_AUTHOR_OPEN_QUESTIONS_SECTION_ID,
            section_type="checklist",
            title=title,
            body_markdown=body_markdown,
            sort_order=sort_order,
            linked_asset_ref_hashes=[],
            projection_policy="excluded",
            sensitivity_hint="author_only",
        )
        if current is None:
            sections.append(preserved)
        else:
            sections[sections.index(current)] = preserved
        return WorldBiblePageProposalContent.model_validate(
            {
                **page.model_dump(mode="json"),
                "sections_json": [item.model_dump(mode="json") for item in sections],
            }
        )

    def _page_section(
        self,
        item,
        *,
        index: int,
        prepared: dict[str, Any],
        existing: dict[str, Any] | None,
    ) -> WorldBibleSection:
        defaults = self._new_section_defaults(prepared, index, item.title)
        section_id = (
            str(existing["section_id"])
            if existing is not None
            else "ai-"
            + hashlib.sha256(
                (
                    f"{prepared['source_snapshot'].content_hash}:{index}:"
                    f"{item.title}:{item.body_markdown}"
                ).encode()
            ).hexdigest()[:20]
        )
        return WorldBibleSection(
            section_id=section_id,
            section_type=item.section_type,
            title=item.title,
            body_markdown=item.body_markdown,
            sort_order=index,
            linked_asset_ref_hashes=[
                self._asset_ref_hash(prepared["assets"]["by_key"][key]["ref"])
                for key in dict.fromkeys(item.linked_asset_keys)
                if self._require_asset_key(key, prepared)
            ],
            projection_policy=(
                str(existing.get("projection_policy", "eligible"))
                if existing is not None
                else defaults["projection_policy"]
            ),
            sensitivity_hint=(
                str(existing.get("sensitivity_hint", "author_safe"))
                if existing is not None
                else defaults["sensitivity_hint"]
            ),
        )

    @staticmethod
    def _new_section_defaults(
        prepared: dict[str, Any],
        index: int,
        title: str,
    ) -> dict[str, str]:
        if isinstance(prepared.get("request_target"), WorldGenerationExistingPageTarget):
            return {
                "projection_policy": "excluded",
                "sensitivity_hint": "author_only",
            }
        template = prepared.get("page_template")
        if template is not None:
            candidates = [
                item.model_dump(mode="json") for item in template.default_sections_json
            ]
            matched = next(
                (item for item in candidates if item.get("title") == title),
                candidates[index] if index < len(candidates) else None,
            )
            if matched:
                return {
                    "projection_policy": matched.get("projection_policy", "eligible"),
                    "sensitivity_hint": matched.get("sensitivity_hint", "author_safe"),
                }
        return {"projection_policy": "eligible", "sensitivity_hint": "author_safe"}

    def _proposal_asset_refs(
        self,
        page_keys: list[str],
        section_key_groups: list[list[str]],
        prepared: dict[str, Any],
    ) -> list[dict[str, Any]]:
        keys = list(page_keys)
        for group in section_key_groups:
            keys.extend(group)
        result: list[dict[str, Any]] = []
        for key in dict.fromkeys(keys):
            self._require_asset_key(key, prepared)
            result.append(dict(prepared["assets"]["by_key"][key]["ref"]))
        return result

    @staticmethod
    def _require_asset_key(key: str, prepared: dict[str, Any]) -> bool:
        if key not in prepared["assets"]["by_key"]:
            raise ValidationError(f"Unknown asset reference key: {key}")
        return True

    @staticmethod
    def _validate_page_type(page_type: str, prepared: dict[str, Any]) -> None:
        if page_type not in prepared["allowed_page_types"]:
            raise ValidationError(f"Unknown World Bible page type: {page_type}")

    @staticmethod
    def _target_brief(data: WorldGenerationRequestBase) -> str:
        boundary = (
            "\n已保存的作者决定限定本轮共创，不代表正式采用。"
            "新消息与长期决定冲突时须明确指出，并请作者先更新决定，不能静默覆盖。"
            if data.session_id
            else ""
        )
        if isinstance(data.target, WorldGenerationCoreEntityTarget):
            return _CORE_ENTITY_BRIEF + boundary
        if isinstance(data.target, WorldGenerationExistingPageTarget):
            return _EXISTING_PAGE_BRIEF + boundary
        return _NEW_PAGE_BRIEF + boundary

    @staticmethod
    def _operation_for_target(data: WorldGenerationSuggestionRequest) -> str:
        if isinstance(data.target, WorldGenerationCoreEntityTarget):
            return "world.generation.core_entity"
        return "world.generation.world_bible_page"

    @staticmethod
    def _conversation_hash(data: WorldGenerationRequestBase) -> str:
        return hashlib.sha256(
            "\n".join(f"{item.role}:{item.content}" for item in data.messages).encode(
                "utf-8"
            )
        ).hexdigest()

    @staticmethod
    def _focus_text(
        data: WorldGenerationRequestBase,
        template: ResolvedGenerationTemplate | None,
    ) -> str:
        # Retrieval should follow the author's latest direction. Feeding every prior
        # correction back into the retrieval query can make explicitly invalidated
        # names and concepts reappear inside the compiled background.
        latest_user = next(
            (item.content for item in reversed(data.messages) if item.role == "user"),
            "",
        )
        parts = [latest_user] if latest_user else []
        if template is not None:
            parts.extend([template.label, template.rendered_prompt])
        if data.pasted_context:
            parts.append(data.pasted_context[-1500:])
        return "\n".join(parts)[:4000]

    @staticmethod
    def _source_refs(
        data: WorldGenerationRequestBase,
        source: dict[str, Any],
        chapters: list[dict[str, Any]],
        assets: dict[str, Any],
        background: dict[str, Any],
    ) -> list[WorldBibleSourceRef]:
        refs: list[WorldBibleSourceRef] = []
        snapshot: WorldGenerationSourceSnapshot = source["source_snapshot"]
        if snapshot.kind == "world_bible_page":
            refs.append(
                WorldBibleSourceRef(
                    source_type=(
                        "world_bible_page_draft"
                        if snapshot.draft_id
                        else "world_bible_page"
                    ),
                    source_id=snapshot.draft_id or snapshot.page_id,
                    source_version=snapshot.page_version,
                    source_hash=snapshot.content_hash,
                    page_id=snapshot.page_id,
                    title=snapshot.title,
                )
            )
        refs.extend(
            WorldBibleSourceRef(
                source_type="writing_chapter",
                chapter_index=item["chapter_index"],
                title=item["title"],
                source_hash=hashlib.sha256(item["excerpt"].encode("utf-8")).hexdigest(),
            )
            for item in chapters
        )
        refs.extend(
            WorldBibleSourceRef(
                source_type=item["type"],
                source_id=item["ref"]["id"],
                title=item["title"],
                source_hash=item["source_hash"],
            )
            for item in assets["by_key"].values()
        )
        usage = background.get("context_usage") or {}
        if usage.get("included") and usage.get("revision_id"):
            refs.append(
                WorldBibleSourceRef(
                    source_type="world_bible_synopsis",
                    source_id=usage.get("revision_id"),
                    source_hash=usage.get("source_hash"),
                    block_hash=usage.get("block_hash"),
                    title="世界观简介",
                )
            )
        if data.messages:
            refs.append(
                WorldBibleSourceRef(
                    source_type="author_messages",
                    source_hash=WorldGenerationCenterService._conversation_hash(data),
                    title="作者消息",
                )
            )
        return refs
