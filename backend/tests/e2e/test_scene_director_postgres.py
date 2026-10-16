"""Real PostgreSQL checks for director history retention and ledger row locking."""

from __future__ import annotations

import asyncio
import json
import os
import traceback
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from infrastructure.llm.workflow_budget import AIRunEnvelope
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.account.models import Account
from modules.project.models import Project
from modules.story.director_budget import budget_stop_reason, preview_director_budget
from modules.story.director_context import read_director_source
from modules.story.director_schemas import DirectorContinueRequest, DirectorStartRequest
from modules.story.director_service import (
    delete_director_branch,
    delete_unstarred_director_branches,
    purge_expired_director_history,
    restore_director_branch,
)
from modules.story.director_tasks import _mirror_run_envelope
from modules.story.models import (
    StorySceneDirectorBranch,
    StorySceneDirectorReference,
    StorySceneDirectorRoot,
    StorySceneDirectorRound,
)
from modules.story.outline_state.models import Scene
from modules.world.models import CoreEntity
from modules.world.models.character import Character
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest.fixture(autouse=True)
def enable_scene_director(monkeypatch):
    from core.config import get_settings

    monkeypatch.setenv("STORY_SCENE_DIRECTOR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
async def director_pg_engine():
    url = os.environ["DATABASE_URL"]
    assert url == os.environ["E2E_DATABASE_URL"]
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _seed_history(db, novel_id, scene_id, *, starred=False):
    root_id, branch_id, round_id = (uuid4() for _ in range(3))
    db.add(
        StorySceneDirectorRoot(
            id=root_id,
            novel_id=novel_id,
            scene_id=scene_id,
            source_hash="a" * 64,
            request_json={},
            llm_execution_snapshot_json={},
            run_envelope_json={},
            status="ready",
        )
    )
    await db.flush()
    db.add(
        StorySceneDirectorBranch(
            id=branch_id,
            novel_id=novel_id,
            root_id=root_id,
            branch_kind="start",
            source_hash="a" * 64,
            request_json={},
            pending_round_json={},
            status="complete",
            starred=starred,
        )
    )
    await db.flush()
    db.add(
        StorySceneDirectorRound(
            id=round_id,
            novel_id=novel_id,
            root_id=root_id,
            branch_id=branch_id,
            round_number=1,
            source_hash="a" * 64,
            input_hash="b" * 64,
            output_hash="c" * 64,
            input_json={},
            output_json={},
            state_json={},
            run_envelope_json={},
        )
    )
    await db.flush()
    return root_id, branch_id, round_id


async def test_expired_branch_purges_round_but_keeps_copied_reference(director_pg_engine):
    from sqlalchemy.ext.asyncio import AsyncSession

    engine = director_pg_engine
    novel_id = uuid4()
    root_id, branch_id, round_id, ref_id = (uuid4() for _ in range(4))
    async with AsyncSession(engine, expire_on_commit=False) as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="director-review"))
        db.add(Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="导演合成测试"))
        await db.flush()
        db.add(
            StorySceneDirectorRoot(
                id=root_id,
                novel_id=novel_id,
                scene_id=uuid4(),
                source_hash="a" * 64,
                request_json={},
                llm_execution_snapshot_json={},
                run_envelope_json={},
                status="ready",
            )
        )
        await db.flush()
        db.add(
            StorySceneDirectorBranch(
                id=branch_id,
                novel_id=novel_id,
                root_id=root_id,
                branch_kind="start",
                source_hash="a" * 64,
                request_json={},
                pending_round_json={},
                status="deleted",
                deleted_at=datetime.now(UTC) - timedelta(days=31),
                restore_until=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        await db.flush()
        db.add(
            StorySceneDirectorRound(
                id=round_id,
                novel_id=novel_id,
                root_id=root_id,
                branch_id=branch_id,
                round_number=1,
                source_hash="a" * 64,
                input_hash="b" * 64,
                output_hash="c" * 64,
                input_json={},
                output_json={},
                state_json={},
                run_envelope_json={},
            )
        )
        await db.flush()
        db.add(
            StorySceneDirectorReference(
                id=ref_id,
                novel_id=novel_id,
                root_id=root_id,
                scene_id=uuid4(),
                source_round_id=round_id,
                source_basis_hash="a" * 64,
                source_deleted=False,
                name="独立副本",
                content_copy_json={"materials": ["synthetic"]},
                material_ids_json=["synthetic"],
                angle_json={},
                annotation="",
            )
        )
        await db.commit()

    async with AsyncSession(engine, expire_on_commit=False) as db:
        await purge_expired_director_history(db, str(novel_id))
        await db.commit()
        assert await db.get(StorySceneDirectorBranch, branch_id) is None
        assert await db.get(StorySceneDirectorRound, round_id) is None
        copy = await db.get(StorySceneDirectorReference, ref_id)
        assert copy is not None
        assert copy.content_copy_json == {"materials": ["synthetic"]}
        assert copy.source_deleted is True


async def test_ledger_mirror_uses_scoped_root_lock_without_self_deadlock(
    director_pg_engine,
):
    from sqlalchemy.ext.asyncio import AsyncSession

    engine = director_pg_engine
    novel_id, root_id = uuid4(), uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="director-review"))
        db.add(Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="导演账本测试"))
        await db.flush()
        db.add(
            StorySceneDirectorRoot(
                id=root_id,
                novel_id=novel_id,
                scene_id=uuid4(),
                source_hash="a" * 64,
                request_json={},
                llm_execution_snapshot_json={},
                run_envelope_json={},
                status="running",
            )
        )
        await db.commit()
        await db.scalar(
            select(StorySceneDirectorRoot)
            .where(StorySceneDirectorRoot.id == root_id)
            .with_for_update()
        )
        await db.commit()
        async with AsyncSession(engine, expire_on_commit=False) as checkpoint:
            task = SimpleNamespace(
                novel_id=novel_id, meta={"director_root_id": str(root_id)}
            )
            await asyncio.wait_for(
                _mirror_run_envelope(checkpoint, task, {"requests_started": 1}),
                timeout=2,
            )
            await checkpoint.commit()
    async with AsyncSession(engine) as verify:
        row = await verify.get(StorySceneDirectorRoot, root_id)
        assert row.run_envelope_json == {"requests_started": 1}
    async with AsyncSession(engine, expire_on_commit=False) as newer:
        task = SimpleNamespace(novel_id=novel_id, meta={"director_root_id": str(root_id)})
        await _mirror_run_envelope(newer, task, {"requests_started": 2})
        await newer.commit()
    async with AsyncSession(engine, expire_on_commit=False) as stale:
        with pytest.raises(ValueError, match="stale director"):
            await asyncio.wait_for(
                _mirror_run_envelope(stale, task, {"requests_started": 1}),
                timeout=2,
            )
        await stale.rollback()
    async with AsyncSession(engine) as verify:
        assert (await verify.get(StorySceneDirectorRoot, root_id)).run_envelope_json == {
            "requests_started": 2
        }


async def test_author_soft_delete_restores_within_30_days_and_preserves_other_history(
    director_pg_engine,
):
    from sqlalchemy.ext.asyncio import AsyncSession

    novel_id, other_novel = uuid4(), uuid4()
    scene_id = uuid4()
    async with AsyncSession(director_pg_engine, expire_on_commit=False) as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="director-review"))
        db.add_all(
            [
                Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="导演清理测试"),
                Project(id=other_novel, owner_id=BOOTSTRAP_ACCOUNT_ID, title="其他作品"),
            ]
        )
        await db.flush()
        _, deleted_id, deleted_round = await _seed_history(db, novel_id, scene_id)
        _, starred_id, starred_round = await _seed_history(
            db, novel_id, scene_id, starred=True
        )
        _, active_id, active_round = await _seed_history(db, novel_id, scene_id)
        _, foreign_id, foreign_round = await _seed_history(db, other_novel, scene_id)
        await db.commit()

        await delete_director_branch(db, str(novel_id), str(deleted_id))
        await db.commit()
        await purge_expired_director_history(db, str(novel_id))
        assert await db.get(StorySceneDirectorRound, deleted_round) is not None
        assert await db.get(StorySceneDirectorBranch, deleted_id) is not None
        assert await db.get(StorySceneDirectorBranch, starred_id) is not None
        assert await db.get(StorySceneDirectorBranch, foreign_id) is not None
        await restore_director_branch(db, str(novel_id), str(deleted_id))
        assert (await db.get(StorySceneDirectorBranch, deleted_id)).deleted_at is None

        result = await delete_unstarred_director_branches(
            db, str(novel_id), str(scene_id)
        )
        assert set(result["deleted_branch_ids"]) == {str(deleted_id), str(active_id)}
        await db.commit()
        assert (await db.get(StorySceneDirectorBranch, starred_id)).deleted_at is None
        assert await db.get(StorySceneDirectorRound, starred_round) is not None
        assert await db.get(StorySceneDirectorRound, active_round) is not None
        assert await db.get(StorySceneDirectorRound, foreign_round) is not None
        await purge_expired_director_history(db, str(novel_id))
        await db.commit()
        assert await db.get(StorySceneDirectorBranch, active_id) is not None


async def test_project_delete_cascades_and_round_direct_mutation_is_rejected(
    director_pg_engine,
):
    from sqlalchemy.ext.asyncio import AsyncSession

    novel_id, scene_id = uuid4(), uuid4()
    async with AsyncSession(director_pg_engine, expire_on_commit=False) as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="director-review"))
        project = Project(
            id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="导演项目删除测试"
        )
        db.add(project)
        await db.flush()
        root_id, branch_id, round_id = await _seed_history(db, novel_id, scene_id)
        await db.commit()

        with pytest.raises(DBAPIError):
            await db.execute(
                text(
                    "UPDATE story_scene_director_rounds "
                    "SET output_hash = :hash WHERE id = :id"
                ),
                {"hash": "d" * 64, "id": round_id},
            )
        await db.rollback()
        with pytest.raises(DBAPIError):
            await db.execute(
                text("DELETE FROM story_scene_director_rounds WHERE id = :id"),
                {"id": round_id},
            )
        await db.rollback()
        round_row = await db.get(StorySceneDirectorRound, round_id)
        round_row.name = "作者标记"
        round_row.starred = True
        await db.commit()
        assert (await db.get(StorySceneDirectorRound, round_id)).name == "作者标记"
        project = await db.get(Project, novel_id)
        await db.delete(project)
        await db.commit()

    async with AsyncSession(director_pg_engine) as verify:
        assert await verify.get(StorySceneDirectorRoot, root_id) is None
        assert await verify.get(StorySceneDirectorBranch, branch_id) is None
        assert await verify.get(StorySceneDirectorRound, round_id) is None


async def test_http_preview_and_start_write_a_scoped_task_without_a_provider(
    director_pg_engine,
):
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.main import app
    from infrastructure.tasks.models import AsyncTask
    from modules.assistant.operation_trace_http_adapter import (
        install_operation_trace_route_adapters,
    )
    from modules.story.director_budget import preview_director_budget
    from modules.story.director_schemas import DirectorBudgetPreviewRequest

    novel_id, scene_id, actor_id = uuid4(), uuid4(), uuid4()
    async with AsyncSession(director_pg_engine) as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="director-http"))
        db.add(Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="导演 HTTP"))
        await db.commit()
    source = {
        "novel_id": str(novel_id),
        "scene_id": str(scene_id),
        "source_hash": "a" * 64,
        "scene_context": {},
        "author_brief": {"omissions": []},
        "role_briefs": {
            str(actor_id): {
                "brief": {
                    "world_items": [],
                    "continuity_items": [],
                    "pattern_items": [],
                },
                "style_anchors": [],
                "known_participant_ids": [],
            }
        },
    }
    request = {
        "operation_id": str(uuid4()),
        "novel_id": str(novel_id),
        "scene_id": str(scene_id),
        "character_ids": [str(actor_id)],
        "rounds": 1,
    }
    preview_hash = preview_director_budget(
        DirectorBudgetPreviewRequest.model_validate(request), source
    )["preview_hash"]
    confirmation = SimpleNamespace(
        compile_options={
            "scene_id": str(scene_id),
            "character_ids": [str(actor_id)],
            "entity_ids": [],
        }
    )
    install_operation_trace_route_adapters(app)
    with (
        patch(
            "modules.story.director_api.read_director_source",
            autospec=True,
            return_value=source,
        ),
        patch(
            "modules.story.director_api.require_fresh_confirmation",
            autospec=True,
            return_value=confirmation,
        ),
        patch(
            "modules.story.director_api.build_project_llm_execution_snapshot",
            autospec=True,
            return_value={"novel_id": str(novel_id)},
        ),
        patch("modules.story.director_api.attach_result_ref", autospec=True),
    ):
        async with XhrAsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            preview = await client.post(
                "/api/story/scenes/director/budget-preview", json=request
            )
            assert preview.status_code == 200, preview.text
            assert preview.json()["preview_hash"] == preview_hash
            start = await client.post(
                f"/api/story/scenes/{scene_id}/director",
                json={
                    **request,
                    "operation_id": str(uuid4()),
                    "request_limit": 8,
                    "token_limit": 20_000,
                    "time_budget_seconds": 120,
                    "context_confirmation_id": "synthetic-confirmation",
                    "budget_preview_hash": preview_hash,
                },
            )
            assert start.status_code == 202, start.text
            result = start.json()
            assert result["run_id"] == result["root_id"]
            async with AsyncSession(director_pg_engine) as verify:
                task = await verify.get(AsyncTask, result["task_id"])
                assert task is not None
                assert task.task_type == "story_scene_director"
                assert task.meta["director_root_id"] == result["root_id"]


async def test_assistant_bridge_accepts_only_owned_ordinary_author_turn(
    director_pg_engine,
):
    from sqlalchemy.ext.asyncio import AsyncSession

    from infrastructure.tasks.models import AsyncTask
    from modules.assistant.director_bridge import is_author_turn_run
    from modules.assistant.models import AssistantRun, AssistantSession

    novel_id, other_novel, run_id, task_id, session_id = (uuid4() for _ in range(5))
    async with AsyncSession(director_pg_engine, expire_on_commit=False) as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="director-bridge"))
        db.add_all(
            [
                Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="桥接作品"),
                Project(id=other_novel, owner_id=BOOTSTRAP_ACCOUNT_ID, title="另一作品"),
            ]
        )
        await db.flush()
        db.add(
            AssistantSession(
                id=session_id,
                novel_id=novel_id,
                title="作者会话",
                source_kind="project",
            )
        )
        db.add(AsyncTask(id=task_id, novel_id=novel_id, task_type="assistant_turn"))
        await db.flush()
        run = AssistantRun(
            id=run_id,
            novel_id=novel_id,
            owner_id=BOOTSTRAP_ACCOUNT_ID,
            session_id=session_id,
            task_id=task_id,
            mode="author",
            status="completed",
            request_hash="a" * 64,
        )
        db.add(run)
        await db.flush()
        scoped = dict(
            novel_id=str(novel_id),
            run_id=str(run_id),
            owner_id=str(BOOTSTRAP_ACCOUNT_ID),
        )
        assert await is_author_turn_run(db, **scoped)
        assert not await is_author_turn_run(
            db, **{**scoped, "novel_id": str(other_novel)}
        )
        assert not await is_author_turn_run(db, **{**scoped, "owner_id": str(uuid4())})
        task = await db.get(AsyncTask, task_id)
        task.task_type = "assistant_goal"
        await db.flush()
        assert not await is_author_turn_run(db, **scoped)
        await db.rollback()


@pytest.mark.parametrize(
    ("request_limit", "token_limit", "initial_rounds", "threshold"),
    [
        (10, 20_000, 1, "request_budget_80_percent"),
        (100, 100, 1, "token_budget_80_percent"),
        (100, 50, 2, "token_budget_80_percent"),
    ],
)
async def test_exact_worker_continues_same_root_and_stops_new_unknown(
    director_pg_engine, monkeypatch, request_limit, token_limit, initial_rounds, threshold
):
    from app.main import app as _app  # noqa: F401 - production task registration
    from infrastructure.llm.client import LLMClient
    from infrastructure.llm.schemas import LLMCallResponse, LLMUsage, read_ai_run_envelope
    from infrastructure.tasks.registry import TaskRegistry
    from infrastructure.tasks.worker import TaskWorker
    from modules.story.director_api import continue_director_root, submit_director_start
    from modules.story.director_operations import _continuation_preview
    from modules.story.tests.test_run_envelope_story import _NullLimiter

    novel_id, scene_id, actor_id = (uuid4() for _ in range(3))
    sessions = async_sessionmaker(director_pg_engine, expire_on_commit=False)
    async with sessions.begin() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="director-worker"))
        db.add(Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="导演离线整轮"))
        await db.flush()
        db.add(
            CoreEntity(
                id=actor_id,
                novel_id=novel_id,
                entity_type="character",
                name="阿澄",
                summary="谨慎的守夜人",
                status="canonical",
            )
        )
        await db.flush()
        db.add(
            Character(
                entity_id=actor_id,
                novel_id=novel_id,
                name="阿澄",
                status="canonical",
            )
        )
        db.add(Scene(id=scene_id, novel_id=novel_id, scene_index=0, title="北门对峙"))
    async with sessions() as db:
        source = await read_director_source(
            db,
            novel_id=str(novel_id),
            scene_id=str(scene_id),
            character_ids=[str(actor_id)],
            related_object_ids=[],
        )
    start = DirectorStartRequest(
        operation_id=uuid4(),
        novel_id=str(novel_id),
        scene_id=str(scene_id),
        character_ids=[str(actor_id)],
        rounds=initial_rounds,
        request_limit=request_limit,
        token_limit=token_limit,
        time_budget_seconds=120,
        context_confirmation_id=str(uuid4()),
        budget_preview_hash="0" * 64,
    )
    start.budget_preview_hash = preview_director_budget(start, source)["preview_hash"]
    confirmation = SimpleNamespace(
        compile_options={
            "scene_id": str(scene_id),
            "character_ids": [str(actor_id)],
            "entity_ids": [],
        }
    )

    async def confirmed(*_args, **_kwargs):
        return confirmation

    async def llm_snapshot(*_args):
        return {
            "novel_id": str(novel_id),
            "profile": {"provider_id": "deepseek", "model": "deepseek-flash"},
        }

    class Provider:
        name = "offline-director"
        calls = 0
        fail_next = False

        async def generate(self, request):
            self.calls += 1
            if self.fail_next:
                self.fail_next = False
                raise TimeoutError("offline synthetic unknown charge")
            data = json.loads(
                next(
                    message.content
                    for message in reversed(request.messages)
                    if message.role == "user"
                )
            )
            if self.calls % 4 == 1:
                payload = {"kind": "observe", "action": "听门外风声", "effect": "none"}
            elif self.calls % 4 == 2:
                payload = {
                    "outcomes": [
                        {"intent_id": item["intent_id"], "outcome": "succeeded"}
                        for item in data["intents"]
                    ]
                }
            elif self.calls % 4 == 3:
                payload = {
                    "character_id": str(actor_id),
                    "action": "停下脚步",
                    "expression": "眉间收紧",
                    "body_language": "侧身倾听",
                    "voice_and_dialogue": "低声说：等等。",
                    "subtext": "判断门外是谁",
                    "motive_and_emotion": "谨慎",
                    "trigger_and_defense": "风声骤停",
                    "attention": "门外",
                    "ignored": "桌面",
                    "change_from_previous": "初次",
                    "basis": [{"source_kind": "director_inference", "note": "合成候选"}],
                }
            else:
                payload = {
                    "materials": [
                        {
                            "material_id": "north-gate-wind",
                            "category": "environment",
                            "content": "北门的风声突然停了",
                            "senses": ["sound"],
                            "source_kind": "director_inference",
                        }
                    ],
                    "recommended_angles": [
                        {
                            "angle_id": "close",
                            "label": "阿澄视角",
                            "viewpoint_kind": "character",
                            "viewpoint_character_id": str(actor_id),
                            "narrative_distance": "close",
                            "focus": "门外",
                            "detail_and_pacing": "放慢",
                            "material_ids": ["north-gate-wind"],
                        },
                        {
                            "angle_id": "wide",
                            "label": "全知视角",
                            "viewpoint_kind": "omniscient",
                            "narrative_distance": "omniscient",
                            "focus": "全场",
                            "detail_and_pacing": "简洁",
                            "material_ids": ["north-gate-wind"],
                        },
                    ],
                    "alternatives": [
                        {
                            "alternative_id": "a",
                            "label": "谨慎",
                            "branch_instruction": "维持沉默",
                            "divergence": "conservative",
                        },
                        {
                            "alternative_id": "b",
                            "label": "行动",
                            "branch_instruction": "走向北门",
                            "divergence": "balanced",
                        },
                    ],
                }
            return LLMCallResponse(
                content=json.dumps(payload, ensure_ascii=False),
                finish_reason="stop",
                model="deepseek-flash",
                provider=self.name,
                usage=LLMUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            )

    provider = Provider()
    client = LLMClient.from_project_settings(
        {"llm": {"provider_id": "deepseek", "model": "deepseek-flash"}}
    )
    client._provider = provider

    @asynccontextmanager
    async def offline_client(*_args, **_kwargs):
        yield client

    monkeypatch.setattr(
        "infrastructure.llm.client.get_llm_limiter", lambda: _NullLimiter()
    )
    monkeypatch.setattr(
        "modules.story.director_api.require_fresh_confirmation", confirmed
    )
    monkeypatch.setattr("modules.story.director_api.attach_result_ref", confirmed)
    monkeypatch.setattr(
        "modules.story.director_api.build_project_llm_execution_snapshot", llm_snapshot
    )
    monkeypatch.setattr(
        "modules.story.director_tasks.prepare_confirmed_ai_action", confirmed
    )
    monkeypatch.setattr(
        "modules.story.director_tasks.open_project_snapshot_llm_client", offline_client
    )
    async with sessions.begin() as db:
        accepted = await submit_director_start(db, start)

    class Manager:
        engine = director_pg_engine
        session_factory = sessions

    worker = TaskWorker(db_manager=Manager(), heartbeat_interval=60.0)
    registry = TaskRegistry()
    original_handler = registry._handlers["story_scene_director"]
    captured_errors = []

    async def capture_error(db, task):
        try:
            return await original_handler(db, task)
        except Exception as error:
            captured_errors.append(error)
            raise

    monkeypatch.setitem(registry._handlers, "story_scene_director", capture_error)
    result = await asyncio.wait_for(
        worker.run_once(task_id=accepted.task_id, novel_id=novel_id), timeout=12
    )
    assert result is not None and result.status == "done", (
        [
            (frame.filename, frame.lineno, frame.line)
            for frame in traceback.extract_tb(captured_errors[-1].__traceback__)
            if "/modules/story/" in frame.filename
            or "/infrastructure/tasks/" in frame.filename
        ]
        if captured_errors
        else result.error_message
        if result
        else "no task"
    )
    assert provider.calls == 4, result.result
    if initial_rounds > 1:
        assert result.result["status"] == "paused_budget"
        assert result.result["completed_rounds"] == 1
        assert result.result["needs_author_resume"] is True
    else:
        assert result.result["status"] == "complete"
    async with sessions() as db:
        root = await db.get(StorySceneDirectorRoot, accepted.root_id)
        rounds = list(
            (
                await db.scalars(
                    select(StorySceneDirectorRound).where(
                        StorySceneDirectorRound.root_id == accepted.root_id
                    )
                )
            ).all()
        )
        assert len(rounds) == 1
        assert rounds[0].output_json["performances"][0]["character_id"] == str(actor_id)
        envelope = read_ai_run_envelope(root.run_envelope_json)
        assert envelope.run_id == str(accepted.root_id)
        assert envelope.requests_started == 4
        assert envelope.requests_settled == 4
        original_started_at = envelope.started_at
        original_deadline_at = envelope.deadline_at
        parent_round_id = rounds[0].id
    continuation = DirectorContinueRequest(
        novel_id=str(novel_id),
        context_confirmation_id=start.context_confirmation_id,
        operation_id=uuid4(),
        parent_round_id=parent_round_id,
        additional_tokens=50 if initial_rounds > 1 else 0,
        basis_choice="frozen",
        budget_preview_hash="0" * 64,
    )
    async with sessions() as db:
        _root, _parent, preview = await _continuation_preview(
            db, str(novel_id), continuation
        )
    continuation.budget_preview_hash = preview["preview_hash"]
    async with sessions.begin() as db:
        accepted_continuation = await continue_director_root(
            db, root_id=str(accepted.root_id), data=continuation
        )
    continued = await asyncio.wait_for(
        worker.run_once(task_id=accepted_continuation.task_id, novel_id=novel_id),
        timeout=12,
    )
    assert continued is not None and continued.status == "done", (
        continued.error_message if continued else "no task"
    )
    assert provider.calls == 8
    assert continued.result["status"] == "complete"
    assert not continued.result.get("needs_author_resume", False)
    async with sessions() as db:
        root = await db.get(StorySceneDirectorRoot, accepted.root_id)
        rounds = list(
            (
                await db.scalars(
                    select(StorySceneDirectorRound).where(
                        StorySceneDirectorRound.root_id == accepted.root_id
                    )
                )
            ).all()
        )
        assert len(rounds) == 2
        envelope = read_ai_run_envelope(root.run_envelope_json)
        assert envelope.run_id == str(accepted.root_id)
        assert envelope.requests_started == envelope.requests_settled == 8
        assert envelope.usage.total_tokens == 80
        assert envelope.started_at == original_started_at
        assert envelope.deadline_at == original_deadline_at
        assert budget_stop_reason(AIRunEnvelope(envelope)) == threshold
        assert root.status == "ready"
    continuation.operation_id = uuid4()
    continuation.parent_round_id = rounds[-1].id
    continuation.additional_requests = 0
    continuation.additional_tokens = 0
    async with sessions() as db:
        _root, _parent, preview = await _continuation_preview(
            db, str(novel_id), continuation
        )
    continuation.budget_preview_hash = preview["preview_hash"]
    with pytest.raises(ConflictError):
        async with sessions.begin() as db:
            await continue_director_root(
                db, root_id=str(accepted.root_id), data=continuation
            )
    assert provider.calls == 8

    # Reconstruct one explicitly labelled synthetic prior unknown receipt. The
    # next request still goes through the real worker/LLMClient path: accepting
    # the old possible charge must never waive a newly unknown provider result.
    async with sessions.begin() as db:
        root = await db.get(StorySceneDirectorRoot, accepted.root_id)
        receipt = read_ai_run_envelope(root.run_envelope_json).model_dump(mode="json")
        receipt["requests_started"] += 1
        receipt["requests_unknown"] += 1
        receipt["usage_complete"] = False
        receipt["charge_state"] = "possible"
        receipt["steps"][-1]["requests_started"] += 1
        receipt["steps"][-1]["requests_unknown"] += 1
        receipt["steps"][-1]["usage_complete"] = False
        receipt["steps"][-1]["charge_state"] = "possible"
        old_attempt = dict(receipt["recent_attempts"][-1])
        old_attempt.update(
            request_index=9,
            outcome="unknown",
            charge_state="possible",
            error_kind="SyntheticPriorUnknown",
        )
        receipt["recent_attempts"].append(old_attempt)
        root.run_envelope_json = read_ai_run_envelope(receipt).model_dump(mode="json")
    continuation.operation_id = uuid4()
    continuation.allow_possible_duplicate_charge = True
    continuation.additional_requests = 10
    continuation.additional_tokens = 100 if token_limit <= 100 else 0
    provider.fail_next = True
    async with sessions.begin() as db:
        accepted_unknown = await continue_director_root(
            db, root_id=str(accepted.root_id), data=continuation
        )
    paused = await asyncio.wait_for(
        worker.run_once(task_id=accepted_unknown.task_id, novel_id=novel_id), timeout=12
    )
    assert paused is not None and paused.status == "done"
    assert paused.result["status"] == "paused_unknown"
    assert provider.calls == 9
    async with sessions() as db:
        root = await db.get(StorySceneDirectorRoot, accepted.root_id)
        envelope = read_ai_run_envelope(root.run_envelope_json)
        assert envelope.requests_started == 10
        assert envelope.requests_unknown == 2
        assert envelope.started_at == original_started_at
        assert envelope.deadline_at == original_deadline_at
        assert envelope.run_id == str(accepted.root_id)
    await client.close()


async def test_api_delete_uses_worker_root_then_branch_lock_order(director_pg_engine):
    from sqlalchemy import delete

    from modules.account.context import bind_principal, reset_principal
    from modules.account.contracts import AccountPrincipal
    from modules.story.director_api import api_delete_director_branch
    from modules.story.director_schemas import DirectorDeleteBranchRequest

    sessions = async_sessionmaker(director_pg_engine, expire_on_commit=False)
    owner_id, novel_id, scene_id = (uuid4() for _ in range(3))
    token = bind_principal(
        AccountPrincipal(
            account_id=owner_id,
            status="active",
            identity_type="email",
            support_code=owner_id.hex,
        )
    )
    deletion = None
    try:
        async with sessions.begin() as db:
            db.add(Account(id=owner_id, support_code=owner_id.hex))
            db.add(Project(id=novel_id, owner_id=owner_id, title="导演锁顺序回归"))
            await db.flush()
            root_id, branch_id, _ = await _seed_history(db, novel_id, scene_id)
        started = asyncio.Event()
        deletion_pid = None

        async def delete_branch():
            nonlocal deletion_pid
            async with sessions.begin() as db:
                deletion_pid = await db.scalar(text("SELECT pg_backend_pid()"))
                started.set()
                return await api_delete_director_branch(
                    str(branch_id),
                    DirectorDeleteBranchRequest(novel_id=str(novel_id), confirm=True),
                    db,
                )

        async with sessions.begin() as worker:
            await worker.scalar(
                select(StorySceneDirectorRoot)
                .where(StorySceneDirectorRoot.id == root_id)
                .with_for_update()
            )
            deletion = asyncio.create_task(delete_branch())
            await asyncio.wait_for(started.wait(), timeout=5)

            async def wait_for_root_contention():
                # The fixture has two connections; use a separate observer so
                # the worker and deleting request can both retain their locks.
                observer_engine = create_async_engine(director_pg_engine.url, pool_size=1)
                try:
                    async with observer_engine.connect() as observer:
                        while not await observer.scalar(
                            text("SELECT cardinality(pg_blocking_pids(:pid))"),
                            {"pid": deletion_pid},
                        ):
                            await asyncio.sleep(0.01)
                finally:
                    await observer_engine.dispose()

            await asyncio.wait_for(wait_for_root_contention(), timeout=5)
            await asyncio.wait_for(
                worker.scalar(
                    select(StorySceneDirectorBranch)
                    .where(StorySceneDirectorBranch.id == branch_id)
                    .with_for_update()
                ),
                timeout=2,
            )
        await asyncio.wait_for(deletion, timeout=5)
    finally:
        if deletion is not None and not deletion.done():
            deletion.cancel()
            await asyncio.gather(deletion, return_exceptions=True)
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
            await db.execute(delete(Account).where(Account.id == owner_id))
        reset_principal(token)
