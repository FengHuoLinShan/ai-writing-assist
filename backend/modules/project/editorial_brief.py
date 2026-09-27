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
