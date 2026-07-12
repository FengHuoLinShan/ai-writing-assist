from __future__ import annotations

from unittest import mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


class TestImportsOutlineIntegration:
    """T5: Import 工作流触发生成大纲"""

    @pytest.mark.asyncio
    async def test_deep_import_calls_outline_generation(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """深度导入的 _analyze_structure 应通过 DI 容器调用 outline.generate_structure"""
        from modules.imports.workflow import DeepImportWorkflow

        workflow = DeepImportWorkflow()

        async def _mock_generate(db, novel_id, *, start_chapter, end_chapter, **kwargs):
            return {
                "total_threads": 3,
                "total_arcs": 2,
                "threads": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                "arcs": [{"id": "x"}, {"id": "y"}],
            }

        with mock.patch(
            "modules.imports.workflow._container_get",
            return_value=_mock_generate,
        ):
            result = await workflow._analyze_structure(
                db_session,
                sample_novel_id,
                start_chapter=1,
                end_chapter=10,
            )

        assert result["total_threads"] == 3
        assert result["total_arcs"] == 2

    @pytest.mark.asyncio
    async def test_analyze_structure_failure_graceful(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """outline 生成失败时应优雅降级，不抛异常"""
        from modules.imports.workflow import DeepImportWorkflow

        workflow = DeepImportWorkflow()

        async def _mock_generate_fail(
            db, novel_id, *, start_chapter, end_chapter, **kwargs
        ):
            raise Exception("LLM timeout")

        with mock.patch(
            "modules.imports.workflow._container_get",
            return_value=_mock_generate_fail,
        ):
            result = await workflow._analyze_structure(
                db_session,
                sample_novel_id,
                start_chapter=1,
                end_chapter=10,
            )

        assert result["total_threads"] == 0
        assert result["total_arcs"] == 0
        assert result["threads"] == []
        assert result["arcs"] == []
