"""Real HTTP and independent PostgreSQL sessions for the seven notice sources."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import func, select

from app.main import app
from core.config import Settings
from core.container import container_scope, get
from core.database import (
    assert_database_target_for_testing,
    isolated_database_manager_for_testing,
)
from core.service_keys import ASSISTANT_NOTICE_SOURCES
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID, AccountPrincipal
from modules.account.models import Account
from modules.assistant.notice_models import (
    AssistantNoticeCategoryMute,
    AssistantNoticeDisposition,
)
from modules.assistant.operation_trace_models import AssistantOperationTrace
from modules.project.models import Project
from tests.e2e.config import DATABASE_URL, require_e2e_database_url
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest_asyncio.fixture(autouse=True)
async def isolated_global_database_manager():
    """The API holds one connection while seven sources open their own."""
    url = require_e2e_database_url(DATABASE_URL)
    settings = Settings(database_url=url, pool_size=8, max_overflow=0)
    async with isolated_database_manager_for_testing(settings) as manager:
        assert_database_target_for_testing(url, manager.engine.url)
        yield manager


async def test_unified_notice_http_reads_seven_sources_and_persists_author_actions(
    isolated_global_database_manager,
):
    manager = isolated_global_database_manager
    novel_id = uuid4()
    foreign_owner_id = uuid4()
    created_account = False
    async with manager.session() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="notice-integration"))
            created_account = True
        db.add(Account(id=foreign_owner_id, support_code=uuid4().hex))
        db.add(Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="提醒组合测试"))

    try:
        registry = get(ASSISTANT_NOTICE_SOURCES)
        assert set(registry) == {
            "assistant.proactive",
            "assistant.editorial",
            "assistant.forecast",
            "story.structure",
            "writing.conflict",
            "writing.invalidation",
            "world.map_source",
        }
        async with XhrAsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            draft = await client.post(
                f"/api/writing/drafts?novel_id={novel_id}",
                json={
                    "novel_id": str(novel_id),
                    "chapter_index": 1,
                    "title": "第一章",
                    "content": "合成正文用于真实来源契约核对。",
                },
            )
            assert draft.status_code in {200, 201}, draft.text
            params = {"novel_id": str(novel_id), "chapter_index": 1}
            response = await client.get("/api/assistant/unified-notices", params=params)
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["partial"] is False
            assert body["unavailable_sources"] == []
            conflict = next(
                item for item in body["items"] if item["source_id"] == "writing.conflict"
            )

            async def unavailable(_db, _novel_id, _scope):
                raise RuntimeError("synthetic editorial source outage")

            with container_scope(
                {
                    ASSISTANT_NOTICE_SOURCES: {
                        **registry,
                        "assistant.editorial": replace(
                            registry["assistant.editorial"], list_notices=unavailable
                        ),
                    }
                }
            ):
                partial = await client.get(
                    "/api/assistant/unified-notices", params=params
                )
            assert partial.status_code == 200, partial.text
            assert partial.json()["partial"] is True
            unavailable = partial.json()["unavailable_sources"]
            assert [item["source_id"] for item in unavailable] == ["assistant.editorial"]
            assert any(
                item["notice_key"] == conflict["notice_key"]
                for item in partial.json()["items"]
            )

            payload = {
                "novel_id": str(novel_id),
                "source_id": conflict["source_id"],
                "notice_key": conflict["notice_key"],
                "basis_fingerprint": conflict["basis_fingerprint"],
                "scope": {"chapter_index": 1},
                "expected_row_version": conflict["row_version"],
                "action": "read",
            }
            saved = await client.post(
                "/api/assistant/unified-notices/dispositions", json=payload
            )
            assert saved.status_code == 200, saved.text
            reread = await client.get("/api/assistant/unified-notices", params=params)
            assert reread.status_code == 200, reread.text
            assert any(
                item["notice_key"] == conflict["notice_key"] and item["status"] == "read"
                for item in reread.json()["items"]
            )
            async with manager.session() as db:
                disposition = await db.scalar(
                    select(AssistantNoticeDisposition).where(
                        AssistantNoticeDisposition.novel_id == novel_id,
                        AssistantNoticeDisposition.notice_key == conflict["notice_key"],
                    )
                )
                assert disposition is not None and disposition.status == "read"

            muted = await client.put(
                "/api/assistant/unified-notices/category-mutes/"
                f"{conflict['source_id']}/{conflict['category']}",
                json={"novel_id": str(novel_id), "expected_row_version": 0},
            )
            assert muted.status_code == 200, muted.text
            after_mute = await client.get("/api/assistant/unified-notices", params=params)
            assert after_mute.status_code == 200, after_mute.text
            assert not any(
                item["notice_key"] == conflict["notice_key"]
                for item in after_mute.json()["items"]
            )
            assert any(
                item["source_id"] == conflict["source_id"]
                and item["category"] == conflict["category"]
                for item in after_mute.json()["muted_categories"]
            )

            async with manager.session() as db:
                before = (
                    await db.scalar(
                        select(func.count())
                        .select_from(AssistantNoticeDisposition)
                        .where(AssistantNoticeDisposition.novel_id == novel_id)
                    ),
                    await db.scalar(
                        select(func.count())
                        .select_from(AssistantNoticeCategoryMute)
                        .where(AssistantNoticeCategoryMute.novel_id == novel_id)
                    ),
                    await db.scalar(
                        select(func.count())
                        .select_from(AssistantOperationTrace)
                        .where(AssistantOperationTrace.novel_id == novel_id)
                    ),
                )
            foreign_token = bind_principal(
                AccountPrincipal(
                    account_id=foreign_owner_id,
                    status="active",
                    identity_type="email",
                    support_code="notice-foreign",
                )
            )
            try:
                foreign_read = await client.get(
                    "/api/assistant/unified-notices", params=params
                )
                foreign_write = await client.post(
                    "/api/assistant/unified-notices/dispositions",
                    json={**payload, "expected_row_version": 1},
                )
                assert foreign_read.status_code == 404
                assert foreign_write.status_code == 404
            finally:
                reset_principal(foreign_token)
            demo_token = bind_principal(
                AccountPrincipal(
                    account_id=BOOTSTRAP_ACCOUNT_ID,
                    status="active",
                    identity_type="demo_readonly",
                    support_code="notice-demo",
                    access_scope="demo_readonly",
                    demo_project_id=novel_id,
                )
            )
            try:
                denied = await client.post(
                    "/api/assistant/unified-notices/dispositions",
                    json={**payload, "expected_row_version": 1},
                )
                assert denied.status_code in {403, 404}
            finally:
                reset_principal(demo_token)
            async with manager.session() as db:
                after = (
                    await db.scalar(
                        select(func.count())
                        .select_from(AssistantNoticeDisposition)
                        .where(AssistantNoticeDisposition.novel_id == novel_id)
                    ),
                    await db.scalar(
                        select(func.count())
                        .select_from(AssistantNoticeCategoryMute)
                        .where(AssistantNoticeCategoryMute.novel_id == novel_id)
                    ),
                    await db.scalar(
                        select(func.count())
                        .select_from(AssistantOperationTrace)
                        .where(AssistantOperationTrace.novel_id == novel_id)
                    ),
                )
            assert after == before
    finally:
        async with manager.session() as db:
            project = await db.get(Project, UUID(str(novel_id)))
            if project is not None:
                await db.delete(project)
            foreign_account = await db.get(Account, foreign_owner_id)
            if foreign_account is not None:
                await db.delete(foreign_account)
        if created_account:
            async with manager.session() as db:
                account = await db.get(Account, BOOTSTRAP_ACCOUNT_ID)
                if account is not None:
                    await db.delete(account)
