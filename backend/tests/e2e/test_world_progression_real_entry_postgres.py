"""A canonical chapter and Scene can enter the real progression task pipeline."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import inspect, select

from app.main import app
from core.config import Settings
from core.database import (
    assert_database_target_for_testing,
    get_manager,
    isolated_database_manager_for_testing,
)
from core.errors import ConflictError
from infrastructure.llm.client import LLMClient
from infrastructure.llm.limits import reset_llm_limiter_for_tests
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.llm.secret_store import encrypt_secret, fingerprint_secret
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.worker import TaskWorker
from modules.account.settings_constants import (
    ACCOUNT_LLM_PROVIDER_TEMPLATES,
    LOCAL_OWNER_ID,
)
from modules.account.settings_repositories import (
    AccountLLMCredentialRepository,
    GlobalLLMDefaultsRepository,
)
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.schemas import WorkContext
from modules.project.models import Project
from modules.story import world_progression_tasks
from modules.story.outline_state.models import Scene
from modules.story.world_progression_models import (
    StoryWorldProgressionRoot,
    StoryWorldProgressionStep,
)
from modules.story.world_progression_operations import (
    _apply_hook_adopt,
    _apply_resume,
    _apply_start,
    _prepare_budget,
    _prepare_compare,
    _prepare_history,
    _prepare_hook_adopt,
    _prepare_hook_preview,
    _prepare_resume,
    _prepare_start,
    _read_continuous,
    _require_root_scope,
    _require_work_scope,
)
from modules.story.world_progression_schemas import (
    ProgressionBudgetPreviewRequest,
    ProgressionCompareRequest,
    ProgressionContinuousAuthorizationReadRequest,
    ProgressionHistoryRequest,
    ProgressionHookAdoptRequest,
    ProgressionHookPreviewRequest,
    ProgressionResumeRequest,
    ProgressionStartRequest,
)
from modules.world.models import CoreEntity
from modules.world.models.character import Character
from modules.writing.facade import create_published_draft_only
from tests.e2e.config import DATABASE_URL, require_e2e_database_url
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest_asyncio.fixture(autouse=True)
async def isolated_global_database_manager():
    """Compile and TaskWorker use independent sessions concurrently."""
    database_url = require_e2e_database_url(DATABASE_URL)
    settings = Settings(database_url=database_url, pool_size=4, max_overflow=0)
    async with isolated_database_manager_for_testing(settings) as manager:
        assert_database_target_for_testing(database_url, manager.engine.url)
        yield


def _row_snapshot(row):
    if row is None:
        return None
    return {
        attribute.key: deepcopy(getattr(row, attribute.key))
        for attribute in inspect(row).mapper.column_attrs
    }


@pytest_asyncio.fixture
async def offline_account_settings(monkeypatch, isolated_global_database_manager):
    """Restore opaque account rows after the offline execution snapshot test."""
    monkeypatch.setenv(
        "LLM_SETTINGS_ENCRYPTION_KEY", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
    )
    credentials = AccountLLMCredentialRepository()
    defaults = GlobalLLMDefaultsRepository()
    async with get_manager().session_factory() as db:
        credential_before = _row_snapshot(
            await credentials.get(db, LOCAL_OWNER_ID, "deepseek")
        )
        defaults_before = _row_snapshot(await defaults.get(db, LOCAL_OWNER_ID))
    try:
        async with get_manager().session_factory() as db:
            key = "offline-world-progression-e2e-no-network"
            await credentials.upsert(
                db,
                {
                    "owner_id": LOCAL_OWNER_ID,
                    "provider_id": "deepseek",
                    "encrypted_api_key": encrypt_secret(key),
                    "key_fingerprint": fingerprint_secret(
                        key, purpose="account-llm-api-key"
                    ),
                    "verified_at": datetime.now(UTC),
                },
            )
            await defaults.upsert(
                db,
                {
                    "owner_id": LOCAL_OWNER_ID,
                    **ACCOUNT_LLM_PROVIDER_TEMPLATES["deepseek"],
                },
            )
            await db.commit()
        yield
    finally:
        async with get_manager().session_factory() as db:
            for repository, before, current in (
                (
                    credentials,
                    credential_before,
                    await credentials.get(db, LOCAL_OWNER_ID, "deepseek"),
                ),
                (defaults, defaults_before, await defaults.get(db, LOCAL_OWNER_ID)),
            ):
                if before is None:
                    if current is not None:
                        await db.delete(current)
                elif current is not None:
                    for field, value in before.items():
                        setattr(current, field, value)
                else:
                    raise AssertionError(
                        f"account row disappeared: {type(repository).__name__}"
                    )
            await db.commit()


class _OfflineProvider:
    name = "offline"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        prompt = json.loads(
            next(
                message.content for message in request.messages if message.role == "user"
            )
        )
        if "actor_id" in prompt:
            result = {
                "intent": {
                    "actor_id": prompt["actor_id"],
                    "kind": "action",
                    "action": "留在门前辨认标记",
                    "reason": "合成角色谨慎确认线索",
                    "basis_ids": [
                        next(
                            source_id
                            for source_id in prompt["packet"]["source_ids"]
                            if source_id.startswith("world:entity:")
                        )
                    ],
                    "effect": "none",
                }
            }
        else:
            intent_id = next(iter(prompt["intent_ids"].values()))
            result = {
                "story_time_text": "约一天",
                "narrative_summary": "巡行者辨认标记后仍留在门前。",
                "rolling_summary": "巡行者在门前观察。",
                "outcomes": {intent_id: "succeeded"},
            }
        return LLMCallResponse(
            content=json.dumps(result, ensure_ascii=False),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            model="deepseek-flash",
            provider="offline",
        )


async def test_canonical_scene_preview_confirmation_start_and_offline_worker(
    monkeypatch, offline_account_settings
):
    monkeypatch.setenv("STORY_WORLD_PROGRESSION_ENABLED", "true")
    # The verified synthetic setting is restored by the fixture. The provider
    # itself is always replaced with the offline implementation below.
    novel_id, actor_id = (uuid4() for _ in range(2))
    async with get_manager().session_factory() as db:
        db.add(Project(id=novel_id, title="真实来源离线世界推进"))
        await db.flush()
        draft = await create_published_draft_only(
            db,
            str(novel_id),
            1,
            "合成第一章",
            "巡行者抵达门前。他看见信使留下的标记。",
        )
        assert draft.status == "published"
        db.add(
            CoreEntity(
                id=actor_id,
                novel_id=novel_id,
                entity_type="character",
                name="巡行者",
                summary="谨慎寻找信使",
                status="canonical",
            )
        )
        await db.flush()
        db.add_all(
            [
                Character(
                    entity_id=actor_id,
                    novel_id=novel_id,
                    name="巡行者",
                    desire="寻找信使",
                    status="canonical",
                ),
            ]
        )
        await db.commit()

    async with XhrAsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://test",
    ) as client:
        scene_response = await client.post(
            f"/api/outline/scenes?novel_id={novel_id}",
            json={
                "scene_index": 0,
                "title": "门前标记",
                "chapter_ids": ["1"],
                "pov_character_id": str(actor_id),
                "status": "canonical",
                "goal": "辨认标记",
            },
        )
        assert scene_response.status_code == 201, scene_response.text
        scene_id = UUID(scene_response.json()["id"])

    selection = {
        "novel_id": str(novel_id),
        "task": "从门前标记推进一小步",
        "scope": "scene",
        "scene_id": str(scene_id),
        "visible_until_scene_id": str(scene_id),
        "character_ids": [str(actor_id)],
        "entity_ids": [],
        "budget_tokens": 0,
    }
    budget = {
        "novel_id": str(novel_id),
        "participants": [{"kind": "character", "id": str(actor_id)}],
        "request_limit": 10,
        "token_limit": 20000,
        "time_budget_seconds": 3600,
    }
    reset_llm_limiter_for_tests()
    async with XhrAsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://test",
    ) as client:
        preview = await client.post(
            "/api/story/world-progression/budget-preview", json=budget
        )
        assert preview.status_code == 200, preview.text
        preview_data = preview.json()
        assert preview_data["scene_id"] == str(scene_id)
        assert preview_data["scene_index"] == 0
        assert preview_data["scene_title"] == "门前标记"
        assert preview_data["participants"] == 1
        assert preview_data["request_budget"]["estimate_minimum"] == 2
        compiled = await client.post(
            "/api/evidence/compilation/compile",
            json={**selection, "action": "story.one_click.simulate"},
        )
        assert compiled.status_code == 200, compiled.text
        assert len(compiled.json()["context_fingerprint"]) == 64
        confirmation = await client.post(
            "/api/evidence/compilation/confirm",
            json={
                **selection,
                "action": "story.one_click.simulate",
                "expected_context_fingerprint": compiled.json()["context_fingerprint"],
            },
        )
        assert confirmation.status_code == 201, confirmation.text
        assert (
            confirmation.json()["context_fingerprint"]
            == compiled.json()["context_fingerprint"]
        )
        stale = await client.post(
            "/api/story/world-progression/roots",
            json={
                **budget,
                "scene_id": str(scene_id),
                "operation_id": str(uuid4()),
                "context_confirmation_id": confirmation.json()["id"],
                "budget_preview_hash": "0" * 64,
            },
        )
        assert stale.status_code == 409, stale.text
        async with get_manager().session_factory() as db:
            assert (
                await db.scalars(
                    select(StoryWorldProgressionRoot).where(
                        StoryWorldProgressionRoot.novel_id == novel_id
                    )
                )
            ).all() == []
        started = await client.post(
            "/api/story/world-progression/roots",
            json={
                **budget,
                "scene_id": str(scene_id),
                "operation_id": str(uuid4()),
                "context_confirmation_id": confirmation.json()["id"],
                "budget_preview_hash": preview_data["preview_hash"],
            },
        )
        assert started.status_code == 202, started.text
        task_id = UUID(started.json()["task_id"])
        root_id = UUID(started.json()["root_id"])

    provider = _OfflineProvider()

    @asynccontextmanager
    async def offline_client(_db, _novel_id, _snapshot):
        client = LLMClient.from_project_settings(
            {"llm": {"provider_id": "deepseek", "model": "deepseek-flash"}}
        )
        client._provider = provider
        yield client

    monkeypatch.setattr(
        world_progression_tasks, "open_project_snapshot_llm_client", offline_client
    )
    worker = TaskWorker(db_manager=get_manager())
    await worker.run_once(task_id=task_id, novel_id=novel_id)
    async with get_manager().session_factory() as db:
        task = await db.get(AsyncTask, task_id)
        root = await db.get(StoryWorldProgressionRoot, root_id)
        steps = (
            await db.scalars(
                select(StoryWorldProgressionStep).where(
                    StoryWorldProgressionStep.root_id == root_id
                )
            )
        ).all()
        assert task.status == "done"
        assert len(steps) == 1
        assert root.scene_id == scene_id
        scene_snapshot = root.source_snapshot_json["scene_context"]["outline_bundle"][
            "scene"
        ]
        assert scene_snapshot["scene_index"] == 0
        assert root.run_envelope_json["requests_started"] == provider.calls == 2

        from evals.authoring_quality_guard import AuthoringQualityError, ProductReference
        from evals.authoring_quality_product import read_product_evidence

        evidence_ref = ProductReference(
            kind="world_progression",
            scene_id=str(scene_id),
            root_id=str(root_id),
            branch_id=started.json()["branch_id"],
            task_id=str(task_id),
            source_sha256=steps[0].source_hash,
            output_ids=[str(steps[0].id)],
        )
        evaluation = SimpleNamespace(
            project_id=str(novel_id),
            project_snapshot=root.llm_execution_snapshot_json,
        )
        evidence = await read_product_evidence(db, evaluation, evidence_ref)
        assert evidence["task"]["status"] == "done"
        assert evidence["outputs"][0]["output_sha256"] == steps[0].output_hash
        assert evidence["confirmation"]["compile_options"]["scene_id"] == str(scene_id)
        with pytest.raises(AuthoringQualityError):
            await read_product_evidence(
                db,
                evaluation,
                evidence_ref.model_copy(update={"branch_id": str(uuid4())}),
            )
        savepoint = await db.begin_nested()
        try:
            changed_scene = await db.get(Scene, scene_id)
            changed_scene.goal = "合成修订：改变原场景目标"
            await db.flush()
            with pytest.raises(AuthoringQualityError, match="source|confirmation"):
                await read_product_evidence(db, evaluation, evidence_ref)
        finally:
            await savepoint.rollback()

        current_work = WorkContext(scope="current", scene_id=scene_id)
        other_scene = AssistantOperationContext(
            run_id=str(uuid4()),
            owner_id=str(LOCAL_OWNER_ID),
            work=current_work.model_copy(update={"scene_id": uuid4()}),
        )
        with pytest.raises(PermissionError, match="Scene"):
            await _require_root_scope(db, str(novel_id), other_scene, root)
        history_request = ProgressionHistoryRequest(
            novel_id=str(novel_id), root_id=root_id
        )
        with pytest.raises(PermissionError, match="Scene"):
            await _prepare_history(
                db, str(novel_id), history_request, context=other_scene
            )
        compare_request = ProgressionCompareRequest(
            novel_id=str(novel_id),
            first_step_id=steps[0].id,
            second_step_id=steps[0].id,
        )
        with pytest.raises(PermissionError, match="Scene"):
            await _prepare_compare(
                db, str(novel_id), compare_request, context=other_scene
            )
        branch_id = UUID(started.json()["branch_id"])
        resume_request = ProgressionResumeRequest(
            novel_id=str(novel_id),
            root_id=root_id,
            branch_id=branch_id,
            resume_hash="0" * 64,
            operation_id=uuid4(),
            acknowledge_unknown_requests=0,
            context_confirmation_id=confirmation.json()["id"],
        )
        for operation in (_prepare_resume, _apply_resume):
            with pytest.raises(PermissionError, match="Scene"):
                if operation is _apply_resume:
                    await operation(
                        db, str(novel_id), resume_request, {}, context=other_scene
                    )
                else:
                    await operation(
                        db, str(novel_id), resume_request, context=other_scene
                    )
        hook_request = ProgressionHookPreviewRequest(
            novel_id=str(novel_id),
            root_id=root_id,
            step_id=steps[0].id,
            hook_id="synthetic-hook",
            asset_type="plot_thread",
            operation_id=uuid4(),
            context_confirmation_id=confirmation.json()["id"],
        )
        with pytest.raises(PermissionError, match="Scene"):
            await _prepare_hook_preview(
                db, str(novel_id), hook_request, context=other_scene
            )
        hook_adopt = ProgressionHookAdoptRequest(
            **hook_request.model_dump(), preview_hash="0" * 64
        )
        for operation in (_prepare_hook_adopt, _apply_hook_adopt):
            with pytest.raises(PermissionError, match="Scene"):
                if operation is _apply_hook_adopt:
                    await operation(
                        db, str(novel_id), hook_adopt, {}, context=other_scene
                    )
                else:
                    await operation(db, str(novel_id), hook_adopt, context=other_scene)
        authorization_read = ProgressionContinuousAuthorizationReadRequest(
            novel_id=str(novel_id), root_id=root_id, branch_id=branch_id
        )
        with pytest.raises(PermissionError, match="Scene"):
            await _read_continuous(
                db, str(novel_id), authorization_read, context=other_scene
            )
        current_context = AssistantOperationContext(
            run_id=str(uuid4()), owner_id=str(LOCAL_OWNER_ID), work=current_work
        )
        budget_request = ProgressionBudgetPreviewRequest(**budget)
        with pytest.raises(PermissionError, match="Scene"):
            await _prepare_budget(db, str(novel_id), budget_request, context=other_scene)
        start_request = ProgressionStartRequest(
            **budget,
            scene_id=str(scene_id),
            operation_id=uuid4(),
            context_confirmation_id=confirmation.json()["id"],
            budget_preview_hash=preview_data["preview_hash"],
        )
        with pytest.raises(PermissionError, match="Scene"):
            await _prepare_start(db, str(novel_id), start_request, context=other_scene)
        with pytest.raises(PermissionError, match="Scene"):
            await _apply_start(db, str(novel_id), start_request, {}, context=other_scene)
        with pytest.raises(PermissionError, match="整部作品"):
            await _prepare_history(
                db,
                str(novel_id),
                ProgressionHistoryRequest(novel_id=str(novel_id)),
                context=current_context,
            )
        excluded_context = AssistantOperationContext(
            run_id=str(uuid4()),
            owner_id=str(LOCAL_OWNER_ID),
            work=current_work.model_copy(
                update={"excluded_targets": [f"core_entity:{actor_id}"]}
            ),
        )
        with pytest.raises(ConflictError, match="已排除"):
            await _require_root_scope(db, str(novel_id), excluded_context, root)
        confirmed_context = AssistantOperationContext(
            run_id=str(uuid4()),
            owner_id=str(LOCAL_OWNER_ID),
            work=current_work.model_copy(
                update={
                    "context_confirmation_id": UUID(confirmation.json()["id"]),
                    "context_confirmation_action": "story.one_click.simulate",
                }
            ),
        )
        await _require_root_scope(db, str(novel_id), confirmed_context, root)
        scoped_budget = await _prepare_budget(
            db, str(novel_id), budget_request, context=confirmed_context
        )
        assert scoped_budget["scene_id"] == str(scene_id)
        assert (
            await _prepare_start(
                db, str(novel_id), start_request, context=confirmed_context
            )
        )["preview_hash"] == preview_data["preview_hash"]
        scoped_history = await _prepare_history(
            db, str(novel_id), history_request, context=confirmed_context
        )
        assert len(scoped_history["roots"]) == 1
        with pytest.raises(ConflictError, match="原确认"):
            await _require_work_scope(
                db,
                str(novel_id),
                confirmed_context,
                scene_id=scene_id,
                participant_ids=[uuid4()],
            )

    from tests.e2e.authoring_quality_helpers import assert_director_product_evidence

    await assert_director_product_evidence(
        monkeypatch, novel_id, scene_id, actor_id, confirmation.json()["id"]
    )
