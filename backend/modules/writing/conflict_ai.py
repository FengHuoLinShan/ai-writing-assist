"""AI review and suggestion services for writing conflict checks."""

from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.context.markdown_renderer import render_compiled_context
from modules.writing.repositories import WritingConflictCheckRepository
from modules.writing.schemas import (
    WritingConflictAiReviewIssue,
    WritingConflictAiReviewRawOutput,
    WritingConflictSuggestionOutput,
)
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)

AI_REVIEW_ACTION = "writing.conflict_check.ai_review"
AI_SUGGESTION_ACTION = "writing.conflict_check.ai_suggestion"
WRITING_CONFLICT_AI_MAX_TOKENS = 20000


class ConflictCheckAiReviewService:
    """Append LLM soft-conflict judgments to an existing check."""

    def __init__(
        self,
        repo: WritingConflictCheckRepository,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._repo = repo
        self._llm = llm_client or LLMClient()

    async def run(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        check_id: str,
        context_confirmation_id: str,
    ) -> tuple[object, list[object]]:
        from modules.context.facade import (
            attach_result_ref,
            compile_from_confirmation,
            require_fresh_confirmation,
        )

        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(check_id, "check_id")
        confirmation_uuid = parse_uuid(
            context_confirmation_id,
            "context_confirmation_id",
        )
        existing = await self._repo.get_check(db, cid, nid)
        if existing is None:
            raise HTTPException(status_code=404, detail="Conflict check not found")
        check, current_items = existing

        try:
            confirmation = await require_fresh_confirmation(
                db,
                novel_id=novel_id,
                action=AI_REVIEW_ACTION,
                confirmation_id=context_confirmation_id,
            )
            _validate_confirmation_scope(confirmation, check)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        await self._repo.update_ai_review(
            db,
            check_id=cid,
            novel_id=nid,
            status="running",
            confirmation_id=confirmation_uuid,
            model=getattr(self._llm, "model_name", None),
            error=None,
        )

        try:
            compiled = await compile_from_confirmation(
                db,
                novel_id=novel_id,
                action=AI_REVIEW_ACTION,
                confirmation_id=context_confirmation_id,
            )
            context_markdown = render_compiled_context(compiled)
            output = await self._llm.generate_structured(
                LLMCallRequest(
                    model=getattr(self._llm, "model_name", "gpt-4o"),
                    messages=[
                        LLMMessage(
                            role="system",
                            content=_AI_REVIEW_SYSTEM_PROMPT,
                        ),
                        LLMMessage(
                            role="user",
                            content=_build_ai_review_prompt(
                                check=check,
                                items=current_items,
                                context_markdown=context_markdown,
                            ),
                        ),
                    ],
                    temperature=0.2,
                    max_tokens=WRITING_CONFLICT_AI_MAX_TOKENS,
                ),
                WritingConflictAiReviewRawOutput,
            )
            ai_items, discarded_count = _ai_review_items(
                output,
                check=check,
                confirmation_id=confirmation_uuid,
                include_pending_objects=confirmation.include_pending_objects,
            )
            if ai_items:
                await self._repo.append_items(
                    db,
                    check_id=cid,
                    novel_id=nid,
                    items=ai_items,
                )
            items = await self._repo.list_items(db, cid, nid)
            status = "partial" if discarded_count else "done"
            summary_json = _summary_with_ai_review(
                items,
                check.summary_json or {},
                status=status,
                discarded_count=discarded_count,
            )
            updated = await self._repo.update_ai_review(
                db,
                check_id=cid,
                novel_id=nid,
                status=status,
                summary_json=summary_json,
                confirmation_id=confirmation_uuid,
                model=getattr(self._llm, "model_name", None),
                error=None,
            )
            await attach_result_ref(
                db,
                confirmation_id=context_confirmation_id,
                result_type="writing_conflict_check",
                result_id=check_id,
                status=status,
            )
            return updated or check, items
        except Exception as exc:  # LLM/context failures degrade AI only.
            logger.exception("AI conflict review failed")
            items = await self._repo.list_items(db, cid, nid)
            summary_json = _summary_with_ai_review(
                items,
                check.summary_json or {},
                status="failed",
                discarded_count=0,
            )
            updated = await self._repo.update_ai_review(
                db,
                check_id=cid,
                novel_id=nid,
                status="failed",
                summary_json=summary_json,
                confirmation_id=confirmation_uuid,
                model=getattr(self._llm, "model_name", None),
                error=str(exc),
            )
            try:
                await attach_result_ref(
                    db,
                    confirmation_id=context_confirmation_id,
                    result_type="writing_conflict_check",
                    result_id=check_id,
                    status="failed",
                )
            except ValueError:
                logger.exception("Failed to attach AI review result ref")
            return updated or check, items


class ConflictSuggestionService:
    """Generate and persist manual AI repair suggestions for one item."""

    def __init__(
        self,
        repo: WritingConflictCheckRepository,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._repo = repo
        self._llm = llm_client or LLMClient()

    async def generate(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        item_id: str,
        context_confirmation_id: str,
    ) -> object:
        from modules.context.facade import (
            attach_result_ref,
            compile_from_confirmation,
            require_fresh_confirmation,
        )

        nid = parse_uuid(novel_id, "novel_id")
        iid = parse_uuid(item_id, "item_id")
        confirmation_uuid = parse_uuid(
            context_confirmation_id,
            "context_confirmation_id",
        )
        item = await self._repo.get_item(db, iid, nid)
        if item is None:
            raise HTTPException(status_code=404, detail="Conflict item not found")
        check_result = await self._repo.get_check(db, item.check_id, nid)
        if check_result is None:
            raise HTTPException(status_code=404, detail="Conflict check not found")
        check, check_items = check_result

        try:
            confirmation = await require_fresh_confirmation(
                db,
                novel_id=novel_id,
                action=AI_SUGGESTION_ACTION,
                confirmation_id=context_confirmation_id,
            )
            _validate_confirmation_scope(confirmation, check)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        await self._repo.update_item_suggestion(
            db,
            item_id=iid,
            novel_id=nid,
            status="running",
            confirmation_id=confirmation_uuid,
            error=None,
        )

        try:
            compiled = await compile_from_confirmation(
                db,
                novel_id=novel_id,
                action=AI_SUGGESTION_ACTION,
                confirmation_id=context_confirmation_id,
            )
            output = await self._llm.generate_structured(
                LLMCallRequest(
                    model=getattr(self._llm, "model_name", "gpt-4o"),
                    messages=[
                        LLMMessage(
                            role="system",
                            content=_AI_SUGGESTION_SYSTEM_PROMPT,
                        ),
                        LLMMessage(
                            role="user",
                            content=_build_ai_suggestion_prompt(
                                check=check,
                                item=item,
                                items=check_items,
                                context_markdown=render_compiled_context(compiled),
                            ),
                        ),
                    ],
                    temperature=0.3,
                    max_tokens=WRITING_CONFLICT_AI_MAX_TOKENS,
                ),
                WritingConflictSuggestionOutput,
            )
            suggestion_text = output.suggestion.model_dump_json(ensure_ascii=False)
            updated = await self._repo.update_item_suggestion(
                db,
                item_id=iid,
                novel_id=nid,
                status="done",
                confirmation_id=confirmation_uuid,
                ai_suggestion=suggestion_text,
                llm_rationale=output.suggestion.rationale,
                error=None,
            )
            await attach_result_ref(
                db,
                confirmation_id=context_confirmation_id,
                result_type="writing_conflict_item",
                result_id=item_id,
                status="done",
            )
            return updated or item
        except Exception as exc:
            logger.exception("AI conflict suggestion failed")
            updated = await self._repo.update_item_suggestion(
                db,
                item_id=iid,
                novel_id=nid,
                status="failed",
                confirmation_id=confirmation_uuid,
                error=str(exc),
            )
            try:
                await attach_result_ref(
                    db,
                    confirmation_id=context_confirmation_id,
                    result_type="writing_conflict_item",
                    result_id=item_id,
                    status="failed",
                )
            except ValueError:
                logger.exception("Failed to attach AI suggestion result ref")
            return updated or item


def _ai_review_items(
    output: WritingConflictAiReviewRawOutput,
    *,
    check: object,
    confirmation_id: uuid.UUID,
    include_pending_objects: bool,
) -> tuple[list[dict], int]:
    items: list[dict] = []
    discarded_count = 0
    for raw in output.issues:
        try:
            issue = WritingConflictAiReviewIssue.model_validate(raw)
        except ValidationError:
            discarded_count += 1
            continue
        items.append(
            {
                "kind": issue.kind,
                "severity": issue.severity,
                "source_module": "ai",
                "source_type": "llm.soft_conflict",
                "source_id": str(getattr(check, "id", "")),
                "evidence_summary": f"{issue.summary}｜证据：{issue.evidence}",
                "location_json": issue.location_hint or {"target": "ai_review"},
                "is_ai_judgment": True,
                "needs_review": (
                    include_pending_objects or issue.depends_on_pending_objects
                ),
                "confidence": issue.confidence,
                "source_confirmation_id": confirmation_id,
                "llm_rationale": issue.rationale,
                "status": "open",
            }
        )
    return items, discarded_count


def _validate_confirmation_scope(confirmation: object, check: object) -> None:
    options = getattr(confirmation, "compile_options", None) or {}
    confirmed_chapter = options.get("chapter_index")
    check_chapter = getattr(check, "chapter_index", None)
    if check_chapter is not None and confirmed_chapter != check_chapter:
        raise ValueError(
            "context confirmation chapter_index does not match conflict check",
        )

    check_scene = getattr(check, "scene_id", None)
    if check_scene:
        confirmed_scene = options.get("scene_id")
        if str(confirmed_scene or "") != str(check_scene):
            raise ValueError(
                "context confirmation scene_id does not match conflict check",
            )


def _summary_with_ai_review(
    items: list[object],
    existing_summary: dict,
    *,
    status: str,
    discarded_count: int,
) -> dict:
    by_severity: dict[str, int] = {}
    open_high = 0
    ai_count = 0
    for item in items:
        severity = getattr(item, "severity", "info")
        by_severity[severity] = by_severity.get(severity, 0) + 1
        if (
            getattr(item, "severity", None) == "high"
            and getattr(item, "status", None) == "open"
        ):
            open_high += 1
        if getattr(item, "is_ai_judgment", False):
            ai_count += 1
    summary = dict(existing_summary or {})
    summary.update(
        {
            "total": len(items),
            "open_high_count": open_high,
            "by_severity": by_severity,
        }
    )
    summary["ai_review"] = {
        "status": status,
        "item_count": ai_count,
        "discarded_count": discarded_count,
    }
    return summary


def _build_ai_review_prompt(
    *,
    check: object,
    items: list[object],
    context_markdown: str,
) -> str:
    rule_summary = "\n".join(
        f"- {getattr(item, 'kind', '')}: {getattr(item, 'evidence_summary', '')}"
        for item in items
        if not getattr(item, "is_ai_judgment", False)
    )
    scope = getattr(check, "scope", None) or {}
    content_excerpt = scope.get("content_excerpt") or ""
    return (
        "请基于当前 Scene 写作目标和 AI 参考资料，补充判断叙事软冲突。\n\n"
        f"检查范围：第 {getattr(check, 'chapter_index', '-')} 章，"
        f"Scene={getattr(check, 'scene_id', None) or '未指定'}。\n\n"
        "当前正文摘录：\n"
        f"{content_excerpt or '- 无正文摘录'}\n\n"
        "规则层已命中问题：\n"
        f"{rule_summary or '- 无'}\n\n"
        "AI 参考资料：\n"
        f"{context_markdown}\n\n"
        "只输出 JSON，不要输出 Markdown 或解释。格式必须是：\n"
        "{\n"
        "  \"issues\": [\n"
        "    {\n"
        "      \"kind\": \"motivation_gap\",\n"
        "      \"severity\": \"medium\",\n"
        "      \"summary\": \"一句话概括问题\",\n"
        "      \"evidence\": \"正文或上下文中的具体证据\",\n"
        "      \"rationale\": \"为什么这构成软冲突\",\n"
        "      \"location_hint\": {\"chapter_index\": 1, "
        "\"text_quote\": \"可定位短句\"},\n"
        "      \"confidence\": 0.72,\n"
        "      \"depends_on_pending_objects\": false\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "字段取值必须严格使用英文枚举：\n"
        "- kind: motivation_gap, emotion_jump, foreshadowing_misfire, "
        "premature_reveal, implicit_lore_conflict, voice_or_pov_drift, "
        "scene_goal_drift, continuity_soft_risk\n"
        "- severity: high, medium, low\n"
        "- confidence: 0 到 1 之间的数字\n"
        "- depends_on_pending_objects: true 或 false\n"
        "最多输出 2 条 issues。\n"
        "summary/evidence/rationale 各限制 1-2 句。\n"
        "不要展开长段解释；无法确定时输出 {\"issues\": []}。\n"
        "如果没有可报告的软冲突，输出 {\"issues\": []}。"
    )


def _build_ai_suggestion_prompt(
    *,
    check: object,
    item: object,
    items: list[object],
    context_markdown: str,
) -> str:
    related = "\n".join(
        f"- {getattr(entry, 'kind', '')}: {getattr(entry, 'evidence_summary', '')}"
        for entry in items
    )
    return (
        "请只针对下面这一条写作冲突生成可手动采纳的修复建议。\n\n"
        f"检查范围：第 {getattr(check, 'chapter_index', '-')} 章。\n"
        f"目标问题：{getattr(item, 'kind', '')} - "
        f"{getattr(item, 'evidence_summary', '')}\n\n"
        "同次检查问题摘要：\n"
        f"{related or '- 无'}\n\n"
        "AI 参考资料：\n"
        f"{context_markdown}\n\n"
        "只输出 JSON，格式为 {\"suggestion\": {\"strategy\": ..., "
        "\"suggested_text\": ..., \"rationale\": ..., "
        "\"constraints\": [], \"risk_notes\": []}}。\n"
        "strategy/rationale 各 1-2 句。\n"
        "suggested_text 控制在 300-600 字以内。\n"
        "constraints/risk_notes 每项不超过 3 条。"
    )


_AI_REVIEW_SYSTEM_PROMPT = (
    "你是小说写作软冲突审阅器。只报告与当前 Scene 写作目标相关的动机、"
    "情绪、伏笔、揭示、隐含设定、POV 或 Scene 目标漂移问题。不要重复规则层"
    "已经明确列出的问题，除非提供新的叙事角度。不要把缺少信息当作事实错误。"
    "不要输出正史修改指令或一键应用补丁。每条问题必须给出依据、理由、置信度，"
    "依赖待确认对象时 depends_on_pending_objects=true。"
)

_AI_SUGGESTION_SYSTEM_PROMPT = (
    "你是小说写作修复建议助手。只针对单条问题生成可手动采纳的建议。"
    "尊重 Scene 的必须发生和禁止发生，不提前揭示隐藏真相，不引入新的正史事实。"
    "如建议需要新增事实，必须在风险说明中标记需要作者确认。不得输出自动补丁。"
)
