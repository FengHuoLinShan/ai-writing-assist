"""Writing Scene conflict-check behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from infrastructure.llm.errors import LLMTimeoutError
from infrastructure.tasks.models import AsyncTask
from modules.evidence.compilation.models import ContextConfirmation
from modules.project.models import Project
from modules.writing import facade as writing_facade
from modules.writing.conflict_ai import (
    ConflictCheckAiReviewService,
    ConflictSuggestionService,
)
from modules.writing.facade import get_author_attention_items
from modules.writing.repositories import (
    AI_REVIEW_TASK_OWNER_KEY,
    WritingConflictCheckRepository,
    WritingDraftRepository,
)
from modules.writing.schemas import (
    WritingConflictCheckCreate,
    WritingDraftCreate,
    WritingDraftUpdate,
)
from modules.writing.services import WritingConflictCheckService

pytestmark = pytest.mark.usefixtures("account_llm_connection")


async def _create_project(async_client: AsyncClient, title: str = "冲突检查项目") -> str:
    resp = await async_client.post("/api/projects", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_scene(
    async_client: AsyncClient,
    novel_id: str,
    *,
    chapter_index: int = 1,
    must_happen: str = "主角拿到令牌；王后签字",
    must_not_happen: str = "主角死亡",
    pov_character_id: str | None = None,
) -> dict:
    resp = await async_client.post(
        f"/api/outline/scenes?novel_id={novel_id}",
        json={
            "scene_index": chapter_index,
            "title": "东门交涉",
            "goal": "拿到入城许可",
            "core_conflict": "守卫拒绝放行",
            "must_happen": must_happen,
            "must_not_happen": must_not_happen,
            "pov_character_id": pov_character_id,
            "chapter_ids": [str(chapter_index)],
            "scene_chunks": [
                {
                    "chapter_id": str(chapter_index),
                    "chapter_index": chapter_index,
                    "start_pos": 0,
                    "end_pos": 5,
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_check(
    async_client: AsyncClient,
    novel_id: str,
    scene_id: str | None,
    *,
    content: str = "主角死亡。王后沉默。",
    chapter_index: int = 1,
    include_candidates: bool = False,
) -> dict:
    resp = await async_client.post(
        "/api/writing/conflict-checks",
        json={
            "novel_id": novel_id,
            "chapter_index": chapter_index,
            "scene_id": scene_id,
            "content": content,
            "include_candidates": include_candidates,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_context_confirmation(
    async_client: AsyncClient,
    novel_id: str,
    *,
    action: str,
    chapter_index: int = 1,
    scene_id: str | None = None,
    include_pending_objects: bool = False,
) -> str:
    payload = {
        "novel_id": novel_id,
        "action": action,
        "task": "writing conflict AI test",
        "scope": "chapter",
        "chapter_index": chapter_index,
        "context_mode": "canonical",
        "include_pending_objects": include_pending_objects,
    }
    if scene_id:
        payload["scene_id"] = scene_id
    resp = await async_client.post(
        "/api/evidence/compilation/confirm",
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_conflict_check_persists_rule_hits_and_summary(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)

    body = await _create_check(async_client, novel_id, scene["id"])

    assert body["status"] in {"completed", "degraded"}
    assert body["summary_json"]["total"] == len(body["items"])
    kinds = {item["kind"]: item for item in body["items"]}
    assert kinds["forbidden_present"]["severity"] == "medium"
    assert kinds["forbidden_present"]["author_action"] == "can_improve"
    assert kinds["forbidden_present"]["source_module"] == "outline"
    assert "仅字面命中" in kinds["forbidden_present"]["evidence_summary"]
    forbidden_location = kinds["forbidden_present"]["location_json"]
    assert forbidden_location["source"] == {
        "module": "outline",
        "type": "scene.must_not_happen",
        "id": scene["id"],
        "label": "Scene：东门交涉",
        "field": "禁止发生",
        "excerpt": "主角死亡",
    }
    assert forbidden_location["open_target"] == {
        "kind": "outline_scene",
        "scene_id": scene["id"],
    }
    assert forbidden_location["text_range"]["start"] == 0
    assert "字面命中不代表语义冲突" in forbidden_location["needs_review_reason"]
    assert kinds["required_missing"]["severity"] == "low"
    assert kinds["required_missing"]["author_action"] == "can_improve"
    required_summaries = [
        item["evidence_summary"]
        for item in body["items"]
        if item["kind"] == "required_missing"
    ]
    assert any("主角拿到令牌" in summary for summary in required_summaries)
    required_items = [
        item for item in body["items"] if item["kind"] == "required_missing"
    ]
    assert all(
        item["location_json"]["open_target"]["kind"] == "outline_scene"
        for item in required_items
    )
    required_location = required_items[0]["location_json"]
    assert required_location["source"]["type"] == "scene.must_happen"
    assert required_location["source"]["field"] == "必须发生"
    assert required_location["source"]["excerpt"] in {"主角拿到令牌", "王后签字"}
    assert kinds["required_missing"]["status"] == "open"


@pytest.mark.asyncio
async def test_conflict_check_uses_injected_scene_loader_for_rule_hits(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="Injected scene loader"))
    await db_session.flush()
    calls: list[tuple[object, str, str]] = []

    async def fake_scene_loader(
        db: AsyncSession,
        passed_novel_id: str,
        passed_scene_id: str,
    ) -> object:
        calls.append((db, passed_novel_id, passed_scene_id))
        return SimpleNamespace(
            id=passed_scene_id,
            title="东门交涉",
            must_happen="王后签字",
            must_not_happen="主角死亡",
            pov_character_id=None,
            scene_chunks=[{"chapter_index": 1, "start_pos": 0, "end_pos": 5}],
        )

    service = WritingConflictCheckService(scene_contract_loader=fake_scene_loader)

    response = await service.create_check(
        db_session,
        WritingConflictCheckCreate(
            novel_id=str(novel_id),
            chapter_index=1,
            scene_id=str(scene_id),
            content="主角死亡。",
        ),
    )

    assert calls == [(db_session, str(novel_id), str(scene_id))]
    assert response.status == "completed"
    assert response.summary_json["degraded_sources"] == []
    kinds = {item.kind: item for item in response.items}
    assert kinds["forbidden_present"].source_module == "outline"
    assert kinds["forbidden_present"].source_id == str(scene_id)
    assert "主角死亡" in kinds["forbidden_present"].evidence_summary
    assert kinds["required_missing"].source_module == "outline"
    assert "王后签字" in kinds["required_missing"].evidence_summary


@pytest.mark.asyncio
async def test_conflict_check_only_scans_current_scene_chunks(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="Exact Scene scope"))
    await db_session.flush()
    llm = AsyncMock()

    async def fake_scene_loader(*_args) -> object:
        return SimpleNamespace(
            id=str(scene_id),
            title="中段",
            must_happen="拿到令牌",
            must_not_happen="主角死亡",
            scene_chunks=[
                {"chapter_index": 1, "start_pos": 5, "end_pos": 9},
                {"chapter_index": 1, "start_pos": 10, "end_pos": 14},
                {"chapter_index": 2, "start_pos": 0, "end_pos": 4},
            ],
        )

    service = WritingConflictCheckService(
        scene_contract_loader=fake_scene_loader,
        llm_client=llm,
    )
    response = await service.create_check(
        db_session,
        WritingConflictCheckCreate(
            novel_id=str(novel_id),
            chapter_index=1,
            scene_id=str(scene_id),
            content="主角死亡|拿到令牌|主角死亡",
        ),
    )

    assert response.status == "completed"
    assert [item for item in response.items if item.kind == "required_missing"] == []
    forbidden = [item for item in response.items if item.kind == "forbidden_present"]
    assert len(forbidden) == 1
    assert forbidden[0].location_json["text_range"]["start"] == 10
    llm.generate_structured.assert_not_called()


@pytest.mark.asyncio
async def test_conflict_check_degrades_when_scene_range_is_invalid(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="Invalid Scene scope"))
    await db_session.flush()

    async def fake_scene_loader(*_args) -> object:
        return SimpleNamespace(
            id=str(scene_id),
            title="失效范围",
            must_happen="拿到令牌",
            must_not_happen="主角死亡",
            scene_chunks=[{"chapter_index": 1, "start_pos": 100, "end_pos": 120}],
        )

    response = await WritingConflictCheckService(
        scene_contract_loader=fake_scene_loader
    ).create_check(
        db_session,
        WritingConflictCheckCreate(
            novel_id=str(novel_id),
            chapter_index=1,
            scene_id=str(scene_id),
            content="其他场景中主角死亡。",
        ),
    )

    assert response.status == "degraded"
    assert response.items == []
    assert response.summary_json["degraded_sources"] == ["outline.scene_chunks"]
    assert response.summary_json["omissions"] == [
        {"source": "outline.scene_chunks", "reason": "invalid_for_content"}
    ]


@pytest.mark.asyncio
async def test_conflict_check_skips_all_rules_when_scene_range_is_partially_invalid(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="Partial Scene scope"))
    await db_session.flush()

    async def fake_scene_loader(*_args) -> object:
        return SimpleNamespace(
            id=str(scene_id),
            title="部分失效范围",
            must_happen="拿到令牌",
            must_not_happen="主角死亡",
            scene_chunks=[
                {"chapter_index": 1, "start_pos": 0, "end_pos": 4},
                {"chapter_index": 1, "start_pos": 100, "end_pos": 120},
            ],
        )

    response = await WritingConflictCheckService(
        scene_contract_loader=fake_scene_loader
    ).create_check(
        db_session,
        WritingConflictCheckCreate(
            novel_id=str(novel_id),
            chapter_index=1,
            scene_id=str(scene_id),
            content="主角死亡，但令牌在后一个未覆盖片段。",
        ),
    )

    assert response.status == "degraded"
    assert response.items == []
    assert response.summary_json["omissions"] == [
        {
            "source": "outline.scene_chunks",
            "reason": "partially_invalid_for_content",
        }
    ]


@pytest.mark.asyncio
async def test_conflict_check_degrades_when_scene_range_hash_is_stale(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="Stale Scene scope"))
    await db_session.flush()

    async def fake_scene_loader(*_args) -> object:
        return SimpleNamespace(
            id=str(scene_id),
            title="旧正文范围",
            must_happen="拿到令牌",
            must_not_happen="主角死亡",
            scene_chunks=[
                {
                    "chapter_index": 1,
                    "start_pos": 0,
                    "end_pos": 4,
                    "source_content_hash": "0" * 64,
                }
            ],
        )

    response = await WritingConflictCheckService(
        scene_contract_loader=fake_scene_loader
    ).create_check(
        db_session,
        WritingConflictCheckCreate(
            novel_id=str(novel_id),
            chapter_index=1,
            scene_id=str(scene_id),
            content="主角死亡。",
        ),
    )

    assert response.status == "degraded"
    assert response.items == []
    assert response.summary_json["omissions"] == [
        {"source": "outline.scene_chunks", "reason": "source_hash_mismatch"}
    ]


def test_writing_facade_exports_author_attention_seam() -> None:
    assert "get_author_attention_items" in writing_facade.__all__


@pytest.mark.parametrize("loader_mode", ["none", "exception"])
@pytest.mark.asyncio
async def test_conflict_check_injected_scene_loader_degrades_on_missing_scene(
    db_session: AsyncSession,
    loader_mode: str,
) -> None:
    novel_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title=f"Scene loader {loader_mode}"))
    await db_session.flush()

    async def fake_scene_loader(
        _db: AsyncSession,
        _novel_id: str,
        _scene_id: str,
    ) -> object | None:
        if loader_mode == "exception":
            raise RuntimeError("outline unavailable")
        return None

    service = WritingConflictCheckService(scene_contract_loader=fake_scene_loader)

    response = await service.create_check(
        db_session,
        WritingConflictCheckCreate(
            novel_id=str(novel_id),
            chapter_index=1,
            scene_id=str(scene_id),
            content="主角死亡。",
        ),
    )

    assert response.status == "degraded"
    assert response.summary_json["degraded_sources"] == ["outline"]
    assert [item for item in response.items if item.source_module == "outline"] == []


@pytest.mark.asyncio
async def test_conflict_item_status_update_is_novel_scoped(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "A")
    other_novel_id = await _create_project(async_client, "B")
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    item_id = check["items"][0]["id"]

    wrong_scope = await async_client.patch(
        f"/api/writing/conflict-check-items/{item_id}?novel_id={other_novel_id}",
        json={"status": "later"},
    )
    assert wrong_scope.status_code == 404

    ok = await async_client.patch(
        f"/api/writing/conflict-check-items/{item_id}?novel_id={novel_id}",
        json={"status": "later"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "later"


@pytest.mark.asyncio
async def test_conflict_check_history_returns_latest_first(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    first = await _create_check(async_client, novel_id, scene["id"], content="正文一")
    second = await _create_check(async_client, novel_id, scene["id"], content="正文二")

    resp = await async_client.get(
        "/api/writing/conflict-checks",
        params={
            "novel_id": novel_id,
            "chapter_index": 1,
            "scene_id": scene["id"],
            "limit": 1,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert [item["id"] for item in body["items"]] == [second["id"]]
    assert first["id"] != second["id"]


@pytest.mark.asyncio
async def test_author_attention_only_projects_latest_open_scope_items(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    old_check = await _create_check(async_client, novel_id, scene["id"])
    latest_check = await _create_check(async_client, novel_id, scene["id"])
    await async_client.patch(
        f"/api/writing/conflict-check-items/{latest_check['items'][0]['id']}",
        params={"novel_id": novel_id},
        json={"status": "later"},
    )

    items = await get_author_attention_items(db_session, novel_id)

    projected_ids = {item.item_id for item in items}
    assert all(item["id"] not in projected_ids for item in old_check["items"])
    assert projected_ids == {item["id"] for item in latest_check["items"][1:]}
    assert all(item.author_action == "can_improve" for item in items)


@pytest.mark.asyncio
async def test_author_attention_collapses_stale_check_to_recheck(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    saved = await async_client.post(
        "/api/writing/drafts/autosave",
        json={
            "novel_id": novel_id,
            "chapter_index": 1,
            "title": "第一章",
            "content": "新工作稿",
        },
    )
    assert saved.status_code == 201

    items = await get_author_attention_items(db_session, novel_id)

    assert len(items) == 1
    assert items[0].key == f"writing:recheck:{check['id']}"
    assert items[0].item_id is None
    assert items[0].author_action == "can_improve"
    assert items[0].title == "重新检查第 1 章"


@pytest.mark.asyncio
async def test_author_attention_detects_in_place_draft_content_change(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="In-place stale check"))
    await db_session.flush()
    draft_repo = WritingDraftRepository()
    draft = await draft_repo.create(
        db_session,
        WritingDraftCreate(
            novel_id=str(novel_id),
            chapter_index=1,
            title="第一章",
            content="主角死亡",
        ),
    )

    async def fake_scene_loader(*_args) -> object:
        return SimpleNamespace(
            id=str(scene_id),
            title="当前场景",
            must_happen=None,
            must_not_happen="主角死亡",
            scene_chunks=[{"chapter_index": 1, "start_pos": 0, "end_pos": 4}],
        )

    service = WritingConflictCheckService(
        draft_repo=draft_repo,
        scene_contract_loader=fake_scene_loader,
    )
    check = await service.create_check(
        db_session,
        WritingConflictCheckCreate(
            novel_id=str(novel_id),
            chapter_index=1,
            scene_id=str(scene_id),
            draft_id=str(draft.id),
            version_number=draft.version_number,
            content="主角死亡",
        ),
    )
    await draft_repo.update(
        db_session,
        draft,
        WritingDraftUpdate(content="主角离开"),
    )

    items = await service.get_author_attention_items(db_session, str(novel_id))

    assert len(items) == 1
    assert items[0].key == f"writing:recheck:{check.id}"
    assert items[0].item_id is None


@pytest.mark.asyncio
async def test_conflict_check_history_batches_item_loading(
    db_session: AsyncSession,
) -> None:
    class CountingConflictCheckRepository(WritingConflictCheckRepository):
        def __init__(self) -> None:
            super().__init__()
            self.list_items_calls = 0

        async def list_items(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            self.list_items_calls += 1
            return await super().list_items(*args, **kwargs)

    novel_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="Conflict history perf"))
    await db_session.flush()
    repo = CountingConflictCheckRepository()
    for idx in range(3):
        await repo.create_check(
            db_session,
            novel_id=novel_id,
            chapter_index=1,
            scene_id=None,
            draft_id=None,
            version_number=None,
            scope={"chapter_index": 1},
            include_candidates=False,
            status="completed",
            summary_json={"total": 1},
            items=[
                {
                    "kind": "required_missing",
                    "severity": "medium",
                    "source_module": "outline",
                    "source_type": "scene.must_happen",
                    "source_id": f"scene-{idx}",
                    "evidence_summary": f"missing-{idx}",
                }
            ],
        )

    pairs, total = await repo.list_checks(
        db_session,
        novel_id=novel_id,
        chapter_index=1,
        scene_id=None,
        limit=3,
    )

    assert total == 3
    assert len(pairs) == 3
    assert all(len(items) == 1 for _check, items in pairs)
    assert repo.list_items_calls <= 1


@pytest.mark.asyncio
async def test_draft_only_autosave_creates_draft_and_requests_working_rag_index(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = await _create_project(async_client)

    resp = await async_client.post(
        "/api/writing/drafts/autosave",
        json={
            "novel_id": novel_id,
            "chapter_index": 3,
            "title": "第三章",
            "content": "尚未发布的正文",
        },
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["chapter_index"] == 3
    result = await db_session.execute(select(AsyncTask))
    tasks = list(result.scalars().all())
    assert [task.task_type for task in tasks] == ["rag_index_chapter"]
    assert tasks[0].meta["content_mode"] == "working"


@pytest.mark.asyncio
async def test_publish_archives_latest_conflict_check_snapshot(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    item_id = check["items"][0]["id"]

    published = await async_client.post(
        "/api/writing/drafts",
        json={
            "novel_id": novel_id,
            "chapter_index": 1,
            "scene_id": scene["id"],
            "title": "第一章",
            "content": "发布正文",
        },
    )
    assert published.status_code == 201, published.text
    snapshot = published.json()["draft"]["conflict_check_snapshot_json"]
    assert snapshot["check_id"] == check["id"]
    assert snapshot["open_high_count"] == 0
    first_snapshot_item = snapshot["items"][0]
    assert first_snapshot_item["location_json"]["source"]
    assert first_snapshot_item["location_json"]["open_target"]
    assert "text_range" not in first_snapshot_item["location_json"]

    status_resp = await async_client.patch(
        f"/api/writing/conflict-check-items/{item_id}?novel_id={novel_id}",
        json={"status": "ignored"},
    )
    assert status_resp.status_code == 200

    draft_id = published.json()["draft"]["id"]
    fetched = await async_client.get(
        f"/api/writing/drafts/{draft_id}",
        params={"novel_id": novel_id},
    )
    assert fetched.status_code == 200
    assert fetched.json()["conflict_check_snapshot_json"] == snapshot


@pytest.mark.asyncio
async def test_publish_without_scene_id_does_not_archive_scene_scoped_check(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    await _create_check(async_client, novel_id, scene["id"])

    published = await async_client.post(
        "/api/writing/drafts",
        json={
            "novel_id": novel_id,
            "chapter_index": 1,
            "title": "第一章",
            "content": "发布正文",
        },
    )

    assert published.status_code == 201, published.text
    assert published.json()["draft"]["conflict_check_snapshot_json"] is None


@pytest.mark.asyncio
async def test_ai_review_service_uses_domain_not_found_error() -> None:
    repo = type(
        "Repo",
        (),
        {"get_check_for_ai_review_update": AsyncMock(return_value=None)},
    )()
    service = ConflictCheckAiReviewService(repo)  # type: ignore[arg-type]

    with pytest.raises(NotFoundError) as exc_info:
        await service.run(
            None,  # type: ignore[arg-type]
            novel_id="11111111-1111-4111-8111-111111111111",
            check_id="22222222-2222-4222-8222-222222222222",
            context_confirmation_id="33333333-3333-4333-8333-333333333333",
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_ai_review_reuses_loaded_items_after_append(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid.uuid4()
    check_id = uuid.uuid4()
    confirmation_id = uuid.uuid4()
    current_item = SimpleNamespace(
        id=uuid.uuid4(),
        kind="required_missing",
        severity="low",
        evidence_summary="王后签字没有出现",
        is_ai_judgment=False,
        status="open",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    check = SimpleNamespace(
        id=check_id,
        chapter_index=1,
        scene_id=None,
        scope={"content_excerpt": "主角点头同意。"},
        summary_json={"total": 1},
    )

    class Repo:
        def __init__(self) -> None:
            self.append_items_calls = 0
            self.list_items_calls = 0

        async def get_check_for_ai_review_update(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return check, [current_item]

        async def update_ai_review(
            self,
            _db,
            *,
            status,
            summary_json=None,
            **_kwargs,
        ):  # type: ignore[no-untyped-def]
            check.ai_review_status = status
            check.summary_json = summary_json or check.summary_json
            return check

        async def append_items(self, *_args, items, **_kwargs):  # type: ignore[no-untyped-def]
            self.append_items_calls += 1
            return [
                SimpleNamespace(
                    id=uuid.uuid4(),
                    created_at=datetime(2026, 1, 2, tzinfo=UTC),
                    **item,
                )
                for item in items
            ]

        async def list_items(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            self.list_items_calls += 1
            raise AssertionError("AI review success must reuse loaded and appended items")

    class LLM:
        model_name = "fake-model"

        async def generate_structured(self, _request, schema, **_kwargs):
            return schema.model_validate(
                {
                    "issues": [
                        {
                            "kind": "motivation_gap",
                            "severity": "high",
                            "summary": "主角突然信任港务长",
                            "evidence": "主角点头同意。",
                            "rationale": "此前没有建立信任动机。",
                            "location_hint": {"chapter_index": 1},
                            "confidence": 0.72,
                            "depends_on_pending_objects": False,
                        }
                    ]
                }
            )

    async def fake_prepare_confirmed_ai_action(*_args, **_kwargs):
        return SimpleNamespace(
            confirmation=SimpleNamespace(
                compile_options={"chapter_index": 1},
                include_pending_objects=False,
            ),
            rendered_markdown="scene context",
        )

    async def fake_bind_confirmed_action_result(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "modules.evidence.facade.prepare_confirmed_ai_action",
        fake_prepare_confirmed_ai_action,
    )
    monkeypatch.setattr(
        "modules.evidence.facade.bind_confirmed_action_result",
        fake_bind_confirmed_action_result,
    )

    repo = Repo()
    service = ConflictCheckAiReviewService(repo, llm_client=LLM())  # type: ignore[arg-type]

    updated, items = await service.run(
        None,  # type: ignore[arg-type]
        novel_id=str(novel_id),
        check_id=str(check_id),
        context_confirmation_id=str(confirmation_id),
    )

    assert updated is check
    assert repo.append_items_calls == 1
    assert repo.list_items_calls == 0
    assert [item.severity for item in items] == ["high", "low"]
    assert check.summary_json["total"] == 2
    assert check.summary_json["ai_review"]["item_count"] == 1


@pytest.mark.asyncio
async def test_ai_suggestion_service_uses_domain_not_found_error() -> None:
    repo = type("Repo", (), {"get_item": AsyncMock(return_value=None)})()
    service = ConflictSuggestionService(repo)  # type: ignore[arg-type]

    with pytest.raises(NotFoundError) as exc_info:
        await service.generate(
            None,  # type: ignore[arg-type]
            novel_id="11111111-1111-4111-8111-111111111111",
            item_id="22222222-2222-4222-8222-222222222222",
            context_confirmation_id="33333333-3333-4333-8333-333333333333",
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_ai_suggestion_reuses_loaded_item_for_status_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid.uuid4()
    check_id = uuid.uuid4()
    item_id = uuid.uuid4()
    confirmation_id = uuid.uuid4()
    check = SimpleNamespace(
        id=check_id,
        chapter_index=1,
        scene_id=None,
    )
    item = SimpleNamespace(
        id=item_id,
        check_id=check_id,
        kind="required_missing",
        evidence_summary="王后签字没有出现",
        suggestion_status="not_requested",
    )

    class Repo:
        def __init__(self) -> None:
            self.get_item_calls = 0
            self.loaded_update_statuses: list[str] = []

        async def get_item(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            self.get_item_calls += 1
            return item

        async def get_check(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return check, [item]

        async def update_item_suggestion(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("suggestion flow must not re-fetch item")

        async def update_loaded_item_suggestion(
            self,
            _db,
            loaded_item,
            *,
            status,
            confirmation_id=None,
            ai_suggestion=None,
            llm_rationale=None,
            error=None,
        ):  # type: ignore[no-untyped-def]
            assert loaded_item is item
            self.loaded_update_statuses.append(status)
            loaded_item.suggestion_status = status
            loaded_item.suggestion_confirmation_id = confirmation_id
            loaded_item.ai_suggestion = ai_suggestion
            loaded_item.llm_rationale = llm_rationale
            loaded_item.suggestion_error = error
            return loaded_item

    class LLM:
        model_name = "fake-model"

        async def generate_structured(self, _request, schema, **_kwargs):
            return schema.model_validate(
                {
                    "suggestion": {
                        "strategy": "补足签字动作",
                        "suggested_text": "王后按下印鉴后，守卫才侧身放行。",
                        "rationale": "让必须发生的签字动作进入正文。",
                        "constraints": [],
                        "risk_notes": [],
                    }
                }
            )

    async def fake_prepare_confirmed_ai_action(*_args, **_kwargs):
        return SimpleNamespace(
            confirmation=SimpleNamespace(
                compile_options={"chapter_index": 1},
                include_pending_objects=False,
            ),
            rendered_markdown="scene context",
        )

    async def fake_bind_confirmed_action_result(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "modules.evidence.facade.prepare_confirmed_ai_action",
        fake_prepare_confirmed_ai_action,
    )
    monkeypatch.setattr(
        "modules.evidence.facade.bind_confirmed_action_result",
        fake_bind_confirmed_action_result,
    )

    repo = Repo()
    service = ConflictSuggestionService(repo, llm_client=LLM())  # type: ignore[arg-type]

    updated = await service.generate(
        None,  # type: ignore[arg-type]
        novel_id=str(novel_id),
        item_id=str(item_id),
        context_confirmation_id=str(confirmation_id),
    )

    assert updated is item
    assert repo.get_item_calls == 1
    assert repo.loaded_update_statuses == ["running", "done"]
    assert item.suggestion_status == "done"
    assert "补足签字动作" in item.ai_suggestion


@pytest.mark.asyncio
async def test_ai_review_valid_output_adds_ai_judgment_items(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_review",
        scene_id=scene["id"],
    )

    async def fake_generate_structured(_self, _request, schema, **_kwargs):
        return schema.model_validate(
            {
                "issues": [
                    {
                        "kind": "motivation_gap",
                        "severity": "medium",
                        "summary": "主角突然信任港务长",
                        "evidence": "主角点头同意。",
                        "rationale": "此前没有建立信任动机。",
                        "location_hint": {
                            "chapter_index": 1,
                            "scene_id": scene["id"],
                            "text_quote": "点头同意",
                        },
                        "confidence": 0.72,
                        "depends_on_pending_objects": False,
                    }
                ]
            }
        )

    monkeypatch.setattr(
        "infrastructure.llm.client.LLMClient.generate_structured",
        fake_generate_structured,
    )

    resp = await async_client.post(
        f"/api/writing/conflict-checks/{check['id']}/ai-review",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ai_review_status"] == "done"
    ai_items = [item for item in body["items"] if item["is_ai_judgment"]]
    assert len(ai_items) == 1
    assert ai_items[0]["kind"] == "motivation_gap"
    assert ai_items[0]["source_module"] == "ai"
    assert ai_items[0]["source_confirmation_id"] == confirmation_id
    assert ai_items[0]["confidence"] == 0.72
    assert "信任动机" in ai_items[0]["llm_rationale"]


@pytest.mark.asyncio
async def test_ai_review_inherits_project_budget_and_uses_concise_prompt_constraints(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_review",
        scene_id=scene["id"],
    )

    async def fake_generate_structured(_self, request, schema, **_kwargs):
        assert request.max_tokens is None
        prompt = request.messages[-1].content
        assert "最多输出 2 条 issues" in prompt
        assert "summary/evidence/rationale 各限制 1-2 句" in prompt
        assert "不要展开长段解释" in prompt
        return schema.model_validate({"issues": []})

    monkeypatch.setattr(
        "infrastructure.llm.client.LLMClient.generate_structured",
        fake_generate_structured,
    )

    resp = await async_client.post(
        f"/api/writing/conflict-checks/{check['id']}/ai-review",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["ai_review_status"] == "done"


@pytest.mark.asyncio
async def test_ai_review_task_endpoint_marks_running_and_binds_task(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id, chapter_index=3)
    check = await _create_check(
        async_client,
        novel_id,
        scene["id"],
        chapter_index=3,
    )
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_review",
        chapter_index=3,
        scene_id=scene["id"],
    )

    resp = await async_client.post(
        f"/api/writing/conflict-checks/{check['id']}/ai-review-task",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["task_id"]
    assert body["status"] == "pending"
    assert body["check"]["ai_review_status"] == "running"
    assert body["check"]["ai_review_confirmation_id"] == confirmation_id

    task_result = await db_session.execute(
        select(AsyncTask).where(AsyncTask.id == uuid.UUID(body["task_id"]))
    )
    task = task_result.scalar_one()
    assert task.task_type == "writing_conflict_ai_review"
    assert task.meta["novel_id"] == novel_id
    assert task.meta["check_id"] == check["id"]
    assert task.meta["context_confirmation_id"] == confirmation_id
    snapshot = task.meta["llm_execution_snapshot"]
    assert snapshot["novel_id"] == novel_id
    assert snapshot["profile_hash"]
    assert "base_url" not in snapshot["profile"]
    assert "extra" not in snapshot["profile"]
    assert isinstance(snapshot["profile"]["api_key_configured"], bool)
    assert AI_REVIEW_TASK_OWNER_KEY not in body["check"]["summary_json"]

    stored_check = await WritingConflictCheckRepository().get_check(
        db_session,
        uuid.UUID(check["id"]),
        uuid.UUID(novel_id),
    )
    assert stored_check is not None
    assert stored_check[0].summary_json[AI_REVIEW_TASK_OWNER_KEY] == body["task_id"]

    confirmation_result = await db_session.execute(
        select(ContextConfirmation).where(
            ContextConfirmation.id == uuid.UUID(confirmation_id)
        )
    )
    confirmation = confirmation_result.scalar_one()
    assert confirmation.result_status == "running"
    assert {"type": "task", "id": body["task_id"]} in confirmation.result_refs


@pytest.mark.asyncio
async def test_ai_review_rejects_wrong_confirmation_action(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.generate",
        scene_id=scene["id"],
    )

    resp = await async_client.post(
        f"/api/writing/conflict-checks/{check['id']}/ai-review",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 400
    assert "action" in resp.text


@pytest.mark.asyncio
async def test_ai_review_rejects_confirmation_for_wrong_chapter(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_review",
        chapter_index=2,
        scene_id=scene["id"],
    )

    resp = await async_client.post(
        f"/api/writing/conflict-checks/{check['id']}/ai-review",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 400
    assert "chapter_index" in resp.text


@pytest.mark.asyncio
async def test_ai_review_partial_invalid_output_records_discard_count(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_review",
        scene_id=scene["id"],
        include_pending_objects=True,
    )

    async def fake_generate_structured(_self, _request, schema, **_kwargs):
        return schema.model_validate(
            {
                "issues": [
                    {
                        "kind": "emotion_jump",
                        "severity": "low",
                        "summary": "情绪转折过快",
                        "evidence": "上一句愤怒，下一句平静。",
                        "rationale": "缺少情绪缓冲。",
                        "confidence": 0.61,
                        "depends_on_pending_objects": True,
                    },
                    {
                        "kind": "unknown_kind",
                        "severity": "medium",
                        "summary": "应被丢弃",
                        "evidence": "bad",
                        "rationale": "bad",
                        "confidence": 0.5,
                    },
                    "not an issue object",
                ]
            }
        )

    monkeypatch.setattr(
        "infrastructure.llm.client.LLMClient.generate_structured",
        fake_generate_structured,
    )

    resp = await async_client.post(
        f"/api/writing/conflict-checks/{check['id']}/ai-review",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ai_review_status"] == "partial"
    assert body["summary_json"]["ai_review"]["discarded_count"] == 2
    ai_items = [item for item in body["items"] if item["is_ai_judgment"]]
    assert len(ai_items) == 1
    assert ai_items[0]["needs_review"] is True


@pytest.mark.asyncio
async def test_ai_review_failure_keeps_rule_items_and_marks_check_failed(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_review",
        scene_id=scene["id"],
    )

    secret = "private-token-value"

    async def fake_generate_structured(_self, _request, _schema, **_kwargs):
        raise LLMTimeoutError(
            f"timeout Authorization: Bearer {secret} api_key={secret}",
            provider="fake",
        )

    monkeypatch.setattr(
        "infrastructure.llm.client.LLMClient.generate_structured",
        fake_generate_structured,
    )

    resp = await async_client.post(
        f"/api/writing/conflict-checks/{check['id']}/ai-review",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ai_review_status"] == "failed"
    assert "timeout" in body["ai_review_error"]
    assert secret not in body["ai_review_error"]
    assert secret not in caplog.text
    assert [item for item in body["items"] if not item["is_ai_judgment"]]


@pytest.mark.asyncio
async def test_ai_suggestion_stores_manual_suggestion_without_mutating_draft(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    item_id = check["items"][0]["id"]
    draft = await async_client.post(
        "/api/writing/drafts/autosave",
        json={
            "novel_id": novel_id,
            "chapter_index": 1,
            "title": "第一章",
            "content": "原始正文",
        },
    )
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()["id"]
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_suggestion",
        scene_id=scene["id"],
    )

    async def fake_generate_structured(_self, _request, schema, **_kwargs):
        return schema.model_validate(
            {
                "suggestion": {
                    "strategy": "补一段动机过渡",
                    "suggested_text": "他想起旧约，才勉强点头。",
                    "rationale": "补足信任动作的心理来源。",
                    "constraints": ["不能提前揭示证人全部真相"],
                    "risk_notes": ["保持港务长仍不可信"],
                }
            }
        )

    monkeypatch.setattr(
        "infrastructure.llm.client.LLMClient.generate_structured",
        fake_generate_structured,
    )

    resp = await async_client.post(
        f"/api/writing/conflict-check-items/{item_id}/ai-suggestion",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["suggestion_status"] == "done"
    assert body["suggestion_confirmation_id"] == confirmation_id
    assert "补一段动机过渡" in body["ai_suggestion"]
    fetched = await async_client.get(
        f"/api/writing/drafts/{draft_id}",
        params={"novel_id": novel_id},
    )
    assert fetched.status_code == 200
    assert fetched.json()["content"] == "原始正文"


@pytest.mark.asyncio
async def test_ai_suggestion_task_uses_operation_receipt(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    item_id = check["items"][0]["id"]
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_suggestion",
        scene_id=scene["id"],
    )
    operation_id = str(uuid.uuid4())
    payload = {
        "novel_id": novel_id,
        "context_confirmation_id": confirmation_id,
        "operation_id": operation_id,
    }

    first = await async_client.post(
        f"/api/writing/conflict-check-items/{item_id}/ai-suggestion-task",
        json=payload,
    )
    repeated = await async_client.post(
        f"/api/writing/conflict-check-items/{item_id}/ai-suggestion-task",
        json=payload,
    )

    assert first.status_code == repeated.status_code == 202
    assert (
        first.json()
        == repeated.json()
        == {
            "task_id": operation_id,
            "status": "pending",
        }
    )
    task = await db_session.scalar(
        select(AsyncTask).where(AsyncTask.id == uuid.UUID(operation_id))
    )
    assert task is not None
    assert task.task_type == "writing_conflict_item_ai_suggestion"


@pytest.mark.asyncio
async def test_ai_suggestion_uses_large_budget_and_concise_prompt_constraints(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    item_id = check["items"][0]["id"]
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_suggestion",
        scene_id=scene["id"],
    )

    async def fake_generate_structured(_self, request, schema, **_kwargs):
        assert request.max_tokens is None
        prompt = request.messages[-1].content
        assert "strategy/rationale 各 1-2 句" in prompt
        assert "suggested_text 控制在 300-600 字以内" in prompt
        assert "constraints/risk_notes 每项不超过 3 条" in prompt
        return schema.model_validate(
            {
                "suggestion": {
                    "strategy": "补动机",
                    "suggested_text": "他想起旧约，才勉强点头。",
                    "rationale": "补足心理来源。",
                    "constraints": [],
                    "risk_notes": [],
                }
            }
        )

    monkeypatch.setattr(
        "infrastructure.llm.client.LLMClient.generate_structured",
        fake_generate_structured,
    )

    resp = await async_client.post(
        f"/api/writing/conflict-check-items/{item_id}/ai-suggestion",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_ai_suggestion_rejects_confirmation_for_wrong_chapter(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    item_id = check["items"][0]["id"]
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_suggestion",
        chapter_index=2,
        scene_id=scene["id"],
    )

    resp = await async_client.post(
        f"/api/writing/conflict-check-items/{item_id}/ai-suggestion",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 400
    assert "chapter_index" in resp.text


@pytest.mark.asyncio
async def test_drifted_suggestion_marked_failed_instead_of_stuck_running() -> None:
    novel_id = uuid.uuid4()
    item_id = uuid.uuid4()
    confirmation_id = uuid.uuid4()
    item = SimpleNamespace(
        id=item_id,
        suggestion_status="running",
        suggestion_confirmation_id=confirmation_id,
        suggestion_error=None,
    )

    class Repo:
        async def get_item(self, _db, _item_uuid, _novel_uuid, *, for_update=False):  # type: ignore[no-untyped-def]
            assert for_update is True
            return item

        async def update_loaded_item_suggestion(
            self,
            _db,
            loaded_item,
            *,
            status,
            confirmation_id=None,
            ai_suggestion=None,
            llm_rationale=None,
            error=None,
        ):  # type: ignore[no-untyped-def]
            loaded_item.suggestion_status = status
            loaded_item.suggestion_confirmation_id = confirmation_id
            loaded_item.suggestion_error = error
            return loaded_item

    service = ConflictSuggestionService(Repo())  # type: ignore[arg-type]

    await service._mark_drifted_suggestion_failed(
        None,  # type: ignore[arg-type]
        novel_id=str(novel_id),
        item_id=str(item_id),
        context_confirmation_id=str(confirmation_id),
    )

    assert item.suggestion_status == "failed"
    assert item.suggestion_confirmation_id == confirmation_id
    assert "已变化" in (item.suggestion_error or "")


@pytest.mark.asyncio
async def test_drifted_suggestion_keeps_new_takeover_untouched() -> None:
    novel_id = uuid.uuid4()
    item_id = uuid.uuid4()
    takeover_confirmation = uuid.uuid4()
    item = SimpleNamespace(
        id=item_id,
        suggestion_status="running",
        suggestion_confirmation_id=takeover_confirmation,
        suggestion_error=None,
    )

    class Repo:
        async def get_item(self, _db, _item_uuid, _novel_uuid, *, for_update=False):  # type: ignore[no-untyped-def]
            return item

        async def update_loaded_item_suggestion(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("已被新任务接管的状态不得被旧任务覆盖")

    service = ConflictSuggestionService(Repo())  # type: ignore[arg-type]

    await service._mark_drifted_suggestion_failed(
        None,  # type: ignore[arg-type]
        novel_id=str(novel_id),
        item_id=str(item_id),
        context_confirmation_id=str(uuid.uuid4()),
    )

    assert item.suggestion_status == "running"
