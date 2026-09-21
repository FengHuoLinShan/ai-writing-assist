"""Public routes reject wrong owners, restricted identities and missing CSRF."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from infrastructure.tasks.models import AsyncTask
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.assistant.forecast.tests.test_forecasts import settings_on


@pytest.mark.parametrize(
    "identity", ["other_owner", "demo_readonly", "anonymous_rp", "pending_deletion"]
)
async def test_forecast_routes_do_not_reveal_restricted_project(
    db_session, project_factory, async_client, monkeypatch, identity
):
    settings_on(monkeypatch)
    db, owner = db_session, uuid4()
    db.add(
        Account(
            id=owner,
            status="pending_deletion" if identity == "pending_deletion" else "active",
            support_code="forecast-" + owner.hex[:15],
        )
    )
    await db.flush()
    nid = str(
        await project_factory.create_project(title="不能泄露的项目名称", owner_id=owner)
    )
    token = bind_principal(
        AccountPrincipal(
            account_id=uuid4() if identity == "other_owner" else owner,
            status="pending_deletion" if identity == "pending_deletion" else "active",
            identity_type="anonymous_rp" if identity == "anonymous_rp" else "email",
            support_code="forecast-test",
            access_scope="demo_readonly" if identity == "demo_readonly" else "account",
            demo_project_id=None,
        )
    )
    try:
        base = "/api/assistant/forecasts"
        context = {"client_context_id": str(uuid4()), "focus_seq": 0, "page": "today"}
        for endpoint in ("capabilities", f"runs/{uuid4()}", f"candidates/{uuid4()}"):
            result = await async_client.get(
                f"{base}/{endpoint}", params={"novel_id": nid}
            )
            assert result.status_code == 404, result.text
            assert "不能泄露" not in result.text
        for endpoint, body in [
            ("feed", {"context": context}),
            (
                "evaluate",
                {
                    "context": context,
                    "operation_id": str(uuid4()),
                    "horizon": {"unit": "scene"},
                },
            ),
        ]:
            result = await async_client.post(
                f"{base}/{endpoint}", params={"novel_id": nid}, json=body
            )
            assert result.status_code == 404, result.text
        assert await db.scalar(select(func.count()).select_from(AsyncTask)) == 0
    finally:
        reset_principal(token)


async def test_forecast_post_without_xhr_is_rejected_before_work(
    raw_async_client, db_session, test_project_id, monkeypatch
):
    settings_on(monkeypatch)
    response = await raw_async_client.post(
        "/api/assistant/forecasts/feed",
        params={"novel_id": test_project_id},
        json={
            "context": {
                "client_context_id": str(uuid4()),
                "focus_seq": 0,
                "page": "today",
            }
        },
    )
    assert response.status_code == 403 and "detail" in response.json()
    assert await db_session.scalar(select(func.count()).select_from(AsyncTask)) == 0
