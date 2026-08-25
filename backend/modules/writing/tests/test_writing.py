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
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, DomainError, NotFoundError, ValidationError
from infrastructure.llm.schemas import LLMCallResponse
from modules.writing.contracts import WritingDraftContract
from modules.writing.facade import (
    create_draft,
    get_draft,
    get_latest_draft_for_chapter,
    list_chapter_indices,
    list_effective_chapter_indices,
    list_latest_drafts_for_chapters,
    list_project_writing_stats,
)
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import (
    WritingDraftCreate,
    WritingDraftUpdate,
    WritingPublishRequest,
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
                "list_latest_drafts_for_chapters, get_project_writing_stats, "
                "lock_chapter_versions_for_revalidation; "
                "from infrastructure.tasks.worker import TaskWorker; "
                "print(list_latest_drafts_for_chapters.__name__, "
                "get_project_writing_stats.__name__, "
                "lock_chapter_versions_for_revalidation.__name__, "
                "TaskWorker.__name__)"
            ),
        ],
        cwd=backend_root,
        check=False,
        text=True,
        capture_output=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert (
        "list_latest_drafts_for_chapters get_project_writing_stats "
        "lock_chapter_versions_for_revalidation TaskWorker"
    ) in result.stdout


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
            assert node.module != "modules.story.outline_state.facade"
        elif isinstance(node, ast.Import):
            assert all(
                alias.name != "modules.story.outline_state.facade" for alias in node.names
            )


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
        {
          "pov_state": {
            "perceived_facts": ["听见警报"],
            "interpretation": "有人触发了系统",
            "current_intention": "先查看控制台",
            "withheld_known_information": []
          },
          "draft_prose": "她停下脚步",
          "uncertainties": [],
        }
        ```"""
    )

    assert parsed.content == "她停下脚步"
    assert parsed.pov_view["pov_state"]["perceived_facts"] == ["听见警报"]
    assert "json_repaired" in parsed.warnings


def test_pov_parser_repairs_missing_comma_before_uncertainties() -> None:
    """真实 provider 偶发漏掉顶层字段间逗号时仍提取正文。"""
    from modules.writing.pov_generation import PovGenerationParser

    parsed = PovGenerationParser().parse(
        """{
          "pov_state": {
            "perceived_facts": ["听见第二块亵渎石板"],
            "interpretation": "信息来源仍不明确",
            "current_intention": "维持镇定",
            "withheld_known_information": []
          },
          "draft_prose": "他没有立刻追问。"
          "uncertainties": ["消息来源未知"]
        }"""
    )

    assert parsed.content == "他没有立刻追问。"
    assert parsed.pov_view["uncertainties"] == ["消息来源未知"]
    assert "json_repaired" in parsed.warnings


def test_pov_prompt_uses_limited_viewpoint_without_prose_templates() -> None:
    from modules.writing.pov_generation import (
        POV_SYSTEM_PROMPT,
        build_pov_generation_prompt,
    )

    prompt = build_pov_generation_prompt(
        chapter_index=3,
        instruction="保持克制",
        context_markdown="## POV 角色档案\n\n- 姓名: 秦岚",
        base_content="警报响起前，秦岚正在核对日志。",
    )

    assert "不等于必须使用第一人称" in POV_SYSTEM_PROMPT
    assert "不是分步推理过程" in POV_SYSTEM_PROMPT
    assert "不预设字数、段落" in POV_SYSTEM_PROMPT
    assert "当前 Scene" in POV_SYSTEM_PROMPT
    assert "不能扩大输出范围" in POV_SYSTEM_PROMPT
    assert "<writing_request>" in prompt
    assert "<character_safe_context_json>" in prompt
    assert "<locked_existing_chapter_json>" in prompt
    assert "警报响起前，秦岚正在核对日志。" in prompt
    assert "完整替换候选" in prompt
    assert '"pov_state"' in prompt
    assert '"withheld_known_information"' in prompt
    assert '"uncertainties"' in prompt
    assert '"inner_monologue"' not in prompt
    assert '"dialogue_candidates"' not in prompt


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
            "pov_state": {"withheld_known_information": ["林澈　关闭了 安全协议"]},
            "uncertainties": [],
        },
        draft_prose="正文",
        guard_terms=[term],
    )

    assert validation["status"] == "failed"
    assert validation["findings"][0]["field_path"] == (
        "pov_view.pov_state.withheld_known_information[0]"
    )
    assert "林澈关闭了安全协议" not in validation["findings"][0]["source_label"]


# ============================================================
# Repository 测试
# ============================================================


class TestWritingDraftRepository:
    @pytest.mark.asyncio
    async def test_create_many_reads_versions_once_and_flushes_once(self) -> None:
        novel_id = uuid.uuid4()
        rows = MagicMock()
        rows.all.return_value = [(1, 3)]
        db = MagicMock()
        db.get_bind.return_value = SimpleNamespace(
            dialect=SimpleNamespace(name="sqlite")
        )
        db.execute = AsyncMock(return_value=rows)
        db.flush = AsyncMock()
        items = [
            WritingDraftCreate(
                novel_id=str(novel_id),
                chapter_index=chapter,
                content=f"chapter-{chapter}",
            )
            for chapter in range(1, 101)
        ]

        drafts = await WritingDraftRepository().create_many_with_status(
            db,
            items,
            status="published",
        )

        assert len(drafts) == 100
        assert drafts[0].version_number == 4
        assert drafts[-1].version_number == 1
        db.execute.assert_awaited_once()
        db.flush.assert_awaited_once()
        db.add_all.assert_called_once_with(drafts)

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
    async def test_effective_chapter_indices_ignore_latest_blank_body(
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
                content="曾经有正文",
            ),
        )
        await repo.create(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=1,
                content=" \n\t\u3000",
            ),
        )
        await repo.create(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=2,
                content="有效正文",
            ),
        )

        assert await repo.list_chapter_indices(db_session, nid) == [1, 2]
        assert await repo.list_effective_chapter_indices(db_session, nid) == [2]

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
        repo.get_for_update = AsyncMock(return_value=draft)
        repo.lock_version_chapters_for_revalidation = AsyncMock()
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
        repo.get_for_update = AsyncMock(return_value=draft)
        repo.lock_version_chapters_for_revalidation = AsyncMock()
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
        repo.lock_version_chapters_for_revalidation = AsyncMock()
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
        repo.get_for_update = AsyncMock(return_value=v1)
        repo.lock_version_chapters_for_revalidation = AsyncMock()
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
        repo.get_for_update = AsyncMock(return_value=v1)
        repo.lock_version_chapters_for_revalidation = AsyncMock()
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
        repo.get_for_update = AsyncMock(return_value=v1)
        repo.lock_version_chapters_for_revalidation = AsyncMock()
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
    async def test_update_draft_serializes_before_latest_validation(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        draft = _make_draft(novel_id=uuid.UUID(sample_draft_data.novel_id))
        repo = MagicMock()
        repo.get = AsyncMock(return_value=draft)
        repo.get_for_update = AsyncMock(return_value=draft)
        repo.lock_version_chapters_for_revalidation = AsyncMock()
        repo.get_latest_by_chapter = AsyncMock(return_value=draft)
        repo.update = AsyncMock(return_value=draft)
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        await service.update_draft(
            db,
            str(draft.id),
            WritingDraftUpdate(title="t"),
            sample_draft_data.novel_id,
        )

        repo.lock_version_chapters_for_revalidation.assert_awaited_once_with(
            db, draft.novel_id, [draft.chapter_index]
        )
        repo.get_for_update.assert_awaited_once_with(db, draft.id)
        repo.get_latest_by_chapter.assert_awaited_once_with(
            db, draft.novel_id, draft.chapter_index
        )

    @pytest.mark.asyncio
    async def test_publish_without_draft_id_still_checks_expected_snapshot(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        latest = _make_draft(
            novel_id=uuid.UUID(sample_draft_data.novel_id),
            version_number=3,
            status="published",
        )
        repo = MagicMock()
        repo.get_latest_by_chapter = AsyncMock(return_value=latest)
        repo.lock_version_chapters_for_revalidation = AsyncMock()
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        stale_request = WritingPublishRequest(
            novel_id=sample_draft_data.novel_id,
            chapter_index=1,
            title="第一章",
            content="全新正文",
            expected_version=2,
        )
        with pytest.raises(ConflictError) as exc_info:
            await service.publish_draft(db, stale_request)

        assert exc_info.value.status_code == 409
        repo.get_latest_by_chapter.assert_awaited_once_with(db, latest.novel_id, 1)

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
        repo.get_for_update = AsyncMock(return_value=v2)
        repo.lock_version_chapters_for_revalidation = AsyncMock()
        repo.count_working_versions = AsyncMock(return_value=2)
        repo.delete = AsyncMock(return_value=v2)
        repo.renumber_versions_after_delete = AsyncMock()
        service = WritingDraftService(repo=repo)
        db = MagicMock()
        db.flush = AsyncMock()

        await service.delete_draft(db, str(v2.id), sample_draft_data.novel_id)

        repo.lock_version_chapters_for_revalidation.assert_awaited_once_with(
            db,
            v2.novel_id,
            [v2.chapter_index],
        )
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
        repo.get_for_update = AsyncMock(return_value=v1)
        repo.lock_version_chapters_for_revalidation = AsyncMock()
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
        repo.get_for_update = AsyncMock(return_value=working)
        repo.lock_version_chapters_for_revalidation = AsyncMock()
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
    async def test_delete_candidate_rejects_it_into_read_only_history(
        self,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        candidate = _make_draft(
            novel_id=uuid.UUID(sample_draft_data.novel_id),
            status="candidate",
        )
        repo = MagicMock()
        repo.get = AsyncMock(return_value=candidate)
        repo.get_for_update = AsyncMock(return_value=candidate)
        repo.lock_version_chapters_for_revalidation = AsyncMock()
        repo.delete = AsyncMock(return_value=candidate)
        service = WritingDraftService(repo=repo)
        db = MagicMock()
        db.flush = AsyncMock()

        await service.delete_draft(
            db,
            str(candidate.id),
            sample_draft_data.novel_id,
        )

        repo.count_working_versions.assert_not_called()
        repo.delete.assert_awaited_once_with(db, candidate.id)
        assert candidate.provenance_json["rejected_by"] == "author"
        assert candidate.provenance_json["rejected_at"]

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
        repo.get_version_history = AsyncMock(return_value=[candidate, deprecated, active])

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
    async def test_list_effective_chapter_indices(self) -> None:
        novel_id = str(uuid.uuid4())
        repo = MagicMock()
        repo.list_effective_chapter_indices = AsyncMock(return_value=[2, 4])
        service = WritingDraftService(repo=repo)
        db = MagicMock()

        indices = await service.list_effective_chapter_indices(db, novel_id)

        assert indices == [2, 4]

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
    async def test_list_effective_chapter_indices(
        self,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await create_draft(db_session, novel_id, 1, "占位", " \n\u3000")
        await create_draft(db_session, novel_id, 2, "正文", "有效正文")

        assert await list_effective_chapter_indices(db_session, novel_id) == [2]

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
