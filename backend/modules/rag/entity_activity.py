"""Rebuildable CoreEntity activity derived from current chapter indexes."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get as _container_get
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.models import AsyncTask
from modules.rag.contracts import (
    RagEntityActivityBundleContract,
    RagEntityActivityStatContract,
)
from modules.rag.query_expansion import (
    _load_project_terms,
    _match_project_terms,
    clear_project_terms_cache,
)
from modules.rag.repositories import RagChunkRepository


class EntityActivityService:
    def __init__(self, repo: RagChunkRepository | None = None) -> None:
        self._repo = repo or RagChunkRepository()

    async def get_stats(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> RagEntityActivityBundleContract:
        nid = uuid.UUID(str(novel_id))
        appearances, states = await self._repo.list_entity_activity_rows(db, nid)
        try:
            chapter_indices = await _container_get(
                "writing.list_effective_chapter_indices"
            )(db, novel_id)
        except KeyError:
            chapter_indices = sorted({state.chapter_index for state in states})

        fresh_states: dict[tuple[int, str], object] = {}
        for state in states:
            if (
                state.status == "succeeded"
                and state.indexed_hash
                and state.indexed_hash == state.requested_hash
            ):
                fresh_states[(state.chapter_index, state.content_mode)] = state

        selected: dict[int, object] = {}
        for chapter_index in chapter_indices:
            state = fresh_states.get((chapter_index, "working"))
            if state is None:
                state = fresh_states.get((chapter_index, "canonical"))
            if state is not None:
                selected[chapter_index] = state

        chapters_by_entity: dict[str, list[int]] = defaultdict(list)
        for appearance in appearances:
            state = selected.get(appearance.chapter_index)
            if state is None:
                continue
            if appearance.content_mode != state.content_mode:
                continue
            if appearance.source_content_hash != state.indexed_hash:
                continue
            chapters_by_entity[str(appearance.entity_id)].append(
                appearance.chapter_index
            )

        items = [
            RagEntityActivityStatContract(
                entity_id=entity_id,
                appearance_chapters=chapters,
                last_chapter_index=max(chapters) if chapters else None,
            )
            for entity_id, chapters in sorted(chapters_by_entity.items())
        ]
        total = len(chapter_indices)
        covered = len(selected)
        status = "unavailable"
        if covered:
            status = "ready" if covered == total else "partial"
        return RagEntityActivityBundleContract(
            items=items,
            as_of_chapter=max(chapter_indices) if chapter_indices else None,
            covered_chapters=covered,
            total_chapters=total,
            status=status,
        )

    async def request_reannotation(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> str:
        """Invalidate term matching and coalesce one project reannotation task."""
        nid = uuid.UUID(str(novel_id))
        clear_project_terms_cache(nid)
        active = list(
            (
                await db.execute(
                    select(AsyncTask).where(
                        AsyncTask.task_type == "rag_reannotate_entities",
                        AsyncTask.status.in_(("pending", "running")),
                        AsyncTask.meta["novel_id"].as_string() == str(nid),
                    )
                )
            )
            .scalars()
            .all()
        )
        for task in active:
            if task.status == "pending":
                return str(task.id)
        # A running task may already have captured an older term snapshot.
        # Queue exactly one pending follower so mutations during execution are
        # never lost; subsequent requests coalesce into that pending row.
        return enqueue_task(
            db,
            "rag_reannotate_entities",
            meta={"novel_id": str(nid)},
        )

    async def reannotate_project(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        progress_callback: Callable[[float], None] | None = None,
    ) -> dict[str, int]:
        """Refresh term associations and appearances, preserving embeddings."""
        nid = uuid.UUID(str(novel_id))
        clear_project_terms_cache(nid)
        terms = await _load_project_terms(db, nid, strict=True)
        keys = await self._repo.list_reannotation_keys(db, nid)
        for chapter_index in sorted({chapter for chapter, _mode in keys}):
            await self._repo.lock_chapter_chunks(db, nid, chapter_index)
        fresh_hashes = await self._repo.list_fresh_index_hashes(db, nid)
        chunks = []
        for chapter_index, content_mode in keys:
            source_hash = fresh_hashes.get((chapter_index, content_mode))
            if not source_hash:
                continue
            chunks.extend(
                await self._repo.list_chapter_chunks_for_reannotation(
                    db,
                    nid,
                    chapter_index=chapter_index,
                    content_mode=content_mode,
                    source_content_hash=source_hash,
                )
            )
        total = len(chunks)
        changed = 0
        for position, chunk in enumerate(chunks, start=1):
            character_ids, entity_ids, thread_ids = _match_project_terms(
                chunk.text,
                terms,
            )
            if (
                list(chunk.character_ids or []) != character_ids
                or list(chunk.entity_ids or []) != entity_ids
                or list(chunk.thread_ids or []) != thread_ids
            ):
                chunk.character_ids = character_ids
                chunk.entity_ids = entity_ids
                chunk.thread_ids = thread_ids
                changed += 1
            if progress_callback and total:
                progress_callback(position / total * 0.9)
        await db.flush()
        await self._repo.replace_project_entity_appearances(
            db,
            nid,
            chunks=chunks,
        )
        if progress_callback:
            progress_callback(1.0)
        return {
            "chunks_scanned": total,
            "chunks_changed": changed,
            "chapter_modes_rebuilt": len(
                {
                    (chunk.chapter_index, chunk.content_mode)
                    for chunk in chunks
                }
            ),
        }
