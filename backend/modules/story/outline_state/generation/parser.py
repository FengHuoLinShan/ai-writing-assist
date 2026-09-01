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
    StructureEvidenceReviewOutput,
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
                    "parameter_version": "phase3_structure_simple_v2",
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
            "parameter_version": "phase3_structure_simple_v2",
            "input_mode": (
                "scenes_plus_world" if self._context.markdown else "scenes_only"
            ),
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
                call_diagnostics: list[dict] = []
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
                    diagnostics=call_diagnostics,
                    fix_prompt=(
                        "请修复为严格 JSON object，只包含 plot_threads、arcs、"
                        "foreshadowing、reveals、turning_points、uncertain_items。"
                        "每条结构结论必须有 supporting_scene_ids，且只能使用给定 "
                        "Scene ID。不要 Markdown。"
                    ),
                )
                diagnostics["first_pass_cache_usage"] = _cache_usage_summary(
                    call_diagnostics
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
            normalized, evidence_diagnostics = await _review_structure_evidence(
                llm_client,
                model=model,
                output=normalized,
                scene_by_id=scene_by_id,
                high_quality=self._high_quality,
            )
            diagnostics["invalid_scene_ref_count"] = invalid_refs
            diagnostics.update(evidence_diagnostics)
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
        prompt_scene_cards = [
            {key: value for key, value in scene.items() if not str(key).startswith("_")}
            for scene in scene_cards
        ]
        input_mode = "scenes_plus_world" if self._context.markdown else "scenes_only"
        input_block = (
            "【Scene卡片 JSON】\n"
            f"{json.dumps(prompt_scene_cards, ensure_ascii=False)}\n\n"
            "【Phase2世界资产与上下文摘要】\n"
            f"{self._context.markdown}"
        )
        system_prompt = (
            "你是小说叙事结构分析助手。基于输入 Scene 总结主线、人物弧、伏笔、"
            "揭示和关键转折；不要重新切 Scene、使用可见范围之外的剧情、用后文"
            "知识解释当前内容或为了凑数量拆分。每条结论必须提供 supporting_scene_ids，"
            "且只能使用输入给出的 Scene ID。模型置信度只表示第一遍判断，不代表采用。\n"
            "只输出 JSON object，顶层仅含 plot_threads、arcs、foreshadowing、reveals、"
            "turning_points、uncertain_items。结构条目通用字段为 title、summary、"
            "confidence、needs_review、review_reason、supporting_scene_ids；plot_threads "
            "另含 thread_type=main|subplot|mystery|relationship|world 和 "
            "current_stage=active|resolved|paused；arcs 另含 character_name。"
            "uncertain_items 使用 description、reason、supporting_scene_ids。"
            "不要输出 evidence_gate、Markdown 或解释。"
        )
        user_prompt = (
            f"可见章节范围：{start_chapter}-{end_chapter}\n"
            f"输入模式：{input_mode}\n"
            "Phase2 来源组合：production_phase2_world_window_v1\n"
            f"可用 Scene IDs：{', '.join(scene_ids)}\n\n"
            f"{input_block}"
        )
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


_PHASE3_EVIDENCE_BATCH_CHARS = 60_000
_PHASE3_EVIDENCE_TEXT_PART_CHARS = 48_000


async def _review_structure_evidence(
    llm_client: LLMClient,
    *,
    model: str,
    output: SimpleStructureOutput,
    scene_by_id: dict[str, dict],
    high_quality: bool,
) -> tuple[SimpleStructureOutput, dict[str, int]]:
    collections = (
        "plot_threads",
        "arcs",
        "foreshadowing",
        "reveals",
        "turning_points",
    )
    states: dict[str, dict] = {}
    units: list[dict] = []
    unit_map: dict[str, tuple[str, str]] = {}

    for category in collections:
        for index, item in enumerate(getattr(output, category)):
            candidate_id = f"{category}:{index}"
            refs = list(dict.fromkeys(item.supporting_scene_ids))
            state = {
                "category": category,
                "item": item,
                "refs": refs,
                "reasons": [],
                "reviews": [],
            }
            states[candidate_id] = state
            if item.confidence < 0.80:
                state["reasons"].append("first_pass_confidence_below_0.80")
                continue
            if item.needs_review:
                state["reasons"].append("first_pass_requested_review")
                continue
            if not refs:
                state["reasons"].append("missing_valid_supporting_scene_evidence")
                continue
            for scene_id in refs:
                scene = scene_by_id.get(scene_id) or {}
                evidence = scene.get("_evidence") or {}
                if evidence.get("status") != "exact":
                    state["reasons"].append(f"scene_source_not_exact:{scene_id}")
                    continue
                sources = evidence.get("sources") or []
                scene_text = "\n\n".join(
                    str(source.get("text") or "")
                    for source in sources
                    if isinstance(source, dict)
                )
                if not scene_text:
                    state["reasons"].append(f"scene_source_empty:{scene_id}")
                    continue
                for part_index, start in enumerate(
                    range(0, len(scene_text), _PHASE3_EVIDENCE_TEXT_PART_CHARS),
                    start=1,
                ):
                    unit_id = f"{candidate_id}@{scene_id}:{part_index}"
                    units.append(
                        {
                            "candidate_id": unit_id,
                            "category": category,
                            "title": item.title[:500],
                            "summary": item.summary[:4000],
                            "first_pass_confidence": item.confidence,
                            "supporting_scene_ids": refs,
                            "scene_id": scene_id,
                            "scene_text": scene_text[
                                start : start + _PHASE3_EVIDENCE_TEXT_PART_CHARS
                            ],
                        }
                    )
                    unit_map[unit_id] = (candidate_id, scene_id)

    review_calls = 0
    call_failures = 0
    raw_verdicts: list[str] = []
    cache_usage: dict[str, int] = {}
    for batch in _phase3_evidence_batches(units):
        request = _phase3_evidence_request(
            model=model,
            batch=batch,
            high_quality=high_quality,
        )
        review_calls += 1
        batch_diagnostics: list[dict] = []
        try:
            reviewed = await run_managed_structured(
                llm_client,
                request,
                StructureEvidenceReviewOutput,
                step_name=f"outline.structure_parser.evidence_review_{review_calls}",
                max_fix_attempts=1,
                transport_retries=True,
                format_repair_attempts=1,
                diagnostics=batch_diagnostics,
                fix_prompt=(
                    "只输出 JSON object，顶层仅含 reviews。每项必须逐字复用输入中的 "
                    "candidate_id，并包含 verdict、confidence、evidence。"
                ),
            )
            batch_usage = _cache_usage_summary(batch_diagnostics)
            for key, value in batch_usage.items():
                cache_usage[key] = cache_usage.get(key, 0) + int(value or 0)
        except Exception as exc:
            call_failures += 1
            logger.warning(
                "Phase 3 evidence review batch failed: %s",
                redact_diagnostic(exc, limit=300),
            )
            continue
        for review in reviewed.reviews:
            expected = unit_map.get(review.candidate_id)
            if expected is None:
                continue
            candidate_id, scene_id = expected
            source_texts = [
                str(source.get("text") or "")
                for source in (
                    (scene_by_id.get(scene_id) or {}).get("_evidence") or {}
                ).get("sources", [])
                if isinstance(source, dict)
            ]
            exact_evidence = [
                {"scene_id": scene_id, **evidence.model_dump(mode="json")}
                for evidence in review.evidence
                if evidence.quote and any(evidence.quote in text for text in source_texts)
            ]
            verdict = review.verdict if exact_evidence else "uncertain"
            raw_verdicts.append(review.verdict)
            states[candidate_id]["reviews"].append(
                {
                    "scene_id": scene_id,
                    "raw_verdict": review.verdict,
                    "verdict": verdict,
                    "confidence": review.confidence,
                    "evidence": exact_evidence,
                }
            )

    replacements: dict[str, list[SimpleSupportedStructureItem]] = {
        key: [] for key in collections
    }
    passed = 0
    needs_review = 0
    for state in states.values():
        item = state["item"]
        supported_scene_ids: list[str] = []
        evidence_quotes: list[dict] = []
        review_confidences: list[float] = []
        scene_verdicts: dict[str, str] = {}
        for scene_id in state["refs"]:
            scene_reviews = [
                review for review in state["reviews"] if review["scene_id"] == scene_id
            ]
            blocking_verdicts = {
                review["raw_verdict"]
                for review in scene_reviews
                if review["raw_verdict"] in {"unsupported", "conflict"}
            }
            if blocking_verdicts:
                verdict = "conflict" if "conflict" in blocking_verdicts else "unsupported"
                scene_verdicts[scene_id] = verdict
                state["reasons"].append(f"evidence_review_{verdict}:{scene_id}")
                continue
            supported = [
                review
                for review in scene_reviews
                if review["verdict"] == "supported"
                and review["confidence"] >= 0.90
                and review["evidence"]
            ]
            if supported:
                best = max(supported, key=lambda review: review["confidence"])
                supported_scene_ids.append(scene_id)
                review_confidences.append(float(best["confidence"]))
                evidence_quotes.extend(best["evidence"])
                scene_verdicts[scene_id] = "supported"
            else:
                scene_verdicts[scene_id] = (
                    scene_reviews[0]["verdict"] if scene_reviews else "uncertain"
                )

        minimum_scenes = 2 if state["category"] in {"plot_threads", "arcs"} else 1
        if len(supported_scene_ids) < minimum_scenes:
            state["reasons"].append(f"requires_{minimum_scenes}_supported_scene")
        if set(supported_scene_ids) != set(state["refs"]):
            state["reasons"].append("not_all_referenced_scenes_supported")
        if call_failures and not state["reviews"]:
            state["reasons"].append("evidence_review_call_failed")
        gate_passed = not state["reasons"]
        passed += int(gate_passed)
        needs_review += int(not gate_passed)
        deduped_evidence = {
            (entry["scene_id"], entry["quote"]): entry for entry in evidence_quotes
        }
        gate = {
            "status": "passed" if gate_passed else "needs_review",
            "review_confidence": min(review_confidences) if review_confidences else 0.0,
            "scene_verdicts": scene_verdicts,
            "supported_scene_ids": supported_scene_ids,
            "evidence": list(deduped_evidence.values()),
            "reasons": list(dict.fromkeys(state["reasons"])),
        }
        review_reason = "; ".join(
            dict.fromkeys(
                [
                    *([item.review_reason] if item.review_reason else []),
                    *gate["reasons"],
                ]
            )
        )
        replacements[state["category"]].append(
            item.model_copy(
                update={
                    "needs_review": not gate_passed,
                    "review_reason": review_reason,
                    "evidence_gate": gate,
                }
            )
        )

    return (
        output.model_copy(update=replacements),
        {
            "evidence_review_call_count": review_calls,
            "evidence_review_call_failure_count": call_failures,
            "evidence_gate_passed_count": passed,
            "evidence_gate_review_count": needs_review,
            "evidence_review_unsupported_count": raw_verdicts.count("unsupported"),
            "evidence_review_conflict_count": raw_verdicts.count("conflict"),
            **cache_usage,
        },
    )


def _cache_usage_summary(diagnostics: list[dict]) -> dict[str, int]:
    entries = [
        item
        for item in diagnostics
        if item.get("kind") == "structured_usage"
        and ("cache_hit_tokens" in item or "cache_miss_tokens" in item)
    ]
    if not entries:
        return {}
    return {
        key: sum(int(item.get(key, 0) or 0) for item in entries)
        for key in ("cache_hit_tokens", "cache_miss_tokens")
    }


def _phase3_evidence_batches(units: list[dict]) -> list[list[dict]]:
    batches: list[list[dict]] = []
    current: list[dict] = []
    current_chars = 0
    for unit in units:
        size = len(json.dumps(unit, ensure_ascii=False, default=str))
        if current and current_chars + size > _PHASE3_EVIDENCE_BATCH_CHARS:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(unit)
        current_chars += size
    if current:
        batches.append(current)
    return batches


def _phase3_evidence_request(
    *,
    model: str,
    batch: list[dict],
    high_quality: bool,
) -> LLMCallRequest:
    system_prompt = (
        "你是与结构生成第一遍分离的证据复核员。逐项判断候选结论是否被给定的"
        "单个 Scene 精确正文支持。只使用当前 item 的 scene_text；不能使用常识、"
        "后文、Scene 卡摘要或模型自报置信度。verdict 只能是 supported、"
        "structural_inference、unsupported、conflict、uncertain。supported 必须返回"
        "至少一条逐字证据。每个输入 candidate_id "
        "恰好返回一次。只输出符合 schema 的 JSON。"
    )
    return LLMCallRequest(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {"review_items": batch},
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ),
            },
        ],
        temperature=0,
        max_tokens=12_000,
        response_format={"type": "json_object"},
        extra=_deepseek_extra(model, high_quality=high_quality),
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
            evidence_gate=item.evidence_gate,
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
            evidence_gate=item.evidence_gate,
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
            evidence_gate=item.evidence_gate,
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
            evidence_gate=item.evidence_gate,
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
        "evidence_gate": item.evidence_gate,
        "chapter_range": [min(chapters), max(chapters)] if chapters else [],
    }
