from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from modules.outline.facade import create_scene
from modules.project.models import Project
from modules.world.contracts import (
    MapCharacterLocationProposal,
    MapObservationCandidateAuthorization,
    MapObservationCandidateInput,
)
from modules.world.facade import create_map_observation_candidates
from modules.world.map_models import MapFact, MapObservation
from modules.world.map_schemas import (
    MapConfigCreate,
    MapObservationCreate,
    MapObservationRevisionRequest,
)
from modules.world.services.map.map_config_service import MapConfigService
from modules.world.services.map_service import MapDynamicFactService
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_competing_first_candidate_inserts_reuse_one_observation() -> None:
    """A missing-row-safe identity lock serializes deterministic first inserts."""

    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    workflow_id = f"workflow-{uuid.uuid4()}"

    try:
        async with sessions.begin() as setup_db:
            setup_db.add(Project(id=novel_id, title="candidate insert concurrency"))
            await setup_db.flush()
            scene = await create_scene(
                setup_db,
                str(novel_id),
                {"scene_index": 1, "title": "抵达青石镇", "status": "canonical"},
            )

        candidate = MapObservationCandidateInput(
            workflow_id=workflow_id,
            task_id="task-concurrent-candidate",
            source_item_key="map-proposal:v1:character_location:stable:0",
            scene_id=scene["id"],
            scene_index=1,
            source_chapter_index=1,
            scene_source_fingerprint="a" * 64,
            context_snapshot_id="snapshot-concurrent-candidate",
            evidence_text="沈砚抵达青石镇。",
            evidence_anchor="b" * 64,
            confidence=0.91,
            target_name="沈砚",
            proposal=MapCharacterLocationProposal(
                proposal_type="character_location",
                location_name="青石镇",
            ),
            authorization=MapObservationCandidateAuthorization(
                adoption_policy="user_authorized_pipeline",
                authorization_confirmed=True,
                authorized_at=datetime(2026, 7, 15, tzinfo=UTC),
                scope={
                    "novel_id": str(novel_id),
                    "start_chapter": 1,
                    "end_chapter": 1,
                    "stage": None,
                },
                snapshot_fingerprint="c" * 64,
            ),
        )

        async def create_once():
            async with sessions.begin() as db:
                return await create_map_observation_candidates(
                    db,
                    str(novel_id),
                    candidates=[candidate],
                )

        first, second = await asyncio.gather(create_once(), create_once())

        assert first.created_count + second.created_count == 1
        assert first.reused_count + second.reused_count == 1
        assert first.items[0].observation_id == second.items[0].observation_id
        async with sessions() as verify_db:
            count = await verify_db.scalar(
                select(func.count(MapObservation.id)).where(
                    MapObservation.novel_id == novel_id
                )
            )
            assert count == 1
    finally:
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()


async def test_competing_confirm_and_ignore_have_one_terminal_result() -> None:
    """A confirm row lock makes a concurrent stale ignore lose deterministically."""

    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    first_confirmed = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    first_task: asyncio.Task[str] | None = None
    second_task: asyncio.Task[ConflictError] | None = None

    async def confirm_first() -> str:
        async with sessions() as db:
            await db.begin()
            fact = await MapDynamicFactService().confirm_observation(
                db,
                str(novel_id),
                map_id=map_id,
                observation_id=observation_id,
                data=MapObservationRevisionRequest(
                    expected_updated_at=expected_updated_at,
                ),
            )
            first_confirmed.set()
            await release_first.wait()
            await db.commit()
            return fact.id

    async def ignore_second() -> ConflictError:
        await first_confirmed.wait()
        try:
            async with sessions.begin() as db:
                second_started.set()
                await MapDynamicFactService().ignore_observation(
                    db,
                    str(novel_id),
                    map_id=map_id,
                    observation_id=observation_id,
                    data=MapObservationRevisionRequest(
                        expected_updated_at=expected_updated_at,
                    ),
                )
        except ConflictError as exc:
            return exc
        raise AssertionError("the stale ignore unexpectedly succeeded")

    try:
        async with sessions.begin() as setup_db:
            setup_db.add(Project(id=novel_id, title="map observation concurrency"))
            config = await MapConfigService().create(
                setup_db,
                str(novel_id),
                MapConfigCreate(
                    name="concurrent observation map",
                    map_type="world",
                    grid_width=2,
                    grid_height=2,
                    template="blank",
                ),
            )
            observation = await MapDynamicFactService().create_observation(
                setup_db,
                str(novel_id),
                map_id=config.id,
                data=MapObservationCreate(
                    target_name="initial alert",
                    dynamic_type="status",
                    time_anchor={"kind": "initial_state"},
                    value_json={
                        "schema_version": 1,
                        "type": "status",
                        "field_key": "alert",
                        "value": "high",
                    },
                    source_ref={"source": "manual_e2e"},
                ),
            )
            map_id = config.id
            observation_id = observation.id
            assert observation.updated_at is not None
            expected_updated_at = observation.updated_at

        first_task = asyncio.create_task(confirm_first())
        await asyncio.wait_for(first_confirmed.wait(), timeout=2.0)
        second_task = asyncio.create_task(ignore_second())
        await asyncio.wait_for(second_started.wait(), timeout=2.0)

        done, _pending = await asyncio.wait({second_task}, timeout=0.1)
        assert not done, "the stale ignore must wait for the confirm transaction"

        release_first.set()
        fact_id, conflict = await asyncio.gather(first_task, second_task)
        assert conflict.code == "map_observation_revision_conflict"
        assert conflict.status_code == 409
        assert conflict.context is not None
        assert conflict.context["latest"]["review_state"] == "confirmed"

        async with sessions() as verify_db:
            stored_observation = await verify_db.scalar(
                select(MapObservation).where(
                    MapObservation.id == uuid.UUID(observation_id)
                )
            )
            fact_count = await verify_db.scalar(
                select(func.count(MapFact.id)).where(
                    MapFact.observation_id == uuid.UUID(observation_id)
                )
            )
            assert stored_observation is not None
            assert stored_observation.review_state == "confirmed"
            assert fact_count == 1
            assert await verify_db.get(MapFact, uuid.UUID(fact_id)) is not None
    finally:
        release_first.set()
        pending = [
            task
            for task in (first_task, second_task)
            if task is not None and not task.done()
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()


async def test_competing_confirms_reuse_one_fact() -> None:
    """The second confirmer waits for the row lock and reuses the first Fact."""

    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    first_confirmed = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    first_task: asyncio.Task[str] | None = None
    second_task: asyncio.Task[str] | None = None

    async def confirm_first() -> str:
        async with sessions() as db:
            await db.begin()
            fact = await MapDynamicFactService().confirm_observation(
                db,
                str(novel_id),
                map_id=map_id,
                observation_id=observation_id,
                data=MapObservationRevisionRequest(
                    expected_updated_at=expected_updated_at,
                ),
            )
            first_confirmed.set()
            await release_first.wait()
            await db.commit()
            return fact.id

    async def confirm_second() -> str:
        await first_confirmed.wait()
        async with sessions.begin() as db:
            second_started.set()
            fact = await MapDynamicFactService().confirm_observation(
                db,
                str(novel_id),
                map_id=map_id,
                observation_id=observation_id,
                data=MapObservationRevisionRequest(
                    expected_updated_at=expected_updated_at,
                ),
            )
            return fact.id

    try:
        async with sessions.begin() as setup_db:
            setup_db.add(Project(id=novel_id, title="double map confirmation"))
            config = await MapConfigService().create(
                setup_db,
                str(novel_id),
                MapConfigCreate(
                    name="double confirmation map",
                    map_type="world",
                    grid_width=2,
                    grid_height=2,
                    template="blank",
                ),
            )
            observation = await MapDynamicFactService().create_observation(
                setup_db,
                str(novel_id),
                map_id=config.id,
                data=MapObservationCreate(
                    target_name="initial gate state",
                    dynamic_type="status",
                    time_anchor={"kind": "initial_state"},
                    value_json={
                        "schema_version": 1,
                        "type": "status",
                        "field_key": "gate",
                        "value": "closed",
                    },
                    source_ref={"source": "manual_e2e"},
                ),
            )
            map_id = config.id
            observation_id = observation.id
            assert observation.updated_at is not None
            expected_updated_at = observation.updated_at

        first_task = asyncio.create_task(confirm_first())
        await asyncio.wait_for(first_confirmed.wait(), timeout=2.0)
        second_task = asyncio.create_task(confirm_second())
        await asyncio.wait_for(second_started.wait(), timeout=2.0)

        done, _pending = await asyncio.wait({second_task}, timeout=0.1)
        assert not done, "the second confirm must wait for the first transaction"

        release_first.set()
        first_fact_id, second_fact_id = await asyncio.gather(first_task, second_task)
        assert second_fact_id == first_fact_id

        async with sessions() as verify_db:
            fact_count = await verify_db.scalar(
                select(func.count(MapFact.id)).where(
                    MapFact.observation_id == uuid.UUID(observation_id)
                )
            )
            stored_observation = await verify_db.scalar(
                select(MapObservation).where(
                    MapObservation.id == uuid.UUID(observation_id)
                )
            )
            assert fact_count == 1
            assert stored_observation is not None
            assert stored_observation.review_state == "confirmed"
    finally:
        release_first.set()
        pending = [
            task
            for task in (first_task, second_task)
            if task is not None and not task.done()
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()
