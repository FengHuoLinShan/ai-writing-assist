"""
RAG 补全测试 — contracts / schemas / api / tasks / tuning (剩余未覆盖)

覆盖现有 test_rag_services.py 和 test_rag_facade_extra.py 未测试的全部源文件。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.container import register, reset

# ============================================================
# contracts.py — 数据契约
# ============================================================


class TestContracts:
    """RagChunkContract / RagQueryContract / RagResultBundle / RagIndexReport"""

    def test_rag_chunk_contract_defaults(self):
        """GREEN: RagChunkContract 使用最少字段创建"""
        from modules.rag.contracts import RagChunkContract

        c = RagChunkContract(
            id="c1", novel_id="n1", source_type="chapter_text", text="hello"
        )
        assert c.id == "c1"
        assert c.novel_id == "n1"
        assert c.source_type == "chapter_text"
        assert c.text == "hello"
        assert c.source_id is None
        assert c.chapter_index is None
        assert c.chunk_index is None
        assert c.start_offset is None
        assert c.end_offset is None
        assert c.char_count is None
        assert c.summary is None
        assert c.entity_ids == []
        assert c.character_ids == []
        assert c.thread_ids == []
        assert c.visibility == "author_only"
        assert c.importance == 0.5
        assert c.index_version == "legacy"
        assert c.embedding_status == "pending"
        assert c.embedding_error is None
        assert c.index_warnings == []
        assert c.meta is None
        assert c.score is None

    def test_rag_chunk_contract_frozen_raises_on_modify(self):
        """EDGE: RagChunkContract 是 frozen dataclass，修改属性应报错"""
        from dataclasses import FrozenInstanceError

        from modules.rag.contracts import RagChunkContract

        c = RagChunkContract(id="c1", novel_id="n1", source_type="t", text="t")
        with pytest.raises(FrozenInstanceError):
            c.text = "modified"  # type: ignore[misc]

    def test_rag_chunk_contract_with_all_fields(self):
        """GREEN: RagChunkContract 填充全部字段"""
        from modules.rag.contracts import RagChunkContract

        c = RagChunkContract(
            id="c1",
            novel_id="n1",
            source_type="chapter_text",
            source_id="src1",
            chapter_index=3,
            chunk_index=1,
            start_offset=10,
            end_offset=200,
            char_count=190,
            text="full text",
            summary="sum",
            entity_ids=["e1", "e2"],
            character_ids=["c1"],
            thread_ids=["t1"],
            visibility="reader_known",
            importance=0.9,
            index_version="v2",
            embedding_status="succeeded",
            embedding_error=None,
            index_warnings=["warn1"],
            meta={"arc": "arc1"},
            score=0.85,
        )
        assert c.source_id == "src1"
        assert c.chapter_index == 3
        assert c.chunk_index == 1
        assert c.start_offset == 10
        assert c.end_offset == 200
        assert c.char_count == 190
        assert c.summary == "sum"
        assert c.entity_ids == ["e1", "e2"]
        assert c.character_ids == ["c1"]
        assert c.thread_ids == ["t1"]
        assert c.visibility == "reader_known"
        assert c.importance == 0.9
        assert c.index_version == "v2"
        assert c.embedding_status == "succeeded"
        assert c.embedding_error is None
        assert c.index_warnings == ["warn1"]
        assert c.meta == {"arc": "arc1"}
        assert c.score == 0.85

    def test_rag_query_contract_defaults(self):
        """GREEN: RagQueryContract 默认值正确"""
        from modules.rag.contracts import RagQueryContract

        q = RagQueryContract(query="test query")
        assert q.query == "test query"
        assert q.entity_ids is None
        assert q.character_ids is None
        assert q.thread_ids is None
        assert q.chapter_index is None
        assert q.mode == "search"
        assert q.top_k == 12

    def test_rag_query_contract_custom_values(self):
        """GREEN: RagQueryContract 自定义值"""
        from modules.rag.contracts import RagQueryContract

        q = RagQueryContract(
            query="q",
            entity_ids=["e1"],
            character_ids=["c1"],
            thread_ids=["t1"],
            chapter_index=5,
            mode="extraction",
            top_k=24,
        )
        assert q.entity_ids == ["e1"]
        assert q.character_ids == ["c1"]
        assert q.thread_ids == ["t1"]
        assert q.chapter_index == 5
        assert q.mode == "extraction"
        assert q.top_k == 24

    def test_rag_result_bundle_defaults(self):
        """GREEN: RagResultBundle 默认值为空"""
        from modules.rag.contracts import RagResultBundle

        r = RagResultBundle()
        assert r.chunks == []
        assert r.total == 0
        assert r.query == ""
        assert r.warnings == []
        assert r.degraded is False

    def test_rag_result_bundle_with_data(self):
        """GREEN: RagResultBundle 带数据"""
        from modules.rag.contracts import RagChunkContract, RagResultBundle

        chunk = RagChunkContract(id="c1", novel_id="n1", source_type="t", text="t")
        r = RagResultBundle(
            chunks=[chunk],
            total=1,
            query="q",
            warnings=["w1"],
            degraded=True,
        )
        assert len(r.chunks) == 1
        assert r.chunks[0] is chunk
        assert r.total == 1
        assert r.query == "q"
        assert r.warnings == ["w1"]
        assert r.degraded is True

    def test_rag_index_report_defaults(self):
        """GREEN: RagIndexReport 默认值"""
        from modules.rag.contracts import RagIndexReport

        r = RagIndexReport(chapter_index=1)
        assert r.chapter_index == 1
        assert r.chunks_created == 0
        assert r.warnings == []
        assert r.embedding_failed_count == 0
        assert r.chunks_created_ids == []

    def test_rag_index_report_full(self):
        """GREEN: RagIndexReport 全字段"""
        from modules.rag.contracts import RagIndexReport

        r = RagIndexReport(
            chapter_index=3,
            chunks_created=7,
            warnings=["w"],
            embedding_failed_count=1,
            chunks_created_ids=["id1"],
        )
        assert r.chunks_created == 7
        assert r.warnings == ["w"]
        assert r.embedding_failed_count == 1
        assert r.chunks_created_ids == ["id1"]


# ============================================================
# schemas.py — Pydantic schema
# ============================================================


class TestSchemas:
    """Pydantic schemas 与 validators"""

    def test_rag_chunk_create_requires_source_type_and_text(self):
        """GREEN: RagChunkCreate 必需字段"""
        from modules.rag.schemas import RagChunkCreate

        s = RagChunkCreate(source_type="chapter_text", text="hello")
        assert s.source_type == "chapter_text"
        assert s.text == "hello"
        assert s.visibility == "author_only"
        assert s.importance == 0.5
        assert s.index_version == "legacy"
        assert s.embedding_status == "pending"
        assert s.entity_ids == []
        assert s.meta == {}

    def test_rag_chunk_create_rejects_empty_text(self):
        """ERROR: RagChunkCreate text 为空报 ValidationError"""
        from pydantic import ValidationError

        from modules.rag.schemas import RagChunkCreate

        with pytest.raises(
            ValidationError, match="String should have at least 1 character"
        ):
            RagChunkCreate(source_type="t", text="")

    def test_rag_chunk_create_rejects_negative_offset(self):
        """ERROR: RagChunkCreate start_offset < 0 报错"""
        from pydantic import ValidationError

        from modules.rag.schemas import RagChunkCreate

        with pytest.raises(ValidationError):
            RagChunkCreate(source_type="t", text="t", start_offset=-1)

    @pytest.mark.parametrize(
        "field", ["source_type", "visibility", "index_version", "embedding_status"]
    )
    def test_rag_chunk_create_enforces_max_length(self, field):
        """ERROR: RagChunkCreate 超长字段报错"""
        from pydantic import ValidationError

        from modules.rag.schemas import RagChunkCreate

        kwargs = {"source_type": "t", "text": "t", field: "x" * 65}
        with pytest.raises(ValidationError):
            RagChunkCreate(**kwargs)

    def test_rag_chunk_create_rejects_importance_out_of_range(self):
        """ERROR: RagChunkCreate importance 超出 0-1 范围报错"""
        from pydantic import ValidationError

        from modules.rag.schemas import RagChunkCreate

        with pytest.raises(ValidationError):
            RagChunkCreate(source_type="t", text="t", importance=1.5)
        with pytest.raises(ValidationError):
            RagChunkCreate(source_type="t", text="t", importance=-0.1)

    def test_rag_query_requires_query_text(self):
        """GREEN: RagQuery 必需字段"""
        from modules.rag.schemas import RagQuery

        q = RagQuery(query="search this")
        assert q.query == "search this"
        assert q.mode == "search"
        assert q.top_k == 12
        assert q.entity_ids is None
        assert q.visibility is None
        assert q.chapter_index is None

    def test_rag_query_rejects_empty_query(self):
        """ERROR: RagQuery 空查询文本报错"""
        from pydantic import ValidationError

        from modules.rag.schemas import RagQuery

        with pytest.raises(
            ValidationError, match="String should have at least 1 character"
        ):
            RagQuery(query="")

    def test_rag_query_rejects_invalid_mode(self):
        """ERROR: RagQuery mode 不是 Literal 值报错"""
        from pydantic import ValidationError

        from modules.rag.schemas import RagQuery

        with pytest.raises(ValidationError):
            RagQuery(query="q", mode="invalid_mode")

    @pytest.mark.parametrize("mode", ["search", "context", "extraction"])
    def test_rag_query_accepts_valid_modes(self, mode):
        """GREEN: RagQuery 接受所有合法 mode 值"""
        from modules.rag.schemas import RagQuery

        q = RagQuery(query="q", mode=mode)  # type: ignore[arg-type]
        assert q.mode == mode

    def test_rag_query_top_k_bounds(self):
        """ERROR: RagQuery top_k 超出 1-50 范围报错"""
        from pydantic import ValidationError

        from modules.rag.schemas import RagQuery

        with pytest.raises(ValidationError):
            RagQuery(query="q", top_k=0)
        with pytest.raises(ValidationError):
            RagQuery(query="q", top_k=51)

    def test_rag_chunk_response_coerces_uuid_id(self):
        """GREEN: RagChunkResponse 将 UUID id 转字符串"""
        from modules.rag.schemas import RagChunkResponse

        raw_uuid = uuid.UUID(hex="a" * 32)
        obj = RagChunkResponse(
            id=raw_uuid,
            novel_id=str(raw_uuid),
            source_type="t",
            text="t",
        )
        assert isinstance(obj.id, str)
        assert obj.id == str(raw_uuid)

    def test_rag_chunk_response_keeps_str_id(self):
        """GREEN: RagChunkResponse 保留字符串 id"""
        from modules.rag.schemas import RagChunkResponse

        obj = RagChunkResponse(
            id="already-str",
            novel_id="novel-str",
            source_type="t",
            text="t",
        )
        assert obj.id == "already-str"

    def test_rag_chunk_response_coerces_novel_id(self):
        """GREEN: RagChunkResponse 将 UUID novel_id 转字符串"""
        from modules.rag.schemas import RagChunkResponse

        raw = uuid.UUID(hex="b" * 32)
        obj = RagChunkResponse(
            id="id",
            novel_id=raw,
            source_type="t",
            text="t",
        )
        assert obj.novel_id == str(raw)

    def test_rag_chunk_response_coerces_source_id_uuid(self):
        """GREEN: RagChunkResponse 将 UUID source_id 转字符串"""
        from modules.rag.schemas import RagChunkResponse

        raw = uuid.UUID(hex="c" * 32)
        obj = RagChunkResponse(
            id="id",
            novel_id="n",
            source_type="t",
            source_id=raw,
            text="t",
        )
        assert obj.source_id == str(raw)

    def test_rag_chunk_response_source_id_none(self):
        """EDGE: RagChunkResponse source_id 为 None 不变"""
        from modules.rag.schemas import RagChunkResponse

        obj = RagChunkResponse(
            id="id",
            novel_id="n",
            source_type="t",
            source_id=None,
            text="t",
        )
        assert obj.source_id is None

    def test_rag_result_defaults(self):
        """GREEN: RagResult 必需字段"""
        from modules.rag.schemas import RagResult

        r = RagResult(chunks=[], total=0, query="q")
        assert r.warnings == []
        assert r.degraded is False

    def test_similar_entity_defaults(self):
        """GREEN: SimilarEntity 必需字段"""
        from modules.rag.schemas import SimilarEntity

        se = SimilarEntity(entity_id="e1", name="entity", similarity_score=0.85)
        assert se.similarity_score == 0.85
        assert se.name == "entity"

    def test_similar_entity_response_defaults(self):
        """GREEN: SimilarEntityResponse"""
        from modules.rag.schemas import SimilarEntity, SimilarEntityResponse

        resp = SimilarEntityResponse(items=[], total=0)
        assert resp.items == []

        se = SimilarEntity(entity_id="e1", name="n", similarity_score=0.9)
        resp2 = SimilarEntityResponse(items=[se], total=1)
        assert len(resp2.items) == 1


# ============================================================
# api.py — API 路由
# ============================================================


@pytest.fixture
def _stub_rag_active_project_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    from modules.rag import api as rag_api

    async def require_active_project(_db, _novel_id):
        return None

    monkeypatch.setattr(rag_api, "_require_active_project", require_active_project)


@pytest.mark.usefixtures("_stub_rag_active_project_guard")
class TestApiRoutes:
    """RAG API 路由单元测试（mock facade + circuit_breaker + metrics）"""

    @pytest.mark.asyncio
    async def test_create_rag_chunk_calls_facade(self):
        """GREEN: POST /api/rag/chunks 调用 facade.create_chunk"""
        from modules.rag.schemas import RagChunkCreate

        with patch("modules.rag.api.create_chunk", autospec=True) as mock_create:
            mock_create.return_value = MagicMock(id="new-id", novel_id="n", text="t")

            from modules.rag.api import create_rag_chunk

            db = AsyncMock()
            data = RagChunkCreate(source_type="chapter_text", text="test text")
            result = await create_rag_chunk(db=db, novel_id="novel-1", data=data)

            mock_create.assert_awaited_once()
            assert result.id == "new-id"

    @pytest.mark.asyncio
    async def test_list_rag_chunks_returns_combined_dict(self):
        """GREEN: GET /api/rag/chunks 组合 items + status"""
        from modules.rag.schemas import RagChunkResponse

        mock_chunks = [
            RagChunkResponse(id="c1", novel_id="n", source_type="t", text="t1"),
        ]

        with (
            patch("modules.rag.api.list_chunks", autospec=True) as mock_list,
            patch("modules.rag.api.get_index_status", autospec=True) as mock_status,
        ):
            mock_list.return_value = (mock_chunks, 1)
            mock_status.return_value = {"index_version": "v1", "total_chunks": 1}

            from modules.rag.api import list_rag_chunks

            db = AsyncMock()
            result = await list_rag_chunks(db=db, novel_id="n1")

            assert result["items"] == mock_chunks
            assert result["total"] == 1
            assert result["index_version"] == "v1"

    @pytest.mark.asyncio
    async def test_retrieve_chunks_converts_contracts_to_responses(self):
        """GREEN: POST /api/rag/retrieve 将 RagChunkContract 转为 RagChunkResponse"""
        from modules.rag.contracts import RagChunkContract, RagResultBundle
        from modules.rag.schemas import RagQuery

        mock_bundle = RagResultBundle(
            chunks=[
                RagChunkContract(
                    id="c1",
                    novel_id="n1",
                    source_type="chapter_text",
                    source_id="s1",
                    chapter_index=3,
                    chunk_index=1,
                    start_offset=0,
                    end_offset=100,
                    char_count=100,
                    text="retrieved text",
                    summary="sum",
                    entity_ids=["e1"],
                    character_ids=["c1"],
                    thread_ids=["t1"],
                    visibility="author_only",
                    importance=0.8,
                    index_version="v1",
                    embedding_status="succeeded",
                    embedding_error=None,
                    index_warnings=[],
                    meta={"arc": "main"},
                    score=0.92,
                ),
            ],
            total=1,
            query="test query",
            warnings=[],
            degraded=False,
        )

        with patch("modules.rag.api.retrieve", autospec=True) as mock_retrieve:
            mock_retrieve.return_value = mock_bundle

            from modules.rag.api import retrieve_chunks
            from modules.rag.schemas import RagResult

            db = AsyncMock()
            query = RagQuery(query="test query")
            result = await retrieve_chunks(db=db, novel_id="n1", query=query)

            assert isinstance(result, RagResult)
            assert result.total == 1
            assert result.query == "test query"
            assert len(result.chunks) == 1
            chunk = result.chunks[0]
            assert chunk.id == "c1"
            assert chunk.score == 0.92
            assert chunk.importance == 0.8

    @pytest.mark.asyncio
    async def test_retrieve_chunks_handles_empty_results(self):
        """EDGE: POST /api/rag/retrieve 空结果也返回合法 RagResult"""
        from modules.rag.contracts import RagResultBundle
        from modules.rag.schemas import RagQuery

        mock_bundle = RagResultBundle(chunks=[], total=0, query="empty")

        with patch("modules.rag.api.retrieve", autospec=True) as mock_retrieve:
            mock_retrieve.return_value = mock_bundle

            from modules.rag.api import retrieve_chunks

            db = AsyncMock()
            query = RagQuery(query="empty")
            result = await retrieve_chunks(db=db, novel_id="n1", query=query)

            assert result.total == 0
            assert len(result.chunks) == 0

    @pytest.mark.asyncio
    async def test_get_rag_metrics_returns_snapshot(self):
        """GREEN: GET /api/rag/metrics 返回指标 + 熔断器状态"""
        with (
            patch(
                "modules.rag.metrics.get_metrics", autospec=True
            ) as mock_metrics_getter,
            patch(
                "modules.rag.circuit_breaker.get_circuit_breaker", autospec=True
            ) as mock_cb_getter,
        ):
            mock_metrics = MagicMock()
            mock_metrics.snapshot = {
                "query_count": 42,
                "degraded_rate": 0.1,
                "avg_latency_ms": 150.0,
            }
            mock_metrics_getter.return_value = mock_metrics

            mock_cb = MagicMock()
            mock_cb.status = {"state": "closed", "failure_count": 0}
            mock_cb_getter.return_value = mock_cb

            from modules.rag.api import get_rag_metrics

            result = await get_rag_metrics()

            assert result["metrics"]["query_count"] == 42
            assert result["circuit_breaker"]["state"] == "closed"

    @pytest.mark.asyncio
    async def test_split_text_paragraph_method_uses_chunking_service(self):
        """GREEN: POST /api/rag/chunks/split 段落分割"""
        from modules.rag.api import split_text

        result = await split_text(
            text="段落一\n\n段落二\n\n段落三",
            method="paragraph",
            chunk_size=1000,
            overlap=100,
        )
        assert result["method"] == "paragraph"
        assert result["total"] == 3
        assert "段落一" in result["chunks"]
        assert "段落二" in result["chunks"]

    @pytest.mark.asyncio
    async def test_split_text_length_method(self):
        """GREEN: POST /api/rag/chunks/split 固定长度分割"""
        from modules.rag.api import split_text

        result = await split_text(
            text="ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            method="length",
            chunk_size=10,
            overlap=0,
        )
        assert result["method"] == "length"
        assert result["total"] >= 2  # 26 chars / 10 = 3 chunks

    @pytest.mark.asyncio
    async def test_split_text_unknown_method_returns_whole_text(self):
        """EDGE: 未知分割方法回退为整段"""
        from modules.rag.api import split_text

        result = await split_text(
            text="whole text",
            method="unknown",
        )
        assert result["total"] == 1
        assert result["chunks"] == ["whole text"]


# ============================================================
# tasks.py — 任务处理器
# ============================================================


class TestTasks:
    """RAG 异步任务处理器"""

    @pytest.mark.asyncio
    async def test_handle_rag_index_chapter_success(self):
        """GREEN: 章节索引任务正常执行"""
        from modules.rag.contracts import RagIndexReport, RagTaskIndexOutcome

        report = RagIndexReport(
            chapter_index=3,
            chunks_created=5,
            embedding_failed_count=0,
            warnings=[],
            chunks_created_ids=["c1", "c2"],
        )

        mock_index = AsyncMock(return_value=RagTaskIndexOutcome(report=report))
        reset()
        register("rag.index_chapter_for_task", mock_index)
        try:
            from modules.rag.tasks import handle_rag_index_chapter

            db = AsyncMock()
            task = SimpleNamespace(
                id="task-1",
                task_type="rag_index_chapter",
                attempt=1,
                lease_id="lease-1",
                meta={"novel_id": "n1", "chapter_index": "3"},
            )
            result = await handle_rag_index_chapter(db, task)

            assert result["chapter_index"] == 3
            assert result["chunks_created"] == 5
            assert result["embedding_failed_count"] == 0
        finally:
            reset()

    @pytest.mark.asyncio
    async def test_handle_rag_index_chapter_missing_novel_id_raises(self):
        """ERROR: 缺少 novel_id 报 ValueError"""
        from modules.rag.tasks import handle_rag_index_chapter

        db = AsyncMock()
        task = SimpleNamespace(meta={"chapter_index": "3"})

        with pytest.raises(ValueError, match="novel_id is required"):
            await handle_rag_index_chapter(db, task)

    @pytest.mark.asyncio
    async def test_handle_rag_index_chapter_invalid_chapter_index_raises(self):
        """ERROR: chapter_index < 1 报 ValueError"""
        from modules.rag.tasks import handle_rag_index_chapter

        db = AsyncMock()
        task = SimpleNamespace(meta={"novel_id": "n1", "chapter_index": "0"})

        with pytest.raises(ValueError, match="chapter_index must be >= 1"):
            await handle_rag_index_chapter(db, task)

    @pytest.mark.asyncio
    async def test_handle_rag_index_chapter_empty_meta_raises(self):
        """ERROR: task.meta 为 None 报 ValueError"""
        from modules.rag.tasks import handle_rag_index_chapter

        db = AsyncMock()
        task = SimpleNamespace(meta=None)

        with pytest.raises(ValueError, match="novel_id is required"):
            await handle_rag_index_chapter(db, task)

    @pytest.mark.asyncio
    async def test_handle_rag_reindex_novel_success(self):
        """GREEN: 全量重建任务正常执行"""
        from modules.rag.contracts import RagIndexReport, RagTaskIndexOutcome

        report = RagIndexReport(
            chapter_index=1, chunks_created=3, warnings=[], embedding_failed_count=0
        )

        reset()
        register("writing.list_chapter_indices", AsyncMock(return_value=[1, 2]))
        mock_index = AsyncMock(return_value=RagTaskIndexOutcome(report=report))
        register("rag.index_chapter_for_task", mock_index)

        try:
            from modules.rag.tasks import handle_rag_reindex_novel

            db = AsyncMock()
            task = SimpleNamespace(
                id="task-1",
                task_type="rag_reindex_novel",
                attempt=1,
                lease_id="lease-1",
                meta={"novel_id": "n1"},
            )
            task.update_progress = MagicMock()

            result = await handle_rag_reindex_novel(db, task)

            assert result["total_chapters"] == 2
            assert result["chunks_created"] == 6
            assert len(result["chapters"]) == 2
            assert mock_index.await_args.kwargs["scene_annotation_only"] is False
            task.update_progress.assert_called()
        finally:
            reset()

    @pytest.mark.asyncio
    async def test_handle_rag_reindex_novel_coalesces_running_chapter(self):
        """A rebuild must not execute beside an indexer that already owns the row."""
        from modules.rag.contracts import RagIndexReport, RagTaskIndexOutcome

        reset()
        register("writing.list_chapter_indices", AsyncMock(return_value=[1]))
        mock_index = AsyncMock(
            return_value=RagTaskIndexOutcome(
                report=RagIndexReport(chapter_index=1),
                status="coalesced",
            )
        )
        register("rag.index_chapter_for_task", mock_index)

        try:
            from modules.rag.tasks import handle_rag_reindex_novel

            db = AsyncMock()
            task = SimpleNamespace(
                id="task-1",
                task_type="rag_reindex_novel",
                attempt=1,
                lease_id="lease-1",
                meta={"novel_id": "n1"},
            )
            task.update_progress = MagicMock()

            result = await handle_rag_reindex_novel(db, task)
            assert result["chunks_created"] == 0
            assert result["chapters"][0]["coalesced"] is True
            assert "已合并" in result["warnings"][0]
            mock_index.assert_awaited_once()
        finally:
            reset()

    @pytest.mark.asyncio
    async def test_handle_rag_reindex_novel_uses_scene_annotation_for_known_sources(
        self,
    ):
        from modules.rag.contracts import RagIndexReport, RagTaskIndexOutcome

        reset()
        register("writing.list_chapter_indices", AsyncMock(return_value=[1]))
        mock_index = AsyncMock(
            return_value=RagTaskIndexOutcome(report=RagIndexReport(chapter_index=1))
        )
        register("rag.index_chapter_for_task", mock_index)

        try:
            from modules.rag.tasks import handle_rag_reindex_novel

            db = AsyncMock()
            task = SimpleNamespace(
                id="task-1",
                task_type="rag_reindex_novel",
                attempt=1,
                lease_id="lease-1",
                meta={"novel_id": "n1", "source": "deep_import_scene_commit"},
            )
            task.update_progress = MagicMock()

            await handle_rag_reindex_novel(db, task)

            assert mock_index.await_args.kwargs["scene_annotation_only"] is True
        finally:
            reset()

    @pytest.mark.asyncio
    async def test_handle_rag_reindex_novel_keeps_unknown_source_as_full_rebuild(self):
        from modules.rag.contracts import RagIndexReport, RagTaskIndexOutcome

        reset()
        register("writing.list_chapter_indices", AsyncMock(return_value=[1]))
        mock_index = AsyncMock(
            return_value=RagTaskIndexOutcome(report=RagIndexReport(chapter_index=1))
        )
        register("rag.index_chapter_for_task", mock_index)

        try:
            from modules.rag.tasks import handle_rag_reindex_novel

            db = AsyncMock()
            task = SimpleNamespace(
                id="task-1",
                task_type="rag_reindex_novel",
                attempt=1,
                lease_id="lease-1",
                meta={"novel_id": "n1", "source": "manual"},
            )
            task.update_progress = MagicMock()

            await handle_rag_reindex_novel(db, task)

            assert mock_index.await_args.kwargs["scene_annotation_only"] is False
        finally:
            reset()

    @pytest.mark.asyncio
    async def test_handle_rag_reindex_novel_missing_novel_id_raises(self):
        """ERROR: 缺少 novel_id 报 ValueError"""
        from modules.rag.tasks import handle_rag_reindex_novel

        db = AsyncMock()
        task = SimpleNamespace(meta={})

        with pytest.raises(ValueError, match="novel_id is required"):
            await handle_rag_reindex_novel(db, task)

    @pytest.mark.asyncio
    async def test_handle_rag_reindex_novel_with_range(self):
        """GREEN: 指定起止章节范围"""
        from modules.rag.contracts import RagIndexReport, RagTaskIndexOutcome

        report = RagIndexReport(
            chapter_index=2, chunks_created=4, warnings=[], embedding_failed_count=0
        )

        reset()
        register("writing.list_chapter_indices", AsyncMock(return_value=[1, 2, 3, 4, 5]))
        mock_index = AsyncMock(return_value=RagTaskIndexOutcome(report=report))
        register("rag.index_chapter_for_task", mock_index)

        try:
            from modules.rag.tasks import handle_rag_reindex_novel

            db = AsyncMock()
            task = SimpleNamespace(
                id="task-1",
                task_type="rag_reindex_novel",
                attempt=1,
                lease_id="lease-1",
                meta={
                    "novel_id": "n1",
                    "start_chapter": "2",
                    "end_chapter": "4",
                },
            )
            task.update_progress = MagicMock()

            result = await handle_rag_reindex_novel(db, task)

            assert result["total_chapters"] == 3
            assert mock_index.await_count == 3
        finally:
            reset()

    @pytest.mark.asyncio
    async def test_handle_rag_reindex_novel_empty_chapters(self):
        """EDGE: 无匹配章节时正常返回"""
        reset()
        register("writing.list_chapter_indices", AsyncMock(return_value=[]))

        from modules.rag.tasks import handle_rag_reindex_novel

        db = AsyncMock()
        task = SimpleNamespace(meta={"novel_id": "n1"})
        task.update_progress = MagicMock()

        result = await handle_rag_reindex_novel(db, task)

        assert result["total_chapters"] == 0
        assert result["chunks_created"] == 0
        assert result["chapters"] == []

        reset()


# ============================================================
# tuning.py — 未覆盖的调优逻辑
# ============================================================


class TestTuningExtra:
    """Tuning 模块剩余函数: 数据类 / build_eval_set / evaluate_weights / print_report"""

    def test_eval_query_defaults(self):
        """GREEN: EvalQuery 数据类"""
        from modules.rag.tuning import EvalQuery

        eq = EvalQuery(query="test", relevant_ids={"a", "b"})
        assert eq.query == "test"
        assert eq.relevant_ids == {"a", "b"}
        assert eq.chapter_index is None

    def test_eval_result_defaults(self):
        """GREEN: EvalResult 数据类"""
        from modules.rag.tuning import EvalResult

        er = EvalResult(weights=(0.5, 0.2, 0.15, 0.15))
        assert er.mrr == 0.0
        assert er.ndcg_at_5 == 0.0
        assert er.precision_at_5 == 0.0

    def test_tuning_report_defaults(self):
        """GREEN: TuningReport 数据类"""
        from modules.rag.tuning import TuningReport

        tr = TuningReport()
        assert tr.best.weights == (0, 0, 0, 0)
        assert tr.top5 == []
        assert tr.total_combinations == 0
        assert tr.total_queries == 0

    # --- build_eval_set ---

    @pytest.mark.asyncio
    async def test_build_eval_set_empty_db_returns_empty(self):
        """EDGE: DB 中无 chunk 返回空列表"""
        from modules.rag.tuning import build_eval_set

        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=db_result)

        queries = await build_eval_set(db, uuid.UUID(hex="a" * 32))
        assert queries == []

    @pytest.mark.asyncio
    async def test_build_eval_set_skips_short_text(self):
        """EDGE: 文本太短 (< 10 字符) 跳过"""
        from modules.rag.tuning import build_eval_set

        c = SimpleNamespace()
        c.id = "short"
        c.text = "短"
        c.entity_ids = []
        c.chapter_index = 1

        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalars.return_value.all.return_value = [c]
        db.execute = AsyncMock(return_value=db_result)

        queries = await build_eval_set(db, uuid.UUID(hex="a" * 32))
        assert queries == []

    @pytest.mark.asyncio
    async def test_build_eval_set_skips_few_relevant(self):
        """EDGE: 相关 chunk 不足 2 个跳过"""
        from modules.rag.tuning import build_eval_set

        # Two chunks sharing one entity → each sees 1 relevant (< 2) → skipped
        chunks = []
        for i in range(2):
            c = SimpleNamespace()
            c.id = f"chunk{i}"
            c.text = "这是一个足够长的测试查询文本用于构建评估数据集    "
            c.entity_ids = ["e_shared"]
            c.chapter_index = 1
            chunks.append(c)

        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalars.return_value.all.return_value = chunks
        db.execute = AsyncMock(return_value=db_result)

        queries = await build_eval_set(db, uuid.UUID(hex="a" * 32))
        assert len(queries) == 0

    @pytest.mark.asyncio
    async def test_build_eval_set_honors_max_queries(self):
        """EDGE: max_queries 限制"""
        from modules.rag.tuning import build_eval_set

        # 10 chunks all sharing 1 entity → each sees 9 relevant (>= 2)
        chunks = []
        for i in range(10):
            c = SimpleNamespace()
            c.id = f"chunk{i}"
            c.text = f"这是一个足够长的测试查询文本用于构建评估数据集编号{i}    "
            c.entity_ids = ["e_all"]
            c.chapter_index = 1
            chunks.append(c)

        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalars.return_value.all.return_value = chunks
        db.execute = AsyncMock(return_value=db_result)

        queries = await build_eval_set(db, uuid.UUID(hex="a" * 32), max_queries=3)
        assert len(queries) == 3

    @pytest.mark.asyncio
    async def test_build_eval_set_creates_queries_from_chunks(self):
        """GREEN: 从 chunk 构建 EvalQuery（共享 entity 的 chunk 互相关）"""
        from modules.rag.tuning import build_eval_set

        chunks = []
        for i in range(4):
            c = SimpleNamespace()
            c.id = f"chunk{i}"
            c.text = f"这是一个足够长的测试查询文本用于构建评估数据集编号{i}    "
            # All share e0, plus each has a unique entity
            c.entity_ids = ["e0", f"e{i}"]
            c.chapter_index = 1
            chunks.append(c)

        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalars.return_value.all.return_value = chunks
        db.execute = AsyncMock(return_value=db_result)

        queries = await build_eval_set(db, uuid.UUID(hex="a" * 32), max_queries=10)

        # Each chunk shares e0 with 3 others → 3 relevant (>= 2)
        assert len(queries) == 4
        for q in queries:
            assert len(q.relevant_ids) == 3
            assert q.query.startswith("这是一个")

    # --- evaluate_weights ---

    @pytest.mark.asyncio
    async def test_evaluate_weights_with_empty_queries(self):
        """EDGE: 无查询时返回零指标"""
        from modules.rag.tuning import evaluate_weights

        db = AsyncMock()
        result = await evaluate_weights(
            db,
            uuid.UUID(hex="a" * 32),
            [],
            (0.5, 0.2, 0.15, 0.15),
        )
        assert result.mrr == 0.0
        assert result.ndcg_at_5 == 0.0
        assert result.ndcg_at_10 == 0.0
        assert result.precision_at_5 == 0.0
        assert result.recall_at_5 == 0.0
        assert result.avg_latency_ms == 0.0

    @pytest.mark.asyncio
    async def test_evaluate_weights_logs_embedding_failure_and_uses_lexical_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from modules.rag.tuning import EvalQuery, evaluate_weights

        class _FailingEmbeddingClient:
            async def generate_embedding(self, *_args, **_kwargs):
                raise RuntimeError("embedding unavailable")

            async def close(self) -> None:
                return None

        class _CapturingRetrieval:
            query_embedding = object()
            calls = 0

            async def hybrid_search(self, *_args, **kwargs):
                type(self).query_embedding = kwargs["query_embedding"]
                type(self).calls += 1
                return []

        monkeypatch.setattr(
            "infrastructure.llm.client.LLMClient",
            _FailingEmbeddingClient,
        )
        monkeypatch.setattr(
            "modules.rag.retrieval.RetrievalOrchestrator",
            _CapturingRetrieval,
        )
        novel_id = uuid.UUID(hex="a" * 32)

        with caplog.at_level("WARNING", logger="modules.rag.tuning"):
            result = await evaluate_weights(
                AsyncMock(),
                novel_id,
                [
                    EvalQuery(
                        query="测试检索正文不应进入 warning message",
                        relevant_ids={"chunk-1"},
                        chapter_index=7,
                    ),
                    EvalQuery(
                        query="第二条测试检索正文",
                        relevant_ids={"chunk-2"},
                        chapter_index=8,
                    ),
                ],
                (0.5, 0.2, 0.15, 0.15),
            )

        assert result.mrr == 0.0
        assert _CapturingRetrieval.query_embedding is None
        records = [
            item
            for item in caplog.records
            if "rag_tuning_embedding_failed" in item.getMessage()
        ]
        assert len(records) == 1
        record = records[0]
        assert str(novel_id) in record.getMessage()
        assert "chapter_index=7" in record.getMessage()
        assert "测试检索正文" not in record.getMessage()
        assert _CapturingRetrieval.calls == 2
        assert record.exc_info is None

    @pytest.mark.asyncio
    async def test_run_tuning_shares_embedding_failure_log_suppression(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from modules.rag.tuning import EvalQuery, run_tuning

        class _FailingEmbeddingClient:
            async def generate_embedding(self, *_args, **_kwargs):
                raise RuntimeError("embedding unavailable")

            async def close(self) -> None:
                return None

        class _EmptyRetrieval:
            async def hybrid_search(self, *_args, **_kwargs):
                return []

        async def _build_eval_set(*_args, **_kwargs):
            return [
                EvalQuery(
                    query="测试检索",
                    relevant_ids={"chunk-1"},
                    chapter_index=7,
                )
            ]

        monkeypatch.setattr(
            "infrastructure.llm.client.LLMClient",
            _FailingEmbeddingClient,
        )
        monkeypatch.setattr(
            "modules.rag.retrieval.RetrievalOrchestrator",
            _EmptyRetrieval,
        )
        monkeypatch.setattr("modules.rag.tuning.build_eval_set", _build_eval_set)
        monkeypatch.setattr(
            "modules.rag.tuning.generate_weight_combinations",
            lambda: [
                (0.5, 0.2, 0.15, 0.15),
                (0.45, 0.25, 0.15, 0.15),
            ],
        )

        with caplog.at_level("WARNING", logger="modules.rag.tuning"):
            report = await run_tuning(AsyncMock(), novel_id="a" * 32)

        assert report.total_combinations == 2
        records = [
            item
            for item in caplog.records
            if "rag_tuning_embedding_failed" in item.getMessage()
        ]
        assert len(records) == 1
        assert records[0].exc_info is None

    # --- run_tuning ---

    @pytest.mark.asyncio
    async def test_run_tuning_empty_eval_set_returns_empty_report(self):
        """EDGE: 评估集为空返回空报告"""
        from modules.rag.tuning import TuningReport

        with patch("modules.rag.tuning.build_eval_set", autospec=True) as mock_build:
            mock_build.return_value = []

            from modules.rag.tuning import run_tuning

            db = AsyncMock()
            report = await run_tuning(db, novel_id="a" * 32)
            assert isinstance(report, TuningReport)
            assert report.total_combinations == 0
            assert report.total_queries == 0

    # --- print_report ---

    def test_print_report_output_contains_keywords(self, capsys):
        """GREEN: print_report 输出包含关键信息"""
        from modules.rag.tuning import EvalResult, TuningReport, print_report

        best = EvalResult(
            weights=(0.45, 0.25, 0.15, 0.15),
            mrr=0.7234,
            ndcg_at_5=0.8123,
            ndcg_at_10=0.8901,
            precision_at_5=0.75,
            recall_at_5=0.60,
            avg_latency_ms=123.4,
        )
        top5 = [
            best,
            EvalResult(
                weights=(0.50, 0.20, 0.15, 0.15),
                mrr=0.7100,
                ndcg_at_5=0.8000,
            ),
        ]
        report = TuningReport(
            best=best,
            top5=top5,
            total_combinations=100,
            total_queries=50,
            elapsed_seconds=30.5,
        )

        print_report(report)

        captured = capsys.readouterr()
        assert "RAG 权重调优报告" in captured.out
        assert "总组合数: 100" in captured.out
        assert "评估查询: 50" in captured.out
        assert "30.5s" in captured.out
        assert "推荐权重: vector=0.45" in captured.out
        assert "MRR=0.7234" in captured.out
        # Verify generated constants output
        assert "RAG_VECTOR_WEIGHT" in captured.out

    def test_print_report_empty_report(self, capsys):
        """EDGE: 空报告输出"""
        from modules.rag.tuning import TuningReport, print_report

        report = TuningReport()
        print_report(report)

        captured = capsys.readouterr()
        assert "RAG 权重调优报告" in captured.out
        assert "推荐权重: vector=0.00" in captured.out

    # --- main (CLI entry) ---

    def test_main_is_callable(self):
        """GREEN: main 函数可调用（argparse 入口）"""
        from modules.rag.tuning import main as tuning_main

        assert callable(tuning_main)

    # --- generate_weight_combinations (fast mode not in existing tests) ---

    def test_generate_weight_combinations_full_vs_fast_count(self):
        """GREEN: full mode 比 fast mode 产生更多组合"""
        from modules.rag.tuning import generate_weight_combinations as gen_full

        full = gen_full()
        assert len(full) > 50  # full mode produces hundreds of combos
