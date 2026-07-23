from __future__ import annotations

import pytest

from core.errors import NotFoundError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.project.schemas import ProjectCreate
from modules.project.services import ProjectService


def _principal(account: Account) -> AccountPrincipal:
    return AccountPrincipal(
        account_id=account.id,
        status="active",
        identity_type="email",
        support_code=account.support_code,
    )


@pytest.mark.asyncio
async def test_project_reads_are_hidden_across_accounts(db_session) -> None:
    first = Account(status="active", support_code="U-OWNER001")
    second = Account(status="active", support_code="U-OWNER002")
    db_session.add_all([first, second])
    await db_session.flush()
    service = ProjectService()
    first_token = bind_principal(_principal(first))
    try:
        project = await service.create_project(
            db_session,
            ProjectCreate(title="私有项目"),
        )
    finally:
        reset_principal(first_token)

    second_token = bind_principal(_principal(second))
    try:
        with pytest.raises(NotFoundError):
            await service.get_project(db_session, project.id)
        listed = await service.list_projects(db_session)
    finally:
        reset_principal(second_token)

    assert listed.total == 0
    assert listed.items == []
