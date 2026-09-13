from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings, get_settings
from modules.account.constants import SESSION_COOKIE_NAME
from modules.account.middleware import (
    _is_demo_read_post,
    _is_demo_read_request,
    _session_cookie_name,
    _session_token,
)
from modules.account.models import Account
from modules.account.public_demo import PublicDemoConfig, configured_public_demo
from modules.project.models import Project
from modules.writing.models import WritingDraft


class _SessionManager:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @asynccontextmanager
    async def session(self):
        yield self._session


def test_demo_rp_cookie_is_selected_only_for_explicit_interaction_requests() -> None:
    assert (
        _session_cookie_name(
            "/api/interactions/demo-journeys",
            {"x-demo-rp-session": "1"},
        )
        == "aaw_demo_rp_session"
    )
    assert _session_cookie_name("/api/interactions/demo-journeys", {}) == "aaw_session"
    assert (
        _session_cookie_name("/api/projects", {"x-demo-rp-session": "1"}) == "aaw_session"
    )
    assert _session_token(
        "/api/interactions/demo-journeys",
        {
            "x-demo-rp-session": "1",
            "cookie": "aaw_session=legacy; aaw_demo_rp_session=isolated",
        },
    ) == ("isolated", False)
    assert _session_token(
        "/api/interactions/demo-journeys",
        {"x-demo-rp-session": "1", "cookie": "aaw_session=legacy"},
    ) == ("legacy", True)


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
    published = WritingDraft(
        novel_id=demo.id,
        chapter_index=1,
        title="已发布章节",
        content="公开正文",
        content_hash="a" * 64,
        version_number=1,
        status="published",
        conflict_check_snapshot_json={"summary": "作者诊断"},
        provenance_json={"pov_view": {"withheld_known_information": ["隐藏真相"]}},
    )
    unpublished = WritingDraft(
        novel_id=demo.id,
        chapter_index=1,
        title="未发布修改",
        content="不得公开",
        content_hash="b" * 64,
        version_number=2,
        status="draft",
    )
    draft_only = WritingDraft(
        novel_id=demo.id,
        chapter_index=2,
        title="未发布章节",
        content="不得公开",
        content_hash="c" * 64,
        version_number=1,
        status="draft",
    )
    db_session.add_all([published, unpublished, draft_only])
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
        workspace_summary = await async_client.get(
            f"/api/projects/{demo.id}/workspace-summary?demo=1"
        )
        detail_with_stale_cookie = await async_client.get(
            f"/api/projects/{demo.id}?demo=1",
            headers={"Cookie": f"{SESSION_COOKIE_NAME}=stale-session"},
        )
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
        chapters = await async_client.get(
            f"/api/writing/chapters?novel_id={demo.id}&demo=1"
        )
        latest = await async_client.get(
            f"/api/writing/chapters/1/draft?novel_id={demo.id}&demo=1"
        )
        versions = await async_client.get(
            f"/api/writing/chapters/1/versions?novel_id={demo.id}&demo=1"
        )
        hidden_draft = await async_client.get(
            f"/api/writing/drafts/{unpublished.id}?novel_id={demo.id}&demo=1"
        )
        regeneration = await async_client.get(
            f"/api/writing/drafts/{published.id}/regeneration-context"
            f"?novel_id={demo.id}&demo=1"
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
        assert workspace_summary.status_code == 401
        assert detail_with_stale_cookie.status_code == 200
        assert cross_project.status_code == 401
        assert account.status_code == 401
        assert assistant.status_code == 401
        assert demo_search.status_code == 200
        assert cross_search.status_code == 404
        assert mutated.status_code == 401
        assert chapters.json() == {
            "chapters": [
                {
                    "chapter_index": 1,
                    "title": "已发布章节",
                    "word_count": 4,
                }
            ]
        }
        assert latest.json() == {
            "chapter_index": 1,
            "title": "已发布章节",
            "content": "公开正文",
        }
        assert versions.status_code == 401
        assert hidden_draft.status_code == 401
        assert regeneration.status_code == 401
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
