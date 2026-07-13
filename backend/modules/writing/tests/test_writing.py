"""
Writing 模块测试

测试草稿 CRUD、版本管理、facade 和边界情况。
"""

from __future__ import annotations

import ast
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, DomainError, NotFoundError, ValidationError
from infrastructure.llm.schemas import LLMCallResponse
from infrastructure.tasks.models import AsyncTask
from modules.outline.repositories import SceneRepository
from modules.outline.schemas import SceneCreate
from modules.writing.contracts import WritingDraftContract
from modules.writing.facade import (
    create_draft,
    get_draft,
    get_latest_draft_for_chapter,
    list_chapter_indices,
    list_latest_drafts_for_chapters,
    list_project_writing_stats,
)
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import (
    WritingDraftCreate,
    WritingDraftUpdate,
)
from modules.writing.services import WritingDraftService

# ============================================================
# Fixtures
# ============================================================


def test_writing_facade_cold_import_does_not_cycle_through_worker() -> None:
    """writing facade 可被 worker 冷导入，不应触发 project/writing 循环导入。"""
    backend_root = Path(__file__).resolve().parents[3]

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from modules.writing.facade import "
                "list_latest_drafts_for_chapters, get_project_writing_stats; "
                "from infrastructure.tasks.worker import TaskWorker; "
                "print(list_latest_drafts_for_chapters.__name__, "
                "get_project_writing_stats.__name__, TaskWorker.__name__)"
            ),
        ],
        cwd=backend_root,
        check=False,
        text=True,
        capture_output=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "list_latest_drafts_for_chapters get_project_writing_stats TaskWorker" in (
        result.stdout
    )


def test_writing_facade_does_not_import_api_response_schema() -> None:
    import modules.writing.facade as writing_facade

    facade_source = Path(writing_facade.__file__).read_text()
    contracts_source = Path("modules/writing/contracts.py").read_text()

    assert not hasattr(writing_facade, "WritingDraftResponse")
    assert "WritingDraftResponse" not in facade_source
    assert "WritingDraftResponse" not in contracts_source


def test_writing_services_has_no_top_level_outline_facade_import() -> None:
    services_path = Path("modules/writing/services.py")
    tree = ast.parse(services_path.read_text(), filename=str(services_path))

    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            assert node.module != "modules.outline.facade"
        elif isinstance(node, ast.Import):
            assert all(alias.name != "modules.outline.facade" for alias in node.names)


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


def test_generation_profile_resolver_requires_valid_character_confirmation() -> None:
    from modules.writing.pov_generation import (
        GenerationProfile,
        GenerationProfileResolver,
    )

    resolver = GenerationProfileResolver()
    valid_options = {
        "reveal_mode": "character",
        "scene_id": "scene-1",
        "viewpoint_character_id": "char-1",
    }

    assert resolver.resolve(_fake_confirmed_context(options=valid_options)).profile == (
        GenerationProfile.POV_CHARACTER
    )
    invalid_cases = [
        _fake_confirmed_context(action="world.extract", options=valid_options),
        _fake_confirmed_context(status="pending", options=valid_options),
        _fake_confirmed_context(stale=["context_changed"], options=valid_options),
        _fake_confirmed_context(options={**valid_options, "scene_id": None}),
        _fake_confirmed_context(
            options={**valid_options, "viewpoint_character_id": None}
        ),
        _fake_confirmed_context(options={**valid_options, "reveal_mode": "author_safe"}),
    ]
    for context in invalid_cases:
        assert resolver.resolve(context).profile == GenerationProfile.DEFAULT


def test_pov_parser_repairs_common_json_wrapper() -> None:
    from modules.writing.pov_generation import PovGenerationParser

    parsed = PovGenerationParser().parse(
        """```json
        {"perception":"听见警报","draft_prose":"她停下脚步",}
        ```"""
    )

    assert parsed.content == "她停下脚步"
    assert parsed.pov_view["perception"] == "听见警报"
    assert "json_repaired" in parsed.warnings


def test_pov_parser_rejects_empty_response() -> None:
    from modules.writing.pov_generation import PovGenerationParser

    with pytest.raises(ValueError):
        PovGenerationParser().parse("  ")


def test_character_reveal_guard_matches_normalized_hidden_text() -> None:
    from modules.writing.pov_generation import CharacterRevealGuard

    term = SimpleNamespace(
        phrase="林澈关闭了安全协议",
        rule="hidden_truth_match",
        severity="error",
        source_type="core_entity",
        source_id="entity-1",
        source_label="已过滤的隐藏事实",
    )
    validation = CharacterRevealGuard().validate(
        pov_view={
            "unsaid": "林澈　关闭了 安全协议",
            "dialogue_candidates": [{"line": "别动。"}],
        },
        draft_prose="正文",
        guard_terms=[term],
    )

    assert validation["status"] == "failed"
    assert validation["findings"][0]["field_path"] == "pov_view.unsaid"
    assert "林澈关闭了安全协议" not in validation["findings"][0]["source_label"]


# ============================================================
# Repository 测试
# ============================================================


class TestWritingDraftRepository:
    @pytest.mark.asyncio
    async def test_create(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        draft = await repo.create(db_session, sample_draft_data)
        assert draft.id is not None
        assert draft.novel_id is not None
        assert draft.chapter_index == 1
        assert draft.title == "第一章：开端"
        assert draft.content == "这是一个测试正文的段落。"
        assert draft.version_number == 1
        assert draft.status == "draft"

    @pytest.mark.asyncio
    async def test_create_auto_increment_version(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        v1 = await repo.create(db_session, sample_draft_data)
        assert v1.version_number == 1

        v2_data = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=sample_draft_data.chapter_index,
            title="第二章",
            content="第二版本内容",
        )
        v2 = await repo.create(db_session, v2_data)
        assert v2.version_number == 2

        v3_data = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=sample_draft_data.chapter_index,
            title="第三版",
            content="第三版本内容",
        )
        v3 = await repo.create(db_session, v3_data)
        assert v3.version_number == 3

    @pytest.mark.asyncio
    async def test_create_different_chapters_independent_versions(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        novel_id = sample_draft_data.novel_id
        await repo.create(db_session, sample_draft_data)

        ch1_v2 = WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=1,
            title="第一章第二版",
        )
        v2 = await repo.create(db_session, ch1_v2)
        assert v2.version_number == 2

        ch2_v1 = WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=2,
            title="第二章",
        )
        v1_ch2 = await repo.create(db_session, ch2_v1)
        assert v1_ch2.version_number == 1

    @pytest.mark.asyncio
    async def test_get(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        created = await repo.create(db_session, sample_draft_data)
        fetched = await repo.get(db_session, created.id)
        assert fetched is not None
        assert fetched.id == created.id

    @pytest.mark.parametrize(
        "operation",
        ["get", "update", "delete"],
        ids=["get", "update", "delete"],
    )
    @pytest.mark.asyncio
    async def test_not_found(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        update_data: WritingDraftUpdate,
        operation: str,
    ) -> None:
        fake_id = uuid.uuid4()
        if operation == "get":
            result = await repo.get(db_session, fake_id)
        elif operation == "update":
            result = await repo.update(db_session, fake_id, update_data)
        else:
            result = await repo.delete(db_session, fake_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_latest_by_chapter(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        novel_id = uuid.UUID(hex=sample_draft_data.novel_id)
        await repo.create(db_session, sample_draft_data)
        v2_data = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=1,
            title="最新版本",
            content="最新内容",
        )
        await repo.create(db_session, v2_data)

        latest = await repo.get_latest_by_chapter(db_session, novel_id, chapter_index=1)
        assert latest is not None
        assert latest.version_number == 2

    @pytest.mark.asyncio
    async def test_get_latest_by_chapter_no_draft(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
    ) -> None:
        latest = await repo.get_latest_by_chapter(
            db_session, uuid.uuid4(), chapter_index=1
        )
        assert latest is None

    @pytest.mark.asyncio
    async def test_get_version_history(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        novel_id = uuid.UUID(hex=sample_draft_data.novel_id)
        await repo.create(db_session, sample_draft_data)
        v2_data = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=1,
            title="第二版",
        )
        await repo.create(db_session, v2_data)

        versions = await repo.get_version_history(db_session, novel_id, chapter_index=1)
        assert len(versions) == 2
        assert versions[0].version_number == 2
        assert versions[1].version_number == 1

    @pytest.mark.asyncio
    async def test_update(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
        update_data: WritingDraftUpdate,
    ) -> None:
        created = await repo.create(db_session, sample_draft_data)
        updated = await repo.update(db_session, created.id, update_data)
        assert updated is not None
        assert updated.title == "更新后的标题"
        assert updated.content == "更新后的正文内容。"
        assert updated.version_number == 1

    @pytest.mark.asyncio
    async def test_update_partial(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        created = await repo.create(db_session, sample_draft_data)
        partial = WritingDraftUpdate(title="仅更新标题")
        updated = await repo.update(db_session, created.id, partial)
        assert updated is not None
        assert updated.title == "仅更新标题"
        assert updated.content == "这是一个测试正文的段落。"

    @pytest.mark.asyncio
    async def test_repository_rejects_published_in_place_update(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        published = await repo.create_with_status(
            db_session,
            sample_draft_data,
            status="published",
        )

        with pytest.raises(ValueError, match="published drafts cannot be updated"):
            await repo.update(
                db_session,
                published.id,
                WritingDraftUpdate(content="不应原地修改"),
            )

    @pytest.mark.asyncio
    async def test_delete(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        created = await repo.create(db_session, sample_draft_data)
        # Service 层负责至少保留一个活跃版本；repository 只负责软废弃。
        v2_data = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=1,
            title="第二版",
        )
        await repo.create(db_session, v2_data)

        deleted = await repo.delete(db_session, created.id)
        assert deleted is not None
        fetched = await repo.get(db_session, created.id)
        assert fetched is not None
        assert fetched.status == "deprecated"

    @pytest.mark.asyncio
    async def test_delete_last_version_allowed_in_repo(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """Repository 层不检查"至少保留 1 个版本"，该规则在 Service 层处理"""
        created = await repo.create(db_session, sample_draft_data)
        deleted = await repo.delete(db_session, created.id)
        assert deleted is not None

    @pytest.mark.asyncio
    async def test_delete_preserves_version_history(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        novel_id = uuid.UUID(hex=sample_draft_data.novel_id)
        await repo.create(db_session, sample_draft_data)
        v2 = await repo.create(
            db_session,
            WritingDraftCreate(
                novel_id=sample_draft_data.novel_id,
                chapter_index=1,
                title="v2",
                content="v2",
            ),
        )
        await repo.create(
            db_session,
            WritingDraftCreate(
                novel_id=sample_draft_data.novel_id,
                chapter_index=1,
                title="v3",
                content="v3",
            ),
        )
        # 删除是软废弃：版本号和可追溯历史都必须保持稳定。
        deleted = await repo.delete(db_session, v2.id)
        assert deleted is not None
        versions = await repo.get_version_history(db_session, novel_id, chapter_index=1)
        assert len(versions) == 3
        version_numbers = sorted([v.version_number for v in versions])
        assert version_numbers == [1, 2, 3]
        assert next(v for v in versions if v.id == v2.id).status == "deprecated"

    @pytest.mark.asyncio
    async def test_repeated_delete_preserves_original_status_provenance(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        created = await repo.create(db_session, sample_draft_data)

        await repo.delete(db_session, created.id)
        deleted_again = await repo.delete(db_session, created.id)

        assert deleted_again is not None
        assert deleted_again.status == "deprecated"
        assert deleted_again.provenance_json["deprecated_from_status"] == "draft"

    @pytest.mark.asyncio
    async def test_delete_all_versions(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        novel_id = uuid.UUID(hex=sample_draft_data.novel_id)
        await repo.create(db_session, sample_draft_data)
        await repo.create(
            db_session,
            WritingDraftCreate(
                novel_id=sample_draft_data.novel_id,
                chapter_index=1,
                title="v2",
                content="v2",
            ),
        )
        count = await repo.delete_all_versions(db_session, novel_id, 1)
        assert count == 2

    @pytest.mark.asyncio
    async def test_list_chapter_indices(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        nid = uuid.UUID(hex=novel_id)
        for ch in (1, 1, 3, 5):
            data = WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=ch,
                title=f"第{ch}章",
                content="内容",
            )
            await repo.create(db_session, data)
        indices = await repo.list_chapter_indices(db_session, nid)
        assert indices == [1, 3, 5]

    @pytest.mark.asyncio
    async def test_list_chapter_indices_empty(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
    ) -> None:
        indices = await repo.list_chapter_indices(db_session, uuid.uuid4())
        assert indices == []

    @pytest.mark.asyncio
    async def test_list_chapter_summaries_uses_latest_versions(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        nid = uuid.UUID(hex=novel_id)
        await repo.create(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=1,
                title="旧标题",
                content="旧",
            ),
        )
        await repo.create(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=1,
                title="新标题",
                content="新版正文",
            ),
        )
        await repo.create(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=2,
                title="第二章",
                content="第二章正文",
            ),
        )

        summaries = await repo.list_chapter_summaries(db_session, nid)

        assert [item.chapter_index for item in summaries] == [1, 2]
        assert summaries[0].title == "新标题"
        assert summaries[0].version_number == 2
        assert summaries[0].content == "新版正文"


# ============================================================
# Service 测试
# ============================================================


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


class TestWritingDraftService:
    """测试业务逻辑层 — repo 用 AsyncMock 替换"""

    @pytest.mark.asyncio
    async def test_create_draft(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        draft = _make_draft(novel_id=uuid.UUID(sample_draft_data.novel_id))
        repo = MagicMock()
        repo.create = AsyncMock(return_value=draft)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        resp = await service.create_draft(db, sample_draft_data)

        assert resp.id == str(draft.id)
        assert resp.novel_id == sample_draft_data.novel_id
        assert resp.chapter_index == 1
        assert resp.title == "第一章：开端"
        assert resp.version_number == 1
        repo.create.assert_awaited_once_with(db, sample_draft_data)

    @pytest.mark.asyncio
    async def test_create_draft_sanitizes_html_before_repo(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        async def _create(_db: object, data: WritingDraftCreate) -> object:
            return _make_draft(
                novel_id=uuid.UUID(data.novel_id),
                title=data.title,
                content=data.content,
            )

        repo = MagicMock()
        repo.create = AsyncMock(side_effect=_create)
        service = WritingDraftService(repo=repo)
        db = MagicMock()
        unsafe_data = sample_draft_data.model_copy(
            update={
                "title": "A < B",
                "content": (
                    "A < B\n<script>alert(1)</script>正文"
                    "<b>加粗</b><br>下一行 &lt;safe&gt;"
                ),
            }
        )

        resp = await service.create_draft(db, unsafe_data)

        passed = repo.create.await_args.args[1]
        assert passed.title == "A < B"
        assert passed.content == "A < B\n正文加粗\n下一行 &lt;safe&gt;"
        assert resp.content == "A < B\n正文加粗\n下一行 &lt;safe&gt;"
        assert "alert" not in resp.content
        assert "<script>" not in resp.content
        assert "<b>" not in resp.content

    @pytest.mark.asyncio
    async def test_get_draft(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        draft = _make_draft(novel_id=uuid.UUID(sample_draft_data.novel_id))
        repo = MagicMock()
        repo.get = AsyncMock(return_value=draft)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        fetched = await service.get_draft(db, str(draft.id), sample_draft_data.novel_id)

        assert fetched.id == str(draft.id)

    @pytest.mark.parametrize(
        "operation",
        ["get_draft", "update_draft", "delete_draft", "get_latest_draft"],
        ids=["get", "update", "delete", "get_latest"],
    )
    @pytest.mark.asyncio
    async def test_service_not_found(
        self,
        sample_draft_data: WritingDraftCreate,
        update_data: WritingDraftUpdate,
        operation: str,
    ) -> None:
        fake_id = str(uuid.uuid4())
        novel_id = sample_draft_data.novel_id
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        repo.get_latest_by_chapter = AsyncMock(return_value=None)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        with pytest.raises(NotFoundError) as exc_info:
            if operation == "get_draft":
                await service.get_draft(db, fake_id, novel_id)
            elif operation == "update_draft":
                await service.update_draft(db, fake_id, update_data, novel_id)
            elif operation == "delete_draft":
                await service.delete_draft(db, fake_id, novel_id)
            else:
                await service.get_latest_draft(db, novel_id, 1)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_draft(
        self,
        sample_draft_data: WritingDraftCreate,
        update_data: WritingDraftUpdate,
    ) -> None:
        draft = _make_draft(novel_id=uuid.UUID(sample_draft_data.novel_id))
        updated = _make_draft(
            id=draft.id,
            novel_id=draft.novel_id,
            title="更新后的标题",
            content="更新后的正文内容。",
        )
        repo = MagicMock()
        repo.get = AsyncMock(return_value=draft)
        repo.get_latest_by_chapter = AsyncMock(return_value=draft)
        repo.update = AsyncMock(return_value=updated)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        resp = await service.update_draft(
            db, str(draft.id), update_data, sample_draft_data.novel_id
        )

        assert resp.title == "更新后的标题"
        repo.update.assert_awaited_once_with(db, draft, update_data)

    @pytest.mark.asyncio
    async def test_update_draft_sanitizes_html_before_repo(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        draft = _make_draft(novel_id=uuid.UUID(sample_draft_data.novel_id))

        async def _update(
            _db: object,
            _draft: object,
            data: WritingDraftUpdate,
        ) -> object:
            return _make_draft(
                id=draft.id,
                novel_id=draft.novel_id,
                title=data.title,
                content=data.content,
            )

        repo = MagicMock()
        repo.get = AsyncMock(return_value=draft)
        repo.get_latest_by_chapter = AsyncMock(return_value=draft)
        repo.update = AsyncMock(side_effect=_update)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        resp = await service.update_draft(
            db,
            str(draft.id),
            WritingDraftUpdate(
                title="<i>更新</i>",
                content="A < B<script>alert(1)</script>正文<b>加粗</b>",
            ),
            sample_draft_data.novel_id,
        )

        passed = repo.update.await_args.args[2]
        assert passed.title == "更新"
        assert passed.content == "A < B正文加粗"
        assert resp.content == "A < B正文加粗"
        assert "alert" not in resp.content

    @pytest.mark.asyncio
    async def test_publish_draft_deduplicates_using_sanitized_content(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        latest = _make_draft(
            novel_id=uuid.UUID(sample_draft_data.novel_id),
            title="第一章",
            content="正文加粗",
            status="published",
        )
        repo = MagicMock()
        repo.get_latest_by_chapter = AsyncMock(return_value=latest)
        repo.create_with_status = AsyncMock()
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        resp = await service.publish_draft(
            db,
            WritingDraftCreate(
                novel_id=sample_draft_data.novel_id,
                chapter_index=1,
                title="<b>第一章</b>",
                content="正文<b>加粗</b>",
            ),
        )

        assert resp.id == str(latest.id)
        repo.create_with_status.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_draft_conflict_detection(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        v1 = _make_draft(
            novel_id=uuid.UUID(sample_draft_data.novel_id),
            version_number=1,
        )
        v2 = _make_draft(
            novel_id=uuid.UUID(sample_draft_data.novel_id),
            version_number=2,
        )
        repo = MagicMock()
        repo.get = AsyncMock(return_value=v1)
        repo.get_latest_by_chapter = AsyncMock(return_value=v2)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        conflict_update = WritingDraftUpdate(
            title="conflict",
            expected_version=1,
        )
        with pytest.raises(ConflictError) as exc_info:
            await service.update_draft(
                db, str(v1.id), conflict_update, sample_draft_data.novel_id
            )
        assert exc_info.value.status_code == 409
        assert "v2" in exc_info.value.detail or "2" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_update_draft_no_conflict_when_expected_version_matches(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        v1 = _make_draft(
            novel_id=uuid.UUID(sample_draft_data.novel_id),
            version_number=1,
        )
        updated = _make_draft(
            id=v1.id,
            novel_id=v1.novel_id,
            version_number=1,
            title="matched",
        )
        repo = MagicMock()
        repo.get = AsyncMock(return_value=v1)
        repo.get_latest_by_chapter = AsyncMock(return_value=v1)
        repo.update = AsyncMock(return_value=updated)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        matched_update = WritingDraftUpdate(
            title="matched",
            expected_version=1,
        )
        resp = await service.update_draft(
            db, str(v1.id), matched_update, sample_draft_data.novel_id
        )

        assert resp.title == "matched"
        assert resp.version_number == 1

    @pytest.mark.asyncio
    async def test_update_old_draft_conflicts_without_expected_version(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        v1 = _make_draft(
            novel_id=uuid.UUID(sample_draft_data.novel_id),
            version_number=1,
        )
        v2 = _make_draft(
            novel_id=uuid.UUID(sample_draft_data.novel_id),
            version_number=2,
        )
        repo = MagicMock()
        repo.get = AsyncMock(return_value=v1)
        repo.get_latest_by_chapter = AsyncMock(return_value=v2)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        no_check_update = WritingDraftUpdate(title="no check")
        with pytest.raises(ConflictError) as exc_info:
            await service.update_draft(
                db, str(v1.id), no_check_update, sample_draft_data.novel_id
            )

        assert exc_info.value.status_code == 409
        repo.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_draft(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        v2 = _make_draft(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(sample_draft_data.novel_id),
            version_number=2,
        )
        repo = MagicMock()
        repo.get = AsyncMock(return_value=v2)
        repo.count_working_versions = AsyncMock(return_value=2)
        repo.delete = AsyncMock(return_value=v2)
        repo.renumber_versions_after_delete = AsyncMock()
        service = WritingDraftService(repo=repo)
        db = AsyncMock()

        await service.delete_draft(db, str(v2.id), sample_draft_data.novel_id)

        repo.delete.assert_awaited_once_with(db, v2.id)
        repo.renumber_versions_after_delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_draft_last_version_rejected(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        v1 = _make_draft(
            novel_id=uuid.UUID(sample_draft_data.novel_id),
            version_number=1,
        )
        repo = MagicMock()
        repo.get = AsyncMock(return_value=v1)
        repo.count_working_versions = AsyncMock(return_value=1)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        with pytest.raises(ValidationError) as exc_info:
            await service.delete_draft(db, str(v1.id), sample_draft_data.novel_id)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_only_working_draft_is_not_unlocked_by_candidate(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        working = _make_draft(
            novel_id=uuid.UUID(sample_draft_data.novel_id),
            status="draft",
        )
        repo = MagicMock()
        repo.get = AsyncMock(return_value=working)
        repo.count_working_versions = AsyncMock(return_value=1)
        repo.delete = AsyncMock()
        service = WritingDraftService(repo=repo)

        with pytest.raises(ValidationError, match="last working version"):
            await service.delete_draft(
                AsyncMock(),
                str(working.id),
                sample_draft_data.novel_id,
            )

        repo.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_candidate_is_rejected_as_read_only_history(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        candidate = _make_draft(
            novel_id=uuid.UUID(sample_draft_data.novel_id),
            status="candidate",
        )
        repo = MagicMock()
        repo.get = AsyncMock(return_value=candidate)
        repo.delete = AsyncMock(return_value=candidate)
        service = WritingDraftService(repo=repo)
        db = AsyncMock()

        with pytest.raises(ConflictError, match="仅供预览"):
            await service.delete_draft(
                db,
                str(candidate.id),
                sample_draft_data.novel_id,
            )

        repo.count_working_versions.assert_not_called()
        repo.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_latest_draft(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        v2 = _make_draft(
            novel_id=uuid.UUID(sample_draft_data.novel_id),
            version_number=2,
        )
        repo = MagicMock()
        repo.get_latest_by_chapter = AsyncMock(return_value=v2)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        latest = await service.get_latest_draft(db, sample_draft_data.novel_id, 1)

        assert latest.version_number == 2

    @pytest.mark.asyncio
    async def test_get_version_history(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        versions = [
            _make_draft(
                novel_id=uuid.UUID(sample_draft_data.novel_id),
                version_number=3,
            ),
            _make_draft(
                novel_id=uuid.UUID(sample_draft_data.novel_id),
                version_number=2,
            ),
            _make_draft(
                novel_id=uuid.UUID(sample_draft_data.novel_id),
                version_number=1,
            ),
        ]
        repo = MagicMock()
        repo.get_version_history = AsyncMock(return_value=versions)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        history = await service.get_version_history(db, sample_draft_data.novel_id, 1)

        assert history.total == 3
        assert history.versions[0].version_number == 3

    @pytest.mark.asyncio
    async def test_get_version_history_empty(self) -> None:
        repo = MagicMock()
        repo.get_version_history = AsyncMock(return_value=[])
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        history = await service.get_version_history(db, str(uuid.uuid4()), 1)

        assert history.total == 0

    @pytest.mark.asyncio
    async def test_get_version_history_includes_review_and_archived_states(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        candidate = _make_draft(
            novel_id=uuid.UUID(sample_draft_data.novel_id),
            version_number=3,
            status="candidate",
        )
        deprecated = _make_draft(
            novel_id=uuid.UUID(sample_draft_data.novel_id),
            version_number=2,
            status="deprecated",
            provenance_json={"deprecated_from_status": "published"},
        )
        active = _make_draft(
            novel_id=uuid.UUID(sample_draft_data.novel_id),
            version_number=1,
            status="published",
        )
        repo = MagicMock()
        repo.get_version_history = AsyncMock(
            return_value=[candidate, deprecated, active]
        )

        history = await WritingDraftService(repo=repo).get_version_history(
            MagicMock(), sample_draft_data.novel_id, 1
        )

        assert history.total == 3
        assert [item.display_state for item in history.versions] == [
            "review",
            "archived",
            "active",
        ]
        assert history.versions[1].deprecated_from_status == "published"

    @pytest.mark.asyncio
    async def test_invalid_uuid(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        service = WritingDraftService()
        db = MagicMock()
        with pytest.raises(DomainError) as exc_info:
            await service.get_draft(db, "not-a-uuid", sample_draft_data.novel_id)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_get_draft_contract(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        draft = _make_draft(novel_id=uuid.UUID(sample_draft_data.novel_id))
        repo = MagicMock()
        repo.get = AsyncMock(return_value=draft)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        contract = await service.get_draft_contract(
            db,
            sample_draft_data.novel_id,
            str(draft.id),
        )

        assert contract is not None
        assert isinstance(contract, WritingDraftContract)
        assert contract.novel_id == sample_draft_data.novel_id
        assert contract.chapter_index == 1
        assert contract.title == "第一章：开端"

    @pytest.mark.asyncio
    async def test_get_draft_contract_not_found(self) -> None:
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        contract = await service.get_draft_contract(
            db,
            str(uuid.uuid4()),
            str(uuid.uuid4()),
        )

        assert contract is None

    @pytest.mark.asyncio
    async def test_get_latest_draft_contract(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        draft = _make_draft(novel_id=uuid.UUID(sample_draft_data.novel_id))
        repo = MagicMock()
        repo.get_latest_by_chapter = AsyncMock(return_value=draft)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        contract = await service.get_latest_draft_contract(
            db, sample_draft_data.novel_id, 1
        )

        assert contract is not None

    @pytest.mark.asyncio
    async def test_get_latest_draft_contract_not_found(self) -> None:
        repo = MagicMock()
        repo.get_latest_by_chapter = AsyncMock(return_value=None)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        contract = await service.get_latest_draft_contract(db, str(uuid.uuid4()), 1)

        assert contract is None

    @pytest.mark.asyncio
    async def test_list_chapter_indices(self) -> None:
        novel_id = str(uuid.uuid4())
        repo = MagicMock()
        repo.list_chapter_indices = AsyncMock(return_value=[1, 3, 5])
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        indices = await service.list_chapter_indices(db, novel_id)

        assert indices == [1, 3, 5]

    @pytest.mark.asyncio
    async def test_list_chapter_indices_empty(self) -> None:
        repo = MagicMock()
        repo.list_chapter_indices = AsyncMock(return_value=[])
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        indices = await service.list_chapter_indices(db, str(uuid.uuid4()))

        assert indices == []

    @pytest.mark.asyncio
    async def test_list_chapter_summaries_returns_word_counts(self) -> None:
        novel_id = str(uuid.uuid4())
        draft = _make_draft(
            novel_id=uuid.UUID(hex=novel_id),
            chapter_index=3,
            title="第三章",
            content="一二三四",
            version_number=4,
            status="published",
            updated_at=datetime(2026, 7, 3, tzinfo=UTC),
        )
        repo = MagicMock()
        repo.list_chapter_summaries = AsyncMock(return_value=[draft])
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        items = await service.list_chapter_summaries(db, novel_id)

        assert len(items) == 1
        assert items[0].chapter_index == 3
        assert items[0].title == "第三章"
        assert items[0].word_count == 4
        assert items[0].version_number == 4
        assert items[0].status == "published"

    @pytest.mark.asyncio
    async def test_delete_chapter(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        repo = MagicMock()
        repo.delete_all_versions = AsyncMock(return_value=1)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        count = await service.delete_chapter(db, sample_draft_data.novel_id, 1)

        assert count == 1


@pytest.mark.asyncio
async def test_split_chapter_at_offset_creates_new_chapter_without_publish_task(
    service: WritingDraftService,
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    original = await service.create_draft(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=5,
            title="第五章",
            content="前半段内容。后半段内容。",
        ),
    )

    result = await service.split_chapter_at_offset(
        db_session,
        novel_id=novel_id,
        chapter_index=5,
        split_pos=5,
        source_scene_id=None,
    )

    tasks_result = await db_session.execute(select(AsyncTask))
    assert len(tasks_result.scalars().all()) == 0

    assert result.source_chapter_index == 5
    assert result.new_chapter_index == 6
    assert result.source_draft.content == "前半段内容"
    assert result.new_draft.content == "。后半段内容。"
    assert result.source_draft.version_number == original.version_number
    assert result.new_draft.version_number == 1


@pytest.mark.asyncio
async def test_split_chapter_shifts_later_chapters(
    service: WritingDraftService,
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    await service.create_draft(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id, chapter_index=5, title="第五章", content="甲乙丙丁"
        ),
    )
    await service.create_draft(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id, chapter_index=6, title="第六章", content="原第六章"
        ),
    )
    await service.create_draft(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id, chapter_index=7, title="第七章", content="原第七章"
        ),
    )
    await service.create_draft(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id, chapter_index=8, title="第八章", content="原第八章"
        ),
    )

    engine = db_session.bind.sync_engine
    draft_updates: list[str] = []

    def count_draft_updates(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("update writing_drafts"):
            draft_updates.append(normalized)

    event.listen(engine, "before_cursor_execute", count_draft_updates)
    try:
        result = await service.split_chapter_at_offset(
            db_session,
            novel_id=novel_id,
            chapter_index=5,
            split_pos=2,
            source_scene_id=None,
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_draft_updates)

    assert result.new_chapter_index == 6
    indices = await service.list_chapter_indices(db_session, novel_id)
    assert indices == [5, 6, 7, 8, 9]
    assert (await service.get_latest_draft(db_session, novel_id, 7)).content == "原第六章"
    assert (await service.get_latest_draft(db_session, novel_id, 8)).content == "原第七章"
    assert (await service.get_latest_draft(db_session, novel_id, 9)).content == "原第八章"
    assert len(draft_updates) == 3


@pytest.mark.asyncio
async def test_split_chapter_at_offset_syncs_scene_chunks(
    service: WritingDraftService,
    db_session: AsyncSession,
) -> None:
    """跨模块测试：切分章节时同步切分 source Scene 的 chunk 并新建 Scene"""
    novel_id = str(uuid.uuid4())
    await service.create_draft(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=1,
            title="第一章",
            content="一二三四五六七八九十",
        ),
    )

    repo = SceneRepository()
    nid = uuid.UUID(hex=novel_id)
    source_scene = await repo.create(
        db_session,
        nid,
        SceneCreate(
            scene_index=0,
            title="Source Scene",
            chapter_ids=["1"],
            scene_chunks=[
                {"chapter_id": "1", "chapter_index": 1, "start_pos": 0, "end_pos": 10}
            ],
            status="draft",
        ),
    )
    await db_session.flush()

    result = await service.split_chapter_at_offset(
        db_session,
        novel_id=novel_id,
        chapter_index=1,
        split_pos=4,
        source_scene_id=str(source_scene.id),
    )

    assert result.source_chapter_index == 1
    assert result.new_chapter_index == 2
    assert result.source_draft.content == "一二三四"
    assert result.new_draft.content == "五六七八九十"
    assert len(result.scenes) >= 2

    source_id = str(source_scene.id)
    source_item = next(item for item in result.scenes if item.id == source_id)
    assert source_item.scene_chunks[0]["end_pos"] == 4

    new_item = next(item for item in result.scenes if item.id != source_id)
    assert new_item.chapter_ids == ["2"]
    assert new_item.scene_chunks[0]["chapter_id"] == "2"
    assert new_item.scene_chunks[0]["chapter_index"] == 2
    assert new_item.scene_index == source_item.scene_index + 1


@pytest.mark.asyncio
async def test_split_chapter_at_offset_uses_injected_scene_chunk_splitter(
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    calls: list[dict[str, object]] = []

    async def fake_split_scene_chunk_to_new_chapter(
        db: AsyncSession,
        passed_novel_id: str,
        *,
        source_scene_id: str,
        source_chapter_id: str,
        source_chapter_index: int,
        new_chapter_id: str,
        new_chapter_index: int,
        split_pos: int,
        new_chapter_length: int,
    ) -> list[dict[str, object]]:
        calls.append(
            {
                "db": db,
                "novel_id": passed_novel_id,
                "source_scene_id": source_scene_id,
                "source_chapter_id": source_chapter_id,
                "source_chapter_index": source_chapter_index,
                "new_chapter_id": new_chapter_id,
                "new_chapter_index": new_chapter_index,
                "split_pos": split_pos,
                "new_chapter_length": new_chapter_length,
            }
        )
        return [
            {
                "id": "fake-scene-2",
                "novel_id": passed_novel_id,
                "scene_index": 2,
                "title": "Injected Scene",
                "scene_chunks": [
                    {
                        "chapter_id": new_chapter_id,
                        "chapter_index": new_chapter_index,
                        "start_pos": 0,
                        "end_pos": new_chapter_length,
                    }
                ],
                "chapter_ids": [new_chapter_id],
            }
        ]

    service = WritingDraftService(
        split_scene_chunk_to_new_chapter=fake_split_scene_chunk_to_new_chapter
    )
    await service.create_draft(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=1,
            title="第一章",
            content="abcdEFGH",
        ),
    )

    result = await service.split_chapter_at_offset(
        db_session,
        novel_id=novel_id,
        chapter_index=1,
        split_pos=4,
        source_scene_id="fake-scene-1",
    )

    assert calls == [
        {
            "db": db_session,
            "novel_id": novel_id,
            "source_scene_id": "fake-scene-1",
            "source_chapter_id": "1",
            "source_chapter_index": 1,
            "new_chapter_id": "2",
            "new_chapter_index": 2,
            "split_pos": 4,
            "new_chapter_length": 4,
        }
    ]
    assert result.source_draft.content == "abcd"
    assert result.new_draft.content == "EFGH"
    assert result.scenes[0].id == "fake-scene-2"
    assert result.scenes[0].scene_chunks[0]["end_pos"] == 4


# ============================================================
# Facade 测试
# ============================================================


class TestWritingFacade:
    @pytest.mark.asyncio
    async def test_create_draft(
        self,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        draft, task_id = await create_draft(
            db_session,
            sample_draft_data.novel_id,
            sample_draft_data.chapter_index,
            sample_draft_data.title,
            sample_draft_data.content or "",
        )
        assert draft.id is not None
        assert isinstance(draft, WritingDraftContract)
        assert task_id is not None  # 发布任务也应创建
        assert draft.title == "第一章：开端"
        assert draft.chapter_index == 1

    @pytest.mark.asyncio
    async def test_get_draft(
        self,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        draft, _ = await create_draft(
            db_session,
            sample_draft_data.novel_id,
            sample_draft_data.chapter_index,
            sample_draft_data.title,
            sample_draft_data.content or "",
        )
        contract = await get_draft(db_session, sample_draft_data.novel_id, draft.id)
        assert contract is not None
        assert isinstance(contract, WritingDraftContract)
        assert contract.novel_id == sample_draft_data.novel_id

    @pytest.mark.asyncio
    async def test_get_draft_returns_none_for_other_novel(
        self,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        draft, _ = await create_draft(
            db_session,
            sample_draft_data.novel_id,
            sample_draft_data.chapter_index,
            sample_draft_data.title,
            sample_draft_data.content or "",
        )
        contract = await get_draft(db_session, str(uuid.uuid4()), draft.id)
        assert contract is None

    @pytest.mark.asyncio
    async def test_get_draft_not_found(
        self,
        db_session: AsyncSession,
    ) -> None:
        contract = await get_draft(db_session, str(uuid.uuid4()), str(uuid.uuid4()))
        assert contract is None

    @pytest.mark.asyncio
    async def test_get_latest_draft_for_chapter(
        self,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        await create_draft(
            db_session,
            sample_draft_data.novel_id,
            sample_draft_data.chapter_index,
            sample_draft_data.title,
            sample_draft_data.content or "",
        )
        contract = await get_latest_draft_for_chapter(
            db_session,
            sample_draft_data.novel_id,
            1,
        )
        assert contract is not None

    @pytest.mark.asyncio
    async def test_get_latest_draft_for_chapter_not_found(
        self,
        db_session: AsyncSession,
    ) -> None:
        contract = await get_latest_draft_for_chapter(db_session, str(uuid.uuid4()), 1)
        assert contract is None

    @pytest.mark.asyncio
    async def test_list_latest_drafts_for_chapters_returns_latest_requested_versions(
        self,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await create_draft(db_session, novel_id, 1, "第一章 v1", "旧内容")
        await create_draft(db_session, novel_id, 1, "第一章 v2", "新内容")
        await create_draft(db_session, novel_id, 2, "第二章", "不应返回")
        await create_draft(db_session, novel_id, 3, "第三章", "第三章内容")

        drafts = await list_latest_drafts_for_chapters(
            db_session,
            novel_id,
            [3, 1, 99],
        )

        assert [draft.chapter_index for draft in drafts] == [1, 3]
        assert [draft.title for draft in drafts] == ["第一章 v2", "第三章"]
        assert [draft.content for draft in drafts] == ["新内容", "第三章内容"]
        assert [draft.version_number for draft in drafts] == [2, 1]
        assert [draft.status for draft in drafts] == ["published", "published"]
        assert all(isinstance(draft, WritingDraftContract) for draft in drafts)
        assert all(draft.id for draft in drafts)
        assert all(draft.created_at is not None for draft in drafts)
        assert all(draft.updated_at is not None for draft in drafts)

    @pytest.mark.asyncio
    async def test_list_latest_drafts_for_chapters_truncates_latest_content(
        self,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        service = WritingDraftService()
        await service.create_published_draft(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=1,
                title="第一章 v1",
                content="old-contents",
            ),
        )
        latest = await service.create_published_draft(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=1,
                title="第一章 v2",
                content="new-contents",
                provenance_json={"source": "projection-test"},
            ),
        )
        await service.set_conflict_check_snapshot(
            db_session,
            latest.id,
            novel_id,
            {"source": {"module": "writing-test"}},
        )
        await service.create_published_draft(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=2,
                title="第二章",
                content="chapter-two",
            ),
        )

        drafts = await list_latest_drafts_for_chapters(
            db_session,
            novel_id,
            [2, 1],
            content_limit=4,
        )

        assert [draft.chapter_index for draft in drafts] == [1, 2]
        assert [draft.title for draft in drafts] == ["第一章 v2", "第二章"]
        assert [draft.content for draft in drafts] == ["new-", "chap"]
        assert [draft.version_number for draft in drafts] == [2, 1]
        assert [draft.status for draft in drafts] == ["published", "published"]
        assert drafts[0].id == latest.id
        assert drafts[0].provenance_json == {"source": "projection-test"}
        assert drafts[0].conflict_check_snapshot_json == {
            "source": {"module": "writing-test"}
        }
        assert drafts[0].created_at is not None
        assert drafts[0].updated_at is not None

    @pytest.mark.asyncio
    async def test_list_chapter_indices(
        self,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        for ch in (1, 1, 3, 5):
            await create_draft(db_session, novel_id, ch, f"第{ch}章", "内容")
        indices = await list_chapter_indices(db_session, novel_id)
        assert indices == [1, 3, 5]

    @pytest.mark.asyncio
    async def test_list_chapter_indices_empty(
        self,
        db_session: AsyncSession,
    ) -> None:
        indices = await list_chapter_indices(db_session, str(uuid.uuid4()))
        assert indices == []

    @pytest.mark.asyncio
    async def test_list_project_writing_stats_batches_latest_versions(
        self,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())
        missing_id = str(uuid.uuid4())
        await create_draft(db_session, novel_id, 1, "第一章 v1", "旧稿")
        await create_draft(db_session, novel_id, 1, "第一章 v2", "新稿内容")
        await create_draft(db_session, novel_id, 2, "第二章", "第二")
        await create_draft(db_session, other_id, 1, "另一项目", "其他")

        stats = await list_project_writing_stats(
            db_session,
            [novel_id, missing_id, other_id],
        )

        assert stats[novel_id].chapter_count == 2
        assert stats[novel_id].word_count == 6
        assert stats[missing_id].chapter_count == 0
        assert stats[missing_id].word_count == 0
        assert stats[other_id].chapter_count == 1
        assert stats[other_id].word_count == 2


# ============================================================
# API 路由测试
# ============================================================


async def _create_api_project(async_client: AsyncClient) -> str:
    response = await async_client.post(
        "/api/projects",
        json={"title": "Writing API test project"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestWritingSplitApi:
    @pytest.mark.asyncio
    async def test_split_chapter_endpoint(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """POST /api/writing/chapters/{chapter_index}/split 返回切分结果"""
        novel_id = await _create_api_project(async_client)
        service = WritingDraftService()
        await service.create_draft(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=1,
                title="第一章",
                content="abcdefghij",
            ),
        )

        repo = SceneRepository()
        scene = await repo.create(
            db_session,
            uuid.UUID(hex=novel_id),
            SceneCreate(
                scene_index=0,
                title="Scene 1",
                chapter_ids=["1"],
                scene_chunks=[
                    {"chapter_id": "1", "chapter_index": 1, "start_pos": 0, "end_pos": 10}
                ],
                status="draft",
            ),
        )
        await db_session.flush()

        response = await async_client.post(
            f"/api/writing/chapters/1/split?novel_id={novel_id}",
            json={"split_pos": 4, "source_scene_id": str(scene.id)},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["source_chapter_index"] == 1
        assert data["new_chapter_index"] == 2
        assert data["source_draft"]["content"] == "abcd"
        assert data["new_draft"]["content"] == "efghij"
        assert len(data["scenes"]) >= 2


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
        assert [
            item["version_number"] for item in history.json()["versions"]
        ] == [3, 2, 1]
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
    from modules.context.facade import confirm_context
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
async def test_writing_generation_saves_secret_safe_managed_llm_provenance(
    db_session: AsyncSession,
) -> None:
    import json

    from infrastructure.llm.agent_step_harness import MANAGED_LLM_PROVENANCE_KEY
    from modules.context.facade import confirm_context
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
    from modules.context.facade import confirm_context
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
) -> None:
    """AI 正文生成任务创建的候选稿可追踪到确认记录与任务。"""
    from modules.context.facade import confirm_context
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
            settings={
                "llm": {
                    "api_key": "sk-test-only",
                    "base_url": "https://llm.test/v1",
                    "model": "test-model",
                }
            },
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
        status="pending",
        meta={
            "novel_id": novel_id,
            "chapter_index": 4,
            "context_confirmation_id": confirmation.id,
        },
    )
    db_session.add(task)
    await db_session.flush()

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
    from modules.context.facade import confirm_context
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
          "perception": "秦岚听见警报声。",
          "interpretation": "她判断控制台被人动过。",
          "inner_monologue": "她还不知道真正的幕后。",
          "true_intention": "先稳住现场。",
          "action": "她靠近控制台。",
          "expression": "神色收紧。",
          "dialogue_candidates": [
            {"line": "别碰控制台。", "tone": "冷静", "subtext": "试探"}
          ],
          "subtext": "她在试探对方。",
          "unsaid": "首领是国王",
          "draft_prose": "秦岚听见警报声，抬手制止了靠近控制台的人。"
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
    assert provenance["model"] == "fake-pov-model"
    assert provenance["pov_view"]["unsaid"] == "首领是国王"
    assert provenance["pov_validation"]["status"] == "failed"
    finding = provenance["pov_validation"]["findings"][0]
    assert finding["field_path"] == "pov_view.unsaid"
    assert finding["source_type"] == "core_entity"
    assert finding["source_id"] == str(target_id)
    assert finding["redacted"] is True
    assert "首领是国王" not in finding["source_label"]
    prompt_text = llm.requests[0].messages[1].content
    assert "首领是国王" not in prompt_text


@pytest.mark.asyncio
async def test_writing_generation_pov_parse_failure_keeps_raw_candidate(
    db_session: AsyncSession,
) -> None:
    """Bad POV JSON still creates a raw candidate when LLM returned useful text."""
    from modules.context.facade import confirm_context
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
    assert draft.provenance_json["pov_validation"]["status"] == "passed"
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
    from modules.rag.repositories import RagChunkRepository
    from modules.writing.facade import create_draft
    from modules.writing.tasks import handle_publish_chapter

    rag_repo = RagChunkRepository()
    nid_uuid = uuid.UUID(hex=test_project_id)
    embed_exc = Exception("embedding down")

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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

        result = await handle_publish_chapter(db_session, task)
        assert result["rag_chunks"] > 0

    first_chunks = await rag_repo.find_by_chapter(db_session, nid_uuid, 1)
    assert len(first_chunks) == result["rag_chunks"]
    assert all("一切都变得陌生" in c.text for c in first_chunks)

    # 重新发布同一章节
    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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
        result_2 = await handle_publish_chapter(db_session, task_2)
        assert result_2["rag_chunks"] > 0

    second_chunks = await rag_repo.find_by_chapter(db_session, nid_uuid, 1)
    assert len(second_chunks) == result_2["rag_chunks"]
    assert all("世界已经完全不同" in c.text for c in second_chunks)
    assert all("一切都变得陌生" not in c.text for c in second_chunks)
