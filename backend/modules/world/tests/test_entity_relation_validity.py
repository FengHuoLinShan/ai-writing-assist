from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError as DomainValidationError
from modules.story.outline_state.models import Scene
from modules.world.models import CoreEntity, EntityRelation
from modules.world.repositories import EntityRelationRepository
from modules.world.schemas import (
    EntityRelationCreate,
    EntityRelationReviewEditRequest,
    EntityRelationUpdate,
)
from modules.world.schemas.dossier import DossierValidity
from modules.world.services.core.entity_relation_service import EntityRelationService


async def _seed_relation(
    db: AsyncSession,
    novel_id: str,
    *,
    status: str,
    validity: DossierValidity | None = None,
) -> EntityRelation:
    nid = uuid.UUID(novel_id)
    source = CoreEntity(
        novel_id=nid,
        entity_type="character",
        name=f"source-{uuid.uuid4()}",
        status="canonical",
    )
    target = CoreEntity(
        novel_id=nid,
        entity_type="character",
        name=f"target-{uuid.uuid4()}",
        status="canonical",
    )
    db.add_all([source, target])
    await db.flush()
    relation = await EntityRelationRepository().create(
        db,
        nid,
        EntityRelationCreate(
            source_id=str(source.id),
            target_id=str(target.id),
            relation_type="ally_of",
            relation_kind="social",
            status=status,
        ),
    )
    if validity is not None:
        relation.validity_json = validity.model_dump(mode="json")
        await db.flush()
    return relation


def _validity(scene_id: uuid.UUID) -> DossierValidity:
    return DossierValidity(start={"kind": "scene", "id": scene_id})


@pytest.mark.asyncio
async def test_relation_demotion_requires_explicitly_clearing_validity(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    scene = Scene(novel_id=uuid.UUID(project_novel_id), scene_index=1, status="draft")
    db_session.add(scene)
    await db_session.flush()
    interval = _validity(scene.id)
    relation = await _seed_relation(
        db_session, project_novel_id, status="canonical", validity=interval
    )
    service = EntityRelationService()

    with pytest.raises(DomainValidationError, match="只有正式关系"):
        await service.update(
            db_session,
            str(relation.id),
            EntityRelationUpdate(status="candidate"),
            novel_id=project_novel_id,
        )

    await db_session.refresh(relation)
    assert relation.status == "canonical"
    assert relation.validity_json == interval.model_dump(mode="json")

    demoted = await service.update(
        db_session,
        str(relation.id),
        EntityRelationUpdate(status="candidate", validity=None),
        novel_id=project_novel_id,
    )
    assert demoted.status == "candidate"
    assert demoted.validity is None

    with pytest.raises(DomainValidationError, match="只有正式关系"):
        await service.update(
            db_session,
            str(relation.id),
            EntityRelationUpdate(validity=interval),
            novel_id=project_novel_id,
        )


@pytest.mark.asyncio
async def test_canonical_relation_update_validates_retained_and_novel_scoped_anchors(
    db_session: AsyncSession,
    two_projects: tuple[str, str],
) -> None:
    novel_id, other_novel_id = two_projects
    scene = Scene(novel_id=uuid.UUID(novel_id), scene_index=1, status="draft")
    foreign_scene = Scene(
        novel_id=uuid.UUID(other_novel_id), scene_index=2, status="draft"
    )
    db_session.add_all([scene, foreign_scene])
    await db_session.flush()
    relation = await _seed_relation(db_session, novel_id, status="canonical")
    service = EntityRelationService()

    updated = await service.update(
        db_session,
        str(relation.id),
        EntityRelationUpdate(validity=_validity(scene.id)),
        novel_id=novel_id,
    )
    assert updated.validity == _validity(scene.id)

    with pytest.raises(DomainValidationError, match="锚点无效"):
        await service.update(
            db_session,
            str(relation.id),
            EntityRelationUpdate(validity=_validity(foreign_scene.id)),
            novel_id=novel_id,
        )

    await db_session.delete(scene)
    await db_session.flush()
    with pytest.raises(DomainValidationError, match="锚点无效"):
        await service.update(
            db_session,
            str(relation.id),
            EntityRelationUpdate(description="编辑描述"),
            novel_id=novel_id,
        )


@pytest.mark.asyncio
async def test_review_confirmation_checks_final_status_and_project_anchor(
    db_session: AsyncSession,
    two_projects: tuple[str, str],
) -> None:
    novel_id, other_novel_id = two_projects
    scene = Scene(novel_id=uuid.UUID(novel_id), scene_index=1, status="draft")
    foreign_scene = Scene(
        novel_id=uuid.UUID(other_novel_id), scene_index=2, status="draft"
    )
    db_session.add_all([scene, foreign_scene])
    await db_session.flush()
    relation = await _seed_relation(db_session, novel_id, status="candidate")
    service = EntityRelationService()

    with pytest.raises(DomainValidationError, match="只有正式关系"):
        await service.review_edit(
            db_session,
            novel_id,
            str(relation.id),
            EntityRelationReviewEditRequest(
                confirm_review=False,
                validity=_validity(scene.id),
            ),
        )

    with pytest.raises(DomainValidationError, match="锚点无效"):
        await service.review_edit(
            db_session,
            novel_id,
            str(relation.id),
            EntityRelationReviewEditRequest(validity=_validity(foreign_scene.id)),
        )

    confirmed = await service.review_edit(
        db_session,
        novel_id,
        str(relation.id),
        EntityRelationReviewEditRequest(validity=_validity(scene.id)),
    )
    assert confirmed["relation"]["status"] == "canonical"
    assert confirmed["relation"]["validity"] == _validity(scene.id).model_dump(
        mode="json"
    )
