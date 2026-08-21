from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from modules.account.settings_service import SettingsService


@pytest.mark.asyncio
async def test_image_connection_is_separate_from_active_text_provider(db_session) -> None:
    client = AsyncMock()
    with patch(
        "modules.account.settings_service.OpenAIImageClient",
        autospec=True,
        return_value=client,
    ):
        service = SettingsService()
        connected = await service.connect_account_image_provider(db_session, "sk-test")
        text_connections = await service.get_account_llm_connections(db_session)

    assert connected.connected is True
    assert connected.model == "gpt-image-2"
    assert connected.verification_scope == "credential_only"
    assert text_connections.active_provider_id == "deepseek"
    assert {item.provider_id for item in text_connections.providers} == {"deepseek"}
    client.verify_connection.assert_awaited_once()
    client.close.assert_awaited_once()

    cleared = await service.clear_account_image_provider(db_session)
    assert cleared.connected is False
