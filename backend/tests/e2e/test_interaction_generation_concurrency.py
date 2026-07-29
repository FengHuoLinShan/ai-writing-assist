from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError, NotFoundError
from infrastructure.tasks.models import AsyncTask
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.interaction.models import (
    InteractionAccountPreference,
    InteractionBranchSelection,
    InteractionGenerationAttempt,
    InteractionJourney,
    InteractionMessageNode,
)
from modules.interaction.repositories import InteractionRepository
from modules.interaction.services import InteractionService
from modules.project.facade import require_interaction_project
from modules.project.models import Project
from modules.settings.models import AccountLLMCredential, GlobalLLMDefaults
from modules.settings.services import SettingsService
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


def _principal(owner_id: uuid.UUID) -> AccountPrincipal:
    return AccountPrincipal(
        account_id=owner_id,
        status="active",
        identity_type="email",
        support_code=f"rp-pg-{owner_id.hex[:12]}",
    )


async def test_account_generation_lock_admits_only_the_eighth_attempt() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_id = uuid.uuid4()
    targets: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []
    now = datetime.now(UTC)

    try:
        async with sessions.begin() as setup_db:
            setup_db.add(
                Account(
                    id=owner_id,
                    status="active",
                    support_code=f"rp-limit-{uuid.uuid4().hex[:16]}",
                )
            )
            await setup_db.flush()
            for index in range(9):
                novel_id = uuid.uuid4()
                journey_id = uuid.uuid4()
                node_id = uuid.uuid4()
                setup_db.add(
                    Project(
                        id=novel_id,
                        owner_id=owner_id,
                        project_kind="interaction",
                        title=f"RP concurrency {index}",
                    )
                )
                targets.append((novel_id, journey_id, node_id))
            await setup_db.flush()
            for index, (novel_id, journey_id, _node_id) in enumerate(targets):
                setup_db.add(
                    InteractionJourney(
                        id=journey_id,
                        novel_id=novel_id,
                        owner_id=owner_id,
                        title=f"旅程 {index}",
                        title_source="fallback",
                        opening_text="并发门禁测试",
                        status="active",
                        see_sea_enabled=False,
                        action_options_enabled=True,
                        selection_epoch=0,
                        overview_epoch=0,
                        latest_activity_at=now,
                    )
                )
            await setup_db.flush()
            for novel_id, journey_id, node_id in targets:
                setup_db.add(
                    InteractionMessageNode(
                        id=node_id,
                        novel_id=novel_id,
                        journey_id=journey_id,
                        role="user",
                        message_kind="setup",
                        content="并发门禁测试",
                        completion_state="complete",
                        token_estimate=8,
                    )
                )
            await setup_db.flush()
            for index, (novel_id, journey_id, node_id) in enumerate(targets[:7]):
                setup_db.add(
                    InteractionGenerationAttempt(
                        novel_id=novel_id,
                        journey_id=journey_id,
                        owner_id=owner_id,
                        response_to_node_id=node_id,
                        idempotency_key=f"existing-{index}-{uuid.uuid4()}",
                        request_kind="message",
                        status="pending",
                        started_selection_epoch=0,
                        visible_text="",
                        visible_offset=0,
                        metadata_text="",
                        llm_execution_snapshot={},
                        context_path_hash="a" * 64,
                        context_node_ids=[str(node_id)],
                        reference_node_ids=[],
                        usage={},
                    )
                )

        ready = 0
        ready_lock = asyncio.Lock()
        release = asyncio.Event()

        async def try_admit(
            target: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
        ) -> bool:
            nonlocal ready
            async with ready_lock:
                ready += 1
                if ready == 2:
                    release.set()
            await release.wait()
            novel_id, journey_id, node_id = target
            async with sessions.begin() as db:
                repo = InteractionRepository()
                await repo.lock_owner_generation_slots(db, owner_id=owner_id)
                if await repo.count_active_attempts(db, owner_id=owner_id) >= 8:
                    return False
                db.add(
                    InteractionGenerationAttempt(
                        novel_id=novel_id,
                        journey_id=journey_id,
                        owner_id=owner_id,
                        response_to_node_id=node_id,
                        idempotency_key=f"candidate-{uuid.uuid4()}",
                        request_kind="message",
                        status="pending",
                        started_selection_epoch=0,
                        visible_text="",
                        visible_offset=0,
                        metadata_text="",
                        llm_execution_snapshot={},
                        context_path_hash="b" * 64,
                        context_node_ids=[str(node_id)],
                        reference_node_ids=[],
                        usage={},
                    )
                )
                await db.flush()
                return True

        admitted = await asyncio.gather(
            try_admit(targets[7]),
            try_admit(targets[8]),
        )

        assert sorted(admitted) == [False, True]
        async with sessions() as verify_db:
            count = await verify_db.scalar(
                select(func.count(InteractionGenerationAttempt.id)).where(
                    InteractionGenerationAttempt.owner_id == owner_id,
                    InteractionGenerationAttempt.status.in_(
                        ("pending", "preparing_context", "running")
                    ),
                )
            )
            assert count == 8
    finally:
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(Account).where(Account.id == owner_id))
        await engine.dispose()


async def test_same_provider_connect_validates_once_under_concurrency() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_id = uuid.uuid4()
    token = None
    try:
        async with sessions.begin() as setup_db:
            setup_db.add(
                Account(
                    id=owner_id,
                    status="active",
                    support_code=f"rp-llm-{owner_id.hex[:16]}",
                )
            )
        token = bind_principal(_principal(owner_id))

        async def connect() -> None:
            async with sessions.begin() as db:
                await SettingsService().connect_account_llm_provider(
                    db,
                    "deepseek",
                    "test-account-key",
                )

        with pytest.MonkeyPatch.context() as monkeypatch:
            validator_calls = 0

            async def validate(_provider_id: str, _api_key: str) -> None:
                nonlocal validator_calls
                validator_calls += 1

            monkeypatch.setattr(
                "modules.settings.services._validate_account_llm_connection",
                validate,
            )
            await asyncio.gather(connect(), connect())

        async with sessions() as verify_db:
            credential_count = await verify_db.scalar(
                select(func.count(AccountLLMCredential.id)).where(
                    AccountLLMCredential.owner_id == owner_id,
                    AccountLLMCredential.provider_id == "deepseek",
                )
            )
            head_count = await verify_db.scalar(
                select(func.count(GlobalLLMDefaults.id)).where(
                    GlobalLLMDefaults.owner_id == owner_id
                )
            )
        assert validator_calls == 1
        assert credential_count == 1
        assert head_count == 1
    finally:
        if token is not None:
            reset_principal(token)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(Account).where(Account.id == owner_id))
        await engine.dispose()


async def test_cross_provider_connect_keeps_one_account_head(
    monkeypatch,
) -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_id = uuid.uuid4()
    token = None
    monkeypatch.setenv("ENABLE_ACCOUNT_KIMI_K3", "1")
    try:
        async with sessions.begin() as setup_db:
            setup_db.add(
                Account(
                    id=owner_id,
                    status="active",
                    support_code=f"rp-cross-{owner_id.hex[:16]}",
                )
            )
        token = bind_principal(_principal(owner_id))

        async def connect(provider_id: str) -> None:
            async with sessions.begin() as db:
                await SettingsService().connect_account_llm_provider(
                    db,
                    provider_id,
                    f"test-{provider_id}-key",
                )

        async def validate(_provider_id: str, _api_key: str) -> None:
            return None

        monkeypatch.setattr(
            "modules.settings.services._validate_account_llm_connection",
            validate,
        )
        await asyncio.gather(connect("deepseek"), connect("kimi"))

        async with sessions() as verify_db:
            credentials = list(
                (
                    await verify_db.execute(
                        select(AccountLLMCredential).where(
                            AccountLLMCredential.owner_id == owner_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            heads = list(
                (
                    await verify_db.execute(
                        select(GlobalLLMDefaults).where(
                            GlobalLLMDefaults.owner_id == owner_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert {item.provider_id for item in credentials} == {
            "deepseek",
            "kimi",
        }
        assert len(heads) == 1
        assert heads[0].provider_id in {"deepseek", "kimi"}
    finally:
        if token is not None:
            reset_principal(token)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(Account).where(Account.id == owner_id))
        await engine.dispose()


async def test_see_sea_notice_acknowledgement_is_idempotent_under_concurrency(
    monkeypatch,
) -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_id = uuid.uuid4()
    token = None
    original_get_preference = InteractionRepository.get_account_preference
    try:
        async with sessions.begin() as setup_db:
            setup_db.add(
                Account(
                    id=owner_id,
                    status="active",
                    support_code=f"rp-notice-{owner_id.hex[:16]}",
                )
            )
        token = bind_principal(_principal(owner_id))

        async def delayed_missing_preference(
            self,
            db,
            *,
            owner_id,
            for_update=False,
        ):
            value = await original_get_preference(
                self,
                db,
                owner_id=owner_id,
                for_update=for_update,
            )
            if value is None:
                await asyncio.sleep(0.05)
            return value

        monkeypatch.setattr(
            InteractionRepository,
            "get_account_preference",
            delayed_missing_preference,
        )

        async def acknowledge() -> None:
            async with sessions.begin() as db:
                await InteractionService().acknowledge_see_sea_notice(db)

        await asyncio.gather(acknowledge(), acknowledge())

        async with sessions() as verify_db:
            preferences = list(
                (
                    await verify_db.execute(
                        select(InteractionAccountPreference).where(
                            InteractionAccountPreference.owner_id == owner_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(preferences) == 1
        assert preferences[0].see_sea_notice_acknowledged is True
    finally:
        if token is not None:
            reset_principal(token)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(Account).where(Account.id == owner_id))
        await engine.dispose()


async def test_archive_locks_hidden_project_before_journey(
    monkeypatch,
) -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_id = uuid.uuid4()
    novel_id = uuid.uuid4()
    journey_id = uuid.uuid4()
    token = None
    journey_locked = asyncio.Event()
    release_archive = asyncio.Event()
    worker_has_project_lock = asyncio.Event()
    service = InteractionService()
    original_get_journey = service._repo.get_journey  # noqa: SLF001
    try:
        async with sessions.begin() as setup_db:
            setup_db.add(
                Account(
                    id=owner_id,
                    status="active",
                    support_code=f"rp-archive-{owner_id.hex[:16]}",
                )
            )
            setup_db.add(
                Project(
                    id=novel_id,
                    owner_id=owner_id,
                    project_kind="interaction",
                    title="RP archive lock order",
                )
            )
            await setup_db.flush()
            setup_db.add(
                InteractionJourney(
                    id=journey_id,
                    novel_id=novel_id,
                    owner_id=owner_id,
                    title="归档锁顺序",
                    title_source="fallback",
                    opening_text="归档并发测试",
                    status="active",
                    see_sea_enabled=False,
                    action_options_enabled=True,
                    selection_epoch=0,
                    overview_epoch=0,
                    latest_activity_at=datetime.now(UTC),
                )
            )
        token = bind_principal(_principal(owner_id))

        async def pause_after_journey_lock(
            db,
            *,
            journey_id,
            owner_id,
            status="active",
            for_update=False,
        ):
            result = await original_get_journey(
                db,
                journey_id=journey_id,
                owner_id=owner_id,
                status=status,
                for_update=for_update,
            )
            if for_update:
                journey_locked.set()
                await release_archive.wait()
            return result

        monkeypatch.setattr(
            service._repo,  # noqa: SLF001
            "get_journey",
            pause_after_journey_lock,
        )

        async def archive():
            async with sessions.begin() as db:
                return await service.archive_journey(
                    db,
                    journey_id=str(journey_id),
                    confirmed=True,
                )

        async def worker_preflight() -> str:
            async with sessions.begin() as db:
                try:
                    await require_interaction_project(db, str(novel_id))
                except NotFoundError:
                    return "archived"
                worker_has_project_lock.set()
                row = await InteractionRepository().get_journey_for_task(
                    db,
                    journey_id=journey_id,
                    novel_id=novel_id,
                    for_update=True,
                )
                return "active" if row is not None else "missing"

        archive_task = asyncio.create_task(archive())
        await journey_locked.wait()
        worker_task = asyncio.create_task(worker_preflight())
        try:
            await asyncio.wait_for(worker_has_project_lock.wait(), timeout=0.2)
        except TimeoutError:
            pass
        release_archive.set()
        archived, worker_status = await asyncio.wait_for(
            asyncio.gather(archive_task, worker_task),
            timeout=5,
        )

        assert archived.status == "archived"
        assert worker_status == "archived"
    finally:
        release_archive.set()
        if token is not None:
            reset_principal(token)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(Account).where(Account.id == owner_id))
        await engine.dispose()


async def test_branch_selection_epoch_allows_only_one_concurrent_switch() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_id = uuid.uuid4()
    novel_id = uuid.uuid4()
    journey_id = uuid.uuid4()
    root_id = uuid.uuid4()
    branch_ids = [uuid.uuid4(), uuid.uuid4()]
    token = None
    now = datetime.now(UTC)
    try:
        async with sessions.begin() as setup_db:
            setup_db.add(
                Account(
                    id=owner_id,
                    status="active",
                    support_code=f"rp-branch-{owner_id.hex[:16]}",
                )
            )
            setup_db.add(
                Project(
                    id=novel_id,
                    owner_id=owner_id,
                    project_kind="interaction",
                    title="RP branch race",
                )
            )
            # These models intentionally do not expose cross-module ORM
            # relationships, so make the FK ordering explicit in the fixture.
            await setup_db.flush()
            setup_db.add(
                InteractionJourney(
                    id=journey_id,
                    novel_id=novel_id,
                    owner_id=owner_id,
                    title="并发分支",
                    title_source="fallback",
                    opening_text="并发分支测试",
                    status="active",
                    see_sea_enabled=False,
                    action_options_enabled=True,
                    selected_leaf_node_id=branch_ids[0],
                    selection_epoch=0,
                    overview_epoch=0,
                    latest_activity_at=now,
                )
            )
            setup_db.add(
                InteractionMessageNode(
                    id=root_id,
                    novel_id=novel_id,
                    journey_id=journey_id,
                    role="user",
                    message_kind="setup",
                    content="起点",
                    completion_state="complete",
                    token_estimate=2,
                )
            )
            for index, branch_id in enumerate(branch_ids):
                setup_db.add(
                    InteractionMessageNode(
                        id=branch_id,
                        novel_id=novel_id,
                        journey_id=journey_id,
                        parent_node_id=root_id,
                        role="assistant",
                        message_kind="story",
                        content=f"分支 {index}",
                        completion_state="complete",
                        token_estimate=2,
                    )
                )
            await setup_db.flush()
            setup_db.add_all(
                [
                    InteractionBranchSelection(
                        novel_id=novel_id,
                        journey_id=journey_id,
                        parent_node_id=None,
                        parent_key="__root__",
                        selected_child_node_id=root_id,
                    ),
                    InteractionBranchSelection(
                        novel_id=novel_id,
                        journey_id=journey_id,
                        parent_node_id=root_id,
                        parent_key=str(root_id),
                        selected_child_node_id=branch_ids[0],
                    ),
                ]
            )
        token = bind_principal(_principal(owner_id))

        async def select_target(node_id: uuid.UUID) -> bool:
            try:
                async with sessions.begin() as db:
                    await InteractionService().select_branch(
                        db,
                        journey_id=str(journey_id),
                        node_id=str(node_id),
                        expected_selection_epoch=0,
                    )
                return True
            except ConflictError:
                return False

        outcomes = await asyncio.gather(
            select_target(branch_ids[0]),
            select_target(branch_ids[1]),
        )

        assert sorted(outcomes) == [False, True]
        async with sessions() as verify_db:
            journey = await verify_db.get(InteractionJourney, journey_id)
            assert journey is not None
            assert journey.selection_epoch == 1
            assert journey.selected_leaf_node_id in branch_ids
    finally:
        if token is not None:
            reset_principal(token)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(Account).where(Account.id == owner_id))
        await engine.dispose()


async def test_manual_send_wins_fresh_see_sea_beat_boundary() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_id = uuid.uuid4()
    novel_id = uuid.uuid4()
    journey_id = uuid.uuid4()
    root_id = uuid.uuid4()
    story_id = uuid.uuid4()
    token = None
    now = datetime.now(UTC)
    try:
        async with sessions.begin() as setup_db:
            setup_db.add(
                Account(
                    id=owner_id,
                    status="active",
                    support_code=f"rp-manual-{owner_id.hex[:16]}",
                )
            )
            setup_db.add(
                Project(
                    id=novel_id,
                    owner_id=owner_id,
                    project_kind="interaction",
                    title="RP manual priority",
                )
            )
            await setup_db.flush()
            setup_db.add(
                InteractionJourney(
                    id=journey_id,
                    novel_id=novel_id,
                    owner_id=owner_id,
                    title="手工操作优先",
                    title_source="fallback",
                    opening_text="边界竞态测试",
                    status="active",
                    see_sea_enabled=True,
                    action_options_enabled=True,
                    see_sea_last_heartbeat_at=now,
                    selected_leaf_node_id=story_id,
                    selection_epoch=0,
                    overview_epoch=0,
                    latest_activity_at=now,
                )
            )
            setup_db.add_all(
                [
                    InteractionMessageNode(
                        id=root_id,
                        novel_id=novel_id,
                        journey_id=journey_id,
                        role="user",
                        message_kind="setup",
                        content="起点",
                        completion_state="complete",
                        token_estimate=2,
                        created_at=now,
                    ),
                    InteractionMessageNode(
                        id=story_id,
                        novel_id=novel_id,
                        journey_id=journey_id,
                        parent_node_id=root_id,
                        role="assistant",
                        message_kind="story",
                        content="刚刚正式化的看海节拍。",
                        completion_state="complete",
                        token_estimate=8,
                        created_at=now,
                    ),
                ]
            )
            await setup_db.flush()
            setup_db.add_all(
                [
                    InteractionBranchSelection(
                        novel_id=novel_id,
                        journey_id=journey_id,
                        parent_node_id=None,
                        parent_key="__root__",
                        selected_child_node_id=root_id,
                    ),
                    InteractionBranchSelection(
                        novel_id=novel_id,
                        journey_id=journey_id,
                        parent_node_id=root_id,
                        parent_key=str(root_id),
                        selected_child_node_id=story_id,
                    ),
                ]
            )
        token = bind_principal(_principal(owner_id))

        async def heartbeat():
            async with sessions.begin() as db:
                return await InteractionService().heartbeat(
                    db,
                    journey_id=str(journey_id),
                )

        async def manual_send():
            async with sessions.begin() as db:
                return await InteractionService().send_message(
                    db,
                    journey_id=str(journey_id),
                    content="我现在接管故事，先检查门外的动静。",
                    expected_selection_epoch=0,
                    idempotency_key=f"manual-priority-{uuid.uuid4()}",
                )

        async def snapshot(_db, requested_novel_id: str) -> dict:
            return {
                "version": "1",
                "novel_id": requested_novel_id,
                "profile": {"provider_id": "deepseek"},
            }

        with patch(
            "modules.interaction.services.build_project_llm_execution_snapshot",
            autospec=True,
            side_effect=snapshot,
        ):
            heartbeat_result, manual_result = await asyncio.gather(
                heartbeat(),
                manual_send(),
            )

        assert manual_result.attempt is not None
        if heartbeat_result.attempt is not None:
            assert heartbeat_result.attempt.id == manual_result.attempt.id
        async with sessions() as verify_db:
            attempts = list(
                (
                    await verify_db.execute(
                        select(InteractionGenerationAttempt).where(
                            InteractionGenerationAttempt.journey_id == journey_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            journey = await verify_db.get(InteractionJourney, journey_id)
        assert len(attempts) == 1
        assert attempts[0].request_kind == "message"
        assert journey is not None
        assert journey.selection_epoch == 1
        assert journey.selected_leaf_node_id == attempts[0].response_to_node_id
    finally:
        if token is not None:
            reset_principal(token)
        async with sessions.begin() as cleanup_db:
            task_ids = list(
                (
                    await cleanup_db.execute(
                        select(InteractionGenerationAttempt.task_id).where(
                            InteractionGenerationAttempt.owner_id == owner_id,
                            InteractionGenerationAttempt.task_id.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if task_ids:
                await cleanup_db.execute(
                    delete(AsyncTask).where(AsyncTask.id.in_(task_ids))
                )
            await cleanup_db.execute(delete(Account).where(Account.id == owner_id))
        await engine.dispose()
