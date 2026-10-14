"""Synthetic map/prose provenance tests; no models or production database."""

import uuid
from dataclasses import asdict

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from core.container import container_scope
from core.errors import NotFoundError
from core.service_keys import WORLD_READ_MAP_CHAPTER_CONSUMERS
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.evolution.consumption import RECOMPUTE_SCOPE_COVERS, receipt_fingerprint
from modules.evolution.impact import receipt_view
from modules.evolution.invalidation import record_writing_source_change
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.map_source_consumption import read_map_chapter_consumers
from modules.writing.facade import (
    build_manuscript_range_ref,
    create_draft_only,
    create_published_draft_only,
    deprecate_chapter_versions,
)
from modules.writing.models import WritingInvalidationNotice


async def saved_map(db, nid, draft, *, title="东岸地图", ref_overrides=None):
    ref = asdict(
        await build_manuscript_range_ref(
            db,
            nid,
            draft_id=draft.id,
            start_offset=0,
            end_offset=len(draft.content),
            content_mode="canonical",
        )
    )
    ref.update(ref_overrides or {})
    node = MapAtlasNode(
        novel_id=uuid.UUID(nid),
        semantic_key=str(uuid.uuid4()),
        title=title,
        level="region",
        status="adopted",
    )
    db.add(node)
    await db.flush()
    revision = MapAtlasRevision(
        novel_id=uuid.UUID(nid),
        node_id=node.id,
        status="saved",
        geometry_hash="a" * 64,
        document={
            "features": [
                {
                    "id": "bank",
                    "kind": "location",
                    "label": "东岸",
                    "sources": [
                        {
                            "kind": "source_range",
                            "id": draft.id,
                            "source_hash": draft.content_hash,
                            "source_ref": ref,
                        }
                    ],
                }
            ]
        },
    )
    db.add(revision)
    await db.flush()
    node.current_revision_id = revision.id
    await db.flush()
    return node, revision


async def changed_receipt(db, nid, *, published_changed=True):
    return await record_writing_source_change(
        db,
        nid,
        chapter_index=1,
        old_content="东岸是港口",
        new_content="东岸是山地",
        published_changed=published_changed,
    )


@pytest.mark.asyncio
async def test_saved_current_head_matches_real_old_source_and_persists_notice(
    db_session,
    test_project_id,
    project_factory,
):
    db, nid = db_session, test_project_id
    old = await create_published_draft_only(db, nid, 1, "旧章", "东岸是港口")
    node, revision = await saved_map(db, nid, old)
    other_chapter = await create_published_draft_only(db, nid, 2, "另一章", "北岸是森林")
    await saved_map(db, nid, other_chapter, title="另一章地图")
    other_nid = str(await project_factory.create_project())
    other_draft = await create_published_draft_only(
        db, other_nid, 1, "外部章", "另一作品"
    )
    await saved_map(db, other_nid, other_draft, title="其他作品地图")
    current = await create_published_draft_only(db, nid, 1, "新章", "东岸是山地")
    await saved_map(db, nid, current, title="当前版地图")
    receipt = await changed_receipt(db, nid)
    maps = receipt.invalidated_consumers["map_atlas"]
    assert maps["maps"] == [
        {
            "node_id": str(node.id),
            "revision_id": str(revision.id),
            "title": "东岸地图",
            "chapter_index": 1,
        }
    ]
    assert maps["truncated"] is False
    assert maps["unverified_sources"] == 0
    assert node.status == "adopted" and revision.status == "saved"
    assert receipt.earliest_affected_scene_index is None
    assert receipt.impact_assessment.unknown_scope.chapter_registration_missing is True
    assert all("map_atlas" not in covers for covers in RECOMPUTE_SCOPE_COVERS.values())
    view = receipt_view(receipt)
    assert view["receipt_id"] == receipt.receipt_id == receipt_fingerprint(receipt)
    assert any(item.get("map_title") == "东岸地图" for item in view["affected"])
    assert all(item.get("scene_index") is None for item in view["affected"])
    replay = await changed_receipt(db, nid)
    assert replay.receipt_id == receipt.receipt_id
    notices = (
        (
            await db.execute(
                select(WritingInvalidationNotice).where(
                    WritingInvalidationNotice.novel_id == uuid.UUID(nid),
                )
            )
        )
        .scalars()
        .all()
    )
    assert any(
        any(
            item.get("map_title") == "东岸地图" for item in notice.notice_json["affected"]
        )
        for notice in notices
    )


@pytest.mark.asyncio
async def test_working_draft_does_not_scan_maps(db_session, test_project_id):
    async def forbidden(*args, **kwargs):
        raise AssertionError("working edits must not invoke the map port")

    with container_scope({WORLD_READ_MAP_CHAPTER_CONSUMERS: forbidden}):
        await create_draft_only(db_session, test_project_id, 1, "工作稿", "东岸")
        receipt = await changed_receipt(
            db_session, test_project_id, published_changed=False
        )
    assert "map_atlas" not in receipt.invalidated_consumers


@pytest.mark.asyncio
async def test_retracted_canonical_still_reports_real_historical_sources(
    db_session,
    test_project_id,
):
    old = await create_published_draft_only(db_session, test_project_id, 1, "旧", "东岸")
    node, _ = await saved_map(db_session, test_project_id, old)
    await deprecate_chapter_versions(db_session, test_project_id, 1)
    receipt = await changed_receipt(db_session, test_project_id)
    assert (
        receipt.invalidated_consumers["canonical_chapter_index"]["requested_source_id"]
        is None
    )
    assert receipt.invalidated_consumers["map_atlas"]["maps"][0]["node_id"] == str(
        node.id
    )


@pytest.mark.asyncio
async def test_forged_chapter_or_hash_is_visible_unverified(db_session, test_project_id):
    old = await create_published_draft_only(db_session, test_project_id, 2, "旧", "东岸")
    await saved_map(db_session, test_project_id, old, ref_overrides={"chapter_index": 1})
    receipt = await changed_receipt(db_session, test_project_id)
    assert receipt.invalidated_consumers["map_atlas"]["maps"] == []
    assert receipt.invalidated_consumers["map_atlas"]["unverified_sources"] == 1
    assert "地图册未核对完整" in receipt_view(receipt)["coverage_note"]


@pytest.mark.asyncio
async def test_map_query_failure_uses_savepoint_and_keeps_main_receipt(
    db_session,
    test_project_id,
):
    async def fail(*args, **kwargs):
        raise SQLAlchemyError("synthetic query failure")

    with container_scope({WORLD_READ_MAP_CHAPTER_CONSUMERS: fail}):
        receipt = await changed_receipt(db_session, test_project_id)
    assert receipt.invalidated_consumers["map_atlas"]["checked"] is False
    assert "地图册未核对" in receipt.coverage_note
    assert "evidence_chapter_index" in receipt.invalidated_consumers
    assert await db_session.scalar(select(1)) == 1


@pytest.mark.asyncio
async def test_map_port_empty_limit_and_owner(db_session, test_project_id, monkeypatch):
    import modules.world.map_source_consumption as sources

    assert (
        await read_map_chapter_consumers(
            db_session,
            test_project_id,
            chapter_index=1,
            current_draft_id=None,
            current_source_hash=None,
        )
    )["maps"] == []
    old = await create_published_draft_only(db_session, test_project_id, 1, "旧", "东岸")
    await saved_map(db_session, test_project_id, old)
    await saved_map(db_session, test_project_id, old, title="第二地图")
    monkeypatch.setattr(sources, "MAP_CONSUMPTION_LIMIT", 1)
    result = await read_map_chapter_consumers(
        db_session,
        test_project_id,
        chapter_index=1,
        current_draft_id=None,
        current_source_hash=None,
    )
    assert result["truncated"] is True and len(result["maps"]) == 1
    monkeypatch.setattr(sources, "MAP_CONSUMPTION_LIMIT", 200)
    monkeypatch.setattr(sources, "MAP_SOURCE_LIMIT", 1)
    source_limited = await read_map_chapter_consumers(
        db_session,
        test_project_id,
        chapter_index=1,
        current_draft_id=None,
        current_source_hash=None,
    )
    assert source_limited["truncated"] is True
    assert len(source_limited["maps"]) == 1
    token = bind_principal(
        AccountPrincipal(
            account_id=uuid.uuid4(),
            status="active",
            identity_type="email",
            support_code="OTHER-OWNER",
        )
    )
    try:
        with pytest.raises(NotFoundError):
            await read_map_chapter_consumers(
                db_session,
                test_project_id,
                chapter_index=1,
                current_draft_id=None,
                current_source_hash=None,
            )
    finally:
        reset_principal(token)


@pytest.mark.asyncio
async def test_only_saved_current_revision_counts_and_wrong_hash_is_visible(
    db_session,
    test_project_id,
):
    old = await create_published_draft_only(db_session, test_project_id, 1, "旧", "东岸")
    node, previous = await saved_map(db_session, test_project_id, old)
    head = MapAtlasRevision(
        novel_id=uuid.UUID(test_project_id),
        node_id=node.id,
        status="saved",
        geometry_hash="a" * 64,
        document={},
    )
    db_session.add(head)
    await db_session.flush()
    node.current_revision_id = head.id
    candidate_node, candidate = await saved_map(db_session, test_project_id, old)
    candidate.status = "candidate"
    forged_node, forged = await saved_map(db_session, test_project_id, old)
    document = dict(forged.document)
    source = dict(document["features"][0]["sources"][0])
    source["source_hash"] = "0" * 64
    source["source_ref"] = {**source["source_ref"], "source_hash": "0" * 64}
    forged.document = {
        **document,
        "features": [{**document["features"][0], "sources": [source]}],
    }
    await db_session.flush()
    receipt = await changed_receipt(db_session, test_project_id)
    maps = receipt.invalidated_consumers["map_atlas"]
    assert maps["maps"] == []
    assert maps["unverified_sources"] == 1
    assert previous.status == "saved" and candidate_node.status == "adopted"
    assert forged_node.status == "adopted"
