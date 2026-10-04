"""实体改动历史（阶段 0）— 服务层行为。

覆盖：时间带时区；改动字段识别（别名单独拆出、忽略内部来源标记、无改动时
返回空列表）；写作进度落库；旧记录（无 change_summary）推算并标"大致"；
同一时间戳的排序稳定；deprecated 实体不给恢复；备注批量读取。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from modules.world.models import CoreEntity, EntityRevision
from modules.world.schemas import CoreEntityUpdate
from modules.world.services.core.entity_service import WorldEntityService
from modules.world.services.revision_notes import set_revision_note
from tests.utils import _create_entity, _create_project


async def _make_entity(db_session, novel_id: str, **overrides) -> CoreEntity:
    payload = {
        "entity_type": "character",
        "name": "白砚",
        "summary": "初版摘要",
        "status": "canonical",
    }
    payload.update(overrides)
    return await _create_entity(db_session, novel_id, **payload)


async def test_created_at_has_timezone(db_session, project_novel_id: str) -> None:
    entity = await _make_entity(db_session, project_novel_id)
    service = WorldEntityService()
    await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="第二版摘要"),
        novel_id=project_novel_id,
    )

    from modules.world.services.core.entity_revision_service import (
        EntityRevisionService,
    )

    response = await EntityRevisionService().get_revisions(
        db_session, str(entity.id), project_novel_id
    )

    assert response.total == 1
    item = response.items[0]
    assert item.created_at.tzinfo is not None
    assert item.created_at.utcoffset().total_seconds() == 0
    assert response.current_updated_at is not None
    assert response.current_updated_at.tzinfo is not None


async def test_changed_fields_summary_recorded_exact(
    db_session, project_novel_id: str
) -> None:
    entity = await _make_entity(db_session, project_novel_id)
    service = WorldEntityService()
    await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="第二版摘要"),
        novel_id=project_novel_id,
    )

    from modules.world.services.core.entity_revision_service import (
        EntityRevisionService,
    )

    response = await EntityRevisionService().get_revisions(
        db_session, str(entity.id), project_novel_id
    )
    item = response.items[0]
    assert item.changed_fields == ["summary"]
    assert item.changed_fields_exact is True
    assert item.snapshot.summary == "初版摘要"


async def test_changed_fields_alias_split_and_meta_ignored(
    db_session, project_novel_id: str
) -> None:
    entity = await _make_entity(db_session, project_novel_id)
    entity.content_json = {"_meta": {"source": "manual"}}
    await db_session.flush()
    service = WorldEntityService()

    # 只加别名：改动字段是 aliases，而不是 content。
    await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(
            content_json={
                "_meta": {"source": "manual"},
                "aliases": [
                    {"alias": "白衣", "kind": "name", "type": "nickname"},
                ],
            }
        ),
        novel_id=project_novel_id,
    )
    # 再改一次只动内部来源标记：无实质改动，返回空列表。
    second = await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(
            content_json={
                "_meta": {"source": "manual", "user_edited": True},
                "aliases": [
                    {"alias": "白衣", "kind": "name", "type": "nickname"},
                ],
            }
        ),
        novel_id=project_novel_id,
    )
    assert second.content_json is not None
    assert second.content_json["_meta"]["user_edited"] is True

    from modules.world.services.core.entity_revision_service import (
        EntityRevisionService,
    )

    response = await EntityRevisionService().get_revisions(
        db_session, str(entity.id), project_novel_id
    )
    assert response.total == 2
    latest, previous = response.items[0], response.items[1]
    assert latest.changed_fields == []
    assert latest.changed_fields_exact is True
    assert previous.changed_fields == ["aliases"]
    assert previous.changed_fields_exact is True
    # 快照视图：别名单独拆出，content_json 不含 _meta/aliases。
    # items 倒序：latest 是第二次更新前（已含别名）的快照，previous 无别名。
    assert latest.snapshot.aliases == ["白衣"]
    assert "_meta" not in latest.snapshot.content_json
    assert "aliases" not in latest.snapshot.content_json
    assert previous.snapshot.aliases == []


async def test_noop_update_records_empty_fields(
    db_session, project_novel_id: str
) -> None:
    entity = await _make_entity(db_session, project_novel_id)
    service = WorldEntityService()
    await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="同值摘要"),
        novel_id=project_novel_id,
    )
    await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="同值摘要"),
        novel_id=project_novel_id,
    )

    from modules.world.services.core.entity_revision_service import (
        EntityRevisionService,
    )

    response = await EntityRevisionService().get_revisions(
        db_session, str(entity.id), project_novel_id
    )
    assert response.items[0].changed_fields == []
    assert response.items[0].changed_fields_exact is True


async def test_writing_chapter_index_recorded(db_session, project_novel_id: str) -> None:
    from modules.writing.facade import create_published_draft_only

    entity = await _make_entity(db_session, project_novel_id)
    service = WorldEntityService()

    # 没有正文时记录 0（动笔前）。
    await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="动笔前编辑"),
        novel_id=project_novel_id,
    )
    await create_published_draft_only(
        db_session, project_novel_id, 6, "第六章", "第六章的正文"
    )
    await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="写到第六章时的编辑"),
        novel_id=project_novel_id,
    )

    from modules.world.services.core.entity_revision_service import (
        EntityRevisionService,
    )

    response = await EntityRevisionService().get_revisions(
        db_session, str(entity.id), project_novel_id
    )
    assert response.items[0].writing_chapter_index == 6
    assert response.items[1].writing_chapter_index == 0


async def test_legacy_revision_estimates_fields_as_inexact(
    db_session, project_novel_id: str
) -> None:
    entity = await _make_entity(db_session, project_novel_id)
    service = WorldEntityService()
    await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="二版"),
        novel_id=project_novel_id,
    )
    await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="三版"),
        novel_id=project_novel_id,
    )

    # 把较早一条的保存记录抹掉，模拟功能上线前的旧记录。
    rows = (
        (
            await db_session.execute(
                select(EntityRevision)
                .where(EntityRevision.entity_id == entity.id)
                .order_by(EntityRevision.created_at.desc(), EntityRevision.id.desc())
            )
        )
        .scalars()
        .all()
    )
    legacy = rows[1]
    legacy.change_summary = None
    await db_session.flush()

    from modules.world.services.core.entity_revision_service import (
        EntityRevisionService,
    )

    response = await EntityRevisionService().get_revisions(
        db_session, str(entity.id), project_novel_id
    )
    latest, estimated = response.items[0], response.items[1]
    assert latest.changed_fields == ["summary"]
    assert latest.changed_fields_exact is True
    assert estimated.changed_fields == ["summary"]
    assert estimated.changed_fields_exact is False


async def test_same_timestamp_ordering_is_stable(
    db_session, project_novel_id: str
) -> None:
    entity = await _make_entity(db_session, project_novel_id)
    service = WorldEntityService()
    for index in range(4):
        await service.update(
            db_session,
            str(entity.id),
            CoreEntityUpdate(summary=f"第{index}版"),
            novel_id=project_novel_id,
        )

    rows = (
        (
            await db_session.execute(
                select(EntityRevision).where(EntityRevision.entity_id == entity.id)
            )
        )
        .scalars()
        .all()
    )
    expected = [
        str(row.id)
        for row in sorted(
            rows, key=lambda row: (row.created_at, str(row.id)), reverse=True
        )
    ]

    from modules.world.services.core.entity_revision_service import (
        EntityRevisionService,
    )

    response = await EntityRevisionService().get_revisions(
        db_session, str(entity.id), project_novel_id
    )
    assert [item.revision_id for item in response.items] == expected


async def test_deprecated_entity_cannot_restore(
    db_session, project_novel_id: str
) -> None:
    entity = await _make_entity(db_session, project_novel_id)
    service = WorldEntityService()
    await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="编辑后"),
        novel_id=project_novel_id,
    )
    await service.delete(db_session, str(entity.id), novel_id=project_novel_id)

    from modules.world.services.core.entity_revision_service import (
        EntityRevisionService,
    )

    response = await EntityRevisionService().get_revisions(
        db_session, str(entity.id), project_novel_id
    )
    assert all(item.can_restore is False for item in response.items)
    assert response.total >= 2


async def test_change_note_loaded_in_batch(db_session, project_novel_id: str) -> None:
    entity = await _make_entity(db_session, project_novel_id)
    service = WorldEntityService()
    await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="二版"),
        novel_id=project_novel_id,
    )
    await service.update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="三版"),
        novel_id=project_novel_id,
    )
    rows = (
        (
            await db_session.execute(
                select(EntityRevision)
                .where(EntityRevision.entity_id == entity.id)
                .order_by(EntityRevision.created_at.desc(), EntityRevision.id.desc())
            )
        )
        .scalars()
        .all()
    )
    await set_revision_note(
        db_session, project_novel_id, "entity", str(rows[0].id), "这次改了性格"
    )

    from modules.world.services.core.entity_revision_service import (
        EntityRevisionService,
    )

    response = await EntityRevisionService().get_revisions(
        db_session, str(entity.id), project_novel_id
    )
    assert response.items[0].change_note == "这次改了性格"
    assert response.items[1].change_note is None


async def test_cross_novel_entity_rejected(db_session) -> None:
    novel_a = uuid.uuid4().hex
    novel_b = uuid.uuid4().hex
    await _create_project(db_session, novel_a)
    await _create_project(db_session, novel_b)
    entity = await _make_entity(db_session, novel_a)

    from core.errors import NotFoundError
    from modules.world.services.core.entity_revision_service import (
        EntityRevisionService,
    )

    with pytest.raises(NotFoundError):
        await EntityRevisionService().get_revisions(db_session, str(entity.id), novel_b)


async def test_estimated_boundary_reads_adjacent_newer_revision(
    db_session, project_novel_id: str
) -> None:
    """翻页首条的推算额外读取相邻一条更新的修订，不重不漏。"""
    entity = await _make_entity(db_session, project_novel_id)
    service = WorldEntityService()
    for index in range(3):
        await service.update(
            db_session,
            str(entity.id),
            CoreEntityUpdate(summary=f"第{index}版"),
            novel_id=project_novel_id,
        )
    rows = (
        (
            await db_session.execute(
                select(EntityRevision)
                .where(EntityRevision.entity_id == entity.id)
                .order_by(EntityRevision.created_at.desc(), EntityRevision.id.desc())
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.change_summary = None
    await db_session.flush()

    from modules.world.services.core.entity_revision_service import (
        EntityRevisionService,
    )

    full = await EntityRevisionService().get_revisions(
        db_session, str(entity.id), project_novel_id
    )
    page2 = await EntityRevisionService().get_revisions(
        db_session, str(entity.id), project_novel_id, skip=1, limit=1
    )
    page3 = await EntityRevisionService().get_revisions(
        db_session, str(entity.id), project_novel_id, skip=2, limit=1
    )
    # 全量结果做基准：每条的推算字段与对应翻页结果一致。
    assert page2.items[0].revision_id == full.items[1].revision_id
    assert page2.items[0].changed_fields == full.items[1].changed_fields
    assert page3.items[0].revision_id == full.items[2].revision_id
    assert page3.items[0].changed_fields == full.items[2].changed_fields
    assert page2.items[0].changed_fields_exact is False
