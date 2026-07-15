"""Versioned World Bible page templates and draft application."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError
from modules.world.models import (
    WorldBiblePageTemplate,
    WorldBiblePageTemplateRevision,
)
from modules.world.schemas import (
    WorldBibleApplyTemplateRequest,
    WorldBiblePageDraftResponse,
    WorldBiblePageTemplateCreate,
    WorldBiblePageTemplateResponse,
    WorldBiblePageTemplateRevisionResponse,
    WorldBiblePageTemplateUpdate,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from shared.utils import parse_uuid

BUILTIN_PAGE_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "template_key": "world_basic",
        "name": "世界基本背景",
        "category_key_hint": "background",
        "default_sections_json": [
            {
                "section_id": "overview_notes",
                "section_type": "markdown",
                "title": "时代与文明",
                "body_markdown": "",
                "sort_order": 10,
                "linked_asset_ref_hashes": [],
                "projection_policy": "eligible",
                "sensitivity_hint": "author_safe",
            }
        ],
    },
    {
        "template_key": "species_index",
        "name": "种族",
        "category_key_hint": "species",
        "default_sections_json": [],
    },
    {
        "template_key": "factions_index",
        "name": "势力",
        "category_key_hint": "faction",
        "default_sections_json": [],
    },
    {
        "template_key": "locations_index",
        "name": "地点与地图",
        "category_key_hint": "location",
        "default_sections_json": [],
    },
    {
        "template_key": "rules_index",
        "name": "规则体系",
        "category_key_hint": "rule",
        "default_sections_json": [],
    },
    {
        "template_key": "secrets_index",
        "name": "秘密与伏笔",
        "category_key_hint": "secret",
        "default_sections_json": [],
    },
)
BUILTIN_PAGE_TEMPLATE_KEYS = frozenset(
    item["template_key"] for item in BUILTIN_PAGE_TEMPLATES
)


class WorldBiblePageTemplateService:
    def __init__(
        self,
        lifecycle_service: WorldBibleLifecycleService | None = None,
    ) -> None:
        self._lifecycle = lifecycle_service or WorldBibleLifecycleService()

    async def list_templates(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        include_archived: bool = False,
    ) -> list[WorldBiblePageTemplateResponse]:
        nid = parse_uuid(novel_id, "novel_id")
        stmt = select(WorldBiblePageTemplate).where(
            WorldBiblePageTemplate.novel_id == nid
        )
        if not include_archived:
            stmt = stmt.where(WorldBiblePageTemplate.status == "active")
        result = await db.execute(
            stmt.order_by(
                WorldBiblePageTemplate.name,
                WorldBiblePageTemplate.template_key,
            )
        )
        custom = [
            WorldBiblePageTemplateResponse.model_validate(item)
            for item in result.scalars()
        ]
        builtin = [
            self._builtin_response(novel_id, item)
            for item in BUILTIN_PAGE_TEMPLATES
        ]
        return [*builtin, *custom]

    async def create_template(
        self,
        db: AsyncSession,
        data: WorldBiblePageTemplateCreate,
    ) -> WorldBiblePageTemplateResponse:
        nid = parse_uuid(data.novel_id, "novel_id")
        if data.template_key in BUILTIN_PAGE_TEMPLATE_KEYS:
            raise ConflictError("Built-in World Bible page template keys are reserved")
        existing = await db.scalar(
            select(WorldBiblePageTemplate.id).where(
                WorldBiblePageTemplate.novel_id == nid,
                WorldBiblePageTemplate.template_key == data.template_key,
            )
        )
        if existing is not None:
            raise ConflictError("World Bible page template key already exists")
        if data.category_key_hint:
            await self._lifecycle.ensure_category_key(
                db,
                data.novel_id,
                data.category_key_hint,
            )
        template = WorldBiblePageTemplate(
            novel_id=nid,
            template_key=data.template_key,
            name=data.name,
            description=data.description,
            category_key_hint=data.category_key_hint,
            sections_schema_json=data.sections_schema_json,
            default_sections_json=self._lifecycle.serialize_sections(
                data.default_sections_json
            ),
            validation_rules_json=data.validation_rules_json,
            version_number=1,
            status="active",
            created_by=data.created_by,
            updated_by=data.created_by,
        )
        db.add(template)
        await db.flush()
        await self._add_revision(
            db,
            template,
            revision_reason="create",
            created_by=data.created_by,
        )
        await db.flush()
        return WorldBiblePageTemplateResponse.model_validate(template)

    async def update_template(
        self,
        db: AsyncSession,
        novel_id: str,
        template_id: str,
        data: WorldBiblePageTemplateUpdate,
    ) -> WorldBiblePageTemplateResponse:
        template = await self._get_template(
            db,
            novel_id,
            template_id,
            for_update=True,
        )
        if template.version_number != data.base_version_number:
            raise ConflictError("World Bible page template version conflict")
        payload = data.model_dump(
            mode="json",
            exclude_unset=True,
            exclude={"base_version_number"},
        )
        if payload.get("category_key_hint"):
            await self._lifecycle.ensure_category_key(
                db,
                novel_id,
                payload["category_key_hint"],
            )
        changed = any(getattr(template, key) != value for key, value in payload.items())
        if not changed:
            return WorldBiblePageTemplateResponse.model_validate(template)
        for key, value in payload.items():
            setattr(template, key, value)
        template.version_number += 1
        await self._add_revision(
            db,
            template,
            revision_reason="update",
            created_by=data.updated_by,
        )
        await db.flush()
        return WorldBiblePageTemplateResponse.model_validate(template)

    async def list_revisions(
        self,
        db: AsyncSession,
        novel_id: str,
        template_id: str,
    ) -> list[WorldBiblePageTemplateRevisionResponse]:
        template = await self._get_template(db, novel_id, template_id)
        result = await db.execute(
            select(WorldBiblePageTemplateRevision)
            .where(
                WorldBiblePageTemplateRevision.novel_id == template.novel_id,
                WorldBiblePageTemplateRevision.template_id == template.id,
            )
            .order_by(WorldBiblePageTemplateRevision.version_number.desc())
        )
        return [
            WorldBiblePageTemplateRevisionResponse.model_validate(item)
            for item in result.scalars().all()
        ]

    async def restore_revision(
        self,
        db: AsyncSession,
        novel_id: str,
        template_id: str,
        version_number: int,
        *,
        restored_by: str | None = None,
    ) -> WorldBiblePageTemplateResponse:
        template = await self._get_template(
            db,
            novel_id,
            template_id,
            for_update=True,
        )
        revision = await db.scalar(
            select(WorldBiblePageTemplateRevision).where(
                WorldBiblePageTemplateRevision.novel_id == template.novel_id,
                WorldBiblePageTemplateRevision.template_id == template.id,
                WorldBiblePageTemplateRevision.version_number == version_number,
            )
        )
        if revision is None:
            raise NotFoundError("World Bible page template revision not found")
        snapshot = dict(revision.snapshot_json or {})
        for key in (
            "name",
            "description",
            "category_key_hint",
            "sections_schema_json",
            "default_sections_json",
            "validation_rules_json",
            "status",
        ):
            setattr(template, key, snapshot.get(key))
        template.version_number += 1
        template.updated_by = restored_by
        await self._add_revision(
            db,
            template,
            revision_reason="restore",
            created_by=restored_by,
        )
        await db.flush()
        return WorldBiblePageTemplateResponse.model_validate(template)

    async def apply_to_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        draft_id: str,
        data: WorldBibleApplyTemplateRequest,
    ) -> WorldBiblePageDraftResponse:
        draft = await self._lifecycle.get_draft_model(
            db,
            novel_id,
            draft_id,
            for_update=True,
        )
        template = await self._template_payload(
            db,
            novel_id,
            data.template_key,
            data.template_version,
        )
        defaults = list(template["default_sections_json"])
        if data.replace_sections:
            sections = defaults
        else:
            existing = {item.get("section_id") for item in draft.sections_json or []}
            sections = [*list(draft.sections_json or [])]
            sections.extend(
                item for item in defaults if item.get("section_id") not in existing
            )
        self._lifecycle.validate_section_refs(sections, draft.linked_asset_refs_json)
        draft.sections_json = sections
        draft.template_key = template["template_key"]
        draft.template_version = int(template["version_number"])
        draft.updated_by = data.updated_by
        await db.flush()
        await self._lifecycle.mark_draft_context_changed(
            db,
            draft,
            reason="world_bible_draft_template_applied",
        )
        return WorldBiblePageDraftResponse.model_validate(draft)

    async def _template_payload(
        self,
        db: AsyncSession,
        novel_id: str,
        template_key: str,
        version_number: int | None,
    ) -> dict[str, Any]:
        builtin = next(
            (
                item
                for item in BUILTIN_PAGE_TEMPLATES
                if item["template_key"] == template_key
            ),
            None,
        )
        if builtin is not None:
            if version_number not in {None, 1}:
                raise NotFoundError("Built-in World Bible template version not found")
            return {**builtin, "version_number": 1}
        nid = parse_uuid(novel_id, "novel_id")
        template = await db.scalar(
            select(WorldBiblePageTemplate).where(
                WorldBiblePageTemplate.novel_id == nid,
                WorldBiblePageTemplate.template_key == template_key,
                WorldBiblePageTemplate.status == "active",
            )
        )
        if template is None:
            raise NotFoundError("World Bible page template not found")
        if version_number is None or version_number == template.version_number:
            return self._snapshot(template)
        revision = await db.scalar(
            select(WorldBiblePageTemplateRevision).where(
                WorldBiblePageTemplateRevision.novel_id == nid,
                WorldBiblePageTemplateRevision.template_id == template.id,
                WorldBiblePageTemplateRevision.version_number == version_number,
            )
        )
        if revision is None:
            raise NotFoundError("World Bible page template revision not found")
        return dict(revision.snapshot_json or {})

    async def _get_template(
        self,
        db: AsyncSession,
        novel_id: str,
        template_id: str,
        *,
        for_update: bool = False,
    ) -> WorldBiblePageTemplate:
        nid = parse_uuid(novel_id, "novel_id")
        tid = parse_uuid(template_id, "template_id")
        stmt = select(WorldBiblePageTemplate).where(
            WorldBiblePageTemplate.id == tid,
            WorldBiblePageTemplate.novel_id == nid,
        )
        if for_update:
            stmt = stmt.with_for_update()
        template = await db.scalar(stmt)
        if template is None:
            raise NotFoundError("World Bible page template not found")
        return template

    async def _add_revision(
        self,
        db: AsyncSession,
        template: WorldBiblePageTemplate,
        *,
        revision_reason: str,
        created_by: str | None,
    ) -> None:
        snapshot = self._snapshot(template)
        content_hash = hashlib.sha256(
            json.dumps(
                snapshot,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        db.add(
            WorldBiblePageTemplateRevision(
                novel_id=template.novel_id,
                template_id=template.id,
                version_number=template.version_number,
                snapshot_json=snapshot,
                content_hash=content_hash,
                revision_reason=revision_reason,
                created_by=created_by,
            )
        )

    @staticmethod
    def _snapshot(template: WorldBiblePageTemplate) -> dict[str, Any]:
        return {
            "template_key": template.template_key,
            "name": template.name,
            "description": template.description,
            "category_key_hint": template.category_key_hint,
            "sections_schema_json": template.sections_schema_json,
            "default_sections_json": template.default_sections_json,
            "validation_rules_json": template.validation_rules_json,
            "version_number": template.version_number,
            "status": template.status,
        }

    @staticmethod
    def _builtin_response(
        novel_id: str,
        item: dict[str, Any],
    ) -> WorldBiblePageTemplateResponse:
        return WorldBiblePageTemplateResponse(
            id=f"builtin:{item['template_key']}",
            novel_id=novel_id,
            template_key=item["template_key"],
            name=item["name"],
            category_key_hint=item.get("category_key_hint"),
            default_sections_json=item.get("default_sections_json") or [],
            sections_schema_json={},
            validation_rules_json={},
            version_number=1,
            status="active",
            builtin=True,
        )


__all__ = [
    "BUILTIN_PAGE_TEMPLATE_KEYS",
    "BUILTIN_PAGE_TEMPLATES",
    "WorldBiblePageTemplateService",
]
