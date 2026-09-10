"""Read-only cross-module impact enumeration for world assets (ADR-0022).

The World module owns the review aggregation, but it never writes to other
domains: Story threads and manuscript prose are read through their stable
facades, map atlas nodes stay a same-module association, and every section
carries explicit uncovered notes so the preview can never be presented as a
complete dependency proof it did not actually perform.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.models import (
    Character,
    CoreEntity,
    EntityRelation,
    WorldBiblePage,
    WorldBiblePageDraft,
)
from modules.world.schemas import (
    WorldImpactPreviewItem,
    WorldImpactPreviewResponse,
    WorldImpactPreviewSection,
    WorldImpactPreviewTarget,
    WorldImpactSourceReadRequest,
    WorldImpactSourceReadResponse,
)
from modules.world.services.worldbuilding.world_validation_engine import stable_hash
from shared.target_ref import TargetRef
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)

_ADOPTED_STATUSES = ("canonical", "confirmed")
_AFFECTED_PAGE_CAP = 200
_TERM_CAP = 8
_PROSE_SCAN_ITERATIONS = 50


class WorldImpactService:
    """Enumerate proven dependents of a world page / entity / relation."""

    @staticmethod
    def _stamp(value):
        if isinstance(value, datetime):
            return (
                value.replace(tzinfo=UTC)
                if value.tzinfo is None
                else value.astimezone(UTC)
            ).isoformat()
        return str(value or "")

    @staticmethod
    def _row_hash(row):
        return stable_hash(
            {
                column.name: WorldImpactService._stamp(value)
                if isinstance(value, datetime)
                else value
                for column in row.__table__.columns
                for value in [getattr(row, column.name)]
            }
        )

    async def read_source(
        self, db: AsyncSession, data: WorldImpactSourceReadRequest
    ) -> WorldImpactSourceReadResponse:
        from pydantic import TypeAdapter

        from modules.writing.contracts import SourceRangeRefContract
        from modules.writing.facade import (
            get_manuscript_source_manifest,
            read_manuscript_range,
        )

        item = data.item
        if not item.source_hash:
            raise ConflictError("该记录缺少来源版本，请刷新影响清单")
        nid = parse_uuid(data.novel_id, "novel_id")
        source_ref = None
        target_ref = {
            "target_type": "core_entity" if item.kind == "character" else item.kind,
            "target_id": item.id,
            "target_path": "",
        }
        if item.kind == "prose_chapter":
            ref = TypeAdapter(SourceRangeRefContract).validate_python(item.source_ref)
            if str(ref.chapter_index) != item.id:
                raise ValidationError("正文选段与章节不匹配")
            target_ref = None
            manifest = await get_manuscript_source_manifest(
                db,
                data.novel_id,
                content_mode=ref.content_mode,
                chapter_from=ref.chapter_index,
                chapter_to=ref.chapter_index,
            )
            if not any(
                str(row["draft_id"]) == ref.draft_id
                and row["source_hash"] == ref.source_hash
                for row in manifest
            ):
                raise ConflictError("正文版本已变化，请刷新影响清单后核对")
            result = await read_manuscript_range(
                db, data.novel_id, ref, before=0, after=0
            )
            text = result.text[result.highlight_start : result.highlight_end]
            source_ref = asdict(result.source_ref)
            source_hash = result.source_ref.range_hash
            label = result.title or f"第 {ref.chapter_index} 章"
        elif item.kind in {
            "story_thread",
            "outline_arc",
            "outline_scene",
            "story_outline",
        }:
            from modules.story.facade import read_world_dependency

            result = await read_world_dependency(db, data.novel_id, item.kind, item.id)
            text, source_hash, label = result.text, result.source_hash, result.label
        else:
            models = {
                "world_bible_page": WorldBiblePage,
                "core_entity": CoreEntity,
                "entity_relation": EntityRelation,
                "character": Character,
                "map_node": MapAtlasNode,
            }
            model = models[item.kind]
            identity = Character.entity_id if item.kind == "character" else model.id
            row = await db.scalar(
                select(model)
                .where(
                    model.novel_id == nid, identity == parse_uuid(item.id, "source_id")
                )
                .execution_options(populate_existing=True)
            )
            if row is None:
                raise NotFoundError("来源已不存在或不属于当前作品")
            source_hash = self._row_hash(row)
            label = (
                getattr(row, "title", None) or getattr(row, "name", None) or "对象关系"
            )
            text = "\n\n".join(
                str(getattr(row, key))
                for key in (
                    "title",
                    "name",
                    "free_text",
                    "summary",
                    "description",
                    "relation_type",
                    "personality",
                    "background",
                )
                if getattr(row, key, None)
            )
            if item.kind == "world_bible_page":
                text += "\n\n" + "\n\n".join(
                    str(section.get("body_markdown") or "")
                    for section in row.sections_json or []
                    if isinstance(section, dict)
                )
            if item.kind == "map_node" and row.current_revision_id:
                revision = await db.scalar(
                    select(MapAtlasRevision).where(
                        MapAtlasRevision.id == row.current_revision_id,
                        MapAtlasRevision.novel_id == nid,
                        MapAtlasRevision.node_id == row.id,
                    )
                )
                if revision is None:
                    raise ConflictError("地图的当前版本不可用")
                features = {
                    feature["id"]: feature
                    for feature in revision.document.get("features", [])
                }
                text += "\n\n" + "\n".join(
                    f"{feature['label']}：{feature.get('note') or '已记录空间位置'}"
                    for feature in features.values()
                )
                relations = {
                    "inside": "位于内部",
                    "north": "位于北面",
                    "south": "位于南面",
                    "east": "位于东面",
                    "west": "位于西面",
                    "northeast": "位于东北",
                    "northwest": "位于西北",
                    "southeast": "位于东南",
                    "southwest": "位于西南",
                    "adjacent": "相邻",
                    "connects": "连接",
                    "passes_through": "穿过",
                    "along_street": "沿街",
                    "entrance_to": "入口通向",
                    "faces": "面向",
                }
                text += "\n" + "\n".join(
                    f"{features.get(edge['subject'], {}).get('label', '未解析位置')} "
                    f"{relations.get(edge['relation'], '关联')} "
                    f"{features.get(edge['target'], {}).get('label', '未解析位置')}"
                    for edge in revision.document.get("constraints", [])
                )
        if source_hash != item.source_hash:
            raise ConflictError("来源已在预演后变化，请刷新清单；旧记录未覆盖当前版本")
        return WorldImpactSourceReadResponse(
            label=label,
            text=text[:200_000],
            source_hash=source_hash,
            target_ref=target_ref,
            source_ref=source_ref,
            truncated=len(text) > 200_000,
        )

    async def preview(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        target_type: str,
        target_id: str,
    ) -> WorldImpactPreviewResponse:
        if target_type not in {"world_bible_page", "core_entity", "entity_relation"}:
            raise ValidationError("Unsupported impact preview target")
        nid = parse_uuid(novel_id, "novel_id")
        tid = parse_uuid(target_id, "target_id")

        root_entity_ids: list[str] = []
        root_terms: list[str] = []
        label: str | None = None
        if target_type == "world_bible_page":
            page = await db.scalar(
                select(WorldBiblePage).where(
                    WorldBiblePage.id == tid,
                    WorldBiblePage.novel_id == nid,
                )
            )
            if page is None:
                raise NotFoundError("World Bible page not found")
            label = page.title
            root_terms = self._page_terms(page.title, page.page_meta_json)
        elif target_type == "core_entity":
            entity = await db.scalar(
                select(CoreEntity).where(CoreEntity.id == tid, CoreEntity.novel_id == nid)
            )
            if entity is None:
                raise NotFoundError("Core entity not found")
            label = entity.name
            root_entity_ids = [str(entity.id)]
            root_terms = [entity.name, *self._entity_aliases(entity)][:_TERM_CAP]
        else:
            relation = await db.scalar(
                select(EntityRelation).where(
                    EntityRelation.id == tid, EntityRelation.novel_id == nid
                )
            )
            if relation is None:
                raise NotFoundError("Entity relation not found")
            label = relation.relation_type or "对象关系"
            root_entity_ids = [str(relation.source_id), str(relation.target_id)]

        pages = list(
            (
                await db.execute(
                    select(WorldBiblePage)
                    .where(
                        WorldBiblePage.novel_id == nid,
                        WorldBiblePage.status.in_(_ADOPTED_STATUSES),
                    )
                    .order_by(WorldBiblePage.page_key, WorldBiblePage.id)
                )
            )
            .scalars()
            .all()
        )
        page_section = self._page_dependents(pages, target_type, str(tid))
        entity_section, related_entity_ids = await self._entity_dependents(
            db, nid, target_type=target_type, target_id=str(tid), pages=pages
        )
        root_entity_ids = list(dict.fromkeys([*root_entity_ids, *related_entity_ids]))

        character_section = await self._character_dependents(db, nid, root_entity_ids)
        thread_section = await self._thread_dependents(
            db, novel_id, root_entity_ids, root_terms
        )
        prose_section = await self._prose_dependents(
            db, novel_id, root_terms or [label or ""]
        )
        map_section = await self._map_dependents(db, nid, root_entity_ids)

        sections = [
            page_section,
            entity_section,
            character_section,
            thread_section,
            prose_section,
            map_section,
        ]
        complete = all(not section.truncated for section in sections) and not any(
            note.startswith("read_failed:")
            for section in sections
            for note in section.uncovered
        )
        return WorldImpactPreviewResponse(
            target=WorldImpactPreviewTarget(
                target_type=target_type, target_id=str(tid), label=label
            ),
            sections=sections,
            uncovered=self._global_uncovered(sections),
            complete=complete,
            scope_hash=stable_hash(
                {
                    "root": self._row_hash(
                        page
                        if target_type == "world_bible_page"
                        else entity
                        if target_type == "core_entity"
                        else relation
                    ),
                    "pages": [self._row_hash(item) for item in pages],
                    "sections": [section.model_dump(mode="json") for section in sections],
                }
            ),
        )

    async def snapshot(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        scope: str,
        target_type: str | None,
        target_id: str | None,
        root_type: str | None = None,
    ) -> dict[str, Any]:
        """Frozen impact inventory persisted on a validation run at creation."""
        nid = parse_uuid(novel_id, "novel_id")
        if scope == "full":
            page_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(WorldBiblePage)
                    .where(
                        WorldBiblePage.novel_id == nid,
                        WorldBiblePage.status.in_(_ADOPTED_STATUSES),
                    )
                )
                or 0
            )
            entity_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(CoreEntity)
                    .where(CoreEntity.novel_id == nid, CoreEntity.status == "canonical")
                )
                or 0
            )
            relation_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(EntityRelation)
                    .where(
                        EntityRelation.novel_id == nid,
                        EntityRelation.status == "canonical",
                    )
                )
                or 0
            )
            return {
                "mode": "full_inventory",
                "adopted_pages": page_count,
                "canonical_entities": entity_count,
                "canonical_relations": relation_count,
                "note": "完整检查以冻结 manifest 为准，本清单仅记录库内规模",
            }
        if not target_type or not target_id:
            return {"mode": "none"}
        if target_type == "semantic_gap" and root_type:
            if root_type == "core_entity":
                target_type = "core_entity"
            elif root_type == "world_bible_page":
                target_type = "world_bible_page"
            else:
                page_id = await db.scalar(
                    select(WorldBiblePageDraft.page_id).where(
                        WorldBiblePageDraft.id == parse_uuid(target_id, "target_id"),
                        WorldBiblePageDraft.novel_id == nid,
                    )
                )
                if page_id is None:
                    return {"mode": "semantic_gap", "root": target_id}
                target_type, target_id = "world_bible_page", str(page_id)
        elif target_type == "world_bible_draft":
            page_id = await db.scalar(
                select(WorldBiblePageDraft.page_id).where(
                    WorldBiblePageDraft.id == parse_uuid(target_id, "target_id"),
                    WorldBiblePageDraft.novel_id == nid,
                )
            )
            if page_id is None:
                return {
                    "mode": "draft_without_page",
                    "note": "独立工作稿尚无已发布页，页面级影响待发布预演列出",
                }
            target_type, target_id = "world_bible_page", str(page_id)
        elif target_type == "world_adoption_package":
            return {
                "mode": "adoption_package",
                "note": "采用包影响以采用预览的页面 diff 为准",
            }
        try:
            preview = await self.preview(
                db, novel_id, target_type=target_type, target_id=target_id
            )
        except (NotFoundError, ValidationError):
            return {"mode": "none"}
        return {
            "mode": "targeted",
            "target": {"target_type": target_type, "target_id": target_id},
            "sections": {
                section.section: {
                    "count": len(section.items),
                    "truncated": section.truncated,
                    "uncovered": section.uncovered,
                    "items": [item.model_dump(mode="json") for item in section.items],
                }
                for section in preview.sections
            },
            "uncovered": preview.uncovered,
            "complete": preview.complete,
            "scope_hash": preview.scope_hash,
        }

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    @staticmethod
    def _page_dependents(
        pages: list[WorldBiblePage],
        target_type: str,
        target_id: str,
    ) -> WorldImpactPreviewSection:
        """Reverse typed-reference BFS over adopted pages (distance + relation)."""
        edges: dict[str, list[tuple[str, str]]] = {}
        for page in pages:
            for ref in page.linked_asset_refs_json or []:
                try:
                    target = TargetRef.model_validate(
                        {
                            "target_type": ref.get("target_type") or ref.get("type"),
                            "target_id": ref.get("target_id") or ref.get("id"),
                            "target_path": ref.get("target_path") or "",
                            "relation": ref.get("relation") or "informs",
                        }
                    )
                except Exception:
                    continue
                edges.setdefault(target.target_id, []).append(
                    (str(page.id), target.relation)
                )
        title_map = {str(page.id): page for page in pages}
        queue: list[tuple[str, int]] = [(target_id, 0)]
        seen = {target_id}
        items: list[WorldImpactPreviewItem] = []
        truncated = False
        while queue:
            current, distance = queue.pop(0)
            for referrer_id, relation in sorted(edges.get(current, [])):
                page = title_map.get(referrer_id)
                if page is None or referrer_id in seen:
                    continue
                seen.add(referrer_id)
                if len(items) >= _AFFECTED_PAGE_CAP:
                    truncated = True
                    continue
                items.append(
                    WorldImpactPreviewItem(
                        kind="world_bible_page",
                        id=referrer_id,
                        label=page.title,
                        version=f"v{page.version_number}",
                        source_hash=WorldImpactService._row_hash(page),
                        target_ref={
                            "target_type": "world_bible_page",
                            "target_id": str(page.id),
                            "target_path": "",
                        },
                        distance=distance + 1,
                        detail=(
                            f"经 {relation} 引用本目标"
                            if relation != "informs"
                            else "直接参考本目标"
                        ),
                    )
                )
                queue.append((referrer_id, distance + 1))
        return WorldImpactPreviewSection(
            section="world_pages",
            items=sorted(items, key=lambda item: (item.distance or 0, item.label)),
            uncovered=(
                []
                if not truncated
                else [
                    f"受影响页面超过 {_AFFECTED_PAGE_CAP} 个，"
                    f"仅列示前 {_AFFECTED_PAGE_CAP} 个"
                ]
            ),
            truncated=truncated,
        )

    @staticmethod
    async def _entity_dependents(
        db: AsyncSession,
        nid,
        *,
        target_type: str,
        target_id: str,
        pages: list[WorldBiblePage],
    ) -> tuple[WorldImpactPreviewSection, list[str]]:
        """Entities provably tied to the target: declared page refs + relations."""
        entity_ids: set[str] = set()
        if target_type == "core_entity":
            entity_ids.add(target_id)
        elif target_type == "world_bible_page":
            for page in pages:
                if str(page.id) != target_id:
                    continue
                for ref in page.linked_asset_refs_json or []:
                    if str(ref.get("target_type") or ref.get("type") or "") in {
                        "core_entity",
                        "entity",
                    }:
                        entity_ids.add(str(ref.get("target_id") or ref.get("id") or ""))
        relations = list(
            (
                await db.execute(
                    select(EntityRelation)
                    .where(
                        EntityRelation.novel_id == nid,
                        EntityRelation.status == "canonical",
                    )
                    .order_by(EntityRelation.id)
                )
            )
            .scalars()
            .all()
        )
        items: list[WorldImpactPreviewItem] = []
        related: set[str] = set(entity_ids)
        for relation in relations:
            endpoints = {str(relation.source_id), str(relation.target_id)}
            tied = target_type == "entity_relation" and str(relation.id) == target_id
            if tied:
                related |= endpoints
                continue
            if target_type == "core_entity" and target_id in endpoints:
                related |= endpoints
                items.append(
                    WorldImpactPreviewItem(
                        kind="entity_relation",
                        id=str(relation.id),
                        label=(
                            f"{relation.relation_type} 关系"
                            if relation.relation_type
                            else "对象关系"
                        ),
                        version=WorldImpactService._stamp(
                            relation.updated_at or relation.created_at
                        ),
                        source_hash=WorldImpactService._row_hash(relation),
                        target_ref={
                            "target_type": "entity_relation",
                            "target_id": str(relation.id),
                            "target_path": "",
                        },
                        detail="关系的另一端或本对象受影响",
                    )
                )
        return (
            WorldImpactPreviewSection(
                section="world_entities",
                items=items[:_AFFECTED_PAGE_CAP],
                uncovered=[],
                truncated=len(items) > _AFFECTED_PAGE_CAP,
            ),
            sorted(related),
        )

    @staticmethod
    async def _character_dependents(
        db: AsyncSession, nid, entity_ids: list[str]
    ) -> WorldImpactPreviewSection:
        if not entity_ids:
            return WorldImpactPreviewSection(
                section="characters",
                items=[],
                uncovered=["目标未直接关联对象，人物档案层未纳入本次预演"],
            )
        uuid_ids = []
        for item in entity_ids:
            try:
                uuid_ids.append(parse_uuid(item, "entity_id"))
            except Exception:
                continue
        rows = list(
            (
                await db.execute(
                    select(Character)
                    .where(
                        Character.novel_id == nid,
                        Character.entity_id.in_(uuid_ids),
                    )
                    .order_by(Character.entity_id)
                )
            )
            .scalars()
            .all()
        )
        return WorldImpactPreviewSection(
            section="characters",
            items=[
                WorldImpactPreviewItem(
                    kind="character",
                    id=str(row.entity_id),
                    label=row.name,
                    detail="人物档案绑定该对象",
                    source_hash=WorldImpactService._row_hash(row),
                    version=WorldImpactService._stamp(row.updated_at or row.created_at),
                    target_ref={
                        "target_type": "core_entity",
                        "target_id": str(row.entity_id),
                        "target_path": "",
                    },
                )
                for row in rows[:_AFFECTED_PAGE_CAP]
            ],
            uncovered=(
                []
                if len(rows) <= _AFFECTED_PAGE_CAP
                else ["人物档案超过上限，仅列示部分"]
            ),
            truncated=len(rows) > _AFFECTED_PAGE_CAP,
        )

    @staticmethod
    async def _thread_dependents(db, novel_id, entity_ids, terms=()):
        from modules.story.facade import list_world_dependencies

        try:
            sources = await list_world_dependencies(db, novel_id, entity_ids, list(terms))
        except Exception:
            logger.exception("story impact lookup failed")
            return WorldImpactPreviewSection(
                section="story_threads", uncovered=["read_failed:故事结构读取失败"]
            )
        return WorldImpactPreviewSection(
            section="story_threads",
            items=[
                WorldImpactPreviewItem(
                    kind=item.kind,
                    id=item.id,
                    label=item.label,
                    version=item.version,
                    source_hash=item.source_hash,
                    match_basis=item.match_basis,
                    target_ref={
                        "target_type": item.kind,
                        "target_id": item.id,
                        "target_path": "",
                    },
                    detail="声明关联"
                    if item.match_basis == "declared"
                    else "总纲中的名称提及，仍需核对",
                )
                for item in sources[:_AFFECTED_PAGE_CAP]
            ],
            scope_hash=stable_hash(
                [(item.kind, item.id, item.source_hash) for item in sources]
            ),
            truncated=len(sources) > _AFFECTED_PAGE_CAP,
            uncovered=["只列声明关联和总纲中的名称提及；未声明的隐含依赖仍需定向检查"],
        )

    @staticmethod
    async def _prose_dependents(
        db: AsyncSession, novel_id: str, terms: list[str]
    ) -> WorldImpactPreviewSection:
        cleaned = [term for term in terms if term and term.strip()][:_TERM_CAP]
        if not cleaned:
            return WorldImpactPreviewSection(
                section="prose",
                items=[],
                uncovered=["目标没有可用于正文字面匹配的名称"],
            )
        try:
            from modules.writing.facade import (
                get_manuscript_source_manifest,
                scan_manuscript_terms,
            )

            rows = await get_manuscript_source_manifest(
                db, novel_id, content_mode="canonical"
            )
            manifest = {row["draft_id"]: row["source_hash"] for row in rows}
            hits: dict[int, dict[str, Any]] = {}
            cursor = None
            for _ in range(_PROSE_SCAN_ITERATIONS):
                scan = await scan_manuscript_terms(
                    db,
                    novel_id,
                    cleaned,
                    source_manifest=manifest,
                    content_mode="canonical",
                    chapters_per_batch=100,
                    limit=80,
                    cursor=cursor,
                )
                for hit in scan.hits:
                    chapter = hit.source_ref.chapter_index
                    entry = hits.setdefault(
                        chapter,
                        {
                            "title": hit.title,
                            "count": 0,
                            "source_hash": hit.source_ref.range_hash,
                            "source_ref": asdict(hit.source_ref),
                        },
                    )
                    entry["count"] += hit.match_count
                cursor = scan.cursor
                if cursor is None:
                    break
            items = [
                WorldImpactPreviewItem(
                    kind="prose_chapter",
                    id=str(chapter),
                    label=f"第 {chapter} 章",
                    source_hash=str(entry["source_hash"] or "") or None,
                    detail=f"正文出现 {entry['count']} 次（字面匹配，打开首个精确选段）",
                    source_ref=entry["source_ref"],
                    version=str(entry["source_ref"]["version_number"]),
                    match_basis="literal",
                )
                for chapter, entry in sorted(hits.items())
            ]
        except Exception:
            logger.exception("prose impact scan failed")
            return WorldImpactPreviewSection(
                section="prose",
                items=[],
                uncovered=["read_failed:正文扫描失败，本次预演未覆盖正文"],
            )
        return WorldImpactPreviewSection(
            section="prose",
            items=items,
            truncated=cursor is not None,
            scope_hash=stable_hash(manifest),
            uncovered=[
                "正文按名称/别名字面匹配：代词、改写与未列别名无法覆盖",
                *(["正文扫描已达批次上限，仍有章节未检查"] if cursor is not None else []),
            ],
        )

    @staticmethod
    async def _map_dependents(
        db: AsyncSession, nid, entity_ids: list[str]
    ) -> WorldImpactPreviewSection:
        if not entity_ids:
            return WorldImpactPreviewSection(
                section="map",
                items=[],
                uncovered=["目标未直接关联对象，地图层未纳入本次预演"],
            )
        uuid_ids = []
        for item in entity_ids:
            try:
                uuid_ids.append(parse_uuid(item, "entity_id"))
            except Exception:
                continue
        nodes = list(
            (
                await db.execute(
                    select(MapAtlasNode)
                    .where(
                        MapAtlasNode.novel_id == nid,
                        MapAtlasNode.location_entity_id.in_(uuid_ids),
                    )
                    .order_by(MapAtlasNode.id)
                    .limit(_AFFECTED_PAGE_CAP + 1)
                )
            )
            .scalars()
            .all()
        )
        truncated = len(nodes) > _AFFECTED_PAGE_CAP
        return WorldImpactPreviewSection(
            section="map",
            items=[
                WorldImpactPreviewItem(
                    kind="map_node",
                    id=str(node.id),
                    label=node.title,
                    version=str(
                        node.current_revision_id or node.updated_at or node.created_at
                    ),
                    source_hash=WorldImpactService._row_hash(node),
                    target_ref={
                        "target_type": "map_node",
                        "target_id": str(node.id),
                        "target_path": "",
                    },
                    detail=f"地图层级 {node.level}，以该地点对象为空间依据",
                )
                for node in nodes[:_AFFECTED_PAGE_CAP]
            ],
            uncovered=[
                "Scene 级依赖仅按章节粒度列示，未逐一核对场景脚本；地图标注引用未纳入"
            ],
            truncated=truncated,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _page_terms(title: str, metadata: dict | None) -> list[str]:
        raw = dict(metadata or {}).get("aliases")
        aliases = [str(item) for item in raw] if isinstance(raw, list) else []
        return [title, *aliases][:_TERM_CAP]

    @staticmethod
    def _entity_aliases(entity: CoreEntity) -> list[str]:
        content = dict(getattr(entity, "content_json", None) or {})
        aliases = content.get("aliases")
        if not isinstance(aliases, list):
            return []
        return [
            item if isinstance(item, str) else str(item["alias"])
            for item in aliases
            if (isinstance(item, str) and item.strip())
            or (
                isinstance(item, dict)
                and item.get("alias")
                and item.get("status", "canonical") in _ADOPTED_STATUSES
                and not item.get("needs_review")
            )
        ]

    @staticmethod
    def _global_uncovered(sections: list[WorldImpactPreviewSection]) -> list[str]:
        notes: list[str] = []
        for section in sections:
            notes.extend(section.uncovered)
        notes.append("证据分片的实体标注与语义相似改写未纳入本次预演")
        return notes


__all__ = ["WorldImpactService"]
