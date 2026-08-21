"""World Bible categories, working drafts, publish, and revision restore."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.models import (
    CoreEntity,
    EntityRelation,
    WorldBibleCategory,
    WorldBiblePage,
    WorldBiblePageDraft,
    WorldBiblePageProjection,
    WorldBiblePageRevision,
)
from modules.world.schemas import (
    WorldBibleCategoryCreate,
    WorldBibleCategoryResponse,
    WorldBibleCategoryUpdate,
    WorldBibleImpactedPage,
    WorldBibleImpactOmission,
    WorldBibleImpactPathNode,
    WorldBiblePageCreate,
    WorldBiblePageDraftCreate,
    WorldBiblePageDraftResponse,
    WorldBiblePageDraftUpdate,
    WorldBiblePageResponse,
    WorldBiblePageRevisionResponse,
    WorldBiblePageUpdate,
    WorldBiblePublishImpactResponse,
    WorldBiblePublishImpactSource,
    WorldBibleSection,
    WorldBibleValidationReceipt,
)
from shared.target_ref import TargetRef
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
        "category_key": "source_material",
        "name": "导入资料",
        "description": "外部世界书原始资料与候选政策；发布前不会进入正式设定",
        "color": "#475569",
        "icon": "资料",
        "sort_order": 80,
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

WorldBibleBaselineMismatch = Literal[
    "page_version",
    "draft_created",
    "draft_changed",
    "content_hash",
]


@dataclass(frozen=True, slots=True)
class WorldBiblePageSourceState:
    """One locked or observed page/draft source used by generation workflows."""

    page: WorldBiblePage
    draft: WorldBiblePageDraft | None

    @property
    def active(self) -> WorldBiblePage | WorldBiblePageDraft:
        return self.draft or self.page

    def content(self) -> dict[str, Any]:
        active = self.active
        return {
            "id": str(active.id) if self.draft is not None else None,
            "title": active.title,
            "page_type": active.page_type,
            "free_text": active.free_text,
            "sections_json": list(active.sections_json or []),
            "linked_asset_refs_json": list(active.linked_asset_refs_json or []),
            "template_key": active.template_key,
            "template_version": active.template_version,
            "updated_at": self.draft.updated_at if self.draft is not None else None,
        }


class WorldBibleLifecycleService:
    _ADOPTED_STATUSES = frozenset({"canonical", "confirmed"})

    async def create_page(
        self,
        db: AsyncSession,
        data: WorldBiblePageCreate,
    ) -> WorldBiblePageResponse:
        """Create through the legacy direct-page API while owning its lifecycle."""
        nid = parse_uuid(data.novel_id, "novel_id")
        await self._lock_page_universe(db, nid)
        if data.status in self._ADOPTED_STATUSES:
            await self._require_legacy_canon_write_allowed(db, data.novel_id)
        await self._validate_page_content(
            db,
            novel_id=nid,
            template_key=data.template_key,
            sections=data.sections_json,
            refs=data.linked_asset_refs_json,
        )
        page = WorldBiblePage(
            novel_id=nid,
            page_type=data.page_type,
            page_key=data.page_key or self._default_page_key(data.page_type, data.title),
            title=data.title,
            status=data.status,
            page_meta_json=data.page_meta_json,
            free_text=data.free_text,
            sections_json=self._serialize_sections(data.sections_json),
            linked_asset_refs_json=data.linked_asset_refs_json,
            activation_defaults_json=data.activation_defaults_json,
            template_key=data.template_key,
            sort_order=data.sort_order,
            created_by=data.created_by,
            updated_by=data.created_by,
        )
        db.add(page)
        await db.flush()
        if page.status in self._ADOPTED_STATUSES:
            await self._record_adopted_page_change(
                db,
                page,
                revision_reason="legacy_create",
            )
            await db.flush()
        return WorldBiblePageResponse.model_validate(page)

    async def update_page(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        data: WorldBiblePageUpdate,
    ) -> WorldBiblePageResponse:
        """Update a published page and atomically maintain its derived lifecycle."""
        await self._lock_page_universe(db, parse_uuid(novel_id, "novel_id"))
        page = await self._get_page_model(db, novel_id, page_id, for_update=True)
        if await self.has_active_draft(db, page.novel_id, page.id):
            raise ConflictError("World Bible page has an active working draft")
        payload = data.model_dump(mode="json", exclude_unset=True)
        next_sections = payload.get("sections_json", page.sections_json)
        next_refs = payload.get("linked_asset_refs_json", page.linked_asset_refs_json)
        await self._validate_page_content(
            db,
            novel_id=page.novel_id,
            template_key=payload.get("template_key"),
            sections=next_sections or [],
            refs=next_refs or [],
            validate_template="template_key" in payload,
            validate_asset_refs="linked_asset_refs_json" in payload,
        )
        meaningful_fields = {
            "title",
            "status",
            "page_meta_json",
            "free_text",
            "sections_json",
            "linked_asset_refs_json",
            "activation_defaults_json",
            "template_key",
            "sort_order",
        }
        meaningful_change = any(
            key in meaningful_fields and getattr(page, key) != value
            for key, value in payload.items()
        )
        free_text_changed = (
            "free_text" in payload and payload["free_text"] != page.free_text
        )
        before_status = page.status
        next_status = payload.get("status", before_status)
        projection_input_changed = free_text_changed or any(
            key in payload
            for key in {
                "sections_json",
                "linked_asset_refs_json",
                "template_key",
            }
        )
        adopted_change = meaningful_change and (
            next_status in self._ADOPTED_STATUSES
            or before_status in self._ADOPTED_STATUSES
        )
        if adopted_change:
            await self._require_legacy_canon_write_allowed(db, novel_id)
        for key, value in payload.items():
            setattr(page, key, value)
        if projection_input_changed or adopted_change:
            await self._mark_page_projections_stale(db, page)
        if adopted_change:
            page.version_number += 1
            await self._record_adopted_page_change(
                db,
                page,
                revision_reason="legacy_update",
                context_reason="world_bible_page_updated",
            )
        await db.flush()
        return WorldBiblePageResponse.model_validate(page)

    @staticmethod
    async def _require_legacy_canon_write_allowed(
        db: AsyncSession, novel_id: str
    ) -> None:
        from modules.world.services.worldbuilding.world_validation_service import (
            WorldValidationService,
        )

        if await WorldValidationService().active_policy(db, novel_id) is not None:
            raise ConflictError(
                "Published World Bible changes must use a validated draft",
                code="required_validation",
                context={"next_action": "create_and_validate_world_bible_draft"},
            )

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
        if data.default_template_key:
            await self._ensure_page_template_key(
                db,
                data.novel_id,
                data.default_template_key,
            )
        category = WorldBibleCategory(
            novel_id=nid,
            category_key=data.category_key,
            name=data.name,
            description=data.description,
            color=data.color.upper(),
            icon=data.icon,
            sort_order=data.sort_order,
            default_template_key=data.default_template_key,
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
        payload = data.model_dump(mode="json", exclude_unset=True)
        if payload.get("default_template_key"):
            await self._ensure_page_template_key(
                db,
                novel_id,
                payload["default_template_key"],
            )
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
            page_meta = (
                page.page_meta_json
                if data.page_meta_json is None
                else data.page_meta_json
            )
            sections = (
                page.sections_json
                if data.sections_json is None
                else self._serialize_sections(data.sections_json)
            )
            refs = (
                page.linked_asset_refs_json
                if data.linked_asset_refs_json is None
                else data.linked_asset_refs_json
            )
            sort_order = page.sort_order if data.sort_order is None else data.sort_order
            page_id = page.id
            base_version = page.version_number
            template_key = data.template_key or page.template_key
            template_version = data.template_version or page.template_version
        else:
            if not data.title:
                raise ValidationError("title is required for a new World Bible draft")
            title = data.title
            page_type = data.page_type or "custom"
            free_text = data.free_text
            page_meta = data.page_meta_json or {}
            sections = self._serialize_sections(data.sections_json or [])
            refs = data.linked_asset_refs_json or []
            sort_order = data.sort_order or 0
            page_id = None
            base_version = None
            template_key = data.template_key
            template_version = data.template_version or 1
        await self._ensure_category_key(db, nid, page_type)
        if template_key:
            await self._ensure_page_template_key(db, str(nid), template_key)
        await self._validate_asset_refs(db, nid, refs)
        self._validate_section_refs(sections, refs)
        draft = WorldBiblePageDraft(
            novel_id=nid,
            page_id=page_id,
            base_version_number=base_version,
            title=title,
            page_type=page_type,
            page_meta_json=page_meta,
            free_text=free_text,
            sections_json=sections,
            linked_asset_refs_json=refs,
            sort_order=sort_order,
            template_key=template_key,
            template_version=template_version,
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
        payload = data.model_dump(mode="json", exclude_unset=True)
        if "page_type" in payload:
            await self._ensure_category_key(db, draft.novel_id, payload["page_type"])
        if "linked_asset_refs_json" in payload:
            await self._validate_asset_refs(
                db,
                draft.novel_id,
                payload["linked_asset_refs_json"] or [],
            )
        if payload.get("template_key"):
            await self._ensure_page_template_key(
                db,
                str(draft.novel_id),
                payload["template_key"],
            )
        next_sections = payload.get("sections_json", draft.sections_json)
        next_refs = payload.get("linked_asset_refs_json", draft.linked_asset_refs_json)
        self._validate_section_refs(next_sections or [], next_refs or [])
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

    async def preview_publish_impact(
        self,
        db: AsyncSession,
        novel_id: str,
        draft_id: str,
    ) -> WorldBiblePublishImpactResponse:
        draft = await self._get_draft_model(db, novel_id, draft_id)
        page = (
            await self._get_page_model(db, novel_id, str(draft.page_id))
            if draft.page_id is not None
            else None
        )
        if page is not None and page.version_number != draft.base_version_number:
            raise ConflictError("World Bible page changed after this draft was created")
        await self._validate_publish_draft(db, draft)
        return await self._build_publish_impact(db, draft, page)

    async def preview_package_page(
        self,
        db: AsyncSession,
        data: WorldBiblePageDraftCreate,
        *,
        expected_page_version: int | None,
        lock_universe: bool = False,
        for_update: bool = False,
        allow_local_refs: bool = False,
    ) -> WorldBiblePublishImpactResponse:
        """Read-only lifecycle preview for an unsaved package page proposal."""
        nid = parse_uuid(data.novel_id, "novel_id")
        if lock_universe:
            await self._lock_page_universe(db, nid)
        page = None
        if data.page_id:
            page = await self._get_page_model(
                db, data.novel_id, data.page_id, for_update=for_update
            )
            if page.version_number != expected_page_version:
                raise ConflictError("World Bible page changed after package preview")
        draft = WorldBiblePageDraft(
            novel_id=nid,
            page_id=page.id if page else None,
            base_version_number=page.version_number if page else None,
            title=data.title or (page.title if page else ""),
            page_type=data.page_type or (page.page_type if page else "custom"),
            page_meta_json=(data.page_meta_json or (page.page_meta_json if page else {})),
            free_text=data.free_text,
            sections_json=self._serialize_sections(data.sections_json or []),
            linked_asset_refs_json=data.linked_asset_refs_json or [],
            sort_order=data.sort_order or 0,
            template_key=data.template_key,
            template_version=data.template_version or 1,
            created_by=data.created_by,
            updated_by=data.created_by,
        )
        await self._ensure_category_key(db, draft.novel_id, draft.page_type)
        await self._validate_page_content(
            db,
            novel_id=draft.novel_id,
            template_key=draft.template_key,
            sections=draft.sections_json,
            refs=draft.linked_asset_refs_json,
            allow_local_refs=allow_local_refs,
        )
        return await self._build_publish_impact(db, draft, page)

    async def publish_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        draft_id: str,
        *,
        published_by: str | None = None,
        expected_impact_scope_hash: str | None = None,
        validation_run_id: str | None = None,
        _validation_prechecked: bool = False,
    ) -> WorldBiblePageResponse:
        await self._lock_page_universe(db, parse_uuid(novel_id, "novel_id"))
        observed_draft = await self._get_draft_model(db, novel_id, draft_id)
        page: WorldBiblePage | None = None
        if observed_draft.page_id is not None:
            # Keep the global lifecycle lock order page -> draft. Generation
            # suggestion application uses the same order through
            # load_page_source(for_update=True).
            page = await self._get_page_model(
                db,
                novel_id,
                str(observed_draft.page_id),
                for_update=True,
            )
            draft = await self._get_draft_model(
                db,
                novel_id,
                draft_id,
                for_update=True,
            )
            if draft.page_id != page.id:
                raise ConflictError("World Bible draft page changed during publish")
        else:
            draft = await self._get_draft_model(
                db,
                novel_id,
                draft_id,
                for_update=True,
            )
        await self._validate_publish_draft(db, draft)
        current_impact = await self._build_publish_impact(db, draft, page)
        if expected_impact_scope_hash is not None:
            if current_impact.impact_scope_hash != expected_impact_scope_hash:
                raise ConflictError(
                    "World Bible explicit references changed after impact preview",
                    code="world_bible_impact_scope_changed",
                )
        if not _validation_prechecked:
            from modules.world.services.worldbuilding.world_validation_service import (
                WorldValidationService,
            )

            await WorldValidationService().require_gate(
                db,
                novel_id=novel_id,
                validation_run_id=validation_run_id,
                target_type="world_bible_draft",
                target_id=draft_id,
                target_hash=current_impact.impact_scope_hash,
            )
        if draft.page_id is None:
            page = WorldBiblePage(
                novel_id=draft.novel_id,
                page_type=draft.page_type,
                page_key=self._default_page_key(draft.page_type, draft.title),
                title=draft.title,
                page_meta_json=draft.page_meta_json,
                status="canonical",
                free_text=draft.free_text,
                sections_json=draft.sections_json,
                linked_asset_refs_json=draft.linked_asset_refs_json,
                sort_order=draft.sort_order,
                template_key=draft.template_key,
                template_version=draft.template_version,
                version_number=1,
                created_by=published_by or draft.created_by,
                updated_by=published_by or draft.updated_by,
            )
            db.add(page)
            await db.flush()
        else:
            if page is None:
                raise ConflictError("World Bible draft page changed during publish")
            if page.version_number != draft.base_version_number:
                raise ConflictError(
                    "World Bible page changed after this draft was created"
                )
            page.page_type = draft.page_type
            page.title = draft.title
            page.page_meta_json = draft.page_meta_json
            page.free_text = draft.free_text
            page.sections_json = draft.sections_json
            page.linked_asset_refs_json = draft.linked_asset_refs_json
            page.sort_order = draft.sort_order
            page.template_key = draft.template_key
            page.template_version = draft.template_version
            page.status = "canonical"
            page.version_number += 1
            page.updated_by = published_by or draft.updated_by
        await self._mark_draft_context_changed(
            db,
            draft,
            reason="world_bible_draft_published",
        )
        await self._record_adopted_page_change(
            db,
            page,
            revision_reason="manual_publish",
            mark_projections_stale=True,
            context_reason="world_bible_page_published",
        )
        await db.delete(draft)
        await db.flush()
        omissions = {
            "invalid_page_reference": "有页面引用格式损坏",
            "unavailable_page_reference": "有页面引用不可用或不在当前项目",
            "response_limit": "部分显式下游未在回执中展开",
        }
        receipt = WorldBibleValidationReceipt(
            scope="targeted",
            scope_label=(f"当前页面与 {len(current_impact.affected_pages)} 个显式下游"),
            source_version=page.version_number,
            checked=[
                "目标页面的 schema、来源基线与写入版本",
                "发布时显式引用路径与影响范围",
                "当前页面修订历史与派生内容失效标记",
            ],
            not_checked=[
                *current_impact.not_checked,
                "显式下游页面的语义一致性",
                "所属领域的完整检查",
            ],
            omissions=[
                f"{item.count} 处{omissions.get(item.reason, '内容未能检查')}"
                for item in current_impact.omissions
            ],
            impact_scope_hash=current_impact.impact_scope_hash,
            completed_at=datetime.now(UTC),
        )
        return WorldBiblePageResponse.model_validate(page).model_copy(
            update={"validation_receipt": receipt}
        )

    async def _validate_publish_draft(
        self,
        db: AsyncSession,
        draft: WorldBiblePageDraft,
    ) -> None:
        await self._ensure_category_key(db, draft.novel_id, draft.page_type)
        await self._validate_page_content(
            db,
            novel_id=draft.novel_id,
            template_key=draft.template_key,
            sections=draft.sections_json,
            refs=draft.linked_asset_refs_json,
        )

    @staticmethod
    async def _lock_page_universe(db: AsyncSession, novel_id: uuid.UUID) -> None:
        """Serialize adopted-page writes with impact-scope computation."""
        bind = db.get_bind()
        if bind.dialect.name != "postgresql":
            return
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"world_bible_pages:{novel_id}"},
        )

    async def _build_publish_impact(
        self,
        db: AsyncSession,
        draft: WorldBiblePageDraft,
        page: WorldBiblePage | None,
    ) -> WorldBiblePublishImpactResponse:
        result = await db.execute(
            select(WorldBiblePage).where(
                WorldBiblePage.novel_id == draft.novel_id,
                WorldBiblePage.status.in_(self._ADOPTED_STATUSES),
            )
        )
        pages = list(result.scalars().all())
        pages_by_id = {item.id: item for item in pages}
        reverse_edges: dict[uuid.UUID, dict[uuid.UUID, set[str]]] = {}
        normalized_edges: list[dict[str, str]] = []
        omission_counts: dict[tuple[str, uuid.UUID | None, str | None], int] = {}

        def add_omission(reason: str, referrer: WorldBiblePage | None) -> None:
            key = (
                reason,
                referrer.id if referrer is not None else None,
                referrer.title if referrer is not None else None,
            )
            omission_counts[key] = omission_counts.get(key, 0) + 1

        for referrer in pages:
            seen_refs: set[tuple[uuid.UUID, str]] = set()
            for raw_ref in referrer.linked_asset_refs_json or []:
                raw_type = str(
                    raw_ref.get("target_type")
                    or raw_ref.get("type")
                    or raw_ref.get("source_type")
                    or ""
                ).strip()
                if raw_type not in {"world_bible_page", "page"}:
                    continue
                try:
                    target = self._normalize_asset_ref(raw_ref)
                    target_id = uuid.UUID(target.target_id)
                except (TypeError, ValueError):
                    add_omission("invalid_page_reference", referrer)
                    continue
                edge_key = (target_id, target.target_path)
                if edge_key in seen_refs:
                    continue
                seen_refs.add(edge_key)
                normalized_edges.append(
                    {
                        "from": str(referrer.id),
                        "path": target.target_path,
                        "to": str(target_id),
                    }
                )
                if target_id not in pages_by_id:
                    add_omission("unavailable_page_reference", referrer)
                    continue
                target_hash = target.target_hash()
                section_titles = {
                    str(section.get("title") or section.get("section_id") or "未命名分区")
                    for section in referrer.sections_json or []
                    if target_hash
                    in {
                        str(value).removeprefix("sha256:")
                        for value in section.get("linked_asset_ref_hashes") or []
                    }
                }
                reverse_edges.setdefault(target_id, {}).setdefault(
                    referrer.id,
                    set(),
                ).update(section_titles)

        affected: list[WorldBibleImpactedPage] = []
        if page is not None:
            paths: dict[uuid.UUID, list[WorldBibleImpactPathNode]] = {
                page.id: [
                    WorldBibleImpactPathNode(
                        page_id=str(page.id),
                        title=page.title,
                        version_number=page.version_number,
                    )
                ]
            }
            queue = deque([page.id])
            while queue:
                target_id = queue.popleft()
                referrers = reverse_edges.get(target_id, {})
                for referrer_id in sorted(
                    referrers,
                    key=lambda item: (
                        pages_by_id[item].title.casefold(),
                        str(item),
                    ),
                ):
                    if referrer_id in paths:
                        continue
                    referrer = pages_by_id[referrer_id]
                    path = [
                        *paths[target_id],
                        WorldBibleImpactPathNode(
                            page_id=str(referrer.id),
                            title=referrer.title,
                            version_number=referrer.version_number,
                            section_titles=sorted(referrers[referrer_id]),
                        ),
                    ]
                    paths[referrer_id] = path
                    affected.append(
                        WorldBibleImpactedPage(
                            page_id=str(referrer.id),
                            title=referrer.title,
                            page_type=referrer.page_type,
                            version_number=referrer.version_number,
                            distance=len(path) - 1,
                            path=path,
                        )
                    )
                    queue.append(referrer_id)

        affected.sort(
            key=lambda item: (
                item.distance,
                item.title.casefold(),
                item.page_id,
            )
        )
        if len(affected) > 200:
            add_omission("response_limit", None)
            omission_counts[("response_limit", None, None)] = len(affected) - 200
            affected = affected[:200]

        omissions = [
            WorldBibleImpactOmission(
                reason=reason,
                referring_page_id=str(referrer_id) if referrer_id else None,
                referring_page_title=referrer_title,
                count=count,
            )
            for (reason, referrer_id, referrer_title), count in sorted(
                omission_counts.items(),
                key=lambda item: (
                    item[0][0],
                    (item[0][2] or "").casefold(),
                    str(item[0][1] or ""),
                ),
            )
        ]
        base_refs = page.linked_asset_refs_json if page is not None else []
        previous_refs = self._canonical_asset_refs(base_refs or [])
        proposed_refs = self._canonical_asset_refs(draft.linked_asset_refs_json or [])
        content_hash = self.source_content_hash(
            title=draft.title,
            page_type=draft.page_type,
            free_text=draft.free_text,
            sections_json=list(draft.sections_json or []),
            linked_asset_refs_json=list(draft.linked_asset_refs_json or []),
            template_key=draft.template_key,
            template_version=draft.template_version,
            page_version=page.version_number if page is not None else 0,
        )
        scope_payload = {
            "source": {
                "content_hash": content_hash,
                "draft_id": str(draft.id),
                "draft_updated_at": draft.updated_at,
                "page_id": str(page.id) if page is not None else None,
                "page_version": page.version_number if page is not None else None,
            },
            "universe": [
                {
                    "id": str(item.id),
                    "status": item.status,
                    "version": item.version_number,
                }
                for item in sorted(pages, key=lambda current: str(current.id))
            ],
            "edges": sorted(
                normalized_edges,
                key=lambda item: (item["from"], item["to"], item["path"]),
            ),
            "omissions": [item.model_dump(mode="json") for item in omissions],
        }
        impact_scope_hash = hashlib.sha256(
            json.dumps(
                scope_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        return WorldBiblePublishImpactResponse(
            source=WorldBiblePublishImpactSource(
                draft_id=str(draft.id),
                page_id=str(page.id) if page is not None else None,
                title=draft.title,
                page_version=page.version_number if page is not None else None,
                draft_updated_at=draft.updated_at,
                content_hash=content_hash,
            ),
            added_outgoing_refs=len(proposed_refs - previous_refs),
            removed_outgoing_refs=len(previous_refs - proposed_refs),
            affected_pages=affected,
            omissions=omissions,
            automatic_actions=[
                "保存不可变页面版本",
                "标记本页上下文摘要与世界观简介需要刷新",
                "让实际使用过本页的上下文确认重新核对",
            ],
            not_checked=[
                "故事总纲与 Scene",
                "正文和自由文本中的语义提及",
                "地图、人物及其他没有 typed 引用的内容",
            ],
            complete=not omissions,
            impact_scope_hash=impact_scope_hash,
        )

    async def restore_revision_to_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        version_number: int,
        *,
        restored_by: str | None = None,
    ) -> WorldBiblePageDraftResponse:
        page = await self._get_page_model(
            db,
            novel_id,
            page_id,
            for_update=True,
        )
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
            page_meta_json=dict(
                snapshot.get("page_meta_json") or page.page_meta_json or {}
            ),
            free_text=snapshot.get("free_text"),
            sections_json=list(snapshot.get("sections_json") or []),
            linked_asset_refs_json=list(snapshot.get("linked_asset_refs_json") or []),
            sort_order=int(snapshot.get("sort_order") or 0),
            template_key=snapshot.get("template_key"),
            template_version=int(snapshot.get("template_version") or 1),
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

    async def ensure_category_key(
        self,
        db: AsyncSession,
        novel_id: str,
        category_key: str,
    ) -> None:
        await self._ensure_category_key(
            db,
            parse_uuid(novel_id, "novel_id"),
            category_key,
        )

    async def ensure_page_template_key(
        self,
        db: AsyncSession,
        novel_id: str,
        template_key: str,
    ) -> None:
        await self._ensure_page_template_key(db, novel_id, template_key)

    async def get_draft_model(
        self,
        db: AsyncSession,
        novel_id: str,
        draft_id: str,
        *,
        for_update: bool = False,
    ) -> WorldBiblePageDraft:
        return await self._get_draft_model(
            db,
            novel_id,
            draft_id,
            for_update=for_update,
        )

    async def get_page_model(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        *,
        for_update: bool = False,
    ) -> WorldBiblePage:
        return await self._get_page_model(
            db,
            novel_id,
            page_id,
            for_update=for_update,
        )

    async def load_page_source(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        *,
        for_update: bool = False,
    ) -> WorldBiblePageSourceState:
        """Load one novel-scoped page and its exact active working draft."""
        page = await self._get_page_model(
            db,
            novel_id,
            page_id,
            for_update=for_update,
        )
        stmt = select(WorldBiblePageDraft).where(
            WorldBiblePageDraft.novel_id == page.novel_id,
            WorldBiblePageDraft.page_id == page.id,
        )
        if for_update:
            stmt = stmt.execution_options(populate_existing=True).with_for_update()
        draft = await db.scalar(stmt)
        return WorldBiblePageSourceState(page=page, draft=draft)

    @classmethod
    def page_source_hash(cls, state: WorldBiblePageSourceState) -> str:
        content = state.content()
        return cls.source_content_hash(
            title=content["title"],
            page_type=content["page_type"],
            free_text=content["free_text"],
            sections_json=content["sections_json"],
            linked_asset_refs_json=content["linked_asset_refs_json"],
            template_key=content["template_key"],
            template_version=content["template_version"],
            page_version=state.page.version_number,
        )

    @staticmethod
    def source_content_hash(
        *,
        title: str,
        page_type: str,
        free_text: str | None,
        sections_json: list[dict[str, Any]],
        linked_asset_refs_json: list[dict[str, Any]],
        template_key: str | None,
        template_version: int,
        page_version: int,
    ) -> str:
        value = {
            "title": title,
            "page_type": page_type,
            "free_text": free_text,
            "sections_json": sections_json,
            "linked_asset_refs_json": linked_asset_refs_json,
            "template_key": template_key,
            "template_version": template_version,
            "page_version": page_version,
        }
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()

    @classmethod
    def baseline_mismatch(
        cls,
        state: WorldBiblePageSourceState,
        *,
        page_version: int,
        draft_id: str | None,
        draft_updated_at: datetime | None,
        content_hash: str | None = None,
    ) -> WorldBibleBaselineMismatch | None:
        if state.page.version_number != page_version:
            return "page_version"
        if draft_id is None:
            if state.draft is not None:
                return "draft_created"
        elif (
            state.draft is None
            or str(state.draft.id) != draft_id
            or not cls._same_datetime(state.draft.updated_at, draft_updated_at)
        ):
            return "draft_changed"
        if content_hash is not None and cls.page_source_hash(state) != content_hash:
            return "content_hash"
        return None

    @staticmethod
    def projection_source_hash(page: WorldBiblePage) -> str:
        payload = {
            "free_text": page.free_text or "",
            "linked_asset_refs_json": page.linked_asset_refs_json or [],
            "sections_json": page.sections_json or [],
            "template_key": page.template_key,
            "template_version": page.template_version,
            "version_number": page.version_number,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def projection_source_spans(page: WorldBiblePage) -> list[dict[str, Any]]:
        spans: list[dict[str, Any]] = []
        if page.free_text:
            spans.append(
                {
                    "page_id": str(page.id),
                    "section_id": "overview",
                    "start": 0,
                    "end": len(page.free_text),
                }
            )
        for section in page.sections_json or []:
            body = str(section.get("body_markdown") or "")
            if body and section.get("projection_policy", "eligible") == "eligible":
                spans.append(
                    {
                        "page_id": str(page.id),
                        "section_id": section.get("section_id"),
                        "start": 0,
                        "end": len(body),
                    }
                )
        return spans

    async def mark_draft_context_changed(
        self,
        db: AsyncSession,
        draft: WorldBiblePageDraft,
        *,
        reason: str,
    ) -> None:
        await self._mark_draft_context_changed(db, draft, reason=reason)

    @staticmethod
    async def mark_page_context_changed(
        db: AsyncSession,
        page: WorldBiblePage,
        *,
        reason: str,
    ) -> None:
        """Invalidate confirmations that consumed this published page."""
        from modules.evidence.facade import mark_asset_context_changed

        try:
            await mark_asset_context_changed(
                db,
                novel_id=str(page.novel_id),
                asset_type="world_bible_page",
                asset_id=str(page.id),
                reason=reason,
            )
        except Exception as exc:
            raise ConflictError(
                "参考资料状态同步失败，本次世界书发布未保存，请重试",
                code="world_bible_context_invalidation_failed",
            ) from exc

    def validate_section_refs(
        self,
        sections: list[dict[str, Any]] | list[WorldBibleSection],
        refs: list[dict[str, Any]],
    ) -> None:
        self._validate_section_refs(self._serialize_sections(sections), refs)

    async def _validate_page_content(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        template_key: str | None,
        sections: list[dict[str, Any]] | list[WorldBibleSection],
        refs: list[dict[str, Any]],
        validate_template: bool = True,
        validate_asset_refs: bool = True,
        allow_local_refs: bool = False,
    ) -> None:
        if validate_template and template_key:
            await self._ensure_page_template_key(db, str(novel_id), template_key)
        if validate_asset_refs:
            await self._validate_asset_refs(
                db, novel_id, refs, allow_local_refs=allow_local_refs
            )
        self._validate_section_refs(self._serialize_sections(sections), refs)

    async def _record_adopted_page_change(
        self,
        db: AsyncSession,
        page: WorldBiblePage,
        *,
        revision_reason: str,
        mark_projections_stale: bool = False,
        context_reason: str | None = None,
    ) -> None:
        await self._add_revision(db, page, revision_reason=revision_reason)
        if mark_projections_stale:
            await self._mark_page_projections_stale(db, page)
        if context_reason:
            await self.mark_page_context_changed(db, page, reason=context_reason)
        await self._mark_synopsis_stale(db, str(page.novel_id))

    @staticmethod
    def _same_datetime(left: datetime | None, right: datetime | None) -> bool:
        if left is None or right is None:
            return left is right
        if left.tzinfo is None:
            left = left.replace(tzinfo=UTC)
        if right.tzinfo is None:
            right = right.replace(tzinfo=UTC)
        return left.astimezone(UTC) == right.astimezone(UTC)

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
            stmt = stmt.execution_options(populate_existing=True).with_for_update()
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
            stmt = stmt.execution_options(populate_existing=True).with_for_update()
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

    @staticmethod
    async def _ensure_page_template_key(
        db: AsyncSession,
        novel_id: str,
        template_key: str,
    ) -> None:
        from modules.world.models import WorldBiblePageTemplate
        from modules.world.services.worldbuilding.page_template_service import (
            BUILTIN_PAGE_TEMPLATE_KEYS,
        )

        if template_key in BUILTIN_PAGE_TEMPLATE_KEYS:
            return
        nid = parse_uuid(novel_id, "novel_id")
        exists = await db.scalar(
            select(WorldBiblePageTemplate.id).where(
                WorldBiblePageTemplate.novel_id == nid,
                WorldBiblePageTemplate.template_key == template_key,
                WorldBiblePageTemplate.status == "active",
            )
        )
        if exists is None:
            raise ValidationError("Unknown or archived World Bible page template")

    async def _validate_asset_refs(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        refs: list[dict[str, Any]],
        *,
        allow_local_refs: bool = False,
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
            if allow_local_refs and ref_id.startswith("local:"):
                continue
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
                    "sections_json": page.sections_json,
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
        result = await db.execute(
            select(WorldBiblePageProjection).where(
                WorldBiblePageProjection.novel_id == page.novel_id,
                WorldBiblePageProjection.page_id == page.id,
            )
        )
        for projection in result.scalars().all():
            projection.stale = True
            projection.stale_checked_at = datetime.now(UTC)

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
        from modules.evidence.facade import mark_asset_context_changed

        try:
            await mark_asset_context_changed(
                db,
                novel_id=str(draft.novel_id),
                asset_type="world_bible_draft",
                asset_id=str(draft.id),
                reason=reason,
            )
        except Exception as exc:
            raise ConflictError(
                "参考资料状态同步失败，本次世界书工作稿修改未保存，请重试",
                code="world_bible_context_invalidation_failed",
            ) from exc

    @staticmethod
    def _default_page_key(page_type: str, title: str) -> str:
        from modules.world.services.worldbuilding.shared import normalize_profession_slug

        slug = normalize_profession_slug(title) or "page"
        return f"{page_type}:{slug}:{uuid.uuid4().hex[:8]}"

    @staticmethod
    def serialize_sections(
        sections: list[dict[str, Any]] | list[WorldBibleSection],
    ) -> list[dict[str, Any]]:
        return [
            item.model_dump(mode="json")
            if isinstance(item, WorldBibleSection)
            else dict(item)
            for item in sections
        ]

    _serialize_sections = serialize_sections

    @classmethod
    def _validate_section_refs(
        cls,
        sections: list[dict[str, Any]],
        refs: list[dict[str, Any]],
    ) -> None:
        available_hashes = {cls._asset_ref_hash(ref) for ref in refs}
        for section in sections:
            for ref_hash in section.get("linked_asset_ref_hashes") or []:
                normalized = str(ref_hash).removeprefix("sha256:")
                if normalized not in available_hashes:
                    raise ValidationError(
                        "World Bible section references must point to page asset refs"
                    )

    @classmethod
    def _canonical_asset_refs(cls, refs: list[dict[str, Any]]) -> set[str]:
        normalized: set[str] = set()
        for ref in refs:
            try:
                normalized.add(cls._normalize_asset_ref(ref).canonical_json())
            except (TypeError, ValueError):
                normalized.add(
                    json.dumps(
                        ref,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    )
                )
        return normalized

    @staticmethod
    def _normalize_asset_ref(ref: dict[str, Any]) -> TargetRef:
        target_type = str(
            ref.get("target_type") or ref.get("type") or ref.get("source_type") or ""
        )
        target_id = str(
            ref.get("target_id") or ref.get("id") or ref.get("source_id") or ""
        )
        aliases = {
            "entity": "core_entity",
            "profile": "core_entity",
            "event": "core_entity",
            "page": "world_bible_page",
            "relation": "entity_relation",
        }
        return TargetRef(
            target_type=aliases.get(target_type, target_type),
            target_id=target_id,
            target_path=str(ref.get("target_path") or ""),
        )

    @classmethod
    def _asset_ref_hash(cls, ref: dict[str, Any]) -> str:
        return cls._normalize_asset_ref(ref).target_hash()


__all__ = [
    "BUILTIN_WORLD_BIBLE_CATEGORIES",
    "WorldBibleLifecycleService",
]
