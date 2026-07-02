"""LLM adapters used by deep import workflow phases."""

from __future__ import annotations

import json
import os
from importlib import import_module
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.profiles import ResolvedLLMProfile, resolve_llm_profile
from modules.imports.agent_step_harness import (
    AgentPermissionLevel,
    ManagedLLMStep,
    StepExecutionStatus,
    StepToolEnvelope,
)

DEEP_IMPORT_STRUCTURED_TIMEOUT_GRACE_SECONDS = 15
DEEP_IMPORT_STRUCTURED_MAX_FIX_ATTEMPTS = 2
PHASE1B_SMALL_SAMPLE_MAX_TOKENS = 6144
PHASE1B_SMALL_SAMPLE_TIMEOUT_SECONDS = 90
PHASE1B_COMPACT_TEXT_LIMIT = 180
PHASE0_SCENE_MAX_TOKENS = 4096
PHASE0_SCENE_TIMEOUT_SECONDS = 120
PHASE1A_SCENE_MAX_TOKENS = 1024
PHASE1A_STRUCTURED_MAX_FIX_ATTEMPTS = 0


def _workflow_constant(name: str, default: Any) -> Any:
    workflow_module = import_module("modules.imports.workflow")
    return getattr(workflow_module, name, default)


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _phase01_scene_max_tokens(default: int) -> int:
    return _positive_int_env("PHASE01_SCENE_MAX_TOKENS", default)


def _phase0_scene_max_tokens(default: int) -> int:
    default_budget = min(default, PHASE0_SCENE_MAX_TOKENS)
    return _positive_int_env("PHASE0_SCENE_MAX_TOKENS", default_budget)


def _phase0_scene_timeout_seconds(default: int | None) -> int | None:
    if default is not None:
        return default
    return _positive_int_env(
        "PHASE0_SCENE_TIMEOUT_SECONDS",
        _positive_int_env("LLM_TIMEOUT", PHASE0_SCENE_TIMEOUT_SECONDS),
    )


def _phase1a_scene_max_tokens(default: int) -> int:
    del default
    return _positive_int_env("PHASE1A_SCENE_MAX_TOKENS", PHASE1A_SCENE_MAX_TOKENS)


def _phase1a_structured_max_fix_attempts() -> int:
    return _positive_int_env(
        "PHASE1A_STRUCTURED_MAX_FIX_ATTEMPTS",
        PHASE1A_STRUCTURED_MAX_FIX_ATTEMPTS,
    )


def _deep_import_structured_max_fix_attempts() -> int:
    default = int(
        _workflow_constant(
            "DEEP_IMPORT_STRUCTURED_MAX_FIX_ATTEMPTS",
            DEEP_IMPORT_STRUCTURED_MAX_FIX_ATTEMPTS,
        )
    )
    return _positive_int_env("DEEP_IMPORT_STRUCTURED_MAX_FIX_ATTEMPTS", default)


async def _project_settings_for_novel(
    db: AsyncSession | None,
    novel_id: str,
) -> dict[str, Any] | None:
    if db is None:
        return None
    from unittest.mock import Mock

    if isinstance(db, Mock):
        return None
    from modules.project.facade import get_project_context

    context = await get_project_context(db, novel_id)
    if context is None:
        return None
    settings = getattr(context, "settings", None)
    return settings if isinstance(settings, dict) else None


def _llm_client_for_profile(project_settings: dict[str, Any] | None, **overrides: Any):
    from infrastructure.llm.client import LLMClient

    return LLMClient.from_project_settings(project_settings, **overrides)


def _profile_request_defaults(profile: ResolvedLLMProfile) -> dict[str, Any]:
    defaults = profile.request_defaults()
    return {
        "model": defaults["model"],
        "temperature": defaults.get("temperature"),
        "max_tokens": defaults["max_tokens"],
    }


class _Phase0SceneCandidateLLM:
    """LLM adapter that feeds Phase 0 batches with chapter text without writes."""

    def __init__(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        timeout_seconds: int | None = None,
        project_settings: dict[str, Any] | None = None,
    ) -> None:
        self.db = db
        self.novel_id = novel_id
        self.timeout_seconds = timeout_seconds
        self.project_settings = project_settings

    async def __call__(self, batch) -> Any:
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
        from modules.imports.llm_schemas import SceneCandidateOutput
        from modules.imports.scene_segmentation import SceneSegmentationService

        service = SceneSegmentationService()
        chapters = await service._load_chapters(
            self.db,
            self.novel_id,
            min(batch.chapter_indices),
            max(batch.chapter_indices),
        )
        wanted = set(batch.chapter_indices)
        chapters = [ch for ch in chapters if ch.get("chapter_index") in wanted]
        if not chapters:
            return SceneCandidateOutput(
                scenes=[],
                boundary_status="uncertain",
                missing_or_uncertain_items=["no chapter content found"],
            )

        project_settings = self.project_settings
        if project_settings is None and self.db is not None:
            project_settings = await _project_settings_for_novel(self.db, self.novel_id)
        profile = resolve_llm_profile(project_settings)
        request_defaults = _profile_request_defaults(profile)
        timeout_seconds = _phase0_scene_timeout_seconds(self.timeout_seconds)
        request = LLMCallRequest(
            model=request_defaults["model"],
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "你是长篇小说导入的 Phase 0 Scene 预取器。"
                        "目标是快速给 Phase 1a 提供轻量候选锚点，不做正式 Scene 切分。"
                        "只输出 JSON object，不要 Markdown。"
                        "必须包含 scenes 数组、boundary_status、confidence。"
                        "每章最多 1 个候选；5 章窗口最多 5 个候选。"
                        "每个 scene 只允许包含 title、goal、scene_chunks。"
                        "title 不超过 24 个中文字符，goal 不超过 60 个中文字符。"
                        "scene_chunks 每项只保留 chapter_index、start_paragraph、"
                        "end_paragraph；没有段落号时只填 chapter_index。"
                        "不要输出正文摘录、人物列表、长摘要、core_conflict、"
                        "emotional_beat、narrative_tag 或解释文字。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        "请为以下章节生成轻量候选锚点。按章节顺序输出，优先覆盖每章"
                        "最关键的叙事推进；不要展开成细粒度 Scene。\n\n"
                        f"{service._build_chapters_text(chapters)}"
                    ),
                ),
            ],
            temperature=request_defaults["temperature"] or 0.3,
            max_tokens=_phase0_scene_max_tokens(request_defaults["max_tokens"]),
            response_format={"type": "json_object"},
        )
        return await _call_structured(
            _llm_client_for_profile(
                project_settings,
                **({"timeout": timeout_seconds} if timeout_seconds else {}),
            ),
            request,
            SceneCandidateOutput,
            step_name="phase0_prefetch",
            transport_retries=False,
            timeout_seconds=timeout_seconds,
            fix_prompt=(
                "上一轮输出无法通过 SceneCandidateOutput 校验。请只输出一个 JSON "
                "object，必须包含 scenes 数组；每章最多 1 个 scene；每个 scene "
                "只保留 title、goal、scene_chunks，scene_chunks 内必须有 "
                "chapter_index。不要 Markdown，不要正文摘录或长摘要。"
            ),
        )


class _Phase1aSceneCandidateLLM:
    """LLM adapter for text-backed Phase 1a candidate reinforcement."""

    def __init__(self, project_settings: dict[str, Any] | None = None) -> None:
        self.project_settings = project_settings

    async def __call__(self, payload: dict[str, Any]) -> Any:
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
        from modules.imports.llm_schemas import SceneCandidateOutput

        profile = resolve_llm_profile(self.project_settings)
        request_defaults = _profile_request_defaults(profile)
        request = LLMCallRequest(
            model=request_defaults["model"],
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "你是长篇小说导入 Phase 1a 正文级 Scene 候选补强器，"
                        "不是最终 Scene 切分器，也不要写入正式 Scene。"
                        "你的输出只给 Phase 1b 融合使用。"
                        "每个覆盖章节最多输出 1 个中间候选 Scene；"
                        "每 5 章窗口最多 5 个。优先覆盖章节推进锚点，"
                        "不追求最终完整切分。"
                        "每个 scene 只允许包含 title、goal、scene_chunks、"
                        "boundary_reason。title 要短，goal 控制在约 30-60 "
                        "个中文字符。scene_chunks 每项只保留 chapter_index、"
                        "start_paragraph、end_paragraph。禁止正文摘录、长摘要、"
                        "人物列表、core_conflict、emotional_beat、narrative_tag "
                        "或最终 Scene 字段扩展。只输出 JSON object，必须包含 "
                        "scenes；JSON 必须紧凑，不要 pretty print、换行缩进、"
                        "解释文字或 Markdown。顶层不要输出 scenes 之外的字段。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        "请基于章节正文、Phase 0 强/弱候选和相邻批次摘要强化当前"
                        "批次候选。保持 source_round/source_batch_id/"
                        "source_chapter_indices 可追溯。不要复制正文，不要展开"
                        "成最终 Scene，只输出可供 Phase 1b 融合的中间候选。\n\n"
                        f"{json.dumps(payload, ensure_ascii=False)}"
                    ),
                ),
            ],
            temperature=request_defaults["temperature"] or 0.3,
            max_tokens=_phase1a_scene_max_tokens(request_defaults["max_tokens"]),
            response_format={"type": "json_object"},
        )
        return await _call_structured(
            _llm_client_for_profile(self.project_settings),
            request,
            SceneCandidateOutput,
            step_name="phase1a_reinforce",
            transport_retries=False,
            max_fix_attempts=_phase1a_structured_max_fix_attempts(),
            fix_prompt=(
                "上一轮输出无法通过 SceneCandidateOutput 校验。请只输出一个 JSON "
                "object，必须包含 scenes 数组；每个 scene 只保留 title、goal、"
                "scene_chunks、boundary_reason。不要 Markdown，不要正文摘录、"
                "长摘要、人物列表或最终 Scene 字段。保留 source_round、"
                "source_batch_id、source_chapter_indices 等可追溯信息。"
            ),
        )


class _SingleChapterSceneCandidateLLM:
    """Small-scope fallback when batch Phase 1a produces no usable candidates."""

    def __init__(self, project_settings: dict[str, Any] | None = None) -> None:
        self.project_settings = project_settings

    async def __call__(self, chapter: dict[str, Any]) -> Any:
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
        from modules.imports.llm_schemas import SceneSegmentationOutput
        from modules.imports.scene_segmentation import SceneSegmentationService

        service = SceneSegmentationService()
        profile = resolve_llm_profile(self.project_settings)
        request_defaults = _profile_request_defaults(profile)
        request = LLMCallRequest(
            model=request_defaults["model"],
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        service._load_prompt()
                        + "\n\n这是小样本恢复路径。只处理单章正文，输出 1-3 个"
                        "高价值 Scene。只输出 JSON，不要 Markdown。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        "请将以下单章正文切分为叙事 Scene。每个 Scene 必须"
                        "包含 title、goal、core_conflict、emotional_beat、"
                        "narrative_tag、scene_chunks。\n\n"
                        f"{service._build_chapters_text([chapter])}"
                    ),
                ),
            ],
            temperature=0.2,
            max_tokens=_phase01_scene_max_tokens(request_defaults["max_tokens"]),
            response_format={"type": "json_object"},
        )
        return await _call_structured(
            _llm_client_for_profile(self.project_settings),
            request,
            SceneSegmentationOutput,
            step_name="phase1a_single_chapter",
            transport_retries=False,
            fix_prompt=(
                "上一轮输出无法通过 SceneSegmentationOutput 校验。请只输出一个 JSON "
                "object，必须包含 scenes 数组；每个 scene 必须包含 title、goal、"
                "core_conflict、emotional_beat、narrative_tag、scene_chunks。"
            ),
        )


class _Phase1bSceneFusionLLM:
    """LLM adapter for Phase 1b reducer windows."""

    def __init__(self, project_settings: dict[str, Any] | None = None) -> None:
        self.project_settings = project_settings

    async def __call__(self, payload: dict[str, Any]) -> Any:
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
        from modules.imports.scene_fusion import Phase1bReducerOutput

        profile = resolve_llm_profile(self.project_settings)
        compact_payload = _compact_phase1b_payload(payload)
        small_sample = _is_small_phase1b_payload(compact_payload)
        max_tokens = (
            int(
                _workflow_constant(
                    "PHASE1B_SMALL_SAMPLE_MAX_TOKENS",
                    PHASE1B_SMALL_SAMPLE_MAX_TOKENS,
                )
            )
            if small_sample
            else _phase01_scene_max_tokens(max(int(profile.max_tokens), 8192))
        )
        timeout_seconds = (
            int(
                _workflow_constant(
                    "PHASE1B_SMALL_SAMPLE_TIMEOUT_SECONDS",
                    PHASE1B_SMALL_SAMPLE_TIMEOUT_SECONDS,
                )
            )
            if small_sample
            else max(int(profile.timeout), 45)
        )
        scene_guidance = (
            "1-7章样本目标输出9个Scene，必须覆盖1-7章；只合并真正重复的候选。"
            "如果候选覆盖多个章节，应按章节/事件拆分为多个Scene，而不是吞并。"
            if small_sample
            else "按窗口推荐数量输出Scene，必须覆盖窗口核心章节。"
        )
        scene_contract = (
            "每个Scene必须包含完整内容字段：title、goal、core_conflict、"
            "emotional_beat、narrative_tag、scene_chunks，以及追溯字段："
            "source_candidate_ids、source_rounds、source_chapter_indices、operation、"
            "confidence、fallback_required、boundary_status、boundary_reason、"
            "needs_review、review_reason。scene_chunks 内必须有 chapter_index。"
            "所有输出 Scene 的 source_chapter_indices 并集必须覆盖输入的"
            " source_chapter_indices。除非候选确实不可用，不要输出"
            " fallback_required=true。"
        )
        request = LLMCallRequest(
            model=profile.model,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "你是长篇小说导入的 Scene reducer。"
                        "只根据 Phase 1a 候选融合、去重和排序，不读取正文。"
                        f"{scene_guidance}"
                        f"{scene_contract}"
                        "只输出 JSON，必须包含 scenes，可包含 discarded_candidates。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        "请把窗口内候选融合为可提交的正式 Scene 候选。\n"
                        "硬性要求：\n"
                        "1. 输出 scenes 数量应接近 recommended_scene_count；"
                        "小样本 1-7 章不足 9 个时优先拆分跨章候选。\n"
                        "2. 输出 Scene 必须覆盖所有 source_chapter_indices；"
                        "不能只覆盖第一个章节。\n"
                        "3. title/goal/core_conflict/emotional_beat 应来自候选"
                        "内容的综合，不允许留空。\n"
                        "4. scene_chunks 必须写出对应 chapter_index。\n"
                        "5. 只把真正重复或被融合的候选写入 discarded_candidates。\n"
                        "输出示例形状：{\"scenes\":[{\"title\":\"...\","
                        "\"goal\":\"...\",\"core_conflict\":\"...\","
                        "\"emotional_beat\":\"...\",\"narrative_tag\":\"imported\","
                        "\"scene_chunks\":[{\"chapter_index\":1}],"
                        "\"source_candidate_ids\":[\"...\"],"
                        "\"source_rounds\":[\"A\"],"
                        "\"source_chapter_indices\":[1],\"operation\":\"kept\","
                        "\"confidence\":0.8,\"fallback_required\":false,"
                        "\"boundary_status\":\"complete\",\"boundary_reason\":\"...\","
                        "\"needs_review\":true,\"review_reason\":\"...\"}]}\n\n"
                        f"{json.dumps(compact_payload, ensure_ascii=False)}"
                    ),
                ),
            ],
            temperature=0.2,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return await _call_structured(
            _llm_client_for_profile(self.project_settings),
            request,
            Phase1bReducerOutput,
            step_name="phase1b_fusion",
            transport_retries=False,
            timeout_seconds=timeout_seconds,
            fix_prompt=(
                "上一轮输出无法通过 Phase1bReducerOutput 校验。请只输出一个 JSON "
                "object，必须包含 scenes 数组。每个 scene 必须包含 "
                "source_candidate_ids、source_rounds、source_chapter_indices、"
                "operation、confidence、fallback_required、boundary_status、"
                "boundary_reason、needs_review、review_reason。不要 Markdown。"
            ),
        )


def _is_small_phase1b_payload(payload: dict[str, Any]) -> bool:
    chapters = payload.get("source_chapter_indices") or []
    return 0 < len(set(chapters)) <= 7


def _compact_phase1b_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep Phase 1b reducer input bounded and正文-free."""

    return {
        "phase": payload.get("phase"),
        "window": payload.get("window"),
        "source_candidate_ids": _compact_list(payload.get("source_candidate_ids")),
        "source_rounds": _compact_list(payload.get("source_rounds")),
        "source_chapter_indices": _compact_chapters(
            payload.get("source_chapter_indices")
        ),
        "recommended_scene_count": payload.get("recommended_scene_count"),
        "scene_count_guidance": _compact_text(payload.get("scene_count_guidance")),
        "candidates": [
            _compact_phase1b_candidate(candidate)
            for candidate in payload.get("candidates", [])
            if isinstance(candidate, dict)
        ],
        "merge_hints": _compact_list(payload.get("merge_hints"), limit=12),
        "split_hints": _compact_list(payload.get("split_hints"), limit=12),
        "output_requirements": {
            "required_scene_fields": [
                "title",
                "goal",
                "core_conflict",
                "emotional_beat",
                "narrative_tag",
                "scene_chunks",
                "source_candidate_ids",
                "source_rounds",
                "source_chapter_indices",
                "operation",
                "confidence",
                "fallback_required",
                "boundary_status",
                "boundary_reason",
                "needs_review",
                "review_reason",
            ],
            "operation_values": ["kept", "merged", "split", "reordered", "rewritten"],
            "discard_reason_values": [
                "merged",
                "split",
                "duplicate_candidate",
                "low_confidence_unusable",
                "outside_scope",
            ],
        },
    }


def _compact_phase1b_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": candidate.get("candidate_id"),
        "source_round": candidate.get("source_round"),
        "source_batch_id": candidate.get("source_batch_id"),
        "source_batch_index": candidate.get("source_batch_index"),
        "source_chapter_indices": _compact_chapters(
            candidate.get("source_chapter_indices")
        ),
        "quality": candidate.get("quality"),
        "confidence": candidate.get("confidence"),
        "boundary_status": candidate.get("boundary_status"),
        "boundary_reason": _compact_text(candidate.get("boundary_reason")),
        "scenes": [
            _compact_phase1b_scene(scene)
            for scene in candidate.get("scenes", [])
            if isinstance(scene, dict)
        ],
        "evidence_anchors": _compact_list(candidate.get("evidence_anchors"), limit=4),
        "merge_hints": _compact_list(candidate.get("merge_hints"), limit=4),
        "split_hints": _compact_list(candidate.get("split_hints"), limit=4),
        "missing_or_uncertain_items": _compact_list(
            candidate.get("missing_or_uncertain_items"),
            limit=4,
        ),
    }


def _compact_phase1b_scene(scene: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": _compact_text(scene.get("title"), limit=80),
        "goal": _compact_text(scene.get("goal")),
        "core_conflict": _compact_text(scene.get("core_conflict")),
        "emotional_beat": _compact_text(scene.get("emotional_beat")),
        "narrative_tag": _compact_text(scene.get("narrative_tag"), limit=48),
        "scene_chunks": [
            _compact_scene_chunk(chunk)
            for chunk in scene.get("scene_chunks", [])
            if isinstance(chunk, dict)
        ],
    }


def _compact_scene_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    compact = {"chapter_index": chunk.get("chapter_index")}
    if chunk.get("start_paragraph") is not None:
        compact["start_paragraph"] = chunk.get("start_paragraph")
    if chunk.get("end_paragraph") is not None:
        compact["end_paragraph"] = chunk.get("end_paragraph")
    return compact


def _compact_list(value: Any, *, limit: int | None = None) -> list[Any]:
    if not isinstance(value, list):
        return []
    items = value[:limit] if limit is not None else value
    return [
        _compact_text(item) if isinstance(item, str) else item
        for item in items
        if item is not None and item != ""
    ]


def _compact_chapters(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    chapters: list[int] = []
    for item in value:
        try:
            chapter = int(item)
        except (TypeError, ValueError):
            continue
        if chapter > 0:
            chapters.append(chapter)
    return sorted(set(chapters))


def _compact_text(value: Any, *, limit: int | None = None) -> str:
    if limit is None:
        limit = int(
            _workflow_constant(
                "PHASE1B_COMPACT_TEXT_LIMIT",
                PHASE1B_COMPACT_TEXT_LIMIT,
            )
        )
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


async def _run_deep_import_structured_call(
    client,
    request,
    schema,
    *,
    step_name: str = "managed_llm_step",
    transport_retries: bool,
    fix_prompt: str,
    timeout_seconds: int | None = None,
    max_fix_attempts: int | None = None,
):
    from core.config import get_settings

    settings = get_settings()
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else int(settings.llm_timeout)
        + int(
            _workflow_constant(
                "DEEP_IMPORT_STRUCTURED_TIMEOUT_GRACE_SECONDS",
                DEEP_IMPORT_STRUCTURED_TIMEOUT_GRACE_SECONDS,
            )
        )
    )
    step = ManagedLLMStep(
        StepToolEnvelope(
            name=step_name,
            output_schema=schema,
            permission_level=AgentPermissionLevel.draft,
            read_only=False,
            concurrent_safe=True,
            timeout=timeout,
        )
    )
    result = await step.run(
        lambda: client.generate_structured(
            request,
            schema,
            max_fix_attempts=(
                max_fix_attempts
                if max_fix_attempts is not None
                else _deep_import_structured_max_fix_attempts()
            ),
            transport_retries=transport_retries,
            fix_prompt=fix_prompt,
        )
    )
    if result.status != StepExecutionStatus.succeeded:
        if result.exception is not None:
            raise result.exception
        raise RuntimeError(result.error_kind or "managed_llm_step_failed")
    return result.output


async def _call_structured(*args, **kwargs):
    workflow_module = import_module("modules.imports.workflow")
    runner = getattr(
        workflow_module,
        "_run_deep_import_structured_call",
        _run_deep_import_structured_call,
    )
    if runner is _run_deep_import_structured_call:
        return await _run_deep_import_structured_call(*args, **kwargs)
    return await runner(*args, **kwargs)
