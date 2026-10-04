"""按修订恢复（阶段 0）— WorldEntityService.rollback_to_revision 服务层行为。

覆盖：成功恢复（含空字段清空、status 不变、_meta 保留当前来源标记、
rollback 记录带 restored_from_revision_id）；基线过期 409 且不落任何写入；
缺基线 409；跨实体/跨作品 404；Canon 门禁 409；改类型时缓存失效。

路由级断言（expected_updated_at 必填、响应形状）由 P2b 接线 API 后补充。
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select

from core.errors import ConflictError, NotFoundError
from modules.world.models import CoreEntity, EntityRevision
from modules.world.schemas import CoreEntityUpdate
from modules.world.services.core.entity_service import WorldEntityService
from modules.world.services.worldbuilding.world_validation_service import (
    WorldValidationService,
)
from tests.utils import _create_entity


async def _make_entity(db_session, novel_id: str, **overrides) -> CoreEntity:
    payload = {
        "entity_type": "character",
        "name": "白砚",
        "summary": "初版摘要",
        "status": "canonical",
    }
    payload.update(overrides)
    entity = await _create_entity(db_session, novel_id, **payload)
    entity.content_json = {"_meta": {"source": "manual"}, "note": "初始"}
    await db_session.flush()
    return entity


async def _revision_count(db_session, entity_id) -> int:
    rows = await db_session.execute(
        select(EntityRevision).where(EntityRevision.entity_id == entity_id)
    )
    return len(rows.scalars().all())


async def _latest_revision(db_session, entity_id) -> EntityRevision | None:
    rows = await db_session.execute(
        select(EntityRevision)
        .where(EntityRevision.entity_id == entity_id)
        .order_by(EntityRevision.created_at.desc(), EntityRevision.id.desc())
    )
    return rows.scalars().first()


async def test_rollback_restores_fields_and_clears_empty(
    db_session, project_novel_id: str
) -> None:
    entity = await _make_entity(db_session, project_novel_id)
    service = WorldEntityService()

    first = await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(
            summary="第二版摘要",
            public_info="公开设定",
            hidden_truth="作者秘密",
            content_json={
                "_meta": {"source": "manual"},
                "note": "改后",
                "aliases": [{"alias": "白衣", "kind": "name", "type": "nickname"}],
            },
        ),
        novel_id=project_novel_id,
    )
    assert first.summary == "第二版摘要"

    revisions = (
        (
            await db_session.execute(
                select(EntityRevision).where(EntityRevision.entity_id == entity.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(revisions) == 1
    target = revisions[0]

    restored = await service.rollback_to_revision(
        db_session,
        str(entity.id),
        str(target.id),
        novel_id=project_novel_id,
        expected_updated_at=first.updated_at,
    )

    # 恢复到第一次改动之前：summary 回到初版；快照为空的列被显式清空。
    assert restored.summary == "初版摘要"
    assert restored.public_info is None
    assert restored.hidden_truth is None
    # status 不参与恢复。
    assert restored.status == "canonical"
    # content_json 恢复快照内容（去 _meta 后合并当前 _meta）。
    assert restored.content_json is not None
    assert restored.content_json["note"] == "初始"
    assert "aliases" not in restored.content_json
    assert restored.content_json["_meta"]["source"] == "manual"

    # 恢复前先打 reason=rollback 的快照，并记录 restored_from_revision_id。
    latest = await _latest_revision(db_session, entity.id)
    assert latest is not None
    assert latest.revision_reason == "rollback"
    assert latest.change_summary is not None
    assert latest.change_summary.get("restored_from_revision_id") == str(target.id)
    before = dict(latest.snapshot or {})
    assert before.get("summary") == "第二版摘要"
    assert before.get("public_info") == "公开设定"


async def test_rollback_stale_baseline_conflicts_without_writes(
    db_session, project_novel_id: str
) -> None:
    entity = await _make_entity(db_session, project_novel_id)
    service = WorldEntityService()

    updated = await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="第二版摘要"),
        novel_id=project_novel_id,
    )
    revisions = (
        (
            await db_session.execute(
                select(EntityRevision).where(EntityRevision.entity_id == entity.id)
            )
        )
        .scalars()
        .all()
    )
    target = revisions[0]
    stale = updated.updated_at - timedelta(seconds=5)

    with pytest.raises(ConflictError) as exc_info:
        await service.rollback_to_revision(
            db_session,
            str(entity.id),
            str(target.id),
            novel_id=project_novel_id,
            expected_updated_at=stale,
        )
    assert exc_info.value.code == "edit_baseline_stale"

    # 基线过期时不产生任何写入：无 rollback 快照，实体保持改后状态。
    assert await _revision_count(db_session, entity.id) == 1
    await db_session.refresh(entity)
    assert entity.summary == "第二版摘要"


async def test_rollback_requires_baseline(db_session, project_novel_id: str) -> None:
    entity = await _make_entity(db_session, project_novel_id)
    service = WorldEntityService()

    await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="第二版摘要"),
        novel_id=project_novel_id,
    )
    revisions = (
        (
            await db_session.execute(
                select(EntityRevision).where(EntityRevision.entity_id == entity.id)
            )
        )
        .scalars()
        .all()
    )
    target = revisions[0]

    with pytest.raises(ConflictError) as exc_info:
        await service.rollback_to_revision(
            db_session,
            str(entity.id),
            str(target.id),
            novel_id=project_novel_id,
            expected_updated_at=None,
        )
    assert exc_info.value.code == "edit_baseline_required"
    assert await _revision_count(db_session, entity.id) == 1


async def test_rollback_rejects_foreign_revision(
    db_session, project_novel_id: str, two_projects: tuple[str, str]
) -> None:
    other_novel = two_projects[1]
    entity_a = await _make_entity(db_session, project_novel_id)
    entity_b = await _make_entity(db_session, project_novel_id, name="沈墨")
    service = WorldEntityService()

    await service.update(
        db_session,
        str(entity_b.id),
        CoreEntityUpdate(summary="沈墨第二版"),
        novel_id=project_novel_id,
    )
    revision_b = (
        (
            await db_session.execute(
                select(EntityRevision).where(EntityRevision.entity_id == entity_b.id)
            )
        )
        .scalars()
        .all()
    )[0]

    # 同作品但修订属于另一实体。
    with pytest.raises(NotFoundError):
        await service.rollback_to_revision(
            db_session,
            str(entity_a.id),
            str(revision_b.id),
            novel_id=project_novel_id,
            expected_updated_at=entity_a.updated_at,
        )
    assert await _revision_count(db_session, entity_a.id) == 0

    # 修订属于另一作品。
    with pytest.raises(NotFoundError):
        await service.rollback_to_revision(
            db_session,
            str(entity_b.id),
            str(revision_b.id),
            novel_id=other_novel,
            expected_updated_at=entity_b.updated_at,
        )


async def test_rollback_blocked_by_canon_validation_policy(
    db_session, project_novel_id: str
) -> None:
    entity = await _make_entity(db_session, project_novel_id)
    service = WorldEntityService()

    updated = await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="第二版摘要"),
        novel_id=project_novel_id,
    )
    revisions = (
        (
            await db_session.execute(
                select(EntityRevision).where(EntityRevision.entity_id == entity.id)
            )
        )
        .scalars()
        .all()
    )
    target = revisions[0]

    await WorldValidationService().activate_builtin_policy(db_session, project_novel_id)
    with pytest.raises(ConflictError) as exc_info:
        await service.rollback_to_revision(
            db_session,
            str(entity.id),
            str(target.id),
            novel_id=project_novel_id,
            expected_updated_at=updated.updated_at,
        )
    assert exc_info.value.code == "required_validation"
    assert await _revision_count(db_session, entity.id) == 1


async def test_rollback_type_change_invalidates_asset_context(
    db_session, project_novel_id: str
) -> None:
    entity = await _make_entity(db_session, project_novel_id)
    service = WorldEntityService()

    updated = await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="第二版摘要"),
        novel_id=project_novel_id,
    )
    revisions = (
        (
            await db_session.execute(
                select(EntityRevision).where(EntityRevision.entity_id == entity.id)
            )
        )
        .scalars()
        .all()
    )
    target = revisions[0]

    # 直接把类型改成 location（绕过服务层转换链），再恢复到 character 快照。
    entity.entity_type = "location"
    await db_session.flush()
    await db_session.refresh(entity)

    with patch(
        "modules.evidence.facade.mark_asset_context_changed",
        autospec=True,
    ) as mark_changed:
        await service.rollback_to_revision(
            db_session,
            str(entity.id),
            str(target.id),
            novel_id=project_novel_id,
            expected_updated_at=entity.updated_at,
        )
        # update() 的常规失效链也会触发；此处只需断言类型转换失效被触发。
        reasons = [call.kwargs.get("reason") for call in mark_changed.await_args_list]
        assert "entity_type_changed" in reasons
        type_call = next(
            call
            for call in mark_changed.await_args_list
            if call.kwargs.get("reason") == "entity_type_changed"
        )
        assert type_call.kwargs["asset_id"] == str(entity.id)

    await db_session.refresh(entity)
    assert entity.entity_type == "character"
    assert updated.updated_at is not None
