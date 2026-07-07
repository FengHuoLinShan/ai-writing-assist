"""Settings module repositories."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.settings.models import (
    GlobalAuthorPreferences,
    GlobalLLMDefaults,
    ProjectAuthorPreferences,
)

_GLOBAL_LLM_FIELDS: tuple[str, ...] = (
    "provider_id",
    "label",
    "base_url",
    "model",
    "timeout",
    "max_tokens",
    "temperature",
    "top_p",
    "extra",
    "creative_mode",
    "deep_import",
)
_GLOBAL_PREFS_FIELDS: tuple[str, ...] = (
    "daily_goal",
    "editor_font",
    "default_focus_mode",
)
_PROJECT_PREFS_FIELDS: tuple[str, ...] = _GLOBAL_PREFS_FIELDS


class GlobalLLMDefaultsRepository:
    async def get(
        self, db: AsyncSession, owner_id: uuid.UUID
    ) -> GlobalLLMDefaults | None:
        stmt = select(GlobalLLMDefaults).where(GlobalLLMDefaults.owner_id == owner_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, db: AsyncSession, payload: dict) -> GlobalLLMDefaults:
        owner_id = payload["owner_id"]
        existing = await self.get(db, owner_id)
        if existing is None:
            row = GlobalLLMDefaults(**payload)
            db.add(row)
            await db.flush()
            return row
        for f in _GLOBAL_LLM_FIELDS:
            if f in payload:
                setattr(existing, f, payload[f])
        db.add(existing)
        await db.flush()
        return existing


class GlobalAuthorPrefsRepository:
    async def get(
        self, db: AsyncSession, owner_id: uuid.UUID
    ) -> GlobalAuthorPreferences | None:
        stmt = select(GlobalAuthorPreferences).where(
            GlobalAuthorPreferences.owner_id == owner_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, db: AsyncSession, payload: dict) -> GlobalAuthorPreferences:
        owner_id = payload["owner_id"]
        existing = await self.get(db, owner_id)
        if existing is None:
            row = GlobalAuthorPreferences(**payload)
            db.add(row)
            await db.flush()
            return row
        for f in _GLOBAL_PREFS_FIELDS:
            if f in payload:
                setattr(existing, f, payload[f])
        db.add(existing)
        await db.flush()
        return existing


class ProjectAuthorPrefsRepository:
    async def get(
        self, db: AsyncSession, project_id: uuid.UUID
    ) -> ProjectAuthorPreferences | None:
        stmt = select(ProjectAuthorPreferences).where(
            ProjectAuthorPreferences.project_id == project_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, db: AsyncSession, payload: dict) -> ProjectAuthorPreferences:
        project_id = payload["project_id"]
        existing = await self.get(db, project_id)
        if existing is None:
            row = ProjectAuthorPreferences(**payload)
            db.add(row)
            await db.flush()
            return row
        for f in _PROJECT_PREFS_FIELDS:
            if f in payload:
                setattr(existing, f, payload[f])
        db.add(existing)
        await db.flush()
        return existing

    async def reset_field(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        field_name: str,
    ) -> ProjectAuthorPreferences | None:
        if field_name not in _PROJECT_PREFS_FIELDS:
            return None
        existing = await self.get(db, project_id)
        if existing is None:
            row = ProjectAuthorPreferences(project_id=project_id)
            db.add(row)
            await db.flush()
            return row
        setattr(existing, field_name, None)
        db.add(existing)
        await db.flush()
        return existing
