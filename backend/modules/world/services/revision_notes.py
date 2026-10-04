"""世界修订备注 — 实体/页面/地图历史的事后补写备注（路线图阶段 0）。

三种目标共用 ``world_revision_notes`` 一张表；``revision_id`` 不设外键
（一列按 ``target_kind`` 指向三张修订表），归属校验在本服务完成：
目标修订必须属于当前 ``novel_id``，否则 404。

- 地图只有已保存（``status='saved'``）的版本能写备注；候选版本返回 409
  （路由语义见 README 路由表，实现取 409）。
- 备注去掉首尾空白，最多 500 字；空串表示删除。
- 重复写入同样内容是幂等的。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.map_atlas_models import MapAtlasRevision
from modules.world.models import (
    EntityRevision,
    WorldBiblePageRevision,
    WorldRevisionNote,
)
from modules.world.revision_history_schemas import (
    REVISION_NOTE_MAX_LENGTH,
    RevisionNoteResponse,
    RevisionTargetKind,
)
from shared.utils import parse_uuid

_NOTE_KINDS: frozenset[str] = frozenset({"entity", "page", "map"})


def _validate_kind(kind: str) -> None:
    if kind not in _NOTE_KINDS:
        raise ValidationError(
            f"target_kind 必须是 entity/page/map 之一，收到：{kind!r}",
            status_code=422,
        )


async def _ensure_revision_visible(
    db: AsyncSession,
    novel_id: uuid.UUID,
    kind: str,
    revision_id: uuid.UUID,
) -> None:
    """确认目标修订存在且属于当前作品；地图候选版本视为冲突（409）。"""
    if kind == "map":
        stmt = select(MapAtlasRevision.id, MapAtlasRevision.status).where(
            MapAtlasRevision.id == revision_id,
            MapAtlasRevision.novel_id == novel_id,
        )
        row = (await db.execute(stmt)).first()
        if row is None:
            raise NotFoundError(f"Map revision {revision_id} not found")
        if row.status != "saved":
            raise ConflictError(
                "地图候选版本不能写备注，只有已保存的版本支持备注",
            )
        return

    model = EntityRevision if kind == "entity" else WorldBiblePageRevision
    stmt = select(model.id).where(
        model.id == revision_id,
        model.novel_id == novel_id,
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise NotFoundError(f"{kind} revision {revision_id} not found")


async def load_revision_notes(
    db: AsyncSession,
    novel_id: str | uuid.UUID,
    kind: RevisionTargetKind | str,
    ids,
) -> dict[uuid.UUID, str]:
    """批量读取一组修订的备注，返回 ``{revision_id: note}``；无备注的修订不在结果里。"""
    _validate_kind(kind)
    nid = parse_uuid(str(novel_id), "novel_id")
    revision_ids = [parse_uuid(str(value), "revision_id") for value in ids]
    if not revision_ids:
        return {}

    stmt = select(WorldRevisionNote).where(
        WorldRevisionNote.novel_id == nid,
        WorldRevisionNote.target_kind == kind,
        WorldRevisionNote.revision_id.in_(revision_ids),
    )
    notes = (await db.execute(stmt)).scalars().all()
    return {note.revision_id: note.note for note in notes}


async def set_revision_note(
    db: AsyncSession,
    novel_id: str | uuid.UUID,
    kind: RevisionTargetKind | str,
    revision_id: str | uuid.UUID,
    note: str,
) -> RevisionNoteResponse:
    """补写/修改/删除一条修订备注；空串表示删除。"""
    _validate_kind(kind)
    nid = parse_uuid(str(novel_id), "novel_id")
    rid = parse_uuid(str(revision_id), "revision_id")

    if note is None:
        raise ValidationError("note 不能为空", status_code=422)
    cleaned = note.strip()
    if len(cleaned) > REVISION_NOTE_MAX_LENGTH:
        raise ValidationError(
            f"备注最多 {REVISION_NOTE_MAX_LENGTH} 字，当前 {len(cleaned)} 字",
            status_code=422,
        )

    await _ensure_revision_visible(db, nid, kind, rid)

    stmt = select(WorldRevisionNote).where(
        WorldRevisionNote.novel_id == nid,
        WorldRevisionNote.target_kind == kind,
        WorldRevisionNote.revision_id == rid,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if cleaned == "":
        if existing is not None:
            await db.delete(existing)
            await db.flush()
        return RevisionNoteResponse(
            target_kind=kind,
            revision_id=str(rid),
            note=None,
            updated_at=datetime.now(UTC),
        )

    if existing is None:
        existing = WorldRevisionNote(
            novel_id=nid,
            target_kind=kind,
            revision_id=rid,
            note=cleaned,
        )
        db.add(existing)
    else:
        existing.note = cleaned
    await db.flush()

    updated_at = existing.updated_at or datetime.now(UTC)
    return RevisionNoteResponse(
        target_kind=kind,
        revision_id=str(rid),
        note=cleaned,
        updated_at=updated_at,
    )
