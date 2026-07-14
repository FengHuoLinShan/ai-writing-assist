"""World Bible categories, working drafts, publish, and revision restore."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.map_models import MapFact
from modules.world.models import (
    CoreEntity,
    EntityRelation,
    WorldBibleCategory,
    WorldBiblePage,
    WorldBiblePageDraft,
    WorldBiblePageRevision,
)
from modules.world.schemas import (
    WorldBibleCategoryCreate,
    WorldBibleCategoryResponse,
    WorldBibleCategoryUpdate,
    WorldBiblePageDraftCreate,
    WorldBiblePageDraftResponse,
    WorldBiblePageDraftUpdate,
    WorldBiblePageResponse,
    WorldBiblePageRevisionResponse,
)
from shared.utils import parse_uuid

BUILTIN_WORLD_BIBLE_CATEGORIES: tuple[dict[str, Any], ...] = (
    {
        "category_key": "background",
        "name": "世界背景",
        "description": "时代、文明与整体背景",
        "color": "#2563EB",
        "icon": "背景",
        "sort_order": 10,
    },
    {
        "category_key": "species",
        "name": "种族",
        "description": "种族、物种与群体",
        "color": "#059669",
        "icon": "种族",
        "sort_order": 20,
    },
    {
        "category_key": "faction",
        "name": "势力",
        "description": "组织、国家与阵营",
        "color": "#7C3AED",
        "icon": "势力",
        "sort_order": 30,
    },
    {
        "category_key": "location",
        "name": "地点",
        "description": "地点、区域与地图",
        "color": "#D97706",
        "icon": "地点",
        "sort_order": 40,
    },
    {
        "category_key": "rule",
        "name": "规则",
        "description": "世界规则、禁忌与力量边界",
        "color": "#DC2626",
        "icon": "规则",
        "sort_order": 50,
    },
    {
        "category_key": "secret",
        "name": "秘密",
        "description": "秘密、伏笔与隐藏真相",
        "color": "#9333EA",
        "icon": "秘密",
        "sort_order": 60,
    },
    {
        "category_key": "custom",
        "name": "自定义",
        "description": "未归入固定类别的作者页面",
        "color": "#64748B",
        "icon": "自定",
        "sort_order": 90,
    },
)
_BUILTIN_KEYS = frozenset(item["category_key"] for item in BUILTIN_WORLD_BIBLE_CATEGORIES)
logger = logging.getLogger(__name__)


class WorldBibleLifecycleService:
    async def list_categories(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        include_archived: bool = False,
    ) -> list[WorldBibleCategoryResponse]:
        nid = parse_uuid(novel_id, "novel_id")
        stmt = select(WorldBibleCategory).where(WorldBibleCategory.novel_id == nid)
        if not include_archived:
            stmt = stmt.where(WorldBibleCategory.status == "active")
        result = await db.execute(
            stmt.order_by(WorldBibleCategory.sort_order, WorldBibleCategory.name)
        )
        custom = [
            WorldBibleCategoryResponse.model_validate(item)
            for item in result.scalars().all()
        ]
        builtin = [
            WorldBibleCategoryResponse(
                id=f"builtin:{item['category_key']}",
                novel_id=novel_id,
                status="active",
                builtin=True,
                **item,
            )
            for item in BUILTIN_WORLD_BIBLE_CATEGORIES
        ]
        return sorted([*builtin, *custom], key=lambda item: (item.sort_order, item.name))

    async def create_category(
        self,
        db: AsyncSession,
        data: WorldBibleCategoryCreate,
    ) -> WorldBibleCategoryResponse:
        nid = parse_uuid(data.novel_id, "novel_id")
        if data.category_key in _BUILTIN_KEYS:
            raise ConflictError("Built-in World Bible category keys are reserved")
        existing = await db.scalar(
            select(WorldBibleCategory.id).where(
                WorldBibleCategory.novel_id == nid,
                WorldBibleCategory.category_key == data.category_key,
            )
        )
        if existing is not None:
            raise ConflictError("World Bible category key already exists")
        category = WorldBibleCategory(
            novel_id=nid,
            category_key=data.category_key,
            name=data.name,
            description=data.description,
            color=data.color.upper(),
            icon=data.icon,
            sort_order=data.sort_order,
            status="active",
        )
        db.add(category)
        await db.flush()
        return WorldBibleCategoryResponse.model_validate(category)

    async def update_category(
        self,
        db: AsyncSession,
        novel_id: str,
        category_id: str,
        data: WorldBibleCategoryUpdate,
    ) -> WorldBibleCategoryResponse:
        category = await self._get_category(db, novel_id, category_id)
        payload = data.model_dump(exclude_unset=True)
        for key, value in payload.items():
            setattr(category, key, value.upper() if key == "color" and value else value)
        await db.flush()
        return WorldBibleCategoryResponse.model_validate(category)

    async def list_drafts(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> tuple[list[WorldBiblePageDraftResponse], int]:
        nid = parse_uuid(novel_id, "novel_id")
        result = await db.execute(
            select(WorldBiblePageDraft)
            .where(WorldBiblePageDraft.novel_id == nid)
            .order_by(WorldBiblePageDraft.updated_at.desc())
        )
        drafts = list(result.scalars().all())
        return [WorldBiblePageDraftResponse.model_validate(item) for item in drafts], len(
            drafts
        )

    async def get_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        draft_id: str,
    ) -> WorldBiblePageDraftResponse:
        draft = await self._get_draft_model(db, novel_id, draft_id)
        return WorldBiblePageDraftResponse.model_validate(draft)

    async def get_or_create_page_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        *,
        created_by: str | None = None,
    ) -> WorldBiblePageDraftResponse:
        nid = parse_uuid(novel_id, "novel_id")
        pid = parse_uuid(page_id, "page_id")
        existing = await db.scalar(
            select(WorldBiblePageDraft).where(
                WorldBiblePageDraft.novel_id == nid,
                WorldBiblePageDraft.page_id == pid,
            )
        )
        if existing is not None:
            return WorldBiblePageDraftResponse.model_validate(existing)
        return await self.create_draft(
            db,
            WorldBiblePageDraftCreate(
                novel_id=novel_id,
                page_id=page_id,
                created_by=created_by,
            ),
        )

    async def create_draft(
        self,
        db: AsyncSession,
        data: WorldBiblePageDraftCreate,
    ) -> WorldBiblePageDraftResponse:
        nid = parse_uuid(data.novel_id, "novel_id")
        if data.page_id:
            # The page lock serializes the check-and-create sequence.  The
            # nullable unique key permits many new-page drafts, but an existing
            # page must never acquire two active drafts under concurrent calls.
            page = await self._get_page_model(
                db,
                data.novel_id,
                data.page_id,
                for_update=True,
            )
            existing = await db.scalar(
                select(WorldBiblePageDraft.id).where(
                    WorldBiblePageDraft.novel_id == nid,
                    WorldBiblePageDraft.page_id == page.id,
                )
            )
            if existing is not None:
                raise ConflictError("World Bible page already has an active draft")
            title = data.title or page.title
            page_type = data.page_type or page.page_type
            free_text = page.free_text if data.free_text is None else data.free_text
            refs = (
                page.linked_asset_refs_json
                if data.linked_asset_refs_json is None
                else data.linked_asset_refs_json
            )
            sort_order = page.sort_order if data.sort_order is None else data.sort_order
            page_id = page.id
            base_version = page.version_number
        else:
            if not data.title:
                raise ValidationError("title is required for a new World Bible draft")
            title = data.title
            page_type = data.page_type or "custom"
            free_text = data.free_text
            refs = data.linked_asset_refs_json or []
            sort_order = data.sort_order or 0
            page_id = None
            base_version = None
        await self._ensure_category_key(db, nid, page_type)
        await self._validate_asset_refs(db, nid, refs)
        draft = WorldBiblePageDraft(
            novel_id=nid,
            page_id=page_id,
            base_version_number=base_version,
            title=title,
            page_type=page_type,
            free_text=free_text,
            linked_asset_refs_json=refs,
            sort_order=sort_order,
            created_by=data.created_by,
            updated_by=data.created_by,
        )
        db.add(draft)
        await db.flush()
        return WorldBiblePageDraftResponse.model_validate(draft)

    async def update_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        draft_id: str,
        data: WorldBiblePageDraftUpdate,
    ) -> WorldBiblePageDraftResponse:
        draft = await self._get_draft_model(db, novel_id, draft_id)
        payload = data.model_dump(exclude_unset=True)
        if "page_type" in payload:
            await self._ensure_category_key(db, draft.novel_id, payload["page_type"])
        if "linked_asset_refs_json" in payload:
            await self._validate_asset_refs(
                db,
                draft.novel_id,
                payload["linked_asset_refs_json"] or [],
            )
        for key, value in payload.items():
            setattr(draft, key, value)
        await db.flush()
        await self._mark_draft_context_changed(
            db,
            draft,
            reason="world_bible_draft_updated",
        )
        return WorldBiblePageDraftResponse.model_validate(draft)

    async def discard_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        draft_id: str,
    ) -> None:
        draft = await self._get_draft_model(db, novel_id, draft_id)
        await self._mark_draft_context_changed(
            db,
            draft,
            reason="world_bible_draft_discarded",
        )
        await db.delete(draft)
        await db.flush()

    async def publish_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        draft_id: str,
        *,
        published_by: str | None = None,
    ) -> WorldBiblePageResponse:
        draft = await self._get_draft_model(db, novel_id, draft_id, for_update=True)
        await self._ensure_category_key(db, draft.novel_id, draft.page_type)
        await self._validate_asset_refs(db, draft.novel_id, draft.linked_asset_refs_json)
        if draft.page_id is None:
            page = WorldBiblePage(
                novel_id=draft.novel_id,
                page_type=draft.page_type,
                page_key=self._default_page_key(draft.page_type, draft.title),
                title=draft.title,
                status="canonical",
                free_text=draft.free_text,
                linked_asset_refs_json=draft.linked_asset_refs_json,
                sort_order=draft.sort_order,
                version_number=1,
                created_by=published_by or draft.created_by,
                updated_by=published_by or draft.updated_by,
            )
            db.add(page)
            await db.flush()
        else:
            page = await self._get_page_model(
                db,
                novel_id,
                str(draft.page_id),
                for_update=True,
            )
            if page.version_number != draft.base_version_number:
                raise ConflictError(
                    "World Bible page changed after this draft was created"
                )
            page.page_type = draft.page_type
            page.title = draft.title
            page.free_text = draft.free_text
            page.linked_asset_refs_json = draft.linked_asset_refs_json
            page.sort_order = draft.sort_order
            page.status = "canonical"
            page.version_number += 1
            page.updated_by = published_by or draft.updated_by
        await self._add_revision(db, page, revision_reason="manual_publish")
        await self._mark_page_projections_stale(db, page)
        await self._mark_draft_context_changed(
            db,
            draft,
            reason="world_bible_draft_published",
        )
        await db.delete(draft)
        await self._mark_synopsis_stale(db, str(page.novel_id))
        await db.flush()
        return WorldBiblePageResponse.model_validate(page)

    async def restore_revision_to_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        version_number: int,
        *,
        restored_by: str | None = None,
    ) -> WorldBiblePageDraftResponse:
        page = await self._get_page_model(db, novel_id, page_id)
        existing = await db.scalar(
            select(WorldBiblePageDraft.id).where(
                WorldBiblePageDraft.novel_id == page.novel_id,
                WorldBiblePageDraft.page_id == page.id,
            )
        )
        if existing is not None:
            raise ConflictError("World Bible page already has an active draft")
        revision = await db.scalar(
            select(WorldBiblePageRevision).where(
                WorldBiblePageRevision.novel_id == page.novel_id,
                WorldBiblePageRevision.page_id == page.id,
                WorldBiblePageRevision.version_number == version_number,
            )
        )
        if revision is None:
            raise NotFoundError("World Bible page revision not found")
        snapshot = dict(revision.snapshot_json or {})
        draft = WorldBiblePageDraft(
            novel_id=page.novel_id,
            page_id=page.id,
            base_version_number=page.version_number,
            title=str(snapshot.get("title") or page.title),
            page_type=str(snapshot.get("page_type") or page.page_type),
            free_text=snapshot.get("free_text"),
            linked_asset_refs_json=list(snapshot.get("linked_asset_refs_json") or []),
            sort_order=int(snapshot.get("sort_order") or 0),
            created_by=restored_by,
            updated_by=restored_by,
        )
        db.add(draft)
        await db.flush()
        return WorldBiblePageDraftResponse.model_validate(draft)

    async def list_revisions(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
    ) -> list[WorldBiblePageRevisionResponse]:
        page = await self._get_page_model(db, novel_id, page_id)
        result = await db.execute(
            select(WorldBiblePageRevision)
            .where(
                WorldBiblePageRevision.novel_id == page.novel_id,
                WorldBiblePageRevision.page_id == page.id,
            )
            .order_by(WorldBiblePageRevision.version_number.desc())
        )
        return [
            WorldBiblePageRevisionResponse.model_validate(item)
            for item in result.scalars().all()
        ]

    async def has_active_draft(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        page_id: uuid.UUID,
    ) -> bool:
        return (
            await db.scalar(
                select(WorldBiblePageDraft.id).where(
                    WorldBiblePageDraft.novel_id == novel_id,
                    WorldBiblePageDraft.page_id == page_id,
                )
            )
            is not None
        )

    async def validate_asset_refs(
        self,
        db: AsyncSession,
        novel_id: str,
        refs: list[dict[str, Any]],
    ) -> None:
        await self._validate_asset_refs(
            db,
            parse_uuid(novel_id, "novel_id"),
            refs,
        )

    async def _get_category(
        self,
        db: AsyncSession,
        novel_id: str,
        category_id: str,
    ) -> WorldBibleCategory:
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(category_id, "category_id")
        category = await db.scalar(
            select(WorldBibleCategory).where(
                WorldBibleCategory.id == cid,
                WorldBibleCategory.novel_id == nid,
            )
        )
        if category is None:
            raise NotFoundError("World Bible category not found")
        return category

    async def _get_draft_model(
        self,
        db: AsyncSession,
        novel_id: str,
        draft_id: str,
        *,
        for_update: bool = False,
    ) -> WorldBiblePageDraft:
        nid = parse_uuid(novel_id, "novel_id")
        did = parse_uuid(draft_id, "draft_id")
        stmt = select(WorldBiblePageDraft).where(
            WorldBiblePageDraft.id == did,
            WorldBiblePageDraft.novel_id == nid,
        )
        if for_update:
            stmt = stmt.with_for_update()
        draft = await db.scalar(stmt)
        if draft is None:
            raise NotFoundError("World Bible draft not found")
        return draft

    async def _get_page_model(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        *,
        for_update: bool = False,
    ) -> WorldBiblePage:
        nid = parse_uuid(novel_id, "novel_id")
        pid = parse_uuid(page_id, "page_id")
        stmt = select(WorldBiblePage).where(
            WorldBiblePage.id == pid,
            WorldBiblePage.novel_id == nid,
        )
        if for_update:
            stmt = stmt.with_for_update()
        page = await db.scalar(stmt)
        if page is None:
            raise NotFoundError("World Bible page not found")
        return page

    async def _ensure_category_key(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        category_key: str,
    ) -> None:
        if category_key in _BUILTIN_KEYS:
            return
        exists = await db.scalar(
            select(WorldBibleCategory.id).where(
                WorldBibleCategory.novel_id == novel_id,
                WorldBibleCategory.category_key == category_key,
                WorldBibleCategory.status == "active",
            )
        )
        if exists is None:
            raise ValidationError("Unknown or archived World Bible category")

    async def _validate_asset_refs(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        refs: list[dict[str, Any]],
    ) -> None:
        for ref in refs:
            ref_type = str(
                ref.get("type") or ref.get("source_type") or ref.get("target_type") or ""
            )
            ref_id = str(
                ref.get("id") or ref.get("source_id") or ref.get("target_id") or ""
            )
            if not ref_type or not ref_id:
                raise ValidationError("World Bible asset refs require type and id")
            rid = parse_uuid(ref_id, "asset_ref_id")
            if ref_type in {"core_entity", "entity", "profile", "event"}:
                exists = await db.scalar(
                    select(CoreEntity.id).where(
                        CoreEntity.id == rid,
                        CoreEntity.novel_id == novel_id,
                        CoreEntity.status == "canonical",
                    )
                )
            elif ref_type in {"relation", "entity_relation"}:
                exists = await db.scalar(
                    select(EntityRelation.id).where(
                        EntityRelation.id == rid,
                        EntityRelation.novel_id == novel_id,
                        EntityRelation.status == "canonical",
                    )
                )
            elif ref_type == "map_fact":
                exists = await db.scalar(
                    select(MapFact.id).where(
                        MapFact.id == rid,
                        MapFact.novel_id == novel_id,
                        MapFact.fact_status == "confirmed",
                    )
                )
            elif ref_type in {"world_bible_page", "page"}:
                exists = await db.scalar(
                    select(WorldBiblePage.id).where(
                        WorldBiblePage.id == rid,
                        WorldBiblePage.novel_id == novel_id,
                        WorldBiblePage.status.in_({"canonical", "confirmed"}),
                    )
                )
            else:
                raise ValidationError(f"Unsupported World Bible asset ref: {ref_type}")
            if exists is None:
                raise ValidationError(
                    "World Bible asset ref must be an adopted asset in this project"
                )

    @staticmethod
    async def _add_revision(
        db: AsyncSession,
        page: WorldBiblePage,
        *,
        revision_reason: str,
    ) -> None:
        db.add(
            WorldBiblePageRevision(
                novel_id=page.novel_id,
                page_id=page.id,
                version_number=page.version_number,
                revision_reason=revision_reason,
                snapshot_json={
                    "page_type": page.page_type,
                    "page_key": page.page_key,
                    "title": page.title,
                    "status": page.status,
                    "page_meta_json": page.page_meta_json,
                    "free_text": page.free_text,
                    "linked_asset_refs_json": page.linked_asset_refs_json,
                    "activation_defaults_json": page.activation_defaults_json,
                    "template_key": page.template_key,
                    "template_version": page.template_version,
                    "sort_order": page.sort_order,
                },
            )
        )

    @staticmethod
    async def _mark_page_projections_stale(
        db: AsyncSession,
        page: WorldBiblePage,
    ) -> None:
        from modules.world.models import WorldBiblePageProjection

        result = await db.execute(
            select(WorldBiblePageProjection).where(
                WorldBiblePageProjection.novel_id == page.novel_id,
                WorldBiblePageProjection.page_id == page.id,
            )
        )
        for projection in result.scalars().all():
            projection.stale = True

    @staticmethod
    async def _mark_synopsis_stale(db: AsyncSession, novel_id: str) -> None:
        from modules.world.services.worldbuilding.world_bible_synopsis_service import (
            WorldBibleSynopsisService,
        )

        await WorldBibleSynopsisService().mark_stale(db, novel_id)

    @staticmethod
    async def _mark_draft_context_changed(
        db: AsyncSession,
        draft: WorldBiblePageDraft,
        *,
        reason: str,
    ) -> None:
        """Invalidate confirmations that explicitly selected this working draft."""
        try:
            from modules.context.facade import mark_asset_context_changed

            await mark_asset_context_changed(
                db,
                novel_id=str(draft.novel_id),
                asset_type="world_bible_draft",
                asset_id=str(draft.id),
                reason=reason,
            )
        except Exception:
            logger.warning(
                "World Bible 工作稿上下文确认失效标记失败 draft_id=%s",
                draft.id,
                exc_info=True,
            )

    @staticmethod
    def _default_page_key(page_type: str, title: str) -> str:
        from modules.world.services.worldbuilding.shared import normalize_profession_slug

        slug = normalize_profession_slug(title) or "page"
        return f"{page_type}:{slug}:{uuid.uuid4().hex[:8]}"


__all__ = [
    "BUILTIN_WORLD_BIBLE_CATEGORIES",
    "WorldBibleLifecycleService",
]
