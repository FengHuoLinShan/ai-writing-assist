"""Author-facing attention summary owned by the World module."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.contracts import (
    WorldAttentionSummaryContract,
    WorldAuthorAttentionItemContract,
)
from modules.world.services.core.entity_alias_service import EntityAliasService
from modules.world.services.core.entity_relation_service import EntityRelationService
from modules.world.services.core.entity_service import WorldEntityService
from modules.world.services.worldbuilding.conflict_queue_service import (
    ConflictQueueService,
)
from modules.world.services.worldbuilding.suggestion_queue_service import (
    SuggestionQueueService,
)

_WORLD_PAGE_SIZE = 50


def _value(item: object, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _metadata_value(payload: object, name: str) -> Any:
    value = _value(payload, name)
    if value is not None and value != "":
        return value
    meta = _value(payload, "_meta")
    return meta.get(name) if isinstance(meta, dict) else None


def _positive_chapter(*payloads: object) -> int | None:
    for payload in payloads:
        value = _metadata_value(payload, "source_chapter_index")
        if value is None:
            value = _metadata_value(payload, "chapter_index")
        try:
            chapter = int(value)
        except (TypeError, ValueError):
            continue
        if chapter >= 0:
            return chapter
    return None


def _scene_id(*payloads: object) -> str | None:
    for payload in payloads:
        value = _metadata_value(payload, "scene_id")
        if value:
            return str(value)
    return None


def _severity(value: object, *, default: str = "medium") -> str:
    normalized = str(value or default).lower()
    if normalized == "critical":
        return "high"
    return normalized if normalized in {"high", "medium", "low", "info"} else default


def _has_compatibility_shadow(item: object) -> bool:
    result = _value(item, "result_ref_json", {}) or {}
    if result.get("type") == "core_entity_compatibility":
        return True
    payload = _value(item, "payload_json", {}) or {}
    meta = payload.get("_meta") if isinstance(payload, dict) else None
    return bool(
        payload.get("compatibility_shadow")
        or (isinstance(meta, dict) and meta.get("compatibility_shadow"))
    )


def _source_refs(item: object, payload: dict[str, Any]) -> list[dict[str, Any]]:
    refs = [
        ref
        for ref in [
            *list(_value(item, "evidence_refs_json", []) or []),
            *list(payload.get("source_refs") or []),
        ]
        if isinstance(ref, dict)
    ]
    for package_item in payload.get("items") or []:
        if isinstance(package_item, dict):
            refs.extend(
                ref
                for ref in package_item.get("source_refs") or []
                if isinstance(ref, dict)
            )
    return refs


def _updated_at(*items: object) -> datetime | None:
    values = [
        value
        for item in items
        if isinstance((value := _value(item, "updated_at")), datetime)
    ]
    if not values:
        return None
    return max(
        values,
        key=lambda value: (
            value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        ).timestamp(),
    )


class WorldAttentionSummaryService:
    """Aggregate existing World review queues without leaking their raw shapes."""

    def __init__(
        self,
        *,
        entity_service: WorldEntityService | None = None,
        alias_service: EntityAliasService | None = None,
        relation_service: EntityRelationService | None = None,
        conflict_service: ConflictQueueService | None = None,
        suggestion_service: SuggestionQueueService | None = None,
    ) -> None:
        self._entity_service = entity_service or WorldEntityService()
        self._alias_service = alias_service or EntityAliasService()
        self._relation_service = relation_service or EntityRelationService()
        self._conflict_service = conflict_service or ConflictQueueService()
        self._suggestion_service = suggestion_service or SuggestionQueueService()

    async def _review_entities(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> tuple[list[object], int]:
        items: list[object] = []
        skip = 0
        total = 0
        while True:
            page = await self._entity_service.list(
                db,
                novel_id,
                display_state="review",
                skip=skip,
                limit=_WORLD_PAGE_SIZE,
            )
            page_items = list(_value(page, "items", []) or [])
            total = int(_value(page, "total", total) or 0)
            items.extend(page_items)
            if not page_items or len(items) >= total:
                return items, total
            skip += len(page_items)

    async def _review_groups(
        self,
        service: object,
        db: AsyncSession,
        novel_id: str,
    ) -> tuple[list[object], int]:
        groups: list[object] = []
        skip = 0
        item_total = 0
        while True:
            page = await service.list_review_groups(  # type: ignore[attr-defined]
                db,
                novel_id,
                skip=skip,
                limit=_WORLD_PAGE_SIZE,
            )
            page_groups = list(_value(page, "groups", []) or [])
            group_total = int(_value(page, "group_total", len(page_groups)) or 0)
            item_total = int(_value(page, "item_total", item_total) or 0)
            groups.extend(page_groups)
            if not page_groups or len(groups) >= group_total:
                return groups, item_total
            skip += len(page_groups)

    async def _pending_suggestions(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[object]:
        items: list[object] = []
        skip = 0
        while True:
            page, total = await self._suggestion_service.list(
                db,
                novel_id,
                status="pending",
                skip=skip,
                limit=_WORLD_PAGE_SIZE,
            )
            items.extend(page)
            if not page or len(items) >= int(total or 0):
                return items
            skip += len(page)

    @staticmethod
    def _entity_item(item: object) -> WorldAuthorAttentionItemContract:
        item_id = str(_value(item, "id"))
        content = _value(item, "content_json", {}) or {}
        name = str(_value(item, "name") or "未命名对象")
        return WorldAuthorAttentionItemContract(
            key=f"world:object:{item_id}",
            source_kind="world_object",
            title=f"审核世界对象：{name}",
            summary="确认是否采用这条世界设定。",
            author_action="needs_decision",
            severity="medium",
            target_kind="world_review_objects",
            item_id=item_id,
            chapter_index=_positive_chapter(content),
            scene_id=_scene_id(content),
            updated_at=_updated_at(item),
        )

    @staticmethod
    def _alias_item(group: object) -> WorldAuthorAttentionItemContract:
        group_id = str(_value(group, "group_id"))
        members = list(_value(group, "members", []) or [])
        name = str(_value(group, "entity_name") or "未命名对象")
        first = members[0] if members else {}
        member_count = int(_value(group, "member_count", len(members)) or 0)
        return WorldAuthorAttentionItemContract(
            key=f"world:alias:{group_id}",
            source_kind="world_alias_group",
            title=f"审核{name}的别名",
            summary=f"有 {member_count} 个别名待确认。",
            author_action="needs_decision",
            severity="medium",
            target_kind="world_review_aliases",
            item_id=group_id,
            chapter_index=_positive_chapter(first),
            scene_id=_scene_id(first),
            updated_at=_updated_at(*members),
        )

    @staticmethod
    def _relation_item(group: object) -> WorldAuthorAttentionItemContract:
        group_id = str(_value(group, "group_id"))
        members = list(_value(group, "members", []) or [])
        source_name = str(_value(group, "source_name") or "一个对象")
        target_name = str(_value(group, "target_name") or "另一个对象")
        evidence = _value(members[0], "evidence_summary", {}) if members else {}
        chapters = list(_value(group, "source_chapter_indices", []) or [])
        member_count = int(_value(group, "member_count", len(members)) or 0)
        return WorldAuthorAttentionItemContract(
            key=f"world:relation:{group_id}",
            source_kind="world_relation_group",
            title=f"审核{source_name}与{target_name}的关系",
            summary=f"有 {member_count} 条关系待确认。",
            author_action="needs_decision",
            severity="medium",
            target_kind="world_review_relations",
            item_id=group_id,
            chapter_index=(int(chapters[0]) if chapters else _positive_chapter(evidence)),
            scene_id=_scene_id(evidence),
            updated_at=_updated_at(*members),
        )

    @staticmethod
    def _conflict_item(item: object) -> WorldAuthorAttentionItemContract:
        item_id = str(_value(item, "id"))
        target = _value(item, "target", {}) or {}
        resolution = _value(item, "resolution_json", {}) or {}
        refs = _source_refs(item, {})
        action = str(resolution.get("author_action") or "can_improve")
        if action not in {"needs_decision", "can_improve"}:
            action = "can_improve"
        return WorldAuthorAttentionItemContract(
            key=f"world:conflict:{item_id}",
            source_kind="world_conflict",
            title=(
                "世界设定需要确认"
                if action == "needs_decision"
                else "世界设定可以改进"
            ),
            summary=str(_value(item, "summary") or "查看世界设定检查结果。"),
            author_action=action,
            severity=_severity(_value(item, "severity")),
            target_kind="world_bible_conflict",
            item_id=item_id,
            chapter_index=_positive_chapter(target, resolution, *refs),
            scene_id=_scene_id(target, resolution, *refs),
            page_id=(str(target.get("page_id")) if target.get("page_id") else None),
            updated_at=_updated_at(item),
        )

    @staticmethod
    def _suggestion_item(item: object) -> WorldAuthorAttentionItemContract:
        item_id = str(_value(item, "id"))
        payload = _value(item, "payload_json", {}) or {}
        refs = _source_refs(item, payload)
        page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
        target_type = str(_value(item, "target_type") or "")
        default_title = (
            "世界设定采用包"
            if target_type == "world_adoption_package"
            else "世界设定建议"
        )
        title = str(
            payload.get("title")
            or payload.get("name")
            or page.get("title")
            or default_title
        )
        return WorldAuthorAttentionItemContract(
            key=f"world:suggestion:{item_id}",
            source_kind="world_suggestion",
            title=f"确认待采用建议：{title}",
            summary="查看建议并决定是否采用。",
            author_action="needs_decision",
            severity=_severity(_value(item, "risk_level"), default="low"),
            target_kind=(
                "world_adoption"
                if target_type == "world_adoption_package"
                else "world_suggestion"
            ),
            item_id=item_id,
            chapter_index=_positive_chapter(payload, *refs),
            scene_id=_scene_id(payload, *refs),
            page_id=(
                str(payload.get("page_id") or payload.get("target_page_id"))
                if payload.get("page_id") or payload.get("target_page_id")
                else None
            ),
            suggestion_id=item_id,
            updated_at=_updated_at(item),
        )

    async def get_summary(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> WorldAttentionSummaryContract:
        entities, entity_total = await self._review_entities(db, novel_id)
        aliases, alias_total = await self._review_groups(
            self._alias_service, db, novel_id
        )
        relations, relation_total = await self._review_groups(
            self._relation_service, db, novel_id
        )
        conflicts, _ = await self._conflict_service.list(
            db,
            novel_id,
            status="pending",
        )
        suggestions = await self._pending_suggestions(db, novel_id)

        suggestion_items = [
            self._suggestion_item(item)
            for item in suggestions
            if _value(item, "target_type")
            not in {"world_core_checkpoint", "world_design_checkpoint"}
            and _value(item, "status") == "pending"
            and not _has_compatibility_shadow(item)
        ]
        items = [
            *(self._conflict_item(item) for item in conflicts),
            *(self._entity_item(item) for item in entities),
            *(self._alias_item(group) for group in aliases),
            *(self._relation_item(group) for group in relations),
            *suggestion_items,
        ]
        return WorldAttentionSummaryContract(
            novel_id=novel_id,
            world_objects=entity_total,
            world_aliases=alias_total,
            world_relations=relation_total,
            items=tuple(items),
        )
