"""
RAG 章节索引

IndexingService 负责把章节正文处理为 RAG chunk 并生成 embedding，
包括读取草稿、分块、角色/实体匹配、去重创建和批量 embedding 的全流程。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag.chunk_annotation import build_chunk_create
from modules.rag.chunking import ChunkingService
from modules.rag.contracts import RagIndexReport, RagTaskIndexOutcome
from modules.rag.embedding_writer import EmbeddingWriter, EmbeddingWriteResult
from modules.rag.repositories import RagChunkRepository
from modules.rag.schemas import RagChunkCreate
from modules.rag.source_collection import collect_chapter_sources

_MAX_PREPARED_SOURCE_ATTEMPTS = 3
_EMBEDDING_RETRY_BATCH_SIZE = 500


@dataclass(frozen=True)
class _ChapterIndexPlan:
    chapter_index: int
    content_mode: str
    source_draft_id: str | None
    source_content_hash: str | None
    items: list[RagChunkCreate]


@dataclass
class _EmbeddingTarget:
    chunk_index: int
    text: str
    embedding: object | None = None
    embedding_status: str = "pending"
    embedding_error: str | None = None
    index_warnings: list[str] = field(default_factory=list)


@dataclass
class _EmbeddingRetryTarget:
    """Detached retry input plus the source/version fence used on write-back."""

    chunk_id: uuid.UUID
    novel_id: uuid.UUID
    text: str
    expected_status: str
    source_type: str
    source_id: uuid.UUID | None
    source_content_hash: str | None
    content_mode: str
    chapter_index: int | None
    chunk_index: int | None
    index_version: str
    embedding: object | None = None
    embedding_status: str = "pending"
    embedding_error: str | None = None
    index_warnings: list[str] = field(default_factory=list)


class IndexingService:
    """章节索引服务。

    构造函数注入 repo 与 chunking；默认自行实例化以保持现有调用方式兼容。
    """

    def __init__(
        self,
        repo: RagChunkRepository | None = None,
        chunking: ChunkingService | None = None,
    ) -> None:
        self._repo = repo or RagChunkRepository()
        self._chunking = chunking or ChunkingService()

    async def index_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
        *,
        content_mode: str = "canonical",
    ) -> int:
        """索引指定章节的正文到 RAG 库，返回创建的 chunk 数。"""
        report = await self.index_chapter_with_report(
            db,
            novel_id,
            chapter_index,
            content_mode=content_mode,
        )
        return report.chunks_created

    async def index_chapter_with_report(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
        *,
        content_mode: str = "canonical",
    ) -> RagIndexReport:
        """索引指定章节并返回诊断报告。"""
        started_at = time.monotonic()
        plan = await self._prepare_chapter_index(
            db,
            novel_id,
            chapter_index,
            content_mode=content_mode,
        )
        return await self._persist_plan_with_live_embeddings(
            db,
            novel_id,
            plan,
            started_at=started_at,
        )

    async def index_chapter_for_task(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID | str,
        chapter_index: int,
        *,
        content_mode: str = "canonical",
        force: bool = False,
    ) -> RagTaskIndexOutcome:
        """Index a chapter without holding a DB transaction during embedding.

        This entry point is only for TaskWorker handler sessions.  The explicit
        commit is lease/project fenced by ``_TaskHandlerSession`` and closes the
        source-read transaction before the slow external embedding call.  The
        prepared source is claimed and revalidated immediately before the short
        persistence transaction, so a concurrent publish cannot install stale
        chunks as fresh.
        """
        from infrastructure.tasks.facade import require_task_checkpoint_session
        from modules.project.facade import require_active_project
        from modules.rag.index_state import RagIndexStateService

        require_task_checkpoint_session(db)
        normalized_novel_id = uuid.UUID(str(novel_id))
        state_service = RagIndexStateService()
        started_at = time.monotonic()

        async def _mark_failed(
            error: str,
            expected_plan: _ChapterIndexPlan | None,
        ) -> None:
            await db.rollback()
            await require_active_project(db, str(normalized_novel_id))
            await state_service.fail(
                db,
                novel_id=str(normalized_novel_id),
                chapter_index=chapter_index,
                content_mode=content_mode,
                error=error,
                expected_source_id=(
                    expected_plan.source_draft_id if expected_plan else None
                ),
                expected_source_hash=(
                    expected_plan.source_content_hash if expected_plan else None
                ),
                match_expected_source=expected_plan is not None,
            )
            await db.commit()

        last_plan: _ChapterIndexPlan | None = None
        for _attempt in range(_MAX_PREPARED_SOURCE_ATTEMPTS):
            try:
                # Keep deletion lock order project -> domain in every short
                # transaction, including source/span preparation.
                await require_active_project(db, str(normalized_novel_id))
                plan = await self._prepare_chapter_index(
                    db,
                    normalized_novel_id,
                    chapter_index,
                    content_mode=content_mode,
                )
                last_plan = plan
                preflight = await state_service.preflight_prepared(
                    db,
                    novel_id=str(normalized_novel_id),
                    chapter_index=chapter_index,
                    content_mode=content_mode,
                    source_draft_id=plan.source_draft_id,
                    source_content_hash=plan.source_content_hash,
                    force=force,
                )
                if preflight == "source_changed":
                    await db.rollback()
                    continue

                # A task-session commit passes the project/lease fence and
                # releases all source/state locks before provider queue waits.
                await db.commit()
                # TaskWorker sessions intentionally keep ORM state across
                # commits. Expire the first-read identity map so the final
                # source/project revalidation cannot reuse stale Writing,
                # Outline, or World rows after the provider wait. ``plan`` is
                # detached scalar/Pydantic DTO data and remains safe to use.
                db.expire_all()
                if preflight == "fresh":
                    return self._coalesced_outcome(plan)
                targets, embedding_result = await self._embed_plan(plan)

                await require_active_project(db, str(normalized_novel_id))
                claim = await state_service.begin_prepared(
                    db,
                    novel_id=str(normalized_novel_id),
                    chapter_index=chapter_index,
                    content_mode=content_mode,
                    source_draft_id=plan.source_draft_id,
                    source_content_hash=plan.source_content_hash,
                    force=force,
                )
                if claim == "source_changed":
                    await db.rollback()
                    continue
                if claim != "claimed":
                    await db.rollback()
                    return self._coalesced_outcome(plan)

                report = await self._persist_preembedded_plan(
                    db,
                    normalized_novel_id,
                    plan,
                    targets=targets,
                    embedding_result=embedding_result,
                    started_at=started_at,
                )
                followup_task_id = await state_service.finish(
                    db,
                    novel_id=str(normalized_novel_id),
                    report=report,
                )
                # Release state/chunk locks before publish starts memory or a
                # rebuild advances to the next chapter.
                await db.commit()
                return RagTaskIndexOutcome(
                    report=report,
                    status="indexed",
                    followup_task_id=followup_task_id,
                )
            except Exception:
                try:
                    await _mark_failed("task indexing failed", last_plan)
                except Exception:
                    await db.rollback()
                raise

        await _mark_failed(
            "source changed repeatedly during task indexing",
            last_plan,
        )
        raise RuntimeError("章节源在索引期间持续变化，请稍后重试")

    @staticmethod
    def _coalesced_outcome(plan: _ChapterIndexPlan) -> RagTaskIndexOutcome:
        return RagTaskIndexOutcome(
            report=RagIndexReport(
                chapter_index=plan.chapter_index,
                content_mode=plan.content_mode,
                source_draft_id=plan.source_draft_id,
                source_content_hash=plan.source_content_hash,
                warnings=["索引任务已合并或当前版本已是最新"],
            ),
            status="coalesced",
        )

    async def _prepare_chapter_index(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
        *,
        content_mode: str,
    ) -> _ChapterIndexPlan:
        sources = await collect_chapter_sources(
            db,
            novel_id,
            chapter_index,
            content_mode=content_mode,
        )
        if sources is None:
            return _ChapterIndexPlan(
                chapter_index=chapter_index,
                content_mode=content_mode,
                source_draft_id=None,
                source_content_hash=None,
                items=[],
            )

        chunks = self._chunking.split_chinese_novel(sources.content)
        if not chunks:
            return _ChapterIndexPlan(
                chapter_index=chapter_index,
                content_mode=content_mode,
                source_draft_id=sources.source_draft_id,
                source_content_hash=sources.source_content_hash,
                items=[],
            )

        items = [
            build_chunk_create(
                cn_chunk,
                chapter_index=chapter_index,
                content_mode=content_mode,
                source_draft_id=sources.source_draft_id,
                source_content_hash=sources.source_content_hash,
                chunking=self._chunking,
                project_terms=sources.project_terms,
                entity_importance_map=sources.entity_importance_map,
                scenes_for_chapter=sources.scenes_for_chapter,
                scene_spans_for_chapter=sources.scene_spans_for_chapter,
            )
            for cn_chunk in chunks
        ]
        return _ChapterIndexPlan(
            chapter_index=chapter_index,
            content_mode=content_mode,
            source_draft_id=sources.source_draft_id,
            source_content_hash=sources.source_content_hash,
            items=items,
        )

    async def _persist_plan_with_live_embeddings(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        plan: _ChapterIndexPlan,
        *,
        started_at: float,
    ) -> RagIndexReport:
        created_chunks = await self._repo.replace_chapter_chunks(
            db,
            novel_id,
            source_type="chapter_text",
            chapter_index=plan.chapter_index,
            items=plan.items,
            content_mode=plan.content_mode,
        )

        await db.flush()
        async with EmbeddingWriter(self._repo) as embedding_writer:
            embedding_result = await embedding_writer.write_batch(
                db,
                created_chunks,
                warning_prefix="章节 embedding 失败",
            )

        return self._build_report(
            plan,
            created_chunks=created_chunks,
            embedding_result=embedding_result,
            started_at=started_at,
        )

    async def _embed_plan(
        self,
        plan: _ChapterIndexPlan,
    ) -> tuple[list[_EmbeddingTarget], EmbeddingWriteResult]:
        targets = [
            _EmbeddingTarget(
                chunk_index=int(item.chunk_index or 0),
                text=item.text,
            )
            for item in plan.items
        ]
        if not targets:
            return targets, EmbeddingWriteResult()
        async with EmbeddingWriter(self._repo) as embedding_writer:
            result = await embedding_writer.embed_batch(
                targets,
                warning_prefix="章节 embedding 失败",
            )
        return targets, result

    async def _persist_preembedded_plan(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        plan: _ChapterIndexPlan,
        *,
        targets: list[_EmbeddingTarget],
        embedding_result: EmbeddingWriteResult,
        started_at: float,
    ) -> RagIndexReport:
        created_chunks = await self._repo.replace_chapter_chunks(
            db,
            novel_id,
            source_type="chapter_text",
            chapter_index=plan.chapter_index,
            items=plan.items,
            content_mode=plan.content_mode,
        )
        targets_by_index = {target.chunk_index: target for target in targets}
        for chunk in created_chunks:
            target = targets_by_index.get(int(chunk.chunk_index or 0))
            if target is None:
                raise RuntimeError("RAG 分块与预计算 embedding 无法对齐")
            chunk.embedding = target.embedding  # type: ignore[assignment]
            chunk.embedding_status = target.embedding_status
            chunk.embedding_error = target.embedding_error
            chunk.index_warnings = list(target.index_warnings)
        await db.flush()

        return self._build_report(
            plan,
            created_chunks=created_chunks,
            embedding_result=embedding_result,
            started_at=started_at,
        )

    @staticmethod
    def _build_report(
        plan: _ChapterIndexPlan,
        *,
        created_chunks: list,
        embedding_result: EmbeddingWriteResult,
        started_at: float,
    ) -> RagIndexReport:
        from modules.rag.metrics import get_metrics

        get_metrics().record_indexing(
            chunks_created=len(created_chunks),
            embedding_failed_count=embedding_result.failed_count,
            latency_ms=(time.monotonic() - started_at) * 1000,
        )

        return RagIndexReport(
            chapter_index=plan.chapter_index,
            content_mode=plan.content_mode,
            source_draft_id=plan.source_draft_id,
            source_content_hash=plan.source_content_hash,
            chunks_created=len(created_chunks),
            warnings=embedding_result.warnings,
            embedding_failed_count=embedding_result.failed_count,
            chunks_created_ids=[str(c.id) for c in created_chunks],
        )

    async def index_chapter_incremental(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
        old_content: str,
        new_content: str,
        *,
        content_mode: str = "working",
    ) -> RagIndexReport:
        """Compatibility entry point that performs a version-bound full replace.

        Reusing chunks across draft IDs would make their source hash and offsets
        unverifiable. ``old_content``/``new_content`` remain accepted for wire
        compatibility, but the current concrete writing source is authoritative.
        """
        from dataclasses import replace

        del old_content, new_content
        report = await self.index_chapter_with_report(
            db,
            novel_id,
            chapter_index,
            content_mode=content_mode,
        )
        return replace(
            report,
            warnings=[
                "版本绑定索引已使用当前正文执行全量替换",
                *report.warnings,
            ],
        )

    async def retry_embeddings(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
        statuses: list[str] | None = None,
        progress_callback: Callable[[float], None] | None = None,
    ) -> dict:
        """Retry failed or pending chunk embeddings for one novel."""
        started_at = time.monotonic()
        retry_statuses = self._normalize_embedding_retry_statuses(statuses)

        initial_total = await self._repo.count_retryable_embeddings(
            db,
            novel_id,
            statuses=retry_statuses,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )

        total = initial_total
        succeeded = 0
        failed = 0
        warnings: list[str] = []

        from modules.rag.metrics import get_metrics

        if initial_total == 0:
            if progress_callback is not None:
                progress_callback(1.0)
            await db.flush()
            get_metrics().record_embedding_retry(
                total=0,
                failed=0,
                latency_ms=(time.monotonic() - started_at) * 1000,
            )
            return {
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "remaining_retryable_count": 0,
                "warnings": [],
            }

        async with EmbeddingWriter(self._repo) as embedding_writer:
            while True:
                candidates = await self._repo.find_embedding_retry_candidates(
                    db,
                    novel_id,
                    statuses=retry_statuses,
                    start_chapter=start_chapter,
                    end_chapter=end_chapter,
                )
                if not candidates:
                    break

                embedding_result = await embedding_writer.write_batch(
                    db,
                    candidates,
                    warning_prefix="embedding 重试失败",
                )
                batch_succeeded = len(candidates) - embedding_result.failed_count
                succeeded += batch_succeeded
                warnings.extend(embedding_result.warnings)
                if progress_callback is not None:
                    progress_callback(min(1.0, succeeded / max(initial_total, 1)))

                if embedding_result.failed_count == 0:
                    continue
                failed += embedding_result.failed_count
                break

        remaining_retryable_count = await self._repo.count_retryable_embeddings(
            db,
            novel_id,
            statuses=retry_statuses,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        if remaining_retryable_count == 0 and failed == 0:
            if progress_callback is not None:
                progress_callback(1.0)
            await db.flush()

        get_metrics().record_embedding_retry(
            total=total,
            failed=failed,
            latency_ms=(time.monotonic() - started_at) * 1000,
        )

        return {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "remaining_retryable_count": remaining_retryable_count,
            "warnings": warnings,
        }

    async def retry_embeddings_for_task(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID | str,
        *,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
        statuses: list[str] | None = None,
        progress_callback: Callable[[float], None] | None = None,
    ) -> dict:
        """Retry embeddings with lease-fenced commits around provider waits.

        This task-only seam deliberately owns transaction checkpoints.  Each
        provider call receives detached values after the source-read transaction
        commits.  Write-back locks and reloads only the same-novel chunk IDs, then
        applies a result only when text, retry status, and source/version fields
        still match the detached plan.
        """
        from infrastructure.tasks.facade import require_task_checkpoint_session
        from modules.project.facade import require_active_project
        from modules.rag.metrics import get_metrics

        require_task_checkpoint_session(db)
        normalized_novel_id = uuid.UUID(str(novel_id))
        retry_statuses = self._normalize_embedding_retry_statuses(statuses)
        started_at = time.monotonic()
        total: int | None = None
        resolved_chunk_ids: set[uuid.UUID] = set()
        failed_chunk_ids: set[uuid.UUID] = set()
        warnings: list[str] = []
        remaining_retryable_count = 0
        seen_chunk_ids: set[uuid.UUID] = set()

        async with EmbeddingWriter(self._repo) as embedding_writer:
            while True:
                # Project is always the first row lock in each short transaction,
                # so permanent deletion cannot deadlock against chunk write-back.
                await require_active_project(db, str(normalized_novel_id))
                if total is None:
                    total = await self._repo.count_retryable_embeddings(
                        db,
                        normalized_novel_id,
                        statuses=retry_statuses,
                        start_chapter=start_chapter,
                        end_chapter=end_chapter,
                    )
                candidates = await self._repo.find_embedding_retry_candidate_values(
                    db,
                    normalized_novel_id,
                    statuses=retry_statuses,
                    start_chapter=start_chapter,
                    end_chapter=end_chapter,
                    limit=_EMBEDDING_RETRY_BATCH_SIZE,
                )
                targets = [
                    self._detach_embedding_retry_target(candidate)
                    for candidate in candidates
                ]
                seen_chunk_ids.update(target.chunk_id for target in targets)
                total = max(total, len(seen_chunk_ids))
                if not targets and progress_callback is not None:
                    progress_callback(1.0)

                # The TaskWorker commit hook validates project/lease ownership and
                # releases the read transaction before any provider queue wait.
                await db.commit()
                if not targets:
                    remaining_retryable_count = 0
                    break

                embedding_result = await embedding_writer.embed_batch(
                    targets,
                    warning_prefix="embedding 重试失败",
                )

                await require_active_project(db, str(normalized_novel_id))
                current_chunks = (
                    await self._repo.find_embedding_retry_rows_by_ids_for_update(
                        db,
                        normalized_novel_id,
                        [target.chunk_id for target in targets],
                    )
                )
                current_by_id = {chunk.id: chunk for chunk in current_chunks}
                for target in targets:
                    current = current_by_id.get(target.chunk_id)
                    if current is None:
                        # Deletion while the provider was running resolves this
                        # retry target without turning the stale result into a
                        # write.  Sets keep a later same-ID replan idempotent.
                        resolved_chunk_ids.add(target.chunk_id)
                        failed_chunk_ids.discard(target.chunk_id)
                        continue
                    if not self._embedding_retry_target_matches(current, target):
                        # A still-retryable source/version change is replanned in
                        # the next loop.  A concurrent completion, deletion-like
                        # status transition, or move outside the requested range
                        # is already resolved for this task scope.
                        if not self._embedding_retry_chunk_still_in_scope(
                            current,
                            statuses=retry_statuses,
                            start_chapter=start_chapter,
                            end_chapter=end_chapter,
                        ):
                            resolved_chunk_ids.add(target.chunk_id)
                            failed_chunk_ids.discard(target.chunk_id)
                        continue
                    current.embedding = target.embedding  # type: ignore[assignment]
                    current.embedding_status = target.embedding_status
                    current.embedding_error = target.embedding_error
                    current.index_warnings = list(target.index_warnings)
                    if target.embedding_status == "succeeded":
                        resolved_chunk_ids.add(target.chunk_id)
                        failed_chunk_ids.discard(target.chunk_id)
                    elif target.embedding_status == "failed":
                        failed_chunk_ids.add(target.chunk_id)
                        resolved_chunk_ids.discard(target.chunk_id)

                warnings.extend(embedding_result.warnings)
                if progress_callback is not None:
                    progress_callback(min(1.0, len(resolved_chunk_ids) / max(total, 1)))
                await db.flush()
                # Persist only still-matching rows and release the project/chunk
                # locks before the next provider batch.
                await db.commit()

                if embedding_result.failed_count > 0:
                    await require_active_project(db, str(normalized_novel_id))
                    remaining_retryable_count = (
                        await self._repo.count_retryable_embeddings(
                            db,
                            normalized_novel_id,
                            statuses=retry_statuses,
                            start_chapter=start_chapter,
                            end_chapter=end_chapter,
                        )
                    )
                    await db.commit()
                    break

        final_total = total or 0
        succeeded = len(resolved_chunk_ids)
        failed = len(failed_chunk_ids)
        get_metrics().record_embedding_retry(
            total=final_total,
            failed=failed,
            latency_ms=(time.monotonic() - started_at) * 1000,
        )
        return {
            "total": final_total,
            "succeeded": succeeded,
            "failed": failed,
            "remaining_retryable_count": remaining_retryable_count,
            "warnings": warnings,
        }

    @staticmethod
    def _normalize_embedding_retry_statuses(statuses: list[str] | None) -> list[str]:
        allowed_statuses = {"failed", "pending_vectorization"}
        retry_statuses = [
            status
            for status in (statuses or ["failed", "pending_vectorization"])
            if status in allowed_statuses
        ]
        return retry_statuses or ["failed", "pending_vectorization"]

    @staticmethod
    def _detach_embedding_retry_target(chunk) -> _EmbeddingRetryTarget:  # noqa: ANN001
        return _EmbeddingRetryTarget(
            chunk_id=chunk.id,
            novel_id=chunk.novel_id,
            text=chunk.text,
            expected_status=chunk.embedding_status,
            source_type=chunk.source_type,
            source_id=chunk.source_id,
            source_content_hash=chunk.source_content_hash,
            content_mode=chunk.content_mode,
            chapter_index=chunk.chapter_index,
            chunk_index=chunk.chunk_index,
            index_version=chunk.index_version,
        )

    @staticmethod
    def _embedding_retry_target_matches(chunk, target: _EmbeddingRetryTarget) -> bool:  # noqa: ANN001
        return (
            chunk.id == target.chunk_id
            and chunk.novel_id == target.novel_id
            and chunk.text == target.text
            and chunk.embedding_status == target.expected_status
            and chunk.source_type == target.source_type
            and chunk.source_id == target.source_id
            and chunk.source_content_hash == target.source_content_hash
            and chunk.content_mode == target.content_mode
            and chunk.chapter_index == target.chapter_index
            and chunk.chunk_index == target.chunk_index
            and chunk.index_version == target.index_version
        )

    @staticmethod
    def _embedding_retry_chunk_still_in_scope(  # noqa: ANN001
        chunk,
        *,
        statuses: list[str],
        start_chapter: int | None,
        end_chapter: int | None,
    ) -> bool:
        if chunk.embedding_status not in statuses:
            return False
        if start_chapter is not None and (
            chunk.chapter_index is None or chunk.chapter_index < start_chapter
        ):
            return False
        return not (
            end_chapter is not None
            and (chunk.chapter_index is None or chunk.chapter_index > end_chapter)
        )
