"""Settings services tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from core.config import get_settings
from modules.account.settings_constants import (
    ACCOUNT_LLM_PROVIDER_TEMPLATES,
    SOURCE_GLOBAL,
    SOURCE_PROJECT,
    SOURCE_SYSTEM,
)
from modules.account.settings_service import SettingsService
from modules.project.facade import list_projects_using_defaults
from modules.project.settings_service import ProjectSettingsService


@pytest.mark.asyncio
async def test_get_global_llm_defaults_missing_returns_none(db_session):
    svc = SettingsService()
    resp = await svc.get_global_llm_defaults(db_session)
    assert resp is None


@pytest.mark.asyncio
async def test_upsert_global_llm_defaults_rejects_api_key(db_session):
    svc = SettingsService()
    with pytest.raises(Exception) as excinfo:
        await svc.upsert_global_llm_defaults(db_session, {"api_key": "sk-leak"})
    assert (
        "api_key" in str(excinfo.value).lower() or "extra" in str(excinfo.value).lower()
    )


@pytest.mark.asyncio
async def test_legacy_global_defaults_cannot_bypass_account_connection_entry(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("AUTH_MODE", "public")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="账户模型连接入口"):
            await SettingsService().upsert_global_llm_defaults(
                db_session,
                {"base_url": "http://127.0.0.1:9000/v1"},
            )
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_global_author_prefs_system_fallback_when_missing(db_session):
    svc = SettingsService()
    resp = await svc.get_or_system_author_prefs(db_session)
    assert resp.daily_goal is None  # unset
    assert resp.editor_font == "system"
    assert resp.default_focus_mode is False


@pytest.mark.asyncio
async def test_get_effective_author_prefs_layering(db_session, factory):
    account = SettingsService()
    svc = ProjectSettingsService()
    pid = await factory.create_project()
    # 无任何配置 → 全 system
    resp = await svc.get_effective_author_prefs(db_session, pid)
    assert resp.daily_goal.source == SOURCE_SYSTEM
    assert resp.editor_font.source == SOURCE_SYSTEM
    assert resp.default_focus_mode.source == SOURCE_SYSTEM
    assert resp.editor_font.value == "system"
    # 设全局 → 全 global
    await account.upsert_global_author_prefs(
        db_session,
        {
            "daily_goal": 8000,
            "editor_font": "mono",
            "default_focus_mode": True,
        },
    )
    resp = await svc.get_effective_author_prefs(db_session, pid)
    assert all(
        f.source == SOURCE_GLOBAL
        for f in (resp.daily_goal, resp.editor_font, resp.default_focus_mode)
    )
    assert resp.daily_goal.value == 8000
    # 项目覆盖 daily_goal → 字段级 source 区分
    await svc.upsert_project_author_prefs(db_session, pid, {"daily_goal": 4000})
    resp = await svc.get_effective_author_prefs(db_session, pid)
    assert resp.daily_goal.source == SOURCE_PROJECT
    assert resp.daily_goal.value == 4000
    assert resp.editor_font.source == SOURCE_GLOBAL
    # reset 字段回 global
    await svc.reset_project_author_prefs_field(db_session, pid, "daily_goal")
    resp = await svc.get_effective_author_prefs(db_session, pid)
    assert resp.daily_goal.source == SOURCE_GLOBAL
    assert resp.daily_goal.value == 8000


@pytest.mark.asyncio
async def test_effective_llm_settings_ignore_legacy_project_connection_fields(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("ENABLE_ACCOUNT_KIMI_K3", "1")
    account = SettingsService()
    svc = ProjectSettingsService()
    with patch(
        "modules.account.settings_service._validate_account_llm_connection",
        autospec=True,
    ):
        await account.connect_account_llm_provider(
            db_session,
            "kimi",
            "test-account-key",
        )

    resp = await svc.get_effective_llm_settings(
        db_session,
        {
            "llm": {
                "model": "project-model",
                "api_key": "sk-secret",
            },
            "deep_import": {"global": {"structured_max_fix_attempts": 7}},
        },
    )

    assert resp.provider_id.source == SOURCE_GLOBAL
    assert resp.provider_id.value == "kimi"
    assert resp.model.source == SOURCE_GLOBAL
    assert resp.model.value == "kimi-k3"
    assert resp.max_tokens.source == SOURCE_GLOBAL
    assert resp.max_tokens.value == 12_000
    assert resp.top_p.source == SOURCE_GLOBAL
    assert resp.top_p.value is None
    assert resp.api_key_configured.source != SOURCE_PROJECT
    assert resp.api_key_configured.value is True
    assert resp.deep_import.source == SOURCE_PROJECT
    assert resp.deep_import.value["global"]["structured_max_fix_attempts"] == 7


@pytest.mark.asyncio
async def test_reset_field_rejects_unknown_field(db_session, factory):
    svc = ProjectSettingsService()
    pid = await factory.create_project()
    with pytest.raises(ValueError):
        await svc.reset_project_author_prefs_field(db_session, pid, "malicious_field")


@pytest.mark.asyncio
async def test_projects_using_defaults_aggregation(db_session, factory):
    svc = ProjectSettingsService()
    p_partial = await factory.create_project(title="partial-override")
    await factory.create_project(title="missing-prefs")
    await svc.upsert_project_author_prefs(db_session, p_partial, {"daily_goal": 1000})

    # p_partial 仅设了 daily_goal；editor_font 和 default_focus_mode 仍 NULL → 仍在列表
    # missing-prefs 全 NULL（行不存在）→ 也在列表
    # D18: 任一字段 NULL 或行不存在即视为继承默认
    resp = await list_projects_using_defaults(db_session)
    titles = [item.title for item in resp.items]
    assert "missing-prefs" in titles
    assert "partial-override" in titles


@pytest.mark.asyncio
async def test_projects_using_defaults_excludes_fully_overridden(db_session, factory):
    """完全覆盖三个字段的项目不应在继承列表中。"""
    svc = ProjectSettingsService()
    pid = await factory.create_project(title="fully-own")
    await svc.upsert_project_author_prefs(
        db_session,
        pid,
        {
            "daily_goal": 1000,
            "editor_font": "serif",
            "default_focus_mode": True,
        },
    )
    resp = await list_projects_using_defaults(db_session)
    titles = [item.title for item in resp.items]
    assert "fully-own" not in titles


@pytest.mark.asyncio
async def test_fully_overridden_project_ids_are_database_subquery(
    db_session,
    factory,
):
    svc = ProjectSettingsService()
    project_id = await factory.create_project(title="fully-own-contract")
    other_project_id = await factory.create_project(title="outside-contract-scope")
    await svc.upsert_project_author_prefs(
        db_session,
        project_id,
        {
            "daily_goal": 1000,
            "editor_font": "serif",
            "default_focus_mode": True,
        },
    )
    await svc.upsert_project_author_prefs(
        db_session,
        other_project_id,
        {
            "daily_goal": 2000,
            "editor_font": "mono",
            "default_focus_mode": False,
        },
    )

    result = await db_session.execute(svc.fully_overridden_project_ids_subquery())
    assert set(result.scalars()) == {project_id, other_project_id}


@pytest.mark.asyncio
async def test_projects_using_defaults_paginates_in_project_sort_order(
    db_session,
    factory,
):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await factory.create_project(title="old", created_at=base)
    await factory.create_project(title="middle", created_at=base + timedelta(days=1))
    await factory.create_project(title="new", created_at=base + timedelta(days=2))

    resp = await list_projects_using_defaults(db_session, limit=1, offset=1)

    assert resp.total == 3
    assert [item.title for item in resp.items] == ["middle"]


@pytest.mark.asyncio
async def test_projects_using_defaults_excludes_soft_deleted_projects(
    db_session,
    factory,
):
    await factory.create_project(title="active")
    await factory.create_project(title="deleted", deleted_at=datetime.now(UTC))

    resp = await list_projects_using_defaults(db_session)

    titles = [item.title for item in resp.items]
    assert "active" in titles
    assert "deleted" not in titles
    assert resp.total == 1


@pytest.mark.asyncio
async def test_projects_using_defaults_total_and_truncated_over_100(
    db_session,
    factory,
):
    for i in range(101):
        await factory.create_project(title=f"inheriting-{i:03d}")

    resp = await list_projects_using_defaults(db_session, limit=5)

    assert resp.total == 101
    assert len(resp.items) == 5
    assert resp.truncated is True


@pytest.mark.asyncio
async def test_global_llm_tuning_defaults_apply_to_runtime_profile(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("ENABLE_ACCOUNT_KIMI_K3", "1")
    svc = SettingsService()
    with patch(
        "modules.account.settings_service._validate_account_llm_connection",
        autospec=True,
    ):
        await svc.connect_account_llm_provider(
            db_session,
            "kimi",
            "test-account-key",
        )

    # 用户唯一能写的全局默认字段必须真正进入运行 profile
    await svc.upsert_global_llm_defaults(
        db_session,
        {"timeout": 300, "temperature": 0.3, "max_tokens": 8000},
    )

    profile = await svc.resolve_account_llm_runtime_profile(db_session)

    template = ACCOUNT_LLM_PROVIDER_TEMPLATES["kimi"]
    assert profile.provider_id == "kimi"
    assert profile.timeout == 300
    assert profile.temperature == 0.3
    assert profile.max_tokens == 8000
    # 未设置的字段保持模板值
    assert profile.model == template["model"]
    assert profile.base_url == template["base_url"]


@pytest.mark.asyncio
async def test_effective_llm_settings_return_user_saved_global_values(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("ENABLE_ACCOUNT_KIMI_K3", "1")
    account = SettingsService()
    svc = ProjectSettingsService()
    with patch(
        "modules.account.settings_service._validate_account_llm_connection",
        autospec=True,
    ):
        await account.connect_account_llm_provider(
            db_session,
            "kimi",
            "test-account-key",
        )
    await account.upsert_global_llm_defaults(db_session, {"timeout": 456})

    resp = await svc.get_effective_llm_settings(db_session, None)

    assert resp.timeout.source == SOURCE_GLOBAL
    assert resp.timeout.value == 456
