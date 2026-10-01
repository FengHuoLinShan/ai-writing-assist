"""Author-confirmed editorial direction for one project."""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from core.errors import ConflictError
from modules.project.models import Project
from modules.project.services import ProjectService

_KEY = "editorial_brief_v1"


class EditorialBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_readers: str = Field(default="", max_length=500)
    genre_promise: str = Field(default="", max_length=1000)
    goals: list[Annotated[str, Field(max_length=500)]] = Field(
        default_factory=list, max_length=12
    )
    voice: str = Field(default="", max_length=2000)
    preserve: list[Annotated[str, Field(max_length=500)]] = Field(
        default_factory=list, max_length=20
    )
    intentional_choices: list[Annotated[str, Field(max_length=500)]] = Field(
        default_factory=list, max_length=20
    )
    excluded_targets: list[Annotated[str, Field(max_length=256)]] = Field(
        default_factory=list, max_length=200
    )


class EditorialBriefUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    brief: EditorialBrief


async def read_editorial_brief(db, novel_id: str) -> dict:
    await ProjectService().get_project(db, novel_id)
    row = await db.scalar(select(Project).where(Project.id == UUID(novel_id)))
    saved = (row.settings or {}).get(_KEY) or {}
    return {
        "version": int(saved.get("version") or 0),
        "brief": EditorialBrief.model_validate(saved.get("brief") or {}).model_dump(),
    }


async def save_editorial_brief(db, novel_id: str, value: EditorialBriefUpdate) -> dict:
    service = ProjectService()
    service._reject_demo_write()
    await service.get_project(db, novel_id)
    row = await db.scalar(
        select(Project).where(Project.id == UUID(novel_id)).with_for_update()
    )
    saved = (row.settings or {}).get(_KEY) or {}
    current = int(saved.get("version") or 0)
    if value.expected_version != current:
        raise ConflictError("编辑约定已有新版本，请先核对当前内容")
    next_version = current + 1
    row.settings = {
        **(row.settings or {}),
        _KEY: {"version": next_version, "brief": value.brief.model_dump()},
    }
    await db.flush()
    return {"version": next_version, "brief": value.brief.model_dump()}


_WRITING_USE_KEY = "editorial_brief_for_writing_v1"


def _brief_substantive(saved: dict) -> bool:
    """约定是否有实质内容（决定开启开关后是否真正生效）。"""
    brief = EditorialBrief.model_validate(saved.get("brief") or {})
    return bool(
        brief.voice.strip()
        or brief.preserve
        or brief.intentional_choices
        or brief.target_readers.strip()
        or brief.genre_promise.strip()
        or brief.goals
    )


async def read_editorial_brief_for_writing(db, novel_id: str) -> dict | None:
    """作者开启「编辑约定也用于 AI 写作」且约定非空时返回 {version, brief}。

    默认关闭；关闭或约定为空时返回 None，编译层不注入任何 section。
    """
    await ProjectService().get_project(db, novel_id)
    row = await db.scalar(select(Project).where(Project.id == UUID(novel_id)))
    settings = row.settings or {}
    enabled = (settings.get(_WRITING_USE_KEY) or {}).get("enabled") is True
    if not enabled:
        return None
    saved = settings.get(_KEY) or {}
    if not _brief_substantive(saved):
        return None
    return {
        "version": int(saved.get("version") or 0),
        "brief": EditorialBrief.model_validate(saved.get("brief") or {}).model_dump(),
    }


async def read_editorial_brief_writing_toggle(db, novel_id: str) -> dict:
    """读取「也用于 AI 写作」的原始开关值（不叠加约定是否为空）。"""
    await ProjectService().get_project(db, novel_id)
    row = await db.scalar(select(Project).where(Project.id == UUID(novel_id)))
    enabled = ((row.settings or {}).get(_WRITING_USE_KEY) or {}).get("enabled") is True
    return {"enabled": enabled}


async def set_editorial_brief_for_writing(db, novel_id: str, *, enabled: bool) -> dict:
    """切换「编辑约定也用于 AI 写作」；默认关闭，作者显式开启才生效。

    返回的 effective 与 GET 口径一致：开关开启且约定非空。首开时
    不能让界面拿着开启前的旧 effective 误报「约定还是空的」。
    """
    service = ProjectService()
    service._reject_demo_write()
    await service.get_project(db, novel_id)
    row = await db.scalar(
        select(Project).where(Project.id == UUID(novel_id)).with_for_update()
    )
    row.settings = {
        **(row.settings or {}),
        _WRITING_USE_KEY: {"enabled": bool(enabled)},
    }
    await db.flush()
    return {
        "enabled": bool(enabled),
        "effective": bool(enabled) and _brief_substantive(row.settings.get(_KEY) or {}),
    }
