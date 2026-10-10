"""Dedicated PostgreSQL: bounded query counts and source-epoch invalidation."""

from collections import Counter
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from modules.evolution import freshness
from modules.evolution.facade import switch_project_engine
from modules.evolution.ledger import claim_freshness
from modules.evolution.models import EvolutionFrozenAttempt, EvolutionSourceEpoch
from modules.evolution.tests.issue209_data import seed_history
from modules.project.models import Project
from modules.story.outline_state.models import Scene
from modules.writing.models import WritingDraft
from tests.e2e.config import DATABASE_URL

pytestmark = pytest.mark.e2e


@pytest_asyncio.fixture
async def history_project(request):
    count = getattr(request, "param", 10)
    engine = create_async_engine(DATABASE_URL, pool_size=2, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = str(uuid4())
    try:
        async with sessions() as db:
            db.add(Project(id=UUID(nid), title="Issue209 合成小说"))
            await db.flush()
            await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
            claims = await seed_history(db, nid, count)
            await db.commit()
        yield engine, sessions, nid, claims
    finally:
        async with sessions() as db:
            await db.execute(delete(Project).where(Project.id == UUID(nid)))
            await db.commit()
        await engine.dispose()


@pytest.mark.parametrize("history_project", [1, 10, 100], indirect=True)
async def test_warm_calls_across_sessions_do_not_revalidate_history(history_project):
    engine, sessions, nid, claims = history_project
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.split()))

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        async with sessions() as db:
            assert await claim_freshness(db, nid, claims[-1]) == "current"
            cold = len(statements)
        statements.clear()
        async with sessions() as db:
            for claim in reversed(claims):
                assert await claim_freshness(db, nid, claim, cache={}) == "current"
        # The fully verified maximal prefix certifies each owned earlier prefix.
        assert len(statements) == len(claims)
        assert all("evolution_source_epochs" in query for query in statements)
        assert cold > len(claims)
        assert Counter(statements).most_common(1)[0][1] == len(claims)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


async def test_scene_source_updates_rollback_restore_and_new_version(history_project):
    _, sessions, nid, claims = history_project
    claim, original = claims[-1], claims[0]
    cache = {}  # Reusing a caller dictionary must never bypass the epoch guard.
    async with sessions() as db:
        assert await claim_freshness(db, nid, claim, cache=cache) == "current"
        draft_id = UUID(original.evidence[0].source_ref.draft_id)
        draft = await db.get(WritingDraft, draft_id)
        text, digest = draft.content, draft.content_hash
        draft.content = "否" + text[1:]  # Same length, even if hash wasn't recomputed.
        await db.flush()
        assert await claim_freshness(db, nid, claim, cache=cache) == "source_changed"
        dirty_epoch = await freshness._epoch(db, nid)
        await db.rollback()
        assert await claim_freshness(db, nid, claim) == "current"
        draft = await db.get(WritingDraft, draft_id)
        draft.content = "另" + text[1:]
        await db.flush()
        assert await freshness._epoch(db, nid) != dirty_epoch
        assert await claim_freshness(db, nid, claim) == "source_changed"
        draft.content, draft.content_hash = text, digest
        await db.commit()
        assert await claim_freshness(db, nid, claim) == "current"
        # Historical restore via a new version remains a different source identity.
        db.add(
            WritingDraft(
                novel_id=UUID(nid),
                chapter_index=1,
                version_number=2,
                content=text,
                content_hash=digest,
                status="draft",
            )
        )
        await db.commit()
        assert await claim_freshness(db, nid, claim) == "source_changed"
        await db.execute(
            delete(WritingDraft).where(
                WritingDraft.novel_id == UUID(nid), WritingDraft.version_number == 2
            )
        )
        await db.commit()
        assert await claim_freshness(db, nid, claim) == "current"
        scene = await db.get(Scene, original.dependencies[0].scene_id)
        scene.scene_index = 999
        await db.commit()
        assert await claim_freshness(db, nid, claim) == "source_changed"
        scene.scene_index = 0
        await db.commit()
        assert await claim_freshness(db, nid, claim) == "current"


async def test_frozen_change_and_project_isolation(history_project):
    _, sessions, nid, claims = history_project
    async with sessions() as db:
        assert await claim_freshness(db, nid, claims[-1]) == "current"
        row = await db.scalar(
            select(EvolutionFrozenAttempt).where(
                EvolutionFrozenAttempt.novel_id == UUID(nid),
                EvolutionFrozenAttempt.attempt_key
                == claims[0].dependencies[0].attempt_id,
            )
        )
        payload = deepcopy(row.payload_json)
        row.payload_json = {**payload, "previous_receipt": "missing"}
        # The previous receipt is a column, not an arbitrary payload label.
        row.previous_receipt = "missing"
        await db.commit()
        assert await claim_freshness(db, nid, claims[-1]) == "source_changed"
        row.previous_receipt, row.payload_json = None, payload
        await db.commit()
        assert await claim_freshness(db, nid, claims[-1]) == "current"
        assert await claim_freshness(db, str(uuid4()), claims[-1]) == "source_changed"
        other = Project(title="独立项目", id=uuid4())
        db.add(other)
        await db.flush()
        other_id = str(other.id)
        await switch_project_engine(db, other_id, to_engine="evolution", expected_epoch=1)
        # Same run and attempt names; its manifest and source identity differ.
        other_claims = await seed_history(db, other_id, 2)
        await db.commit()
        try:
            assert await claim_freshness(db, other_id, other_claims[-1]) == "current"
            assert await claim_freshness(db, other_id, claims[-1]) == "source_changed"
            assert await claim_freshness(db, nid, claims[-1]) == "current"
        finally:
            await db.execute(delete(Project).where(Project.id == other.id))
            await db.commit()


async def test_cache_bounded_and_missing_epoch_fails_to_full_verification(
    history_project, monkeypatch
):
    engine, sessions, nid, claims = history_project
    monkeypatch.setattr(freshness, "MAX_CACHED_PREFIXES", 3)
    async with sessions() as db:
        assert await claim_freshness(db, nid, claims[-1]) == "current"
        assert len(freshness._RESULTS[engine.sync_engine]) <= 3
        await db.execute(
            delete(EvolutionSourceEpoch).where(EvolutionSourceEpoch.novel_id == UUID(nid))
        )
        await db.commit()
        assert await claim_freshness(db, nid, claims[-1]) == "current"
        scene = await db.get(Scene, claims[0].dependencies[0].scene_id)
        scene.status = "deprecated"
        await db.commit()
        assert await claim_freshness(db, nid, claims[-1]) == "source_changed"


async def test_concurrent_writer_cannot_publish_a_mixed_snapshot(
    history_project, monkeypatch
):
    _, sessions, nid, claims = history_project
    original = freshness.require_current_prefix
    edited = False

    async def verify_then_edit(db, store, frozen, *, verified=None):
        nonlocal edited
        await original(db, store, frozen, verified=verified)
        if not edited:
            async with sessions() as writer:
                scene = await writer.get(Scene, claims[0].dependencies[0].scene_id)
                scene.status = "deprecated"
                await writer.commit()
            edited = True

    monkeypatch.setattr(freshness, "require_current_prefix", verify_then_edit)
    async with sessions() as db:
        assert await claim_freshness(db, nid, claims[-1]) == "source_changed"
        assert await claim_freshness(db, nid, claims[-1]) == "source_changed"


async def test_unrelated_append_reuses_the_unchanged_prefix(history_project):
    engine, sessions, nid, claims = history_project
    async with sessions() as db:
        assert await claim_freshness(db, nid, claims[-1]) == "current"
        db.add(
            WritingDraft(
                novel_id=UUID(nid),
                chapter_index=999,
                content="末尾追加。",
                content_hash="a" * 64,
                status="draft",
            )
        )
        await db.commit()
        queries = []

        def record(conn, cursor, statement, parameters, context, executemany):
            queries.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", record)
        try:
            assert await claim_freshness(db, nid, claims[-1]) == "current"
            assert len(queries) == 3  # Project guard, dependency tokens, final guard.
            assert all("evolution_source_epochs" in query for query in queries)
            queries.clear()
            assert await claim_freshness(db, nid, claims[-1]) == "current"
            assert len(queries) == 1
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", record)


@pytest.mark.parametrize(
    "source_kind",
    ["scene_spans", "scene_chapter_links", "evolution_receipts", "evolution_runs"],
)
async def test_every_remaining_source_table_rotates_the_correct_token(
    history_project, source_kind
):
    from sqlalchemy import text

    _, sessions, nid, claims = history_project
    async with sessions() as db:
        assert await claim_freshness(db, nid, claims[-1]) == "current"
        scene_id = claims[0].dependencies[0].scene_id
        scope = f"scene:{scene_id}"
        before = await freshness._tokens(db, nid, [scope, "project"])
        if source_kind == "scene_spans":
            from modules.story.outline_state.models import SceneSpan

            db.add(
                SceneSpan(
                    novel_id=UUID(nid),
                    scene_id=scene_id,
                    chapter_index=1,
                    part_no=0,
                    content_mode="working",
                    mapping_status="exact",
                    start_offset=1,
                    end_offset=2,
                    status="draft",
                )
            )
        elif source_kind == "scene_chapter_links":
            # There is no source link in the synthetic seed; Scene chapter_ids
            # remains the authoritative mapping, but link changes still fence it.
            from modules.story.outline_state.models import SceneChapterLink

            db.add(
                SceneChapterLink(novel_id=UUID(nid), scene_id=scene_id, chapter_index=1)
            )
        elif source_kind == "evolution_receipts":
            await db.execute(
                text(
                    "UPDATE evolution_receipts SET execution_status = 'failed' "
                    "WHERE novel_id = :nid AND committed_scene_index = 0"
                ),
                {"nid": UUID(nid)},
            )
        else:
            scope = "run:issue209-history"
            before = await freshness._tokens(db, nid, [scope, "project"])
            await db.execute(
                text(
                    "UPDATE evolution_runs SET execution_mode = 'shadow' "
                    "WHERE novel_id = :nid"
                ),
                {"nid": UUID(nid)},
            )
        await db.flush()
        after = await freshness._tokens(db, nid, [scope, "project"])
        assert before["project"] != after["project"]
        assert before[scope] != after[scope]
        if source_kind != "scene_chapter_links":
            assert await claim_freshness(db, nid, claims[-1]) == "source_changed"
        await db.rollback()
        assert await claim_freshness(db, nid, claims[-1]) == "current"


async def test_inherited_run_changes_and_newer_successful_attempt(history_project):
    from sqlalchemy import text

    from modules.evolution.models import EvolutionRun

    _, sessions, nid, claims = history_project
    async with sessions() as db:
        # A newer successful extraction of an existing Scene invalidates an old
        # proof even though the draft content and boundary remain unchanged.
        assert await claim_freshness(db, nid, claims[-1]) == "current"
        first = claims[0].dependencies[0]
        original = await db.scalar(
            select(EvolutionFrozenAttempt).where(
                EvolutionFrozenAttempt.novel_id == UUID(nid),
                EvolutionFrozenAttempt.attempt_key == first.attempt_id,
            )
        )
        db.add(
            EvolutionRun(
                novel_id=UUID(nid),
                run_key="newer-success",
                mode="revise",
                status="drained",
                execution_mode="live",
            )
        )
        db.add(
            EvolutionFrozenAttempt(
                novel_id=UUID(nid),
                run_key="newer-success",
                attempt_key="b" * 64,
                owner_epoch=1,
                producer_version="synthetic",
                source_manifest_hash="c" * 64,
                status="applied",
                payload_json=original.payload_json,
            )
        )
        await db.flush()
        await db.execute(
            text(
                "INSERT INTO evolution_receipts(id, novel_id, run_key, "
                "attempt_key, execution_status, committed_scene_index, "
                "committed_source_revision, receipt_json, created_at) VALUES "
                "(:id, :nid, 'newer-success', :attempt, 'succeeded', 0, 1, "
                "'{}', now() + interval '1 second')"
            ),
            {"id": uuid4(), "nid": UUID(nid), "attempt": "b" * 64},
        )
        await db.commit()
        assert await claim_freshness(db, nid, claims[-1]) == "source_changed"
        await db.execute(
            text(
                "UPDATE evolution_runs SET execution_mode='shadow' "
                "WHERE novel_id=:nid AND run_key='newer-success'"
            ),
            {"nid": UUID(nid)},
        )
        await db.commit()
        assert await claim_freshness(db, nid, claims[-1]) == "current"
        await db.execute(
            text(
                "UPDATE evolution_runs SET execution_mode='live' "
                "WHERE novel_id=:nid AND run_key='newer-success'"
            ),
            {"nid": UUID(nid)},
        )
        await db.commit()
        assert await claim_freshness(db, nid, claims[-1]) == "source_changed"
        await db.execute(
            text(
                "DELETE FROM evolution_receipts WHERE novel_id=:nid "
                "AND run_key='newer-success'"
            ),
            {"nid": UUID(nid)},
        )
        await db.commit()
        assert await claim_freshness(db, nid, claims[-1]) == "current"
        run = await db.scalar(
            select(EvolutionRun).where(
                EvolutionRun.novel_id == UUID(nid),
                EvolutionRun.run_key == "issue209-history",
            )
        )
        old_plan = deepcopy(run.reading_plan_json)
        run.reading_plan_json = {
            "inherited_receipts": [{"run_key": "missing-parent", "attempt_id": "d" * 64}]
        }
        await db.commit()
        assert await claim_freshness(db, nid, claims[-1]) == "source_changed"
        run.reading_plan_json = old_plan
        await db.commit()
        assert await claim_freshness(db, nid, claims[-1]) == "current"


async def test_revalidation_refreshes_retained_prefix_rows(history_project):
    from sqlalchemy import text

    from modules.evolution.models import EvolutionReceiptRecord

    _, sessions, nid, claims = history_project
    async with sessions() as db:
        first = claims[0].dependencies[0]
        retained_frozen = await db.scalar(
            select(EvolutionFrozenAttempt).where(
                EvolutionFrozenAttempt.novel_id == UUID(nid),
                EvolutionFrozenAttempt.attempt_key == first.attempt_id,
            )
        )
        retained_receipt = await db.scalar(
            select(EvolutionReceiptRecord).where(
                EvolutionReceiptRecord.novel_id == UUID(nid),
                EvolutionReceiptRecord.attempt_key == first.attempt_id,
            )
        )
        assert await claim_freshness(db, nid, claims[-1]) == "current"
        await db.execute(
            text(
                "UPDATE evolution_receipts SET committed_scene_index = 999 "
                "WHERE novel_id=:nid AND attempt_key=:attempt"
            ),
            {"nid": UUID(nid), "attempt": first.attempt_id},
        )
        assert retained_receipt.committed_scene_index == 0  # Raw SQL bypasses ORM.
        assert await claim_freshness(db, nid, claims[-1]) == "source_changed"
        await db.rollback()
        assert await claim_freshness(db, nid, claims[-1]) == "current"
        await db.execute(
            text(
                "UPDATE evolution_frozen_attempts SET previous_receipt = :parent "
                "WHERE novel_id=:nid AND attempt_key=:attempt"
            ),
            {"parent": "f" * 64, "nid": UUID(nid), "attempt": first.attempt_id},
        )
        assert retained_frozen.previous_receipt is None
        assert await claim_freshness(db, nid, claims[-1]) == "source_changed"
        await db.rollback()
        assert await claim_freshness(db, nid, claims[-1]) == "current"
        retained_draft = await db.get(
            WritingDraft, UUID(claims[0].evidence[0].source_ref.draft_id)
        )
        old_text = retained_draft.content
        await db.execute(
            text("UPDATE writing_drafts SET content=:content WHERE id=:id"),
            {"id": retained_draft.id, "content": "否" + old_text[1:]},
        )
        assert retained_draft.content == old_text
        assert await claim_freshness(db, nid, claims[-1]) == "source_changed"
        await db.rollback()
        assert await claim_freshness(db, nid, claims[-1]) == "current"
