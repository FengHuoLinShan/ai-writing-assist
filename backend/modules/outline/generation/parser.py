"""剧情结构生成器的 LLM 输出解析模块。

负责 Prompt 加载、LLM 调用、空结果重试、逐项校验降级，
将原始 LLM 输出转换为结构化的 ParsedPlotStructure。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from infrastructure.llm.agent_step_harness import (
    run_managed_generate,
    run_managed_structured,
)
from infrastructure.llm.client import LLMClient
from infrastructure.llm.prompt_loader import load_prompt
from infrastructure.llm.schemas import LLMCallRequest
from modules.outline.generation.context_builder import PlotStructureContext
from modules.outline.generation.models import (
    ForeshadowingPlan,
    GeneratedArc,
    GeneratedOutput,
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

    MAX_EMPTY_RETRIES = 2

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
        self._include_scenes = include_scenes
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
        if self._fast_structured and getattr(self._context, "scenes", []):
            return await self._parse_deep_import_simple(
                llm_client,
                model,
                start_chapter,
                end_chapter,
            )

        system_prompt = self._build_system_prompt(start_chapter, end_chapter)
        request = self._build_request(system_prompt, model, start_chapter, end_chapter)

        result: GeneratedOutput | None = None
        max_empty_retries = 0 if self._fast_structured else self.MAX_EMPTY_RETRIES
        for attempt in range(max_empty_retries + 1):
            parsed: GeneratedOutput | None = None
            try:
                parsed = await run_managed_structured(
                    llm_client,
                    request,
                    GeneratedOutput,
                    step_name="outline.structure_parser.generated_output.structured",
                    max_fix_attempts=1 if self._fast_structured else 2,
                    partial_list_fields={
                        "plot_threads",
                        "outline_arcs",
                        "scenes",
                        "foreshadowing_plans",
                        "reveal_plans",
                        "offscreen_progress",
                        "risks",
                        "questions_for_user",
                    },
                    format_repair_attempts=1,
                    fix_prompt=(
                        "请修复为严格 JSON 对象，只包含 plot_threads、outline_arcs、"
                        "scenes、foreshadowing_plans、reveal_plans、offscreen_progress、"
                        "risks、questions_for_user 字段。不要 Markdown。"
                    ),
                    transport_retries=True,
                )
            except Exception as exc:
                if self._is_recoverable(exc) and not self._fast_structured:
                    logger.warning(
                        "Structured validation failed (attempt %d/%d), "
                        "falling back to per-item validation: %s",
                        attempt + 1,
                        max_empty_retries + 1,
                        exc,
                    )
                    parsed = await self._fallback_per_item_parse(llm_client, request)
                else:
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s",
                        attempt + 1,
                        max_empty_retries + 1,
                        exc,
                    )
                if parsed is None:
                    continue

            if self._has_content(parsed):
                result = parsed
                break

            logger.warning(
                "Empty LLM result (attempt %d/%d), retrying...",
                attempt + 1,
                max_empty_retries + 1,
            )
        else:
            logger.error(
                "All %d generation attempts returned empty or failed",
                max_empty_retries + 1,
            )
            return None

        return self._to_parsed(result)

    def _build_system_prompt(self, start_chapter: int, end_chapter: int) -> str:
        """加载并补全 system prompt。"""
        system_prompt = load_prompt(
            "structure_plot",
            world_context="",
            user_intent="",
            target_scope=f"章节 {start_chapter}-{end_chapter}",
        )
        system_prompt += f"\n\n## 当前上下文\n\n{self._context.markdown}"
        if not self._include_scenes:
            system_prompt += (
                "\n\n## 深度导入结构模式\n"
                "- 不要生成新的 scenes，scenes 必须返回空数组。\n"
                "- 只根据已生成 Scene 摘要、世界对象和人物，生成剧情线、篇章纲、"
                "伏笔计划、揭示计划、幕后推进、风险和问题。\n"
                "- 全范围保持极简：plot_threads 恰好 3 项，outline_arcs 恰好 3 项，"
                "foreshadowing_plans 最多 1 项，reveal_plans 最多 1 项；"
                "offscreen_progress、risks、questions_for_user 返回空数组。\n"
                "- 总 JSON 控制在 1800 个中文字符以内，不要逐章展开。\n"
                "- 所有文本字段保持简短：标题 20 字以内，摘要/描述 50 字以内；"
                "禁止摘录正文、复述场景列表或解释 JSON。\n"
                "- 1-7 章小样本每类目标输出 4 项，至少输出 2 项；"
                "优先保留长期创作资产。\n"
            )
        return system_prompt

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
                    exc,
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
        logger.warning("Deep import simple structure failed: %s", last_error)
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

    def _build_request(
        self,
        system_prompt: str,
        model: str,
        start_chapter: int,
        end_chapter: int,
    ) -> LLMCallRequest:
        """构建 LLM 调用请求。"""
        return LLMCallRequest(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": self._build_user_prompt(start_chapter, end_chapter),
                },
            ],
            temperature=0.5,
            max_tokens=self._max_tokens,
            response_format={"type": "json_object"},
        )

    def _build_user_prompt(self, start_chapter: int, end_chapter: int) -> str:
        if not self._include_scenes:
            return (
                f"请为章节 {start_chapter}-{end_chapter} 生成紧凑剧情结构。"
                "返回 JSON 对象；plot_threads、outline_arcs、foreshadowing_plans、"
                "reveal_plans 四类都应有内容；plot_threads 恰好 3 项，"
                "outline_arcs 恰好 3 项，foreshadowing_plans 最多 1 项，"
                "reveal_plans 最多 1 项；offscreen_progress、risks、"
                "questions_for_user、scenes 都返回空数组；不要逐章展开。"
            )
        return (
            f"请为章节 {start_chapter}-{end_chapter} 生成剧情结构和篇章大纲。"
            "\n\n请同时提取本章范围内的 Scene 卡。"
            "每个 Scene 卡包含 title/goal/core_conflict/"
            "emotional_beat/must_happen/must_not_happen/"
            "narrative_tag，"
            "并标注每个 scene_chunk 对应的 chapter_index、"
            "start_pos、end_pos。"
        )

    def _is_recoverable(self, exc: Exception) -> bool:
        """判断异常是否可通过逐项校验降级恢复。"""
        from infrastructure.llm.errors import LLMInvalidResponseError

        return isinstance(
            exc,
            (LLMInvalidResponseError, ValidationError, json.JSONDecodeError),
        )

    async def _fallback_per_item_parse(
        self,
        llm_client: LLMClient,
        request: LLMCallRequest,
    ) -> GeneratedOutput | None:
        """结构化输出失败时，降级为原始文本 + 逐项校验。"""
        try:
            raw = await run_managed_generate(
                llm_client,
                request,
                step_name="outline.structure_parser.fallback.generate",
            )
            raw_data = json.loads(raw.content)
        except Exception as inner_exc:
            logger.warning("Per-item validation also failed: %s", inner_exc)
            return None

        extra_models = {
            "foreshadowing_plans": ForeshadowingPlan,
            "reveal_plans": RevealPlan,
            "offscreen_progress": OffscreenProgress,
            "risks": Risk,
            "questions_for_user": Question,
            "scenes": GeneratedScene,
        }
        return _per_item_validate(
            raw_data,
            GeneratedThread,
            GeneratedArc,
            extra_models,
            GeneratedOutput,
        )

    def _has_content(self, parsed: GeneratedOutput) -> bool:
        """检查解析结果是否包含任何有效内容。"""
        return bool(
            parsed.plot_threads
            or parsed.outline_arcs
            or parsed.scenes
            or parsed.foreshadowing_plans
            or parsed.reveal_plans
            or parsed.offscreen_progress
            or parsed.risks
            or parsed.questions_for_user
        )

    def _to_parsed(self, output: GeneratedOutput) -> ParsedPlotStructure:
        """将 GeneratedOutput 转换为 ParsedPlotStructure。"""
        return ParsedPlotStructure(
            threads=list(output.plot_threads),
            arcs=list(output.outline_arcs),
            scenes=list(output.scenes),
            foreshadowing_plans=list(output.foreshadowing_plans),
            reveal_plans=list(output.reveal_plans),
            offscreen_progress=list(output.offscreen_progress),
            risks=list(output.risks),
            questions_for_user=list(output.questions_for_user),
            turning_points=[],
            uncertain_items=[],
            diagnostics={},
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


def _per_item_validate[P: BaseModel](
    data: dict | list | None,
    thread_cls: type[BaseModel],
    arc_cls: type[BaseModel],
    extra_models: dict[str, type[BaseModel]] | None,
    output_cls: type[P],
) -> P:
    """逐项校验，单字段错不整批丢弃。

    LLM 常输出类型错误的值（如 planned_payoff_chapter="后续篇章"），
    generate_structured 的全局校验会丢弃整批数据。此函数对每条
    thread/arc 做独立校验，只丢弃无效项。
    """
    if not isinstance(data, dict):
        logger.warning("_per_item_validate: expected dict, got %s", type(data).__name__)
        return output_cls()

    threads = []
    for t in data.get("plot_threads", []):
        try:
            threads.append(thread_cls.model_validate(t))
        except ValidationError as e:
            logger.warning("Skipping invalid thread: %s", e)

    arcs = []
    for a in data.get("outline_arcs", []):
        try:
            arcs.append(arc_cls.model_validate(a))
        except ValidationError as e:
            logger.warning("Skipping invalid arc: %s", e)

    extra_kw: dict[str, list] = {}
    section_keys = (
        "foreshadowing_plans",
        "reveal_plans",
        "offscreen_progress",
        "risks",
        "questions_for_user",
        "scenes",
    )
    for section_key in section_keys:
        items = data.get(section_key, [])
        if not isinstance(items, list):
            logger.warning(
                "_per_item_validate: '%s' expected list, got %s",
                section_key,
                type(items).__name__,
            )
            extra_kw[section_key] = []
            continue
        model_cls = (extra_models or {}).get(section_key)
        validated_items = []
        for item in items:
            if model_cls is not None:
                try:
                    validated_items.append(model_cls.model_validate(item))
                except ValidationError as e:
                    logger.warning("Skipping invalid %s item: %s", section_key, e)
            else:
                validated_items.append(item)
        extra_kw[section_key] = validated_items

    return output_cls(plot_threads=threads, outline_arcs=arcs, **extra_kw)
