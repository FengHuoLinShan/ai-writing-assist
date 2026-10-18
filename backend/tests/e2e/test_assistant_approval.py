"""Real PostgreSQL serialization of task revocation and domain writes."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.assistant_operation_registry import world_operations
from core.errors import ConflictError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.assistant import approval
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.evidence_tools import fingerprint
from modules.assistant.models import AssistantApprovalGrant, AssistantRun
from modules.assistant.schemas import WorkContext
from modules.project.models import Project
from modules.world.models import CoreEntity
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest.mark.parametrize("revoke_first", [False, True])
@pytest.mark.parametrize("change", ["revoke", "budget_resume"])
async def test_grant_change_and_real_write_have_one_transaction_order(
    monkeypatch, revoke_first, change
):
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner, novel, run_id, entity = (uuid.uuid4() for _ in range(4))
    attempt_id = str(uuid.uuid4())
    preview = {"entity": str(entity), "before": "旧简介", "after": "旅人", "version": 1}
    snapshot = {"purpose": "approval_judgment", "profile": {"model": "synthetic"}}
    scope = {"targets": [str(entity)], "budget": {"requests": 4}}
    expires_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    principal = AccountPrincipal(
        account_id=owner,
        status="active",
        identity_type="email",
        support_code="approval-" + owner.hex[:12],
    )
    token = bind_principal(principal)
    entered, release = asyncio.Event(), asyncio.Event()
    tasks = []

    async def restore(_db, novel_id, snapshot):
        assert novel_id == str(novel) and snapshot["purpose"] == "approval_judgment"
        return {}

    monkeypatch.setattr(approval, "restore_project_llm_execution_settings", restore)
    try:
        async with sessions.begin() as db:
            db.add(
                Account(id=owner, status="active", support_code=principal.support_code)
            )
            await db.flush()
            db.add(Project(id=novel, owner_id=owner, title="代批并发合成项目"))
            await db.flush()
            db.add(
                AssistantRun(
                    id=run_id,
                    novel_id=novel,
                    owner_id=owner,
                    request_hash="a" * 64,
                    mode="author",
                    status="running",
                )
            )
            db.add(
                CoreEntity(
                    id=entity,
                    novel_id=novel,
                    entity_type="character",
                    name="林舟",
                    summary="旧简介",
                )
            )
            await db.flush()
            db.add(
                AssistantApprovalGrant(
                    run_id=run_id,
                    novel_id=novel,
                    version=1,
                    status="active",
                    policy_json={
                        "owner_id": str(owner),
                        "novel_id": str(novel),
                        "run_id": str(run_id),
                        "expires_at": expires_at,
                        "judge_fingerprint": approval.calibration_fingerprint(snapshot),
                        "scope_fingerprint": fingerprint(scope),
                        "budget": scope["budget"],
                    },
                    model_snapshot_json=snapshot,
                    attempts_json=[
                        {
                            "id": attempt_id,
                            "version": 1,
                            "decision": "allow",
                            "fingerprint": "a" * 64,
                            "preview_hash": fingerprint(preview),
                        }
                    ],
                )
            )

        async def write():
            async with sessions() as db:
                run = await db.get(AssistantRun, run_id)
                grant, _attempt = await approval.require_execution_approval(
                    db, run, attempt_id, preview
                )
                operation = world_operations["world.edit_entity"]
                arguments = operation.schema.model_validate(
                    {"entity_id": str(entity), "changes": {"summary": "旅人"}}
                )
                context = AssistantOperationContext(
                    str(run_id), str(owner), WorkContext(page="world", scope="project")
                )
                prepared = await operation.prepare(
                    db, str(novel), arguments, context=context
                )
                result = await operation.apply(
                    db, str(novel), arguments, prepared, context=context
                )
                approval.record_execution(
                    grant, attempt_id, {"status": "completed", "result": result}
                )
                entered.set()
                await release.wait()
                await db.commit()

        async def revoke():
            async with sessions() as db:
                if change == "budget_resume":
                    run = await db.get(AssistantRun, run_id)
                    assert await approval.resume_goal_grant(
                        db, run, scope, {**scope, "budget": {"requests": 6}}
                    )
                    await db.commit()
                    return await approval.grant_view(
                        db, str(novel), str(run_id), str(owner)
                    )
                return await approval.revoke_grant(
                    db, str(novel), str(run_id), str(owner), 1
                )

        expected_status = "revoked" if change == "revoke" else "active"
        if revoke_first:
            assert (await revoke())["status"] == expected_status
            with pytest.raises(ConflictError, match="撤回|失效"):
                await write()
        else:
            write_task = asyncio.create_task(write())
            tasks.append(write_task)
            await asyncio.wait_for(entered.wait(), 5)
            revoke_task = asyncio.create_task(revoke())
            tasks.append(revoke_task)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(revoke_task), 0.15)
            release.set()
            await asyncio.wait_for(write_task, 5)
            assert (await asyncio.wait_for(revoke_task, 5))["status"] == expected_status

        async with sessions() as db:
            row = await db.get(CoreEntity, entity)
            grant = await db.get(AssistantApprovalGrant, run_id)
            assert row.summary == ("旧简介" if revoke_first else "旅人")
            assert grant.version == 2 and grant.status == expected_status
            assert bool(grant.attempts_json[0].get("execution")) is not revoke_first
            assert len(grant.attempts_json) == 1
            assert grant.policy_json["expires_at"] == expires_at
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel))
            await db.execute(delete(Account).where(Account.id == owner))
        await engine.dispose()
        reset_principal(token)
