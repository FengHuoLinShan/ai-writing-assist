"""剧情结构生成器的 LLM 输出解析模块。

负责 Prompt 加载、LLM 调用、空结果重试、逐项校验降级，
将原始 LLM 输出转换为结构化的 ParsedPlotStructure。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

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


class PlotStructureParser:
    """解析 LLM 剧情结构输出。"""

    MAX_EMPTY_RETRIES = 2

    def __init__(
        self,
        context: PlotStructureContext,
        *,
        include_scenes: bool = True,
        fast_structured: bool = False,
    ) -> None:
        self._context = context
        self._include_scenes = include_scenes
        self._fast_structured = fast_structured

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
        system_prompt = self._build_system_prompt(start_chapter, end_chapter)
        request = self._build_request(system_prompt, model, start_chapter, end_chapter)

        result: GeneratedOutput | None = None
        max_empty_retries = 0 if self._fast_structured else self.MAX_EMPTY_RETRIES
        for attempt in range(max_empty_retries + 1):
            parsed: GeneratedOutput | None = None
            try:
                parsed = await llm_client.generate_structured(
                    request,
                    GeneratedOutput,
                    max_fix_attempts=1 if self._fast_structured else 2,
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
            max_tokens=3072 if self._fast_structured else (
                6144 if not self._include_scenes else 4096
            ),
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
            raw = await llm_client.generate(request)
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
        )


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
