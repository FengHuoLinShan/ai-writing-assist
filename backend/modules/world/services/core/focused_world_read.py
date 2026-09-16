"""Novel-scoped identity and direct-edge reads; Evidence owns final visibility."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import or_, select

from modules.project.facade import require_active_project
from modules.world.contracts import CoreEntityContract, EntityRelationContract
from modules.world.models import CoreEntity, EntityRelation
from shared.utils import parse_uuid


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _entity(entity):
    aliases = (entity.content_json or {}).get("aliases") or []
    terms = [entity.name]
    for alias in aliases:
        if isinstance(alias, str):
            terms.append(alias)
        elif (
            isinstance(alias, dict)
            and alias.get("status")
            in {None, "active", "canonical", "confirmed", "published"}
            and not alias.get("rolled_back")
        ):
            terms.append(str(alias.get("alias") or ""))
    result = {
        key: getattr(entity, key)
        for key in (
            "name",
            "entity_type",
            "status",
            "summary",
            "public_info",
            "hidden_truth",
            "reveal_level",
        )
    }
    result.update(
        id=str(entity.id), terms=list(dict.fromkeys(term for term in terms if term))
    )
    result["source_hash"] = _hash(result)
    return result


async def get_terms(
    db, *, novel_id, entity_ids=None, names=None, include_review=False, skip=0, limit=128
):
    await require_active_project(db, novel_id)
    nid = parse_uuid(novel_id, "novel_id")
    statuses = ["canonical", "candidate", "draft"] if include_review else ["canonical"]
    query = (
        select(CoreEntity)
        .where(CoreEntity.novel_id == nid, CoreEntity.status.in_(statuses))
        .order_by(CoreEntity.id)
    )
    if entity_ids is not None:
        query = query.where(
            CoreEntity.id.in_([parse_uuid(value, "entity_id") for value in entity_ids])
        )
    if entity_ids is None and names is None:
        raise ValueError("Focused identity reads require ids or names")
    needles = {str(name).strip().casefold() for name in names or []}
    rows = (await db.execute(query)).scalars().all()
    items = [_entity(row) for row in rows]
    if names is not None:
        items = [
            item
            for item in items
            if needles.intersection(term.strip().casefold() for term in item["terms"])
        ]
    skip, limit = max(0, skip), min(256, max(1, limit))
    truncated = len(items) > skip + limit
    return {
        "entities": items[skip : skip + limit],
        "truncated": truncated,
        "next_skip": skip + limit if truncated else None,
    }


async def get_neighbors(
    db, *, novel_id, entity_ids, include_review=False, skip=0, limit=64
):
    await require_active_project(db, novel_id)
    nid = parse_uuid(novel_id, "novel_id")
    roots = [parse_uuid(value, "entity_id") for value in entity_ids]
    canonical = select(CoreEntity.id).where(
        CoreEntity.novel_id == nid, CoreEntity.status == "canonical"
    )
    skip, limit = max(0, skip), min(256, max(1, limit))
    query = (
        select(EntityRelation)
        .where(
            EntityRelation.novel_id == nid,
            EntityRelation.status == "canonical",
            EntityRelation.source_id.in_(canonical),
            EntityRelation.target_id.in_(canonical),
            or_(EntityRelation.source_id.in_(roots), EntityRelation.target_id.in_(roots)),
        )
        .order_by(EntityRelation.id)
        .offset(skip)
        .limit(limit + 1)
    )
    rows = list((await db.execute(query)).scalars().all())
    truncated = len(rows) > limit
    relations = []
    ids = set(roots)
    for row in rows[:limit]:
        ids.update((row.source_id, row.target_id))
        relations.append(relation_projection(row))
    entities = await get_terms(
        db,
        novel_id=novel_id,
        entity_ids=[str(value) for value in ids],
        include_review=include_review,
        limit=256,
    )
    return {
        "entities": entities["entities"],
        "relations": relations,
        "truncated": truncated,
        "next_skip": skip + limit if truncated else None,
    }


def relation_projection(row):
    item = {
        key: getattr(row, key)
        for key in (
            "relation_type",
            "relation_kind",
            "description",
            "quote",
            "status",
            "review_meta",
        )
    }
    item.update(
        id=str(row.id),
        source_id=str(row.source_id),
        target_id=str(row.target_id),
        source_scene_id=(row.review_meta or {}).get("scene_id"),
    )
    item["source_hash"] = _hash(item)
    return item


async def get_hidden_guard_sources(
    db,
    *,
    novel_id: str,
    entity_ids: list[str],
    relation_ids: list[str],
) -> tuple[list[CoreEntityContract], list[EntityRelationContract]]:
    """Batch-read the exact frozen World sources needed by Hidden Guard."""
    await require_active_project(db, novel_id)
    nid = parse_uuid(novel_id, "novel_id")
    parsed_entities = list(
        dict.fromkeys(parse_uuid(value, "entity_id") for value in entity_ids)
    )
    parsed_relations = list(
        dict.fromkeys(parse_uuid(value, "relation_id") for value in relation_ids)
    )
    entities = (
        list(
            (
                await db.execute(
                    select(CoreEntity)
                    .where(
                        CoreEntity.novel_id == nid,
                        CoreEntity.id.in_(parsed_entities),
                    )
                    .order_by(CoreEntity.id)
                )
            )
            .scalars()
            .all()
        )
        if parsed_entities
        else []
    )
    relations = (
        list(
            (
                await db.execute(
                    select(EntityRelation)
                    .where(
                        EntityRelation.novel_id == nid,
                        EntityRelation.id.in_(parsed_relations),
                    )
                    .order_by(EntityRelation.id)
                )
            )
            .scalars()
            .all()
        )
        if parsed_relations
        else []
    )
    return (
        [
            CoreEntityContract(
                novel_id=str(entity.novel_id),
                entity_id=str(entity.id),
                entity_type=entity.entity_type,
                name=entity.name,
                summary=entity.summary,
                public_info=entity.public_info,
                hidden_truth=entity.hidden_truth,
                importance=float(
                    entity.importance if entity.importance is not None else 0.5
                ),
                importance_level=entity.importance_level or "normal",
                reveal_level=entity.reveal_level or "author_only",
                status=entity.status,
            )
            for entity in entities
        ],
        [
            EntityRelationContract(
                novel_id=str(relation.novel_id),
                relation_id=str(relation.id),
                source_id=str(relation.source_id),
                target_id=str(relation.target_id),
                relation_type=relation.relation_type,
                description=relation.description,
                strength=float(
                    relation.strength if relation.strength is not None else 0.5
                ),
                status=relation.status,
            )
            for relation in relations
        ],
    )
