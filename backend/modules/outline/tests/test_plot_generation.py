"""PlotGenerationService 测试"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.services import PlotGenerationService

from tests.conftest import test_project_id  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture
def service() -> PlotGenerationService:
    return PlotGenerationService()


async def _create_draft(db: AsyncSession, novel_id: str, chapter_index: int) -> None:
    """Helper: 创建测试草稿"""
    from modules.writing.models import WritingDraft

    draft = WritingDraft(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        chapter_index=chapter_index,
        title=f"第{chapter_index}章",
        content=f"第{chapter_index}章的正文内容。主角在冒险。",
        version_number=1,
        status="draft",
    )
    db.add(draft)
    await db.flush()


class TestPlotGenerationService:
    """PlotGenerationService 测试"""

    async def test_generate_empty_when_no_draft(
        self,
        db_session: AsyncSession,
        test_project_id: str,
        service: PlotGenerationService,
    ):
        """RED: 无章节正文时返回空结果"""
        result = await service.generate(
            db_session, test_project_id, start_chapter=1, end_chapter=5,
        )

        assert result["total_threads"] == 0
        assert result["total_arcs"] == 0
        assert result["threads"] == []
        assert result["arcs"] == []

    async def test_generate_includes_existing_context(
        self,
        db_session: AsyncSession,
        test_project_id: str,
        service: PlotGenerationService,
    ):
        """RED: 已有剧情线和篇章纲应包含在 LLM prompt 中"""
        # 1. 创建一个已有的 thread
        from modules.outline.schemas import PlotThreadCreate

        thread_svc = service._thread_service
        await thread_svc.create(
            db_session, test_project_id,
            PlotThreadCreate(name="已有主线", thread_type="main", summary="已有摘要", visible_goal="目标"),
        )

        # 2. 创建草稿
        await _create_draft(db_session, test_project_id, 1)

        # 3. Mock LLM 并捕获 prompt
        captured_prompt = None

        async def _mock_gen(request, output_cls):
            nonlocal captured_prompt
            captured_prompt = request.messages[0].content
            fake = type("PlotOutput", (), {"plot_threads": [], "outline_arcs": []})()
            return fake

        with patch("infrastructure.llm.client.LLMClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.generate_structured = _mock_gen
            mock_cls.return_value = mock_client

            await service.generate(
                db_session, test_project_id, start_chapter=1, end_chapter=1,
            )

        # 4. 验证 prompt 包含已有剧情线信息
        assert captured_prompt is not None, "应捕获到 LLM prompt"
        assert "已有主线" in captured_prompt, "已有剧情线名称应在 prompt 中"
        assert "已有摘要" in captured_prompt, "已有剧情线摘要应在 prompt 中"

    async def test_generate_updates_existing(
        self,
        db_session: AsyncSession,
        test_project_id: str,
        service: PlotGenerationService,
    ):
        """RED: existing_id 非空时更新已有记录而非创建"""
        from modules.outline.schemas import PlotThreadCreate, OutlineArcCreate

        # 1. 创建已有 thread 和 arc
        thread_svc = service._thread_service
        arc_svc = service._arc_service
        existing_thread = await thread_svc.create(
            db_session, test_project_id,
            PlotThreadCreate(name="旧主线", thread_type="main", summary="旧摘要", visible_goal="旧目标"),
        )
        existing_arc = await arc_svc.create(
            db_session, test_project_id,
            OutlineArcCreate(
                title="旧篇章", arc_index=1,
                start_chapter=1, end_chapter=3,
                arc_goal="旧目标", core_conflict="旧冲突",
                climax="旧高潮", result="旧结果",
            ),
        )

        # 2. 创建草稿
        await _create_draft(db_session, test_project_id, 1)

        # 3. Mock LLM 返回带 existing_id 的结果
        fake = type("PlotOutput", (), {
            "plot_threads": [
                type("T", (), {
                    "name": "旧主线", "thread_type": "main",
                    "summary": "新摘要", "visible_goal": "新目标",
                    "start_chapter": 1, "planned_payoff_chapter": 10,
                    "existing_id": str(existing_thread.id),
                })(),
            ],
            "outline_arcs": [
                type("A", (), {
                    "title": "旧篇章", "arc_index": 1,
                    "start_chapter": 1, "end_chapter": 5,
                    "arc_goal": "新目标", "core_conflict": "新冲突",
                    "climax": "新高潮", "result": "新结果",
                    "existing_id": str(existing_arc.id),
                })(),
            ],
        })()

        with patch("infrastructure.llm.client.LLMClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.generate_structured = AsyncMock(return_value=fake)
            mock_cls.return_value = mock_client

            result = await service.generate(
                db_session, test_project_id, start_chapter=1, end_chapter=1,
            )

        # 4. 验证：更新不产生新记录
        assert result["total_threads"] == 0, "更新应不产生新 thread"
        assert result["total_arcs"] == 0, "更新应不产生新 arc"

        # 5. 验证 DB 中数据已更新
        from sqlalchemy import select
        from modules.outline.models import PlotThread, OutlineArc

        nid_uuid = uuid.UUID(hex=test_project_id)
        threads = (await db_session.execute(
            select(PlotThread).where(PlotThread.novel_id == nid_uuid)
        )).scalars().all()
        assert len(threads) == 1, "不应新增 thread"
        assert threads[0].summary == "新摘要", "摘要应已更新"
        assert threads[0].visible_goal == "新目标", "目标应已更新"

        arcs = (await db_session.execute(
            select(OutlineArc).where(OutlineArc.novel_id == nid_uuid)
        )).scalars().all()
        assert len(arcs) == 1, "不应新增 arc"
        assert arcs[0].arc_goal == "新目标", "目标应已更新"
        assert arcs[0].end_chapter == 5, "end_chapter 应已更新"

    async def test_facade_delegates_to_service(
        self,
        db_session: AsyncSession,
        test_project_id: str,
    ):
        """RED: facade.generate_plot_structure 应正确委托给服务"""
        from modules.outline.facade import generate_plot_structure

        await _create_draft(db_session, test_project_id, 1)

        fake = type("PlotOutput", (), {
            "plot_threads": [
                type("T", (), {
                    "name": "主线", "thread_type": "main",
                    "summary": "冒险", "visible_goal": "真相",
                    "start_chapter": 1, "planned_payoff_chapter": None,
                    "existing_id": None,
                })(),
            ],
            "outline_arcs": [],
        })()

        with patch("infrastructure.llm.client.LLMClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.generate_structured = AsyncMock(return_value=fake)
            mock_cls.return_value = mock_client

            result = await generate_plot_structure(
                db_session, test_project_id, 1, 1,
            )

        assert result["total_threads"] == 1
        assert result["threads"][0]["name"] == "主线"

    async def test_generate_creates_threads_and_arcs(
        self,
        db_session: AsyncSession,
        test_project_id: str,
        service: PlotGenerationService,
    ):
        """RED: 调用 LLM 后应创建剧情线和篇章纲"""
        # 1. 准备测试数据
        await _create_draft(db_session, test_project_id, 1)
        await _create_draft(db_session, test_project_id, 2)

        # 2. Mock LLM
        fake_output = type(
            "PlotOutput",
            (),
            {
                "plot_threads": [
                    type(
                        "Thread",
                        (),
                        {
                            "name": "主线",
                            "thread_type": "main",
                            "summary": "主角的冒险",
                            "visible_goal": "找到真相",
                            "start_chapter": 1,
                            "planned_payoff_chapter": 10,
                            "existing_id": None,
                        },
                    )(),
                ],
                "outline_arcs": [
                    type(
                        "Arc",
                        (),
                        {
                            "title": "第一章弧",
                            "arc_index": 1,
                            "start_chapter": 1,
                            "end_chapter": 5,
                            "arc_goal": "引入世界",
                            "core_conflict": "未知",
                            "climax": "发现线索",
                            "result": "踏上旅程",
                            "existing_id": None,
                        },
                    )(),
                ],
            },
        )

        with patch(
            "infrastructure.llm.client.LLMClient",
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.generate_structured = AsyncMock(return_value=fake_output)
            mock_cls.return_value = mock_client

            # 3. 执行
            result = await service.generate(
                db_session, test_project_id, start_chapter=1, end_chapter=2,
            )

        # 4. 验证
        assert result["total_threads"] == 1
        assert result["total_arcs"] == 1
        assert len(result["threads"]) == 1
        assert len(result["arcs"]) == 1
        assert result["threads"][0]["name"] == "主线"
        assert result["arcs"][0]["title"] == "第一章弧"

        # 5. 验证 DB 中确实有数据
        from sqlalchemy import select
        from modules.outline.models import PlotThread, OutlineArc

        nid = uuid.UUID(hex=test_project_id)
        thread_result = await db_session.execute(
            select(PlotThread).where(PlotThread.novel_id == nid)
        )
        threads = thread_result.scalars().all()
        assert len(threads) == 1
        assert threads[0].name == "主线"

        arc_result = await db_session.execute(
            select(OutlineArc).where(OutlineArc.novel_id == nid)
        )
        arcs = arc_result.scalars().all()
        assert len(arcs) == 1
        assert arcs[0].title == "第一章弧"
