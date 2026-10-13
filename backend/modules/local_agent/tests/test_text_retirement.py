"""Retired text settings cannot reopen the host transport."""

import pytest

from core.errors import ValidationError
from modules.local_agent.executor_service import task_snapshot_client


@pytest.mark.asyncio
async def test_legacy_text_settings_fail_before_project_or_device_access():
    with pytest.raises(ValidationError, match="只运行图片任务"):
        await task_snapshot_client(
            None, None, {"_local_agent": {"device_id": "old-device"}}, budget=None
        )
