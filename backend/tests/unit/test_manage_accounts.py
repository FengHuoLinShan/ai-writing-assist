from argparse import Namespace
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from core.container import reset
from modules.account.models import Account
from scripts import manage_accounts


@pytest.mark.parametrize("command", ["ban", "purge-due", "purge-maintenance"])
async def test_account_cli_runs_lifecycle_from_cold_container(
    command,
    db_session,
    monkeypatch,
):
    account = Account(
        support_code="U-CLI-REVIEW",
        status="active" if command == "ban" else "pending_deletion",
        purge_after=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.add(account)
    await db_session.flush()
    account_id = account.id
    closed = False

    @asynccontextmanager
    async def session():
        yield db_session

    async def close():
        nonlocal closed
        closed = True

    monkeypatch.setattr(
        manage_accounts,
        "get_manager",
        lambda: SimpleNamespace(session=session, close=close),
    )
    reset()  # The operational CLI starts without the API/worker composition root.

    assert (
        await manage_accounts._run(
            Namespace(command=command, account_id=account_id, execute=True),
        )
        == 0
    )
    status = await db_session.scalar(
        select(Account.status).where(Account.id == account_id)
    )
    assert status == ("banned" if command == "ban" else None)
    assert closed
