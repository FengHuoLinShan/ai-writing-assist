"""Persistence for project-owned author preference overrides."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.settings_models import ProjectAuthorPreferences

_FIELDS = ("daily_goal", "editor_font", "default_focus_mode")


class ProjectAuthorPrefsRepository:
    async def get(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
    ) -> ProjectAuthorPreferences | None:
        result = await db.execute(
            select(ProjectAuthorPreferences).where(
                ProjectAuthorPreferences.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        db: AsyncSession,
        payload: dict,
    ) -> ProjectAuthorPreferences:
        existing = await self.get(db, payload["project_id"])
        if existing is None:
            existing = ProjectAuthorPreferences(**payload)
        else:
            for field_name in _FIELDS:
                if field_name in payload:
                    setattr(existing, field_name, payload[field_name])
        db.add(existing)
        await db.flush()
        return existing

    async def reset_field(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        field_name: str,
    ) -> ProjectAuthorPreferences | None:
        if field_name not in _FIELDS:
            return None
        existing = await self.get(db, project_id)
        if existing is None:
            existing = ProjectAuthorPreferences(project_id=project_id)
        else:
            setattr(existing, field_name, None)
        db.add(existing)
        await db.flush()
        return existing
