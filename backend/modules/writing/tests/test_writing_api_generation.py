"""
Writing 模块测试

测试草稿 CRUD、版本管理、facade 和边界情况。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.schemas import LLMCallResponse
from infrastructure.tasks.models import AsyncTask
from modules.outline.repositories import SceneRepository
from modules.outline.schemas import SceneCreate
from modules.writing.facade import (
    create_draft,
)
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import (
    WritingDraftCreate,
    WritingDraftUpdate,
)
from modules.writing.services import WritingDraftService


@pytest.fixture
def repo() -> WritingDraftRepository:
    return WritingDraftRepository()


@pytest.fixture
def service() -> WritingDraftService:
    return WritingDraftService()


@pytest.fixture
def sample_draft_data() -> WritingDraftCreate:
    return WritingDraftCreate(
        novel_id=str(uuid.uuid4()),
        chapter_index=1,
        title="第一章：开端",
        content="这是一个测试正文的段落。",
    )


@pytest.fixture
def update_data() -> WritingDraftUpdate:
    return WritingDraftUpdate(
        title="更新后的标题",
        content="更新后的正文内容。",
    )


class FakeLLMClient:
    async def generate(self, request):
        return LLMCallResponse(content="这是 AI 生成的候选正文。")

    async def close(self) -> None:
        return None


class FakePovLLMClient:
    model_name = "fake-pov-model"

    def __init__(self, content: str) -> None:
        self.content = content
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return LLMCallResponse(content=self.content, model=self.model_name)


def _fake_confirmed_context(
    *,
    action="writing.generate",
    status="confirmed",
    stale=None,
    options=None,
):
    return SimpleNamespace(
        confirmation=SimpleNamespace(
            action=action,
            result_status=status,
            stale_reasons=stale or [],
        ),
        compile_options=options or {},
    )


def _make_draft(**overrides: object) -> MagicMock:
    draft = MagicMock()
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "novel_id": uuid.uuid4(),
        "chapter_index": 1,
        "title": "第一章：开端",
        "content": "这是一个测试正文的段落。",
        "content_hash": "0" * 64,
        "version_number": 1,
        "status": "draft",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        setattr(draft, key, value)
    return draft


async def _create_api_project(async_client: AsyncClient) -> str:
    response = await async_client.post(
        "/api/projects",
        json={"title": "Writing API test project"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestWritingPublishApi:
    @pytest.mark.asyncio
    async def test_repeated_delete_is_204_and_keeps_original_provenance(
        self,
        async_client: AsyncClient,
    ) -> None:
        novel_id = await _create_api_project(async_client)
        published = (
            await async_client.post(
                "/api/writing/drafts",
                json={"novel_id": novel_id, "chapter_index": 1, "content": "v1"},
            )
        ).json()["draft"]
        working = (
            await async_client.put(
                f"/api/writing/drafts/{published['id']}?novel_id={novel_id}",
                json={"content": "v2"},
            )
        ).json()

        first = await async_client.delete(
            f"/api/writing/drafts/{published['id']}?novel_id={novel_id}"
        )
        second = await async_client.delete(
            f"/api/writing/drafts/{published['id']}?novel_id={novel_id}"
        )

        assert first.status_code == 204
        assert second.status_code == 204
        history = (
            await async_client.get(
                f"/api/writing/chapters/1/versions?novel_id={novel_id}"
            )
        ).json()
        assert history["total"] == 2
        archived = next(
            item for item in history["versions"] if item["id"] == published["id"]
        )
        assert archived["deprecated_from_status"] == "published"
        assert archived["display_state"] == "archived"
        assert history["versions"][0]["id"] == working["id"]

    @pytest.mark.asyncio
    async def test_autosave_update_and_publish_sanitize_html(
        self,
        async_client: AsyncClient,
    ) -> None:
        novel_id = await _create_api_project(async_client)

        autosave = await async_client.post(
            "/api/writing/drafts/autosave",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "title": "<b>草稿</b>",
                "content": "A < B<script>alert(1)</script>正文<b>加粗</b>",
            },
        )
        assert autosave.status_code == 201
        saved = autosave.json()
        assert saved["title"] == "草稿"
        assert saved["content"] == "A < B正文加粗"

        updated = await async_client.put(
            f"/api/writing/drafts/{saved['id']}?novel_id={novel_id}",
            json={
                "title": "<i>暂存</i>",
                "content": "普通 A < B<style>.x{}</style>正文<u>下划线</u>",
            },
        )
        assert updated.status_code == 200
        updated_data = updated.json()
        assert updated_data["title"] == "暂存"
        assert updated_data["content"] == "普通 A < B正文下划线"

        published = await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "title": "<b>发布</b>",
                "content": "正文<script>alert(1)</script><b>加粗</b>",
            },
        )
        assert published.status_code == 201
        published_draft = published.json()["draft"]
        assert published_draft["title"] == "发布"
        assert published_draft["content"] == "正文加粗"
        assert "<script>" not in published_draft["content"]
        assert "<b>" not in published_draft["content"]

    @pytest.mark.asyncio
    async def test_publish_draft_increments_version_and_enqueues_task(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """POST /api/writing/drafts 发布时递增版本并入队任务"""
        novel_id = await _create_api_project(async_client)

        response1 = await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "title": "第一章",
                "content": "第一版内容",
            },
        )
        assert response1.status_code == 201
        data1 = response1.json()
        assert data1["draft"]["version_number"] == 1
        assert data1["draft"]["status"] == "published"
        task_id_1 = data1["task_id"]
        assert task_id_1 is not None

        response2 = await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "title": "第一章（修订）",
                "content": "第二版内容",
            },
        )
        assert response2.status_code == 201
        data2 = response2.json()
        assert data2["draft"]["version_number"] == 2
        assert data2["draft"]["status"] == "published"
        task_id_2 = data2["task_id"]
        assert task_id_2 is not None
        assert task_id_2 != task_id_1

        task = await db_session.get(AsyncTask, uuid.UUID(hex=task_id_2))
        assert task is not None
        assert task.task_type == "publish_chapter"
        assert task.meta.get("novel_id") == novel_id
        assert task.meta.get("chapter_index") == 1

        response3 = await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "title": "第一章（修订）",
                "content": "第二版内容",
            },
        )
        assert response3.status_code == 201
        data3 = response3.json()
        assert data3["draft"]["id"] == data2["draft"]["id"]
        assert data3["draft"]["version_number"] == 2
        assert data3["draft"]["status"] == "published"
        assert data3["task_id"] is None
        assert data3["new_version"] is False

        service = WritingDraftService()
        history = await service.get_version_history(db_session, novel_id, 1)
        assert history.total == 2

    @pytest.mark.asyncio
    async def test_autosave_ignores_whitespace_only_change_to_published(
        self,
        async_client: AsyncClient,
    ) -> None:
        novel_id = await _create_api_project(async_client)
        published = (
            await async_client.post(
                "/api/writing/drafts",
                json={
                    "novel_id": novel_id,
                    "chapter_index": 1,
                    "title": "第一章",
                    "content": "甲\n乙",
                },
            )
        ).json()["draft"]

        response = await async_client.put(
            f"/api/writing/drafts/{published['id']}?novel_id={novel_id}",
            json={
                "title": "标题也不触发版本",
                "content": " \u3000甲\t\n\n乙 ",
                "expected_version": 1,
                "expected_updated_at": published["updated_at"],
            },
        )

        assert response.status_code == 200
        assert response.json()["id"] == published["id"]
        history = await async_client.get(
            f"/api/writing/chapters/1/versions?novel_id={novel_id}"
        )
        assert history.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_auto_working_version_can_revert_to_published_baseline(
        self,
        async_client: AsyncClient,
    ) -> None:
        novel_id = await _create_api_project(async_client)
        published = (
            await async_client.post(
                "/api/writing/drafts",
                json={"novel_id": novel_id, "chapter_index": 1, "content": "旧正文"},
            )
        ).json()["draft"]
        changed = (
            await async_client.put(
                f"/api/writing/drafts/{published['id']}?novel_id={novel_id}",
                json={
                    "content": "新正文",
                    "expected_version": 1,
                    "expected_updated_at": published["updated_at"],
                },
            )
        ).json()
        assert changed["version_number"] == 2
        assert changed["provenance_json"]["version_origin"] == "auto"

        reverted = await async_client.put(
            f"/api/writing/drafts/{changed['id']}?novel_id={novel_id}",
            json={
                "content": " 旧 \n 正文 ",
                "expected_version": 2,
                "expected_updated_at": changed["updated_at"],
            },
        )
        assert reverted.status_code == 200
        assert reverted.json()["id"] == published["id"]
        history = await async_client.get(
            f"/api/writing/chapters/1/versions?novel_id={novel_id}"
        )
        assert [item["version_number"] for item in history.json()["versions"]] == [2, 1]
        assert history.json()["versions"][0]["display_state"] == "archived"
        assert history.json()["versions"][0]["deprecated_from_status"] == "draft"

    @pytest.mark.asyncio
    async def test_checkpoint_and_publish_promote_without_extra_version(
        self,
        async_client: AsyncClient,
    ) -> None:
        novel_id = await _create_api_project(async_client)
        published = (
            await async_client.post(
                "/api/writing/drafts",
                json={"novel_id": novel_id, "chapter_index": 1, "content": "v1"},
            )
        ).json()["draft"]
        working = (
            await async_client.put(
                f"/api/writing/drafts/{published['id']}?novel_id={novel_id}",
                json={"content": "v2", "expected_version": 1},
            )
        ).json()
        checkpoint = await async_client.post(
            f"/api/writing/drafts/{working['id']}/checkpoint?novel_id={novel_id}",
            json={"content": "v2", "expected_version": 2},
        )
        assert checkpoint.status_code == 200
        assert checkpoint.json()["id"] == working["id"]
        assert checkpoint.json()["provenance_json"]["version_origin"] == "manual"

        published_v2 = await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "content": "v2",
                "draft_id": working["id"],
                "expected_version": 2,
            },
        )
        assert published_v2.status_code == 201
        assert published_v2.json()["draft"]["id"] == working["id"]
        assert published_v2.json()["draft"]["version_number"] == 2
        assert published_v2.json()["draft"]["status"] == "published"
        assert published_v2.json()["task_id"] is not None

    @pytest.mark.asyncio
    async def test_publish_reverted_auto_promotes_manual_baseline(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        novel_id = await _create_api_project(async_client)
        published = (
            await async_client.post(
                "/api/writing/drafts",
                json={"novel_id": novel_id, "chapter_index": 1, "content": "v1"},
            )
        ).json()["draft"]
        auto_v2 = (
            await async_client.put(
                f"/api/writing/drafts/{published['id']}?novel_id={novel_id}",
                json={"content": "v2", "expected_version": 1},
            )
        ).json()
        manual_v2 = (
            await async_client.post(
                f"/api/writing/drafts/{auto_v2['id']}/checkpoint?novel_id={novel_id}",
                json={"content": "v2", "expected_version": 2},
            )
        ).json()
        auto_v3 = (
            await async_client.put(
                f"/api/writing/drafts/{manual_v2['id']}?novel_id={novel_id}",
                json={"content": "v3", "expected_version": 2},
            )
        ).json()
        tasks_before = list((await db_session.execute(select(AsyncTask))).scalars())

        response = await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "content": "v2",
                "draft_id": auto_v3["id"],
                "expected_version": 3,
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["new_version"] is True
        assert body["task_id"] is not None
        assert body["draft"]["id"] == manual_v2["id"]
        assert body["draft"]["version_number"] == 2
        assert body["draft"]["status"] == "published"
        assert body["draft"]["content"] == "v2"
        assert body["draft"]["content_hash"] == manual_v2["content_hash"]
        tasks_after = list((await db_session.execute(select(AsyncTask))).scalars())
        assert len(tasks_after) == len(tasks_before) + 1
        discarded = await WritingDraftRepository().get(
            db_session, uuid.UUID(auto_v3["id"])
        )
        assert discarded is not None
        assert discarded.status == "deprecated"
        history = await async_client.get(
            f"/api/writing/chapters/1/versions?novel_id={novel_id}"
        )
        assert [item["version_number"] for item in history.json()["versions"]] == [
            3,
            2,
            1,
        ]
        assert history.json()["versions"][0]["display_state"] == "archived"

    @pytest.mark.asyncio
    async def test_restore_version_validates_latest_snapshot(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        novel_id = await _create_api_project(async_client)
        v1_response = await async_client.post(
            "/api/writing/drafts",
            json={"novel_id": novel_id, "chapter_index": 1, "content": "v1"},
        )
        v1 = v1_response.json()["draft"]
        v2_response = await async_client.post(
            "/api/writing/drafts",
            json={"novel_id": novel_id, "chapter_index": 1, "content": "v2"},
        )
        v2 = v2_response.json()["draft"]

        restored = await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "content": "基于 v1 恢复",
                "draft_id": v1["id"],
                "restore_source_version": 1,
                "expected_version": 2,
                "expected_updated_at": v2["updated_at"],
            },
        )

        assert restored.status_code == 201
        assert restored.json()["draft"]["version_number"] == 3
        assert restored.json()["draft"]["provenance_json"]["restored_from_version"] == 1

        stale_snapshot = restored.json()["draft"]
        newest = (
            await async_client.post(
                "/api/writing/drafts",
                json={"novel_id": novel_id, "chapter_index": 1, "content": "v4"},
            )
        ).json()["draft"]
        tasks_before = list((await db_session.execute(select(AsyncTask))).scalars())

        stale_restore = await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "content": "过期恢复",
                "draft_id": v1["id"],
                "restore_source_version": 1,
                "expected_version": stale_snapshot["version_number"],
                "expected_updated_at": stale_snapshot["updated_at"],
            },
        )

        assert stale_restore.status_code == 409
        history = await async_client.get(
            f"/api/writing/chapters/1/versions?novel_id={novel_id}"
        )
        assert history.json()["versions"][0]["id"] == newest["id"]
        tasks_after = list((await db_session.execute(select(AsyncTask))).scalars())
        assert len(tasks_after) == len(tasks_before)

    @pytest.mark.asyncio
    async def test_restore_version_rejects_in_place_latest_update(
        self,
        async_client: AsyncClient,
    ) -> None:
        novel_id = await _create_api_project(async_client)
        v1 = (
            await async_client.post(
                "/api/writing/drafts",
                json={"novel_id": novel_id, "chapter_index": 1, "content": "v1"},
            )
        ).json()["draft"]
        auto_v2 = (
            await async_client.put(
                f"/api/writing/drafts/{v1['id']}?novel_id={novel_id}",
                json={"content": "v2", "expected_version": 1},
            )
        ).json()
        snapshot_updated_at = auto_v2["updated_at"]
        updated_v2 = await async_client.put(
            f"/api/writing/drafts/{auto_v2['id']}?novel_id={novel_id}",
            json={
                "content": "v2 再次修改",
                "expected_version": 2,
                "expected_updated_at": snapshot_updated_at,
            },
        )
        assert updated_v2.status_code == 200
        assert updated_v2.json()["version_number"] == 2

        stale_restore = await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "content": "过期恢复",
                "draft_id": v1["id"],
                "restore_source_version": 1,
                "expected_version": 2,
                "expected_updated_at": snapshot_updated_at,
            },
        )

        assert stale_restore.status_code == 409

    @pytest.mark.asyncio
    async def test_force_checkpoint_and_explicit_discard(
        self,
        async_client: AsyncClient,
    ) -> None:
        novel_id = await _create_api_project(async_client)
        published = (
            await async_client.post(
                "/api/writing/drafts",
                json={"novel_id": novel_id, "chapter_index": 1, "content": "相同"},
            )
        ).json()["draft"]
        checkpoint = await async_client.post(
            f"/api/writing/drafts/{published['id']}/checkpoint?novel_id={novel_id}",
            json={"content": " \u76f8 \n同 ", "expected_version": 1, "force": True},
        )
        assert checkpoint.status_code == 200
        saved = checkpoint.json()
        assert saved["version_number"] == 2
        assert saved["provenance_json"]["version_origin"] == "manual"

        discarded = await async_client.post(
            f"/api/writing/drafts/{saved['id']}/discard",
            params={"novel_id": novel_id, "expected_version": 2},
        )
        assert discarded.status_code == 200
        assert discarded.json()["id"] == published["id"]

    @pytest.mark.asyncio
    async def test_checkpoint_and_discard_are_novel_scoped(
        self,
        async_client: AsyncClient,
    ) -> None:
        novel_id = await _create_api_project(async_client)
        other_novel_id = await _create_api_project(async_client)
        published = (
            await async_client.post(
                "/api/writing/drafts",
                json={"novel_id": novel_id, "chapter_index": 1, "content": "v1"},
            )
        ).json()["draft"]
        denied_checkpoint = await async_client.post(
            f"/api/writing/drafts/{published['id']}/checkpoint",
            params={"novel_id": other_novel_id},
            json={"content": "v2", "force": True},
        )
        assert denied_checkpoint.status_code == 404

        working = (
            await async_client.put(
                f"/api/writing/drafts/{published['id']}?novel_id={novel_id}",
                json={"content": "v2", "expected_version": 1},
            )
        ).json()
        denied_discard = await async_client.post(
            f"/api/writing/drafts/{working['id']}/discard",
            params={"novel_id": other_novel_id, "expected_version": 2},
        )
        assert denied_discard.status_code == 404

    @pytest.mark.asyncio
    async def test_update_old_draft_conflict_returns_409_without_expectation(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """PUT /api/writing/drafts 无条件拒绝旧 working 版本。"""
        novel_id = await _create_api_project(async_client)
        service = WritingDraftService()

        v1 = await service.create_draft(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=1,
                title="第一章",
                content="第一版",
            ),
        )
        await service.create_draft(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=1,
                title="第一章",
                content="第二版",
            ),
        )

        response = await async_client.put(
            f"/api/writing/drafts/{v1.id}?novel_id={novel_id}",
            json={"title": "conflict"},
        )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "v2" in detail or "2" in detail

    @pytest.mark.asyncio
    @pytest.mark.parametrize("historical_status", ["candidate", "deprecated"])
    async def test_update_read_only_history_returns_409_without_expectation(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        historical_status: str,
    ) -> None:
        novel_id = await _create_api_project(async_client)
        repo = WritingDraftRepository()
        historical = await repo.create_with_status(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=1,
                content="只读历史",
            ),
            status=historical_status,
        )
        await repo.create_with_status(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=1,
                content="当前工作稿",
            ),
            status="draft",
        )

        response = await async_client.put(
            f"/api/writing/drafts/{historical.id}?novel_id={novel_id}",
            json={"content": "不应写入"},
        )

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_restore_rejects_archived_source(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        novel_id = await _create_api_project(async_client)
        repo = WritingDraftRepository()
        archived = await repo.create_with_status(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=1,
                content="已归档",
            ),
            status="deprecated",
        )
        latest = await repo.create_with_status(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=1,
                content="当前稿",
            ),
            status="draft",
        )

        response = await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "content": archived.content,
                "draft_id": str(archived.id),
                "restore_source_version": archived.version_number,
                "expected_version": latest.version_number,
            },
        )

        assert response.status_code == 409


@pytest.mark.asyncio
async def test_writing_generation_creates_candidate_without_publish_task(
    db_session: AsyncSession,
) -> None:
    """AI 正文生成只创建 candidate 草稿，不自动发布/RAG。"""
    from modules.evidence.facade import confirm_context
    from modules.writing.services import WritingGenerationService

    novel_id = "00000000-0000-0000-0000-00000000a201"
    confirmation = await confirm_context(
        db_session,
        novel_id=novel_id,
        action="writing.generate",
        task="生成第 3 章候选正文",
        scope="chapter",
        chapter_index=3,
    )
    service = WritingGenerationService(llm_client=FakeLLMClient())

    draft = await service.generate_candidate(
        db_session,
        novel_id=novel_id,
        chapter_index=3,
        title=None,
        instruction="压低信息密度",
        context_confirmation_id=confirmation.id,
    )

    assert draft.status == "candidate"
    assert draft.display_state == "review"
    assert draft.source == "ai_generated"
    assert draft.chapter_index == 3
    assert draft.title == "第3章 正文建议"
    assert "候选" not in draft.title
    assert draft.content == "这是 AI 生成的候选正文。"
    expected = {
        "source": "writing_generate",
        "source_confirmation_id": confirmation.id,
        "source_task_id": None,
        "context_action": "writing.generate",
        "context_result_refs": confirmation.result_refs,
    }
    for key, value in expected.items():
        assert draft.provenance_json[key] == value
    assert draft.provenance_json["generation_profile"] == "default"
    assert draft.provenance_json["pov_validation"]["status"] == "not_applicable"

    tasks_result = await db_session.execute(select(AsyncTask))
    assert tasks_result.scalars().all() == []


@pytest.mark.asyncio
async def test_default_writing_prompt_keeps_scene_as_chapter_context(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.evidence import facade as context_facade
    from modules.writing.services import WritingGenerationService

    novel_id = "00000000-0000-0000-0000-00000000a212"
    confirmed = SimpleNamespace(
        confirmation=SimpleNamespace(
            action="writing.generate",
            result_status="confirmed",
            stale_reasons=[],
        ),
        compile_options={
            "scene_id": "scene-current",
            "reveal_mode": "author_safe",
        },
        rendered_markdown=(
            "## 当前 Scene\n目标：取回密钥\n\n"
            "## 剧情线\n逃离封锁\n\n"
            "## 人物与物品\n林澈、铜制密钥"
        ),
        result_refs=[],
    )

    async def fake_prepare(*_args, **_kwargs):
        return confirmed

    monkeypatch.setattr(context_facade, "prepare_confirmed_ai_action", fake_prepare)
    monkeypatch.setattr(
        WritingGenerationService,
        "_execution_bundle",
        AsyncMock(
            return_value={
                "contract_hash": "e" * 64,
                "upstream_manifest": [],
                "missing_fields": [],
                "omissions": [],
            }
        ),
    )
    client = FakePovLLMClient("林澈握紧了铜制密钥。")
    draft = await WritingGenerationService(llm_client=client).generate_candidate(
        db_session,
        novel_id=novel_id,
        chapter_index=4,
        title=None,
        instruction="压低节奏",
        context_confirmation_id="00000000-0000-0000-0000-00000000c212",
    )

    assert draft.content == "林澈握紧了铜制密钥。"
    request = client.requests[0]
    system_prompt = request.messages[0].content
    user_prompt = request.messages[1].content
    assert "共同创作者" in system_prompt
    assert "不预设字数" in system_prompt
    assert "保持人物动机、关系、状态、物品" in system_prompt
    assert "写作范围：当前章节" in user_prompt
    assert "完整替换候选" in user_prompt
    assert "当前 Scene 可能跨越多章" in user_prompt
    assert "<confirmed_context>" in user_prompt
    assert "逃离封锁" in user_prompt
    assert "林澈、铜制密钥" in user_prompt


@pytest.mark.asyncio
async def test_continuation_generation_appends_to_frozen_base_deterministically(
    db_session: AsyncSession,
) -> None:
    from modules.evidence.facade import confirm_context
    from modules.writing.services import WritingGenerationService

    novel_id = "00000000-0000-0000-0000-00000000a213"
    base = await WritingDraftRepository().create_with_status(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=4,
            title="第四章",
            content="锁定正文最后一句。",
        ),
        status="published",
    )
    confirmation = await confirm_context(
        db_session,
        novel_id=novel_id,
        action="writing.generate",
        task="从第 4 章末尾续写",
        scope="chapter",
        chapter_index=4,
    )
    client = FakePovLLMClient("这是模型只返回的新增段落。")

    draft = await WritingGenerationService(llm_client=client).generate_candidate(
        db_session,
        novel_id=novel_id,
        chapter_index=4,
        title="第四章",
        instruction="自然接续",
        context_confirmation_id=confirmation.id,
        generation_mode="continue",
        base_draft_id=str(base.id),
    )

    assert draft.content == "锁定正文最后一句。\n\n这是模型只返回的新增段落。"
    assert draft.provenance_json["generation_mode"] == "continue"
    assert draft.provenance_json["base_draft_id"] == str(base.id)
    assert draft.provenance_json["base_content_hash"] == base.content_hash
    request = client.requests[0]
    assert "只为一份锁定的章节正文续写新内容" in request.messages[0].content
    assert "输出只能包含新增的续写正文" in request.messages[0].content
    assert "不能擅自增加会约束后文的长期规则" in request.messages[0].content
    assert "锁定正文最后一句。" in request.messages[1].content
    assert "输出范围：只输出新增续写正文" in request.messages[1].content


@pytest.mark.asyncio
async def test_writing_generation_saves_secret_safe_managed_llm_provenance(
    db_session: AsyncSession,
) -> None:
    import json

    from infrastructure.llm.agent_step_harness import MANAGED_LLM_PROVENANCE_KEY
    from modules.evidence.facade import confirm_context
    from modules.writing.services import WritingGenerationService

    class ProvenanceLLMClient:
        model_name = "writing-phase-model"
        profile_summary = {
            "provider_id": "compatible",
            "model": "project-default-model",
            "base_url_host": (
                "https://writer:password@api.example.test/v1?token=query-secret"
            ),
            "api_key": "sk-writing-secret",
            "base_url": "https://api.example.test/v1?api_key=base-secret",
            "prompt": "private prompt",
            "content": "private novel body",
        }
        runtime_scope = {
            "novel_id": "stale-novel-id",
            "profile_source": "project",
        }

        async def generate(self, request):
            return LLMCallResponse(
                content="这是带来源记录的候选正文。",
                model=request.model,
            )

    novel_id = "00000000-0000-0000-0000-00000000a211"
    confirmation = await confirm_context(
        db_session,
        novel_id=novel_id,
        action="writing.generate",
        task="验证正文候选的 LLM 来源记录",
        scope="chapter",
        chapter_index=11,
    )
    service = WritingGenerationService(llm_client=ProvenanceLLMClient())

    draft = await service.generate_candidate(
        db_session,
        novel_id=novel_id,
        chapter_index=11,
        title=None,
        instruction=None,
        context_confirmation_id=confirmation.id,
    )

    records = draft.provenance_json[MANAGED_LLM_PROVENANCE_KEY]
    assert len(records) == 1
    record = records[0]
    assert record["step_name"] == "writing.generation.candidate.generate"
    assert record["novel_id"] == novel_id
    assert record["profile_source"] == "project"
    assert record["profile_summary"]["model"] == "writing-phase-model"
    assert record["profile_summary"]["default_model"] == "project-default-model"
    assert record["profile_summary"]["base_url_host"] == "api.example.test"
    assert len(record["profile_hash"]) == 64

    serialized = json.dumps(draft.provenance_json, ensure_ascii=False)
    for secret in (
        "password",
        "query-secret",
        "sk-writing-secret",
        "base-secret",
        "private prompt",
        "private novel body",
    ):
        assert secret not in serialized


@pytest.mark.asyncio
async def test_writing_generation_sanitizes_candidate_html(
    db_session: AsyncSession,
) -> None:
    from modules.evidence.facade import confirm_context
    from modules.writing.services import WritingGenerationService

    novel_id = "00000000-0000-0000-0000-00000000a209"
    confirmation = await confirm_context(
        db_session,
        novel_id=novel_id,
        action="writing.generate",
        task="生成含 HTML 的候选正文",
        scope="chapter",
        chapter_index=9,
    )
    service = WritingGenerationService(
        llm_client=FakePovLLMClient("<script>alert(1)</script>正文<b>加粗</b>")
    )

    draft = await service.generate_candidate(
        db_session,
        novel_id=novel_id,
        chapter_index=9,
        title="<b>第九章</b>",
        instruction=None,
        context_confirmation_id=confirmation.id,
    )

    assert draft.status == "candidate"
    assert draft.title == "第九章"
    assert draft.content == "正文加粗"
    assert "<script>" not in draft.content
    assert "<b>" not in draft.content
    assert "alert" not in draft.content
    assert draft.provenance_json["content_sanitization"] == {
        "content_html_removed": True,
        "title_html_removed": True,
    }


@pytest.mark.asyncio
async def test_writing_generate_task_records_task_provenance(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    account_llm_connection: dict,
) -> None:
    """AI 正文生成任务创建的候选稿可追踪到确认记录与任务。"""
    from modules.evidence.facade import bind_confirmed_action_result, confirm_context
    from modules.project import llm_runtime
    from modules.project.models import Project
    from modules.writing.tasks import handle_writing_generate

    monkeypatch.setattr(
        llm_runtime.LLMClient,
        "from_resolved_profile",
        lambda _profile: FakeLLMClient(),
    )

    novel_id = "00000000-0000-0000-0000-00000000a202"
    db_session.add(
        Project(
            id=uuid.UUID(novel_id),
            title="任务来源测试",
            settings={},
        )
    )
    await db_session.flush()
    confirmation = await confirm_context(
        db_session,
        novel_id=novel_id,
        action="writing.generate",
        task="生成第 4 章候选正文",
        scope="chapter",
        chapter_index=4,
    )
    task = AsyncTask(
        task_type="writing_generate",
        status="running",
        lease_id=str(uuid.uuid4()),
        meta={
            "novel_id": novel_id,
            "chapter_index": 4,
            "context_confirmation_id": confirmation.id,
        },
    )
    db_session.add(task)
    await db_session.flush()
    confirmation = await bind_confirmed_action_result(
        db_session,
        novel_id=novel_id,
        confirmation_id=confirmation.id,
        result_type="task",
        result_id=str(task.id),
        status="running",
    )

    db_session.task_checkpoint_enabled = True  # type: ignore[attr-defined]
    result = await handle_writing_generate(db_session, task)

    draft = await WritingDraftRepository().get(
        db_session,
        uuid.UUID(result["draft_id"]),
    )
    assert draft is not None
    expected = {
        "source": "writing_generate",
        "source_confirmation_id": confirmation.id,
        "source_task_id": str(task.id),
        "context_action": "writing.generate",
        "context_result_refs": confirmation.result_refs,
    }
    for key, value in expected.items():
        assert draft.provenance_json[key] == value
    assert draft.provenance_json["generation_profile"] == "default"


@pytest.mark.asyncio
async def test_writing_generation_pov_profile_saves_structured_view_and_validation(
    db_session: AsyncSession,
) -> None:
    """POV character confirmation writes structured view and validation provenance."""
    from modules.evidence.facade import confirm_context
    from modules.project.models import Project
    from modules.world.models import Character, CharacterKnowledge, CoreEntity
    from modules.writing.services import WritingGenerationService

    novel_uuid = uuid.uuid4()
    novel_id = str(novel_uuid)
    char_id = uuid.uuid4()
    target_id = uuid.uuid4()
    db_session.add(Project(id=novel_uuid, title="测试小说", genre="悬疑", language="zh"))
    db_session.add(
        CoreEntity(
            id=char_id,
            novel_id=novel_uuid,
            entity_type="character",
            name="秦岚",
            status="canonical",
            public_info="调查员",
            importance_level="core",
        )
    )
    db_session.add(
        Character(
            entity_id=char_id,
            novel_id=novel_uuid,
            name="秦岚",
            role="调查员",
            status="canonical",
        )
    )
    db_session.add(
        CoreEntity(
            id=target_id,
            novel_id=novel_uuid,
            entity_type="faction",
            name="暗影组织",
            public_info="城中传闻有暗影组织活动。",
            hidden_truth="首领是国王",
            status="canonical",
            importance_level="core",
        )
    )
    db_session.add(
        CharacterKnowledge(
            id=uuid.uuid4(),
            novel_id=novel_uuid,
            character_id=char_id,
            target_type="entity",
            target_id=target_id,
            knowledge_level="unknown",
        )
    )
    scene = await SceneRepository().create(
        db_session,
        novel_uuid,
        SceneCreate(
            scene_index=1,
            title="主控室警报",
            chapter_index=3,
            pov_character_id=str(char_id),
            must_happen="秦岚必须发现控制台日志异常",
        ),
    )
    base = await WritingDraftRepository().create_with_status(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=3,
            title="第三章",
            content="警报响起前，秦岚正在核对控制台日志。",
        ),
        status="published",
    )
    await db_session.flush()

    confirmation = await confirm_context(
        db_session,
        novel_id=novel_id,
        action="writing.generate",
        task="基于当前 Scene 的 POV 角色有限认知，生成正文候选草稿",
        scope="chapter",
        chapter_index=3,
        scene_id=str(scene.id),
        reveal_mode="character",
        viewpoint_character_id=str(char_id),
        character_ids=[str(char_id)],
        include_pending_objects=True,
    )
    llm = FakePovLLMClient(
        """
        {
          "pov_state": {
            "perceived_facts": ["秦岚听见警报声。"],
            "interpretation": "她判断控制台被人动过。",
            "current_intention": "先稳住现场。",
            "withheld_known_information": ["首领是国王"]
          },
          "draft_prose": "秦岚听见警报声，抬手制止了靠近控制台的人。",
          "uncertainties": []
        }
        """
    )
    service = WritingGenerationService(llm_client=llm)

    draft = await service.generate_candidate(
        db_session,
        novel_id=novel_id,
        chapter_index=3,
        title="第三章 POV",
        instruction="保持克制",
        context_confirmation_id=confirmation.id,
    )

    assert draft.status == "candidate"
    assert draft.content == "秦岚听见警报声，抬手制止了靠近控制台的人。"
    provenance = draft.provenance_json
    assert provenance["generation_profile"] == "pov_character"
    assert provenance["scene_id"] == str(scene.id)
    assert provenance["viewpoint_character_id"] == str(char_id)
    assert provenance["prompt_name"] == "writing_pov_character"
    assert provenance["base_draft_id"] == str(base.id)
    assert provenance["base_content_hash"] == base.content_hash
    assert provenance["model"] == "fake-pov-model"
    assert provenance["pov_view"]["pov_state"]["withheld_known_information"] == [
        "首领是国王"
    ]
    assert provenance["pov_validation"]["status"] == "failed"
    finding = provenance["pov_validation"]["findings"][0]
    assert finding["field_path"] == ("pov_view.pov_state.withheld_known_information[0]")
    assert finding["source_type"] == "core_entity"
    assert finding["source_id"] == str(target_id)
    assert finding["redacted"] is True
    assert "首领是国王" not in finding["source_label"]
    prompt_text = llm.requests[0].messages[1].content
    assert "首领是国王" not in prompt_text
    assert "<character_safe_context_json>" in prompt_text
    assert "<locked_existing_chapter_json>" in prompt_text
    assert "警报响起前，秦岚正在核对控制台日志。" in prompt_text
    assert "完整替换候选" in prompt_text
    assert "不等于必须使用第一人称" in llm.requests[0].messages[0].content


@pytest.mark.asyncio
async def test_writing_generation_pov_parse_failure_keeps_raw_candidate(
    db_session: AsyncSession,
) -> None:
    """Bad POV JSON still creates a raw candidate when LLM returned useful text."""
    from modules.evidence.facade import confirm_context
    from modules.project.models import Project
    from modules.world.models import Character, CoreEntity
    from modules.writing.services import WritingGenerationService

    novel_uuid = uuid.uuid4()
    novel_id = str(novel_uuid)
    char_id = uuid.uuid4()
    db_session.add(Project(id=novel_uuid, title="测试小说", genre="悬疑", language="zh"))
    db_session.add(
        CoreEntity(
            id=char_id,
            novel_id=novel_uuid,
            entity_type="character",
            name="秦岚",
            status="canonical",
            importance_level="core",
        )
    )
    db_session.add(
        Character(
            entity_id=char_id,
            novel_id=novel_uuid,
            name="秦岚",
            role="调查员",
            status="canonical",
        )
    )
    scene = await SceneRepository().create(
        db_session,
        novel_uuid,
        SceneCreate(
            scene_index=1,
            title="主控室警报",
            chapter_index=3,
            pov_character_id=str(char_id),
        ),
    )
    await db_session.flush()

    confirmation = await confirm_context(
        db_session,
        novel_id=novel_id,
        action="writing.generate",
        task="基于当前 Scene 的 POV 角色有限认知，生成正文候选草稿",
        scope="chapter",
        chapter_index=3,
        scene_id=str(scene.id),
        reveal_mode="character",
        viewpoint_character_id=str(char_id),
        character_ids=[str(char_id)],
    )
    service = WritingGenerationService(
        llm_client=FakePovLLMClient("这不是 JSON，但可以作为候选正文。")
    )

    draft = await service.generate_candidate(
        db_session,
        novel_id=novel_id,
        chapter_index=3,
        title="第三章 POV",
        instruction=None,
        context_confirmation_id=confirmation.id,
    )

    assert draft.content == "这不是 JSON，但可以作为候选正文。"
    assert draft.provenance_json["pov_view"] is None
    assert draft.provenance_json["pov_validation"]["status"] == "failed"
    assert "pov_parse_failed" in draft.provenance_json["pov_validation"]["warnings"]


@pytest.mark.asyncio
async def test_publish_creates_rag_chunks(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
):
    """发布章节后应创建 RAG chunk，重新发布时应替换旧 chunk。"""
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from infrastructure.tasks.models import AsyncTask
    from modules.evidence.indexing.repositories import RagChunkRepository
    from modules.writing.tasks import handle_publish_chapter

    rag_repo = RagChunkRepository()
    nid_uuid = uuid.UUID(hex=test_project_id)
    embed_exc = Exception("embedding down")

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=embed_exc)
        mock_client_cls.return_value = mock_client

        _, task_id = await create_draft(
            db_session,
            test_project_id,
            1,
            "第一章",
            "周明瑞从梦中醒来，发现一切都变得陌生。" * 20,
        )
        assert task_id is not None

        task = await db_session.get(AsyncTask, _uuid.UUID(hex=task_id))
        assert task is not None
        task.mark_running()
        await db_session.flush()

        # Direct handler execution emulates TaskWorker's fenced session.
        db_session.task_checkpoint_enabled = True  # type: ignore[attr-defined]
        result = await handle_publish_chapter(db_session, task)
        assert result["rag_chunks"] > 0

    first_chunks = await rag_repo.find_by_chapter(db_session, nid_uuid, 1)
    assert len(first_chunks) == result["rag_chunks"]
    assert all("一切都变得陌生" in c.text for c in first_chunks)

    # 重新发布同一章节
    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=embed_exc)
        mock_client_cls.return_value = mock_client

        _, task_id_2 = await create_draft(
            db_session,
            test_project_id,
            1,
            "第一章（修订）",
            "周明瑞从梦中醒来，发现世界已经完全不同。" * 20,
        )
        task_2 = await db_session.get(AsyncTask, _uuid.UUID(hex=task_id_2))
        assert task_2 is not None
        task_2.mark_running()
        await db_session.flush()
        result_2 = await handle_publish_chapter(db_session, task_2)
        assert result_2["rag_chunks"] > 0

    second_chunks = await rag_repo.find_by_chapter(db_session, nid_uuid, 1)
    assert len(second_chunks) == result_2["rag_chunks"]
    assert all("世界已经完全不同" in c.text for c in second_chunks)
    assert all("一切都变得陌生" not in c.text for c in second_chunks)


@pytest.mark.asyncio
async def test_writing_version_lock_uses_sorted_postgres_advisory_keys() -> None:
    repo = WritingDraftRepository()
    novel_id = uuid.uuid4()
    db = MagicMock()
    db.get_bind.return_value = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    db.execute = AsyncMock()

    await repo.lock_version_chapters_for_revalidation(
        db,
        novel_id,
        [3, 1, 2, 3, 0],
    )

    assert [call.args[1]["key"] for call in db.execute.await_args_list] == [
        f"writing_versions:{novel_id}:1",
        f"writing_versions:{novel_id}:2",
        f"writing_versions:{novel_id}:3",
    ]
    assert all(
        "pg_advisory_xact_lock" in str(call.args[0])
        for call in db.execute.await_args_list
    )


@pytest.mark.asyncio
async def test_repository_content_mutations_take_writing_version_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = WritingDraftRepository()
    novel_id = uuid.uuid4()
    first = _make_draft(novel_id=novel_id, chapter_index=2, content="old")
    second = _make_draft(novel_id=novel_id, chapter_index=3, content="old")
    lock = AsyncMock()
    monkeypatch.setattr(repo, "lock_version_chapters_for_revalidation", lock)
    monkeypatch.setattr(
        repo,
        "get_latest_by_chapter",
        AsyncMock(return_value=second),
    )
    db = MagicMock()
    db.flush = AsyncMock()

    await repo.update(db, first, WritingDraftUpdate(content="updated"))
    await repo.update_latest_content(
        db,
        novel_id,
        3,
        title="third",
        content="latest",
    )

    assert [call.args[2] for call in lock.await_args_list] == [[2], [3]]
    assert first.content == "updated"
    assert second.content == "latest"


@pytest.mark.asyncio
async def test_publish_content_replacement_takes_writing_version_lock() -> None:
    novel_id = uuid.uuid4()
    draft = _make_draft(novel_id=novel_id, chapter_index=4, content="old")
    repo = MagicMock()
    repo.lock_version_chapters_for_revalidation = AsyncMock()
    service = WritingDraftService(repo=repo)
    db = MagicMock()
    db.flush = AsyncMock()

    result = await service._promote_loaded_draft(  # noqa: SLF001
        db,
        draft,
        title="fourth",
        content="replacement",
        replace_content=True,
    )

    repo.lock_version_chapters_for_revalidation.assert_awaited_once_with(
        db,
        novel_id,
        [4],
    )
    assert result.content == "replacement"
