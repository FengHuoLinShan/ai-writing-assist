"""Author RP operations through the mounted HTTP routes and real PostgreSQL."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.main import app
from core.database import get_manager
from infrastructure.llm.capabilities import (
    LLM_CAPABILITY_SNAPSHOT_KEY,
    resolve_llm_capability_profile,
)
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import (
    LLMCallResponse,
    LLMMessage,
    read_ai_run_envelope,
)
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.worker import TaskWorker
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.account.models import Account
from modules.interaction import author_operations
from modules.interaction import tasks as interaction_tasks
from modules.interaction.generation import (
    InteractionGenerationWorkflow,
    PreparedSummaryGeneration,
)
from modules.interaction.models import (
    InteractionBranchSelection,
    InteractionJourney,
    InteractionMessageNode,
    InteractionSourceRevision,
)
from modules.project.models import Project
from tests.e2e.config import require_e2e_database_url
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_author_journey_http_keeps_source_consumer_and_owner_separate():
    engine = create_async_engine(require_e2e_database_url())
    author, other_author, consumer, foreign_author, foreign_consumer = (
        uuid4() for _ in range(5)
    )
    owner, foreign_owner = BOOTSTRAP_ACCOUNT_ID, uuid4()
    revision, foreign_revision, journey, foreign_journey = (
        uuid4() for _ in range(4)
    )
    try:
        async with AsyncSession(engine) as db:
            if await db.get(Account, owner) is None:
                db.add(Account(id=owner, support_code=uuid4().hex))
            db.add(Account(id=foreign_owner, support_code=uuid4().hex))
            db.add_all(
                [
                    Project(id=author, owner_id=owner, title="作者作品"),
                    Project(id=other_author, owner_id=owner, title="另一作者作品"),
                    Project(
                        id=consumer,
                        owner_id=owner,
                        title="私有旅程项目",
                        project_kind="interaction",
                    ),
                    Project(id=foreign_author, owner_id=foreign_owner, title="他人作品"),
                    Project(
                        id=foreign_consumer,
                        owner_id=foreign_owner,
                        title="他人旅程",
                        project_kind="interaction",
                    ),
                ]
            )
            await db.flush()
            db.add_all(
                [
                    InteractionSourceRevision(
                        id=revision,
                        source_novel_id=author,
                        owner_id=owner,
                        version_number=1,
                        title="作者作品 v1",
                        status="ready",
                        manifest_hash="a" * 64,
                        fingerprint="b" * 64,
                    ),
                    InteractionSourceRevision(
                        id=foreign_revision,
                        source_novel_id=foreign_author,
                        owner_id=foreign_owner,
                        version_number=1,
                        title="他人作品 v1",
                        status="ready",
                        manifest_hash="c" * 64,
                        fingerprint="d" * 64,
                    ),
                ]
            )
            await db.flush()
            db.add_all(
                [
                    InteractionJourney(
                        id=journey,
                        novel_id=consumer,
                        owner_id=owner,
                        title="雾港来客",
                        opening_text="合成开场",
                        source_revision_id=revision,
                        source_anchor={
                            "chapter_index": 1,
                            "end_offset": 12,
                            "label": "第一章",
                        },
                        latest_activity_at=datetime.now(UTC),
                    ),
                    InteractionJourney(
                        id=foreign_journey,
                        novel_id=foreign_consumer,
                        owner_id=foreign_owner,
                        title="他人的旅程",
                        opening_text="合成开场",
                        source_revision_id=foreign_revision,
                        source_anchor={
                            "chapter_index": 1,
                            "end_offset": 12,
                            "label": "第一章",
                        },
                        latest_activity_at=datetime.now(UTC),
                    ),
                ]
            )
            await db.commit()

        async with XhrAsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            base = "/api/interactions/author/journeys"
            listed = await client.post(
                f"{base}/list", json={"author_project_id": str(author)}
            )
            assert listed.status_code == 200, listed.text
            cards = listed.json()["preview"]["items"]
            assert len(cards) == 1 and cards[0]["id"] == str(journey)
            assert cards[0]["source"]["author_project_id"] == str(author)
            assert cards[0]["consumer_project_id"] == str(consumer)
            for wrong_author, wrong_journey in (
                (other_author, journey),
                (author, foreign_journey),
                (foreign_author, foreign_journey),
                (consumer, journey),
            ):
                denied = await client.post(
                    f"{base}/title/prepare",
                    json={
                        "author_project_id": str(wrong_author),
                        "journey_id": str(wrong_journey),
                        "expected_title": "雾港来客",
                        "title": "雾港新客",
                    },
                )
                assert denied.status_code == 404, denied.text

            request = {
                "author_project_id": str(author),
                "journey_id": str(journey),
                "expected_title": "雾港来客",
                "title": "雾港新客",
            }
            prepared = await client.post(f"{base}/title/prepare", json=request)
            assert prepared.status_code == 200, prepared.text
            digest = prepared.json()["preview_hash"]
            missing_confirmation = await client.post(
                f"{base}/title/confirm",
                json={**request, "expected_preview_hash": digest},
            )
            assert missing_confirmation.status_code == 409
            changed = await client.post(
                f"{base}/title/confirm",
                json={**request, "expected_preview_hash": digest, "confirmed": True},
            )
            assert changed.status_code == 200, changed.text
            stale = await client.post(
                f"{base}/title/confirm",
                json={**request, "expected_preview_hash": digest, "confirmed": True},
            )
            assert stale.status_code == 409
            settings = {
                "author_project_id": str(author),
                "journey_id": str(journey),
                "expected_selection_epoch": 0,
                "expected_action_options_enabled": True,
                "action_options_enabled": False,
            }
            settings_preview = await client.post(
                f"{base}/settings/prepare", json=settings
            )
            assert settings_preview.status_code == 200, settings_preview.text
            settings_saved = await client.post(
                f"{base}/settings/confirm",
                json={
                    **settings,
                    "expected_preview_hash": settings_preview.json()["preview_hash"],
                    "confirmed": True,
                },
            )
            assert settings_saved.status_code == 200, settings_saved.text
            assert (
                await client.post(f"{base}/settings/prepare", json=settings)
            ).status_code == 409

            state = {
                "author_project_id": str(author),
                "journey_id": str(journey),
                "expected_status": "active",
            }
            archive_preview = await client.post(f"{base}/archive/prepare", json=state)
            assert archive_preview.status_code == 200, archive_preview.text
            archived = await client.post(
                f"{base}/archive/confirm",
                json={
                    **state,
                    "expected_preview_hash": archive_preview.json()["preview_hash"],
                    "confirmed": True,
                },
            )
            assert archived.status_code == 200, archived.text
            archived_list = await client.post(
                f"{base}/list",
                json={"author_project_id": str(author), "status": "archived"},
            )
            assert archived_list.json()["preview"]["items"][0]["id"] == str(journey)

            state["expected_status"] = "archived"
            restore_preview = await client.post(f"{base}/restore/prepare", json=state)
            assert restore_preview.status_code == 200, restore_preview.text
            restored = await client.post(
                f"{base}/restore/confirm",
                json={
                    **state,
                    "expected_preview_hash": restore_preview.json()["preview_hash"],
                    "confirmed": True,
                },
            )
            assert restored.status_code == 200, restored.text
            reread = await client.post(
                f"{base}/list", json={"author_project_id": str(author)}
            )
            assert reread.json()["preview"]["items"][0]["title"] == "雾港新客"
            assert reread.json()["preview"]["items"][0]["action_options_enabled"] is False
    finally:
        await engine.dispose()


async def test_summary_http_receipt_and_worker_source_fence(monkeypatch):
    engine = create_async_engine(require_e2e_database_url())
    author, consumer, revision_id, journey_id = (uuid4() for _ in range(4))
    root_node, story_node, operation_id = (uuid4() for _ in range(3))
    try:
        async with AsyncSession(engine) as db:
            if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
                db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code=uuid4().hex))
            db.add_all(
                [
                    Project(id=author, owner_id=BOOTSTRAP_ACCOUNT_ID, title="摘要来源"),
                    Project(
                        id=consumer,
                        owner_id=BOOTSTRAP_ACCOUNT_ID,
                        title="摘要旅程",
                        project_kind="interaction",
                    ),
                ]
            )
            await db.flush()
            db.add(
                InteractionSourceRevision(
                    id=revision_id,
                    source_novel_id=author,
                    owner_id=BOOTSTRAP_ACCOUNT_ID,
                    version_number=1,
                    title="摘要资料",
                    status="ready",
                    manifest_hash="a" * 64,
                    fingerprint="b" * 64,
                )
            )
            await db.flush()
            db.add(
                InteractionJourney(
                    id=journey_id,
                    novel_id=consumer,
                    owner_id=BOOTSTRAP_ACCOUNT_ID,
                    title="摘要旅程",
                    opening_text="合成开场",
                    source_revision_id=revision_id,
                    source_anchor={"chapter_index": 1, "end_offset": 12},
                    selected_leaf_node_id=story_node,
                    latest_activity_at=datetime.now(UTC),
                )
            )
            await db.flush()
            db.add_all(
                [
                    InteractionMessageNode(
                        id=root_node,
                        novel_id=consumer,
                        journey_id=journey_id,
                        role="user",
                        message_kind="setup",
                        content="合成开场",
                        token_estimate=20,
                    ),
                    InteractionMessageNode(
                        id=story_node,
                        novel_id=consumer,
                        journey_id=journey_id,
                        parent_node_id=root_node,
                        role="assistant",
                        message_kind="story",
                        content="合成故事",
                        token_estimate=20,
                    ),
                ]
            )
            await db.flush()
            db.add_all(
                [
                    InteractionBranchSelection(
                        novel_id=consumer,
                        journey_id=journey_id,
                        parent_key="__root__",
                        selected_child_node_id=root_node,
                    ),
                    InteractionBranchSelection(
                        novel_id=consumer,
                        journey_id=journey_id,
                        parent_node_id=root_node,
                        parent_key=str(root_node),
                        selected_child_node_id=story_node,
                    ),
                ]
            )
            await db.commit()

        snapshot = {
            "version": "1",
            "novel_id": str(consumer),
            "profile": {"provider_id": "deepseek", "model": "deepseek-v4-flash"},
            LLM_CAPABILITY_SNAPSHOT_KEY: resolve_llm_capability_profile(
                "deepseek", "deepseek-v4-flash"
            ).to_snapshot(),
        }

        async def frozen_snapshot(_db, novel_id):
            assert novel_id == str(consumer)
            return snapshot

        async def offline_summary(_self, _db, *, journey, current_path, **_kwargs):
            return PreparedSummaryGeneration(
                novel_id=str(consumer),
                journey_id=str(journey.id),
                path_hash=author_operations.path_hash(current_path),
                node_ids=[str(item.id) for item in current_path],
                segment_node_ids=[str(root_node)],
                started_overview_epoch=journey.overview_epoch,
                messages=[LLMMessage(role="user", content="合成旧故事")],
                executable_settings={"llm": {"provider_id": "deepseek"}},
                estimated_input_tokens=20,
                segment_path_hash=author_operations.path_hash(current_path[:1]),
                protected_node_ids=[str(story_node)],
            )

        monkeypatch.setattr(
            author_operations, "build_project_llm_execution_snapshot", frozen_snapshot
        )
        monkeypatch.setattr(
            InteractionGenerationWorkflow, "_prepare_summary_generation", offline_summary
        )
        request = {
            "author_project_id": str(author),
            "journey_id": str(journey_id),
            "operation_id": str(operation_id),
        }
        async with XhrAsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            base = "/api/interactions/author/journeys/summary"
            preview = await client.post(f"{base}/prepare", json=request)
            assert preview.status_code == 200, preview.text
            budget = preview.json()["preview"]
            assert budget["execution_ready"] is True
            assert budget["deadline_seconds"] == 1800
            assert budget["unknown_charge_stop_available"] is True
            confirm = {
                **request,
                "expected_preview_hash": preview.json()["preview_hash"],
                "confirmed": True,
            }
            started = await client.post(f"{base}/confirm", json=confirm)
            assert started.status_code == 200, started.text
            task_id = started.json()["result"]["task_id"]
            repeated = await client.post(f"{base}/confirm", json=confirm)
            assert repeated.status_code == 200, repeated.text
            assert repeated.json()["result"]["task_id"] == task_id
            receipt = await client.post(f"{base}/result", json=confirm)
            assert receipt.status_code == 200 and receipt.json()["task_id"] == task_id

        class OfflineProvider:
            name = "offline"
            calls = 0
            drift_source = False

            async def generate(self, _request):
                self.calls += 1
                if self.drift_source:
                    async with AsyncSession(engine) as domain_db:
                        source = await domain_db.get(
                            InteractionSourceRevision, revision_id
                        )
                        source.status = "failed"
                        await domain_db.commit()
                return LLMCallResponse(
                    content=json.dumps(
                        {
                            "segment_summary": "开场时主角来到雾港。",
                            "overview": {"world_and_start": "雾港开场"},
                        },
                        ensure_ascii=False,
                    ),
                    finish_reason="stop",
                    model="deepseek-v4-flash",
                    provider="offline",
                )

        provider = OfflineProvider()

        def offline_client(*_args, **_kwargs):
            client = LLMClient()
            client._provider = provider
            return client

        monkeypatch.setattr(
            interaction_tasks, "create_project_snapshot_llm_client", offline_client
        )
        completed = await TaskWorker(db_manager=get_manager()).run_once(
            task_id=task_id, novel_id=str(consumer)
        )
        assert completed is not None and completed.status == "done"
        assert provider.calls == 1
        async with AsyncSession(engine) as db:
            first_task = await db.get(AsyncTask, completed.id)
            envelope = read_ai_run_envelope(first_task.meta.get("_ai_run_envelope"))
            assert envelope is not None and envelope.requests_started == 1
            assert envelope.requests_settled == 1

        next_request = {**request, "operation_id": str(uuid4())}
        async with XhrAsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            next_preview = await client.post(f"{base}/prepare", json=next_request)
            assert next_preview.status_code == 200, next_preview.text
            next_confirm = await client.post(
                f"{base}/confirm",
                json={
                    **next_request,
                    "expected_preview_hash": next_preview.json()["preview_hash"],
                    "confirmed": True,
                },
            )
            assert next_confirm.status_code == 200, next_confirm.text
            stale_task_id = next_confirm.json()["result"]["task_id"]

        provider.drift_source = True
        after_provider_drift = await TaskWorker(db_manager=get_manager()).run_once(
            task_id=stale_task_id, novel_id=str(consumer)
        )
        assert after_provider_drift is not None
        assert after_provider_drift.status == "failed"
        assert provider.calls == 2
        async with AsyncSession(engine) as db:
            journey = await db.get(InteractionJourney, journey_id)
            assert journey.overview_epoch == 1
            source = await db.get(InteractionSourceRevision, revision_id)
            source.status = "ready"
            await db.commit()

        provider.drift_source = False
        third_request = {**request, "operation_id": str(uuid4())}
        async with XhrAsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            third_preview = await client.post(f"{base}/prepare", json=third_request)
            assert third_preview.status_code == 200, third_preview.text
            third_confirm = await client.post(
                f"{base}/confirm",
                json={
                    **third_request,
                    "expected_preview_hash": third_preview.json()["preview_hash"],
                    "confirmed": True,
                },
            )
            assert third_confirm.status_code == 200, third_confirm.text
            preflight_stale_task_id = third_confirm.json()["result"]["task_id"]

        async with AsyncSession(engine) as db:
            source = await db.get(InteractionSourceRevision, revision_id)
            source.status = "failed"
            await db.commit()
        monkeypatch.setattr(
            interaction_tasks,
            "create_project_snapshot_llm_client",
            lambda *_args, **_kwargs: pytest.fail("stale source reached provider"),
        )
        finished = await TaskWorker(db_manager=get_manager()).run_once(
            task_id=preflight_stale_task_id, novel_id=str(consumer)
        )
        assert finished is not None and finished.status == "failed"
        async with AsyncSession(engine) as db:
            task = await db.get(AsyncTask, finished.id)
            envelope = read_ai_run_envelope(task.meta.get("_ai_run_envelope"))
            assert envelope is not None and envelope.requests_started == 0
    finally:
        await engine.dispose()
