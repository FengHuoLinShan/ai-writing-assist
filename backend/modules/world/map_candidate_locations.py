"""Bounded adoption previews; execution remains the original World promotion API."""

from uuid import UUID

from sqlalchemy import select

from core.container import get
from core.errors import DomainError
from core.service_keys import WORLD_WORLDBUILDING_REQUIRE_LEGACY_CANON_WRITE_ALLOWED
from modules.world.map_structure_service import source_digest, source_payload
from modules.world.models import CoreEntity
from modules.world.services.common import require_fresh_understanding_source


def promotion_source_hash(entity):
    return source_digest({"entity_type": entity.entity_type, **source_payload(entity)})


async def preview_candidate_locations(db, novel_id, documents):
    ids = {
        feature.entity_id
        for document in documents
        for feature in document.features
        if feature.entity_id is not None
    }
    if not ids:
        return [], False
    rows = list(
        (
            await db.scalars(
                select(CoreEntity)
                .where(
                    CoreEntity.novel_id == UUID(str(novel_id)),
                    CoreEntity.id.in_(ids),
                    CoreEntity.entity_type == "location",
                    CoreEntity.status.in_(["candidate", "draft"]),
                )
                .order_by(CoreEntity.id)
                .limit(21)
            )
        ).all()
    )
    result = []
    for entity in rows[:20]:
        metadata = (entity.content_json or {}).get("_meta") or {}
        reason = None
        try:
            await get(WORLD_WORLDBUILDING_REQUIRE_LEGACY_CANON_WRITE_ALLOWED)(
                db, novel_id, next_action="create_world_adoption_package"
            )
            if metadata.get("compatibility_shadow") is True:
                reason = "该地点由待处理建议管理，请到世界资料页采用对应建议"
            else:
                await require_fresh_understanding_source(db, novel_id, metadata)
        except DomainError as error:
            reason = str(error)
        result.append(
            {
                "entity_id": str(entity.id),
                "name": entity.name,
                "status": entity.status,
                "can_adopt": reason is None,
                "block_reason": reason,
                "source_hash": promotion_source_hash(entity),
                "promotion_endpoint": f"/api/world/entities/{entity.id}/promote",
            }
        )
    return result, len(rows) > 20
