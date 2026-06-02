from __future__ import annotations

from unittest import mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


class TestImportsOutlineIntegration:
    """T5: Import 工作流触发生成大纲"""

    @pytest.mark.asyncio
    async def test_deep_import_calls_outline_generation(
        self, db_session: AsyncSession, sample_novel_id: str,
    ) -> None:
        """深度导入的 _generate_plot 应调用 outline.facade.generate_plot_structure"""
        from modules.imports.workflow import DeepImportWorkflow

        workflow = DeepImportWorkflow()

        with mock.patch(
            "modules.outline.facade.generate_plot_structure",
        ) as mock_gen:
            mock_gen.return_value = {
                "total_threads": 3,
                "total_arcs": 2,
                "threads": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                "arcs": [{"id": "x"}, {"id": "y"}],
            }

            result = await workflow._generate_plot(
                db_session, sample_novel_id,
                start_chapter=1, end_chapter=10,
            )

        mock_gen.assert_called_once_with(
            db_session, sample_novel_id,
            start_chapter=1, end_chapter=10,
        )
        assert result["total_threads"] == 3
        assert result["total_arcs"] == 2

    @pytest.mark.asyncio
    async def test_generate_plot_failure_graceful(
        self, db_session: AsyncSession, sample_novel_id: str,
    ) -> None:
        """outline 生成失败时应优雅降级，不抛异常"""
        from modules.imports.workflow import DeepImportWorkflow

        workflow = DeepImportWorkflow()

        with mock.patch(
            "modules.outline.facade.generate_plot_structure",
            side_effect=Exception("LLM timeout"),
        ):
            result = await workflow._generate_plot(
                db_session, sample_novel_id,
                start_chapter=1, end_chapter=10,
            )

        assert result["total_threads"] == 0
        assert result["total_arcs"] == 0
        assert result["threads"] == []
        assert result["arcs"] == []
