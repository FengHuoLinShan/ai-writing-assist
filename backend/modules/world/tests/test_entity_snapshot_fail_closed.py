"""快照失败即中止（阶段 0）— 手动编辑/提升路径不再尽力而为。

create_snapshot 抛错时：update 与 promote 把错误向上抛且实体保持原状；
delete 维持尽力而为语义，废弃仍成功。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from modules.world.models import CoreEntity
from modules.world.schemas import CoreEntityUpdate, EntityPromoteRequest
from modules.world.services.core.entity_revision_service import (
    EntityRevisionService,
)
from modules.world.services.core.entity_service import WorldEntityService
from tests.utils import _create_entity


async def _make_entity(db_session, novel_id: str, **overrides) -> CoreEntity:
    payload = {
        "entity_type": "character",
        "name": "白砚",
        "summary": "初版摘要",
        "status": "canonical",
    }
    payload.update(overrides)
    return await _create_entity(db_session, novel_id, **payload)


async def test_update_aborts_when_snapshot_fails(
    db_session, project_novel_id: str
) -> None:
    entity = await _make_entity(db_session, project_novel_id)
    service = WorldEntityService()

    with patch.object(
        EntityRevisionService,
        "create_snapshot",
        autospec=True,
        side_effect=RuntimeError("snapshot backend down"),
    ):
        with pytest.raises(RuntimeError):
            await service.update(
                db_session,
                str(entity.id),
                CoreEntityUpdate(summary="第二版摘要"),
                novel_id=project_novel_id,
            )

    await db_session.refresh(entity)
    assert entity.summary == "初版摘要"


async def test_promote_aborts_when_snapshot_fails(
    db_session, project_novel_id: str
) -> None:
    entity = await _make_entity(db_session, project_novel_id, status="draft")
    service = WorldEntityService()

    with patch.object(
        EntityRevisionService,
        "create_snapshot",
        autospec=True,
        side_effect=RuntimeError("snapshot backend down"),
    ):
        with pytest.raises(RuntimeError):
            await service.promote(
                db_session,
                str(entity.id),
                EntityPromoteRequest(summary="采用前微调"),
                novel_id=project_novel_id,
            )

    await db_session.refresh(entity)
    assert entity.status == "draft"


async def test_delete_still_succeeds_when_snapshot_fails(
    db_session, project_novel_id: str
) -> None:
    entity = await _make_entity(db_session, project_novel_id)
    service = WorldEntityService()

    with patch.object(
        EntityRevisionService,
        "create_snapshot",
        autospec=True,
        side_effect=RuntimeError("snapshot backend down"),
    ):
        await service.delete(db_session, str(entity.id), novel_id=project_novel_id)

    await db_session.refresh(entity)
    assert entity.status == "deprecated"
