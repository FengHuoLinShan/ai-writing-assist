"""Fixed review counterexamples and confirmed category rescans, without providers."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.tasks.models import AsyncTask
from modules.evolution.category_rescan import (
    CategoryRescanRequest,
    CategoryRescanStart,
    handle_category_rescan,
    preview_category_rescan,
    resume_category_rescan,
    start_category_rescan,
)
from modules.evolution.consumer_reuse import find_reusable, read_set, sample_inputs
from modules.evolution.contracts import SourceRevisionRef
from modules.evolution.discovery import _compile_change, prepare_discovery
from modules.evolution.ledger import read_discovery_coverage
from modules.evolution.ledger_contracts import LedgerClaim
from modules.evolution.models import EvolutionRun
from modules.evolution.pipeline import _utterance_attribution
from modules.evolution.reading import _inheriting_live_runs
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tasks import handle_evolution_scene_step
from modules.evolution.tests.test_discovery_occurrences import prepared_occurrence
from modules.evolution.tests.test_workflow import (
    empty_world_response,
    request_start,
    seed,
    structure_response,
)
from modules.evolution.workflow import ReadingRequest, preview_reading, start_reading
from modules.writing.facade import create_draft_only


def test_mixed_speaker_quote_cannot_pass_language_habit_compiler():
    prepared, batch, change = prepared_occurrence()
    oid = batch["current_observation_ids"][0]
    obs = prepared["observations"][oid]
    text = "甲说：“够了。”乙说：「我不走。」"
    quote = "够了。”乙说：「我不走"
    start = text.index(quote)
    ref = obs["evidence_quotes"][0]["source_ref"]
    ref.update(start_offset=start, end_offset=start + len(quote))
    ref["range_hash"] = SourceRevisionRef.compute_range_hash(
        ref["content_hash"], start, start + len(quote)
    )
    obs.update(predicate=quote, modality="character_statement")
    obs["evidence_quotes"][0]["quote"] = quote
    attribution = _utterance_attribution(text, quote, start, start + len(quote))
    attribution["speaker_resolution"] = {
        "outcome": "reuse",
        "resolved_entity_id": str(uuid4()),
    }
    obs["utterance_attribution"] = attribution
    change.update(
        category="language_habit",
        label="我不走",
        conditions=[],
        statement="甲的台词。",
        evidence=[
            {"observation_id": oid, "purpose": "occurrence", "occurrence_kind": "event"}
        ],
    )
    with pytest.raises(ValueError, match="language_habit_requires_world_bound_dialogue"):
        _compile_change(prepared, change, batch)


async def test_legal_dense_theme_does_not_poison_new_theme_primary_batch(monkeypatch):
    prepared, batch, change = prepared_occurrence()
    template = deepcopy(next(iter(prepared["observations"].values())))
    template["source_ref"] = template["evidence_quotes"][0]["source_ref"]
    old = [
        deepcopy(template)
        | {"observation_id": f"{i + 1:064x}", "predicate": "旧" * 1990 + f"{i:010d}"}
        for i in range(32)
    ]
    prepared["observations"] = {item["observation_id"]: item for item in old}
    batch["current_observation_ids"] = list(prepared["observations"])
    change["evidence"] = [
        {"observation_id": oid, "purpose": "occurrence", "occurrence_kind": "event"}
        for oid in prepared["observations"]
    ]
    claim = LedgerClaim.model_validate(
        _compile_change(prepared, change, batch)["claim"]
    ).model_dump(mode="json")
    previous = SimpleNamespace(
        run_id="run",
        attempt_id="attempt",
        source_manifest_hash="b" * 64,
        payload={
            "scene_id": template["position"]["scene_id"],
            "scene_index": 0,
            "compiled_observations": old,
        },
    )
    current = deepcopy(template)
    quote = "甲等候。"
    current.update(observation_id="c" * 64, predicate=quote, quote=quote)
    current["evidence_quotes"][0]["quote"] = quote
    ref = current["source_ref"]
    ref.update(
        draft_id="draft-2",
        chapter_identity="chapter:2",
        start_offset=0,
        end_offset=len(quote),
    )
    ref["range_hash"] = SourceRevisionRef.compute_range_hash(
        ref["content_hash"], 0, len(quote)
    )
    frozen = SimpleNamespace(
        novel_id=ref["novel_id"],
        run_id="run",
        attempt_id="current",
        source_manifest_hash="c" * 64,
        payload={
            "scene_id": str(uuid4()),
            "scene_index": 1,
            "scene_text": quote,
            "compiled_observations": [current],
            "source_binding": {
                "draft_id": "draft-2",
                "chapter_index": 2,
                "content_hash": ref["content_hash"],
                "start_offset": 0,
                "end_offset": len(quote),
                "additional_sources": [],
            },
        },
    )
    theme = {
        "entry_id": str(uuid4()),
        "revision": 1,
        "source_status": "current",
        "method_status": "current",
        "proposal_target": None,
        "independent_review": {"verdict": "supported"},
        "author_decision": None,
        "claim": claim,
    }

    class Store:
        async def load_committed_pairs(self, run):
            return [
                (
                    SimpleNamespace(
                        committed_scene_index=0, run_key="run", attempt_key="attempt"
                    ),
                    None,
                )
            ]

        async def load_frozen(self, run, attempt):
            return previous

    async def no_op(*args, **kwargs):
        pass

    async def ledger(*args, **kwargs):
        return {"items": [theme], "total": 1}

    monkeypatch.setattr("modules.evolution.discovery.require_cached_prefix", no_op)
    monkeypatch.setattr("modules.evolution.discovery.list_ledger", ledger)
    result = await prepare_discovery(None, Store(), frozen)
    executable = [
        batch
        for index, batch in enumerate(result["batches"])
        if index not in result["unsupported_batches"]
    ]
    assert result["unsupported_batches"]
    assert any(
        batch["allow_new_themes"] and "c" * 64 in batch["current_observation_ids"]
        for batch in executable
    )


async def test_inheriting_host_is_found_beyond_first_page(
    db_session, evolution_project_id
):
    now = datetime.now(UTC)
    reference = {"run_key": "old", "attempt_id": "old-attempt"}
    for i in range(70):
        db_session.add(
            EvolutionRun(
                novel_id=UUID(evolution_project_id),
                run_key=f"host-{i}",
                mode="scoped_recompute",
                execution_mode="live",
                status="stopped",
                created_at=now + timedelta(seconds=i),
                reading_plan_json={"inherited_receipts": [reference] if i == 0 else []},
            )
        )
    await db_session.flush()
    assert await _inheriting_live_runs(db_session, evolution_project_id, reference) == [
        "host-0"
    ]


@pytest.fixture
async def read_project(
    db_session, evolution_project_id, account_llm_connection, monkeypatch, request
):
    db, nid = db_session, evolution_project_id
    calls = []
    config = getattr(request, "param", {})

    async def provider(self, request, *, complete_stream=False):
        response = empty_world_response(request) or structure_response(request)
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])["title"]
        calls.append(schema)
        if response:
            return response
        if schema in {"SceneSample", "CategorySceneSample"}:
            text = (
                next(
                    message.content
                    for message in request.messages
                    if "正文】\n" in message.content
                )
                .split("正文】\n", 1)[1]
                .split("\n【", 1)[0]
            )
            body = {
                "observations": [{"predicate": text, "quote": text}],
                "scene_events": [],
            }
            if schema == "SceneSample" and config.get("old_empty"):
                body["observations"] = []
            if schema == "SceneSample" and config.get("old_action_only"):
                body["observations"] = [{"predicate": "天亮了。", "quote": "天亮了。"}]
            if schema == "CategorySceneSample":
                body["category_coverage"] = {"external_appearance": "inspected"}

        elif schema == "DiscoveryOutput":
            body = {
                "changes": [],
                "coverage": "inspected",
                "coverage_note": "合成扫描已检查，未检出。",
                "category_coverage": {
                    "external_appearance": "inspected",
                    "language_habit": "inspected",
                    "clue": "inspected",
                },
            }
        else:
            raise AssertionError(schema)
        return LLMCallResponse(
            content=json.dumps(body),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)

    async def checkpoint(self):
        return True

    monkeypatch.setattr(
        AsyncSession, "checkpoint_task_progress", checkpoint, raising=False
    )
    await seed(db, nid, 1, config.get("text", "天亮了。"))
    run = (await start_reading(db, nid, await request_start(db, nid, end_chapter=1)))[
        "run"
    ]
    task_id = run["task_id"]
    while task_id:
        task = await db.get(AsyncTask, UUID(task_id))
        result = await handle_evolution_scene_step(db, task)
        task.mark_done(result)
        await db.commit()
        task_id = result.get("next_task_id")
    return db, nid, run, calls


def rescan_request():
    return CategoryRescanRequest(
        operation_id=uuid4(),
        from_scene_index=0,
        through_scene_index=0,
        categories=["external_appearance"],
        request_limit=4,
    )


@pytest.mark.parametrize("post_commit_stage", [False, True, "unknown", "pending"])
async def test_rescan_preview_confirm_replay_scope_coverage_and_old_receipts(
    read_project,
    post_commit_stage,
):
    db, nid, run, calls = read_project
    store = PostgresAttemptStore(db, nid)
    pairs = await store.load_committed_pairs(run["run_key"])
    if post_commit_stage:
        origin = await store.load_frozen(run["run_key"], pairs[0][0].attempt_key)
        await store.replace_frozen_payload(
            origin.model_copy(
                update={
                    "payload": {
                        **origin.payload,
                        "optional_stage_version": 1,
                        "optional_scene_stage": {
                            "version": 1,
                            "receipt_attempt_id": origin.attempt_id,
                            "steps": {"details": {"status": "complete", "gaps": []}},
                        },
                    }
                }
            )
        )
        if post_commit_stage in {"unknown", "pending"}:
            latest = await store.load_frozen(run["run_key"], origin.attempt_id)
            payload = deepcopy(latest.payload)
            payload["optional_scene_stage"]["steps"]["details"]["status"] = (
                post_commit_stage
            )
            if post_commit_stage == "unknown":
                payload["scene_discovery_0"] = {
                    "stage": "failed",
                    "paid_call_receipt": None,
                }
            await store.replace_frozen_payload(
                latest.model_copy(update={"payload": payload})
            )
            row = await store.load_run(run["run_key"])
            row.reading_plan_json = {**row.reading_plan_json, "optional_stage_version": 1}
        await db.commit()
        pairs = await store.load_committed_pairs(run["run_key"])
    if post_commit_stage in {"unknown", "pending"}:
        with pytest.raises(
            ConflictError,
            match="尚未核清" if post_commit_stage == "unknown" else "可选阶段",
        ):
            await preview_category_rescan(db, nid, run["run_key"], rescan_request())
        if post_commit_stage == "pending":
            from modules.evolution.spatial_rescan import (
                SpatialRescanRequest,
                preview_spatial_rescan,
            )

            with pytest.raises(ConflictError, match="可选阶段"):
                await preview_spatial_rescan(
                    db,
                    nid,
                    run["run_key"],
                    SpatialRescanRequest(
                        operation_id=uuid4(),
                        from_scene_index=0,
                        through_scene_index=0,
                        request_limit=2,
                    ),
                )
        return
    old = deepcopy(pairs[0][1].payload_json)
    from modules.evolution.workflow import reading_proposals

    proposals_before = await reading_proposals(db, nid, run["run_key"])
    before = len(calls)
    request = rescan_request()
    preview = await preview_category_rescan(db, nid, run["run_key"], request)
    assert len(calls) == before
    assert preview["scene_count"] == 1 and preview["call_count"] == 3
    started = CategoryRescanStart(
        **request.model_dump(),
        expected_fingerprint=preview["fingerprint"],
        authorization_confirmed=True,
    )
    queued = await start_category_rescan(db, nid, run["run_key"], started)
    assert (await start_category_rescan(db, nid, run["run_key"], started))[
        "task_id"
    ] == queued["task_id"]
    with pytest.raises(ConflictError, match="补扫仍在运行"):
        await preview_reading(
            db,
            nid,
            ReadingRequest(
                operation_id=uuid4(),
                mode="append",
                run_key=run["run_key"],
                end_chapter=1,
                request_limit=10,
            ),
        )
    task = await db.get(AsyncTask, UUID(queued["task_id"]))
    result = await handle_category_rescan(db, task)
    task.mark_done(result)
    await db.commit()
    assert calls[before:] == ["CategorySceneSample", "DiscoveryOutput"]
    assert (
        await store.load_frozen(pairs[0][0].run_key, pairs[0][0].attempt_key)
    ).payload == old
    assert (await store.load_run(run["run_key"])).committed_scene_index == 0
    assert await reading_proposals(db, nid, run["run_key"]) == proposals_before
    coverage = await read_discovery_coverage(db, nid, old["scene_id"])
    statuses = {item["key"]: item["status"] for item in coverage["categories"]}
    assert statuses["external_appearance"] == "inspected"
    assert statuses["clue"] == statuses["language_habit"] == "not_checked"
    assert coverage["status"] == "partial"


@pytest.mark.parametrize("drift", ["source", "root_task", "request"])
async def test_rescan_start_revalidates_preview_before_budget(read_project, drift):
    db, nid, run, _ = read_project
    store = PostgresAttemptStore(db, nid)
    request = rescan_request()
    preview = await preview_category_rescan(db, nid, run["run_key"], request)
    before = (await store.load_run(run["run_key"])).budget_total
    if drift == "source":
        await create_draft_only(db, nid, 1, "第一章", "天黑了。")
    elif drift == "root_task":
        row = await store.load_run(run["run_key"])
        task = await db.get(AsyncTask, UUID(row.reading_plan_json["task_id"]))
        task.status = "pending"
    else:
        request = request.model_copy(update={"categories": ["language_habit"]})
    await db.commit()
    start = CategoryRescanStart(
        **request.model_dump(),
        expected_fingerprint=preview["fingerprint"],
        authorization_confirmed=True,
    )
    with pytest.raises(ConflictError):
        await start_category_rescan(db, nid, run["run_key"], start)
    await db.rollback()
    row = await store.load_run(run["run_key"])
    assert row.budget_total == before and not row.reading_plan_json.get(
        "category_rescans"
    )


@pytest.mark.parametrize("unknown", [False, True])
async def test_rescan_paid_result_resumes_without_dispatch_and_unknown_blocks(
    read_project, monkeypatch, unknown
):
    db, nid, run, calls = read_project
    store = PostgresAttemptStore(db, nid)
    request = rescan_request()
    preview = await preview_category_rescan(db, nid, run["run_key"], request)
    queued = await start_category_rescan(
        db,
        nid,
        run["run_key"],
        CategoryRescanStart(
            **request.model_dump(),
            expected_fingerprint=preview["fingerprint"],
            authorization_confirmed=True,
        ),
    )
    task = await db.get(AsyncTask, UUID(queued["task_id"]))
    from modules.evolution import discovery

    compile_result = discovery.compile_discovery

    def interrupt(*args):
        raise RuntimeError("interrupted after sampled result")

    monkeypatch.setattr(discovery, "compile_discovery", interrupt)
    before = len(calls)
    with pytest.raises(RuntimeError, match="after sampled"):
        await handle_category_rescan(db, task)
    task.mark_failed("interrupted")
    await db.commit()
    assert len(calls) == before + 2
    row = await store.load_run(run["run_key"])
    attempt = await store.load_frozen(
        run["run_key"], row.reading_plan_json["category_rescans"][0]["attempt_ids"][0]
    )
    if unknown:
        payload = deepcopy(attempt.payload)
        payload["scene_discovery_0"]["stage"] = "sampling"
        await store.replace_frozen_payload(
            attempt.model_copy(update={"payload": payload})
        )
        await db.commit()
        with pytest.raises(ConflictError, match="尚未核清"):
            await resume_category_rescan(db, nid, run["run_key"], request.operation_id)
        assert len(calls) == before + 2
        return
    monkeypatch.setattr(discovery, "compile_discovery", compile_result)
    await resume_category_rescan(db, nid, run["run_key"], request.operation_id)
    await handle_category_rescan(db, await db.get(AsyncTask, UUID(queued["task_id"])))
    assert len(calls) == before + 2


async def test_consumer_reuse_missing_or_changed_proof_is_conservative():
    run = SimpleNamespace(
        llm_snapshot_json={"profile": {"model": "fixture"}},
        reading_plan_json={
            "recompute_baseline": {
                "receipts": [{"scene_index": 0, "run_key": "old", "attempt_id": "old"}]
            }
        },
    )
    old = SimpleNamespace(
        novel_id="project",
        run_id="old",
        attempt_id="old",
        payload={
            "scene_id": "scene",
            "scene_world": {"stage": "sampled", "result": {"entities": []}},
        },
    )

    class Store:
        novel_id = "project"

        async def load_frozen(self, run, attempt):
            return old

    proof = read_set(
        run,
        "state_review",
        {
            "scene_text": "原文",
            "input_manifest": {"author_revision": 2},
            "observations": [],
            "events": [],
        },
    )
    assert await find_reusable(Store(), run, 0, "scene", proof) is None
    old.payload["scene_world"]["read_set"] = proof
    assert await find_reusable(Store(), run, 0, "scene", proof)
    for changed in (
        {"context": {"author_revision": 3}, "text": "原文"},
        {"context": {"author_revision": 2}, "text": "改文"},
    ):
        assert (
            await find_reusable(
                Store(),
                run,
                0,
                "scene",
                read_set(
                    run,
                    "state_review",
                    {
                        "scene_text": changed["text"],
                        "input_manifest": changed["context"],
                        "observations": [],
                        "events": [],
                    },
                ),
            )
            is None
        )
    old.payload["scene_world"]["stage"] = "sampling"
    assert await find_reusable(Store(), run, 0, "scene", proof) is None


def test_scene_sampler_consumes_all_previous_facts_and_coverage():
    manifest = {
        "scene_index": 4,
        "run_key": "old",
        "source_manifest_hash": "old",
        "previous_scene_attempt_id": "old-parent",
        "previous_committed_prefix": {
            "through_scene_index": 3,
            "through_source_revision": 4,
        },
        "previous_observations": [
            {
                "observation_id": "old-id",
                "predicate": "甲知道秘密",
                "modality": "belief",
                "subjects": ["甲"],
                "scene_index": 3,
            }
        ],
        "previous_observations_coverage": {"omitted_observations": 0},
    }
    inputs = sample_inputs("正文", manifest, scene_id="scene", versions={"observer": 1})
    copy = deepcopy(manifest)
    copy.update(
        run_key="new", source_manifest_hash="new", previous_scene_attempt_id="new-parent"
    )
    copy["previous_observations"][0]["observation_id"] = "new-id"
    assert (
        sample_inputs("正文", copy, scene_id="scene", versions={"observer": 1}) == inputs
    )
    for field, value in (
        ("predicate", "甲不知道秘密"),
        ("modality", "event_observed"),
        ("subjects", ["乙"]),
    ):
        changed = deepcopy(copy)
        changed["previous_observations"][0][field] = value
        assert (
            sample_inputs("正文", changed, scene_id="scene", versions={"observer": 1})
            != inputs
        )


async def test_changed_early_scene_only_resamples_consuming_window(
    db_session, evolution_project_id, account_llm_connection, monkeypatch
):
    db, nid = db_session, evolution_project_id
    scenes = [
        "天亮了。",
        "下雨了。",
        "风停了。",
        "花开了。",
        "船到了。",
        "门开了。",
        "夜深了。",
    ]
    for chapter, text in enumerate(scenes, 1):
        await seed(db, nid, chapter, text)
    calls = []

    async def provider(self, request, *, complete_stream=False):
        if result := empty_world_response(request) or structure_response(request):
            return result
        text = (
            next(
                message.content
                for message in request.messages
                if "正文】\n" in message.content
            )
            .split("正文】\n", 1)[1]
            .split("\n【", 1)[0]
        )
        calls.append(text)
        return LLMCallResponse(
            content=json.dumps(
                {"observations": [{"predicate": text, "quote": text}], "scene_events": []}
            ),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)

    async def finish(run):
        task_id = run["task_id"]
        while task_id:
            task = await db.get(AsyncTask, UUID(task_id))
            result = await handle_evolution_scene_step(db, task)
            task.mark_done(result)
            await db.commit()
            task_id = result.get("next_task_id")

    old = (
        await start_reading(
            db, nid, await request_start(db, nid, end_chapter=7, request_limit=100)
        )
    )["run"]
    await finish(old)
    assert calls == scenes
    await create_draft_only(db, nid, 1, "第一章", "天黑了。")
    await db.commit()
    new = (
        await start_reading(
            db,
            nid,
            await request_start(
                db,
                nid,
                mode="revise",
                run_key=old["run_key"],
                end_chapter=7,
                request_limit=100,
            ),
        )
    )["run"]
    await finish(new)
    assert calls[7:] == ["天黑了。", *scenes[1:4]]
    store = PostgresAttemptStore(db, nid)
    pairs = await store.load_committed_pairs(new["run_key"])
    assert len(pairs) == 7
    for receipt, row in pairs[4:]:
        journal = row.payload_json["scene_sample"]
        assert journal["reused_from"]["run_key"] == old["run_key"]
        assert not row.payload_json.get("paid_call_receipt")
        assert row.payload_json["input_manifest"]["run_key"] == new["run_key"]
    assert pairs[0][1].payload_json["compiled_observations"][0]["predicate"] == "天黑了。"


@pytest.mark.parametrize(
    "read_project",
    [
        {"text": "林舟左脸有一道疤。", "old_empty": True},
        {"text": "天亮了。林舟左脸有一道疤。", "old_action_only": True},
    ],
    indirect=True,
)
async def test_rescan_collects_new_evidence_when_old_observations_missed_category(
    read_project, monkeypatch
):
    db, nid, run, calls = read_project
    original_provider = OpenAIProvider.generate

    async def provider(self, request, *, complete_stream=False):
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])["title"]
        if schema not in {"DiscoveryOutput", "DiscoveryReview"}:
            return await original_provider(self, request, complete_stream=complete_stream)
        inputs = json.loads(
            next(
                message.content
                for message in request.messages
                if message.role == "user" and "current_observation_ids" in message.content
            )
        )
        calls.append(schema)
        if schema == "DiscoveryOutput":
            body = {
                "changes": [
                    {
                        "action": "new",
                        "category": "external_appearance",
                        "label": "左脸伤疤",
                        "statement": "林舟左脸有一道疤。",
                        "confidence": 0.8,
                        "evidence": [
                            {
                                "observation_id": inputs["current_observation_ids"][0],
                                "purpose": "occurrence",
                                "occurrence_kind": "event",
                            }
                        ],
                    }
                ],
                "coverage": "inspected",
                "coverage_note": "新扫描原文。",
                "category_coverage": {"external_appearance": "inspected"},
            }
        else:
            body = {
                "verdicts": [
                    {
                        "change_index": 0,
                        "verdict": "supported",
                        "reason": "原文直接描写。",
                        "occurrence_observation_ids": [
                            inputs["changes"][0]["evidence"][0]["observation_id"]
                        ],
                    }
                ]
            }
        return LLMCallResponse(
            content=json.dumps(body),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    store = PostgresAttemptStore(db, nid)
    old = (await store.load_committed_pairs(run["run_key"]))[0][1]
    original_observations = deepcopy(old.payload_json["compiled_observations"])
    request = rescan_request()
    preview = await preview_category_rescan(db, nid, run["run_key"], request)
    queued = await start_category_rescan(
        db,
        nid,
        run["run_key"],
        CategoryRescanStart(
            **request.model_dump(),
            expected_fingerprint=preview["fingerprint"],
            authorization_confirmed=True,
        ),
    )
    task = await db.get(AsyncTask, UUID(queued["task_id"]))
    result = await handle_category_rescan(db, task)
    task.mark_done(result)
    await db.commit()
    from modules.evolution.ledger import list_ledger

    entries = await list_ledger(
        db, nid, through_scene_index=0, category="external_appearance"
    )
    assert entries["total"] == 1
    assert entries["items"][0]["source_status"] == "current"
    assert "林舟左脸有一道疤。" in entries["items"][0]["claim"]["evidence"][0]["quote"]
    assert (await store.load_frozen(old.run_key, old.attempt_key)).payload[
        "compiled_observations"
    ] == original_observations


@pytest.mark.parametrize("stage", ["before_send", "sampled", "unknown"])
async def test_rescan_crashed_worker_projects_lifecycle_and_preserves_unknown(
    read_project, stage
):
    db, nid, run, calls = read_project
    store = PostgresAttemptStore(db, nid)
    request = rescan_request()
    preview = await preview_category_rescan(db, nid, run["run_key"], request)
    queued = await start_category_rescan(
        db,
        nid,
        run["run_key"],
        CategoryRescanStart(
            **request.model_dump(),
            expected_fingerprint=preview["fingerprint"],
            authorization_confirmed=True,
        ),
    )
    task = await db.get(AsyncTask, UUID(queued["task_id"]))
    task.mark_running()
    task.heartbeat_at = task.started_at = datetime.now(UTC) - timedelta(minutes=5)
    row = await store.load_run(run["run_key"])
    row.reading_plan_json = {
        **row.reading_plan_json,
        "category_rescans": [
            {**item, "status": "running"}
            for item in row.reading_plan_json["category_rescans"]
        ],
    }
    entry = row.reading_plan_json["category_rescans"][0]
    if stage != "before_send":
        frozen = await store.load_frozen(run["run_key"], entry["attempt_ids"][0])
        payload = deepcopy(frozen.payload)
        payload["scene_discovery_0"] = {
            "stage": "sampling" if stage == "unknown" else "sampled",
            "result": {"changes": []},
        }
        await store.replace_frozen_payload(frozen.model_copy(update={"payload": payload}))
    await db.commit()
    from infrastructure.tasks.lifecycle import TaskLifecycleService

    counts = await TaskLifecycleService().recover_stale(db, max_heartbeat_gap=60)
    await db.commit()
    assert counts["manual_resume"] == 1
    from modules.evolution.workflow import reading_status

    view = (await reading_status(db, nid, run["run_key"]))["run"]["category_rescans"][0]
    before = len(calls)
    if stage == "unknown":
        assert view["status"] == "needs_reconciliation" and not view["can_resume"]
        with pytest.raises(ConflictError, match="尚未核清"):
            await resume_category_rescan(db, nid, run["run_key"], request.operation_id)
    else:
        assert view["status"] == "failed" and view["can_resume"]
        assert (
            await resume_category_rescan(db, nid, run["run_key"], request.operation_id)
        )["status"] == "pending"
    assert len(calls) == before


@pytest.mark.parametrize("crashed", [False, True])
async def test_rescan_does_not_inherit_settled_world_failure(read_project, crashed):
    db, nid, run, _ = read_project
    store = PostgresAttemptStore(db, nid)
    receipt = (await store.load_committed_pairs(run["run_key"]))[0][0]
    old = await store.load_frozen(receipt.run_key, receipt.attempt_key)
    payload = deepcopy(old.payload)
    payload["scene_world"] = {
        "stage": "failed",
        "paid_call_receipt": {
            "outcome": "failed_final",
            "usage": {"usage_complete": True, "unknown_attempts": 0},
            "attempts_detail": [{"status": "failed", "error_kind": "invalid_json"}],
        },
    }
    await store.replace_frozen_payload(old.model_copy(update={"payload": payload}))
    await db.commit()
    request = rescan_request()
    preview = await preview_category_rescan(db, nid, run["run_key"], request)
    queued = await start_category_rescan(
        db,
        nid,
        run["run_key"],
        CategoryRescanStart(
            **request.model_dump(),
            expected_fingerprint=preview["fingerprint"],
            authorization_confirmed=True,
        ),
    )
    task = await db.get(AsyncTask, UUID(queued["task_id"]))
    row = await store.load_run(run["run_key"])
    fresh = await store.load_frozen(
        run["run_key"], row.reading_plan_json["category_rescans"][0]["attempt_ids"][0]
    )
    assert "scene_world" not in fresh.payload
    assert "paid_call_receipt" not in fresh.payload
    if crashed:
        task.mark_running()
        task.heartbeat_at = task.started_at = datetime.now(UTC) - timedelta(minutes=5)
        await db.commit()
        from infrastructure.tasks.lifecycle import TaskLifecycleService

        await TaskLifecycleService().recover_stale(db, max_heartbeat_gap=60)
        await db.commit()
        await resume_category_rescan(db, nid, run["run_key"], request.operation_id)
    result = await handle_category_rescan(db, task)
    task.mark_done(result)
    await db.commit()
    from modules.evolution.workflow import reading_status

    view = (await reading_status(db, nid, run["run_key"]))["run"]["category_rescans"][0]
    assert view["status"] == "completed" and not view["can_resume"]
    assert (
        await store.load_frozen(receipt.run_key, receipt.attempt_key)
    ).payload == payload


def test_identity_review_read_set_uses_actual_review_prompt_schema_and_runtime():
    from modules.evolution.consumer_reuse import consumer_kind, request_contract
    from modules.evolution.discovery import REVIEW_PROMPT
    from modules.evolution.ledger_contracts import DiscoveryReview

    kind = consumer_kind("scene_discovery_identity_0_1")
    contract = request_contract(
        kind, {"inputs": {}}, {"model": "deepseek-flash", "provider_id": "deepseek"}
    )
    assert kind == "scene_discovery_identity"
    assert contract["schema"] == DiscoveryReview.model_json_schema()
    assert contract["request"]["messages"][0]["content"] == REVIEW_PROMPT
    assert "partial_list_fields" not in contract["options"]


@pytest.mark.parametrize(
    "read_project",
    [{"text": "甲留下线索。" + "。" * 300 + "乙留下线索。"}],
    indirect=True,
)
async def test_world_group_exact_read_set_reuses_only_unaffected_group(
    read_project, monkeypatch
):
    from modules.evolution.consumer_reuse import request_contract
    from modules.evolution.pipeline import SceneSourceBinding, _run_scene_call
    from modules.evolution.world import (
        _make_world_audit_group,
        materialize_world_audit_group,
    )

    db, novel_id, previous_run, _ = read_project
    store = PostgresAttemptStore(db, novel_id)
    old_receipt = (await store.load_committed_pairs(previous_run["run_key"]))[0][0]
    original = await store.load_frozen(old_receipt.run_key, old_receipt.attempt_key)
    scene_id = original.payload["scene_id"]
    text = "甲留下线索。" + "。" * 300 + "乙留下线索。"
    updated = text.replace("甲留下线索。", "甲丢下线索。")
    entities = [
        {
            "name": name,
            "entity_type": "character",
            "suggested_action": "create_new",
            "evidence_quotes": [quote],
        }
        for name, quote in (("甲", "甲留下线索。"), ("乙", "乙留下线索。"))
    ]
    context = {"identity_candidates": [], "_identity_queries": [], "_entity_ref_map": {}}

    def group(index, current_text, draft, digest):
        world = {
            "entities": deepcopy(entities),
            "delta_events": [],
            "uncertain_items": [],
        }
        if draft == "new":
            world["entities"][0]["evidence_quotes"] = ["甲丢下线索。"]
        return _make_world_audit_group(
            members=[
                {
                    "path": "entities",
                    "index": index,
                    "refs": set(),
                    "query_keys": set(),
                    "quotes": world["entities"][index]["evidence_quotes"],
                }
            ],
            world=world,
            relations={"aliases": [], "relations": [], "uncertain_items": []},
            context=context,
            initial_context=context,
            source=SceneSourceBinding(
                draft_id=draft,
                chapter_index=1,
                content_hash=digest,
                start_offset=0,
                end_offset=len(current_text),
            ),
            scene_text=current_text,
            novel_id=novel_id,
            attempt_id=draft,
            grouped=True,
        )

    before = [group(i, text, "old", "a" * 64) for i in range(2)]
    after = [group(i, updated, "new", "b" * 64) for i in range(2)]
    verdict = {
        "verdict": "pass",
        "findings": [],
        "dimensions": [
            {"dimension": name, "checked": True}
            for name in ("prior_prose", "world_entities", "imported_assets")
        ],
    }
    old_run = await store.load_run(previous_run["run_key"])
    payload = deepcopy(original.payload)
    for i in range(2):
        payload[f"scene_world_review_group_{i}"] = {
            "stage": "sampled",
            "read_set": read_set(
                old_run,
                "scene_world_review_group",
                {"method": "imports.scene_world_review.group.v3", **before[i]["spec"]},
            ),
            "result": verdict,
        }
    await store.replace_frozen_payload(original.model_copy(update={"payload": payload}))
    await db.commit()
    await create_draft_only(db, novel_id, 1, "第一章", updated)
    await db.commit()
    current_run = (
        await start_reading(
            db,
            novel_id,
            await request_start(
                db,
                novel_id,
                mode="revise",
                run_key=previous_run["run_key"],
                end_chapter=1,
                request_limit=20,
            ),
        )
    )["run"]
    from modules.evolution import pipeline

    finish = pipeline._finish_scene_results

    async def finish_with_group_audit(db, store, frozen, source, reviewer, caller):
        frozen = await finish(db, store, frozen, source, reviewer, caller)
        current = await store.load_run(frozen.run_id)
        budget_before = current.budget_remaining
        dispatched = []

        async def call(**inputs):
            dispatched.append(inputs)
            return {"result": verdict, "paid_call_receipt": {"outcome": "succeeded"}}

        assert before[1]["group_id"] == after[1]["group_id"]
        assert before[1]["source_read_set"] != after[1]["source_read_set"]
        for i, expected in ((1, True), (0, False)):
            proof = read_set(
                current,
                "scene_world_review_group",
                {"method": "imports.scene_world_review.group.v3", **after[i]["spec"]},
            )
            assert (
                bool(await find_reusable(store, current, 0, scene_id, proof)) == expected
            )
            key = f"scene_world_review_group_current_{i}"
            frozen = await _run_scene_call(
                db,
                store,
                frozen,
                SceneSourceBinding.model_validate(frozen.payload["source_binding"]),
                journal_key=key,
                inputs={
                    "method": "imports.scene_world_review.group.v3",
                    **after[i]["spec"],
                },
                call_inputs=after[i]["spec"],
                call=call,
            )
            journal = frozen.payload[key]
            assert bool(journal.get("reused_from")) == expected
            assert bool(journal.get("paid_call_receipt")) != expected
            assert (
                materialize_world_audit_group(after[i], journal["result"])["status"]
                == "passed"
            )
            assert (
                request_contract(
                    "scene_world_review_group",
                    after[i]["spec"],
                    current.llm_snapshot_json["profile"],
                )["schema"]["title"]
                == "AuditVerdictOutput"
            )
        assert len(dispatched) == 1
        assert (await store.load_run(frozen.run_id)).budget_remaining == budget_before - 1
        return frozen

    monkeypatch.setattr(pipeline, "_finish_scene_results", finish_with_group_audit)
    task = await db.get(AsyncTask, UUID(current_run["task_id"]))
    result = await handle_evolution_scene_step(db, task)
    task.mark_done(result)
    await db.commit()
    receipt = (await store.load_committed_pairs(current_run["run_key"]))[0][0]
    frozen = await store.load_frozen(receipt.run_key, receipt.attempt_key)
    assert (
        frozen.payload["scene_world_review_group_current_1"]["reused_from"]["run_key"]
        == previous_run["run_key"]
    )


@pytest.mark.parametrize("new_context", [False, True])
async def test_first_rescan_uses_new_luna_context_without_upgrading_legacy(
    read_project, new_context
):
    from infrastructure.llm.capabilities import legacy_capability_snapshot
    from infrastructure.llm.tests.test_luna_context_scope import luna_snapshot
    from modules.evolution.category_rescan import _plan

    db, nid, run, _ = read_project
    store = PostgresAttemptStore(db, nid)
    row = await store.load_run(run["run_key"])
    snapshot = luna_snapshot()
    if not new_context:
        snapshot["llm_capability_profile"] = legacy_capability_snapshot(
            "codex", "gpt-6-luna"
        )
    row.llm_snapshot_json = snapshot
    await db.commit()
    before = await store.load_committed_pairs(run["run_key"])
    original = deepcopy(before[0][1].payload_json)
    assert original["discovery_version"] == 0
    _, _, plans, _, _ = await _plan(
        db,
        nid,
        run["run_key"],
        rescan_request().model_copy(update={"request_limit": 100}),
    )
    assert plans[0]["frozen"].payload["discovery_version"] == (2 if new_context else 1)
    assert (plans[0]["preparation"].get("context_snapshot") is not None) == new_context
    assert (await store.load_committed_pairs(run["run_key"]))[0][
        1
    ].payload_json == original
