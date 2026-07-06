"""LLM adapters used by deep import workflow phases."""

from __future__ import annotations

import json
from importlib import import_module
from typing import Any, get_origin

from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.profiles import ResolvedLLMProfile, resolve_llm_profile
from modules.imports.agent_step_harness import (
    AgentPermissionLevel,
    ManagedLLMStep,
    StepExecutionStatus,
    StepToolEnvelope,
)
from modules.imports.env_helpers import positive_int_env

DEEP_IMPORT_STRUCTURED_TIMEOUT_GRACE_SECONDS = 15
DEEP_IMPORT_STRUCTURED_MAX_FIX_ATTEMPTS = 2
PHASE1B_SMALL_SAMPLE_MAX_TOKENS = 6144
PHASE1B_SMALL_SAMPLE_TIMEOUT_SECONDS = 90
PHASE1B_REDUCER_MAX_TOKENS = 128
PHASE1B_REDUCER_TIMEOUT_SECONDS = 45
PHASE1B_COMPACT_TEXT_LIMIT = 180
PHASE0_SCENE_MAX_TOKENS = 8192
PHASE0_SCENE_TIMEOUT_SECONDS = 120
PHASE1A_SCENE_MAX_TOKENS = 8192
PHASE1A_STRUCTURED_MAX_FIX_ATTEMPTS = 1
PHASE1A_SCENE_SLICING_TIMEOUT_SECONDS = 900
PHASE1B_ENRICH_MAX_TOKENS = 4096
PHASE1B_ENRICH_TIMEOUT_SECONDS = 300
PHASE2_WORLD_TIMEOUT_SECONDS = 900
PHASE2_WORLD_MIN_MAX_TOKENS = 24_576


def _workflow_constant(name: str, default: Any) -> Any:
    try:
        workflow_module = import_module("modules.imports.workflow")
    except ImportError as exc:
        if "partially initialized module" not in str(exc):
            raise
        return default
    return getattr(workflow_module, name, default)


def _phase01_scene_max_tokens(default: int) -> int:
    return positive_int_env("PHASE01_SCENE_MAX_TOKENS", default)


def _phase0_scene_max_tokens(default: int) -> int:
    del default
    return positive_int_env("PHASE0_SCENE_MAX_TOKENS", PHASE0_SCENE_MAX_TOKENS)


def _phase0_scene_timeout_seconds(default: int | None) -> int | None:
    if default is not None:
        return default
    return positive_int_env(
        "PHASE0_SCENE_TIMEOUT_SECONDS",
        positive_int_env("LLM_TIMEOUT", PHASE0_SCENE_TIMEOUT_SECONDS),
    )


def _phase1a_scene_max_tokens(default: int) -> int:
    del default
    return positive_int_env("PHASE1A_SCENE_MAX_TOKENS", PHASE1A_SCENE_MAX_TOKENS)


def _phase1a_structured_max_fix_attempts() -> int:
    return positive_int_env(
        "PHASE1A_STRUCTURED_MAX_FIX_ATTEMPTS",
        PHASE1A_STRUCTURED_MAX_FIX_ATTEMPTS,
    )


def _phase1a_scene_slicing_timeout_seconds() -> int:
    return positive_int_env(
        "PHASE1A_SCENE_SLICING_TIMEOUT_SECONDS",
        PHASE1A_SCENE_SLICING_TIMEOUT_SECONDS,
    )


def _deep_import_structured_max_fix_attempts() -> int:
    default = int(
        _workflow_constant(
            "DEEP_IMPORT_STRUCTURED_MAX_FIX_ATTEMPTS",
            DEEP_IMPORT_STRUCTURED_MAX_FIX_ATTEMPTS,
        )
    )
    return positive_int_env("DEEP_IMPORT_STRUCTURED_MAX_FIX_ATTEMPTS", default)


def _structured_list_fields(schema: type[BaseModel]) -> set[str]:
    fields: set[str] = set()
    for name, field in schema.model_fields.items():
        if get_origin(field.annotation) is list:
            fields.add(name)
    return fields


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


def _phase_model(profile: ResolvedLLMProfile, *, high_quality: bool = False) -> str:
    return "deepseek-v4-pro" if high_quality else profile.model


def _deepseek_request_extra(
    profile: ResolvedLLMProfile,
    *,
    model: str,
) -> dict[str, Any]:
    extra = dict(profile.extra or {})
    if profile.provider_id == "deepseek" or model.startswith("deepseek-v4"):
        extra.setdefault("thinking", {"type": "enabled"})
        extra.setdefault("reasoning_effort", "max")
    return extra


def _chapters_text(chapters: list[dict[str, Any]]) -> str:
    from modules.imports.scene_segmentation import SceneSegmentationService

    return SceneSegmentationService._build_chapters_text(chapters)


def _phase2_overlap_text(window: dict[str, Any]) -> str:
    owned_end = int(window.get("owned_end") or 0)
    covered_end = int(window.get("covered_end") or 0)
    if owned_end and covered_end and owned_end < covered_end:
        return f"第{owned_end + 1}章-第{covered_end}章"
    return "无"


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
                        "参考跨章 Scene 边界识别：如果相邻章节仍在同一目标、"
                        "同一冲突或同一行动链中延续，应输出一个 Scene，并在 "
                        "scene_chunks 中显式列出连续多个 chapter_index；"
                        "章节号变化本身不是拆分理由。若目标/冲突/行动链已切换，"
                        "再拆成独立 Scene。不要把同一 batch 内互不相干的事件"
                        "强行标成跨章。"
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
                        "成最终 Scene，只输出可供 Phase 1b 融合的中间候选。"
                        "跨章延续必须通过一个 scene 的多个 scene_chunks 表达；"
                        "不确定边界时在 boundary_reason 中说明。\n\n"
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
                "长摘要、人物列表或最终 Scene 字段。若相邻章节仍属同一目标/"
                "冲突/行动链，用一个 scene 的多个 scene_chunks 显式保留跨章；"
                "保留 source_round、source_batch_id、source_chapter_indices "
                "等可追溯信息。"
            ),
        )


class _Phase1aSceneSlicingLLM:
    """LLM adapter for final Phase 1a Scene slicing."""

    def __init__(
        self,
        project_settings: dict[str, Any] | None = None,
        *,
        high_quality: bool = False,
    ) -> None:
        self.project_settings = project_settings
        self.high_quality = high_quality

    async def __call__(self, payload: dict[str, Any]) -> Any:
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
        from modules.imports.llm_schemas import SceneSlicingOutput

        profile = resolve_llm_profile(self.project_settings)
        model = _phase_model(profile, high_quality=self.high_quality)
        request_defaults = _profile_request_defaults(profile)
        chapters = [
            chapter
            for chapter in payload.get("chapters", [])
            if isinstance(chapter, dict)
        ]
        window = payload.get("window") or {}
        max_tokens = int(payload.get("max_tokens") or request_defaults["max_tokens"])
        covered_start = int(window.get("covered_start") or 0)
        covered_end = int(window.get("covered_end") or 0)
        owned_start = int(window.get("owned_start") or covered_start or 0)
        owned_end = int(window.get("owned_end") or covered_end or 0)
        right_overlap = (
            f"第{owned_end + 1}章-第{covered_end}章"
            if covered_end and owned_end and owned_end < covered_end
            else "无"
        )
        request = LLMCallRequest(
            model=model,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "你是小说叙事结构分析助手。只输出 JSON object，不要 Markdown。"
                        "任务是把连续章节正文切分为有独立叙事意义的 Scene。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        f"{_chapters_text(chapters)}\n\n"
                        "请基于上面正文切分有独立叙事意义的 Scene。"
                        "只输出 JSON object，不要 Markdown，不要解释。\n\n"
                        "【输入范围】\n"
                        f"- input_range: 第{covered_start}章-第{covered_end}章\n"
                        f"- owned_range: 第{owned_start}章-第{owned_end}章\n"
                        f"- right_overlap_range: {right_overlap}\n\n"
                        "【Scene 定义】\n"
                        "- Scene 是最小叙事单元，不是物理章。\n"
                        "- 一个 Scene 可以跨章。\n"
                        "- Scene 应有明确的叙事目标、阻碍或张力。\n"
                        "- 不要按章节机械切分，不要输出章节大纲。\n\n"
                        "【归属规则】\n"
                        "- 只输出 start_chapter 落在 owned_range 内的 Scene。\n"
                        "- 如果 Scene 从 owned_range 延续到 right_overlap_range，"
                        "end_chapter 可以落在 input_range 内。\n"
                        "- 不要输出完全发生在 right_overlap_range 内的新 Scene。\n\n"
                        "【输出格式】\n"
                        "{\n"
                        "  \"scenes\": [\n"
                        "    {\n"
                        "      \"title\": \"简短标题\",\n"
                        "      \"goal\": \"角色或叙事目标\",\n"
                        "      \"core_conflict\": \"阻碍、风险或张力\",\n"
                        "      \"start_chapter\": 1,\n"
                        "      \"end_chapter\": 1,\n"
                        "      \"boundary_status\": \"complete|continues|uncertain\"\n"
                        "    }\n"
                        "  ]\n"
                        "}"
                    ),
                ),
            ],
            temperature=0.2,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            extra=_deepseek_request_extra(profile, model=model),
        )
        return await _call_structured(
            _llm_client_for_profile(self.project_settings),
            request,
            SceneSlicingOutput,
            step_name="phase1a_scene_slicing",
            transport_retries=False,
            timeout_seconds=_phase1a_scene_slicing_timeout_seconds(),
            max_fix_attempts=1,
            fix_prompt=(
                "上一轮输出无法通过 SceneSlicingOutput 校验。只输出 JSON object："
                "{\"scenes\":[{\"title\":\"...\",\"goal\":\"...\","
                "\"core_conflict\":\"...\",\"start_chapter\":1,"
                "\"end_chapter\":1,\"boundary_status\":\"complete\"}]}。"
                "不要 Markdown，不要解释，不要输出其他字段。"
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
                        "must_happen、must_not_happen、narrative_tag、"
                        "scene_chunks。\n\n"
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
                "core_conflict、emotional_beat、must_happen、must_not_happen、"
                "narrative_tag、scene_chunks。"
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
        if not small_sample:
            return await self._call_compact_decision_reducer(
                compact_payload,
                profile,
            )
        max_tokens = (
            int(
                _workflow_constant(
                    "PHASE1B_SMALL_SAMPLE_MAX_TOKENS",
                    PHASE1B_SMALL_SAMPLE_MAX_TOKENS,
                )
            )
            if small_sample
            else positive_int_env(
                "PHASE1B_REDUCER_MAX_TOKENS",
                PHASE1B_REDUCER_MAX_TOKENS,
            )
        )
        timeout_seconds = (
            int(
                _workflow_constant(
                    "PHASE1B_SMALL_SAMPLE_TIMEOUT_SECONDS",
                    PHASE1B_SMALL_SAMPLE_TIMEOUT_SECONDS,
                )
            )
            if small_sample
            else positive_int_env(
                "PHASE1B_REDUCER_TIMEOUT_SECONDS",
                PHASE1B_REDUCER_TIMEOUT_SECONDS,
            )
        )
        scene_guidance = (
            "1-7章样本目标输出9个Scene，必须覆盖1-7章；只合并真正重复的候选。"
            "如果候选覆盖多个章节，应按章节/事件拆分为多个Scene，而不是吞并。"
            if small_sample
            else "按窗口推荐数量输出Scene，必须覆盖窗口核心章节。"
        )
        scene_contract = (
            "每个Scene只输出短字段：title、goal、must_happen、"
            "must_not_happen、scene_chunks，以及追溯字段："
            "source_candidate_ids、source_rounds、source_chapter_indices、operation、"
            "confidence、fallback_required、boundary_status、boundary_reason、"
            "needs_review、review_reason。scene_chunks 内必须有 chapter_index。"
            "如果候选已有 must_happen/must_not_happen，需短句保留；缺失时可"
            "根据 goal/core_conflict 生成一句源文本约束。"
            "所有输出 Scene 的 source_chapter_indices 并集必须覆盖输入的"
            " source_chapter_indices。除非候选确实不可用，不要输出"
            " fallback_required=true。优先沿用 Phase1a 候选的 title/goal/chunks，"
            "不要重写成长摘要，不要补 core_conflict、emotional_beat、narrative_tag。"
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
                        "小样本 1-7 章不足 9 个时优先拆分吞并多事件的候选，"
                        "但不要拆散同一目标/冲突/行动链延续的跨章 Scene。\n"
                        "2. 输出 Scene 必须覆盖所有 source_chapter_indices；"
                        "不能只覆盖第一个章节。\n"
                        "3. title/goal 应直接沿用或极短改写候选内容，不允许留空。\n"
                        "4. scene_chunks 必须写出对应 chapter_index。\n"
                        "5. 只把真正重复或被融合的候选写入 discarded_candidates。\n"
                        "输出示例形状：{\"scenes\":[{\"title\":\"...\","
                        "\"goal\":\"...\","
                        "\"must_happen\":\"...\",\"must_not_happen\":\"...\","
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
                "boundary_reason、needs_review、review_reason。不要 Markdown，"
                "不要输出 core_conflict、emotional_beat、narrative_tag。"
            ),
        )

    async def _call_compact_decision_reducer(
        self,
        compact_payload: dict[str, Any],
        profile: ResolvedLLMProfile,
    ) -> Any:
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

        core_range = (compact_payload.get("window") or {}).get("core_range") or []
        candidates = [
            candidate
            for candidate in compact_payload.get("candidates", [])
            if isinstance(candidate, dict) and candidate.get("candidate_id")
        ]
        candidate_summary = [
            {
                "id": str(candidate.get("candidate_id")),
                "round": candidate.get("source_round"),
                "chapters": _compact_chapters(candidate.get("source_chapter_indices")),
            }
            for candidate in candidates
        ]
        request = LLMCallRequest(
            model=profile.model,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "你是 Phase 1b 的最小决策器，只判断是否沿用 A 轮候选。"
                        "只输出 JSON object：{\"use_primary_round\":true} 或 "
                        "{\"use_primary_round\":false}。不要输出候选列表、scenes、"
                        "摘要、正文、理由或解释。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        "如果 source_round=A 的候选已经覆盖 core_range 内所有章节，"
                        "回答 {\"use_primary_round\":true}；否则回答 "
                        "{\"use_primary_round\":false}。\n"
                        f"core_range={core_range}\n"
                        f"candidates={json.dumps(candidate_summary, ensure_ascii=False)}"
                    ),
                ),
            ],
            temperature=0.0,
            max_tokens=positive_int_env(
                "PHASE1B_REDUCER_MAX_TOKENS",
                PHASE1B_REDUCER_MAX_TOKENS,
            ),
            response_format={"type": "json_object"},
        )
        try:
            raw_decision = await _call_structured(
                _llm_client_for_profile(self.project_settings),
                request,
                _Phase1bDecisionOutput,
                step_name="phase1b_fusion",
                transport_retries=False,
                timeout_seconds=positive_int_env(
                    "PHASE1B_REDUCER_TIMEOUT_SECONDS",
                    PHASE1B_REDUCER_TIMEOUT_SECONDS,
                ),
                max_fix_attempts=1,
                fix_prompt=(
                    "上一轮输出无法通过 Phase1b decision schema。只输出 JSON object："
                    "{\"use_primary_round\":true} 或 {\"use_primary_round\":false}。"
                    "不要输出候选列表、scenes、Markdown 或解释。"
                ),
            )
        except Exception:
            raw_decision = _Phase1bDecisionOutput(use_primary_round=True)
        if not isinstance(raw_decision, _Phase1bDecisionOutput):
            raw_decision = _Phase1bDecisionOutput.model_validate(raw_decision)
        return _materialize_phase1b_decision_output(compact_payload, raw_decision)


class _Phase1bSceneEnrichmentLLM:
    """LLM adapter for per-Scene Phase 1b enrichment."""

    def __init__(
        self,
        project_settings: dict[str, Any] | None = None,
        *,
        high_quality: bool = False,
    ) -> None:
        self.project_settings = project_settings
        self.high_quality = high_quality

    async def __call__(self, payload: dict[str, Any]) -> Any:
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
        from modules.imports.llm_schemas import SceneEnrichmentOutput

        profile = resolve_llm_profile(self.project_settings)
        model = _phase_model(profile, high_quality=self.high_quality)
        chapters = [
            chapter
            for chapter in payload.get("chapters", [])
            if isinstance(chapter, dict)
        ]
        locked_scene = payload.get("locked_scene") or {}
        max_tokens = int(payload.get("max_tokens") or PHASE1B_ENRICH_MAX_TOKENS)
        request = LLMCallRequest(
            model=model,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "你是小说 Scene enrichment 助手。只补充叙事字段，"
                        "不得重切 Scene，不得改 title/goal/core_conflict/start/end。"
                        "只输出 JSON object，不要 Markdown。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        f"{_chapters_text(chapters)}\n\n"
                        "请基于上面正文为锁定 Scene 补充叙事字段。"
                        "不要重新切分，不要定位正文，不要输出 scene_chunks。\n\n"
                        "【锁定 Scene】\n"
                        f"{json.dumps(locked_scene, ensure_ascii=False)}\n\n"
                        "【输出字段】\n"
                        "只输出 JSON object，且只包含以下字段："
                        "emotional_beat、must_happen、must_not_happen、"
                        "narrative_tag、confidence、needs_review、review_reason。\n\n"
                        "【要求】\n"
                        "- 字段必须基于正文有实际内容，"
                        "不要机械复述 goal/core_conflict。\n"
                        "- 即使你认为锁定字段不准，也不要修改或复写 "
                        "title/goal/core_conflict/start_chapter/end_chapter。\n"
                        "- 如果信息不足或判断不稳，needs_review=true 并说明 "
                        "review_reason。"
                    ),
                ),
            ],
            temperature=0.2,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            extra=_deepseek_request_extra(profile, model=model),
        )
        return await _call_structured(
            _llm_client_for_profile(self.project_settings),
            request,
            SceneEnrichmentOutput,
            step_name="phase1b_enrichment",
            transport_retries=False,
            timeout_seconds=positive_int_env(
                "PHASE1B_ENRICH_TIMEOUT_SECONDS",
                PHASE1B_ENRICH_TIMEOUT_SECONDS,
            ),
            max_fix_attempts=1,
            fix_prompt=(
                "上一轮输出无法通过 SceneEnrichmentOutput 校验。只输出 JSON object，"
                "只能包含 emotional_beat、must_happen、must_not_happen、"
                "narrative_tag、confidence、needs_review、review_reason。"
                "不要输出 title、goal、core_conflict、start_chapter、end_chapter。"
            ),
        )


class _Phase2WorldExtractionLLM:
    """LLM adapter for simplified window-level Phase 2 world extraction."""

    def __init__(
        self,
        project_settings: dict[str, Any] | None = None,
        *,
        high_quality: bool = False,
    ) -> None:
        self.project_settings = project_settings
        self.high_quality = high_quality

    async def __call__(self, payload: dict[str, Any]) -> Any:
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
        from modules.imports.llm_schemas import Phase2WorldExtractionOutput

        profile = resolve_llm_profile(self.project_settings)
        model = _phase_model(profile, high_quality=self.high_quality)
        chapters = [
            chapter
            for chapter in payload.get("chapters", [])
            if isinstance(chapter, dict)
        ]
        scenes = [
            scene for scene in payload.get("scenes", []) if isinstance(scene, dict)
        ]
        window = payload.get("window") or {}
        max_tokens = int(payload.get("max_tokens") or PHASE2_WORLD_MIN_MAX_TOKENS)
        owned_scene_ids = [
            str(scene_id)
            for scene_id in payload.get("owned_scene_ids", [])
            if str(scene_id).strip()
        ]
        all_scene_ids = [
            str(scene_id)
            for scene_id in payload.get("all_scene_ids", [])
            if str(scene_id).strip()
        ]
        input_block = (
            "【章节正文】\n"
            f"{_chapters_text(chapters)}\n\n"
            "【Scene卡片 JSON】\n"
            f"{json.dumps(scenes, ensure_ascii=False)}"
        )
        request = LLMCallRequest(
            model=model,
            messages=[
                LLMMessage(
                    role="system",
                    content="你只输出可解析 JSON。不要 Markdown，不要解释。",
                ),
                LLMMessage(
                    role="user",
                    content=(
                        f"{input_block}\n\n"
                        "你是小说世界资产抽取助手。上方是唯一证据来源。\n"
                        f"当前输入范围：第{window.get('covered_start')}章到"
                        f"第{window.get('covered_end')}章。\n"
                        f"owned range：第{window.get('owned_start')}章到"
                        f"第{window.get('owned_end')}章。\n"
                        f"右侧 overlap：{_phase2_overlap_text(window)}。\n"
                        "输入模式：scenes_plus_text。\n\n"
                        "抽取原则：\n"
                        "- 宁可少抽，不要污染资产库。\n"
                        "- 只抽长期资产：主要人物、重复出现或明显重要的人物、"
                        "组织、地点、关键物品、超凡概念、秘密、制度、能力。\n"
                        "- 关系只抽对后续剧情理解有价值的稳定关系或关键互动。\n"
                        "- 状态变化只抽会影响后续上下文的变化，例如身份确认、"
                        "加入组织、获得物品、知识升级、秘密暴露、关系改变。\n"
                        "- 每条 objects / relations / deltas 都必须有 "
                        "supporting_scene_ids。\n"
                        "- supporting_scene_ids 只能来自全部可用 Scene IDs。\n"
                        "- 如果依据不足，放入 uncertain_items，不要硬编。\n"
                        "- 不要输出旁枝路人、普通菜品、普通马车、"
                        "一次性背景名词。\n"
                        "- 不要用输入范围之外的后文知识补全当前内容。\n"
                        "- 不要输出完全只由 overlap Scene 支撑的新条目。\n\n"
                        f"owned Scene IDs：{', '.join(owned_scene_ids)}\n"
                        f"全部可用 Scene IDs：{', '.join(all_scene_ids)}\n\n"
                        "只输出 JSON object：\n"
                        "{\n"
                        "  \"objects\": [\n"
                        "    {\n"
                        "      \"name\": \"名称\",\n"
                        "      \"entity_type\": \"character|organization|location|"
                        "item|concept|ability|secret|other\",\n"
                        "      \"summary\": \"当前输入中可证实的稳定意义\",\n"
                        "      \"aliases\": [],\n"
                        "      \"suggested_action\": \"create|merge|update|ignore\",\n"
                        "      \"suggested_existing_name\": \"\",\n"
                        "      \"importance\": \"high|medium|low\",\n"
                        "      \"confidence\": 0.0,\n"
                        "      \"needs_review\": false,\n"
                        "      \"review_reason\": \"\",\n"
                        "      \"supporting_scene_ids\": []\n"
                        "    }\n"
                        "  ],\n"
                        "  \"relations\": [\n"
                        "    {\n"
                        "      \"source_name\": \"源对象\",\n"
                        "      \"target_name\": \"目标对象\",\n"
                        "      \"relation_type\": \"关系类型\",\n"
                        "      \"description\": \"关系说明\",\n"
                        "      \"confidence\": 0.0,\n"
                        "      \"needs_review\": false,\n"
                        "      \"review_reason\": \"\",\n"
                        "      \"supporting_scene_ids\": []\n"
                        "    }\n"
                        "  ],\n"
                        "  \"deltas\": [\n"
                        "    {\n"
                        "      \"subject_name\": \"对象\",\n"
                        "      \"category\": \"knowledge|status|location|ownership|"
                        "relationship|power|secret|other\",\n"
                        "      \"field\": \"变化字段\",\n"
                        "      \"old\": \"\",\n"
                        "      \"new\": \"\",\n"
                        "      \"description\": \"变化说明\",\n"
                        "      \"confidence\": 0.0,\n"
                        "      \"needs_review\": false,\n"
                        "      \"review_reason\": \"\",\n"
                        "      \"supporting_scene_ids\": []\n"
                        "    }\n"
                        "  ],\n"
                        "  \"uncertain_items\": [\n"
                        "    {\n"
                        "      \"description\": \"不确定项\",\n"
                        "      \"reason\": \"为什么不确定\",\n"
                        "      \"supporting_scene_ids\": []\n"
                        "    }\n"
                        "  ]\n"
                        "}"
                    ),
                ),
            ],
            temperature=0.2,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            extra=_deepseek_request_extra(profile, model=model),
        )
        return await _call_structured(
            _llm_client_for_profile(self.project_settings),
            request,
            Phase2WorldExtractionOutput,
            step_name="phase2_world_extraction",
            transport_retries=False,
            timeout_seconds=positive_int_env(
                "PHASE2_WORLD_TIMEOUT_SECONDS",
                PHASE2_WORLD_TIMEOUT_SECONDS,
            ),
            max_fix_attempts=1,
            fix_prompt=(
                "上一轮输出无法通过 Phase2WorldExtractionOutput 校验。"
                "只输出 JSON object，只包含 objects、relations、deltas、"
                "uncertain_items。每条 objects/relations/deltas 必须包含 "
                "supporting_scene_ids，且只能使用给定 Scene ID。不要 Markdown。"
            ),
        )


class _Phase1bDecisionOutput(BaseModel):
    use_primary_round: bool = True

    @field_validator("use_primary_round", mode="before")
    @classmethod
    def _normalize_use_primary_round(cls, value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value) if value is not None else True


def _materialize_phase1b_decision_output(
    payload: dict[str, Any],
    decision: _Phase1bDecisionOutput,
):
    from modules.imports.scene_fusion import Phase1bReducerOutput

    candidates = [
        candidate
        for candidate in payload.get("candidates", [])
        if isinstance(candidate, dict) and candidate.get("candidate_id")
    ]
    candidate_by_id = {
        str(candidate["candidate_id"]): candidate for candidate in candidates
    }
    core_start, core_end = _phase1b_core_range(payload)
    core_candidates = [
        candidate
        for candidate in candidates
        if core_start <= _phase1b_primary_chapter(candidate) <= core_end
    ]
    selected_ids: list[str] = []
    if decision.use_primary_round:
        selected_ids = [
            str(candidate["candidate_id"])
            for candidate in core_candidates
            if candidate.get("source_round") == "A"
        ]
    if not _phase1b_selected_covers_core(
        [candidate_by_id[candidate_id] for candidate_id in selected_ids],
        core_start=core_start,
        core_end=core_end,
    ):
        a_core_candidates = [
            candidate
            for candidate in core_candidates
            if candidate.get("source_round") == "A"
        ]
        if _phase1b_selected_covers_core(
            a_core_candidates,
            core_start=core_start,
            core_end=core_end,
        ):
            selected_ids = [
                str(candidate["candidate_id"]) for candidate in a_core_candidates
            ]
        else:
            selected_ids = [
                str(candidate["candidate_id"]) for candidate in core_candidates
            ]

    selected_candidates = [candidate_by_id[candidate_id] for candidate_id in selected_ids]
    scenes = [
        scene
        for candidate in selected_candidates
        for scene in _phase1b_scenes_for_candidate(candidate, core_start, core_end)
    ]
    selected_set = set(selected_ids)
    discarded_candidates = {
        str(candidate["candidate_id"]): "duplicate_candidate"
        for candidate in core_candidates
        if str(candidate["candidate_id"]) not in selected_set
    }
    return Phase1bReducerOutput.model_validate(
        {
            "scenes": scenes,
            "discarded_candidates": discarded_candidates,
        }
    )


def _phase1b_core_range(payload: dict[str, Any]) -> tuple[int, int]:
    raw_range = (payload.get("window") or {}).get("core_range") or []
    try:
        start = int(raw_range[0])
        end = int(raw_range[1])
    except (IndexError, TypeError, ValueError):
        chapters = _compact_chapters(payload.get("source_chapter_indices"))
        start = min(chapters) if chapters else 1
        end = max(chapters) if chapters else start
    return start, end


def _phase1b_primary_chapter(candidate: dict[str, Any]) -> int:
    chapters = _compact_chapters(candidate.get("source_chapter_indices"))
    return min(chapters) if chapters else 10**9


def _phase1b_selected_covers_core(
    candidates: list[dict[str, Any]],
    *,
    core_start: int,
    core_end: int,
) -> bool:
    expected = set(range(core_start, core_end + 1))
    covered = {
        chapter
        for candidate in candidates
        for chapter in _compact_chapters(candidate.get("source_chapter_indices"))
        if core_start <= chapter <= core_end
    }
    return expected.issubset(covered)


def _phase1b_scenes_for_candidate(
    candidate: dict[str, Any],
    core_start: int,
    core_end: int,
) -> list[dict[str, Any]]:
    scenes = []
    source_scenes = [
        scene for scene in candidate.get("scenes") or [] if isinstance(scene, dict)
    ]
    for index, scene in enumerate(source_scenes, start=1):
        scene_chapters = _phase1b_scene_chapters(
            scene,
            candidate,
            scene_index=index,
            scene_count=len(source_scenes),
        )
        owned_chapters = [
            chapter for chapter in scene_chapters if core_start <= chapter <= core_end
        ]
        if not owned_chapters:
            continue
        scenes.append(
            {
                "candidate_id": (
                    f"phase1b-kept-{candidate.get('candidate_id')}-{index}"
                ),
                "title": scene.get("title") or f"Scene {owned_chapters[0]}",
                "goal": scene.get("goal") or "沿用 Phase1a 候选。",
                "core_conflict": scene.get("core_conflict") or "",
                "emotional_beat": scene.get("emotional_beat") or "",
                "must_happen": scene.get("must_happen") or "",
                "must_not_happen": scene.get("must_not_happen") or "",
                "narrative_tag": scene.get("narrative_tag") or "imported",
                "scene_chunks": _phase1b_materialized_chunks(
                    scene.get("scene_chunks"),
                    owned_chapters,
                ),
                "source_candidate_ids": [str(candidate.get("candidate_id"))],
                "source_rounds": [str(candidate.get("source_round") or "A")],
                "source_chapter_indices": owned_chapters,
                "operation": "kept",
                "confidence": candidate.get("confidence") or 0.75,
                "fallback_required": False,
                "boundary_status": candidate.get("boundary_status") or "complete",
                "boundary_reason": (
                    "LLM reducer selected this Phase1a candidate; "
                    "fields were materialized deterministically."
                ),
                "needs_review": True,
                "review_reason": "LLM reducer decision should be reviewed.",
            }
        )
    if scenes:
        return scenes
    chapters = [
        chapter
        for chapter in _compact_chapters(candidate.get("source_chapter_indices"))
        if core_start <= chapter <= core_end
    ]
    return [
        {
            "candidate_id": f"phase1b-kept-{candidate.get('candidate_id')}-{chapter}",
            "title": f"Chapter {chapter}",
            "goal": "沿用 Phase1a 候选。",
            "must_happen": "沿用 Phase1a 候选。",
            "must_not_happen": "不得与已导入章节正文冲突",
            "scene_chunks": [{"chapter_index": chapter}],
            "source_candidate_ids": [str(candidate.get("candidate_id"))],
            "source_rounds": [str(candidate.get("source_round") or "A")],
            "source_chapter_indices": [chapter],
            "operation": "kept",
            "confidence": 0.7,
            "fallback_required": False,
            "boundary_status": "complete",
            "boundary_reason": "LLM reducer selected this Phase1a candidate.",
            "needs_review": True,
            "review_reason": "LLM reducer decision should be reviewed.",
        }
        for chapter in chapters
    ]


def _phase1b_scene_chapters(
    scene: dict[str, Any],
    candidate: dict[str, Any],
    *,
    scene_index: int = 1,
    scene_count: int = 1,
) -> list[int]:
    chunk_chapters = [
        chunk.get("chapter_index")
        for chunk in scene.get("scene_chunks", [])
        if isinstance(chunk, dict)
    ]
    chapters = _compact_chapters(chunk_chapters)
    if chapters:
        return chapters

    scene_chapters = _compact_chapters(scene.get("source_chapter_indices"))
    if scene_chapters:
        return scene_chapters

    candidate_chapters = _compact_chapters(candidate.get("source_chapter_indices"))
    if len(candidate_chapters) <= 1:
        return candidate_chapters

    return _phase1b_distribute_missing_scene_chapters(
        candidate_chapters,
        scene_index=scene_index,
        scene_count=scene_count,
    )


def _phase1b_distribute_missing_scene_chapters(
    candidate_chapters: list[int],
    *,
    scene_index: int,
    scene_count: int,
) -> list[int]:
    """Conservatively assign missing chunks instead of broadening every Scene."""

    if scene_count <= 1:
        return [candidate_chapters[0]]
    total = len(candidate_chapters)
    safe_index = max(1, min(scene_index, scene_count))
    start = (safe_index - 1) * total // scene_count
    end = safe_index * total // scene_count
    if end <= start:
        end = min(total, start + 1)
    return candidate_chapters[start:end] or [candidate_chapters[-1]]


def _phase1b_materialized_chunks(
    raw_chunks: Any,
    owned_chapters: list[int],
) -> list[dict[str, int | None]]:
    normalized: list[dict[str, int | None]] = []
    if isinstance(raw_chunks, list):
        for chunk in raw_chunks:
            if not isinstance(chunk, dict):
                continue
            try:
                chapter = int(chunk.get("chapter_index"))
            except (TypeError, ValueError):
                continue
            if chapter not in owned_chapters:
                continue
            try:
                start = int(chunk.get("start_paragraph") or 0)
            except (TypeError, ValueError):
                start = 0
            start = max(0, start)
            raw_end = chunk.get("end_paragraph")
            try:
                end = None if raw_end is None else int(raw_end)
            except (TypeError, ValueError):
                end = None
            if end is not None and end < start:
                end = None
            normalized.append(
                {
                    "chapter_index": chapter,
                    "start_paragraph": start,
                    "end_paragraph": end,
                }
            )
    return normalized or [
        {"chapter_index": chapter, "start_paragraph": 0, "end_paragraph": None}
        for chapter in owned_chapters
    ]


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
                "must_happen",
                "must_not_happen",
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
        "must_happen": _compact_text(scene.get("must_happen")),
        "must_not_happen": _compact_text(scene.get("must_not_happen")),
        "narrative_tag": _compact_text(scene.get("narrative_tag"), limit=40),
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
    diagnostics: list[dict[str, Any]] | None = None,
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
            partial_list_fields=_structured_list_fields(schema),
            diagnostics=diagnostics,
            format_repair_attempts=1,
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
