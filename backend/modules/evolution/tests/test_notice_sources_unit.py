"""Offline tests for current-head map source notices."""

from types import SimpleNamespace

import pytest

from modules.evolution import notice_sources as source

NOVEL_ID = "11111111-1111-4111-8111-111111111111"


class ScalarResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, receipts=()):
        self.receipts = list(receipts)

    async def scalars(self, _statement):
        return ScalarResult(self.receipts)


def receipt(*, receipt_id="receipt-1", revision_id="map-revision-1"):
    return SimpleNamespace(
        id=receipt_id,
        receipt_json={
            "invalidated_consumers": {
                "map_atlas": {
                    "maps": [
                        {
                            "node_id": "map-node-1",
                            "revision_id": revision_id,
                            "chapter_index": 3,
                        }
                    ]
                }
            }
        },
    )


def current_map(*, revision_id="map-revision-1"):
    return {
        "node_id": "map-node-1",
        "revision_id": revision_id,
        "title": "北岸地图",
        "chapter_index": 3,
    }


def configure(monkeypatch, report, receipts=()):
    session = FakeSession(receipts)

    async def source_manifest(db, novel_id, **kwargs):
        assert db is session
        assert str(novel_id) == NOVEL_ID
        assert kwargs == {"content_mode": "canonical", "chapter_from": 3, "chapter_to": 3}
        return [
            {"draft_id": "draft-current", "chapter_index": 3, "source_hash": "b" * 64}
        ]

    async def read_current(_db, novel_id, **kwargs):
        assert str(novel_id) == NOVEL_ID
        assert kwargs == {
            "chapter_index": 3,
            "current_draft_id": "draft-current",
            "current_source_hash": "b" * 64,
            "content_mode": "canonical",
        }
        return report

    monkeypatch.setattr(source, "get_manuscript_source_manifest", source_manifest)
    monkeypatch.setattr(source, "get", lambda _key: read_current)
    return session


@pytest.mark.asyncio
async def test_historical_receipt_does_not_keep_resolved_map_notice_alive(monkeypatch):
    session = configure(
        monkeypatch,
        {
            "maps": [],
            "auto_drafts": [],
            "checked": True,
            "truncated": False,
            "unverified_sources": 0,
        },
        [receipt()],
    )

    result = await source.list_map_source_notices(session, NOVEL_ID, {"chapter_index": 3})

    assert result == []


@pytest.mark.asyncio
async def test_notice_uses_current_map_head_and_only_matching_receipt_as_evidence(
    monkeypatch,
):
    session = configure(
        monkeypatch,
        {
            "maps": [current_map()],
            "auto_drafts": [],
            "checked": True,
            "truncated": False,
            "unverified_sources": 0,
        },
        [receipt(receipt_id="receipt-current")],
    )

    result = await source.list_map_source_notices(session, NOVEL_ID, {"chapter_index": 3})

    assert len(result) == 1
    assert result[0]["source_id"] == "world.map_source"
    assert result[0]["target"] == {"chapter_index": 3, "node_id": "map-node-1"}
    assert result[0]["evidence"][0]["receipt_id"] == "receipt-current"

    session = configure(
        monkeypatch,
        {
            "maps": [current_map(revision_id="map-revision-new")],
            "auto_drafts": [],
            "checked": True,
            "truncated": False,
            "unverified_sources": 0,
        },
        [receipt(receipt_id="receipt-old")],
    )
    changed_head = await source.list_map_source_notices(
        session, NOVEL_ID, {"chapter_index": 3}
    )
    assert len(changed_head) == 1
    assert "receipt_id" not in changed_head[0]["evidence"][0]
    assert "旧版正文" in changed_head[0]["summary"]


@pytest.mark.asyncio
async def test_partial_current_map_scan_keeps_known_items_and_discloses_truncation(
    monkeypatch,
):
    session = configure(
        monkeypatch,
        {
            "maps": [current_map()],
            "auto_drafts": [],
            "checked": True,
            "truncated": True,
            "unverified_sources": 2,
            "coverage": "当前已保存地图和待审空间草图的canonical正文来源",
        },
    )

    result = await source.list_map_source_notices(session, NOVEL_ID, {"chapter_index": 3})

    assert len(result) == 2
    assert result[0]["target"]["node_id"] == "map-node-1"
    coverage = result[1]
    assert coverage["category"] == "map_source_coverage"
    assert "2 条来源无法验证" in coverage["summary"]
    assert "结果已截断" in coverage["summary"]


def test_receipt_matches_only_same_chapter_map_node_and_revision():
    indexes = source._receipt_indexes_current_head(
        [
            receipt(receipt_id="same-head"),
            receipt(receipt_id="old-head", revision_id="map-revision-old"),
        ],
        3,
    )

    assert indexes == {
        ("map-node-1", "map-revision-1"): "same-head",
        ("map-node-1", "map-revision-old"): "old-head",
    }


def test_candidate_auto_draft_notice_uses_the_world_report_kind():
    item = source._map_notice(
        {**current_map(), "kind": "auto_draft"},
        novel_id=NOVEL_ID,
        chapter_index=3,
        current_draft_id="draft-current",
        current_source_hash="b" * 64,
        matching_receipt_id=None,
    )

    assert "空间草图" in item["summary"]
    saved = source._map_notice(
        current_map(),
        novel_id=NOVEL_ID,
        chapter_index=3,
        current_draft_id="draft-current",
        current_source_hash="b" * 64,
        matching_receipt_id=None,
    )
    assert item["basis_fingerprint"] != saved["basis_fingerprint"]
