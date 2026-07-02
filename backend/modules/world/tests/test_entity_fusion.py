from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.entity_fusion import WorldEntityFusionService
from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import CoreEntityCreate, EntityFusionApplyItem

pytestmark = [pytest.mark.asyncio]


async def _create_entity(
    db: AsyncSession,
    novel_id: str,
    *,
    name: str,
    status: str,
    entity_type: str = "character",
) -> str:
    repo = CoreEntityRepository()
    entity = await repo.create(
        db,
        uuid.UUID(hex=novel_id),
        CoreEntityCreate(
            name=name,
            entity_type=entity_type,
            summary=f"{name} 摘要",
            status=status,
        ),
    )
    return str(entity.id)


async def test_entity_fusion_alias_only_persists_alias(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    source_id = await _create_entity(
        db_session,
        project_novel_id,
        name="周明瑞",
        status="draft",
    )
    target_id = await _create_entity(
        db_session,
        project_novel_id,
        name="克莱恩",
        status="canonical",
    )

    result = await WorldEntityFusionService().apply(
        db_session,
        novel_id=project_novel_id,
        confirmed=True,
        suggestions=[
            EntityFusionApplyItem(
                action="alias_only",
                source_entity_id=source_id,
                target_entity_id=target_id,
                alias="周明瑞",
            )
        ],
    )

    assert result["applied"] == 1
    target = await CoreEntityRepository().get(db_session, uuid.UUID(hex=target_id))
    assert target is not None
    aliases = (target.content_json or {}).get("aliases", [])
    assert any(alias.get("alias") == "周明瑞" for alias in aliases)


async def test_entity_fusion_canonical_merge_requires_explicit_confirmation(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    source_id = await _create_entity(
        db_session,
        project_novel_id,
        name="林七",
        status="canonical",
    )
    target_id = await _create_entity(
        db_session,
        project_novel_id,
        name="林柒",
        status="canonical",
    )

    result = await WorldEntityFusionService().apply(
        db_session,
        novel_id=project_novel_id,
        confirmed=True,
        suggestions=[
            EntityFusionApplyItem(
                action="merge",
                source_entity_id=source_id,
                target_entity_id=target_id,
            )
        ],
    )

    assert result["applied"] == 0
    assert result["skipped"] == 1
    assert "二次确认" in result["warnings"][0]
