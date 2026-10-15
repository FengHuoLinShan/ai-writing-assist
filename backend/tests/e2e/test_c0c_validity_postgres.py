"""Real PostgreSQL owner, CAS, and HTTP trace checks for C0c settings."""

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.main import app
from core.errors import ConflictError
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.account.models import Account
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.operation_trace_models import AssistantOperationTrace
from modules.assistant.operations import catalog
from modules.assistant.schemas import WorkContext
from modules.project.models import Project
from modules.project.object_dossier_settings import (
    ObjectDossierSettingsUpdate,
    update_object_dossier_settings,
)
from modules.story.continuity.models import MemoryEvent
from modules.story.outline_state.models import Scene
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.notice_sources import list_object_validity_notices
from tests.e2e.config import require_e2e_database_url
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_settings_http_enforces_owner_and_two_session_cas_with_trace():
    engine = create_async_engine(require_e2e_database_url())
    novel_id, foreign_id, other_owner = uuid4(), uuid4(), uuid4()
    try:
        async with AsyncSession(engine) as db:
            if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
                db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="c0c-validity"))
            db.add(Account(id=other_owner, support_code=f"c0c-{other_owner.hex[:12]}"))
            db.add_all(
                [
                    Project(
                        id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="有效期审查"
                    ),
                    Project(id=foreign_id, owner_id=other_owner, title="不可访问项目"),
                ]
            )
            await db.commit()

        async with XhrAsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            path = f"/api/projects/{novel_id}/object-dossier-settings"
            initial = await client.get(path)
            assert initial.status_code == 200, initial.text
            assert initial.json() == {"version": 0, "allow_story_override": False}

            changed = await client.put(
                path, json={"expected_version": 0, "allow_story_override": True}
            )
            assert changed.status_code == 200, changed.text
            assert changed.json() == {"version": 1, "allow_story_override": True}

            stale = await client.put(
                path, json={"expected_version": 0, "allow_story_override": False}
            )
            assert stale.status_code == 409, stale.text
            assert (await client.get(path)).json() == changed.json()

            foreign_path = f"/api/projects/{foreign_id}/object-dossier-settings"
            assert (await client.get(foreign_path)).status_code == 404
            assert (
                await client.put(
                    foreign_path,
                    json={"expected_version": 0, "allow_story_override": True},
                )
            ).status_code == 404
            relations = await client.get(f"/api/world/relations?novel_id={novel_id}")
            assert relations.status_code == 200, relations.text
            assert relations.json()["items"] == []
            assert (
                await client.get(f"/api/world/relations?novel_id={foreign_id}")
            ).status_code == 404

        async with AsyncSession(engine) as verify:
            trace = list(
                (
                    await verify.scalars(
                        select(AssistantOperationTrace).where(
                            AssistantOperationTrace.novel_id == novel_id,
                            AssistantOperationTrace.op_id
                            == "project.object_validity_settings.edit",
                        )
                    )
                ).all()
            )
            assert any(item.event_type == "executed" for item in trace)
            assert not any(item.novel_id == foreign_id for item in trace)
            project = await verify.get(Project, foreign_id)
            assert "world_object_dossier_v1" not in (project.settings or {})
    finally:
        await engine.dispose()


async def test_settings_cas_serializes_two_independent_postgres_sessions():
    engine = create_async_engine(require_e2e_database_url(), pool_size=2)
    novel_id = uuid4()
    try:
        async with AsyncSession(engine) as db:
            if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
                db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="c0c-cas"))
            db.add(Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="并发设置"))
            await db.commit()

        async def update(enabled: bool):
            async with AsyncSession(engine) as db:
                try:
                    result = await update_object_dossier_settings(
                        db,
                        str(novel_id),
                        ObjectDossierSettingsUpdate(
                            expected_version=0, allow_story_override=enabled
                        ),
                    )
                    await db.commit()
                    return result
                except ConflictError as exc:
                    await db.rollback()
                    return exc

        outcomes = await asyncio.gather(update(True), update(False))
        assert sum(isinstance(item, ConflictError) for item in outcomes) == 1
        async with AsyncSession(engine) as verify:
            project = await verify.get(Project, novel_id)
            assert project.settings["world_object_dossier_v1"]["version"] == 1
    finally:
        await engine.dispose()


async def test_confirmed_map_state_http_revalidates_current_world_revision():
    engine = create_async_engine(require_e2e_database_url())
    novel_id, foreign_id, foreign_owner = uuid4(), uuid4(), uuid4()
    scene_id, later_scene_id, node_id, revision_id, next_revision_id = (
        uuid4() for _ in range(5)
    )
    document = {
        "schema_version": 2,
        "spaces": [{"id": "main", "label": "主空间"}],
        "features": [
            {
                "id": "feature:harbor",
                "kind": "location",
                "label": "北港",
                "effective": {"start": {"kind": "scene", "id": str(scene_id)}},
            }
        ],
    }
    try:
        async with AsyncSession(engine) as db:
            if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
                db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="c0c-map-state"))
            db.add(
                Account(id=foreign_owner, support_code=f"c0c-{foreign_owner.hex[:12]}")
            )
            db.add_all(
                [
                    Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="地图状态"),
                    Project(id=foreign_id, owner_id=foreign_owner, title="异主项目"),
                    Scene(id=scene_id, novel_id=novel_id, scene_index=0),
                    Scene(id=later_scene_id, novel_id=novel_id, scene_index=1),
                    MapAtlasNode(
                        id=node_id,
                        novel_id=novel_id,
                        semantic_key=f"harbor-{node_id.hex}",
                        title="北港",
                        level="city",
                        status="adopted",
                        current_revision_id=revision_id,
                    ),
                    MapAtlasRevision(
                        id=revision_id,
                        novel_id=novel_id,
                        node_id=node_id,
                        status="saved",
                        document=document,
                        geometry_hash="a" * 64,
                    ),
                ]
            )
            await db.commit()

        path = f"/api/novels/{novel_id}/memories/map-declaration-state"
        payload = {
            "scene_id": str(scene_id),
            "node_id": str(node_id),
            "revision_id": str(revision_id),
            "declaration_kind": "feature",
            "declaration_id": "feature:harbor",
            "status": "inactive",
            "idempotency_key": f"map-{uuid4()}",
            "confirmed": True,
        }
        async with AsyncSession(engine) as db:
            operation = catalog()["story.map_declaration_state.confirm"]
            args = operation.schema.model_validate(payload)
            preview = await operation.prepare(
                db,
                str(novel_id),
                args,
                context=AssistantOperationContext(
                    str(uuid4()),
                    str(BOOTSTRAP_ACCOUNT_ID),
                    WorkContext(page="map", scope="project"),
                ),
            )
            assert preview["revision_id"] == str(revision_id)
            assert not (
                await db.scalars(
                    select(MemoryEvent).where(MemoryEvent.novel_id == novel_id)
                )
            ).all()
            await db.rollback()
        async with XhrAsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (
                await client.post(path, json={**payload, "confirmed": False})
            ).status_code == 422
            assert (
                await client.post(
                    f"/api/novels/{foreign_id}/memories/map-declaration-state",
                    json=payload,
                )
            ).status_code == 404
            saved = await client.post(path, json=payload)
            assert saved.status_code == 200, saved.text
            assert saved.json()["map_declaration"]["declaration_id"] == "feature:harbor"
            repeat = await client.post(path, json=payload)
            assert repeat.status_code == 200, repeat.text

            ensure = await client.post(
                f"/api/novels/{novel_id}/memories/scene-checkpoints/ensure",
                json={"scene_id": str(later_scene_id)},
            )
            assert ensure.status_code == 200, ensure.text

            async with AsyncSession(engine) as db:
                notices = await list_object_validity_notices(
                    db, str(novel_id), {"scene_id": str(later_scene_id)}
                )
                relevant = [
                    item
                    for item in notices
                    if item["target"].get("node_id") == str(node_id)
                ]
                assert len(relevant) == 1
                assert relevant[0]["validity_decision"] == "author_priority"
                author_priority_fingerprint = relevant[0]["basis_fingerprint"]
                await db.rollback()

            setting_path = f"/api/projects/{novel_id}/object-dossier-settings"
            changed = await client.put(
                setting_path,
                json={"expected_version": 0, "allow_story_override": True},
            )
            assert changed.status_code == 200, changed.text
            async with AsyncSession(engine) as db:
                notices = await list_object_validity_notices(
                    db, str(novel_id), {"scene_id": str(later_scene_id)}
                )
                relevant = [
                    item
                    for item in notices
                    if item["target"].get("node_id") == str(node_id)
                ]
                assert len(relevant) == 1
                assert relevant[0]["validity_decision"] == "story_override"
                assert relevant[0]["basis_fingerprint"] != author_priority_fingerprint
                await db.rollback()

            async with AsyncSession(engine) as db:
                node = await db.get(MapAtlasNode, node_id)
                node.current_revision_id = next_revision_id
                db.add(
                    MapAtlasRevision(
                        id=next_revision_id,
                        novel_id=novel_id,
                        node_id=node_id,
                        status="saved",
                        document=document,
                        geometry_hash="b" * 64,
                    )
                )
                await db.commit()
            stale = await client.post(
                path, json={**payload, "idempotency_key": f"map-{uuid4()}"}
            )
            assert stale.status_code == 409, stale.text

        async with AsyncSession(engine) as verify:
            rows = list(
                (
                    await verify.scalars(
                        select(MemoryEvent).where(MemoryEvent.novel_id == novel_id)
                    )
                ).all()
            )
            assert len(rows) == 1
            assert rows[0].snapshot_after["effective_status"] == "inactive"
            assert rows[0].snapshot_after["meta"]["map_declaration_state"][
                "revision_id"
            ] == str(revision_id)
            trace = list(
                (
                    await verify.scalars(
                        select(AssistantOperationTrace).where(
                            AssistantOperationTrace.novel_id == novel_id,
                            AssistantOperationTrace.op_id
                            == "story.map_declaration_state.confirm",
                        )
                    )
                ).all()
            )
            assert any(item.event_type == "executed" for item in trace)
            assert not (
                await verify.scalars(
                    select(AssistantOperationTrace).where(
                        AssistantOperationTrace.novel_id == foreign_id
                    )
                )
            ).all()
    finally:
        await engine.dispose()
