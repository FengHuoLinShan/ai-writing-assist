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
from modules.world.schemas import WorldProfileUpsertRequest
from modules.world.schemas.dossier import (
    DossierEntryCreate,
    DossierEntryUpdate,
    DossierFacingRef,
)
from modules.world.services.worldbuilding.profile_service import WorldProfileService
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


async def test_strong_profile_dossier_bridge_roundtrips_on_postgres():
    engine = create_async_engine(require_e2e_database_url(), pool_size=2, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_id, novel_id = uuid4(), uuid4()
    cases = [
        ("species", "origin_summary", "history", "雾海迁徙", "远古林地"),
        (
            "faction",
            "resources_json",
            "resources",
            [{"name": "盐铁", "amount": 3}],
            [{"name": "盐铁", "amount": 4}],
        ),
        ("location", "climate", "sensory_details", "潮湿冷风", "乾燥暖风"),
        ("rule", "rule_domain", "known_scope", "北境", "全境"),
        (
            "item",
            "powers_json",
            "abilities_limits",
            [{"label": "照明"}],
            [{"label": "护身"}],
        ),
        ("secret", "truth_summary", "truth", "盟主在世", "盟主已死"),
    ]
    profile_service = WorldProfileService()
    dossier_service = WorldObjectDossierService()
    token = bind_principal(
        AccountPrincipal(
            account_id=owner_id,
            status="active",
            identity_type="email",
            support_code=owner_id.hex,
        )
    )
    try:
        async with sessions.begin() as db:
            db.add(Account(id=owner_id, status="active", support_code=owner_id.hex))
            db.add(Project(id=novel_id, owner_id=owner_id, title="强档案桥接 PG"))
            await db.flush()
            for entity_type, _field, _facing, _value, _updated in cases:
                db.add(
                    CoreEntity(
                        novel_id=novel_id,
                        entity_type=entity_type,
                        name=f"PG {entity_type}",
                        status="canonical",
                    )
                )
            await db.flush()
            entities = {
                row.entity_type: row
                for row in (
                    await db.scalars(
                        select(CoreEntity).where(CoreEntity.novel_id == novel_id)
                    )
                ).all()
            }
            for entity_type, field, facing, value, updated_value in cases:
                entity = entities[entity_type]
                await profile_service.upsert_profile(
                    db,
                    str(novel_id),
                    str(entity.id),
                    WorldProfileUpsertRequest.model_validate(
                        {"status": "canonical", field: value}
                    ),
                )
                view = await dossier_service.read(db, str(novel_id), str(entity.id))
                row = next(
                    item
                    for item in view.entries
                    if item.legacy_field_key == f"{entity_type}_profiles.{field}"
                )
                assert row.facing.key == facing
                assert row.legacy_value == (value if field.endswith("_json") else None)

                update = (
                    DossierEntryUpdate(
                        expected_revision_id=row.id,
                        legacy_value=updated_value,
                    )
                    if field.endswith("_json")
                    else DossierEntryUpdate(
                        expected_revision_id=row.id,
                        content=updated_value,
                    )
                )
                await dossier_service.update_entry(
                    db,
                    str(novel_id),
                    str(entity.id),
                    str(row.id),
                    update,
                )
                profile = await profile_service.get_profile(
                    db, str(novel_id), str(entity.id)
                )
                assert profile.fields[field] == updated_value
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
            await db.execute(delete(Account).where(Account.id == owner_id))
        reset_principal(token)
        await engine.dispose()


async def test_role_dossier_validates_storage_limit_before_changing_current_revision():
    from modules.world.models import Character

    engine = create_async_engine(require_e2e_database_url(), pool_size=2)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_id, novel_id, entity_id = (uuid4() for _ in range(3))
    token = bind_principal(
        AccountPrincipal(
            account_id=owner_id,
            status="active",
            identity_type="email",
            support_code=owner_id.hex,
        )
    )
    service = WorldObjectDossierService()
    try:
        async with sessions.begin() as db:
            db.add(Account(id=owner_id, status="active", support_code=owner_id.hex))
            db.add(Project(id=novel_id, owner_id=owner_id, title="角色长度回归"))
            db.add(
                CoreEntity(
                    id=entity_id,
                    novel_id=novel_id,
                    entity_type="character",
                    name="合成人物",
                    status="canonical",
                )
            )
            await db.flush()
            db.add(
                Character(
                    entity_id=entity_id, novel_id=novel_id, name="合成人物", role="旧定位"
                )
            )
        async with sessions.begin() as db:
            first = await service.create_entry(
                db,
                str(novel_id),
                str(entity_id),
                DossierEntryCreate(
                    facing=DossierFacingRef(kind="core", key="identity_position"),
                    legacy_field_key="role",
                    content="甲" * 64,
                ),
            )
            current = await service.update_entry(
                db,
                str(novel_id),
                str(entity_id),
                str(first.id),
                DossierEntryUpdate(expected_revision_id=first.id, content="乙" * 64),
            )
            with pytest.raises(ValidationError) as raised:
                await service.update_entry(
                    db,
                    str(novel_id),
                    str(entity_id),
                    str(current.id),
                    DossierEntryUpdate(
                        expected_revision_id=current.id, content="丙" * 65
                    ),
                )
            assert raised.value.code == "dossier_role_too_long"
            assert (await db.get(Character, entity_id)).role == "乙" * 64
            view = await service.read(db, str(novel_id), str(entity_id))
            assert [(row.id, row.content) for row in view.entries] == [
                (current.id, "乙" * 64)
            ]
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
            await db.execute(delete(Account).where(Account.id == owner_id))
        reset_principal(token)
        await engine.dispose()
