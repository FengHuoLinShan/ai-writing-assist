"""Real PostgreSQL CAS and rollback for revisioned World dossiers."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.project.models import Project
from modules.world.dossier_service import WorldObjectDossierService
from modules.world.models import CoreEntity, WorldObjectDossierEntry
from modules.world.schemas.dossier import (
    DossierEntryCreate,
    DossierEntryUpdate,
    DossierFacingRef,
)
from tests.e2e.config import require_e2e_database_url

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_dossier_competing_edit_and_failed_write_preserve_current_revision():
    engine = create_async_engine(require_e2e_database_url(), pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_id, novel_id, other_novel_id, entity_id = (uuid4() for _ in range(4))
    principal = AccountPrincipal(
        account_id=owner_id,
        status="active",
        identity_type="email",
        support_code=f"dossier-{owner_id.hex[:12]}",
    )
    token = bind_principal(principal)
    service = WorldObjectDossierService()
    try:
        async with sessions.begin() as db:
            db.add(
                Account(
                    id=owner_id,
                    status="active",
                    support_code=principal.support_code,
                )
            )
            db.add_all(
                [
                    Project(id=novel, owner_id=owner_id, title="合成档案并发")
                    for novel in (novel_id, other_novel_id)
                ]
            )
            db.add(
                CoreEntity(
                    id=entity_id,
                    novel_id=novel_id,
                    entity_type="location",
                    name="合成地点",
                    status="canonical",
                )
            )
        async with sessions.begin() as db:
            created = await service.create_entry(
                db,
                str(novel_id),
                str(entity_id),
                DossierEntryCreate(
                    facing=DossierFacingRef(kind="core", key="history"),
                    content="初始内容",
                ),
            )
            with pytest.raises(NotFoundError):
                await service.read(db, str(other_novel_id), str(entity_id))

        gate = asyncio.Event()

        async def edit(content):
            await gate.wait()
            try:
                async with sessions.begin() as db:
                    return await service.update_entry(
                        db,
                        str(novel_id),
                        str(entity_id),
                        str(created.id),
                        DossierEntryUpdate(
                            expected_revision_id=created.id, content=content
                        ),
                    )
            except ConflictError as error:
                return error

        edits = [asyncio.create_task(edit(value)) for value in ("甲修订", "乙修订")]
        gate.set()
        outcomes = await asyncio.wait_for(asyncio.gather(*edits), timeout=10)
        assert sum(not isinstance(value, ConflictError) for value in outcomes) == 1
        winner = next(value for value in outcomes if not isinstance(value, ConflictError))

        with pytest.raises(ValidationError):
            async with sessions.begin() as db:
                await service.update_entry(
                    db,
                    str(novel_id),
                    str(entity_id),
                    str(winner.id),
                    DossierEntryUpdate(expected_revision_id=winner.id, content="应回滚"),
                    source="invalid_source",
                )
        async with sessions.begin() as db:
            rows = list(
                (
                    await db.scalars(
                        select(WorldObjectDossierEntry).where(
                            WorldObjectDossierEntry.novel_id == novel_id,
                            WorldObjectDossierEntry.entity_id == entity_id,
                        )
                    )
                ).all()
            )
            assert len(rows) == 2
            assert [(row.id, row.status) for row in rows if row.status == "active"] == [
                (winner.id, "active")
            ]
    finally:
        async with sessions.begin() as db:
            await db.execute(
                delete(Project).where(Project.id.in_([novel_id, other_novel_id]))
            )
            await db.execute(delete(Account).where(Account.id == owner_id))
        reset_principal(token)
        await engine.dispose()
