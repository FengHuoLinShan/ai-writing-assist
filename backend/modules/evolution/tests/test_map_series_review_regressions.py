"""Regression targets from the map-series review (T-20261016-map-series-claude-review).

Each case encodes the specified behavior for a confirmed review finding. Cases
remain strict xfail only while their corresponding defect is open.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from core.errors import ConflictError
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


@pytest.mark.parametrize("unknown", [False, True])
async def test_b2_scene_card_edit_settles_optional_stage_as_gap(
    db_session, evolution_project_id, monkeypatch, unknown
):
    from modules.story.outline_state.models import Scene

    db, nid = db_session, evolution_project_id
    scene_id = await seed(db, nid, {1: "城门开启。"})
    store = await plan_run(db, nid)
    register_scene_sampler("source-integrity", lambda db, novel_id: Sample())
    calls = []

    async def provider(**kwargs):
        calls.append("provider")
        # The author edits the Scene card while optional work is in flight.
        scene = await db.get(Scene, UUID(scene_id))
        scene.title = "作者修订后的卡片"
        await db.commit()
        if unknown:
            from modules.evolution.pipeline import SamplePendingReconciliationError

            raise SamplePendingReconciliationError(
                "scene_spatial_discovery", "provider result requires reconciliation"
            )
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
    await handle_evolution_scene_step(db, task)

    # The committed main receipt must not stay hostage to optional work: the
    # step settles as a stale gap that a later spatial rescan can fill.
    run = await store.load_run("source-integrity")
    assert await load_pending_optional_stage(store, run) is None
    receipt = await store.load_committed_scene_receipt("source-integrity", 0)
    frozen = await store.load_frozen(receipt.run_id, receipt.attempt_id)
    assert frozen.payload["optional_scene_stage"]["steps"]["spatial"] == {
        "status": "unknown" if unknown else "stale",
        "gaps": [
            {"reason": "request_requires_reconciliation"}
            if unknown
            else {"reason": "scene_card_changed"}
        ],
    }
    assert frozen.payload["optional_step_coverage"]["spatial"]["status"] == (
        "unknown" if unknown else "stale"
    )
    await handle_evolution_scene_step(db, task)
    assert calls == ["provider"]


def test_b2_density_precheck_ignores_non_spatial_common_words():
    density = _density_hits(
        "他把东西放下，说了声谢谢，又低头喝茶。", [], MapSpatialClueContext()
    )

    assert density["count"] == 0, density


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

    review_context = _type_review_context(raw, context, str(uuid4()), "f" * 64)

    # _make_clues requires reviewed_evidence_indices == range(len(prior) + 1).
    quotes = [item["quote"] for item in review_context["evidence"]]
    assert quotes == ["旧城被高墙围住", "门在东侧"]


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
                "spatial_rescan_origin": {
                    "run_key": origin.run_id,
                    "attempt_id": origin.attempt_id,
                    "source_manifest_hash": origin.source_manifest_hash,
                },
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
    incomplete_operation_id = str(uuid4())
    incomplete = origin.model_copy(
        update={
            "attempt_id": str(uuid4()),
            "payload": {
                **origin.payload,
                "spatial_rescan_operation_id": incomplete_operation_id,
                "spatial_rescan_status": "pending",
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
                },
                {
                    "operation_id": incomplete_operation_id,
                    "attempt_ids": [incomplete.attempt_id],
                    "from_scene_index": 0,
                    "through_scene_index": 0,
                    "status": "failed",
                },
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
            return [
                (
                    receipt,
                    SimpleNamespace(
                        payload_json=origin.payload,
                        source_manifest_hash=origin.source_manifest_hash,
                    ),
                )
            ]

        async def load_committed_scene_receipt(
            self, run_key, scene_index, *, source_manifest_hash=None
        ):
            if (
                run_key == receipt.run_key
                and scene_index == receipt.committed_scene_index
                and source_manifest_hash == origin.source_manifest_hash
            ):
                return SimpleNamespace(attempt_id=origin.attempt_id)
            return None

        async def load_head_receipt(self, run_key):
            return SimpleNamespace(attempt_id=origin.attempt_id, committed_prefix="p")

        async def load_frozen(self, run_key, attempt_id):
            return {
                origin.attempt_id: origin,
                rescanned.attempt_id: rescanned,
                incomplete.attempt_id: incomplete,
            }.get(attempt_id)

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
    from modules.evolution.workflow import _optional_coverage_summary

    summary = await _optional_coverage_summary(Store(), run, None)
    assert summary["spatial"]["counts"]["inspected"] == 1


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


@pytest.mark.parametrize("decision_key", ["reject", "corrected"])
async def test_b6_author_reject_after_extension_applies_at_earlier_cutoff(
    db_session, evolution_project_id, monkeypatch, decision_key
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
    decision = {
        "decision": decision_key,
        "scene_index": 5,
        "basis_revision": 2,
        **(
            {"corrected_statement": "更正后的倾向"} if decision_key == "corrected" else {}
        ),
    }
    entry = EvolutionLedgerEntry(
        id=uuid4(),
        novel_id=nid,
        origin_key="b6-f3",
        category="conditional_behavior",
        head_revision=3,
        author_decision_json=decision,
    )
    db_session.add(entry)
    await db_session.flush()
    for revision, scene_index, claim, decision, kind in (
        (1, 2, first, {}, "create"),
        (2, 5, extended, {}, "update"),
        (3, 5, extended, decision, "author_decision"),
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
    if decision_key == "reject":
        assert result["items"] == [], result["items"]
    else:
        assert [item["statement"] for item in result["items"]] == ["更正后的倾向"]


async def test_append_preview_rejects_active_spatial_rescan(monkeypatch):
    import modules.evolution.optional_scene as optional_scene
    import modules.evolution.spatial_rescan as spatial_rescan
    import modules.evolution.workflow as workflow

    run = SimpleNamespace(
        run_key="reading-run",
        status="active",
        committed_scene_index=0,
        llm_snapshot_json={"profile": {"model": "luna"}},
        reading_plan_json={
            "steps": [{"scene_index": 0}],
            "spatial_version": 0,
            "preparation": None,
            "spatial_rescans": [{"task_id": "rescan-task", "status": "pending"}],
        },
    )

    class Store:
        async def load_run(self, _run_key):
            return run

        async def require_project_owner(self, _run_key):
            return None

    async def allow_writer(*_args, **_kwargs):
        return "owner"

    async def no_optional_stage(*_args, **_kwargs):
        return None

    async def pending_spatial_rescan(*_args, **_kwargs):
        return [{"status": "pending"}]

    monkeypatch.setattr(workflow, "require_understanding_writer", allow_writer)
    monkeypatch.setattr(workflow, "PostgresAttemptStore", lambda *_args: Store())
    monkeypatch.setattr(
        optional_scene, "load_pending_optional_stage", no_optional_stage
    )
    monkeypatch.setattr(spatial_rescan, "spatial_rescan_states", pending_spatial_rescan)
    request = workflow.ReadingRequest(
        operation_id=uuid4(),
        mode="append",
        run_key=run.run_key,
        end_chapter=2,
        request_limit=10,
    )

    with pytest.raises(ConflictError, match="完成或恢复当前空间补扫"):
        await workflow._plan(None, str(uuid4()), request)
