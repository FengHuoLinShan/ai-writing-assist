"""Real page reads, source baselines and response-only comparisons."""

import uuid

import pytest
from sqlalchemy import select

from modules.story.outline_state.models import StoryOutlineRevision
from modules.story.outline_state.story_outline_schemas import StoryOutlineRevisionCreate
from modules.story.outline_state.story_outline_service import StoryOutlineService
from modules.story.outline_state.tests.test_story_outline import _payload
from modules.world.facade import read_world_bible_page_revisions
from modules.world.models import WorldBiblePage, WorldBiblePageRevision
from modules.world.world_background import WorldBackgroundAggregation


async def page_revision(db, novel_id, page=None):
    if page is None:
        page = WorldBiblePage(
            novel_id=uuid.UUID(novel_id),
            page_type="setting",
            page_key=str(uuid.uuid4()),
            title="潮汐规则",
            free_text="每夜退潮一次",
            status="canonical",
            version_number=1,
        )
        db.add(page)
        await db.flush()
    else:
        page.version_number += 1
    revision = WorldBiblePageRevision(
        novel_id=page.novel_id,
        page_id=page.id,
        version_number=page.version_number,
        snapshot_json={"free_text": page.free_text},
        revision_digest=str(page.version_number) * 64,
        revision_reason="manual_publish",
    )
    db.add(revision)
    await db.flush()
    return page, revision


@pytest.mark.asyncio
async def test_actual_page_read_captures_current_revision_and_filters_projects(
    db_session, sample_novel_id
):
    page, revision = await page_revision(db_session, sample_novel_id)
    background = await WorldBackgroundAggregation().build(db_session, sample_novel_id)
    entry = next(x for x in background.entries if x.asset_type == "world_bible_page")
    assert (entry.asset_id, entry.revision_id, entry.revision_digest) == (
        str(page.id),
        str(revision.id),
        revision.revision_digest,
    )
    heads = await read_world_bible_page_revisions(
        db_session, sample_novel_id, [str(page.id)]
    )
    assert heads[str(page.id)]["revision_id"] == str(revision.id)
    assert (
        await read_world_bible_page_revisions(
            db_session, str(uuid.uuid4()), [str(page.id)]
        )
        == {}
    )
    page.status = "draft"
    await db_session.flush()
    assert (
        await read_world_bible_page_revisions(db_session, sample_novel_id, [str(page.id)])
        == {}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revision", "unadopt", "missing"])
async def test_outline_read_only_notice_preserves_content_provenance_and_hash(
    db_session, sample_novel_id, change
):
    page, revision = await page_revision(db_session, sample_novel_id)
    baseline = {
        "page_id": str(page.id),
        "revision_id": str(revision.id),
        "revision_digest": revision.revision_digest,
    }
    data = _payload()
    # This is the same server provenance that generated-preview adoption preserves.
    provenance = StoryOutlineService._task_provenance(
        task_id=str(uuid.uuid4()),
        context_hash="a" * 64,
        context_provenance={"world_bible_page_revisions": [baseline]},
    )
    data["provenance"] = provenance.model_dump(mode="json")
    service = StoryOutlineService()
    created = await service.create_revision(
        db_session, sample_novel_id, StoryOutlineRevisionCreate.model_validate(data)
    )
    before = (await service.get_current(db_session, sample_novel_id)).revision.model_dump(
        mode="json"
    )
    steady = (
        await service.get_current(
            db_session, sample_novel_id, include_canon_staleness=True
        )
    ).revision
    assert steady.canon_staleness.changed is False
    if change == "revision":
        await page_revision(db_session, sample_novel_id, page)
    elif change == "unadopt":
        page.status = "draft"
        await db_session.flush()
    else:
        # Simulate a missing page without deleting append-only adopted history.
        from core.container import container_scope
        from core.service_keys import WORLD_READ_BIBLE_PAGE_REVISIONS

        async def absent(*args):
            return {}

        with container_scope({WORLD_READ_BIBLE_PAGE_REVISIONS: absent}):
            fetched = await service.get_revision(
                db_session, sample_novel_id, created.id, include_canon_staleness=True
            )
    if change != "missing":
        fetched = await service.get_revision(
            db_session, sample_novel_id, created.id, include_canon_staleness=True
        )
    assert fetched.canon_staleness.changed_page_ids == [page.id]
    assert fetched.canon_staleness.changed is True
    internal = (await service.get_current(db_session, sample_novel_id)).revision
    assert internal.canon_staleness is None
    assert internal.model_dump(mode="json") == before
    assert fetched.content_hash == before["content_hash"]
    assert fetched.outline_markdown == before["outline_markdown"]
    stored = await db_session.scalar(
        select(StoryOutlineRevision).where(StoryOutlineRevision.id == created.id)
    )
    assert stored.provenance_json == before["provenance"]
    assert "canon_staleness" not in stored.provenance_json
    listed = await service.list_revisions(
        db_session, sample_novel_id, skip=0, limit=10, include_canon_staleness=True
    )
    assert listed.items[0].content_hash == before["content_hash"]


@pytest.mark.asyncio
async def test_legacy_outline_has_no_warning_or_invented_baseline(
    db_session, sample_novel_id
):
    service = StoryOutlineService()
    await service.create_revision(
        db_session, sample_novel_id, StoryOutlineRevisionCreate.model_validate(_payload())
    )
    assert (
        await service.get_current(
            db_session, sample_novel_id, include_canon_staleness=True
        )
    ).revision.canon_staleness is None
