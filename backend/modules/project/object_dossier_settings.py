"""Project-owned read policy for author-valid World object intervals."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError
from modules.project.models import Project
from modules.project.services import ProjectService

_KEY = "world_object_dossier_v1"


class ObjectDossierSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    allow_story_override: bool


async def read_object_dossier_settings(
    db: AsyncSession, project_id: str
) -> dict[str, bool | int]:
    service = ProjectService()
    await service.get_project(db, project_id)
    row = await db.scalar(select(Project).where(Project.id == UUID(project_id)))
    saved = (row.settings or {}).get(_KEY) or {}
    return {
        "version": int(saved.get("version") or 0),
        "allow_story_override": saved.get("allow_story_override") is True,
    }


async def update_object_dossier_settings(
    db: AsyncSession, project_id: str, data: ObjectDossierSettingsUpdate
) -> dict[str, bool | int]:
    service = ProjectService()
    service._reject_demo_write()
    await service.get_project(db, project_id)
    row = await db.scalar(
        select(Project).where(Project.id == UUID(project_id)).with_for_update()
    )
    settings = dict(row.settings or {})
    saved = settings.get(_KEY) or {}
    version = int(saved.get("version") or 0)
    if data.expected_version != version:
        raise ConflictError("对象有效期设置已变化，请先读取当前设置")
    next_state = {
        "version": version + 1,
        "allow_story_override": data.allow_story_override,
    }
    row.settings = {**settings, _KEY: next_state}
    await db.flush()
    return next_state
