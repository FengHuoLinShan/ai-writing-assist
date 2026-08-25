"""Novel-scoped persistence seams for Story assets.

Repositories never accept an unscoped primary-key lookup.  Every read and
write carries ``novel_id`` so a caller cannot accidentally turn a stale asset
ID into a cross-project read.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.models import (
    CharacterCard,
    CharacterCardRevision,
    SceneScriptFile,
    SceneScriptRevision,
)


class CharacterCardRepository:
    async def get(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        card_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> CharacterCard | None:
        stmt = select(CharacterCard).where(
            CharacterCard.novel_id == novel_id,
            CharacterCard.id == card_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def get_by_character(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
        character_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> CharacterCard | None:
        stmt = select(CharacterCard).where(
            CharacterCard.novel_id == novel_id,
            CharacterCard.scene_id == scene_id,
            CharacterCard.character_id == character_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        scene_id: uuid.UUID | None = None,
        character_ids: list[uuid.UUID] | None = None,
    ) -> list[CharacterCard]:
        stmt = select(CharacterCard).where(CharacterCard.novel_id == novel_id)
        if scene_id is not None:
            stmt = stmt.where(CharacterCard.scene_id == scene_id)
        if character_ids:
            stmt = stmt.where(CharacterCard.character_id.in_(character_ids))
        stmt = stmt.order_by(CharacterCard.created_at, CharacterCard.id)
        return list((await db.execute(stmt)).scalars().all())

    async def create(self, db: AsyncSession, card: CharacterCard) -> CharacterCard:
        db.add(card)
        await db.flush()
        return card


class CharacterCardRevisionRepository:
    async def get_many(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        revision_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, CharacterCardRevision]:
        if not revision_ids:
            return {}
        stmt = select(CharacterCardRevision).where(
            CharacterCardRevision.novel_id == novel_id,
            CharacterCardRevision.id.in_(revision_ids),
        )
        revisions = (await db.execute(stmt)).scalars().all()
        return {revision.id: revision for revision in revisions}

    async def get(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        revision_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> CharacterCardRevision | None:
        stmt = select(CharacterCardRevision).where(
            CharacterCardRevision.novel_id == novel_id,
            CharacterCardRevision.id == revision_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def list_for_card(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        card_id: uuid.UUID,
    ) -> list[CharacterCardRevision]:
        stmt = (
            select(CharacterCardRevision)
            .where(
                CharacterCardRevision.novel_id == novel_id,
                CharacterCardRevision.card_id == card_id,
            )
            .order_by(
                CharacterCardRevision.version_number.desc(),
                CharacterCardRevision.id.desc(),
            )
        )
        return list((await db.execute(stmt)).scalars().all())

    async def get_latest_version(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        card_id: uuid.UUID,
    ) -> int:
        value = (
            await db.execute(
                select(func.max(CharacterCardRevision.version_number)).where(
                    CharacterCardRevision.novel_id == novel_id,
                    CharacterCardRevision.card_id == card_id,
                )
            )
        ).scalar()
        return int(value or 0)

    async def create(
        self,
        db: AsyncSession,
        revision: CharacterCardRevision,
    ) -> CharacterCardRevision:
        db.add(revision)
        await db.flush()
        return revision


class SceneScriptFileRepository:
    async def get(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        file_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> SceneScriptFile | None:
        stmt = select(SceneScriptFile).where(
            SceneScriptFile.novel_id == novel_id,
            SceneScriptFile.id == file_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def get_by_key(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
        file_key: str,
        *,
        for_update: bool = False,
    ) -> SceneScriptFile | None:
        stmt = select(SceneScriptFile).where(
            SceneScriptFile.novel_id == novel_id,
            SceneScriptFile.scene_id == scene_id,
            SceneScriptFile.file_key == file_key,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def list_for_scene(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
    ) -> list[SceneScriptFile]:
        stmt = (
            select(SceneScriptFile)
            .where(
                SceneScriptFile.novel_id == novel_id,
                SceneScriptFile.scene_id == scene_id,
            )
            .order_by(SceneScriptFile.file_key, SceneScriptFile.id)
        )
        return list((await db.execute(stmt)).scalars().all())

    async def create(self, db: AsyncSession, file: SceneScriptFile) -> SceneScriptFile:
        db.add(file)
        await db.flush()
        return file


class SceneScriptRevisionRepository:
    async def get_many(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        revision_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, SceneScriptRevision]:
        if not revision_ids:
            return {}
        stmt = select(SceneScriptRevision).where(
            SceneScriptRevision.novel_id == novel_id,
            SceneScriptRevision.id.in_(revision_ids),
        )
        revisions = (await db.execute(stmt)).scalars().all()
        return {revision.id: revision for revision in revisions}

    async def get(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        revision_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> SceneScriptRevision | None:
        stmt = select(SceneScriptRevision).where(
            SceneScriptRevision.novel_id == novel_id,
            SceneScriptRevision.id == revision_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def list_for_file(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> list[SceneScriptRevision]:
        stmt = (
            select(SceneScriptRevision)
            .where(
                SceneScriptRevision.novel_id == novel_id,
                SceneScriptRevision.file_id == file_id,
            )
            .order_by(
                SceneScriptRevision.version_number.desc(),
                SceneScriptRevision.id.desc(),
            )
        )
        return list((await db.execute(stmt)).scalars().all())

    async def get_latest_version(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> int:
        value = (
            await db.execute(
                select(func.max(SceneScriptRevision.version_number)).where(
                    SceneScriptRevision.novel_id == novel_id,
                    SceneScriptRevision.file_id == file_id,
                )
            )
        ).scalar()
        return int(value or 0)

    async def create(
        self,
        db: AsyncSession,
        revision: SceneScriptRevision,
    ) -> SceneScriptRevision:
        db.add(revision)
        await db.flush()
        return revision
