"""Author-confirmed planning assets through the existing Story services."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.assistant.contracts import AssistantOperation
from modules.story.outline_state.schemas import OutlineArcCreate, PlotThreadCreate
from modules.story.outline_state.services import OutlineArcService, PlotThreadService


class NewThread(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    thread_type: str = Field(min_length=1, max_length=32)
    summary: str = Field(default="", max_length=12000)
    visible_goal: str = Field(default="", max_length=12000)
    hidden_truth: str = Field(default="", max_length=12000)
    start_chapter: int | None = Field(default=None, ge=1, le=2147483647)
    planned_payoff_chapter: int | None = Field(default=None, ge=1, le=2147483647)


class NewArc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=255)
    start_chapter: int | None = Field(default=None, ge=1, le=2147483647)
    end_chapter: int | None = Field(default=None, ge=1, le=2147483647)
    arc_goal: str = Field(default="", max_length=12000)
    core_conflict: str = Field(default="", max_length=12000)
    midpoint_turn: str = Field(default="", max_length=12000)
    climax: str = Field(default="", max_length=12000)
    result: str = Field(default="", max_length=12000)
    next_hook: str = Field(default="", max_length=12000)
    related_thread_ids: list[UUID] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def ordered_chapters(self):
        if (
            self.start_chapter
            and self.end_chapter
            and self.end_chapter < self.start_chapter
        ):
            raise ValueError("篇章结束位置不能早于开始位置")
        return self


def _provenance(context):
    return {
        "source": "assistant",
        "assistant_run_id": context.run_id,
        "approved_by": context.owner_id,
        "user_edited": True,
        "needs_review": False,
    }


async def _thread_preview(db, novel_id, args, *, context=None):
    return {
        "title": args.name,
        "after": args.model_dump(mode="json"),
        "effect": "保存可编辑剧情线规划，不自动创建正文或改变世界事实",
    }


async def _thread_apply(db, novel_id, args, preview, *, context=None):
    result = await PlotThreadService().create(
        db,
        novel_id,
        PlotThreadCreate(
            **args.model_dump(mode="json"),
            provenance_meta=_provenance(context),
        ),
    )
    return {"type": "plot_thread", "id": result.id, "label": "已保存剧情线规划"}


async def _arc_preview(db, novel_id, args, *, context=None):
    from modules.assistant.facade import require_operation_targets

    await require_operation_targets(
        db, novel_id, context, [("plot_thread", key) for key in args.related_thread_ids]
    )
    threads = [
        await PlotThreadService().get(db, str(key), novel_id=novel_id)
        for key in args.related_thread_ids
    ]
    return {
        "title": args.title,
        "after": args.model_dump(mode="json"),
        "related_threads": [
            {"id": thread.id, "name": thread.name, "updated_at": str(thread.updated_at)}
            for thread in threads
        ],
        "effect": "保存篇章规划并关联已有剧情线，不替换场景或正文",
    }


async def _arc_apply(db, novel_id, args, preview, *, context=None):
    from core.errors import ConflictError

    if await _arc_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("关联剧情线已变化，请重新查看方案")
    result = await OutlineArcService().create(
        db,
        novel_id,
        OutlineArcCreate(
            **args.model_dump(mode="json"),
            provenance_meta=_provenance(context),
        ),
    )
    return {"type": "outline_arc", "id": result.id, "label": "已保存篇章规划"}


OPERATIONS = {
    "story.create_thread": AssistantOperation(
        "规划新剧情线", NewThread, _thread_preview, _thread_apply
    ),
    "story.create_arc": AssistantOperation(
        "规划新篇章", NewArc, _arc_preview, _arc_apply
    ),
}
