"""Confirmed, source-bound writing generation task lifecycle."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, ValidationError
from infrastructure.llm.agent_step_harness import (
    MANAGED_LLM_PROVENANCE_KEY,
    build_managed_llm_provenance,
    run_managed_generate,
)
from infrastructure.llm.client import LLMClient
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.writing.pov_generation import (
    POV_PROMPT_NAME,
    POV_SYSTEM_PROMPT,
    CharacterRevealGuard,
    GenerationProfile,
    GenerationProfileInfo,
    PovGenerationParser,
    build_pov_generation_prompt,
    prompt_hash,
)
from modules.writing.repositories import (
    WORKING_DRAFT_STATUSES,
    WritingDraftRepository,
)
from modules.writing.schemas import (
    WritingDraftCreate,
    WritingDraftResponse,
)
from modules.writing.service_support import (
    _CONTINUATION_WRITING_SYSTEM_PROMPT,
    _DEFAULT_WRITING_SYSTEM_PROMPT,
    _FROZEN_GENERATION_CANDIDATE_META_KEY,
    _FROZEN_GENERATION_CANDIDATE_VERSION,
    WRITING_GENERATION_TIMEOUT_SECONDS,
    _build_writing_generation_prompt,
    _frozen_candidate_for_plan,
    _FrozenHiddenGuardTerm,
    _generation_task_source_fingerprint,
    _parse_uuid,
    _story_assets_are_stale,
    _WritingGenerationTaskPlan,
    logger,
)
from modules.writing.text_sanitizer import sanitize_writing_text


class WritingGenerationService:
    """AI 正文建议生成服务。"""

    async def submit_generation(
        self,
        db,
        data,
        *,
        llm_execution_snapshot=None,
        internal_meta=None,
        operation_payload=None,
    ):
        from infrastructure.tasks.facade import (
            enqueue_task_with_optional_operation,
            get_operation_task,
        )
        from modules.evidence.facade import (
            bind_confirmed_action_result,
            confirmed_knowledge_source_count,
            prepare_confirmed_ai_action,
        )
        from modules.project.facade import (
            build_project_llm_execution_snapshot,
            require_active_project,
            restore_project_llm_execution_settings,
        )
        from modules.story.facade import get_scene_story_assets

        await require_active_project(db, data.novel_id)
        if set(internal_meta or {}) - {
            "_execution_mode",
            "_parent_task_id",
            "_task_priority",
        }:
            raise ValueError("Unsupported internal generation metadata")
        payload = data.model_dump(mode="json", exclude={"operation_id"})
        identity = operation_payload if operation_payload is not None else payload
        try:
            existing = await get_operation_task(
                db,
                operation_id=str(data.operation_id) if data.operation_id else None,
                task_type="writing_generate",
                novel_id=data.novel_id,
                request_payload=identity,
            )
        except ValueError as error:
            raise ConflictError(
                "该请求已用于另一份正文生成，请沿用原请求或重新提交"
            ) from error
        if existing:
            return {"task_id": existing.task_id, "status": existing.status}
        confirmed = await prepare_confirmed_ai_action(
            db,
            novel_id=data.novel_id,
            action="writing.generate",
            confirmation_id=data.context_confirmation_id,
        )
        scene_id = str((confirmed.compile_options or {}).get("scene_id") or "") or None
        basis = []
        if scene_id:
            assets = await get_scene_story_assets(
                db, novel_id=data.novel_id, scene_id=scene_id
            )
            basis = [
                {
                    "file_id": str(item.get("id") or ""),
                    "adopted_revision_id": str(item.get("adopted_revision_id") or ""),
                    "basis_hash": item.get("basis_hash"),
                    "expected_basis_hash": item.get("expected_basis_hash"),
                }
                for item in assets.get("adopted_scripts", [])
                if isinstance(item, dict)
            ]
            stale = [
                item
                for item in basis
                if item.get("basis_hash") != item.get("expected_basis_hash")
            ]
            if stale and not data.confirm_stale_story_assets:
                raise ConflictError(
                    "已采用的 Scene 剧本依据已变化；请明确确认后继续写作",
                    code="stale_story_assets",
                    context={"assets": stale},
                )
        if llm_execution_snapshot:
            await restore_project_llm_execution_settings(
                db, data.novel_id, llm_execution_snapshot
            )
        snapshot = llm_execution_snapshot or await build_project_llm_execution_snapshot(
            db, data.novel_id
        )
        try:
            receipt = await enqueue_task_with_optional_operation(
                db,
                operation_id=str(data.operation_id) if data.operation_id else None,
                task_type="writing_generate",
                novel_id=data.novel_id,
                request_payload=identity,
                meta={
                    **payload,
                    # 供跨设备在途查询把生成任务归位到同一 Scene；
                    # scene 由确认编译选项解析，客户端不可伪造替换确认范围。
                    "scene_id": scene_id,
                    "story_asset_basis": basis,
                    "llm_execution_snapshot": snapshot,
                    # 冻结本次确认编译产物的来源数上界：任务配额公式按真实 K 计，
                    # 不再退回 16384 的物理上界导致 1544 请求的虚高 cap。
                    "included_sources_upper_bound": confirmed_knowledge_source_count(
                        confirmed
                    ),
                    **(internal_meta or {}),
                },
            )
        except ValueError as error:
            raise ConflictError("正文生成提交发生冲突，请刷新原任务") from error
        if not receipt.reused:
            await bind_confirmed_action_result(
                db,
                novel_id=data.novel_id,
                confirmation_id=data.context_confirmation_id,
                result_type="task",
                result_id=receipt.task_id,
                status="running",
            )
        await db.flush()
        return {"task_id": receipt.task_id, "status": receipt.status}

    def __init__(
        self,
        repo: WritingDraftRepository | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._repo = repo or WritingDraftRepository()
        self._llm = llm_client
        self._pov_parser = PovGenerationParser()
        self._pov_guard = CharacterRevealGuard()

    @staticmethod
    def _task_profile(confirmed_context: object) -> GenerationProfileInfo:
        """Resolve POV from a fresh task confirmation whose status is running."""
        confirmation = getattr(confirmed_context, "confirmation")
        options = dict(getattr(confirmed_context, "compile_options", None) or {})
        scene_id = options.get("scene_id")
        viewpoint_character_id = options.get("viewpoint_character_id")
        if (
            getattr(confirmation, "action", None) == "writing.generate"
            and options.get("reveal_mode") == "character"
            and scene_id
            and viewpoint_character_id
        ):
            return GenerationProfileInfo(
                profile=GenerationProfile.POV_CHARACTER,
                scene_id=str(scene_id),
                viewpoint_character_id=str(viewpoint_character_id),
            )
        return GenerationProfileInfo(profile=GenerationProfile.DEFAULT)

    @staticmethod
    def _require_task_confirmation_owner(
        confirmed_context: object,
        *,
        chapter_index: int,
        source_task_id: str,
    ) -> None:
        """Fail closed unless this task is the latest running confirmation owner."""
        confirmation = getattr(confirmed_context, "confirmation")
        if getattr(confirmation, "result_status", None) != "running":
            raise ValidationError("Writing generation confirmation is not running")
        if list(getattr(confirmation, "stale_reasons", None) or []):
            raise ValidationError("Writing generation confirmation is stale")

        task_refs = [
            str(ref.get("id"))
            for ref in (getattr(confirmed_context, "result_refs", None) or [])
            if isinstance(ref, Mapping)
            and ref.get("type") == "task"
            and ref.get("id") is not None
        ]
        if not task_refs or task_refs[-1] != str(source_task_id):
            raise ValidationError("Writing generation task was superseded")

        compile_options = dict(getattr(confirmed_context, "compile_options", None) or {})
        confirmed_chapter = compile_options.get("requested_chapter_index")
        if confirmed_chapter is None:
            confirmed_chapter = compile_options.get("chapter_index")
        if confirmed_chapter is not None:
            try:
                normalized_chapter = int(confirmed_chapter)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    "Writing generation confirmation chapter_index is invalid"
                ) from exc
            if normalized_chapter != int(chapter_index):
                raise ValidationError(
                    "Writing generation confirmation chapter_index mismatch"
                )

    @staticmethod
    def _build_generation_request(
        *,
        confirmed_context: object,
        profile: GenerationProfileInfo,
        chapter_index: int,
        instruction: str | None,
        model: str,
        generation_mode: str = "draft",
        base_content: str | None = None,
        scene_execution_bundle: dict[str, Any] | None = None,
    ) -> tuple[str, LLMCallRequest]:
        is_pov = profile.profile == GenerationProfile.POV_CHARACTER
        if is_pov:
            if generation_mode != "draft":
                raise ValidationError(
                    "Character POV generation does not support continuation mode"
                )
            prompt = build_pov_generation_prompt(
                chapter_index=chapter_index,
                instruction=instruction,
                context_markdown=str(getattr(confirmed_context, "rendered_markdown", "")),
                base_content=base_content,
            )
            system_prompt = POV_SYSTEM_PROMPT
            response_format = {"type": "json_object"}
        else:
            compile_options = dict(
                getattr(confirmed_context, "compile_options", None) or {}
            )
            prompt = _build_writing_generation_prompt(
                chapter_index=chapter_index,
                instruction=instruction,
                context_markdown=str(getattr(confirmed_context, "rendered_markdown", "")),
                target_scope="当前章节",
                scene_is_context=bool(compile_options.get("scene_id")),
                generation_mode=generation_mode,
                base_content=base_content,
            )
            system_prompt = (
                _CONTINUATION_WRITING_SYSTEM_PROMPT
                if generation_mode == "continue"
                else _DEFAULT_WRITING_SYSTEM_PROMPT
            )
            response_format = None
        if scene_execution_bundle:
            prompt += (
                "\n\n【已冻结的 Scene 执行合同】\n"
                + json.dumps(
                    scene_execution_bundle,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
                + "\n严格执行其中约束；missing_fields/omissions "
                "是未决项，不得擅自补成长期事实。"
            )
        return prompt, LLMCallRequest(
            model=model,
            messages=[
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=0.7,
            response_format=response_format,
        )

    def _build_candidate_create(
        self,
        *,
        novel_id: str,
        chapter_index: int,
        title: str | None,
        context_confirmation_id: str,
        source_task_id: str | None,
        context_result_refs: list[dict[str, str]],
        profile: GenerationProfileInfo,
        prompt: str,
        response_content: str,
        model_name: str,
        managed_llm_provenance: dict[str, Any],
        guard_terms: list[_FrozenHiddenGuardTerm],
        generation_mode: str = "draft",
        base_draft_id: str | None = None,
        base_content: str | None = None,
        base_content_hash: str | None = None,
        scene_id: str | None = None,
        scene_execution_bundle: dict[str, Any] | None = None,
        scene_execution_bundle_hash: str | None = None,
        knowledge_review: dict[str, Any] | None = None,
        author_examples_used: bool = False,
    ) -> WritingDraftCreate:
        is_pov = profile.profile == GenerationProfile.POV_CHARACTER
        pov_view = None
        pov_validation = {
            "status": "not_applicable",
            "findings": [],
            "warnings": [],
        }
        content = response_content.strip()
        generation_profile = "default"
        prompt_name = "writing_default"
        parse_warnings: list[str] = []

        if is_pov:
            generation_profile = "pov_character"
            prompt_name = POV_PROMPT_NAME
            parsed = self._pov_parser.parse(response_content)
            content = parsed.content
            pov_view = parsed.pov_view
            parse_warnings = parsed.warnings
            content_sanitized = sanitize_writing_text(content)
            content = content_sanitized.text or ""
            pov_validation = self._pov_guard.validate(
                pov_view=pov_view,
                draft_prose=content,
                guard_terms=guard_terms,
                warnings=parse_warnings,
            )
        else:
            content_sanitized = sanitize_writing_text(content)
            content = content_sanitized.text or ""

        if generation_mode == "continue":
            if not base_draft_id or base_content is None or not base_content_hash:
                raise ValidationError(
                    "Continuation generation requires a frozen base draft"
                )
            continuation = content.strip()
            if not continuation:
                raise ValidationError("Continuation generation returned empty prose")
            locked_content = base_content.rstrip()
            separator = "\n\n" if locked_content else ""
            content = f"{locked_content}{separator}{continuation}"
            content_sanitized = sanitize_writing_text(content)
            content = content_sanitized.text or ""

        candidate_title = title or f"第{chapter_index}章 正文建议"
        title_sanitized = sanitize_writing_text(candidate_title)
        provenance = {
            "source": "writing_generate",
            "source_confirmation_id": context_confirmation_id,
            "source_task_id": source_task_id,
            "context_action": "writing.generate",
            "author_examples_used": author_examples_used,
            "context_result_refs": deepcopy(context_result_refs),
            "generation_profile": generation_profile,
            "generation_mode": generation_mode,
            "base_draft_id": base_draft_id,
            "base_content_hash": base_content_hash,
            "context_confirmation_id": context_confirmation_id,
            "scene_id": scene_id or profile.scene_id,
            "scene_execution_bundle_hash": scene_execution_bundle_hash,
            "upstream_manifest": deepcopy(
                (scene_execution_bundle or {}).get("upstream_manifest") or []
            ),
            "review_required": True,
            "viewpoint_character_id": profile.viewpoint_character_id,
            "prompt_name": prompt_name,
            "prompt_hash": prompt_hash(prompt),
            "model": model_name,
            MANAGED_LLM_PROVENANCE_KEY: [deepcopy(managed_llm_provenance)],
            "pov_view": pov_view,
            "pov_validation": pov_validation,
            "knowledge_review": deepcopy(knowledge_review or {}),
            "content_sanitization": {
                "content_html_removed": content_sanitized.html_removed,
                "title_html_removed": title_sanitized.html_removed,
            },
        }
        return WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=chapter_index,
            title=title_sanitized.text,
            content=content,
            provenance_json=provenance,
        )

    @staticmethod
    def _freeze_guard_terms(terms: list[object]) -> tuple[_FrozenHiddenGuardTerm, ...]:
        return tuple(
            _FrozenHiddenGuardTerm(
                phrase=str(getattr(term, "phrase", "")),
                rule=str(getattr(term, "rule", "")),
                severity=str(getattr(term, "severity", "")),
                source_type=str(getattr(term, "source_type", "")),
                source_id=str(getattr(term, "source_id", "")),
                source_label=str(getattr(term, "source_label", "")),
            )
            for term in terms
        )

    async def _load_generation_base(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        generation_mode: str,
        base_draft_id: str | None,
        for_update: bool = False,
    ) -> object | None:
        if generation_mode not in {"draft", "continue"}:
            raise ValidationError(
                f"Unsupported writing generation mode: {generation_mode}"
            )
        if generation_mode == "continue" and not base_draft_id:
            raise ValidationError("Continuation generation requires base_draft_id")

        if base_draft_id:
            parsed_id = _parse_uuid(base_draft_id, "base_draft_id")
            draft = (
                await self._repo.get_for_update(db, parsed_id)
                if for_update
                else await self._repo.get(db, parsed_id)
            )
        else:
            draft = await self._repo.get_latest_by_chapter(
                db,
                _parse_uuid(novel_id, "novel_id"),
                chapter_index,
            )
            if for_update and draft is not None:
                draft = await self._repo.get_for_update(db, getattr(draft, "id"))
        if draft is None:
            if generation_mode == "draft":
                return None
            raise ValidationError("Continuation base draft does not exist")
        if str(getattr(draft, "novel_id", "")) != str(_parse_uuid(novel_id, "novel_id")):
            raise ValidationError("Continuation base draft belongs to another project")
        if int(getattr(draft, "chapter_index", 0)) != int(chapter_index):
            raise ValidationError("Continuation base draft belongs to another chapter")
        if str(getattr(draft, "status", "")) not in WORKING_DRAFT_STATUSES:
            raise ValidationError(
                "Continuation base draft is not an active manuscript version"
            )
        if (
            generation_mode == "continue"
            and not str(getattr(draft, "content", "") or "").strip()
        ):
            raise ValidationError("Continuation base draft is empty")
        return draft

    @staticmethod
    async def _checkpoint_before_external_call(db: AsyncSession) -> None:
        from infrastructure.tasks.facade import checkpoint_handler_session

        await checkpoint_handler_session(
            db,
            error_message=(
                "writing generation task requires a transaction-free checkpoint"
            ),
        )

    @staticmethod
    async def _execution_bundle(
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str | None,
    ) -> dict[str, Any] | None:
        if not scene_id:
            return None
        from modules.story.facade import get_scene_execution_bundle

        bundle = await get_scene_execution_bundle(db, novel_id, scene_id)
        if bundle is None:
            raise ValidationError("Writing generation Scene does not exist")
        return deepcopy(bundle) if isinstance(bundle, dict) else asdict(bundle)

    async def _prepare_generation_task(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        title: str | None,
        instruction: str | None,
        context_confirmation_id: str,
        source_task_id: str,
        llm_execution_snapshot: dict[str, Any],
        generation_mode: str = "draft",
        base_draft_id: str | None = None,
        confirm_stale_story_assets: bool = False,
        story_asset_basis: list[dict[str, Any]] | None = None,
    ) -> _WritingGenerationTaskPlan:
        from modules.evidence.facade import (
            build_hidden_guard_context,
            prepare_confirmed_ai_action,
        )
        from modules.project.facade import require_active_project

        await require_active_project(db, novel_id)
        confirmed_context = await prepare_confirmed_ai_action(
            db,
            novel_id=novel_id,
            action="writing.generate",
            confirmation_id=context_confirmation_id,
        )
        self._require_task_confirmation_owner(
            confirmed_context,
            chapter_index=chapter_index,
            source_task_id=source_task_id,
        )
        profile = self._task_profile(confirmed_context)
        compile_options = dict(getattr(confirmed_context, "compile_options", None) or {})
        scene_id = str(compile_options.get("scene_id") or "") or None
        execution_bundle = await self._execution_bundle(
            db,
            novel_id=novel_id,
            scene_id=scene_id,
        )
        execution_bundle_hash = (
            str(execution_bundle.get("contract_hash") or "") if execution_bundle else None
        )
        if _story_assets_are_stale(execution_bundle) and not confirm_stale_story_assets:
            raise ValidationError(
                "已采用的 Scene 剧本依据已变化；请明确确认后继续写作",
                code="stale_story_assets",
                status_code=409,
            )
        base_draft = await self._load_generation_base(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            generation_mode=generation_mode,
            base_draft_id=base_draft_id,
        )
        guard_terms: tuple[_FrozenHiddenGuardTerm, ...] = ()
        if profile.profile == GenerationProfile.POV_CHARACTER:
            guard_terms = self._freeze_guard_terms(
                await build_hidden_guard_context(
                    db,
                    confirmed_context=confirmed_context,
                )
            )
        knowledge_plan = self._build_knowledge_scope_plan(
            confirmed_context,
            chapter_index=chapter_index,
            instruction=instruction,
            guard_terms=guard_terms,
        )

        snapshot_profile = llm_execution_snapshot.get("profile")
        model = (
            str(snapshot_profile.get("model") or "")
            if isinstance(snapshot_profile, dict)
            else ""
        )
        if not model:
            raise ValidationError(
                "writing generation task requires a frozen project LLM model"
            )
        prompt, request = self._build_generation_request(
            confirmed_context=confirmed_context,
            profile=profile,
            chapter_index=chapter_index,
            instruction=instruction,
            model=model,
            generation_mode=generation_mode,
            base_content=(
                str(getattr(base_draft, "content", "") or "")
                if base_draft is not None
                else None
            ),
            scene_execution_bundle=execution_bundle,
        )
        normalized_base_id = (
            str(getattr(base_draft, "id")) if base_draft is not None else None
        )
        base_content_hash = (
            str(getattr(base_draft, "content_hash", ""))
            if base_draft is not None
            else None
        )
        return _WritingGenerationTaskPlan(
            novel_id=str(novel_id),
            chapter_index=chapter_index,
            title=title,
            context_confirmation_id=str(context_confirmation_id),
            source_task_id=str(source_task_id),
            profile=profile,
            prompt=prompt,
            request=request,
            context_result_refs=tuple(
                deepcopy(getattr(confirmed_context, "result_refs", None) or [])
            ),
            hidden_guard_terms=guard_terms,
            source_fingerprint=_generation_task_source_fingerprint(
                confirmed_context,
                profile=profile,
                hidden_guard_terms=guard_terms,
                generation_mode=generation_mode,
                base_draft=base_draft,
                scene_execution_bundle_hash=execution_bundle_hash,
                confirm_stale_story_assets=confirm_stale_story_assets,
                story_asset_basis=story_asset_basis or [],
            ),
            llm_execution_snapshot=deepcopy(llm_execution_snapshot),
            generation_mode=generation_mode,
            base_draft_id=normalized_base_id,
            base_content=(
                str(getattr(base_draft, "content", "") or "")
                if base_draft is not None
                else None
            ),
            base_content_hash=base_content_hash,
            scene_id=scene_id,
            scene_execution_bundle=execution_bundle,
            scene_execution_bundle_hash=execution_bundle_hash,
            confirm_stale_story_assets=confirm_stale_story_assets,
            story_asset_basis=tuple(deepcopy(story_asset_basis or [])),
            knowledge_policy_id=knowledge_plan["policy_id"],
            knowledge_scope_receipt=dict(knowledge_plan["scope_receipt"]),
            knowledge_generator_keys=tuple(knowledge_plan["generator_keys"]),
            knowledge_audit_only_keys=tuple(knowledge_plan["audit_only_keys"]),
            knowledge_hidden_phrases=tuple(knowledge_plan["hidden_phrases"]),
            knowledge_task_instruction=knowledge_plan["task_instruction"],
            knowledge_generator_context=knowledge_plan["generator_context"],
            knowledge_authority_context=knowledge_plan["authority_context"],
            author_examples_used=any(
                section.key == "author_examples"
                for section in getattr(
                    getattr(confirmed_context, "compiled", None), "sections", []
                )
            ),
        )

    @staticmethod
    def _build_knowledge_scope_plan(
        confirmed_context: object,
        *,
        chapter_index: int,
        instruction: str | None,
        guard_terms: tuple[_FrozenHiddenGuardTerm, ...],
    ) -> dict[str, Any]:
        """冻结写作生成的知识范围（ADR-0025）：receipt + 导演/审查所需材料。

        生成者可见集 = 冻结编译来源 − 被 hidden guard 保护的对象 − audit_only 引用；
        权威上下文额外携带隐藏事实短语，仅供独立审查，不进生成 Prompt。
        """
        from modules.evidence.contracts import (
            KnowledgeSubject,
            build_scope_receipt,
            require_capability_policy,
        )

        confirmation = getattr(confirmed_context, "confirmation")
        options = dict(getattr(confirmed_context, "compile_options", None) or {})
        if options.get("reveal_mode") == "character":
            cutoff_present = bool(
                options.get("visible_until_chapter")
                or options.get("visible_until_scene_id")
                or options.get("visible_until_offset")
            )
            if not (
                options.get("scene_id")
                and options.get("viewpoint_character_id")
                and cutoff_present
            ):
                raise ValidationError(
                    "角色模式生成必须同时具备 Scene、视角人物和揭示截止点",
                    code="pov_knowledge_scope_incomplete",
                    status_code=422,
                )

        policy = require_capability_policy("writing.generate")
        subject = KnowledgeSubject(
            subject_type={
                "reader": "reader",
                "character": "character",
            }.get(options.get("reveal_mode"), "author"),
            character_id=options.get("viewpoint_character_id"),
            cutoff_chapter=options.get("visible_until_chapter")
            or options.get("requested_chapter_index"),
            cutoff_scene_id=options.get("visible_until_scene_id")
            or options.get("scene_id"),
            cutoff_offset=options.get("visible_until_offset"),
        )
        preliminary = build_scope_receipt(
            getattr(confirmed_context, "compiled"),
            policy,
            subject,
            novel_id=str(getattr(confirmation, "novel_id", "")),
            reference_usages=options.get("reference_usages") or {},
        )
        authority_only = {
            f"core_entity:{term.source_id}"
            for term in guard_terms
            if term.source_type == "core_entity"
        }
        allowed = (
            set(preliminary.receipt.source_keys())
            - authority_only
            - set(preliminary.audit_only_keys)
        )
        scope_build = build_scope_receipt(
            getattr(confirmed_context, "compiled"),
            policy,
            subject,
            novel_id=str(getattr(confirmation, "novel_id", "")),
            reference_usages=options.get("reference_usages") or {},
            generator_visible=allowed,
        )
        rendered = str(getattr(confirmed_context, "rendered_markdown", "") or "")
        hidden_lines = [
            f"- {term.phrase}（来源：{term.source_label}）" for term in guard_terms
        ]
        authority_context = rendered
        if hidden_lines:
            authority_context = (
                rendered
                + "\n\n【仅审查可见的隐藏事实短语（不得出现在正文中）】\n"
                + "\n".join(hidden_lines)
            )
        return {
            "policy_id": policy.capability_id,
            "scope_receipt": scope_build.receipt.to_dict(),
            "generator_keys": scope_build.generator_keys,
            "audit_only_keys": scope_build.audit_only_keys,
            "hidden_phrases": tuple(term.phrase for term in guard_terms),
            "task_instruction": str(
                instruction or getattr(confirmation, "task", "") or ""
            ),
            "generator_context": rendered,
            "authority_context": authority_context,
        }

    async def generate_candidate_for_task(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        title: str | None,
        instruction: str | None,
        context_confirmation_id: str,
        source_task_id: str,
        llm_execution_snapshot: dict[str, Any],
        generation_mode: str = "draft",
        base_draft_id: str | None = None,
        confirm_stale_story_assets: bool = False,
        story_asset_basis: list[dict[str, Any]] | None = None,
        freeze_paid_output: bool = False,
    ) -> WritingDraftResponse:
        """Generate a candidate with no transaction during provider/parse work.

        Worker 启用付费输出冻结，经 Tasks 窄 facade 与原租约 checkpoint 保存。
        崩溃重排仅复用同来源的输出；已有输出漂移或损坏则失败关闭，不重付费。
        """
        from infrastructure.tasks.facade import require_task_checkpoint_session

        require_task_checkpoint_session(db)
        plan = await self._prepare_generation_task(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            title=title,
            instruction=instruction,
            context_confirmation_id=context_confirmation_id,
            source_task_id=source_task_id,
            llm_execution_snapshot=llm_execution_snapshot,
            generation_mode=generation_mode,
            base_draft_id=base_draft_id,
            confirm_stale_story_assets=confirm_stale_story_assets,
            story_asset_basis=story_asset_basis,
        )

        candidate: WritingDraftCreate | None = None
        if freeze_paid_output:
            from infrastructure.tasks.facade import read_private_task_checkpoint

            frozen = await read_private_task_checkpoint(
                db,
                task_id=source_task_id,
                task_type="writing_generate",
                novel_id=novel_id,
                key=_FROZEN_GENERATION_CANDIDATE_META_KEY,
            )
            if frozen is not None:
                candidate = _frozen_candidate_for_plan(frozen, plan)

        if candidate is None:
            try:
                from modules.evidence.contracts import (
                    GovernedWorkflowHooks,
                    KnowledgeScopeBuild,
                    KnowledgeScopeReceipt,
                    knowledge_review_payload,
                    require_capability_policy,
                    run_governed_generation,
                )
                from modules.project.facade import open_project_snapshot_llm_client

                async with open_project_snapshot_llm_client(
                    db,
                    novel_id,
                    llm_execution_snapshot,
                    timeout_override=WRITING_GENERATION_TIMEOUT_SECONDS,
                    injected_client=self._llm,
                ) as client:
                    await self._checkpoint_before_external_call(db)
                    response_holder: dict[str, Any] = {}

                    async def _governed_generate(_plan, _generator_keys) -> str:
                        response = await run_managed_generate(
                            client,
                            plan.request,
                            step_name="writing.generation.candidate.generate",
                            timeout=WRITING_GENERATION_TIMEOUT_SECONDS,
                        )
                        response_holder["model"] = response.model
                        return response.content

                    scope_build = KnowledgeScopeBuild(
                        receipt=KnowledgeScopeReceipt.from_dict(
                            plan.knowledge_scope_receipt
                        ),
                        generator_keys=tuple(plan.knowledge_generator_keys),
                        audit_only_keys=tuple(plan.knowledge_audit_only_keys),
                    )
                    outcome = await run_governed_generation(
                        client,
                        policy=require_capability_policy(plan.knowledge_policy_id),
                        scope_build=scope_build,
                        hooks=GovernedWorkflowHooks(
                            generate=_governed_generate,
                            repair=None,
                            task_instruction=plan.knowledge_task_instruction,
                            generator_context=plan.knowledge_generator_context,
                            authority_context=plan.knowledge_authority_context,
                            hidden_phrases=tuple(plan.knowledge_hidden_phrases),
                        ),
                        step_prefix="writing.generate",
                        enforce_scope_complete=False,
                    )
                    managed_llm_provenance = build_managed_llm_provenance(
                        client,
                        step_name="writing.generation.candidate.generate",
                        request=plan.request,
                        novel_id=plan.novel_id,
                    )
                    model_name = response_holder.get("model") or getattr(
                        client,
                        "model_name",
                        plan.request.model,
                    )
                    knowledge_review = knowledge_review_payload(
                        audit=outcome.audit,
                        repaired=outcome.repaired,
                        visible_keys=outcome.generator_keys,
                        hidden_phrases=tuple(plan.knowledge_hidden_phrases),
                    )
                    knowledge_review.update(
                        {
                            "scope_receipt_fingerprint": (
                                scope_build.receipt.receipt_fingerprint()
                            ),
                            "director_plan_fingerprint": outcome.plan.plan_fingerprint(),
                            "audit_fingerprint": outcome.audit.audit_fingerprint(),
                            "stage_trace": list(outcome.stage_trace),
                        }
                    )
                    candidate = self._build_candidate_create(
                        novel_id=plan.novel_id,
                        chapter_index=plan.chapter_index,
                        title=plan.title,
                        context_confirmation_id=plan.context_confirmation_id,
                        source_task_id=plan.source_task_id,
                        context_result_refs=list(plan.context_result_refs),
                        profile=plan.profile,
                        prompt=plan.prompt,
                        response_content=outcome.raw_output,
                        model_name=model_name,
                        managed_llm_provenance=managed_llm_provenance,
                        guard_terms=list(plan.hidden_guard_terms),
                        generation_mode=plan.generation_mode,
                        base_draft_id=plan.base_draft_id,
                        base_content=plan.base_content,
                        base_content_hash=plan.base_content_hash,
                        scene_id=plan.scene_id,
                        scene_execution_bundle=plan.scene_execution_bundle,
                        scene_execution_bundle_hash=plan.scene_execution_bundle_hash,
                        knowledge_review=knowledge_review,
                        author_examples_used=plan.author_examples_used,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                from infrastructure.llm.retry import is_retryable_llm_error

                safe_error = redact_diagnostic(
                    f"{type(exc).__name__}: {exc}",
                    limit=500,
                )
                logger.warning("Writing generation task failed: %s", safe_error)
                if is_retryable_llm_error(exc):
                    raise
                raise RuntimeError(safe_error) from None

            if freeze_paid_output:
                from infrastructure.tasks.facade import write_private_task_checkpoint

                await write_private_task_checkpoint(
                    db,
                    task_id=source_task_id,
                    task_type="writing_generate",
                    novel_id=novel_id,
                    key=_FROZEN_GENERATION_CANDIDATE_META_KEY,
                    payload={
                        "version": _FROZEN_GENERATION_CANDIDATE_VERSION,
                        "source_fingerprint": str(plan.source_fingerprint),
                        "candidate": candidate.model_dump(mode="json"),
                    },
                )

        return await self._finalize_generation_task(
            db,
            plan=plan,
            candidate=candidate,
        )

    async def _finalize_generation_task(
        self,
        db: AsyncSession,
        *,
        plan: _WritingGenerationTaskPlan,
        candidate: WritingDraftCreate,
    ) -> WritingDraftResponse:
        from modules.evidence.facade import (
            bind_confirmed_action_result,
            build_hidden_guard_context,
            prepare_confirmed_ai_action,
        )
        from modules.project.facade import (
            require_active_project,
            restore_project_llm_execution_settings,
        )

        await require_active_project(db, plan.novel_id)
        if self._llm is None:
            # The provider wait releases the project lock. Revalidate the frozen
            # executable profile after reacquiring it so endpoint/provider drift
            # cannot publish a result produced from superseded settings.
            await restore_project_llm_execution_settings(
                db,
                plan.novel_id,
                plan.llm_execution_snapshot,
            )
        confirmed_context = await prepare_confirmed_ai_action(
            db,
            novel_id=plan.novel_id,
            action="writing.generate",
            confirmation_id=plan.context_confirmation_id,
            for_update=True,
        )
        self._require_task_confirmation_owner(
            confirmed_context,
            chapter_index=plan.chapter_index,
            source_task_id=plan.source_task_id,
        )
        profile = self._task_profile(confirmed_context)
        current_execution_bundle = await self._execution_bundle(
            db,
            novel_id=plan.novel_id,
            scene_id=plan.scene_id,
        )
        current_execution_bundle_hash = (
            str(current_execution_bundle.get("contract_hash") or "")
            if current_execution_bundle
            else None
        )
        if (
            _story_assets_are_stale(current_execution_bundle)
            and not plan.confirm_stale_story_assets
        ):
            raise ValidationError(
                "已采用的 Scene 剧本依据已变化；已丢弃未确认的正文结果",
                code="stale_story_assets",
                status_code=409,
            )
        base_draft = await self._load_generation_base(
            db,
            novel_id=plan.novel_id,
            chapter_index=plan.chapter_index,
            generation_mode=plan.generation_mode,
            base_draft_id=plan.base_draft_id,
            for_update=True,
        )
        guard_terms: tuple[_FrozenHiddenGuardTerm, ...] = ()
        if profile.profile == GenerationProfile.POV_CHARACTER:
            guard_terms = self._freeze_guard_terms(
                await build_hidden_guard_context(
                    db,
                    confirmed_context=confirmed_context,
                )
            )
        current_fingerprint = _generation_task_source_fingerprint(
            confirmed_context,
            profile=profile,
            hidden_guard_terms=guard_terms,
            generation_mode=plan.generation_mode,
            base_draft=base_draft,
            scene_execution_bundle_hash=current_execution_bundle_hash,
            confirm_stale_story_assets=plan.confirm_stale_story_assets,
            story_asset_basis=list(plan.story_asset_basis),
        )
        if current_fingerprint != plan.source_fingerprint:
            raise ValidationError(
                "Writing generation context changed while the task was running; "
                "discarded stale result"
            )

        # 来源指纹与 finalize 重算值同源落盘：此前只在任务内校验、不持久化，
        # 进度投影与后续流程无法据此核对新鲜度。
        candidate.provenance_json = {
            **(candidate.provenance_json or {}),
            "source_fingerprint": current_fingerprint,
        }
        draft = await self._repo.create_with_status(db, candidate, status="candidate")
        await bind_confirmed_action_result(
            db,
            novel_id=plan.novel_id,
            confirmation_id=plan.context_confirmation_id,
            result_type="writing_draft",
            result_id=str(draft.id),
            status="done",
        )
        return WritingDraftResponse.model_validate(draft)
