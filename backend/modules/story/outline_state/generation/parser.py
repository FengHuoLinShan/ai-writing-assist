"""深度导入 Phase 3 的 Scene 证据结构化解析模块。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from infrastructure.llm.agent_step_harness import run_managed_structured
from infrastructure.llm.client import LLMClient
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.llm.schemas import LLMCallRequest
from modules.story.outline_state.generation.context_builder import PlotStructureContext
from modules.story.outline_state.generation.models import (
    ForeshadowingPlan,
    GeneratedArc,
    GeneratedScene,
    GeneratedThread,
    OffscreenProgress,
    Question,
    RevealPlan,
    Risk,
    SimpleStructureOutput,
    SimpleSupportedStructureItem,
)

logger = logging.getLogger(__name__)


@dataclass
class ParsedPlotStructure:
    """解析后的剧情结构数据。"""

    threads: list[GeneratedThread]
    arcs: list[GeneratedArc]
    scenes: list[GeneratedScene]
    foreshadowing_plans: list[ForeshadowingPlan]
    reveal_plans: list[RevealPlan]
    offscreen_progress: list[OffscreenProgress]
    risks: list[Risk]
    questions_for_user: list[Question]
    turning_points: list[dict] | None = None
    uncertain_items: list[dict] | None = None
    diagnostics: dict | None = None


class PlotStructureParser:
    """解析 LLM 剧情结构输出。"""

    def __init__(
        self,
        context: PlotStructureContext,
        *,
        include_scenes: bool = True,
        fast_structured: bool = False,
        max_tokens: int = 32_768,
        high_quality: bool = False,
    ) -> None:
        self._context = context
        del include_scenes  # retained in the internal constructor seam for callers
        self._fast_structured = fast_structured
        self._max_tokens = max(1, int(max_tokens))
        self._high_quality = bool(high_quality)

    async def parse(
        self,
        llm_client: LLMClient,
        model: str,
        start_chapter: int,
        end_chapter: int,
    ) -> ParsedPlotStructure | None:
        """调用 LLM 并解析输出。

        Args:
            llm_client: LLM 客户端实例
            model: 模型名称
            start_chapter: 起始章节索引
            end_chapter: 结束章节索引

        Returns:
            ParsedPlotStructure: 成功时返回解析结果
            None: 多次重试后仍无有效内容时返回 None
        """
        if not self._fast_structured:
            raise RuntimeError(
                "legacy whole-structure creative generation is retired; "
                "use the P20 current-layer workflow"
            )
        if not getattr(self._context, "scenes", []):
            return ParsedPlotStructure(
                threads=[],
                arcs=[],
                scenes=[],
                foreshadowing_plans=[],
                reveal_plans=[],
                offscreen_progress=[],
                risks=[],
                questions_for_user=[],
                turning_points=[],
                uncertain_items=[
                    {
                        "kind": "missing_scene_evidence",
                        "message": "没有已采用 Scene 证据，Phase 3 未生成结构资产",
                    }
                ],
                diagnostics={
                    "parameter_version": "phase3_structure_simple_v1",
                    "input_mode": "no_scene_evidence",
                    "prompt_level": "none",
                    "provider_called": False,
                    "needs_review": True,
                },
            )
        return await self._parse_deep_import_simple(
            llm_client,
            model,
            start_chapter,
            end_chapter,
        )

    async def _parse_deep_import_simple(
        self,
        llm_client: LLMClient,
        model: str,
        start_chapter: int,
        end_chapter: int,
    ) -> ParsedPlotStructure | None:
        scene_cards = [
            scene
            for scene in getattr(self._context, "scenes", [])
            if isinstance(scene, dict) and scene.get("scene_id")
        ]
        scene_by_id = {str(scene["scene_id"]): scene for scene in scene_cards}
        request, prompt_chars = self._build_deep_import_simple_request(
            model,
            start_chapter,
            end_chapter,
            scene_cards,
        )
        diagnostics: dict[str, object] = {
            "parameter_version": "phase3_structure_simple_v1",
            "input_mode": "scenes_plus_world" if scene_cards else "scenes_only",
            "prompt_level": "minimal",
            "prompt_chars": prompt_chars,
            "retry_count": 0,
            "invalid_scene_ref_count": 0,
        }
        token_attempts = _phase3_token_attempts(
            prompt_chars,
            max_tokens=self._max_tokens,
        )
        last_error: Exception | None = None
        for attempt_index, max_tokens in enumerate(token_attempts):
            request.max_tokens = max_tokens
            diagnostics["max_tokens"] = max_tokens
            diagnostics["retry_count"] = attempt_index
            try:
                parsed = await run_managed_structured(
                    llm_client,
                    request,
                    SimpleStructureOutput,
                    step_name="outline.structure_parser.simple_output.structured",
                    max_fix_attempts=1,
                    partial_list_fields={
                        "plot_threads",
                        "arcs",
                        "foreshadowing",
                        "reveals",
                        "turning_points",
                        "uncertain_items",
                    },
                    format_repair_attempts=1,
                    transport_retries=True,
                    fix_prompt=(
                        "请修复为严格 JSON object，只包含 plot_threads、arcs、"
                        "foreshadowing、reveals、turning_points、uncertain_items。"
                        "每条结构结论必须有 supporting_scene_ids，且只能使用给定 "
                        "Scene ID。不要 Markdown。"
                    ),
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Deep import simple structure parse failed at max_tokens=%s: %s",
                    max_tokens,
                    redact_diagnostic(exc, limit=300),
                )
                continue
            normalized, invalid_refs = _normalize_simple_structure_refs(
                parsed,
                scene_by_id,
            )
            diagnostics["invalid_scene_ref_count"] = invalid_refs
            diagnostics["turning_point_count"] = len(normalized.turning_points)
            diagnostics["uncertain_count"] = len(normalized.uncertain_items)
            if _simple_structure_has_content(normalized):
                return _simple_structure_to_parsed(
                    normalized,
                    scene_by_id=scene_by_id,
                    start_chapter=start_chapter,
                    end_chapter=end_chapter,
                    diagnostics=diagnostics,
                )
            last_error = RuntimeError("empty simple structure output")
        logger.warning(
            "Deep import simple structure failed: %s",
            redact_diagnostic(last_error, limit=300),
        )
        return None

    def _build_deep_import_simple_request(
        self,
        model: str,
        start_chapter: int,
        end_chapter: int,
        scene_cards: list[dict],
    ) -> tuple[LLMCallRequest, int]:
        scene_ids = [str(scene["scene_id"]) for scene in scene_cards]
        input_mode = "scenes_plus_world" if self._context.markdown else "scenes_only"
        input_block = (
            "【Scene卡片 JSON】\n"
            f"{json.dumps(scene_cards, ensure_ascii=False)}\n\n"
            "【Phase2世界资产与上下文摘要】\n"
            f"{self._context.markdown}"
        )
        user_prompt = (
            f"{input_block}\n\n"
            f"你是小说叙事结构分析助手。上方是第{start_chapter}章到"
            f"第{end_chapter}章的 Scene 输入。\n"
            f"输入模式：{input_mode}。\n"
            "Phase2 来源组合：production_phase2_world_window_v1。\n\n"
            "任务：\n"
            "- 基于输入 Scene 总结叙事结构，不要重新切 Scene。\n"
            "- 输出主线、人物弧、伏笔、揭示、关键转折。\n"
            "- 每条结论必须有 supporting_scene_ids，且只能使用输入中的 "
            "Scene ID。\n"
            f"- 不要引用第{end_chapter}章之后的剧情，不要用后文知识解释"
            "当前内容。\n"
            "- 不要为了凑数量而拆得过细。\n\n"
            f"可用 Scene IDs：{', '.join(scene_ids)}\n\n"
            "严格输出 JSON object：\n"
            "{\n"
            '  "plot_threads": [\n'
            "    {\n"
            '      "title": "主线标题",\n'
            '      "summary": "主线说明",\n'
            '      "thread_type": "main|subplot|mystery|relationship|world",\n'
            '      "current_stage": "active|resolved|paused",\n'
            '      "confidence": 0.0,\n'
            '      "needs_review": false,\n'
            '      "review_reason": "",\n'
            '      "supporting_scene_ids": []\n'
            "    }\n"
            "  ],\n"
            '  "arcs": [\n'
            "    {\n"
            '      "character_name": "人物名",\n'
            '      "title": "弧线标题",\n'
            '      "summary": "人物阶段性变化",\n'
            '      "confidence": 0.0,\n'
            '      "needs_review": false,\n'
            '      "review_reason": "",\n'
            '      "supporting_scene_ids": []\n'
            "    }\n"
            "  ],\n"
            '  "foreshadowing": [\n'
            "    {\n"
            '      "title": "伏笔标题",\n'
            '      "summary": "设置与潜在指向",\n'
            '      "confidence": 0.0,\n'
            '      "needs_review": false,\n'
            '      "review_reason": "",\n'
            '      "supporting_scene_ids": []\n'
            "    }\n"
            "  ],\n"
            '  "reveals": [\n'
            "    {\n"
            '      "title": "揭示标题",\n'
            '      "summary": "揭示内容",\n'
            '      "confidence": 0.0,\n'
            '      "needs_review": false,\n'
            '      "review_reason": "",\n'
            '      "supporting_scene_ids": []\n'
            "    }\n"
            "  ],\n"
            '  "turning_points": [\n'
            "    {\n"
            '      "title": "转折标题",\n'
            '      "summary": "为什么是转折",\n'
            '      "confidence": 0.0,\n'
            '      "needs_review": false,\n'
            '      "review_reason": "",\n'
            '      "supporting_scene_ids": []\n'
            "    }\n"
            "  ],\n"
            '  "uncertain_items": [\n'
            "    {\n"
            '      "description": "不确定项",\n'
            '      "reason": "为什么不确定",\n'
            '      "supporting_scene_ids": []\n'
            "    }\n"
            "  ]\n"
            "}"
        )
        system_prompt = "你只输出可解析 JSON。不要 Markdown，不要解释。"
        prompt_chars = len(user_prompt) + len(system_prompt)
        return (
            LLMCallRequest(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=_phase3_token_attempts(
                    prompt_chars,
                    max_tokens=self._max_tokens,
                )[0],
                response_format={"type": "json_object"},
                extra=_deepseek_extra(model, high_quality=self._high_quality),
            ),
            prompt_chars,
        )

def _deepseek_extra(model: str, *, high_quality: bool = False) -> dict[str, object]:
    if str(model).startswith("deepseek"):
        return {
            "thinking": {"type": "enabled"},
            "reasoning_effort": "max" if high_quality else "high",
        }
    return {}


def _phase3_token_attempts(
    prompt_chars: int,
    *,
    max_tokens: int = 32_768,
) -> list[int]:
    del prompt_chars
    return [max(1, int(max_tokens))]


def _normalize_simple_structure_refs(
    output: SimpleStructureOutput,
    scene_by_id: dict[str, dict],
) -> tuple[SimpleStructureOutput, int]:
    invalid_refs = 0

    def normalize_item(
        item: SimpleSupportedStructureItem,
    ) -> SimpleSupportedStructureItem:
        nonlocal invalid_refs
        valid_ids: list[str] = []
        item_invalid_refs = 0
        for scene_id in item.supporting_scene_ids:
            if scene_id in scene_by_id:
                if scene_id not in valid_ids:
                    valid_ids.append(scene_id)
            else:
                invalid_refs += 1
                item_invalid_refs += 1
        review_reasons = [item.review_reason] if item.review_reason else []
        if item.confidence < 0.7:
            review_reasons.append("low_confidence")
        if item_invalid_refs:
            review_reasons.append("invalid_supporting_scene_refs_removed")
        if not valid_ids:
            review_reasons.append("missing_valid_supporting_scene_evidence")
        return item.model_copy(
            update={
                "supporting_scene_ids": valid_ids,
                "needs_review": bool(
                    item.needs_review
                    or item.confidence < 0.7
                    or item_invalid_refs
                    or not valid_ids
                ),
                "review_reason": "; ".join(dict.fromkeys(review_reasons)),
            }
        )

    uncertain_items: list[dict] = []
    for item in output.uncertain_items:
        if not isinstance(item, dict):
            continue
        raw_ids = item.get("supporting_scene_ids") or []
        valid_ids = []
        if isinstance(raw_ids, list):
            for scene_id in raw_ids:
                scene_id = str(scene_id)
                if scene_id in scene_by_id:
                    valid_ids.append(scene_id)
                else:
                    invalid_refs += 1
        uncertain_items.append({**item, "supporting_scene_ids": valid_ids})

    return (
        SimpleStructureOutput(
            plot_threads=[normalize_item(item) for item in output.plot_threads],
            arcs=[normalize_item(item) for item in output.arcs],
            foreshadowing=[normalize_item(item) for item in output.foreshadowing],
            reveals=[normalize_item(item) for item in output.reveals],
            turning_points=[normalize_item(item) for item in output.turning_points],
            uncertain_items=uncertain_items,
        ),
        invalid_refs,
    )


def _simple_structure_has_content(output: SimpleStructureOutput) -> bool:
    return bool(
        output.plot_threads
        or output.arcs
        or output.foreshadowing
        or output.reveals
        or output.turning_points
    )


def _simple_structure_to_parsed(
    output: SimpleStructureOutput,
    *,
    scene_by_id: dict[str, dict],
    start_chapter: int,
    end_chapter: int,
    diagnostics: dict,
) -> ParsedPlotStructure:
    threads = [
        GeneratedThread(
            name=item.title or item.summary[:24] or f"导入主线{index}",
            thread_type=item.thread_type or "main",
            summary=item.summary,
            visible_goal=item.summary,
            hidden_truth=None,
            start_chapter=_supported_start(item, scene_by_id, start_chapter),
            planned_payoff_chapter=_supported_end(item, scene_by_id, end_chapter),
            current_stage=item.current_stage or "active",
            confidence=item.confidence,
            needs_review=item.needs_review,
            review_reason=item.review_reason,
            supporting_scene_ids=item.supporting_scene_ids,
        )
        for index, item in enumerate(output.plot_threads, start=1)
        if item.title or item.summary
    ]
    arcs = [
        GeneratedArc(
            title=item.title or f"{item.character_name or '人物'}弧线",
            arc_index=index,
            start_chapter=_supported_start(item, scene_by_id, start_chapter),
            end_chapter=_supported_end(item, scene_by_id, end_chapter),
            arc_goal=item.summary,
            core_conflict=None,
            related_character_names=[item.character_name] if item.character_name else [],
            confidence=item.confidence,
            needs_review=item.needs_review,
            review_reason=item.review_reason,
            supporting_scene_ids=item.supporting_scene_ids,
        )
        for index, item in enumerate(output.arcs, start=1)
        if item.title or item.summary or item.character_name
    ]
    foreshadowing = [
        ForeshadowingPlan(
            name=item.title or item.summary[:24],
            summary=item.summary,
            planned_seed_chapter=_supported_start(item, scene_by_id, start_chapter),
            planned_payoff_chapter=_supported_end(item, scene_by_id, end_chapter),
            confidence=item.confidence,
            needs_review=item.needs_review,
            review_reason=item.review_reason,
            supporting_scene_ids=item.supporting_scene_ids,
        )
        for item in output.foreshadowing
        if item.title or item.summary
    ]
    reveals = [
        RevealPlan(
            target_name=item.title or item.summary[:24],
            target_type="world_entity",
            secret_summary=item.summary,
            confidence=item.confidence,
            needs_review=item.needs_review,
            review_reason=item.review_reason,
            supporting_scene_ids=item.supporting_scene_ids,
        )
        for item in output.reveals
        if item.title or item.summary
    ]
    turning_points = [
        _supported_extra_item(item, scene_by_id)
        for item in output.turning_points
        if item.title or item.summary
    ]
    return ParsedPlotStructure(
        threads=threads,
        arcs=arcs,
        scenes=[],
        foreshadowing_plans=foreshadowing,
        reveal_plans=reveals,
        offscreen_progress=[],
        risks=[],
        questions_for_user=[],
        turning_points=turning_points,
        uncertain_items=list(output.uncertain_items),
        diagnostics=dict(diagnostics),
    )


def _supported_start(
    item: SimpleSupportedStructureItem,
    scene_by_id: dict[str, dict],
    default: int,
) -> int:
    chapters = _chapters_for_scene_ids(item.supporting_scene_ids, scene_by_id)
    return min(chapters) if chapters else default


def _supported_end(
    item: SimpleSupportedStructureItem,
    scene_by_id: dict[str, dict],
    default: int,
) -> int:
    chapters = _chapters_for_scene_ids(item.supporting_scene_ids, scene_by_id)
    return max(chapters) if chapters else default


def _chapters_for_scene_ids(
    scene_ids: list[str],
    scene_by_id: dict[str, dict],
) -> list[int]:
    chapters: list[int] = []
    for scene_id in scene_ids:
        scene = scene_by_id.get(scene_id)
        if not scene:
            continue
        for key in ("start_chapter", "end_chapter"):
            try:
                value = int(scene.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                chapters.append(value)
    return chapters


def _supported_extra_item(
    item: SimpleSupportedStructureItem,
    scene_by_id: dict[str, dict],
) -> dict:
    chapters = _chapters_for_scene_ids(item.supporting_scene_ids, scene_by_id)
    return {
        "title": item.title,
        "summary": item.summary,
        "confidence": item.confidence,
        "needs_review": item.needs_review,
        "review_reason": item.review_reason,
        "supporting_scene_ids": item.supporting_scene_ids,
        "chapter_range": [min(chapters), max(chapters)] if chapters else [],
    }
