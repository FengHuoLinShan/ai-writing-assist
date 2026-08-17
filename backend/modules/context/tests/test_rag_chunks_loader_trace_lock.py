from __future__ import annotations

import uuid

import pytest

from modules.context.contracts import CompileOptions, StructureContextBundle
from modules.context.services.loaders.rag_chunks_loader import (
    RagChunksLoader,
    _default_record_trace,
)


class _PostgresBind:
    class _Dialect:
        name = "postgresql"

    dialect = _Dialect()


class _Db:
    def get_bind(self):
        return _PostgresBind()


class _TraceSession:
    def __init__(self, *, fail: bool = False) -> None:
        self.statements: list[str] = []
        self.committed = False
        self.fail = fail

    async def execute(self, statement, *_args, **_kwargs) -> None:
        self.statements.append(str(statement))
        if self.fail:
            raise RuntimeError("simulated lock timeout")

    async def commit(self) -> None:
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info) -> None:
        return None


@pytest.mark.asyncio
async def test_pg_trace_session_sets_lock_timeout_before_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _TraceSession()

    class _Manager:
        def session_factory(self):
            return session

    calls: list[str] = []

    async def _record(_db, *, novel_id, payload):
        calls.append(novel_id)
        assert payload == {"candidate_count": 1}
        return object()

    monkeypatch.setattr("core.database.get_manager", lambda: _Manager())
    monkeypatch.setattr(
        "modules.context.services.retrieval_trace_service.RetrievalTraceService",
        lambda: type("Service", (), {"record": staticmethod(_record)})(),
    )

    novel_id = str(uuid.uuid4())
    await _default_record_trace(
        _Db(),
        novel_id=novel_id,
        payload={"candidate_count": 1},
    )

    assert calls == [novel_id]
    assert session.committed is True
    assert session.statements == ["SET LOCAL lock_timeout = '2000ms'"]


@pytest.mark.asyncio
async def test_pg_trace_lock_timeout_does_not_block_context_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Manager:
        def session_factory(self):
            return _TraceSession(fail=True)

    monkeypatch.setattr("core.database.get_manager", lambda: _Manager())
    loader = RagChunksLoader()
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="核对当前正文证据",
        scope="chapter",
        chapter_index=1,
        retrieval_purpose="manual_search",
    )
    bundle = StructureContextBundle(
        novel_id=options.novel_id,
        task=options.task,
        scope=options.scope,
    )

    await loader._record_trace(
        _Db(),
        options,
        bundle,
        {"candidate_count": 0, "unique_count": 0, "hydrated_count": 0},
    )

    assert "RAG 检索诊断记录失败" in bundle.warnings
