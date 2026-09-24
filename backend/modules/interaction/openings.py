"""Reusable RP entry cards; never generate or overwrite source-author content."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.interaction.models import InteractionOpening
from modules.interaction.schemas import JourneyCreateRequest, JourneySourceSetup
from modules.interaction.source_service import InteractionSourceService
from modules.project.facade import require_active_project_exclusive
from modules.world.facade import read_world_object_image
from shared.utils import parse_uuid


class OpeningImageReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: UUID
    image_version: UUID
    reviewed_for_anchor: Literal[True]


class OpeningSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: datetime | None = None
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    experience_kind: Literal[
        "exploration", "source_character", "original_character", "event", "scene"
    ]
    source_setup: JourneySourceSetup
    opening_text: str = Field(min_length=1, max_length=8000)
    image_reference: OpeningImageReference | None = None
    archived: bool = False

    @field_validator("title", "description", "opening_text")
    @classmethod
    def nonblank(cls, value):
        value = value.replace("\x00", "").strip()
        if not value:
            raise ValueError("内容不能为空")
        return value


class OpeningStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=128)


class InteractionOpeningService:
    def __init__(self):
        self.sources = InteractionSourceService()

    async def _owned(self, db, opening_id):
        row = await db.get(InteractionOpening, parse_uuid(opening_id, "opening_id"))
        if row is None:
            raise NotFoundError("开局不存在")
        await self.sources.require_author_project(db, str(row.novel_id))
        return row

    def response(self, row, source):
        _, anchor, player, _ = self.sources._prepare_setup_for_revision(
            source, JourneySourceSetup.model_validate(row.source_setup)
        )
        return {
            "id": str(row.id),
            "project_id": str(row.novel_id),
            "source_revision_id": str(row.source_revision_id),
            "source_title": source.title,
            "title": row.title,
            "description": row.description,
            "experience_kind": row.experience_kind,
            "player_label": player.get("label") or player.get("name"),
            "progress_label": anchor["label"],
            "source_setup": row.source_setup,
            "opening_text": row.opening_text,
            "has_image": row.image_reference is not None,
            "archived": row.archived,
            "updated_at": row.updated_at,
            "curation": "开局由作者或代理整理，进入后的回应由模型实时生成",
        }

    async def list(self, db, project_id=None):
        sources = await self.sources.list_sources(db)
        project_ids = [
            parse_uuid(p.project_id, "project_id")
            for p in sources.projects
            if project_id is None or p.project_id == project_id
        ]
        if project_id:
            await self.sources.require_author_project(db, project_id)
        if not project_ids:
            return {"items": []}
        rows = list(
            (
                await db.scalars(
                    select(InteractionOpening)
                    .where(
                        InteractionOpening.novel_id.in_(project_ids),
                        InteractionOpening.archived.is_(False),
                    )
                    .order_by(InteractionOpening.created_at, InteractionOpening.id)
                    .limit(100)
                )
            ).all()
        )
        items = []
        for row in rows:
            revision = await self.sources._owned_revision(db, str(row.source_revision_id))
            if revision.status == "ready":
                items.append(self.response(row, revision))
        return {"items": items}

    async def save(self, db, project_id, opening_id, data: OpeningSaveRequest):
        await self.sources.require_author_project(db, project_id)
        await require_active_project_exclusive(db, project_id)
        revision, anchor, _player, _references = await self.sources.prepare_setup(
            db, data.source_setup
        )
        if str(revision.source_novel_id) != project_id:
            raise ValidationError("开局资料必须属于当前作品")
        await self.sources.validate_frozen_source_candidate(
            db, revision_id=str(revision.id)
        )
        if data.image_reference:
            image = data.image_reference
            reference = next(
                (
                    r
                    for r in revision.reference_manifest
                    if r["target_id"] == str(image.entity_id)
                ),
                None,
            )
            if reference is None or not self.sources.reference_visible(
                revision, reference, anchor
            ):
                raise ValidationError("配图对象尚未在开局进度登场")
            await read_world_object_image(
                db,
                novel_id=project_id,
                entity_id=str(image.entity_id),
                expected_version=str(image.image_version),
            )
        payload = data.model_dump(mode="json", exclude={"expected_updated_at"})
        row = await db.get(InteractionOpening, parse_uuid(opening_id, "opening_id"))
        if row is not None:
            if str(row.novel_id) != project_id:
                raise NotFoundError("开局不存在")
            if all(getattr(row, key) == value for key, value in payload.items()):
                return self.response(row, revision)
            if row.updated_at != data.expected_updated_at:
                raise ConflictError("开局已在别处更新，请刷新后重试")
        else:
            if data.expected_updated_at is not None:
                raise ConflictError("开局已变化，请刷新后重试")
            row = InteractionOpening(
                id=parse_uuid(opening_id, "opening_id"),
                novel_id=parse_uuid(project_id, "project_id"),
            )
            db.add(row)
        for key, value in payload.items():
            setattr(row, key, value)
        row.source_revision_id = revision.id
        await db.flush()
        return self.response(row, revision)

    async def image(self, db, opening_id):
        row = await self._owned(db, opening_id)
        if row.archived or not row.image_reference:
            raise NotFoundError("开局配图不可用")
        revision, anchor, _player, _references = await self.sources.prepare_setup(
            db, JourneySourceSetup.model_validate(row.source_setup)
        )
        image = OpeningImageReference.model_validate(row.image_reference)
        reference = next(
            (
                r
                for r in revision.reference_manifest
                if r["target_id"] == str(image.entity_id)
            ),
            None,
        )
        if reference is None or not self.sources.reference_visible(
            revision, reference, anchor
        ):
            raise NotFoundError("开局配图不可用")
        return await read_world_object_image(
            db,
            novel_id=str(row.novel_id),
            entity_id=str(image.entity_id),
            expected_version=str(image.image_version),
        )

    async def start(self, db, opening_id, data: OpeningStartRequest):
        from modules.interaction.services import InteractionService

        row = await self._owned(db, opening_id)
        if row.archived:
            raise NotFoundError("开局已归档")
        return await InteractionService().create_journey(
            db,
            JourneyCreateRequest(
                opening_text=row.opening_text,
                source_setup=JourneySourceSetup.model_validate(row.source_setup),
                idempotency_key=data.idempotency_key,
            ),
        )
