from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings, get_settings
from modules.account.middleware import _is_demo_read_post, _is_demo_read_request
from modules.account.models import Account
from modules.account.public_demo import PublicDemoConfig, configured_public_demo
from modules.project.models import Project


class _SessionManager:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @asynccontextmanager
    async def session(self):
        yield self._session


@pytest.mark.asyncio
async def test_public_demo_config_and_scoped_viewer_routes(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = Account(status="active", support_code="PUBLIC-DEMO")
    db_session.add(owner)
    await db_session.flush()
    demo = Project(
        owner_id=owner.id,
        title="公开演示",
        language="zh",
        default_reveal_policy="author_safe",
        settings={},
    )
    private = Project(
        owner_id=owner.id,
        title="同 owner 私有项目",
        language="zh",
        default_reveal_policy="author_safe",
        settings={},
    )
    db_session.add_all([demo, private])
    await db_session.flush()

    monkeypatch.setenv("AUTH_MODE", "public")
    monkeypatch.setenv("AUTH_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://test")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://test")
    monkeypatch.setenv("PUBLIC_DEMO_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_DEMO_PROJECT_ID", str(demo.id))
    monkeypatch.setenv("PUBLIC_DEMO_VERSION", "v1")
    monkeypatch.setattr(
        "modules.account.middleware.get_manager",
        lambda: _SessionManager(db_session),
    )
    get_settings.cache_clear()
    try:
        config = await async_client.get("/api/auth/config")
        listing = await async_client.get("/api/projects?demo=1")
        detail = await async_client.get(f"/api/projects/{demo.id}?demo=1")
        cross_project = await async_client.get(f"/api/projects/{private.id}?demo=1")
        account = await async_client.get("/api/account/settings/llm-defaults?demo=1")
        assistant = await async_client.get(
            f"/api/assistant/capabilities?novel_id={demo.id}&demo=1"
        )
        demo_search = await async_client.post(
            "/api/evidence/compilation/evidence/search?demo=1",
            json={"novel_id": str(demo.id), "query": "演示"},
            headers={"Origin": "http://test"},
        )
        cross_search = await async_client.post(
            "/api/evidence/compilation/evidence/search?demo=1",
            json={"novel_id": str(private.id), "query": "私有"},
            headers={"Origin": "http://test"},
        )
        mutated = await async_client.put(
            f"/api/projects/{demo.id}?demo=1",
            json={"title": "不应写入"},
        )

        assert config.json()["demo"] == {
            "enabled": True,
            "project_id": str(demo.id),
            "version": "v1",
            "rp_enabled": False,
        }
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()["items"]] == [str(demo.id)]
        assert detail.status_code == 200
        assert cross_project.status_code == 401
        assert account.status_code == 401
        assert assistant.status_code == 401
        assert demo_search.status_code == 200
        assert cross_search.status_code == 404
        assert mutated.status_code == 401
        assert (await db_session.get(Project, demo.id)).title == "公开演示"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_invalid_demo_configuration_is_not_exposed(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUBLIC_DEMO_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_DEMO_PROJECT_ID", "not-a-uuid")
    monkeypatch.setenv("PUBLIC_DEMO_VERSION", "v1")
    get_settings.cache_clear()
    try:
        response = await async_client.get("/api/auth/config")
        assert response.status_code == 200
        assert response.json()["demo"] == {
            "enabled": False,
            "project_id": None,
            "version": None,
            "rp_enabled": False,
        }
    finally:
        get_settings.cache_clear()


def test_demo_route_policy_covers_path_scoped_core_reads_only() -> None:
    project_id = "9e0a66bc-a836-4b0d-a077-1656baf0ee48"
    config = PublicDemoConfig(
        enabled=True,
        project_id=uuid.UUID(project_id),
        version="v1",
    )
    memory_scope = {
        "query_string": b"demo=1",
    }
    map_scope = {
        "query_string": b"demo=1",
    }
    retrieval_scope = {
        "query_string": f"demo=1&novel_id={project_id}".encode(),
    }
    other_scope = {
        "query_string": b"demo=1",
    }

    assert _is_demo_read_request(
        memory_scope,
        path=f"/api/novels/{project_id}/memories/status",
        method="GET",
        config=config,
    )
    assert _is_demo_read_request(
        map_scope,
        path=f"/api/world/map-atlas/{project_id}/atlas",
        method="GET",
        config=config,
    )
    assert _is_demo_read_request(
        map_scope,
        path=f"/api/world/map-atlas/{project_id}/runs/latest",
        method="GET",
        config=config,
    )
    assert _is_demo_read_post(
        retrieval_scope,
        path="/api/evidence/indexing/retrieve",
        method="POST",
        config=config,
    )
    assert _is_demo_read_post(
        {"query_string": b"demo=1"},
        path="/api/evidence/compilation/evidence/search",
        method="POST",
        config=config,
    )
    assert not _is_demo_read_request(
        other_scope,
        path=f"/api/novels/{project_id}/memories/status",
        method="POST",
        config=config,
    )
    assert not _is_demo_read_request(
        other_scope,
        path="/api/novels/20dc683a-b7f0-40d7-9c65-e08bd02a4304/memories/status",
        method="GET",
        config=config,
    )
    assert not _is_demo_read_request(
        retrieval_scope,
        path="/api/world/cocreation/sessions",
        method="GET",
        config=config,
    )
    for path in (
        "/api/evidence/compilation/retrieval-traces",
        "/api/evidence/compilation/snapshots",
        "/api/world/generation-prompt-templates",
        f"/api/world/map-atlas/{project_id}/pages/page-1/prompt",
    ):
        assert not _is_demo_read_request(
            retrieval_scope,
            path=path,
            method="GET",
            config=config,
        )


def test_rp_entry_requires_a_valid_configured_source_revision() -> None:
    project_id = str(uuid.uuid4())
    base = {
        "public_demo_enabled": True,
        "public_demo_project_id": project_id,
        "public_demo_version": "v1",
        "public_demo_rp_enabled": True,
    }

    assert configured_public_demo(Settings(**base)).rp_enabled is False
    assert (
        configured_public_demo(
            Settings(**base, public_demo_rp_source_revision_id=str(uuid.uuid4()))
        ).rp_enabled
        is True
    )
