"""Settings services tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from modules.settings.constants import (
    SOURCE_GLOBAL,
    SOURCE_PROJECT,
    SOURCE_SYSTEM,
)
from modules.settings.facade import list_projects_using_defaults
from modules.settings.services import SettingsService


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
async def test_global_author_prefs_system_fallback_when_missing(db_session):
    svc = SettingsService()
    resp = await svc.get_or_system_author_prefs(db_session)
    assert resp.daily_goal is None  # unset
    assert resp.editor_font == "system"
    assert resp.default_focus_mode is False


@pytest.mark.asyncio
async def test_get_effective_author_prefs_layering(db_session, factory):
    svc = SettingsService()
    pid = await factory.create_project()
    # 无任何配置 → 全 system
    resp = await svc.get_effective_author_prefs(db_session, pid)
    assert resp.daily_goal.source == SOURCE_SYSTEM
    assert resp.editor_font.source == SOURCE_SYSTEM
    assert resp.default_focus_mode.source == SOURCE_SYSTEM
    assert resp.editor_font.value == "system"
    # 设全局 → 全 global
    await svc.upsert_global_author_prefs(
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
async def test_get_effective_llm_settings_for_raw_project_settings_layers_values(
    db_session,
):
    svc = SettingsService()
    await svc.upsert_global_llm_defaults(
        db_session,
        {
            "provider_id": "kimi",
            "base_url": "https://api.moonshot.cn/v1",
            "model": "kimi-k2.6",
            "top_p": 0.7,
        },
    )

    resp = await svc.get_effective_llm_settings_for_project_settings(
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
    assert resp.model.source == SOURCE_PROJECT
    assert resp.model.value == "project-model"
    assert resp.top_p.source == SOURCE_GLOBAL
    assert resp.top_p.value == 0.7
    assert resp.api_key_configured.source == SOURCE_PROJECT
    assert resp.api_key_configured.value is True
    assert resp.deep_import.source == SOURCE_PROJECT
    assert resp.deep_import.value["global"]["structured_max_fix_attempts"] == 7


@pytest.mark.asyncio
async def test_materialize_effective_project_settings_keeps_project_api_key(
    db_session,
):
    svc = SettingsService()
    await svc.upsert_global_llm_defaults(
        db_session,
        {
            "provider_id": "kimi",
            "base_url": "https://api.moonshot.cn/v1",
            "model": "kimi-k2.6",
        },
    )

    settings = await svc.materialize_effective_project_settings(
        db_session,
        {"llm": {"api_key": "sk-secret"}},
    )

    assert settings["llm"]["provider_id"] == "kimi"
    assert settings["llm"]["base_url"] == "https://api.moonshot.cn/v1"
    assert settings["llm"]["model"] == "kimi-k2.6"
    assert settings["llm"]["api_key"] == "sk-secret"
    assert "deep_import" not in settings["llm"]


@pytest.mark.asyncio
async def test_reset_field_rejects_unknown_field(db_session, factory):
    svc = SettingsService()
    pid = await factory.create_project()
    with pytest.raises(ValueError):
        await svc.reset_project_author_prefs_field(db_session, pid, "malicious_field")


@pytest.mark.asyncio
async def test_projects_using_defaults_aggregation(db_session, factory):
    svc = SettingsService()
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
    svc = SettingsService()
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
