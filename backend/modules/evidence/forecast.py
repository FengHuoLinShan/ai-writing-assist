"""Read-only context and index readiness; retrieval remains an explicit operation."""

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ConflictError
from modules.assistant.contracts import AssistantOperation, ForecastDomainFact

INSTRUCTIONS = {
    "evidence.next_query.v1": (
        "指出当前问题缺少的解释、反证或原文证据，给一"
        "个范围明确的下一查询。相似命中不等于答案，不"
        "自动联网。"
    )
}


async def inspect(db, novel_id, focus, excluded):
    from modules.evidence.indexing.index_state import RagIndexStateService

    if focus.page != "rag" or excluded:
        return []
    status = await RagIndexStateService().summary(db, novel_id)
    working = status["by_content_mode"]["working"]
    return [
        ForecastDomainFact(
            capability_id="evidence.freshness_ready.v1",
            subject="working_index",
            title="先核对预备资料的新鲜性",
            summary=f"索引回执中有 {working[('fresh')]} 项已同步、{
                working[('stale')]
            } 项尚未同步。没有回执的资料仍未验证。",
            source=status,
            scope_label="已有索引回执，不代表已索引全部正文",
            target={"page": "rag"},
            unknowns=["查询集合新增会改变答案；旧命中和缓存时间不能证明来源仍有效。"],
        ),
        ForecastDomainFact(
            capability_id="evidence.context_gap.v1",
            subject="confirmation",
            title="为本次操作确认资料范围",
            summary="已有资料确认将按原范围重新物化。"
            if focus.context_confirmation_id
            else "尚未指定本次资料确认，先选择必需资料与排除项。",
            source={
                "confirmation_id": str(focus.context_confirmation_id)
                if focus.context_confirmation_id
                else None,
                "consumer_action": focus.context_confirmation_action,
            },
            scope_label="本次操作的确认身份；容量与具体缺口由原确认界面核对",
            target={"page": "rag"},
        ),
    ]


async def prepare_direction(db, novel_id, ctx, direction):
    return "evidence.focused_search", {
        "root": direction["title"],
        "question": direction["proposal"],
    }


class FocusedChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=2000)


async def _prepare(db, novel_id, args, *, context=None):
    from modules.evidence.compilation.focused_tasks import (
        FocusedSearchSubmit,
        prepare_focused_search,
    )

    if (
        context is None
        or context.work.context_confirmation_id
        or context.work.excluded_targets
    ):
        raise ConflictError("原确认或排除范围请在资料选择页内继续补查")
    data = FocusedSearchSubmit(
        novel_id=novel_id,
        roots=[{"name": args.root}],
        question=args.question,
        content_mode="working",
        chapter_to=context.work.chapter_index,
        chapter_index=context.work.chapter_index,
        scene_id=str(context.work.scene_id) if context.work.scene_id else None,
        consumer="writing" if context.work.draft_id else "author",
    )
    request, snapshot = await prepare_focused_search(db, data)
    return {
        "title": "按所选问题补查资料",
        "request": request.model_dump(mode="json"),
        "snapshot": snapshot,
        "after": {
            "问题": args.question,
            "线索": args.root,
            "截止章节": context.work.chapter_index or "当前作品全部保存正文",
        },
        "effect": "仅检索原作品资料，保留边界与实际遗漏，不联网、不采用或修改正文。",
    }


async def _apply(db, novel_id, args, preview, *, context=None):
    from modules.evidence.compilation.focused_contracts import FocusedEvidenceRequest
    from modules.evidence.compilation.focused_tasks import _enqueue

    fresh = await _prepare(db, novel_id, args, context=context)
    if fresh != preview:
        raise ConflictError("资料来源或检索配置已变化，请重新核对")
    result = await _enqueue(
        db, FocusedEvidenceRequest.model_validate(preview["request"]), preview["snapshot"]
    )
    return {
        "type": "evidence_focused_search",
        "id": result["task_id"],
        "task_id": result["task_id"],
        "label": "已提交所选资料补查",
    }


OPERATIONS = {
    "evidence.focused_search": AssistantOperation(
        "按明确问题补查当前授权作品资料", FocusedChoice, _prepare, _apply
    )
}
