"""Generic profile compatibility writes and dossier revisions on PostgreSQL."""

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from core.database import get_manager
from core.errors import ConflictError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID, AccountPrincipal
from modules.account.models import Account
from modules.project.models import Project
from modules.world.models import CoreEntity, WorldObjectDossierEntry
from modules.world.schemas.workspace import WorldProfileUpsertRequest
from modules.world.services.worldbuilding.profile_service import WorldProfileService
from tests.e2e.config import require_e2e_database_url
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_generic_http_round_trip_cas_and_null_clear():
    manager = get_manager()
    novel_id, entity_id = uuid4(), uuid4()
    async with manager.session_factory() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code=uuid4().hex))
        db.add(Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="C2 generic"))
        db.add(
            CoreEntity(
                id=entity_id,
                novel_id=novel_id,
                entity_type="spirit_beast",
                name="合成山灵",
                status="canonical",
            )
        )
        await db.commit()

    profile_url = f"/api/world/profiles/{entity_id}"
    dossier_url = f"/api/world/entities/{entity_id}/dossier"
    params = {"novel_id": str(novel_id)}
    async with XhrAsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        term = await client.post(
            f"/api/world/project-vocabulary/{novel_id}/terms",
            json={"kind": "dossier_facing", "name": "源地"},
        )
        assert term.status_code == 201, term.text
        template = await client.put(
            "/api/world/dossier-templates/spirit_beast",
            params=params,
            json={
                "fields": [
                    {
                        "key": "origin_place",
                        "facing": {"kind": "project", "term_id": term.json()["id"]},
                        "label": "来源地点",
                    }
                ]
            },
        )
        assert template.status_code == 200, template.text
        first = await client.put(
            profile_url,
            params=params,
            json={
                "status": "canonical",
                "data_json": {
                    "origin_place": "旧根洞",
                    "unknown_json": {"kept": [1, 2]},
                },
            },
        )
        assert first.status_code == 200, first.text
        initial_revision = first.json()["expected_dossier_revision"]
        dossier = await client.get(dossier_url, params=params)
        assert dossier.status_code == 200, dossier.text
        mapped = [
            row
            for row in dossier.json()["entries"]
            if str(row.get("legacy_field_key") or "").startswith("generic_profile:")
        ]
        assert len(mapped) == 1, dossier.json()["entries"]
        entry = mapped[0]
        edited = await client.patch(
            f"{dossier_url}/entries/{entry['id']}",
            params=params,
            json={"expected_revision_id": entry["id"], "content": "新石窟"},
        )
        assert edited.status_code == 200, edited.text
        read_back = await client.get(profile_url, params=params)
        assert read_back.status_code == 200, read_back.text
        assert read_back.json()["data_json"] == {
            "origin_place": "新石窟",
            "unknown_json": {"kept": [1, 2]},
        }
        stale = await client.put(
            profile_url,
            params=params,
            json={
                "expected_dossier_revision": initial_revision,
                "data_json": {"origin_place": "旧根洞"},
            },
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["error"] == "world_profile_revision_stale"
        latest = await client.get(profile_url, params=params)
        assert latest.json()["data_json"] == read_back.json()["data_json"]
        cleared = await client.put(
            profile_url,
            params=params,
            json={
                "expected_dossier_revision": latest.json()["expected_dossier_revision"],
                "data_json": None,
            },
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["data_json"] == {}
        after = await client.get(dossier_url, params=params)
        assert after.status_code == 200, after.text
        assert not any(
            str(row.get("legacy_field_key") or "").startswith("generic_profile:")
            for row in after.json()["entries"]
        )
    async with manager.session_factory() as db:
        rows = (
            await db.scalars(
                select(WorldObjectDossierEntry).where(
                    WorldObjectDossierEntry.novel_id == novel_id,
                    WorldObjectDossierEntry.entity_id == entity_id,
                )
            )
        ).all()
    assert rows and all(row.status != "active" for row in rows)


async def test_generic_profile_two_sessions_cas_and_legacy_row_lock():
    engine = create_async_engine(require_e2e_database_url(), pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_id, novel_id, entity_id = uuid4(), uuid4(), uuid4()
    principal = AccountPrincipal(
        account_id=owner_id,
        status="active",
        identity_type="email",
        support_code=f"c2-{owner_id.hex[:12]}",
    )
    token = bind_principal(principal)
    service = WorldProfileService()
    try:
        async with sessions.begin() as db:
            db.add(
                Account(
                    id=owner_id,
                    status="active",
                    support_code=principal.support_code,
                )
            )
            db.add(Project(id=novel_id, owner_id=owner_id, title="C2 CAS"))
            db.add(
                CoreEntity(
                    id=entity_id,
                    novel_id=novel_id,
                    entity_type="spirit_beast",
                    name="并发对象",
                    status="canonical",
                )
            )
        async with sessions.begin() as db:
            initial = await service.upsert_profile(
                db,
                str(novel_id),
                str(entity_id),
                WorldProfileUpsertRequest(data_json={"origin_place": "初值"}),
            )
        baseline = initial.expected_dossier_revision
        assert baseline

        gate = asyncio.Event()

        async def write(value, *, expected):
            await gate.wait()
            try:
                async with sessions.begin() as db:
                    return await service.upsert_profile(
                        db,
                        str(novel_id),
                        str(entity_id),
                        WorldProfileUpsertRequest(
                            expected_dossier_revision=expected,
                            data_json={"origin_place": value},
                        ),
                    )
            except ConflictError as error:
                return error

        competing = [
            asyncio.create_task(write(value, expected=baseline)) for value in ("甲", "乙")
        ]
        gate.set()
        outcomes = await asyncio.wait_for(asyncio.gather(*competing), timeout=10)
        assert sum(not isinstance(item, ConflictError) for item in outcomes) == 1
        assert sum(isinstance(item, ConflictError) for item in outcomes) == 1
        winner = next(item for item in outcomes if not isinstance(item, ConflictError))
        async with sessions.begin() as db:
            current = await service.get_profile(db, str(novel_id), str(entity_id))
            rows = (
                await db.scalars(
                    select(WorldObjectDossierEntry).where(
                        WorldObjectDossierEntry.novel_id == novel_id,
                        WorldObjectDossierEntry.entity_id == entity_id,
                    )
                )
            ).all()
        assert current.data_json == winner.data_json
        assert len(rows) == 2
        assert sum(row.status == "active" for row in rows) == 1

        gate = asyncio.Event()
        legacy = [
            asyncio.create_task(write(value, expected=None))
            for value in ("旧客户端甲", "旧客户端乙")
        ]
        gate.set()
        legacy_outcomes = await asyncio.wait_for(asyncio.gather(*legacy), timeout=10)
        assert all(not isinstance(item, ConflictError) for item in legacy_outcomes)
        async with sessions.begin() as db:
            latest = await service.get_profile(db, str(novel_id), str(entity_id))
            rows = (
                await db.scalars(
                    select(WorldObjectDossierEntry).where(
                        WorldObjectDossierEntry.novel_id == novel_id,
                        WorldObjectDossierEntry.entity_id == entity_id,
                    )
                )
            ).all()
        assert latest.data_json["origin_place"] in {"旧客户端甲", "旧客户端乙"}
        assert len(rows) == 4
        assert sum(row.status == "active" for row in rows) == 1
    finally:
        reset_principal(token)
        await engine.dispose()
