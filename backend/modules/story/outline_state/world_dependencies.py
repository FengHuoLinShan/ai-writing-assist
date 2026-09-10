"""Read-only, versioned structure references for World change review."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select

from core.errors import NotFoundError
from modules.story.contracts import StoryWorldDependencyContract
from modules.story.outline_state.models import (
    OutlineArc,
    PlotThread,
    Scene,
    StoryOutlineHead,
    StoryOutlineRevision,
)
from shared.utils import parse_uuid

_MODELS = {"story_thread": PlotThread, "outline_arc": OutlineArc, "outline_scene": Scene}
_TEXT_FIELDS = {
    "story_thread": ("name", "summary", "visible_goal", "current_stage"),
    "outline_arc": (
        "title",
        "arc_goal",
        "core_conflict",
        "main_opposition",
        "entry_hook",
        "midpoint_turn",
        "climax",
        "result",
        "next_hook",
    ),
    "outline_scene": (
        "title",
        "goal",
        "core_conflict",
        "emotional_beat",
        "must_happen",
        "must_not_happen",
    ),
}


def _snapshot(kind, row, match_basis="declared"):
    fields = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    for key, value in fields.items():
        if isinstance(value, datetime):
            fields[key] = (
                value.replace(tzinfo=UTC)
                if value.tzinfo is None
                else value.astimezone(UTC)
            ).isoformat()
    source_hash = hashlib.sha256(
        json.dumps(fields, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()
    names = _TEXT_FIELDS.get(kind, ("title", "outline_markdown"))
    return StoryWorldDependencyContract(
        kind=kind,
        id=str(row.id),
        label=getattr(row, "name", None) or getattr(row, "title", None) or "未命名场景",
        version=str(
            getattr(row, "version_number", None)
            or fields["updated_at"]
            or fields["created_at"]
        ),
        source_hash=source_hash,
        text="\n\n".join(
            str(getattr(row, name)) for name in names if getattr(row, name, None)
        ),
        match_basis=match_basis,
    )


async def list_world_dependencies(db, novel_id, entity_ids, terms):
    nid = parse_uuid(novel_id, "novel_id")
    wanted = {str(item) for item in entity_ids}
    items = []
    for kind, model in _MODELS.items():
        # ponytail: author-triggered scan; add JSON indexes if structure scans get slow.
        rows = (
            await db.scalars(
                select(model)
                .where(
                    model.novel_id == nid,
                    model.status.in_(("candidate", "draft", "canonical")),
                )
                .order_by(model.id)
            )
        ).all()
        for row in rows:
            if kind == "outline_scene":
                meta = row.structure_meta or {}
                related = {str(row.pov_character_id or "")}
                for key in (
                    "related_entity_ids",
                    "related_character_ids",
                    "present_character_ids",
                    "character_ids",
                ):
                    related.update(str(item) for item in meta.get(key) or [])
            else:
                related = {
                    str(item)
                    for item in [
                        *(row.related_entity_ids or []),
                        *(row.related_character_ids or []),
                    ]
                }
            if wanted & related:
                items.append(_snapshot(kind, row))
    revision = await db.scalar(
        select(StoryOutlineRevision)
        .join(
            StoryOutlineHead,
            (StoryOutlineHead.current_revision_id == StoryOutlineRevision.id)
            & (StoryOutlineHead.novel_id == StoryOutlineRevision.novel_id),
        )
        .where(StoryOutlineHead.novel_id == nid)
    )
    if revision:
        sources = (revision.provenance_json or {}).get("source_refs") or []
        declared = any(
            str(ref.get("id")) in wanted for ref in sources if isinstance(ref, dict)
        )
        if declared or any(term and term in revision.outline_markdown for term in terms):
            items.append(
                _snapshot(
                    "story_outline", revision, "declared" if declared else "literal"
                )
            )
    return items


async def read_world_dependency(db, novel_id, kind, source_id):
    nid = parse_uuid(novel_id, "novel_id")
    sid = parse_uuid(source_id, "source_id")
    model = _MODELS.get(kind)
    if kind == "story_outline":
        row = await db.scalar(
            select(StoryOutlineRevision)
            .join(
                StoryOutlineHead,
                (StoryOutlineHead.current_revision_id == StoryOutlineRevision.id)
                & (StoryOutlineHead.novel_id == StoryOutlineRevision.novel_id),
            )
            .where(StoryOutlineHead.novel_id == nid, StoryOutlineRevision.id == sid)
        )
    elif model:
        row = await db.scalar(
            select(model).where(
                model.id == sid,
                model.novel_id == nid,
                model.status.in_(("candidate", "draft", "canonical")),
            )
        )
    else:
        row = None
    if row is None:
        raise NotFoundError("故事来源已变化或不存在")
    return _snapshot(kind, row)
