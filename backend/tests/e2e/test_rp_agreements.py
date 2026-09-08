"""Run agreement persistence and real reducer transactions on PostgreSQL."""

import uuid

import pytest

from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.interaction.tests.test_services import (
    test_agreements_survive_three_real_reducer_passes_and_clear as _three_passes,
)
from modules.interaction.tests.test_services import (
    test_first_agreement_save_keeps_all_raw_and_supports_legacy_omission as _first_save,
)

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("verify", [_first_save, _three_passes])
async def test_agreements_on_postgresql(db_session, verify):
    owner = Account(status="active", support_code="RP-EVAL-" + uuid.uuid4().hex[:16])
    db_session.add(owner)
    await db_session.flush()
    token = bind_principal(
        AccountPrincipal(owner.id, "active", "email", owner.support_code)
    )
    try:
        await verify(db_session)
    finally:
        reset_principal(token)
