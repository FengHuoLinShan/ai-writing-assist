"""世界改动记录时间线 — 实体/页面/地图三类修订的合并读取（路线图阶段 0 · P2）。

``GET /api/world/change-history`` 的服务实现：在 SQL 里把三段查询
``UNION ALL`` 起来，并逐段 LEFT JOIN ``world_revision_notes`` 带出备注，
不做逐条查询：

- 实体改动：``entity_revisions`` 全部 reason；实体当前处于历史态
  （deprecated/ignored/merged 等作者态 archived）时 ``target_state="removed"``，
  链接仍可跳转，名称仍可解析（实体行缺失时回退快照里的 name）。
- 世界书页面发布：``world_bible_page_revisions``。
- 地图保存：``map_atlas_revisions`` 只取 ``status='saved'`` 且
  ``confirmation_id IS NULL`` 的行（整份采用 AI 候选产生的确认行不重复收录）。

排序键 ``(created_at, kind, id)`` 倒序；游标是不透明 base64 JSON，
编码最后一条返回项的排序键，坏游标返回 422；``limit`` 1–50 默认 30，
每次多取一条判断 ``next_cursor``；不返回总数。

合同来源：.agent/tasks/2026/T-20261004-world-edit-history/TASK.md §5.4 / §6.3 / §6.4。
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import and_, literal, null, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from modules.world.asset_state import ARCHIVED_DISPLAY_STATUSES
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.models import (
    CoreEntity,
    EntityRevision,
    WorldBiblePage,
    WorldBiblePageRevision,
    WorldRevisionNote,
)
from modules.world.revision_history_schemas import (
    WorldChangeHistoryItem,
    WorldChangeHistoryResponse,
)
from shared.utils import parse_uuid

KIND_ENTITY = "entity"
KIND_PAGE = "page"
KIND_MAP = "map"

CHANGE_HISTORY_KINDS: frozenset[str] = frozenset({KIND_ENTITY, KIND_PAGE, KIND_MAP})
DEFAULT_CHANGE_HISTORY_LIMIT = 30
MAX_CHANGE_HISTORY_LIMIT = 50


def _ensure_utc(value: datetime) -> datetime:
    """SQLite 读出的无时区值统一补 UTC；PG 读出的带时区值原样通过。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _encode_cursor(created_at: datetime, kind: str, revision_id: uuid.UUID) -> str:
    payload = json.dumps(
        {
            "created_at": _ensure_utc(created_at).isoformat(),
            "id": str(revision_id),
            "kind": kind,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, str, uuid.UUID]:
    """解析不透明游标；任何格式问题都以 422 拒绝，不区分错误细节。"""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("cursor payload must be a JSON object")
        created_at = datetime.fromisoformat(str(payload["created_at"]))
        kind = str(payload["kind"])
        revision_id = uuid.UUID(hex=str(payload["id"]))
    except (
        AttributeError,
        KeyError,
        TypeError,
        UnicodeError,
        ValueError,
        binascii.Error,
    ) as exc:
        raise ValidationError("cursor 不合法", status_code=422) from exc
    if kind not in CHANGE_HISTORY_KINDS:
        raise ValidationError("cursor 不合法：kind 非法", status_code=422)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at, kind, revision_id


def _target_state(status: str | None) -> str:
    """按共享作者态投影判定 removed；目标行缺失按已移除处理。"""
    if status is None:
        return "removed"
    if str(status).strip().lower() in ARCHIVED_DISPLAY_STATUSES:
        return "removed"
    return "active"


def _extract_changed_fields(summary) -> list[str] | None:  # noqa: ANN001
    if not isinstance(summary, dict):
        return None
    fields = summary.get("fields")
    if not isinstance(fields, list):
        return None
    return [str(field) for field in fields]


def _entity_segment(nid: uuid.UUID):
    return (
        select(
            literal(KIND_ENTITY).label("kind"),
            EntityRevision.id.label("revision_id"),
            EntityRevision.entity_id.label("target_id"),
            CoreEntity.name.label("title_current"),
            CoreEntity.status.label("target_status"),
            EntityRevision.snapshot.label("snapshot"),
            EntityRevision.revision_reason.label("reason"),
            EntityRevision.created_at.label("created_at"),
            EntityRevision.writing_chapter_index.label("writing_chapter_index"),
            null().label("version_number"),
            EntityRevision.change_summary.label("change_summary"),
            WorldRevisionNote.note.label("change_note"),
        )
        .select_from(EntityRevision)
        .outerjoin(
            CoreEntity,
            and_(
                CoreEntity.id == EntityRevision.entity_id,
                CoreEntity.novel_id == nid,
            ),
        )
        .outerjoin(
            WorldRevisionNote,
            and_(
                WorldRevisionNote.novel_id == nid,
                WorldRevisionNote.target_kind == KIND_ENTITY,
                WorldRevisionNote.revision_id == EntityRevision.id,
            ),
        )
        .where(EntityRevision.novel_id == nid)
    )


def _page_segment(nid: uuid.UUID):
    return (
        select(
            literal(KIND_PAGE).label("kind"),
            WorldBiblePageRevision.id.label("revision_id"),
            WorldBiblePageRevision.page_id.label("target_id"),
            WorldBiblePage.title.label("title_current"),
            WorldBiblePage.status.label("target_status"),
            WorldBiblePageRevision.snapshot_json.label("snapshot"),
            WorldBiblePageRevision.revision_reason.label("reason"),
            WorldBiblePageRevision.created_at.label("created_at"),
            WorldBiblePageRevision.writing_chapter_index.label("writing_chapter_index"),
            WorldBiblePageRevision.version_number.label("version_number"),
            WorldBiblePageRevision.change_summary.label("change_summary"),
            WorldRevisionNote.note.label("change_note"),
        )
        .select_from(WorldBiblePageRevision)
        .outerjoin(
            WorldBiblePage,
            and_(
                WorldBiblePage.id == WorldBiblePageRevision.page_id,
                WorldBiblePage.novel_id == nid,
            ),
        )
        .outerjoin(
            WorldRevisionNote,
            and_(
                WorldRevisionNote.novel_id == nid,
                WorldRevisionNote.target_kind == KIND_PAGE,
                WorldRevisionNote.revision_id == WorldBiblePageRevision.id,
            ),
        )
        .where(WorldBiblePageRevision.novel_id == nid)
    )


def _map_segment(nid: uuid.UUID):
    return (
        select(
            literal(KIND_MAP).label("kind"),
            MapAtlasRevision.id.label("revision_id"),
            MapAtlasRevision.node_id.label("target_id"),
            MapAtlasNode.title.label("title_current"),
            null().label("target_status"),
            null().label("snapshot"),
            null().label("reason"),
            MapAtlasRevision.created_at.label("created_at"),
            MapAtlasRevision.writing_chapter_index.label("writing_chapter_index"),
            null().label("version_number"),
            MapAtlasRevision.change_summary.label("change_summary"),
            WorldRevisionNote.note.label("change_note"),
        )
        .select_from(MapAtlasRevision)
        .outerjoin(
            MapAtlasNode,
            and_(
                MapAtlasNode.id == MapAtlasRevision.node_id,
                MapAtlasNode.novel_id == nid,
            ),
        )
        .outerjoin(
            WorldRevisionNote,
            and_(
                WorldRevisionNote.novel_id == nid,
                WorldRevisionNote.target_kind == KIND_MAP,
                WorldRevisionNote.revision_id == MapAtlasRevision.id,
            ),
        )
        .where(
            MapAtlasRevision.novel_id == nid,
            MapAtlasRevision.status == "saved",
            MapAtlasRevision.confirmation_id.is_(None),
        )
    )


def _to_item(row) -> WorldChangeHistoryItem:  # noqa: ANN001
    kind = row.kind
    snapshot = row.snapshot if isinstance(row.snapshot, dict) else {}
    title = row.title_current
    if not title:
        title = snapshot.get("name" if kind == KIND_ENTITY else "title")
    return WorldChangeHistoryItem(
        kind=kind,
        revision_id=str(row.revision_id),
        target_id=str(row.target_id),
        target_title=str(title or ""),
        target_state=_target_state(row.target_status),
        reason=row.reason,
        created_at=_ensure_utc(row.created_at),
        writing_chapter_index=row.writing_chapter_index,
        version_number=row.version_number,
        changed_fields=_extract_changed_fields(row.change_summary),
        change_note=row.change_note or None,
    )


class WorldChangeHistoryService:
    """世界改动记录时间线读取服务。"""

    async def list(  # 合同签名（TASK.md §6.3），与 _character_service.list 同风格
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        kinds: Sequence[str] | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_CHANGE_HISTORY_LIMIT,
    ) -> WorldChangeHistoryResponse:
        nid = parse_uuid(str(novel_id), "novel_id")

        if kinds:
            invalid = [kind for kind in kinds if kind not in CHANGE_HISTORY_KINDS]
            if invalid:
                raise ValidationError(
                    f"kinds 含非法取值（只允许 entity/page/map）：{invalid!r}",
                    status_code=422,
                )
            selected_kinds = set(kinds)
        else:
            selected_kinds = set(CHANGE_HISTORY_KINDS)

        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValidationError("limit 必须是整数", status_code=422)
        if not 1 <= limit <= MAX_CHANGE_HISTORY_LIMIT:
            raise ValidationError(
                f"limit 必须在 1–{MAX_CHANGE_HISTORY_LIMIT} 之间",
                status_code=422,
            )

        cursor_key = _decode_cursor(cursor) if cursor else None

        segments = []
        if KIND_ENTITY in selected_kinds:
            segments.append(_entity_segment(nid))
        if KIND_PAGE in selected_kinds:
            segments.append(_page_segment(nid))
        if KIND_MAP in selected_kinds:
            segments.append(_map_segment(nid))
        timeline = union_all(*segments).subquery()

        stmt = (
            select(timeline)
            .order_by(
                timeline.c.created_at.desc(),
                timeline.c.kind.desc(),
                timeline.c.revision_id.desc(),
            )
            .limit(limit + 1)
        )
        if cursor_key is not None:
            cursor_created_at, cursor_kind, cursor_revision_id = cursor_key
            stmt = stmt.where(
                or_(
                    timeline.c.created_at < cursor_created_at,
                    and_(
                        timeline.c.created_at == cursor_created_at,
                        timeline.c.kind < cursor_kind,
                    ),
                    and_(
                        timeline.c.created_at == cursor_created_at,
                        timeline.c.kind == cursor_kind,
                        timeline.c.revision_id < cursor_revision_id,
                    ),
                )
            )

        rows = (await db.execute(stmt)).all()
        has_more = len(rows) > limit
        items = [_to_item(row) for row in rows[:limit]]

        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = _encode_cursor(
                last.created_at, last.kind, uuid.UUID(hex=last.revision_id)
            )
        return WorldChangeHistoryResponse(items=items, next_cursor=next_cursor)
