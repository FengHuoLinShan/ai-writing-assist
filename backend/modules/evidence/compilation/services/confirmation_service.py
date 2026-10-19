"""Context confirmation service."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get
from core.errors import ConflictError, ValidationError
from core.service_keys import (
    STORY_GET_SCENE_CONTRACT,
    STORY_SCENE_SOURCE,
    STORY_VALIDATE_EXPLORATION_HANDOFF,
    WORLD_GET_CHARACTER_ID_BY_WORLD_ENTITY,
)
from infrastructure.stable_hash import stable_hash
from modules.evidence.compilation.contracts import (
    CompileOptions,
    ContextConfirmationContract,
    ContextConfirmationRequest,
)
from modules.evidence.compilation.repositories import ContextConfirmationRepository
from modules.evidence.compilation.schemas import ExplorationContextRequest
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    compiled_context_fingerprint,
)
from modules.evidence.compilation.services.context_compiler import ContextCompiler
from modules.evidence.compilation.services.review_projection import (
    context_review_metadata,
)
from shared.utils import parse_uuid


def _scene_memory_port():
    # AO-5: story Scene memory 契约经组合根注册的只读 port 解析，
    # 不再顶层 import modules.story.contracts。
    return get(STORY_SCENE_SOURCE)


_ASSET_TYPE_ALIASES = {
    "outline_scene": "scene",
    "scene_story_assets": "scene",
    "scenes": "scene",
    "outline_arcs": "outline_arc",
    "world_entities": "world_entity",
    "characters": "character",
    "locations": "location",
    "plot_threads": "plot_thread",
    "foreshadowing_plans": "foreshadowing_plan",
    "reveal_plans": "reveal_plan",
    "context_sections": "context_section",
}

_MAP_CONFIRMATION_METADATA = frozenset(
    {"map_spatial_baseline", "compiled_context_core_fingerprint"}
)
_ADVISORY_REFERENCE_SECTION_KEYS = frozenset({"map_spatial", "director_reference"})

EXPLORATION_ACTION_PREFIX = "story.exploration."
"""导演多尺度独立探索动作前缀；detail/revise 编辑类不新开确认，复用根确认。"""

_EXPLORATION_ACTION_SCALES = {
    "story.exploration.sandbox.generate": "sandbox",
    "story.exploration.event.diagnose": "event",
    "story.exploration.event.bridge": "event",
    "story.exploration.scene_line.generate": "scene_line",
}

_EXPLORATION_FROZEN_OPTION_KEYS = (
    "start_kind",
    "exploration_start",
    "exploration_scale",
    "exploration_focus",
    "exploration_fingerprint_version",
    "exploration_input_core_fingerprint",
)


def _exploration_fingerprint(context_fingerprint: str, frozen: dict) -> str:
    return stable_hash(
        {
            "context": context_fingerprint,
            "start": frozen["exploration_start"],
            "scale": frozen["exploration_scale"],
            "focus": frozen["exploration_focus"],
        }
    )


def _pop_exploration_frozen_options(compile_options: dict[str, Any]) -> dict[str, Any]:
    """摘出探索冻结键；CompileOptions 不承载这些字段，回放后经 selection_trace 回传。"""
    return {
        key: compile_options.pop(key)
        for key in _EXPLORATION_FROZEN_OPTION_KEYS
        if key in compile_options
    }


def _validate_exploration_reveal_mode(request: ExplorationContextRequest) -> None:
    """探索确认的揭示模式：作者包默认 author_safe；canonical 角色 POV 需视角与截止点。"""
    if request.reveal_mode == "reader":
        raise ValidationError("探索确认不支持 reader 揭示模式")
    if request.reveal_mode == "character":
        if not request.viewpoint_character_id:
            raise ValidationError("character 视角探索必须提供 viewpoint_character_id")
        if request.visible_until_chapter is None and not request.visible_until_scene_id:
            raise ValidationError("character 视角探索必须提供可见截止点")


async def _validate_exploration_scene_anchor(
    db: AsyncSession,
    request: ExplorationContextRequest,
) -> None:
    """Scene 锚点起点：存在性 + 可见截止对齐（对齐 _validate_confirmed_scene_scope）。"""
    start = request.start
    scene_contract = await get(STORY_GET_SCENE_CONTRACT)(
        db,
        request.novel_id,
        start.scene_id,
    )
    if scene_contract is None:
        raise ValidationError("探索锚点 Scene 不存在或不属于当前项目，请重新选择")
    if (
        request.visible_until_scene_id
        and request.visible_until_scene_id != start.scene_id
    ):
        raise ValidationError("探索确认的可见截止必须与锚点 Scene 一致")


async def _validate_exploration_provisional_start(
    db: AsyncSession,
    request: ExplorationContextRequest,
) -> None:
    """临时假设起点：不绑 Scene；正式角色引用失败关闭；web_refs 只能服务端冻结。"""
    start = request.start
    if request.visible_until_scene_id:
        raise ValidationError("临时假设起点不能绑定 Scene 可见截止点")
    if start.derived_from:
        await get(STORY_VALIDATE_EXPLORATION_HANDOFF)(db, request.novel_id, start)
    elif start.web_refs:
        raise ValidationError(
            "web_refs 只能由服务端从助手当轮网页快照冻结填充；"
            "请通过助手当轮确认联网来源，不能在请求中直传"
        )
    candidate_ids = {candidate.ref_id for candidate in start.candidates}
    entity_ids: set[str] = set(start.canonical_refs)
    entity_ids.update(item.subject_entity_id for item in start.scene_stimuli)
    for entry in start.knowledge:
        if entry.subject_ref in candidate_ids:
            continue
        try:
            uuid.UUID(entry.subject_ref)
        except (ValueError, AttributeError, TypeError) as error:
            raise ValidationError(
                "knowledge.subject_ref 必须是候选 ref_id 或正式角色 entity_id: "
                f"{entry.subject_ref}"
            ) from error
        entity_ids.add(entry.subject_ref)
    for entity_id in sorted(entity_ids):
        resolved = await get(WORLD_GET_CHARACTER_ID_BY_WORLD_ENTITY)(
            db,
            request.novel_id,
            entity_id,
        )
        if not resolved:
            raise ValidationError(
                f"探索引用的正式角色不存在、非正史或不属于当前项目: {entity_id}"
            )


async def validate_exploration_request(
    db: AsyncSession,
    request: ExplorationContextRequest,
) -> None:
    """story.exploration.* 预览/确认共用的失败关闭校验（P0 冻结契约 §2.3）。"""
    expected_scale = _EXPLORATION_ACTION_SCALES.get(request.action)
    if expected_scale is None:
        raise ValidationError(
            f"不支持的探索操作: {request.action}，"
            f"必须是 {', '.join(sorted(_EXPLORATION_ACTION_SCALES))} 之一"
        )
    if request.exploration_scale != expected_scale:
        raise ValidationError(
            f"exploration_scale 与操作不匹配：{request.action} 要求 {expected_scale}"
        )
    if request.start.kind == "provisional":
        if request.scope != "project":
            raise ValidationError("临时假设起点的确认范围必须是 project")
        await _validate_exploration_provisional_start(db, request)
    else:
        if request.scope != "scene":
            raise ValidationError("Scene 锚点起点的确认范围必须是 scene")
        await _validate_exploration_scene_anchor(db, request)
    _validate_exploration_reveal_mode(request)


def execution_compile_options(options: Mapping[str, Any]) -> dict[str, Any]:
    """Strip confirmation-only map baselines before constructing CompileOptions."""
    return {
        key: value
        for key, value in options.items()
        if key not in _MAP_CONFIRMATION_METADATA
    }


def _map_spatial_baseline(compiled: CompiledContext) -> list[dict[str, Any]]:
    for section in compiled.sections:
        if section.key == "map_spatial":
            baseline = (section.retrieval_metadata or {}).get("map_baseline") or []
            return sorted(
                [dict(item) for item in baseline if isinstance(item, dict)],
                key=lambda item: str(item.get("node_id") or ""),
            )
    return []


def _core_context_fingerprint(compiled: CompiledContext) -> str:
    return compiled_context_fingerprint(
        compiled.model_copy(
            update={
                "sections": [
                    section
                    for section in compiled.sections
                    if section.key not in _ADVISORY_REFERENCE_SECTION_KEYS
                ]
            }
        )
    )


def _omit_changed_map_reference(
    compiled: CompiledContext,
    *,
    expected: list[dict[str, Any]],
    current: list[dict[str, Any]],
) -> None:
    section = next(
        (item for item in compiled.sections if item.key == "map_spatial"), None
    )
    if section is not None:
        compiled.omitted_items.extend(
            item.model_copy(
                update={
                    "selection_state": "omitted",
                    "omission_reason": "确认后地图版本变化，空间参考已省略",
                }
            )
            for item in section.materialize_items().items
        )
        compiled.sections = [
            item for item in compiled.sections if item.key != "map_spatial"
        ]
        compiled.total_tokens = sum(item.token_count for item in compiled.sections)
    compiled.warnings = list(
        dict.fromkeys(
            [
                *compiled.warnings,
                "确认后地图版本发生变化，空间参考已省略；可重新核对地图版本后再确认。",
            ]
        )
    )
    compiled.selection_trace["map_spatial_staleness"] = {
        "status": "changed",
        "expected_baseline": expected,
        "current_baseline": current,
    }


def _exploration_compile_options(request: ExplorationContextRequest) -> CompileOptions:
    """探索预览用 CompileOptions；字段映射与 confirm_context 保持一致。"""
    return CompileOptions(
        novel_id=request.novel_id,
        task=request.task,
        scope=request.scope,
        consumer_action=request.action,
        retrieval_purpose=resolve_retrieval_purpose(
            request.action,
            request.retrieval_purpose,
            reveal_mode=request.reveal_mode,
        ),
        chapter_index=request.chapter_index,
        requested_chapter_index=request.chapter_index,
        visible_until_chapter=request.visible_until_chapter,
        visible_until_scene_id=request.visible_until_scene_id,
        visible_until_offset=request.visible_until_offset,
        scene_id=request.scene_id,
        arc_id=request.arc_id,
        entity_ids=request.entity_ids,
        character_ids=request.character_ids,
        thread_ids=request.thread_ids,
        location_ids=request.location_ids,
        reveal_mode=request.reveal_mode,
        enable_geo_filter=request.enable_geo_filter,
        viewpoint_character_id=request.viewpoint_character_id,
        budget_tokens=request.budget_tokens,
        context_mode=request.context_mode,
        content_mode=request.content_mode,
        include_pending_objects=request.include_pending_objects,
        excluded_asset_ids=request.excluded_asset_ids or {},
        pinned_refs=[item.model_dump(mode="json") for item in request.pinned_refs],
        excluded_refs=[item.model_dump(mode="json") for item in request.excluded_refs],
        user_note=request.user_note,
        include_world_synopsis=request.include_world_synopsis,
        selected_world_bible_draft_ids=request.selected_world_bible_draft_ids or [],
        director_reference_ids=request.director_reference_ids or [],
        activation_profile_id=request.activation_profile_id,
        activation_profile_version=request.activation_profile_version,
        scene_memory_contract_version=(
            _scene_memory_port().scene_memory_current_version()
        ),
    )


def _exploration_selection(
    request: ExplorationContextRequest,
) -> ExplorationContextRequest:
    if request.start.kind != "provisional":
        return request
    characters = list(
        dict.fromkeys(
            [
                *(request.character_ids or []),
                *request.start.canonical_refs,
                *(item.subject_entity_id for item in request.start.scene_stimuli),
                *(
                    item.subject_ref
                    for item in request.start.knowledge
                    if not item.subject_ref.startswith("c_")
                ),
            ]
        )
    )
    return request.model_copy(
        update={
            "character_ids": characters,
            "entity_ids": list(dict.fromkeys([*(request.entity_ids or []), *characters])),
        }
    )


async def _bind_handoff_options(db, options, start):
    if not start or not start.get("derived_from"):
        return options
    from modules.evidence.compilation.exploration_start import ProvisionalStart

    inherited = await get(STORY_VALIDATE_EXPLORATION_HANDOFF)(
        db, options.novel_id, ProvisionalStart.model_validate(start)
    )
    # A handoff changes the task, never its historical read window or exclusions.
    for key in (
        "scope",
        "reveal_mode",
        "viewpoint_character_id",
        "scene_id",
        "chapter_index",
        "requested_chapter_index",
        "visible_until_scene_id",
        "visible_until_chapter",
        "visible_until_offset",
        "entity_ids",
        "character_ids",
        "thread_ids",
        "location_ids",
        "arc_id",
        "excluded_asset_ids",
        "excluded_refs",
        "pinned_refs",
        "selected_world_bible_draft_ids",
        "include_world_synopsis",
        "include_pending_objects",
        "source_manifest",
    ):
        if key in inherited:
            setattr(options, key, inherited[key])
    return options


def _exploration_confirmation_request(
    request: ExplorationContextRequest,
) -> ContextConfirmationRequest:
    """把探索请求映射为通用确认请求；起点以判别联合 dump 随确认冻结。"""
    return ContextConfirmationRequest(
        novel_id=request.novel_id,
        action=request.action,
        task=request.task,
        scope=request.scope,
        retrieval_purpose=request.retrieval_purpose,
        chapter_index=request.chapter_index,
        visible_until_chapter=request.visible_until_chapter,
        visible_until_scene_id=request.visible_until_scene_id,
        visible_until_offset=request.visible_until_offset,
        scene_id=request.scene_id,
        arc_id=request.arc_id,
        entity_ids=request.entity_ids,
        character_ids=request.character_ids,
        thread_ids=request.thread_ids,
        location_ids=request.location_ids,
        reveal_mode=request.reveal_mode,
        enable_geo_filter=request.enable_geo_filter,
        viewpoint_character_id=request.viewpoint_character_id,
        budget_tokens=request.budget_tokens,
        context_mode=request.context_mode,
        content_mode=request.content_mode,
        include_pending_objects=request.include_pending_objects,
        excluded_asset_ids=request.excluded_asset_ids or {},
        pinned_refs=[item.model_dump(mode="json") for item in request.pinned_refs],
        excluded_refs=[item.model_dump(mode="json") for item in request.excluded_refs],
        user_note=request.user_note,
        include_world_synopsis=request.include_world_synopsis,
        selected_world_bible_draft_ids=request.selected_world_bible_draft_ids or [],
        director_reference_ids=request.director_reference_ids or [],
        activation_profile_id=request.activation_profile_id,
        activation_profile_version=request.activation_profile_version,
        expected_context_fingerprint=request.expected_context_fingerprint,
        exploration_start=request.start.model_dump(mode="json"),
        exploration_scale=request.exploration_scale,
        exploration_focus=request.focus,
    )


class ContextConfirmationService:
    async def preview_confirmation(self, db, options: CompileOptions) -> dict:
        from dataclasses import replace

        options = replace(
            options,
            requested_chapter_index=options.chapter_index,
            retrieval_purpose=resolve_retrieval_purpose(
                options.consumer_action or "",
                options.retrieval_purpose,
                reveal_mode=options.reveal_mode,
            ),
        )
        compiled = await self._compiler.compile_with_tiers(
            db, options, budget_tokens=options.budget_tokens
        )
        review = context_review_metadata(compiled, options)
        return {
            "context_fingerprint": review["context_fingerprint"],
            "selected_asset_ids": review["selected_asset_ids"],
            "sources": [
                {"title": item.title or section.title, "source": item.source}
                for section in compiled.sections
                for item in section.items
                if item.source
            ],
            "blockers": list(compiled.blockers),
        }

    async def preview_exploration(
        self,
        db: AsyncSession,
        request: ExplorationContextRequest,
    ) -> dict:
        """探索确认预览：同一套失败关闭校验，不落确认记录。"""
        await validate_exploration_request(db, request)
        request = _exploration_selection(request)
        preview = await self.preview_confirmation(
            db,
            await _bind_handoff_options(
                db,
                _exploration_compile_options(request),
                request.start.model_dump(mode="json"),
            ),
        )
        preview["context_fingerprint"] = _exploration_fingerprint(
            preview["context_fingerprint"],
            {
                "exploration_start": request.start.model_dump(mode="json"),
                "exploration_scale": request.exploration_scale,
                "exploration_focus": request.focus,
            },
        )
        return preview

    async def confirm_exploration(
        self,
        db: AsyncSession,
        request: ExplorationContextRequest,
    ) -> ContextConfirmationContract:
        """探索确认：校验后复用通用确认流；起点/尺度/焦点随 compile_options 冻结。"""
        await validate_exploration_request(db, request)
        request = _exploration_selection(request)
        return await self.confirm_context(
            db,
            _exploration_confirmation_request(request),
        )

    """Owns AI reference confirmation semantics."""

    def __init__(
        self,
        repository: ContextConfirmationRepository | None = None,
        compiler: ContextCompiler | None = None,
    ) -> None:
        self._repo = repository or ContextConfirmationRepository()
        self._compiler = compiler or ContextCompiler()

    async def confirm_context(
        self,
        db: AsyncSession,
        request: ContextConfirmationRequest,
    ) -> ContextConfirmationContract:
        action = request.action
        exploration = action.startswith(EXPLORATION_ACTION_PREFIX)
        if exploration and request.exploration_start is None:
            raise ValidationError("探索确认必须携带 exploration_start 起点")
        retrieval_purpose = resolve_retrieval_purpose(
            action,
            request.retrieval_purpose,
            reveal_mode=request.reveal_mode,
        )
        options = CompileOptions(
            novel_id=request.novel_id,
            task=request.task,
            scope=request.scope,
            consumer_action=action,
            retrieval_purpose=retrieval_purpose,
            chapter_index=request.chapter_index,
            requested_chapter_index=request.chapter_index,
            planning_window_end=request.planning_window_end,
            visible_until_chapter=request.visible_until_chapter,
            visible_until_scene_id=request.visible_until_scene_id,
            visible_until_offset=request.visible_until_offset,
            scene_id=request.scene_id,
            arc_id=request.arc_id,
            entity_ids=request.entity_ids,
            character_ids=request.character_ids,
            thread_ids=request.thread_ids,
            location_ids=request.location_ids,
            reveal_mode=request.reveal_mode,
            enable_geo_filter=request.enable_geo_filter,
            viewpoint_character_id=request.viewpoint_character_id,
            budget_tokens=request.budget_tokens,
            context_mode=request.context_mode,
            content_mode=request.content_mode,
            include_pending_objects=request.include_pending_objects,
            excluded_asset_ids=request.excluded_asset_ids or {},
            pinned_refs=request.pinned_refs or [],
            excluded_refs=request.excluded_refs or [],
            user_note=request.user_note,
            include_world_synopsis=request.include_world_synopsis,
            selected_world_bible_draft_ids=request.selected_world_bible_draft_ids or [],
            director_reference_ids=request.director_reference_ids or [],
            activation_profile_id=request.activation_profile_id,
            activation_profile_version=request.activation_profile_version,
            scene_memory_contract_version=(
                _scene_memory_port().scene_memory_current_version()
            ),
        )
        options = await _bind_handoff_options(db, options, request.exploration_start)
        compiled = await self._compiler.compile_with_tiers(
            db,
            options,
            budget_tokens=request.budget_tokens,
        )
        if self._requires_character_profile(options):
            self._require_character_profile(compiled)
        if action == "outline.analyze":
            self._require_outline_analysis_range(compiled, options)
        review = context_review_metadata(compiled, options)
        if exploration:
            review["context_fingerprint"] = _exploration_fingerprint(
                review["context_fingerprint"],
                {
                    "exploration_start": request.exploration_start,
                    "exploration_scale": request.exploration_scale or "",
                    "exploration_focus": request.exploration_focus or "",
                },
            )
        if compiled.blockers:
            raise ValueError("；".join(compiled.blockers))
        if (
            request.expected_context_fingerprint
            and review["context_fingerprint"] != request.expected_context_fingerprint
        ):
            raise ConflictError(
                "AI 参考资料已变化，请重新审查后再开始任务",
                code="context_preview_changed",
            )
        options.compiled_context_fingerprint = review["context_fingerprint"]
        selected_asset_ids = review["selected_asset_ids"]
        warnings = list(compiled.warnings)
        compile_options_json = self._compile_options_json(options)
        compile_options_json.update(
            {
                "map_spatial_baseline": _map_spatial_baseline(compiled),
                "compiled_context_core_fingerprint": _core_context_fingerprint(compiled),
            }
        )
        if exploration:
            # P0 冻结契约 §2.4：起点/尺度/焦点随确认冻结；指纹覆盖由
            # compiled_context_core_fingerprint 承担，不新增 DB 列。
            compile_options_json.update(
                {
                    "start_kind": str(request.exploration_start.get("kind") or ""),
                    "exploration_start": request.exploration_start,
                    "exploration_scale": request.exploration_scale or "",
                    "exploration_focus": request.exploration_focus or "",
                    "exploration_fingerprint_version": 1,
                    "exploration_input_core_fingerprint": _exploration_fingerprint(
                        _core_context_fingerprint(compiled),
                        {
                            "exploration_start": request.exploration_start,
                            "exploration_scale": request.exploration_scale,
                            "exploration_focus": request.exploration_focus or "",
                        },
                    ),
                }
            )
        record = await self._repo.create(
            db,
            novel_id=parse_uuid(request.novel_id, "novel_id"),
            action=action,
            task=request.task,
            scope=request.scope,
            context_mode=request.context_mode,
            include_pending_objects=request.include_pending_objects,
            excluded_asset_ids=request.excluded_asset_ids or {},
            selected_asset_ids=selected_asset_ids,
            user_note=request.user_note,
            compile_options=compile_options_json,
            warnings=warnings,
        )
        await self._repo.replace_asset_refs(
            db,
            record,
            asset_role="selected",
            refs=self._selected_refs(selected_asset_ids),
        )
        return self._to_contract(record, compiled=compiled, review=review)

    async def require_confirmation(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        action: str,
        confirmation_id: str | uuid.UUID,
        for_update: bool = False,
    ) -> ContextConfirmationContract:
        record = await self._repo.get(
            db,
            self._as_uuid(confirmation_id),
            novel_id=parse_uuid(novel_id, "novel_id"),
            for_update=for_update,
        )
        if record is None:
            raise ValueError("context_confirmation_id not found")
        if record.action != action:
            raise ValueError("context confirmation action mismatch")
        return self._to_contract(record)

    async def get_confirmation(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmation_id: str | uuid.UUID,
    ) -> ContextConfirmationContract:
        """Read one author-owned confirmation without recompiling its context."""
        record = await self._repo.get(
            db,
            self._as_uuid(confirmation_id),
            novel_id=parse_uuid(novel_id, "novel_id"),
        )
        if record is None:
            raise ValueError("context confirmation not found")
        return self._to_contract(record)

    async def get_staleness_map(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmation_ids: Sequence[str | uuid.UUID],
    ) -> dict[str, dict[str, Any]]:
        """批量只读确认失效信号，供跨模块进度投影使用；不重编译、不判定。

        与 ``require_fresh_confirmation`` 同一口径：``stale_reasons`` 非空或
        result_status 进入 stale_context/needs_review 即视为已失效。
        """
        ids: list[uuid.UUID] = []
        for value in confirmation_ids:
            try:
                ids.append(self._as_uuid(value))
            except ValueError:
                continue
        if not ids:
            return {}
        rows = await self._repo.list_by_ids(
            db,
            ids,
            novel_id=parse_uuid(novel_id, "novel_id"),
        )
        return {
            str(row.id): {
                "result_status": row.result_status,
                "stale": bool(row.stale_reasons)
                or row.result_status in {"stale_context", "needs_review"},
            }
            for row in rows
        }

    async def require_fresh_confirmation(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        action: str,
        confirmation_id: str | uuid.UUID,
        for_update: bool = False,
    ) -> ContextConfirmationContract:
        confirmation = await self.require_confirmation(
            db,
            novel_id=novel_id,
            action=action,
            confirmation_id=confirmation_id,
            for_update=for_update,
        )
        if confirmation.result_status in {"stale_context", "needs_review"} or (
            confirmation.stale_reasons
        ):
            raise ValueError("参考资料已更新，请重新确认后开始任务")
        return confirmation

    async def compile_from_confirmation(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        action: str,
        confirmation_id: str | uuid.UUID,
        consumer_action: str | None = None,
    ) -> CompiledContext:
        confirmation = await self.require_confirmation(
            db,
            novel_id=novel_id,
            action=action,
            confirmation_id=confirmation_id,
        )
        compile_options = dict(confirmation.compile_options)
        # 探索冻结键先摘出：CompileOptions 不承载这些字段；回放完成后经
        # selection_trace 回传给调用方（worker 校验与请求一致，不一致失败关闭）。
        start_kind = compile_options.get("start_kind")
        frozen_exploration = _pop_exploration_frozen_options(compile_options)
        frozen_start = frozen_exploration.get("exploration_start") or {}
        if frozen_start.get("derived_from"):
            from modules.evidence.compilation.exploration_start import ProvisionalStart

            await get(STORY_VALIDATE_EXPLORATION_HANDOFF)(
                db, novel_id, ProvisionalStart.model_validate(frozen_start)
            )
        expected_map_baseline = compile_options.pop("map_spatial_baseline", None)
        expected_core_fingerprint = compile_options.pop(
            "compiled_context_core_fingerprint", None
        )
        compile_options.setdefault(
            "scene_memory_contract_version",
            _scene_memory_port().scene_memory_v1_version(),
        )
        options = CompileOptions(**compile_options)
        if consumer_action:
            options.map_spatial_consumer_action = consumer_action
        compiled = await self._compiler.compile_with_tiers(
            db,
            options,
            budget_tokens=options.budget_tokens,
        )
        if self._requires_character_profile(options):
            self._require_character_profile(compiled)
        if action == "outline.analyze":
            self._require_outline_analysis_range(compiled, options)
        # 临时起点没有 Scene/大纲分析：跳过 outline 与 scene_state 指纹门；
        # Scene 锚点起点与非探索确认一样走现有全部门禁。
        if start_kind != "provisional":
            if (
                not options.compiled_context_fingerprint
                and options.outline_analysis_fingerprint
            ):
                current_fingerprint = self._outline_analysis_fingerprint(compiled)
                if current_fingerprint != options.outline_analysis_fingerprint:
                    raise ValueError(
                        "outline analysis context changed; "
                        "review and confirm the latest context"
                    )
            if options.scene_state_fingerprint and (
                not options.compiled_context_fingerprint
            ):
                current_fingerprint = self._scene_state_fingerprint(compiled)
                if current_fingerprint != options.scene_state_fingerprint:
                    raise ConflictError(
                        "Scene time state changed; review and confirm the latest context",
                        code="scene_state_changed",
                    )
        if expected_core_fingerprint is not None:
            current_core_fingerprint = _core_context_fingerprint(compiled)
            if current_core_fingerprint != expected_core_fingerprint:
                raise ConflictError(
                    "AI 参考资料已变化，请重新审查后再开始任务",
                    code="context_changed",
                )
            current_map_baseline = _map_spatial_baseline(compiled)
            if current_map_baseline != (expected_map_baseline or []) and (
                not consumer_action or consumer_action == action or expected_map_baseline
            ):
                _omit_changed_map_reference(
                    compiled,
                    expected=expected_map_baseline or [],
                    current=current_map_baseline,
                )
        elif options.compiled_context_fingerprint:
            current_fingerprint = context_review_metadata(compiled, options)[
                "context_fingerprint"
            ]
            if current_fingerprint != options.compiled_context_fingerprint:
                raise ConflictError(
                    "AI 参考资料已变化，请重新审查后再开始任务",
                    code="context_changed",
                )
        if frozen_exploration:
            if frozen_exploration.get("exploration_fingerprint_version") == 1:
                current = _exploration_fingerprint(
                    _core_context_fingerprint(compiled),
                    frozen_exploration,
                )
                if current != frozen_exploration.get(
                    "exploration_input_core_fingerprint"
                ):
                    raise ConflictError(
                        "探索起点或资料已变化，请重新预览并确认", code="context_changed"
                    )
            compiled.selection_trace["exploration"] = {
                "start_kind": frozen_exploration.get("start_kind"),
                "exploration_start": frozen_exploration.get("exploration_start"),
                "exploration_scale": frozen_exploration.get("exploration_scale"),
                "exploration_focus": frozen_exploration.get("exploration_focus"),
            }
        return compiled

    async def attach_result_ref(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmation_id: str | uuid.UUID,
        result_type: str,
        result_id: str,
        status: str = "running",
    ) -> ContextConfirmationContract:
        normalized_ref = self._validated_result_ref(result_type, result_id)
        record = await self._repo.get(
            db,
            self._as_uuid(confirmation_id),
            novel_id=parse_uuid(novel_id, "novel_id"),
            for_update=True,
        )
        if record is None:
            raise ValueError("context_confirmation_id not found")
        refs = [
            ref
            for ref in (record.result_refs or [])
            if not (
                ref.get("type") == normalized_ref["type"]
                and ref.get("id") == normalized_ref["id"]
            )
        ]
        refs.append(normalized_ref)
        updated = await self._repo.update_tracking(
            db,
            record,
            result_refs=refs,
            result_status=status,
        )
        await self._repo.replace_asset_refs(
            db,
            updated,
            asset_role="result",
            refs=self._result_refs(refs),
        )
        return self._to_contract(updated)

    async def attach_result_refs(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmation_id: str | uuid.UUID,
        result_refs: list[dict[str, str]],
        status: str = "running",
    ) -> ContextConfirmationContract:
        normalized_result_refs = [
            self._validated_result_ref(ref.get("type"), ref.get("id"))
            for ref in result_refs
        ]
        record = await self._repo.get(
            db,
            self._as_uuid(confirmation_id),
            novel_id=parse_uuid(novel_id, "novel_id"),
            for_update=True,
        )
        if record is None:
            raise ValueError("context_confirmation_id not found")

        refs_by_key = {
            (ref.get("type"), ref.get("id")): {
                "type": ref.get("type"),
                "id": ref.get("id"),
            }
            for ref in (record.result_refs or [])
        }
        for result_ref in normalized_result_refs:
            result_type = result_ref.get("type")
            result_id = result_ref.get("id")
            key = (result_type, result_id)
            refs_by_key.pop(key, None)
            refs_by_key[key] = {"type": result_type, "id": result_id}

        updated = await self._repo.update_tracking(
            db,
            record,
            result_refs=list(refs_by_key.values()),
            result_status=status,
        )
        await self._repo.replace_asset_refs(
            db,
            updated,
            asset_role="result",
            refs=self._result_refs(list(refs_by_key.values())),
        )
        return self._to_contract(updated)

    async def describe_task_outcomes(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        task_ids: Sequence[str],
    ) -> dict[str, dict[str, Any]]:
        """Read-only: map task ids to their confirmed-action outcome summary.

        用量归因等跨模块只读消费使用；不加锁、不重编译、不改任何状态。
        结果引用里的任务按追加顺序去重，最后一条任务引用是本次确认的
        归属任务（`owner_task`），更早的同确认任务是被取代的旧尝试。
        一个任务被多条确认引用时，先取它是归属任务的确认，再取最新一条。
        没有任何确认引用的任务不出现在返回值里。
        """
        normalized_ids = [str(task_id).strip() for task_id in task_ids]
        normalized_ids = [task_id for task_id in normalized_ids if task_id]
        if not normalized_ids:
            return {}
        records = await self._repo.list_result_confirmations_for_asset_ids(
            db,
            novel_id=parse_uuid(novel_id, "novel_id"),
            asset_type="task",
            asset_ids=normalized_ids,
        )
        outcomes: dict[str, tuple[datetime, bool, dict[str, Any]]] = {}
        for record in records:
            task_refs = [
                str(ref.get("id"))
                for ref in (record.result_refs or [])
                if isinstance(ref, Mapping)
                and str(ref.get("type") or "") == "task"
                and str(ref.get("id") or "").strip()
            ]
            if not task_refs:
                continue
            owner_task = task_refs[-1]
            # created_at 只用于多条确认之间的稳定排序，不出现在返回值里。
            ordered_at = record.created_at or record.compiled_at or datetime.now(UTC)
            for task_id in dict.fromkeys(task_refs):
                entry = {
                    "confirmation_id": str(record.id),
                    "result_status": str(record.result_status or ""),
                    "owner_task": task_id == owner_task,
                }
                current = outcomes.get(task_id)
                if current is None or (entry["owner_task"], ordered_at) > (
                    current[1],
                    current[0],
                ):
                    outcomes[task_id] = (ordered_at, entry["owner_task"], entry)
        return {task_id: value[2] for task_id, value in outcomes.items()}

    async def mark_asset_context_changed(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        asset_type: str,
        asset_id: str,
        reason: str,
        exclude_confirmation_id: str | uuid.UUID | None = None,
    ) -> int:
        query = {
            "novel_id": parse_uuid(novel_id, "novel_id"),
            "asset_type": self._normalized_asset_type(asset_type),
            "asset_id": asset_id,
        }
        if exclude_confirmation_id is not None:
            query["exclude_confirmation_id"] = self._as_uuid(exclude_confirmation_id)
        records = await self._repo.list_by_asset_ref(db, **query)
        status = "needs_review" if reason == "candidate_promoted" else "stale_context"
        updates = []
        for record in records:
            reasons = list(record.stale_reasons or [])
            if reason not in reasons:
                reasons.append(reason)
            updates.append((record, reasons))
        return await self._repo.update_tracking_many(
            db,
            updates,
            result_status=status,
        )

    @staticmethod
    def _selected_refs(
        selected_asset_ids: dict[str, list[str]],
    ) -> list[tuple[str, str]]:
        refs: list[tuple[str, str]] = []
        for asset_type, asset_ids in selected_asset_ids.items():
            normalized_type = ContextConfirmationService._normalized_asset_type(
                asset_type
            )
            if not normalized_type:
                continue
            refs.extend(
                (normalized_type, normalized_id)
                for asset_id in asset_ids
                if (normalized_id := str(asset_id).strip())
            )
        return refs

    @staticmethod
    def _result_refs(result_refs: list[dict[str, str]]) -> list[tuple[str, str]]:
        refs: list[tuple[str, str]] = []
        for result_ref in result_refs:
            result_type = str(result_ref.get("type") or "").strip()
            result_id = str(result_ref.get("id") or "").strip()
            if not result_type or not result_id:
                raise ValueError("result refs require non-empty type and id")
            refs.append(
                (
                    ContextConfirmationService._normalized_asset_type(result_type),
                    result_id,
                )
            )
        return refs

    @staticmethod
    def _normalized_asset_type(asset_type: Any) -> str:
        normalized_type = str(asset_type or "").strip()
        return _ASSET_TYPE_ALIASES.get(normalized_type, normalized_type)

    @staticmethod
    def _validated_result_ref(result_type: Any, result_id: Any) -> dict[str, str]:
        normalized_type = str(result_type or "").strip()
        normalized_id = str(result_id or "").strip()
        if not normalized_type or not normalized_id:
            raise ValueError("result refs require non-empty type and id")
        return {"type": normalized_type, "id": normalized_id}

    @staticmethod
    def _compile_options_json(options: CompileOptions) -> dict[str, Any]:
        return {
            "novel_id": options.novel_id,
            "task": options.task,
            "scope": options.scope,
            "consumer_action": options.consumer_action,
            "retrieval_purpose": options.retrieval_purpose,
            "chapter_index": options.chapter_index,
            "requested_chapter_index": options.requested_chapter_index,
            "planning_window_end": options.planning_window_end,
            "visible_until_chapter": options.visible_until_chapter,
            "visible_until_scene_id": options.visible_until_scene_id,
            "visible_until_offset": options.visible_until_offset,
            "scene_id": options.scene_id,
            "arc_id": options.arc_id,
            "entity_ids": options.entity_ids,
            "character_ids": options.character_ids,
            "thread_ids": options.thread_ids,
            "location_ids": options.location_ids,
            "reveal_mode": options.reveal_mode,
            "viewpoint_character_id": options.viewpoint_character_id,
            "enable_geo_filter": options.enable_geo_filter,
            "budget_tokens": options.budget_tokens,
            "top_k": options.top_k,
            "context_mode": options.context_mode,
            "content_mode": options.content_mode,
            "include_pending_objects": options.include_pending_objects,
            "excluded_asset_ids": options.excluded_asset_ids,
            "pinned_refs": options.pinned_refs,
            "excluded_refs": options.excluded_refs,
            "user_note": options.user_note,
            "include_world_synopsis": options.include_world_synopsis,
            "selected_world_bible_draft_ids": options.selected_world_bible_draft_ids,
            "director_reference_ids": options.director_reference_ids,
            "world_synopsis_revision_id": options.world_synopsis_revision_id,
            "world_synopsis_source_hash": options.world_synopsis_source_hash,
            "world_synopsis_block_hash": options.world_synopsis_block_hash,
            "activation_profile_id": options.activation_profile_id,
            "activation_profile_version": options.activation_profile_version,
            "activation_profile_rule_hash": options.activation_profile_rule_hash,
            "activation_source_hashes": options.activation_source_hashes,
            "activation_included_target_hashes": (
                options.activation_included_target_hashes
            ),
            "compiled_context_fingerprint": options.compiled_context_fingerprint,
            "scene_memory_contract_version": (
                options.scene_memory_contract_version
                if options.scene_memory_contract_version is not None
                else _scene_memory_port().scene_memory_current_version()
            ),
            "capability": options.capability,
            "scope_complete": options.scope_complete,
            "reference_usages": options.reference_usages,
        }

    @staticmethod
    def _outline_analysis_fingerprint(compiled: CompiledContext) -> str:
        payload = [
            {
                "key": section.key,
                "content": section.content,
                "sources": list(section.sources or []),
                "excluded": section.excluded,
                "truncated_reason": section.truncated_reason,
            }
            for section in compiled.sections
        ]
        return stable_hash(payload, stringify_unknown=False)

    @staticmethod
    def _requires_character_profile(options: CompileOptions) -> bool:
        return bool(
            options.consumer_action == "writing.generate"
            and options.reveal_mode == "character"
        )

    @staticmethod
    def _require_character_profile(compiled: CompiledContext) -> None:
        if not any(section.key == "role_profile" for section in compiled.sections):
            raise ValueError(
                "POV character is unavailable; select an active character and recompile"
            )

    @staticmethod
    def _scene_state_fingerprint(compiled: CompiledContext) -> str:
        section = next(
            (item for item in compiled.sections if item.key == "scene_world_state"),
            None,
        )
        if section is None:
            raise ValueError(
                "Scene time state unavailable; review and confirm the latest context"
            )
        versions = section.retrieval_metadata.get("checkpoint_versions") or []
        by_dimension = {
            str(item.get("dimension")): item
            for item in versions
            if isinstance(item, dict) and item.get("dimension")
        }
        metadata = section.retrieval_metadata or {}
        _port = _scene_memory_port()
        contract_version = int(
            metadata.get("contract_version") or _port.scene_memory_v1_version()
        )
        required_dimensions = metadata.get("required_dimensions") or list(
            _port.scene_memory_dimensions(contract_version)
        )
        payload = [
            {
                "dimension": dimension,
                "id": str((by_dimension.get(dimension) or {}).get("id") or ""),
                "status": str(
                    (by_dimension.get(dimension) or {}).get("status") or "missing"
                ),
            }
            for dimension in required_dimensions
        ]
        return stable_hash(payload, stringify_unknown=False)

    @staticmethod
    def _require_outline_analysis_range(
        compiled: CompiledContext,
        options: CompileOptions,
    ) -> None:
        """Fail closed when a requested range could not be materialized.

        Confirmations created before range-aware P07 remain compatible when
        they have no chapter range. A partially specified or failed new range
        in an author view must not silently degrade into a project-only
        analysis. Reader/character views intentionally use their separate
        spoiler-safe compiler path and never materialize author planning cards.
        """
        if options.reveal_mode not in {"author_safe", "author_full"}:
            return
        start = options.chapter_index
        end = options.visible_until_chapter
        if start is None and end is None:
            return
        if start is None:
            raise ValueError("outline analysis chapter range is invalid")
        resolved_end = end if end is not None else start
        expected_id = f"{start}-{resolved_end}"
        range_section = next(
            (
                section
                for section in compiled.sections
                if section.key == "outline_analysis_range"
            ),
            None,
        )
        source_ids = {
            str(source.get("id") or "")
            for source in (range_section.sources if range_section else [])
        }
        if range_section is None or expected_id not in source_ids:
            raise ValueError(
                "outline analysis range context could not be loaded; "
                "review and confirm the reference context again"
            )

    @staticmethod
    def _to_contract(
        record,
        compiled: CompiledContext | None = None,
        review: dict | None = None,
    ) -> ContextConfirmationContract:
        compiled_at = record.compiled_at or datetime.now(UTC)
        created_at = record.created_at or compiled_at
        sections = []
        budget_events = []
        if compiled is not None:
            sections = [
                {
                    "key": section.key,
                    "tier": int(section.tier),
                    "content": section.content,
                    "token_count": section.token_count,
                    "truncated": section.key in compiled.truncated_keys,
                    "title": section.title,
                    "preview": section.preview or section.content[:160],
                    "status": section.status,
                    "activation_reason": section.activation_reason,
                    "sources": section.sources,
                    "can_exclude": section.can_exclude and int(section.tier) != 0,
                    "excluded": section.excluded,
                    "truncated_reason": section.truncated_reason,
                    "retrieval_metadata": section.retrieval_metadata,
                    "items": [item.model_dump(mode="json") for item in section.items],
                }
                for section in compiled.sections
            ]
            budget_events = [event.model_dump() for event in compiled.budget_events]
        review = review or (
            context_review_metadata(
                compiled,
                CompileOptions(**(record.compile_options or {})),
            )
            if compiled is not None
            else {
                "context_fingerprint": str(
                    (record.compile_options or {}).get("compiled_context_fingerprint")
                    or ""
                ),
                "selection_state": {},
                "blockers": [],
            }
        )
        return ContextConfirmationContract(
            id=str(record.id),
            novel_id=str(record.novel_id),
            action=record.action,
            task=record.task,
            scope=record.scope,
            context_mode=record.context_mode,
            include_pending_objects=record.include_pending_objects,
            excluded_asset_ids=record.excluded_asset_ids or {},
            selected_asset_ids=record.selected_asset_ids or {},
            user_note=record.user_note,
            compile_options=record.compile_options or {},
            warnings=record.warnings or [],
            sections=sections,
            budget_events=budget_events,
            result_refs=record.result_refs or [],
            result_status=record.result_status,
            stale_reasons=record.stale_reasons or [],
            compiled_at=compiled_at.isoformat(),
            created_at=created_at.isoformat(),
            context_fingerprint=review["context_fingerprint"],
            selection_state=review["selection_state"],
            blockers=review["blockers"],
        )

    @staticmethod
    def _as_uuid(value: str | uuid.UUID) -> uuid.UUID:
        if isinstance(value, uuid.UUID):
            return value
        return parse_uuid(str(value), "context_confirmation_id")


def resolve_retrieval_purpose(
    action: str,
    requested: str,
    *,
    reveal_mode: str,
) -> str:
    operation_purposes = {
        "story.character_card.generate": "story_character_card",
        "story.reaction.generate": "story_character_reaction",
        "story.script.generate": "story_scene_script",
    }
    operation_purpose = operation_purposes.get(action)
    if operation_purpose is not None:
        if requested not in {"generic_context", operation_purpose}:
            raise ValidationError(
                "retrieval purpose does not match the confirmed Story operation"
            )
        return operation_purpose
    if requested != "generic_context":
        return requested
    if reveal_mode == "character":
        return "character_context"
    if reveal_mode == "reader":
        return "reader_context"
    if action == "writing.generate":
        return "writing_generation"
    if action.startswith("writing.conflict_check"):
        return "conflict_review"
    if action.startswith("outline."):
        return "outline_generation"
    if action.startswith("story."):
        return "story_generation"
    if action.startswith("world.map_atlas"):
        return "map_atlas"
    if action.startswith("world.entity_fusion"):
        return "world_fusion"
    if action == "world.ask":
        return "ask_world"
    if action.startswith("world.generation"):
        return "world_generation"
    return "generic_context"
