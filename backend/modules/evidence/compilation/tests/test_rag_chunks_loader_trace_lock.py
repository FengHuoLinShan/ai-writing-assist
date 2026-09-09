from __future__ import annotations

import uuid

import pytest

from modules.evidence.compilation.contracts import CompileOptions, StructureContextBundle
from modules.evidence.compilation.services.loaders.rag_chunks_loader import (
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
        "modules.evidence.compilation.services.retrieval_trace_service.RetrievalTraceService",
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
    caplog: pytest.LogCaptureFixture,
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

    assert bundle.warnings == []
    assert "Context retrieval trace write failed" in caplog.text


async def test_trace_failure_preserves_confirmation_but_source_change_still_blocks(
    db_session,
    test_project_id,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import patch

    from core.errors import ConflictError
    from modules.evidence.compilation.services.confirmation_service import (
        ContextConfirmationService,
    )
    from modules.evidence.compilation.services.context_compiler import ContextCompiler

    diagnostic_failed = False
    project_title = "不变的测试资料"

    async def record(*_args, **_kwargs):
        if diagnostic_failed:
            raise RuntimeError("simulated lock timeout")

    loader = RagChunksLoader(trace_recorder=record)
    compiler = ContextCompiler()

    async def compile_bundle(db, options):
        bundle = StructureContextBundle(
            novel_id=options.novel_id,
            task=options.task,
            scope=options.scope,
            project={"title": project_title},
        )
        await loader._record_trace(db, options, bundle, {"candidate_count": 0})
        return bundle

    service = ContextConfirmationService(compiler=compiler)
    with patch.object(compiler, "compile", autospec=True, side_effect=compile_bundle):
        confirmation = await service.confirm_context(
            db_session,
            novel_id=test_project_id,
            action="world.map_atlas.structure",
            task="整理地图空间关系",
            scope="full",
        )
        diagnostic_failed = True
        replay = await service.compile_from_confirmation(
            db_session,
            novel_id=test_project_id,
            action="world.map_atlas.structure",
            confirmation_id=confirmation.id,
        )
        assert not replay.warnings
        assert all(section.key != "compiler_warnings" for section in replay.sections)
        project_title = "确实变化的测试资料"
        with pytest.raises(ConflictError, match="AI 参考资料已变化"):
            await service.compile_from_confirmation(
                db_session,
                novel_id=test_project_id,
                action="world.map_atlas.structure",
                confirmation_id=confirmation.id,
            )
