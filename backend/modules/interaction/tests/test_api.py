from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.interaction.models import InteractionJourney
from modules.interaction.schemas import JourneyCreateRequest
from modules.interaction.services import InteractionService

pytestmark = pytest.mark.asyncio
XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def _principal(account: Account) -> AccountPrincipal:
    return AccountPrincipal(
        account_id=account.id,
        status="active",
        identity_type="email",
        support_code=account.support_code,
    )


async def test_interaction_api_hides_all_journey_surfaces_from_other_owner(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = Account(status="active", support_code="U-RP-OWNER")
    stranger = Account(status="active", support_code="U-RP-OTHER")
    db_session.add_all([owner, stranger])
    await db_session.flush()

    owner_token = bind_principal(_principal(owner))
    try:
        with patch(
            "modules.interaction.services.build_project_llm_execution_snapshot",
            autospec=True,
            return_value={
                "version": "1",
                "novel_id": "filled-by-service",
                "profile": {"provider_id": "deepseek"},
            },
        ):
            created = await InteractionService().create_journey(
                db_session,
                JourneyCreateRequest(
                    opening_text="我进入一座陌生的海港城。",
                    idempotency_key="owner-isolation-create",
                ),
            )
    finally:
        reset_principal(owner_token)

    journey_id = created.journey.id
    attempt_id = created.attempt.id
    node_id = created.attempt.response_to_node_id
    other_token = bind_principal(_principal(stranger))
    try:
        listing = await async_client.get("/api/interactions/journeys")
        protected_reads = [
            await async_client.get(f"/api/interactions/journeys/{journey_id}"),
            await async_client.get(
                f"/api/interactions/journeys/{journey_id}/messages"
            ),
            await async_client.get(
                f"/api/interactions/journeys/{journey_id}/tree"
            ),
            await async_client.get(
                f"/api/interactions/journeys/{journey_id}/path-index"
            ),
            await async_client.get(
                f"/api/interactions/journeys/{journey_id}/overview"
            ),
            await async_client.get(
                "/api/interactions/journeys/"
                f"{journey_id}/nodes/{node_id}/branches"
            ),
            await async_client.get(
                "/api/interactions/journeys/"
                f"{journey_id}/attempts/{attempt_id}"
            ),
            await async_client.get(
                "/api/interactions/journeys/"
                f"{journey_id}/attempts/{attempt_id}/events"
            ),
        ]
        protected_write = await async_client.patch(
            f"/api/interactions/journeys/{journey_id}/title",
            json={"title": "不应成功"},
        )
    finally:
        reset_principal(other_token)

    assert listing.status_code == 200
    assert listing.json() == {"items": [], "total": 0}
    assert {response.status_code for response in protected_reads} == {404}
    assert protected_write.status_code == 404
    assert str(uuid.UUID(journey_id)) not in str(listing.json())


async def test_hidden_interaction_project_is_rejected_by_author_apis(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = Account(status="active", support_code="U-RP-AUTHOR-GATE")
    db_session.add(owner)
    await db_session.flush()

    owner_token = bind_principal(_principal(owner))
    try:
        with patch(
            "modules.interaction.services.build_project_llm_execution_snapshot",
            autospec=True,
            return_value={
                "version": "1",
                "novel_id": "filled-by-service",
                "profile": {"provider_id": "deepseek"},
            },
        ):
            created = await InteractionService().create_journey(
                db_session,
                JourneyCreateRequest(
                    opening_text="我在陌生世界的雨夜醒来。",
                    idempotency_key="interaction-author-api-gate",
                ),
            )

        journey = await db_session.get(
            InteractionJourney,
            uuid.UUID(created.journey.id),
        )
        assert journey is not None
        hidden_novel_id = str(journey.novel_id)
        world_read = await async_client.get(
            "/api/world/entities",
            params={"novel_id": hidden_novel_id},
        )
        writing_task = await async_client.post(
            "/api/writing/generate",
            json={
                "novel_id": hidden_novel_id,
                "chapter_index": 1,
                "instruction": "不应进入作者任务队列",
                "context_confirmation_id": str(uuid.uuid4()),
            },
        )
    finally:
        reset_principal(owner_token)

    assert world_read.status_code == 404
    assert writing_task.status_code == 404


async def test_see_sea_notice_acknowledgement_is_account_scoped(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = Account(status="active", support_code="U-RP-NOTICE")
    stranger = Account(status="active", support_code="U-RP-NOTICE-OTHER")
    db_session.add_all([owner, stranger])
    await db_session.flush()

    owner_token = bind_principal(_principal(owner))
    try:
        before = await async_client.get("/api/interactions/preferences")
        acknowledged = await async_client.post(
            "/api/interactions/preferences/see-sea-notice",
            headers=XHR_HEADERS,
        )
        after = await async_client.get("/api/interactions/preferences")
    finally:
        reset_principal(owner_token)

    other_token = bind_principal(_principal(stranger))
    try:
        other = await async_client.get("/api/interactions/preferences")
    finally:
        reset_principal(other_token)

    assert before.json() == {"see_sea_notice_acknowledged": False}
    assert acknowledged.json() == {"see_sea_notice_acknowledged": True}
    assert after.json() == {"see_sea_notice_acknowledged": True}
    assert other.json() == {"see_sea_notice_acknowledged": False}
