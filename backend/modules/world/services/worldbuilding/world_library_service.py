"""World library unified listing, topic directory and author workspace.

The topic directory is purely an authoring organization tool: it never feeds
geography, canon facts, or generation context.  Members reference existing
Page / Draft / Entity rows only, and one item may belong to many topics.
"""

from __future__ import annotations

import json
import uuid as uuid_module
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Text,
    and_,
    case,
    delete,
    desc,
    func,
    literal,
    nullslast,
    or_,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.asset_state import (
    ACTIVE_DISPLAY_STATUSES,
    ARCHIVED_DISPLAY_STATUSES,
    statuses_for_display_state,
)
from modules.world.models import (
    CoreEntity,
    WorldBiblePage,
    WorldBiblePageDraft,
    WorldLibraryFavorite,
    WorldLibraryRecent,
    WorldLibraryTopic,
    WorldLibraryTopicMember,
    WorldLibraryWorkspaceProfile,
)
from modules.world.schemas import (
    WorldLibraryFavoriteResponse,
    WorldLibraryItemResponse,
    WorldLibraryListResponse,
    WorldLibraryMemberRequest,
    WorldLibraryOverviewResponse,
    WorldLibraryTopicCreate,
    WorldLibraryTopicMoveRequest,
    WorldLibraryTopicNode,
    WorldLibraryTopicReorderRequest,
    WorldLibraryTopicUpdate,
    WorldLibraryViewPrefsResponse,
)
from modules.world.services.common import parse_uuid
from shared.constants import MAX_PAGE_SIZE

DEFAULT_LIBRARY_LIMIT = 50
LIBRARY_HOME_LIMIT = 8
LIBRARY_RECENTS_CAP = 50
LIBRARY_VIEW_PREFS_MAX_BYTES = 8_000

_LIBRARY_KINDS = ("all", "entity", "page", "draft")
_LIBRARY_SORTS = ("updated", "recent", "title", "created")
_SUMMARY_LENGTH = 240


def _state_case(status_column: Any) -> Any:
    return case(
        (status_column.in_(tuple(ACTIVE_DISPLAY_STATUSES)), literal("active")),
        (status_column.in_(tuple(ARCHIVED_DISPLAY_STATUSES)), literal("archived")),
        else_=literal("review"),
    )


def _trimmed(*values: Any) -> Any:
    return func.substr(func.coalesce(*values, literal("")), 1, _SUMMARY_LENGTH)


class WorldLibraryService:
    """统一资料列表、主题目录与作者工作区。"""

    # ============================================================
    # Unified library list
    # ============================================================

    async def list_library(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        q: str | None = None,
        target_id: str | None = None,
        kind: str | None = "all",
        item_type: str | None = None,
        state: str | None = None,
        working: bool | None = None,
        favorite: bool | None = None,
        topic_id: str | None = None,
        topic_scope: str = "subtree",
        unclassified: bool = False,
        sort: str = "updated",
        skip: int = 0,
        limit: int = DEFAULT_LIBRARY_LIMIT,
    ) -> WorldLibraryListResponse:
        nid = parse_uuid(novel_id, "novel_id")
        if kind not in _LIBRARY_KINDS:
            raise ValidationError("Invalid kind")
        if sort not in _LIBRARY_SORTS:
            raise ValidationError("Invalid sort")
        if topic_scope not in {"subtree", "topic"}:
            raise ValidationError("Invalid topic_scope")
        if state is not None and state not in {
            "active",
            "review",
            "archived",
            "working",
        }:
            raise ValidationError("Invalid state")
        if state == "working":
            working = True
            state = None
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        skip = max(0, skip)

        topic_ids: set[uuid_module.UUID] | None = None
        if topic_id is not None:
            topic_ids = await self._topic_scope_ids(db, nid, topic_id, topic_scope)

        outer, order_columns = self._library_outer_query(
            nid,
            q=q,
            kind=kind,
            item_type=item_type,
            state=state,
            working=working,
            favorite=favorite,
            topic_ids=topic_ids,
            unclassified=unclassified,
        )
        if target_id is not None:
            outer = outer.where(
                order_columns["target_id"] == parse_uuid(target_id, "target_id")
            )
        total = await db.scalar(select(func.count()).select_from(outer.subquery()))
        order = self._order_clause(order_columns, sort)
        if q and q.strip():
            query = q.strip().casefold()
            alias_rows = await db.execute(
                select(CoreEntity.id, CoreEntity.content_json).where(
                    CoreEntity.novel_id == nid,
                    self._alias_search_condition(q),
                )
            )
            alias_ranks: dict[int, list] = {0: [], 1: [], 2: []}
            for entity_id, content in alias_rows:
                names = [
                    (item if isinstance(item, str) else item.get("alias", "")).casefold()
                    for item in (content or {}).get("aliases", [])
                    if isinstance(item, str)
                    or (
                        isinstance(item, dict)
                        and item.get("status", "active") == "active"
                    )
                ]
                rank = (
                    0
                    if query in names
                    else 1
                    if any(name.startswith(query) for name in names)
                    else 2
                    if any(query in name for name in names)
                    else None
                )
                if rank is not None:
                    alias_ranks[rank].append(entity_id)
            title = func.lower(order_columns["title"])
            target = order_columns["target_id"]
            order.insert(
                0,
                case(
                    (or_(title == query, target.in_(alias_ranks[0])), 0),
                    (
                        or_(
                            title.startswith(query, autoescape=True),
                            target.in_(alias_ranks[1]),
                        ),
                        1,
                    ),
                    (
                        or_(
                            title.contains(query, autoescape=True),
                            target.in_(alias_ranks[2]),
                        ),
                        2,
                    ),
                    else_=3,
                ),
            )
        result = await db.execute(outer.order_by(*order).offset(skip).limit(limit))
        items = [self._row_to_item(row) for row in result.mappings()]
        return WorldLibraryListResponse(items=items, total=int(total or 0))

    # ---------- SQL assembly ----------

    def _library_outer_query(
        self,
        nid: uuid_module.UUID,
        *,
        q: str | None,
        kind: str,
        item_type: str | None,
        state: str | None,
        working: bool | None,
        favorite: bool | None,
        topic_ids: set[uuid_module.UUID] | None,
        unclassified: bool = False,
    ):
        sources = self._library_sources(
            nid,
            q=q,
            kind=kind,
            item_type=item_type,
            state=state,
            working=working,
        )
        if not sources:
            union_sq = self._empty_union().subquery()
        else:
            union_sq = sources[0].union_all(*sources[1:]).subquery()

        outer = select(
            union_sq.c.kind.label("kind"),
            union_sq.c.target_id.label("target_id"),
            union_sq.c.title.label("title"),
            union_sq.c.summary.label("summary"),
            union_sq.c.state.label("state"),
            union_sq.c.working.label("working"),
            union_sq.c.draft_id.label("draft_id"),
            union_sq.c.item_type.label("item_type"),
            union_sq.c.status.label("status"),
            union_sq.c.created_at.label("created_at"),
            union_sq.c.updated_at.label("updated_at"),
            WorldLibraryFavorite.target_id.is_not(None).label("is_favorite"),
            WorldLibraryRecent.last_opened_at.label("last_opened_at"),
        ).select_from(
            union_sq.outerjoin(
                WorldLibraryFavorite,
                and_(
                    WorldLibraryFavorite.novel_id == nid,
                    WorldLibraryFavorite.target_kind == union_sq.c.kind,
                    WorldLibraryFavorite.target_id == union_sq.c.target_id,
                ),
            ).outerjoin(
                WorldLibraryRecent,
                and_(
                    WorldLibraryRecent.novel_id == nid,
                    WorldLibraryRecent.target_kind == union_sq.c.kind,
                    WorldLibraryRecent.target_id == union_sq.c.target_id,
                ),
            )
        )
        if favorite is True:
            outer = outer.where(WorldLibraryFavorite.target_id.is_not(None))
        elif favorite is False:
            outer = outer.where(WorldLibraryFavorite.target_id.is_(None))
        if topic_ids is not None:
            member_exists = (
                select(literal(1))
                .where(
                    WorldLibraryTopicMember.novel_id == nid,
                    WorldLibraryTopicMember.topic_id.in_(tuple(topic_ids)),
                    WorldLibraryTopicMember.target_kind == union_sq.c.kind,
                    WorldLibraryTopicMember.target_id == union_sq.c.target_id,
                )
                .exists()
            )
            outer = outer.where(member_exists)
        if unclassified:
            any_member = (
                select(WorldLibraryTopicMember.id)
                .where(
                    WorldLibraryTopicMember.novel_id == nid,
                    WorldLibraryTopicMember.target_kind == union_sq.c.kind,
                    WorldLibraryTopicMember.target_id == union_sq.c.target_id,
                )
                .exists()
            )
            outer = outer.where(~any_member)
        order_columns = {
            "updated_at": union_sq.c.updated_at,
            "created_at": union_sq.c.created_at,
            "title": union_sq.c.title,
            "target_id": union_sq.c.target_id,
            "last_opened_at": WorldLibraryRecent.last_opened_at,
        }
        return outer, order_columns

    @staticmethod
    def _empty_union() -> Any:
        return select(
            literal("page").label("kind"),
            literal(None, type_=WorldBiblePage.id.type).label("target_id"),
            literal(None).label("title"),
            literal(None).label("summary"),
            literal("review").label("state"),
            literal(False).label("working"),
            literal(None).label("draft_id"),
            literal(None).label("item_type"),
            literal(None).label("status"),
            literal(None).label("created_at"),
            literal(None).label("updated_at"),
        ).where(literal(False))

    def _library_sources(
        self,
        nid: uuid_module.UUID,
        *,
        q: str | None,
        kind: str,
        item_type: str | None,
        state: str | None,
        working: bool | None,
    ) -> list[Any]:
        sources: list[Any] = []
        if kind in {"all", "page", "draft"} and kind != "draft":
            sources.append(
                self._pages_source(
                    nid,
                    q=q,
                    item_type=item_type,
                    state=state,
                    working=working,
                )
            )
        if kind in {"all", "page", "draft"} and working is not False:
            sources.append(
                self._free_drafts_source(
                    nid,
                    q=q,
                    item_type=item_type,
                    state=state,
                )
            )
        if kind in {"all", "entity"} and working is not True:
            sources.append(
                self._entities_source(
                    nid,
                    q=q,
                    item_type=item_type,
                    state=state,
                )
            )
        return sources

    @staticmethod
    def _search_condition(q: str | None, *columns: Any) -> Any | None:
        query = (q or "").strip()
        if not query:
            return None
        like_expr = f"%{query}%"
        return or_(*(column.ilike(like_expr) for column in columns))

    def _pages_source(
        self,
        nid: uuid_module.UUID,
        *,
        q: str | None,
        item_type: str | None,
        state: str | None,
        working: bool | None,
    ) -> Any:
        draft = aliased(WorldBiblePageDraft)
        title_expr = func.coalesce(draft.title, WorldBiblePage.title)
        free_text_expr = func.coalesce(
            func.nullif(draft.free_text, ""),
            func.nullif(WorldBiblePage.free_text, ""),
        )
        summary_expr = _trimmed(
            free_text_expr,
            WorldBiblePage.page_meta_json["summary"].as_string(),
        )
        updated_expr = case(
            (draft.updated_at.is_(None), WorldBiblePage.updated_at),
            (WorldBiblePage.updated_at.is_(None), draft.updated_at),
            (draft.updated_at > WorldBiblePage.updated_at, draft.updated_at),
            else_=WorldBiblePage.updated_at,
        )
        stmt = (
            select(
                literal("page").label("kind"),
                WorldBiblePage.id.label("target_id"),
                title_expr.label("title"),
                summary_expr.label("summary"),
                _state_case(WorldBiblePage.status).label("state"),
                draft.id.is_not(None).label("working"),
                draft.id.label("draft_id"),
                WorldBiblePage.page_type.label("item_type"),
                WorldBiblePage.status.label("status"),
                WorldBiblePage.created_at.label("created_at"),
                updated_expr.label("updated_at"),
            )
            .where(WorldBiblePage.novel_id == nid)
            .outerjoin(
                draft,
                and_(draft.novel_id == nid, draft.page_id == WorldBiblePage.id),
            )
        )
        if state is None:
            stmt = stmt.where(
                WorldBiblePage.status.not_in(tuple(ARCHIVED_DISPLAY_STATUSES))
            )
        else:
            display_statuses = statuses_for_display_state(state)
            if display_statuses:
                stmt = stmt.where(WorldBiblePage.status.in_(tuple(display_statuses)))
        if item_type:
            stmt = stmt.where(WorldBiblePage.page_type == item_type)
        if working is True:
            stmt = stmt.where(draft.id.is_not(None))
        elif working is False:
            stmt = stmt.where(draft.id.is_(None))
        q_condition = self._search_condition(
            q,
            title_expr,
            free_text_expr,
            WorldBiblePage.page_meta_json["summary"].as_string(),
            WorldBiblePage.sections_json.cast(Text),
            draft.sections_json.cast(Text),
        )
        if q_condition is not None:
            stmt = stmt.where(q_condition)
        return stmt

    def _free_drafts_source(
        self,
        nid: uuid_module.UUID,
        *,
        q: str | None,
        item_type: str | None,
        state: str | None,
    ) -> Any:
        summary_expr = _trimmed(
            func.nullif(WorldBiblePageDraft.free_text, ""),
            WorldBiblePageDraft.page_meta_json["summary"].as_string(),
        )
        stmt = select(
            literal("draft").label("kind"),
            WorldBiblePageDraft.id.label("target_id"),
            WorldBiblePageDraft.title.label("title"),
            summary_expr.label("summary"),
            literal("review").label("state"),
            literal(True).label("working"),
            WorldBiblePageDraft.id.label("draft_id"),
            WorldBiblePageDraft.page_type.label("item_type"),
            literal("draft").label("status"),
            WorldBiblePageDraft.created_at.label("created_at"),
            WorldBiblePageDraft.updated_at.label("updated_at"),
        ).where(
            WorldBiblePageDraft.novel_id == nid,
            WorldBiblePageDraft.page_id.is_(None),
        )
        if state is not None and state != "review":
            stmt = stmt.where(literal(False))
        if item_type:
            stmt = stmt.where(WorldBiblePageDraft.page_type == item_type)
        q_condition = self._search_condition(
            q,
            WorldBiblePageDraft.title,
            WorldBiblePageDraft.free_text,
            WorldBiblePageDraft.page_meta_json["summary"].as_string(),
            WorldBiblePageDraft.sections_json.cast(Text),
        )
        if q_condition is not None:
            stmt = stmt.where(q_condition)
        return stmt

    @staticmethod
    def _alias_search_condition(q: str):
        aliases = CoreEntity.content_json["aliases"].cast(Text)
        # JSON text can preserve Unicode or escape it, depending on the database.
        return or_(
            aliases.icontains(q.strip(), autoescape=True),
            aliases.icontains(
                json.dumps(q.strip(), ensure_ascii=True)[1:-1], autoescape=True
            ),
        )

    def _entities_source(
        self,
        nid: uuid_module.UUID,
        *,
        q: str | None,
        item_type: str | None,
        state: str | None,
    ) -> Any:
        summary_expr = _trimmed(
            func.nullif(CoreEntity.summary, ""),
            func.nullif(CoreEntity.public_info, ""),
        )
        stmt = select(
            literal("entity").label("kind"),
            CoreEntity.id.label("target_id"),
            CoreEntity.name.label("title"),
            summary_expr.label("summary"),
            _state_case(CoreEntity.status).label("state"),
            literal(False).label("working"),
            literal(None).label("draft_id"),
            CoreEntity.entity_type.label("item_type"),
            CoreEntity.status.label("status"),
            CoreEntity.created_at.label("created_at"),
            CoreEntity.updated_at.label("updated_at"),
        ).where(CoreEntity.novel_id == nid)
        if state is None:
            stmt = stmt.where(CoreEntity.status.not_in(tuple(ARCHIVED_DISPLAY_STATUSES)))
        else:
            display_statuses = statuses_for_display_state(state)
            if display_statuses:
                stmt = stmt.where(CoreEntity.status.in_(tuple(display_statuses)))
        if item_type:
            stmt = stmt.where(CoreEntity.entity_type == item_type)
        q_condition = self._search_condition(
            q,
            CoreEntity.name,
            CoreEntity.content_json["aliases"].cast(Text),
            CoreEntity.summary,
            CoreEntity.public_info,
            CoreEntity.hidden_truth,
        )
        if q_condition is not None:
            stmt = stmt.where(or_(q_condition, self._alias_search_condition(q)))
        return stmt

    @staticmethod
    def _order_clause(columns: dict[str, Any], sort: str) -> list[Any]:
        from sqlalchemy import asc

        c_updated = columns["updated_at"]
        c_created = columns["created_at"]
        c_title = columns["title"]
        c_target = columns["target_id"]
        c_recent = columns["last_opened_at"]
        if sort == "recent":
            return [
                nullslast(desc(c_recent)),
                nullslast(desc(c_updated)),
                asc(c_title),
                asc(c_target),
            ]
        if sort == "title":
            return [asc(c_title), nullslast(desc(c_updated)), asc(c_target)]
        if sort == "created":
            return [nullslast(desc(c_created)), asc(c_target)]
        return [nullslast(desc(c_updated)), asc(c_title), asc(c_target)]

    # ============================================================
    # Home overview
    # ============================================================

    async def overview(
        self, db: AsyncSession, novel_id: str
    ) -> WorldLibraryOverviewResponse:
        nid = parse_uuid(novel_id, "novel_id")
        topics = await self.list_topic_tree(db, novel_id)

        def outer(**overrides: Any) -> tuple[Any, dict[str, Any]]:
            defaults: dict[str, Any] = {
                "q": None,
                "kind": "all",
                "item_type": None,
                "state": None,
                "working": None,
                "favorite": None,
                "topic_ids": None,
            }
            defaults.update(overrides)
            return self._library_outer_query(nid, **defaults)

        base_query, base_columns = outer()
        base = base_query.subquery()
        kind_counts = dict(
            (
                await db.execute(select(base.c.kind, func.count()).group_by(base.c.kind))
            ).all()
        )
        working_total = await db.scalar(
            select(func.count()).select_from(base).where(base.c.working == literal(True))
        )
        unclassified = await db.scalar(
            select(func.count())
            .select_from(base)
            .where(
                ~select(WorldLibraryTopicMember.id)
                .where(
                    WorldLibraryTopicMember.novel_id == nid,
                    WorldLibraryTopicMember.target_kind == base.c.kind,
                    WorldLibraryTopicMember.target_id == base.c.target_id,
                )
                .exists()
            )
        )
        type_rows = await db.execute(
            select(base.c.item_type, func.count())
            .where(base.c.item_type != "")
            .group_by(base.c.item_type)
            .order_by(func.count().desc(), base.c.item_type)
        )
        favorites_total = await db.scalar(
            select(func.count()).select_from(outer(favorite=True)[0].subquery())
        )
        totals = {
            "all": sum(int(value) for value in kind_counts.values()),
            "entity": int(kind_counts.get("entity", 0)),
            "page": int(kind_counts.get("page", 0)),
            "draft": int(kind_counts.get("draft", 0)),
            "working": int(working_total or 0),
            "unclassified": int(unclassified or 0),
            "favorites": int(favorites_total or 0),
        }
        type_facets = [
            {"type": str(item_type), "count": int(count)}
            for item_type, count in type_rows
        ]

        async def items_for(
            query: Any,
            columns: dict[str, Any],
            *,
            sort: str,
        ) -> list[WorldLibraryItemResponse]:
            result = await db.execute(
                query.order_by(*self._order_clause(columns, sort)).limit(
                    LIBRARY_HOME_LIMIT
                )
            )
            return [self._row_to_item(row) for row in result.mappings()]

        recent_query, recent_columns = outer()
        recent_items = await items_for(recent_query, recent_columns, sort="recent")
        favorite_query, favorite_columns = outer(favorite=True)
        favorite_items = await items_for(favorite_query, favorite_columns, sort="updated")
        working_query, working_columns = outer(working=True)
        working_items = await items_for(working_query, working_columns, sort="updated")
        return WorldLibraryOverviewResponse(
            topics=topics,
            totals=totals,
            type_facets=type_facets,
            recent_items=recent_items,
            favorite_items=favorite_items,
            working_items=working_items,
        )

    # ============================================================
    # Topic directory
    # ============================================================

    async def list_topic_tree(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        include_archived: bool = False,
    ) -> list[WorldLibraryTopicNode]:
        nid = parse_uuid(novel_id, "novel_id")
        await self._purge_dangling_members(db, nid)
        conditions = [WorldLibraryTopic.novel_id == nid]
        if not include_archived:
            conditions.append(WorldLibraryTopic.status == "active")
        rows = (
            (
                await db.execute(
                    select(WorldLibraryTopic)
                    .where(*conditions)
                    .order_by(WorldLibraryTopic.sort_order, WorldLibraryTopic.name)
                )
            )
            .scalars()
            .all()
        )
        member_counts = dict(
            (
                await db.execute(
                    select(WorldLibraryTopicMember.topic_id, func.count())
                    .where(WorldLibraryTopicMember.novel_id == nid)
                    .group_by(WorldLibraryTopicMember.topic_id)
                )
            ).all()
        )
        nodes_by_id: dict[uuid_module.UUID, WorldLibraryTopicNode] = {}
        for topic in rows:
            nodes_by_id[topic.id] = WorldLibraryTopicNode(
                id=topic.id,
                name=topic.name,
                description=topic.description,
                status=topic.status,
                sort_order=topic.sort_order,
                parent_id=topic.parent_id,
                member_count=int(member_counts.get(topic.id, 0)),
                children=[],
            )
        children_by_parent: dict[
            uuid_module.UUID | None,
            list[WorldLibraryTopicNode],
        ] = {}
        for topic in rows:
            node = nodes_by_id[topic.id]
            parent_key = topic.parent_id if topic.parent_id in nodes_by_id else None
            children_by_parent.setdefault(parent_key, []).append(node)

        def collect(node: WorldLibraryTopicNode, visited: set[str]) -> None:
            if node.id in visited:
                return
            visited.add(node.id)
            for child in children_by_parent.get(_parse_or_none(node.id), []):
                node.children.append(child)
                collect(child, visited)

        visited: set[str] = set()
        roots = children_by_parent.get(None, [])
        for root in roots:
            collect(root, visited)
        return roots

    async def create_topic(
        self,
        db: AsyncSession,
        novel_id: str,
        data: WorldLibraryTopicCreate,
    ) -> WorldLibraryTopicNode:
        nid = parse_uuid(novel_id, "novel_id")
        await self._lock_workspace(db, nid)
        name = data.name.strip()
        if not name:
            raise ValidationError("主题名称不能为空")
        parent = (
            await self._get_topic(db, nid, data.parent_id) if data.parent_id else None
        )
        if parent is not None and parent.status != "active":
            raise ValidationError("不能在已归档主题下创建子主题")
        parent_id = parent.id if parent is not None else None
        sibling_filter = (
            WorldLibraryTopic.parent_id.is_(None)
            if parent_id is None
            else WorldLibraryTopic.parent_id == parent_id
        )
        max_sort = await db.scalar(
            select(func.max(WorldLibraryTopic.sort_order)).where(
                WorldLibraryTopic.novel_id == nid,
                sibling_filter,
            )
        )
        topic = WorldLibraryTopic(
            novel_id=nid,
            parent_id=parent_id,
            name=name,
            description=data.description,
            sort_order=(int(max_sort) if max_sort is not None else 0) + 10,
            status="active",
        )
        db.add(topic)
        await db.flush()
        return self._topic_node(topic)

    async def update_topic(
        self,
        db: AsyncSession,
        novel_id: str,
        topic_id: str,
        data: WorldLibraryTopicUpdate,
    ) -> WorldLibraryTopicNode:
        nid = parse_uuid(novel_id, "novel_id")
        await self._lock_workspace(db, nid)
        topic = await self._get_topic(db, nid, topic_id, for_update=True)
        self._check_baseline(topic, data.expected_updated_at)
        if data.name is not None:
            name = data.name.strip()
            if not name:
                raise ValidationError("主题名称不能为空")
            topic.name = name
        if data.description is not None:
            topic.description = data.description
        await db.flush()
        return self._topic_node(topic)

    async def move_topic(
        self,
        db: AsyncSession,
        novel_id: str,
        topic_id: str,
        data: WorldLibraryTopicMoveRequest,
    ) -> WorldLibraryTopicNode:
        nid = parse_uuid(novel_id, "novel_id")
        await self._lock_workspace(db, nid)
        topic = await self._get_topic(db, nid, topic_id, for_update=True)
        self._check_baseline(topic, data.expected_updated_at)
        new_parent_id = (
            parse_uuid(data.parent_id, "parent_id") if data.parent_id else None
        )
        if new_parent_id == topic.id:
            raise ValidationError(
                "主题不能移动到自己之下",
                code="topic_cycle",
            )
        if new_parent_id is not None:
            ancestor = await self._get_topic(db, nid, str(new_parent_id))
            if ancestor.status != "active":
                raise ValidationError("不能移动到已归档主题之下")
            seen: set[uuid_module.UUID] = set()
            while ancestor is not None:
                if ancestor.id == topic.id:
                    raise ValidationError(
                        "移动后主题会成为自己的祖先，已取消",
                        code="topic_cycle",
                    )
                if ancestor.id in seen:
                    break
                seen.add(ancestor.id)
                ancestor = (
                    await self._get_topic(db, nid, str(ancestor.parent_id))
                    if ancestor.parent_id
                    else None
                )
        topic.parent_id = new_parent_id
        sibling_filter = (
            WorldLibraryTopic.parent_id.is_(None)
            if new_parent_id is None
            else WorldLibraryTopic.parent_id == new_parent_id
        )
        edge_func = func.min if data.position == "start" else func.max
        edge_sort = await db.scalar(
            select(edge_func(WorldLibraryTopic.sort_order)).where(
                WorldLibraryTopic.novel_id == nid,
                sibling_filter,
            )
        )
        if data.position == "start":
            topic.sort_order = (int(edge_sort) if edge_sort is not None else 10) - 10
        else:
            topic.sort_order = (int(edge_sort) if edge_sort is not None else 0) + 10
        await db.flush()
        return self._topic_node(topic)

    async def reorder_topics(
        self,
        db: AsyncSession,
        novel_id: str,
        data: WorldLibraryTopicReorderRequest,
    ) -> list[WorldLibraryTopicNode]:
        nid = parse_uuid(novel_id, "novel_id")
        await self._lock_workspace(db, nid)
        parent_id = parse_uuid(data.parent_id, "parent_id") if data.parent_id else None
        if len(set(data.ordered_ids)) != len(data.ordered_ids):
            raise ValidationError("ordered_ids 不能重复")
        ordered_uuids = [parse_uuid(item, "ordered_ids") for item in data.ordered_ids]
        rows = {
            topic.id: topic
            for topic in (
                await db.execute(
                    select(WorldLibraryTopic).where(
                        WorldLibraryTopic.novel_id == nid,
                        WorldLibraryTopic.id.in_(ordered_uuids),
                    )
                )
            ).scalars()
        }
        for row_id in ordered_uuids:
            topic = rows.get(row_id)
            if topic is None or topic.parent_id != parent_id:
                raise ValidationError("ordered_ids 包含不属于同一父主题的项")
        for index, row_id in enumerate(ordered_uuids):
            rows[row_id].sort_order = (index + 1) * 10
        await db.flush()
        return [self._topic_node(rows[row_id]) for row_id in ordered_uuids]

    async def archive_topic(
        self,
        db: AsyncSession,
        novel_id: str,
        topic_id: str,
        *,
        archived: bool,
    ) -> WorldLibraryTopicNode:
        nid = parse_uuid(novel_id, "novel_id")
        await self._lock_workspace(db, nid)
        topic = await self._get_topic(db, nid, topic_id, for_update=True)
        topic.status = "archived" if archived else "active"
        await db.flush()
        return self._topic_node(topic)

    async def add_member(
        self,
        db: AsyncSession,
        novel_id: str,
        topic_id: str,
        data: WorldLibraryMemberRequest,
    ) -> bool:
        nid = parse_uuid(novel_id, "novel_id")
        await self._lock_workspace(db, nid)
        topic = await self._get_topic(db, nid, topic_id)
        if topic.status != "active":
            raise ValidationError("主题已归档，不能添加资料")
        kind, target_id = await self._normalize_target(
            db, nid, data.target_kind, data.target_id
        )
        existing = await db.scalar(
            select(WorldLibraryTopicMember.id).where(
                WorldLibraryTopicMember.novel_id == nid,
                WorldLibraryTopicMember.topic_id == topic.id,
                WorldLibraryTopicMember.target_kind == kind,
                WorldLibraryTopicMember.target_id == target_id,
            )
        )
        if existing is not None:
            return False
        db.add(
            WorldLibraryTopicMember(
                novel_id=nid,
                topic_id=topic.id,
                target_kind=kind,
                target_id=target_id,
            )
        )
        await db.flush()
        return True

    async def remove_member(
        self,
        db: AsyncSession,
        novel_id: str,
        topic_id: str,
        target_kind: str,
        target_id: str,
    ) -> bool:
        nid = parse_uuid(novel_id, "novel_id")
        await self._lock_workspace(db, nid)
        topic = await self._get_topic(db, nid, topic_id)
        kind, normalized_id = await self._normalize_target(
            db, nid, target_kind, target_id
        )
        result = await db.execute(
            delete(WorldLibraryTopicMember).where(
                WorldLibraryTopicMember.novel_id == nid,
                WorldLibraryTopicMember.topic_id == topic.id,
                WorldLibraryTopicMember.target_kind == kind,
                WorldLibraryTopicMember.target_id == normalized_id,
            )
        )
        return bool(result.rowcount)

    async def memberships(
        self,
        db: AsyncSession,
        novel_id: str,
        target_kind: str,
        target_id: str,
    ) -> list[str]:
        nid = parse_uuid(novel_id, "novel_id")
        kind, normalized_id = await self._normalize_target(
            db, nid, target_kind, target_id
        )
        rows = await db.execute(
            select(WorldLibraryTopicMember.topic_id).where(
                WorldLibraryTopicMember.novel_id == nid,
                WorldLibraryTopicMember.target_kind == kind,
                WorldLibraryTopicMember.target_id == normalized_id,
            )
        )
        return [str(topic_id) for topic_id in rows.scalars()]

    # ============================================================
    # Author workspace
    # ============================================================

    async def record_recent(
        self,
        db: AsyncSession,
        novel_id: str,
        target_kind: str,
        target_id: str,
    ) -> None:
        nid = parse_uuid(novel_id, "novel_id")
        await self._lock_workspace(db, nid)
        kind, normalized_id = await self._normalize_target(
            db, nid, target_kind, target_id
        )
        row = (
            await db.execute(
                select(WorldLibraryRecent).where(
                    WorldLibraryRecent.novel_id == nid,
                    WorldLibraryRecent.target_kind == kind,
                    WorldLibraryRecent.target_id == normalized_id,
                )
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if row is None:
            db.add(
                WorldLibraryRecent(
                    novel_id=nid,
                    target_kind=kind,
                    target_id=normalized_id,
                    last_opened_at=now,
                    open_count=1,
                )
            )
        else:
            row.last_opened_at = now
            row.open_count = (row.open_count or 0) + 1
        await db.flush()
        keep_ids = (
            (
                await db.execute(
                    select(WorldLibraryRecent.id)
                    .where(WorldLibraryRecent.novel_id == nid)
                    .order_by(WorldLibraryRecent.last_opened_at.desc())
                    .limit(LIBRARY_RECENTS_CAP)
                )
            )
            .scalars()
            .all()
        )
        if keep_ids:
            await db.execute(
                delete(WorldLibraryRecent).where(
                    WorldLibraryRecent.novel_id == nid,
                    WorldLibraryRecent.id.not_in(keep_ids),
                )
            )

    async def set_favorite(
        self,
        db: AsyncSession,
        novel_id: str,
        target_kind: str,
        target_id: str,
        *,
        favorited: bool,
    ) -> WorldLibraryFavoriteResponse:
        nid = parse_uuid(novel_id, "novel_id")
        await self._lock_workspace(db, nid)
        kind, normalized_id = await self._normalize_target(
            db, nid, target_kind, target_id
        )
        row = (
            await db.execute(
                select(WorldLibraryFavorite).where(
                    WorldLibraryFavorite.novel_id == nid,
                    WorldLibraryFavorite.target_kind == kind,
                    WorldLibraryFavorite.target_id == normalized_id,
                )
            )
        ).scalar_one_or_none()
        if favorited and row is None:
            db.add(
                WorldLibraryFavorite(
                    novel_id=nid,
                    target_kind=kind,
                    target_id=normalized_id,
                )
            )
            await db.flush()
        elif not favorited and row is not None:
            await db.delete(row)
            await db.flush()
        return WorldLibraryFavoriteResponse(
            target_kind=kind,
            target_id=str(normalized_id),
            favorited=favorited,
        )

    async def get_view_prefs(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> WorldLibraryViewPrefsResponse:
        nid = parse_uuid(novel_id, "novel_id")
        row = await db.scalar(
            select(WorldLibraryWorkspaceProfile).where(
                WorldLibraryWorkspaceProfile.novel_id == nid
            )
        )
        return WorldLibraryViewPrefsResponse(
            view_prefs=dict(row.view_prefs_json or {}) if row else {}
        )

    async def update_view_prefs(
        self,
        db: AsyncSession,
        novel_id: str,
        view_prefs: dict[str, Any],
    ) -> WorldLibraryViewPrefsResponse:
        nid = parse_uuid(novel_id, "novel_id")
        await self._lock_workspace(db, nid)
        try:
            encoded = json.dumps(view_prefs, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValidationError("view_prefs 不是可序列化的对象") from exc
        if len(encoded.encode("utf-8")) > LIBRARY_VIEW_PREFS_MAX_BYTES:
            raise ValidationError("view_prefs 内容过大")
        row = await self._get_profile(db, nid)
        row.view_prefs_json = dict(view_prefs)
        await db.flush()
        return WorldLibraryViewPrefsResponse(view_prefs=dict(row.view_prefs_json or {}))

    # ============================================================
    # Draft publish conversion
    # ============================================================

    async def adopt_draft_workspace_refs(
        self,
        db: AsyncSession,
        novel_id: str,
        draft_id: str | uuid_module.UUID,
        page_id: str | uuid_module.UUID,
    ) -> None:
        """工作稿发布后，把目录成员/收藏/最近访问的 draft 引用转换为 page 引用。"""
        nid = parse_uuid(novel_id, "novel_id")
        await self._lock_workspace(db, nid)
        did = (
            draft_id
            if isinstance(draft_id, uuid_module.UUID)
            else parse_uuid(draft_id, "draft_id")
        )
        pid = (
            page_id
            if isinstance(page_id, uuid_module.UUID)
            else parse_uuid(page_id, "page_id")
        )

        draft_members = (
            (
                await db.execute(
                    select(WorldLibraryTopicMember).where(
                        WorldLibraryTopicMember.novel_id == nid,
                        WorldLibraryTopicMember.target_kind == "draft",
                        WorldLibraryTopicMember.target_id == did,
                    )
                )
            )
            .scalars()
            .all()
        )
        if draft_members:
            page_member_topics = set(
                (
                    await db.execute(
                        select(WorldLibraryTopicMember.topic_id).where(
                            WorldLibraryTopicMember.novel_id == nid,
                            WorldLibraryTopicMember.target_kind == "page",
                            WorldLibraryTopicMember.target_id == pid,
                        )
                    )
                ).scalars()
            )
            for member in draft_members:
                if member.topic_id in page_member_topics:
                    await db.delete(member)
                else:
                    member.target_kind = "page"
                    member.target_id = pid

        draft_favorite = (
            await db.execute(
                select(WorldLibraryFavorite).where(
                    WorldLibraryFavorite.novel_id == nid,
                    WorldLibraryFavorite.target_kind == "draft",
                    WorldLibraryFavorite.target_id == did,
                )
            )
        ).scalar_one_or_none()
        if draft_favorite is not None:
            page_favorite = await db.scalar(
                select(WorldLibraryFavorite.id).where(
                    WorldLibraryFavorite.novel_id == nid,
                    WorldLibraryFavorite.target_kind == "page",
                    WorldLibraryFavorite.target_id == pid,
                )
            )
            if page_favorite is None:
                draft_favorite.target_kind = "page"
                draft_favorite.target_id = pid
            else:
                await db.delete(draft_favorite)

        draft_recent = (
            await db.execute(
                select(WorldLibraryRecent).where(
                    WorldLibraryRecent.novel_id == nid,
                    WorldLibraryRecent.target_kind == "draft",
                    WorldLibraryRecent.target_id == did,
                )
            )
        ).scalar_one_or_none()
        if draft_recent is not None:
            page_recent = (
                await db.execute(
                    select(WorldLibraryRecent).where(
                        WorldLibraryRecent.novel_id == nid,
                        WorldLibraryRecent.target_kind == "page",
                        WorldLibraryRecent.target_id == pid,
                    )
                )
            ).scalar_one_or_none()
            if page_recent is None:
                draft_recent.target_kind = "page"
                draft_recent.target_id = pid
            else:
                if (draft_recent.last_opened_at or _EPOCH_MIN) > (
                    page_recent.last_opened_at or _EPOCH_MIN
                ):
                    page_recent.last_opened_at = draft_recent.last_opened_at
                page_recent.open_count = (page_recent.open_count or 0) + (
                    draft_recent.open_count or 0
                )
                await db.delete(draft_recent)
        await db.flush()

    # ============================================================
    # Internals
    # ============================================================

    @staticmethod
    async def _lock_workspace(db: AsyncSession, nid: uuid_module.UUID) -> None:
        # ponytail: per-novel metadata lock; split only on measured contention.
        if db.get_bind().dialect.name == "postgresql":
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"world-library:{nid}"},
            )

    async def _get_topic(
        self,
        db: AsyncSession,
        nid: uuid_module.UUID,
        topic_id: str | uuid_module.UUID | None,
        *,
        for_update: bool = False,
    ) -> WorldLibraryTopic:
        if topic_id in (None, ""):
            raise NotFoundError("主题不存在")
        tid = (
            topic_id
            if isinstance(topic_id, uuid_module.UUID)
            else parse_uuid(topic_id, "topic_id")
        )
        stmt = select(WorldLibraryTopic).where(
            WorldLibraryTopic.novel_id == nid,
            WorldLibraryTopic.id == tid,
        )
        if for_update:
            stmt = stmt.execution_options(populate_existing=True).with_for_update()
        topic = (await db.execute(stmt)).scalar_one_or_none()
        if topic is None:
            raise NotFoundError("主题不存在")
        return topic

    async def _topic_scope_ids(
        self,
        db: AsyncSession,
        nid: uuid_module.UUID,
        topic_id: str,
        topic_scope: str,
    ) -> set[uuid_module.UUID]:
        root = await self._get_topic(db, nid, topic_id)
        if topic_scope == "topic":
            return {root.id}
        rows = (
            await db.execute(
                select(WorldLibraryTopic.id, WorldLibraryTopic.parent_id).where(
                    WorldLibraryTopic.novel_id == nid
                )
            )
        ).all()
        children: dict[uuid_module.UUID | None, list[uuid_module.UUID]] = {}
        for row_id, row_parent in rows:
            children.setdefault(row_parent, []).append(row_id)
        collected = {root.id}
        queue = [root.id]
        while queue:
            current = queue.pop()
            for child in children.get(current, []):
                if child not in collected:
                    collected.add(child)
                    queue.append(child)
        return collected

    async def _normalize_target(
        self,
        db: AsyncSession,
        nid: uuid_module.UUID,
        target_kind: str,
        target_id: str,
    ) -> tuple[str, uuid_module.UUID]:
        tid = parse_uuid(target_id, "target_id")
        if target_kind not in {"page", "draft", "entity"}:
            raise ValidationError("target_kind 必须是 page / draft / entity")
        if target_kind == "page":
            found = await db.scalar(
                select(WorldBiblePage.id).where(
                    WorldBiblePage.novel_id == nid,
                    WorldBiblePage.id == tid,
                )
            )
            if found is None:
                raise NotFoundError("资料页不存在")
            return "page", tid
        if target_kind == "draft":
            draft = (
                await db.execute(
                    select(WorldBiblePageDraft).where(
                        WorldBiblePageDraft.novel_id == nid,
                        WorldBiblePageDraft.id == tid,
                    )
                )
            ).scalar_one_or_none()
            if draft is None:
                raise NotFoundError("工作稿不存在")
            if draft.page_id is not None:
                return "page", draft.page_id
            return "draft", tid
        found = await db.scalar(
            select(CoreEntity.id).where(
                CoreEntity.novel_id == nid,
                CoreEntity.id == tid,
            )
        )
        if found is None:
            raise NotFoundError("人物或设定不存在")
        return "entity", tid

    async def _purge_dangling_members(
        self,
        db: AsyncSession,
        nid: uuid_module.UUID,
    ) -> None:
        members = (
            await db.execute(
                select(
                    WorldLibraryTopicMember.id,
                    WorldLibraryTopicMember.target_kind,
                    WorldLibraryTopicMember.target_id,
                ).where(WorldLibraryTopicMember.novel_id == nid)
            )
        ).all()
        if not members:
            return
        page_ids = {row.target_id for row in members if row.target_kind == "page"}
        draft_ids = {row.target_id for row in members if row.target_kind == "draft"}
        entity_ids = {row.target_id for row in members if row.target_kind == "entity"}

        async def live_ids(model, ids: set[uuid_module.UUID]) -> set[uuid_module.UUID]:
            if not ids:
                return set()
            rows = await db.execute(
                select(model.id).where(model.novel_id == nid, model.id.in_(tuple(ids)))
            )
            return set(rows.scalars())

        live_pages = await live_ids(WorldBiblePage, page_ids)
        live_drafts = await live_ids(WorldBiblePageDraft, draft_ids)
        live_entities = await live_ids(CoreEntity, entity_ids)
        dangling = [
            row.id
            for row in members
            if (
                (row.target_kind == "page" and row.target_id not in live_pages)
                or (row.target_kind == "draft" and row.target_id not in live_drafts)
                or (row.target_kind == "entity" and row.target_id not in live_entities)
            )
        ]
        if dangling:
            await db.execute(
                delete(WorldLibraryTopicMember).where(
                    WorldLibraryTopicMember.id.in_(dangling)
                )
            )

    async def _get_profile(
        self,
        db: AsyncSession,
        nid: uuid_module.UUID,
    ) -> WorldLibraryWorkspaceProfile:
        row = (
            await db.execute(
                select(WorldLibraryWorkspaceProfile).where(
                    WorldLibraryWorkspaceProfile.novel_id == nid
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = WorldLibraryWorkspaceProfile(novel_id=nid, view_prefs_json={})
            db.add(row)
            await db.flush()
        return row

    @staticmethod
    def _topic_node(topic: WorldLibraryTopic) -> WorldLibraryTopicNode:
        return WorldLibraryTopicNode(
            id=topic.id,
            name=topic.name,
            description=topic.description,
            status=topic.status,
            sort_order=topic.sort_order,
            parent_id=topic.parent_id,
            member_count=0,
        )

    @staticmethod
    def _check_baseline(topic: WorldLibraryTopic, expected_updated_at: Any) -> None:
        if expected_updated_at is not None and topic.updated_at != expected_updated_at:
            raise ConflictError(
                "主题已在别处更新，请刷新后重试",
                code="world_topic_stale",
            )

    @staticmethod
    def _row_to_item(row: Any) -> WorldLibraryItemResponse:
        data = dict(row)
        return WorldLibraryItemResponse(
            kind=data["kind"],
            id=data["target_id"],
            title=str(data["title"] or "未命名资料"),
            summary=str(data["summary"] or ""),
            state=data["state"],
            working=bool(data["working"]),
            draft_id=data["draft_id"],
            item_type=str(data["item_type"] or ""),
            status=str(data["status"] or ""),
            is_favorite=bool(data["is_favorite"]),
            last_opened_at=data["last_opened_at"],
            updated_at=data["updated_at"],
            created_at=data["created_at"],
        )


def _parse_or_none(value: str | None) -> uuid_module.UUID | None:
    if not value:
        return None
    try:
        return uuid_module.UUID(value)
    except (TypeError, ValueError):
        return None


_EPOCH_MIN = datetime.min.replace(tzinfo=UTC)
