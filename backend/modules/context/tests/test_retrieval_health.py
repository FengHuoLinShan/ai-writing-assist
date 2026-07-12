from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

import pytest

from modules.context.contracts import CompileOptions, StructureContextBundle
from modules.context.facade import get_evidence_health, list_retrieval_traces
from modules.context.services.loaders.rag_chunks_loader import RagChunksLoader
from modules.context.services.retrieval_trace_service import RetrievalTraceService
from modules.rag.contracts import RagChunkContract
from modules.writing.models import WritingDraft


@dataclass
class _FakeRagResult:
    chunks: list[RagChunkContract] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False


@pytest.mark.asyncio
async def test_loader_records_hydration_drop_trace_and_health(
    db_session,
    test_project_id: str,
) -> None:
    content = "第一段正文。第二段正文。"
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    source = WritingDraft(
        novel_id=uuid.UUID(test_project_id),
        chapter_index=1,
        version_number=1,
        status="published",
        content=content,
        content_hash=content_hash,
    )
    db_session.add(source)
    await db_session.flush()

    good = RagChunkContract(
        id=str(uuid.uuid4()),
        novel_id=test_project_id,
        source_type="chapter_text",
        source_id=str(source.id),
        source_content_hash=content_hash,
        content_mode="canonical",
        chapter_index=1,
        start_offset=0,
        end_offset=6,
        text="stale cached text",
    )
    stale = RagChunkContract(
        id=str(uuid.uuid4()),
        novel_id=test_project_id,
        source_type="chapter_text",
        source_id=str(source.id),
        source_content_hash="f" * 64,
        content_mode="canonical",
        chapter_index=1,
        start_offset=6,
        end_offset=12,
        text="stale cached text",
    )

    async def retrieve(*_args, **_kwargs):
        return _FakeRagResult(chunks=[good, stale])

    options = CompileOptions(
        novel_id=test_project_id,
        task="生成当前 Scene",
        scope="chapter",
        chapter_index=1,
        consumer_action="writing.generate",
        retrieval_purpose="writing_generation",
    )
    bundle = StructureContextBundle(
        novel_id=test_project_id,
        task=options.task,
        scope=options.scope,
        chapter_index=1,
    )

    await RagChunksLoader(retrieve_fn=retrieve).load(db_session, options, bundle)

    assert len(bundle.rag_chunks) == 1
    assert bundle.rag_chunks[0]["text"] == content
    traces = await list_retrieval_traces(
        db_session,
        novel_id=test_project_id,
        content_mode="canonical",
    )
    assert len(traces) == 1
    trace = traces[0]
    assert trace.consumer_action == "writing.generate"
    assert trace.retrieval_purpose == "writing_generation"
    assert trace.candidate_count == 2
    assert trace.unique_count == 2
    assert trace.hydrated_count == 1
    assert trace.drop_counts == {"source_hash_mismatch": 1}
    assert trace.safe_empty_reason is None
    assert all("生成当前" not in str(item) for item in trace.clause_summaries)

    health = await get_evidence_health(
        db_session,
        novel_id=test_project_id,
        content_mode="canonical",
    )
    assert health.retrieval_summary["query_count"] == 1
    assert health.retrieval_summary["drop_counts"] == {"source_hash_mismatch": 1}


@pytest.mark.asyncio
async def test_strict_scene_empty_trace_has_safe_reason(
    db_session,
    test_project_id: str,
) -> None:
    async def retrieve(*_args, **_kwargs):
        return _FakeRagResult()

    options = CompileOptions(
        novel_id=test_project_id,
        task="生成角色视角正文",
        scope="chapter",
        chapter_index=1,
        scene_id=str(uuid.uuid4()),
        reveal_mode="character",
        viewpoint_character_id=str(uuid.uuid4()),
        retrieval_purpose="character_context",
    )
    bundle = StructureContextBundle(
        novel_id=test_project_id,
        task=options.task,
        scope=options.scope,
        chapter_index=1,
    )

    await RagChunksLoader(retrieve_fn=retrieve).load(db_session, options, bundle)

    traces = await list_retrieval_traces(
        db_session,
        novel_id=test_project_id,
        content_mode="canonical",
    )
    assert traces[0].safe_empty_reason == "strict_scene_unmapped"
    assert traces[0].hydrated_count == 0


@pytest.mark.asyncio
async def test_trace_retention_enforces_per_project_hard_cap(
    db_session,
    test_project_id: str,
) -> None:
    service = RetrievalTraceService()
    payload = {
        "content_mode": "canonical",
        "consumer_action": "test",
        "retrieval_purpose": "generic_context",
        "reveal_mode": "author",
        "plan_version": "test-v1",
        "plan_hash": "a" * 64,
        "clause_summaries": [],
        "safe_empty_reason": "no_query_clause",
    }
    await service.record(
        db_session,
        novel_id=test_project_id,
        payload=payload,
    )
    await service.record(
        db_session,
        novel_id=test_project_id,
        payload={**payload, "plan_hash": "b" * 64},
    )

    assert (
        await service.prune(
            db_session,
            novel_id=test_project_id,
            retain_latest=1,
            dry_run=True,
        )
        == 1
    )
    assert (
        await service.prune(
            db_session,
            novel_id=test_project_id,
            retain_latest=1,
            dry_run=False,
        )
        == 1
    )
    traces = await service.list(db_session, novel_id=test_project_id)
    assert len(traces) == 1


@pytest.mark.asyncio
async def test_empty_plan_trace_is_classified_as_no_query_clause(
    db_session,
    test_project_id: str,
) -> None:
    options = CompileOptions(
        novel_id=test_project_id,
        task="",
        scope="chapter",
    )
    bundle = StructureContextBundle(
        novel_id=test_project_id,
        task="",
        scope="chapter",
    )

    await RagChunksLoader().load(db_session, options, bundle)

    assert bundle.retrieval_trace["safe_empty_reason"] == "no_query_clause"


@pytest.mark.asyncio
async def test_retrieval_exception_still_records_exactly_one_degraded_trace(
    db_session,
    test_project_id: str,
) -> None:
    async def failing_retrieve(*_args, **_kwargs):
        raise RuntimeError("temporary retrieval failure")

    options = CompileOptions(
        novel_id=test_project_id,
        task="续写当前剧情",
        scope="chapter",
        retrieval_purpose="writing_generation",
    )
    bundle = StructureContextBundle(
        novel_id=test_project_id,
        task=options.task,
        scope=options.scope,
    )

    await RagChunksLoader(retrieve_fn=failing_retrieve).load(
        db_session,
        options,
        bundle,
    )

    traces = await list_retrieval_traces(
        db_session,
        novel_id=test_project_id,
    )
    assert len(traces) == 1
    assert traces[0].degraded is True
    assert traces[0].warning_codes == ["clause_retrieval_failed"]
    assert traces[0].safe_empty_reason == "retrieval_degraded_empty"
