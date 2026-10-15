"""Evidence read projection enforces Scene cutoff and author review state."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.container import container_scope
from core.service_keys import STORY_SCENE_SOURCE
from modules.evolution.contracts import SourceRevisionRef
from modules.evolution.evidence_read import read_evolution_object_patterns
from modules.evolution.ledger_contracts import LedgerClaim

NOVEL_ID = str(uuid4())
SCENE_ID = str(uuid4())
FUTURE_SCENE_ID = str(uuid4())
ENTITY_ID = str(uuid4())


def _claim(*, scene_id: str = SCENE_ID, scene_index: int = 2) -> LedgerClaim:
    source_ref = SourceRevisionRef(
        novel_id=NOVEL_ID,
        source_kind="chapter_draft",
        draft_id=str(uuid4()),
        content_hash="a" * 64,
        chapter_identity=str(uuid4()),
        start_offset=0,
        end_offset=5,
        range_hash=SourceRevisionRef.compute_range_hash("a" * 64, 0, 5),
        source_revision=1,
        segmentation_version=1,
        source_visibility="canonical",
    )
    return LedgerClaim(
        category="conditional_behavior",
        label="钟声后检查北门",
        statement="守卫听见钟声后会检查北门。",
        conditions=["听见钟声"],
        realm="history",
        modality="hypothesis",
        confidence=0.8,
        competing_explanations=["当日加强巡查"],
        targets=[
            {
                "domain": "world",
                "kind": "entity",
                "target_id": ENTITY_ID,
                "version_fingerprint": "entity-version-1",
                "binding": "resolved",
                "label": "北门守卫",
            }
        ],
        evidence=[
            {
                "observation_id": "observation-1",
                "position": {
                    "scene_id": scene_id,
                    "scene_index": scene_index,
                    "chapter_index": 1,
                },
                "modality": "character_statement",
                "quote": "我听见钟声就去检查北门。",
                "source_ref": source_ref,
                "role": "support",
            }
        ],
        dependencies=[
            {
                "run_key": "run-1",
                "attempt_id": "attempt-1",
                "scene_id": SCENE_ID,
                "scene_index": 2,
                "source_manifest_hash": "b" * 64,
            }
        ],
        method_fingerprint="c" * 64,
    )


class _ScenePort:
    async def get_scene_contract(self, _db, _novel_id, scene_id):
        return {
            "scene_index": 3 if scene_id == FUTURE_SCENE_ID else 2,
        }

    async def get_scene_state_view(self, _db, novel_id, scene_id, *, viewpoint):
        assert viewpoint == {"kind": "author"}
        return {
            "novel_id": novel_id,
            "scene_id": scene_id,
            "scene_index": 2,
            "state_fingerprint": "checkpoint-fingerprint",
            "dimensions": [
                {
                    "dimension": "entities",
                    "facts": [
                        {
                            "source": {"checkpoint_id": "checkpoint-1"},
                        }
                    ],
                }
            ],
        }


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Database:
    def __init__(self, rows):
        self.rows = rows
        self.executed = False

    async def execute(self, _statement):
        self.executed = True
        return _Rows(self.rows)


def _row(claim: LedgerClaim, *, review=None, decision=None, scene_index=2):
    revision = SimpleNamespace(
        id=uuid4(),
        entry_id=uuid4(),
        revision=3,
        scene_index=scene_index,
        body_json={
            "claim": claim.model_dump(mode="json"),
            "review": review if review is not None else {"verdict": "supported"},
            "author_decision": decision or {},
            "proposal_target": None,
        },
    )
    entry = SimpleNamespace(
        id=revision.entry_id,
        category=claim.category,
    )
    return revision, entry


@pytest.fixture
def read_validators(monkeypatch):
    async def active_project(_db, _novel_id, *, allow_demo_readonly):
        assert allow_demo_readonly is False

    async def current_identity(_db, _novel_id, _claim):
        return "current"

    async def current_sources(_db, _novel_id, _claim, **_kwargs):
        return "current"

    monkeypatch.setattr(
        "modules.evolution.evidence_read.require_active_project", active_project
    )
    monkeypatch.setattr(
        "modules.evolution.evidence_read._identity_status", current_identity
    )
    monkeypatch.setattr(
        "modules.evolution.evidence_read.claim_freshness", current_sources
    )
    monkeypatch.setattr(
        "modules.evolution.evidence_read._claim_ranges_current", current_sources
    )


async def _read(db, **kwargs):
    with container_scope({STORY_SCENE_SOURCE: _ScenePort()}):
        return await read_evolution_object_patterns(
            db,
            novel_id=NOVEL_ID,
            scene_id=SCENE_ID,
            entity_ids=[ENTITY_ID],
            **kwargs,
        )


async def test_supported_or_kept_pattern_returns_only_provenance_coordinates(
    monkeypatch, read_validators
):
    claim = _claim()
    db = _Database([_row(claim, decision={"decision": "keep"})])

    result = await _read(db, only_adopted=False)

    assert db.executed is True
    assert result["coverage"] == "complete"
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["modality"] == "hypothesis"
    assert item["author_decision"] == "keep"
    assert item["evidence_refs"][0]["modality"] == "character_statement"
    assert item["evidence_refs"][0]["source"]["range_hash"]
    assert "quote" not in str(item)
    assert result["checkpoint_identities"] == ["checkpoint-1"]


@pytest.mark.parametrize(
    ("review", "decision", "only_adopted", "expected"),
    [
        ({"verdict": "supported"}, {}, False, 1),
        ({"verdict": "unsupported"}, {"decision": "keep"}, False, 1),
        ({"verdict": "unsupported"}, {}, False, 0),
        ({"verdict": "supported"}, {"decision": "reject"}, False, 0),
        ({"verdict": "supported"}, {}, True, 0),
    ],
)
async def test_pattern_requires_support_or_author_adoption(
    monkeypatch, read_validators, review, decision, only_adopted, expected
):
    db = _Database([_row(_claim(), review=review, decision=decision)])
    result = await _read(db, only_adopted=only_adopted)
    assert len(result["items"]) == expected


async def test_pattern_with_changed_or_future_scene_anchor_is_omitted(
    monkeypatch, read_validators
):
    changed_claim = _claim(scene_id=FUTURE_SCENE_ID, scene_index=3)
    db = _Database([_row(changed_claim)])

    result = await _read(db, only_adopted=False)

    assert result["items"] == []
    assert result["omitted_count"] == 1
    assert any("超出截止 Scene" in item for item in result["omissions"])


async def test_story_cutoff_mismatch_stops_before_ledger_query(
    monkeypatch, read_validators
):
    class WrongScenePort(_ScenePort):
        async def get_scene_state_view(self, _db, novel_id, _scene_id, *, viewpoint):
            return {
                "novel_id": novel_id,
                "scene_id": str(uuid4()),
                "scene_index": 1,
            }

    db = _Database([])
    with container_scope({STORY_SCENE_SOURCE: WrongScenePort()}):
        result = await read_evolution_object_patterns(
            db,
            novel_id=NOVEL_ID,
            scene_id=SCENE_ID,
            entity_ids=[ENTITY_ID],
        )

    assert db.executed is False
    assert result["coverage"] == "unknown"
    assert result["items"] == []
