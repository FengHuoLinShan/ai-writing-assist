from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from modules.imports.workflow_llm_adapters import _project_settings_for_novel


@pytest.mark.asyncio
async def test_project_settings_fallback_uses_snapshot_runtime_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.project import facade as project_facade

    snapshot = {
        "version": "1",
        "novel_id": "novel-1",
        "profile_hash": "safe-hash",
    }
    restored = {
        "llm": {
            "provider_id": "deepseek",
            "api_key": "runtime-only-key",
        }
    }
    build_snapshot = AsyncMock(return_value=snapshot)
    restore_settings = AsyncMock(return_value=restored)
    monkeypatch.setattr(
        project_facade,
        "build_project_llm_execution_snapshot",
        build_snapshot,
    )
    monkeypatch.setattr(
        project_facade,
        "restore_project_llm_execution_settings",
        restore_settings,
    )
    db = object()

    result = await _project_settings_for_novel(db, "novel-1")

    assert result is restored
    build_snapshot.assert_awaited_once_with(db, "novel-1")
    restore_settings.assert_awaited_once_with(db, "novel-1", snapshot)
