"""Regression targets from the map-series review (T-20261016-map-series-claude-review).

Each case encodes the specified behavior for a confirmed review finding. Cases are
strict xfail while the defect is open: a fix turns them into an unexpected pass,
which fails the run until the marker is removed and the case becomes a plain
regression test.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from core.errors import ConflictError
from modules.evolution.commit import CommitConflictError
from modules.evolution.optional_scene import load_pending_optional_stage
from modules.evolution.sampler import register_scene_sampler
from modules.evolution.spatial import (
    SPATIAL_VERSION,
    SpatialClueProposal,
    SpatialTypeProposal,
    _density_hits,
    _type_review_context,
    spatial_method_fingerprint,
)
from modules.evolution.tasks import handle_evolution_scene_step
from modules.evolution.tests.test_optional_scene import (
    Sample,
    optional_call,
    plan_run,
    seed,
)
from modules.evolution.tests.test_source_integrity import request
from modules.evolution.tests.test_spatial import _frozen, _source
from modules.world.contracts import MapSpatialClueContext, VocabularyEvidence


@pytest.mark.xfail(
    strict=True,
    reason="B2-F1: a Scene card edit after the main receipt leaves the optional "
    "stage running forever; resume, append and completion stay blocked",
)
async def test_b2_scene_card_edit_settles_optional_stage_as_gap(
    db_session, evolution_project_id, monkeypatch
):
    from modules.story.outline_state.models import Scene

    db, nid = db_session, evolution_project_id
    scene_id = await seed(db, nid, {1: "城门开启。"})
    store = await plan_run(db, nid)
    register_scene_sampler("source-integrity", lambda db, novel_id: Sample())

    async def provider(**kwargs):
        # The author edits the Scene card while optional work is in flight.
        scene = await db.get(Scene, UUID(scene_id))
        scene.title = "作者修订后的卡片"
        await db.commit()
        return {"result": {}}

    monkeypatch.setattr(
        "modules.evolution.spatial.finish_scene_spatial",
        optional_call("scene_spatial_discovery", provider),
    )
    task = request(
        nid,
        scene_id,
        "城门开启。",
        state_review_version=0,
        spatial_version=1,
        source_content_mode="working",
        budget_total=20,
    )
    try:
        await handle_evolution_scene_step(db, task)
    except CommitConflictError:
        await db.rollback()

    # The committed main receipt must not stay hostage to optional work: the
    # step settles as a stale gap that a later spatial rescan can fill.
    run = await store.load_run("source-integrity")
    assert await load_pending_optional_stage(store, run) is None
    await handle_evolution_scene_step(db, task)


@pytest.mark.xfail(
    strict=True,
    reason="B2-F2: single-character density terms match ordinary words such as "
    "东西, so the zero-hit skip almost never fires",
)
def test_b2_density_precheck_ignores_non_spatial_common_words():
    density = _density_hits(
        "他把东西放下，说了声谢谢，又低头喝茶。", [], MapSpatialClueContext()
    )

    assert density["count"] == 0, density


@pytest.mark.xfail(
    strict=True,
    reason="B2-F3: the reviewer must cite the current quote's evidence index, but "
    "its review context lists only prior evidence",
)
def test_b2_emerging_type_review_context_indexes_current_evidence():
    prior = VocabularyEvidence(
        scene_id=uuid4(), quote="旧城被高墙围住", source_hash="e" * 64
    )
    context = MapSpatialClueContext.model_validate(
        {
            "types": [
                {
                    "id": str(uuid4()),
                    "revision_id": str(uuid4()),
                    "kind": "space",
                    "status": "emerging",
                    "source": "model",
                    "name": "封闭街区",
                    "description": "边界封闭的街区",
                    "evidence": [prior.model_dump(mode="json")],
                    "proposal_run_id": str(uuid4()),
                }
            ]
        }
    )
    raw = SpatialClueProposal(
        kind="bearing",
        subject_surface="旧城",
        target_surface="门",
        relation="东侧",
        modality="event_observed",
        quote="门在东侧",
        type=SpatialTypeProposal(kind="space", name="封闭街区"),
    )

    review_context = _type_review_context(raw, context, str(uuid4()))

    # _make_clues requires reviewed_evidence_indices == range(len(prior) + 1).
    quotes = [item["quote"] for item in review_context["evidence"]]
    assert quotes == ["旧城被高墙围住", "门在东侧"]


@pytest.mark.xfail(
    strict=True,
    reason="B2-F6: rescan planning reads only the original receipt, so a Scene "
    "already rescanned with the current method is planned and billed again",
)
async def test_b2_completed_spatial_rescan_is_not_planned_again(monkeypatch):
    import modules.evolution.spatial_rescan as rescan

    # The original receipt predates spatial discovery, so it has no spatial result.
    origin = _frozen(scene_index=0)
    origin = origin.model_copy(
        update={
            "payload": {
                key: value
                for key, value in origin.payload.items()
                if key != "spatial_version"
            }
            | {"source_binding": _source().model_dump(mode="json")}
        }
    )
    operation_id = str(uuid4())
    rescanned = origin.model_copy(
        update={
            "attempt_id": str(uuid4()),
            "payload": {
                **origin.payload,
                "spatial_version": SPATIAL_VERSION,
                "spatial_rescan_operation_id": operation_id,
                "spatial_rescan_status": "completed",
                "scene_spatial_discovery": {"stage": "sampled"},
                "scene_spatial_review": {"stage": "sampled"},
                "spatial_discovery_result": {
                    "status": "inspected",
                    "method_fingerprint": spatial_method_fingerprint(),
                    "gaps": [],
                },
                "optional_step_coverage": {"spatial": {"status": "inspected"}},
            },
        }
    )
    run = SimpleNamespace(
        run_key=origin.run_id,
        status="active",
        execution_mode="live",
        llm_snapshot_json={"profile": {"model": "luna"}},
        committed_scene_index=0,
        owner_epoch=1,
        budget_remaining=None,
        reading_plan_json={
            "steps": [
                {
                    "scene_index": 0,
                    "scene_id": origin.payload["scene_id"],
                    "source_content_mode": "working",
                }
            ],
            "spatial_rescans": [
                {
                    "operation_id": operation_id,
                    "attempt_ids": [rescanned.attempt_id],
                    "from_scene_index": 0,
                    "through_scene_index": 0,
                    "status": "completed",
                }
            ],
        },
    )
    receipt = SimpleNamespace(
        committed_scene_index=0, run_key=origin.run_id, attempt_key=origin.attempt_id
    )

    class Store:
        async def load_run(self, run_key, for_update=False):
            return run

        async def require_project_owner(self, run_key):
            return None

        async def load_committed_pairs(self, run_key):
            return [(receipt, None)]

        async def load_head_receipt(self, run_key):
            return SimpleNamespace(attempt_id=origin.attempt_id, committed_prefix="p")

        async def load_frozen(self, run_key, attempt_id):
            return {origin.attempt_id: origin, rescanned.attempt_id: rescanned}[
                attempt_id
            ]

    async def nothing(*_args, **_kwargs):
        return None

    async def working(*_args, **_kwargs):
        return "working"

    monkeypatch.setattr(rescan, "PostgresAttemptStore", lambda *_: Store())
    monkeypatch.setattr(rescan, "_idle", nothing)
    monkeypatch.setattr(rescan, "require_current_prefix", nothing)
    monkeypatch.setattr(rescan, "_resolve_source_content_mode", working)

    # The progress summary already reports this Scene as inspected (workflow
    # _optional_coverage_summary reads rescan attempts); planning must agree.
    with pytest.raises(ConflictError, match="完整检查"):
        await rescan._plan(
            object(),
            origin.novel_id,
            origin.run_id,
            rescan.SpatialRescanRequest(
                operation_id=uuid4(), from_scene_index=0, through_scene_index=0
            ),
        )


@pytest.mark.xfail(
    strict=True,
    reason="B4-F2: reading notices walk past a newer completed run to a drained run "
    "it superseded and report the dead run as paused",
)
async def test_b4_superseded_drained_run_does_not_raise_a_reading_notice(
    db_session, evolution_project_id
):
    from datetime import UTC, datetime, timedelta

    from modules.evolution.models import EvolutionRun
    from modules.evolution.reading_notice_sources import list_reading_notices

    steps = [
        {"scene_index": index, "source_binding": {"chapter_index": 1}} for index in (0, 1)
    ]
    started = datetime.now(UTC)
    # The first reading stopped after one Scene; scoped recompute drained it
    # (workflow.start_reading) and the replacement run finished both Scenes.
    db_session.add_all(
        [
            EvolutionRun(
                novel_id=UUID(evolution_project_id),
                run_key="reading-original",
                mode="bootstrap",
                status="drained",
                execution_mode="live",
                committed_scene_index=0,
                reading_plan_json={
                    "steps": steps,
                    "preparation": {"stage": "complete"},
                },
                created_at=started,
            ),
            EvolutionRun(
                novel_id=UUID(evolution_project_id),
                run_key="reading-recompute",
                mode="scoped_recompute",
                status="active",
                execution_mode="live",
                committed_scene_index=1,
                reading_plan_json={
                    "steps": steps,
                    "preparation": {"stage": "complete"},
                },
                created_at=started + timedelta(minutes=5),
            ),
        ]
    )
    await db_session.flush()

    notices = await list_reading_notices(db_session, evolution_project_id, {})

    # reading_status (the panel) shows the completed recompute; the drained
    # run cannot be resumed, so a "上次阅读已暂停" notice is stale noise.
    assert [item for item in notices if item["category"] == "reading_run"] == []


@pytest.mark.xfail(
    strict=True,
    reason="B6-F3: the pattern read picks the newest revision at or before the "
    "cutoff, so a later author reject/correct is ignored for earlier Scenes",
)
async def test_b6_author_reject_after_extension_applies_at_earlier_cutoff(
    db_session, evolution_project_id, monkeypatch
):
    from core.container import container_scope
    from core.service_keys import STORY_SCENE_SOURCE
    from modules.evolution.evidence_read import read_evolution_object_patterns
    from modules.evolution.models import EvolutionLedgerEntry, EvolutionLedgerRevision
    from modules.evolution.tests.test_evidence_read import (
        ENTITY_ID,
        SCENE_ID,
        _claim,
        _ScenePort,
    )

    async def current(*_args, **_kwargs):
        return "current"

    async def active_project(*_args, **_kwargs):
        return None

    for name in ("_identity_status", "claim_freshness", "_claim_ranges_current"):
        monkeypatch.setattr(f"modules.evolution.evidence_read.{name}", current)
    monkeypatch.setattr(
        "modules.evolution.evidence_read.require_active_project", active_project
    )

    nid = UUID(evolution_project_id)
    first = _claim().model_dump(mode="json")
    # A later extraction strengthens the same entry with Scene 5 evidence; the
    # ledger stores the revision at max(dependency.scene_index).
    extended = {
        **first,
        "dependencies": [
            *first["dependencies"],
            {**first["dependencies"][0], "scene_id": str(uuid4()), "scene_index": 5},
        ],
    }
    reject = {"decision": "reject", "scene_index": 5, "basis_revision": 2}
    entry = EvolutionLedgerEntry(
        id=uuid4(),
        novel_id=nid,
        origin_key="b6-f3",
        category="conditional_behavior",
        head_revision=3,
        author_decision_json=reject,
    )
    db_session.add(entry)
    await db_session.flush()
    for revision, scene_index, claim, decision, kind in (
        (1, 2, first, {}, "create"),
        (2, 5, extended, {}, "update"),
        (3, 5, extended, reject, "author_decision"),
    ):
        db_session.add(
            EvolutionLedgerRevision(
                id=uuid4(),
                novel_id=nid,
                entry_id=entry.id,
                revision=revision,
                operation_key=f"b6-f3-{revision}",
                request_hash=f"b6-f3-{revision}",
                scene_index=scene_index,
                kind=kind,
                body_json={
                    "claim": claim,
                    "review": {"verdict": "supported"},
                    "author_decision": decision,
                    "proposal_target": None,
                },
            )
        )
    await db_session.flush()

    with container_scope({STORY_SCENE_SOURCE: _ScenePort()}):
        result = await read_evolution_object_patterns(
            db_session,
            novel_id=evolution_project_id,
            scene_id=SCENE_ID,
            entity_ids=[ENTITY_ID],
        )

    # The author rejected this interpretation; a Scene-2 brief must not bring
    # the pre-decision revision back (README: 逐条核验复核/作者决定).
    assert result["items"] == [], result["items"]
