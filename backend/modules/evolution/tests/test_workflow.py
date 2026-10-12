"""The author entry freezes real sources and drives the existing queue/receipts."""

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from core.errors import ConflictError
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.tasks.models import AsyncTask
from modules.evolution.commit import CommitConflictError
from modules.evolution.facade import read_committed_understanding
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tasks import handle_evolution_scene_step
from modules.evolution.workflow import (
    ReadingRequest,
    ReadingStart,
    preview_reading,
    reading_status,
    reading_targets,
    start_reading,
)
from modules.story.facade import create_scene
from modules.writing.facade import create_draft_only


def empty_world_response(prompt):
    schema = json.loads(prompt.messages[-1].content.split("schema: ", 1)[1])["title"]
    if schema in {"Phase2aSceneExtractionOutput", "AliasRelationExtractionOutput"}:
        return LLMCallResponse(
            content="{}",
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
        )
    return None


def structure_response(prompt):
    """One fully-supported plot thread through the structure generate/review pair."""
    schema = json.loads(prompt.messages[-1].content.split("schema: ", 1)[1])["title"]
    usage = LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20)
    if schema == "SimpleStructureOutput":
        cards = json.loads(
            next(
                message.content
                for message in prompt.messages
                if message.role == "user" and "【Scene卡片 JSON】" in message.content
            )
            .split("【Scene卡片 JSON】\n", 1)[1]
            .split("\n\n", 1)[0]
        )
        return LLMCallResponse(
            content=json.dumps(
                {
                    "plot_threads": [
                        {
                            "title": "主线",
                            "summary": "主角推进当前目标。",
                            "confidence": 0.95,
                            "supporting_scene_ids": [item["scene_id"] for item in cards],
                        }
                    ]
                }
            ),
            finish_reason="stop",
            usage=usage,
        )
    if schema == "StructureEvidenceReviewOutput":
        units = json.loads(
            next(message.content for message in prompt.messages if message.role == "user")
        )["review_items"]
        return LLMCallResponse(
            content=json.dumps(
                {
                    "reviews": [
                        {
                            "candidate_id": item["candidate_id"],
                            "verdict": "supported",
                            "confidence": 0.96,
                            "evidence": [{"quote": item["scene_text"]}],
                        }
                        for item in units
                    ]
                }
            ),
            finish_reason="stop",
            usage=usage,
        )
    return None


@pytest.mark.parametrize("kind", ["entity", "observation"])
async def test_targeted_scope_uses_original_receipts_and_preserves_prefix(
    db_session, evolution_project_id, account_llm_connection, monkeypatch, kind
):
    from modules.world.models import WorldEntity

    db, nid = db_session, evolution_project_id
    person = WorldEntity(
        id=uuid4(),
        novel_id=UUID(nid),
        name="林舟",
        entity_type="character",
        status="canonical",
    )
    db.add(person)
    entity_id = person.id
    texts = ["天亮了。", "林舟没有听说封锁。", "风停了。"]
    for chapter, text in enumerate(texts, 1):
        await seed(db, nid, chapter, text)
    calls = []

    async def provider(self, prompt, *, complete_stream=False):
        if response := empty_world_response(prompt):
            return response
        calls.append(prompt)
        if response := structure_response(prompt):
            return response
        text = texts[[0, 1, 2, 2, 2, 1, 2][len(calls) - 1]]
        return LLMCallResponse(
            content=json.dumps(
                {
                    "observations": [
                        {
                            "predicate": text,
                            "quote": text,
                            "modality": "belief",
                            "mentions": [{"surface": "林舟", "entity_type": "character"}]
                            if "林舟" in text
                            else [],
                        }
                    ],
                    "scene_events": [],
                }
            ),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    original = (
        await start_reading(db, nid, await request_start(db, nid, end_chapter=3))
    )["run"]
    task_id = original["task_id"]
    for _ in range(3):
        task = await db.get(AsyncTask, UUID(task_id))
        result = await handle_evolution_scene_step(db, task)
        task.status = "done"
        task_id = result.get("next_task_id")
        await db.commit()
    # The Scene prefix alone is not completion; settle the structure stage so the
    # scoped recompute below is not blocked by a still-running old task.
    structure_task = await db.get(AsyncTask, UUID(task_id))
    await handle_evolution_scene_step(db, structure_task)
    structure_task.status = "done"
    await db.commit()
    targets = await reading_targets(
        db, nid, original["run_key"], kind=kind, query="林舟", limit=1
    )
    assert targets["total"] == 1
    selected = targets["items"][0]
    assert selected["scene_index"] == 1 and selected["modality"] == "belief"
    if kind == "entity":
        assert selected["id"] == str(entity_id)
    assert not (
        await reading_targets(
            db, nid, original["run_key"], kind=kind, query="林舟", offset=1
        )
    )["items"]
    options = {f"{kind}_id": selected["id"]}
    request = await request_start(
        db,
        nid,
        mode="scoped_recompute",
        run_key=original["run_key"],
        end_chapter=3,
        **options,
    )
    preview = await preview_reading(db, nid, request)
    assert preview["inherited_scene_count"] == 1
    assert preview["recompute_target"] == selected
    assert len(calls) == 5  # Searching and previewing never call the model.
    invalid = {f"{kind}_id": uuid4() if kind == "entity" else "0" * 64}
    with pytest.raises(ConflictError, match="不在本次"):
        await request_start(
            db,
            nid,
            mode="scoped_recompute",
            run_key=original["run_key"],
            end_chapter=3,
            **invalid,
        )
    with pytest.raises(ConflictError, match="调用上限"):
        await preview_reading(db, nid, request.model_copy(update={"request_limit": 1}))
    updated = (await start_reading(db, nid, request))["run"]
    assert updated["completed_scenes"] == 1
    assert (await start_reading(db, nid, request))["run"]["task_id"] == updated["task_id"]
    task_id = updated["task_id"]
    for _ in range(2):
        task = await db.get(AsyncTask, UUID(task_id))
        result = await handle_evolution_scene_step(db, task)
        task.status = "done"
        task_id = result.get("next_task_id")
        await db.commit()
    store = PostgresAttemptStore(db, nid)
    pairs = await store.load_committed_pairs(updated["run_key"])
    assert [receipt.run_key for receipt, _ in pairs] == [
        original["run_key"],
        updated["run_key"],
        original["run_key"],
    ]
    current_run = await store.load_run(updated["run_key"])
    assert current_run.committed_scene_index == 2
    assert sum(receipt.run_key == updated["run_key"] for receipt, _ in pairs) == 1
    hashes = {
        step["source_binding"]["draft_id"]: step["source_binding"]["content_hash"]
        for step in current_run.reading_plan_json["steps"]
    }
    refs, omissions = await read_committed_understanding(db, nid, hashes)
    assert [ref.scene_index for ref in refs] == [0, 1, 2]
    assert "prefix_propagation_handoff_invalid" not in omissions
    # A new query still sees the inherited prefix, with its original identity.
    assert (
        await reading_targets(
            db, nid, updated["run_key"], kind="observation", query="天亮"
        )
    )["total"] == 1
    await create_draft_only(db, nid, 1, "第一章", "天黑了。")
    await db.commit()
    expanded = await request_start(
        db,
        nid,
        mode="scoped_recompute",
        run_key=updated["run_key"],
        end_chapter=3,
        **options,
    )
    check = await preview_reading(db, nid, expanded)
    assert check["expanded_scope"] and check["recompute_from_scene_index"] == 0


async def seed(db, nid, chapter, text, *, scene=True):
    await create_draft_only(db, nid, chapter, f"第{chapter}章", text)
    if scene:
        await create_scene(
            db,
            nid,
            {
                "scene_index": chapter - 1,
                "chapter_ids": [str(chapter)],
                "title": f"场景{chapter}",
            },
        )
    await db.commit()


async def request_start(db, nid, **kwargs):
    request = ReadingRequest(
        operation_id=uuid4(), request_limit=kwargs.pop("request_limit", 10), **kwargs
    )
    preview = await preview_reading(db, nid, request)
    return ReadingStart(
        **request.model_dump(),
        expected_fingerprint=preview["fingerprint"],
        authorization_confirmed=True,
    )


async def test_reading_entry_sequences_replays_and_appends_without_resampling(
    db_session,
    evolution_project_id,
    account_llm_connection,
    monkeypatch,
):
    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, "天亮了。")
    await seed(db, nid, 2, "下雨了。")
    calls = []

    async def provider(self, prompt, *, complete_stream=False):
        if response := empty_world_response(prompt):
            return response
        assert not db.in_transaction()
        user = next(
            message.content for message in prompt.messages if message.role == "user"
        )
        calls.append(user)
        if response := structure_response(prompt):
            return response
        text = ["天亮了。", "下雨了。", "风停了。", "风停了。", "风停了。"][
            len(calls) - 1
        ]
        return LLMCallResponse(
            content=json.dumps(
                {
                    "observations": [
                        {
                            "predicate": text,
                            "quote": text,
                            "modality": "event_observed",
                        }
                    ],
                    "scene_events": [],
                }
            ),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    # The author may set a future upper bound; only real saved sources are read.
    request = await request_start(db, nid, end_chapter=10)
    started = (await start_reading(db, nid, request))["run"]
    key = started["run_key"]
    assert started["total_scenes"] == 2 and not calls
    assert started["end_chapter"] == 2
    assert (await start_reading(db, nid, request))["run"]["task_id"] == started["task_id"]
    # Persisted authorizations from before target selection omit its optional fields.
    old_run = await PostgresAttemptStore(db, nid).load_run(key)
    old_plan = json.loads(json.dumps(old_run.reading_plan_json))
    for field in ("entity_id", "observation_id"):
        old_plan["segments"][0]["request"].pop(field)
    old_run.reading_plan_json = old_plan
    await db.flush()
    assert (await start_reading(db, nid, request))["run"]["task_id"] == started["task_id"]
    with pytest.raises(ConflictError, match="同一次操作"):
        await start_reading(db, nid, request.model_copy(update={"request_limit": 4}))
    first = await db.get(AsyncTask, UUID(started["task_id"]))
    first_result = await handle_evolution_scene_step(db, first)
    assert not first_result["reading_complete"]
    # Crash after receipt commit but before the worker acknowledges success.
    replay = await handle_evolution_scene_step(db, first)
    assert replay["attempt_id"] == first_result["attempt_id"]
    assert replay["next_task_id"] == first_result["next_task_id"]
    second = await db.get(AsyncTask, UUID(replay["next_task_id"]))
    assert second.meta["source_revisions"]
    # The Scene prefix alone is not completion: the structure stage follows.
    second_result = await handle_evolution_scene_step(db, second)
    assert not second_result["reading_complete"]
    structure = await db.get(AsyncTask, UUID(second_result["next_task_id"]))
    assert (await handle_evolution_scene_step(db, structure))["reading_complete"]
    assert len(calls) == 4 and "天亮了。" in calls[1]
    assert (await reading_status(db, nid, key))["run"]["status"] == "completed"
    await seed(db, nid, 3, "风停了。")
    append = await request_start(db, nid, mode="append", run_key=key, end_chapter=3)
    next_run = (await start_reading(db, nid, append))["run"]
    assert next_run["budget_total"] == 20
    assert (await start_reading(db, nid, append))["run"]["budget_total"] == 20
    third = await db.get(AsyncTask, UUID(next_run["task_id"]))
    third_result = await handle_evolution_scene_step(db, third)
    assert len(calls) == 5 and "下雨了。" in calls[-1]
    run = await PostgresAttemptStore(db, nid).load_run(key)
    assert run.mode == "bootstrap" and run.budget_remaining == 12
    # Appending retains old batches and opens the newly committed range.
    assert run.reading_plan_json["structure_version"] == 1
    assert not run.reading_plan_json["structure"]["complete"]
    assert len(run.reading_plan_json["structure"]["batches"]) == 1
    appended_structure = await db.get(AsyncTask, UUID(third_result["next_task_id"]))
    assert (await handle_evolution_scene_step(db, appended_structure))["reading_complete"]
    run = await PostgresAttemptStore(db, nid).load_run(key)
    assert run.reading_plan_json["structure"]["complete"]
    assert len(run.reading_plan_json["structure"]["batches"]) == 2
    assert run.reading_plan_json["structure"]["through_scene_index"] == 2
    assert len(calls) == 7
    assert len(run.reading_plan_json["segments"]) == 2


async def test_scoped_recompute_inherits_real_prefix_after_invalid_quote(
    db_session,
    evolution_project_id,
    account_llm_connection,
    monkeypatch,
):
    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, "天亮了。")
    await seed(db, nid, 2, "也没有提起封锁。")
    calls = []

    async def provider(self, prompt, *, complete_stream=False):
        if response := empty_world_response(prompt):
            return response
        calls.append(prompt)
        if response := structure_response(prompt):
            return response
        quote = [
            "天亮了。",
            "他没有提起封锁。",
            "也没有提起封锁。",
            "风停了。",
            "风停了。",
            "风停了。",
        ][len(calls) - 1]
        return LLMCallResponse(
            content=json.dumps(
                {
                    "observations": [
                        {"predicate": quote, "quote": quote, "modality": "event_observed"}
                    ],
                    "scene_events": [],
                }
            ),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    original_request = await request_start(db, nid, end_chapter=2)
    old = (await start_reading(db, nid, original_request))["run"]
    first_task = await db.get(AsyncTask, UUID(old["task_id"]))
    first = await handle_evolution_scene_step(db, first_task)
    second_task = await db.get(AsyncTask, UUID(first["next_task_id"]))
    with pytest.raises(CommitConflictError) as caught:
        await handle_evolution_scene_step(db, second_task)
    assert caught.value.code == "invalid_observation_source"
    second_task.status = "failed"
    await db.commit()
    repair = await request_start(
        db,
        nid,
        mode="scoped_recompute",
        run_key=old["run_key"],
        from_scene_index=1,
        end_chapter=2,
    )
    preview = await preview_reading(db, nid, repair)
    assert preview["inherited_scene_count"] == 1
    assert preview["recompute_from_scene_index"] == 1
    new = (await start_reading(db, nid, repair))["run"]
    assert new["run_key"] != old["run_key"]
    store = PostgresAttemptStore(db, nid)
    head = await store.load_head_receipt(new["run_key"])
    assert head.run_id == old["run_key"] and head.attempt_id == first["attempt_id"]
    assert (await store.load_run(new["run_key"])).committed_scene_index == 0
    assert (await start_reading(db, nid, repair))["run"]["task_id"] == new["task_id"]
    assert len(calls) == 2
    repaired_task = await db.get(AsyncTask, UUID(new["task_id"]))
    repaired = await handle_evolution_scene_step(db, repaired_task)
    assert len(calls) == 3
    structure_task = await db.get(AsyncTask, UUID(repaired["next_task_id"]))
    await handle_evolution_scene_step(db, structure_task)
    assert len(calls) == 5
    assert (await reading_status(db, nid, new["run_key"]))["run"]["status"] == "completed"
    observations, coverage = await store.load_prior_observations(new["run_key"])
    assert [item["scene_index"] for item in observations] == [0, 1]
    assert coverage["total_committed_scenes"] == 2
    steps = (await store.load_run(new["run_key"])).reading_plan_json["steps"]
    hashes = {
        part["draft_id"]: part["content_hash"]
        for step in steps
        for part in [
            step["source_binding"],
            *step["source_binding"].get("additional_sources", []),
        ]
    }
    refs, omissions = await read_committed_understanding(db, nid, hashes)
    assert [(ref.run_key, ref.scene_index) for ref in refs] == [
        (old["run_key"], 0),
        (new["run_key"], 1),
    ]
    assert not omissions
    assert (await read_committed_understanding(db, nid, hashes, required=refs))[0] == refs
    await seed(db, nid, 3, "风停了。")
    appended = await request_start(
        db, nid, mode="append", run_key=new["run_key"], end_chapter=3
    )
    next_task_id = (await start_reading(db, nid, appended))["run"]["task_id"]
    await handle_evolution_scene_step(db, await db.get(AsyncTask, UUID(next_task_id)))
    assert len(calls) == 6
    observations, _ = await store.load_prior_observations(new["run_key"])
    assert [item["scene_index"] for item in observations] == [0, 1, 2]
    await create_draft_only(db, nid, 1, "第一章", "天黑了。")
    await db.commit()
    assert (await store.load_run(new["run_key"])).status == "source_stale"
    with pytest.raises(ConflictError, match="场景理解"):
        await read_committed_understanding(db, nid, hashes, required=refs)


async def test_revise_keeps_unchanged_prefix_and_rejects_unfinished_old_task(
    db_session,
    evolution_project_id,
    account_llm_connection,
    monkeypatch,
):
    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, "天亮了。")
    await seed(db, nid, 2, "下雨了。")
    calls = []

    async def provider(self, prompt, *, complete_stream=False):
        if response := empty_world_response(prompt):
            return response
        calls.append(prompt)
        quote = ["天亮了。", "下雨了。", "风停了。"][len(calls) - 1]
        return LLMCallResponse(
            content=json.dumps(
                {
                    "observations": [
                        {"predicate": quote, "quote": quote, "modality": "event_observed"}
                    ],
                    "scene_events": [],
                }
            ),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    old_request = await request_start(db, nid, end_chapter=2)
    old = (await start_reading(db, nid, old_request))["run"]
    first = await db.get(AsyncTask, UUID(old["task_id"]))
    first_result = await handle_evolution_scene_step(db, first)
    second = await db.get(AsyncTask, UUID(first_result["next_task_id"]))
    second_result = await handle_evolution_scene_step(db, second)
    # The run's latest task after the Scene prefix is the structure stage.
    structure = await db.get(AsyncTask, UUID(second_result["next_task_id"]))
    await create_draft_only(db, nid, 2, "第二章", "风停了。")
    await db.commit()
    assert (
        await PostgresAttemptStore(db, nid).load_run(old["run_key"])
    ).status == "source_stale"
    revise = await request_start(
        db, nid, mode="revise", run_key=old["run_key"], end_chapter=2
    )
    preview = await preview_reading(db, nid, revise)
    assert preview["inherited_scene_count"] == 1
    assert preview["recompute_from_scene_index"] == 1
    structure.status = "running"
    await db.commit()
    with pytest.raises(ConflictError, match="原理解任务仍在运行"):
        await start_reading(db, nid, revise)
    structure.status = "done"
    await db.commit()
    new = (await start_reading(db, nid, revise))["run"]
    await handle_evolution_scene_step(db, await db.get(AsyncTask, UUID(new["task_id"])))
    assert len(calls) == 3
    assert (
        await PostgresAttemptStore(db, nid).load_run(new["run_key"])
    ).committed_scene_index == 1
    steps = (
        await PostgresAttemptStore(db, nid).load_run(new["run_key"])
    ).reading_plan_json["steps"]
    hashes = {
        step["source_binding"]["draft_id"]: step["source_binding"]["content_hash"]
        for step in steps
    }
    refs, omissions = await read_committed_understanding(db, nid, hashes)
    assert [(ref.run_key, ref.scene_index) for ref in refs] == [
        (old["run_key"], 0),
        (new["run_key"], 1),
    ]
    assert not omissions


def test_scene_state_fingerprint_ignores_source_revision_but_not_meaning():
    from copy import deepcopy

    from modules.evolution.pipeline import (
        observation_equivalence_map,
        scene_state_fingerprint,
    )

    baseline = {
        "compiled_observations": [
            {
                "observation_id": "old-id",
                "predicate": "甲看见天亮了。",
                "modality": "event_observed",
                "subjects": ["甲"],
                "evidence_quotes": [
                    {
                        "quote": "天亮了。",
                        "source_ref": {
                            "draft_id": "old-draft",
                            "content_hash": "a" * 64,
                            "chapter_identity": "chapter-1",
                            "start_offset": 0,
                            "end_offset": 4,
                        },
                    }
                ],
            }
        ],
        "gated_scene_events": [],
        "world_result": {
            "context": {
                "_current_scene_text": "天亮了。",
                "source_observation_ids": ["old-id"],
            },
            "dependencies": ["world-1"],
        },
        "world_materialization": {},
        "discovery_result": {"method_fingerprint": "method-1"},
        "discovery_materialization": {},
        "enrichment_result": None,
    }
    current = deepcopy(baseline)
    current["compiled_observations"][0]["observation_id"] = "new-id"
    current["compiled_observations"][0]["evidence_quotes"][0]["source_ref"].update(
        draft_id="new-draft", content_hash="b" * 64
    )
    current["world_result"]["context"].update(
        _current_scene_text="天亮了。今天很暖。",
        source_observation_ids=["new-id"],
    )
    assert scene_state_fingerprint(current) == scene_state_fingerprint(baseline)
    assert observation_equivalence_map(baseline, current) == {"old-id": "new-id"}

    current["compiled_observations"][0]["predicate"] = "甲看见天黑了。"
    assert scene_state_fingerprint(current) != scene_state_fingerprint(baseline)
    assert observation_equivalence_map(baseline, current) is None

    current = deepcopy(baseline)
    current["world_result"]["dependencies"] = ["world-2"]
    assert scene_state_fingerprint(current) != scene_state_fingerprint(baseline)
    current = deepcopy(baseline)
    current["discovery_result"]["method_fingerprint"] = "method-2"
    assert scene_state_fingerprint(current) != scene_state_fingerprint(baseline)


def test_scene_state_fingerprint_covers_scene_events_and_ignores_review_provenance():
    from copy import deepcopy

    from modules.evolution.pipeline import scene_state_fingerprint

    baseline = {
        "compiled_observations": [],
        "scene_events": [
            {
                "event_type": "knowledge_changed",
                "dimension": "knowledge",
                "knowledge_subject": "char-1",
                "source_observation_ids": ["obs-1"],
                "snapshot_after": {
                    "id": "uuid5-run-a",
                    "character_id": "char-1",
                    "knowledge_level": "fact",
                    "meta": {
                        "state_review": {"attempt_id": "attempt-a", "input_hash": "h1"},
                        "source_observation_ids": ["obs-1"],
                    },
                },
            }
        ],
        "gated_scene_events": [],
    }
    # 复核证明与派生 knowledge id 随 run 变化 → 指纹不变。
    current = deepcopy(baseline)
    current["scene_events"][0]["snapshot_after"]["meta"]["state_review"] = {
        "attempt_id": "attempt-b",
        "input_hash": "h2",
    }
    current["scene_events"][0]["snapshot_after"]["id"] = "uuid5-run-b"
    assert scene_state_fingerprint(current) == scene_state_fingerprint(baseline)

    # 实际状态效果变化 → 指纹必须变化。
    current = deepcopy(baseline)
    current["scene_events"][0]["snapshot_after"]["knowledge_level"] = "rumor"
    assert scene_state_fingerprint(current) != scene_state_fingerprint(baseline)

    current = deepcopy(baseline)
    current["scene_events"] = []
    assert scene_state_fingerprint(current) != scene_state_fingerprint(baseline)


def test_scene_state_fingerprint_normalizes_mention_identity_across_revisions():
    from modules.evolution.pipeline import scene_state_fingerprint

    def payload(observation_id, mention_id):
        return {
            "compiled_observations": [
                {
                    "observation_id": observation_id,
                    "predicate": "甲说他会回来。",
                    "modality": "character_statement",
                    "mentions": [
                        {
                            "mention_id": mention_id,
                            "surface": "甲",
                            "entity_type": "character",
                            "resolution": {
                                "mention_id": mention_id,
                                "surface": "甲",
                                "outcome": "reuse",
                                "resolved_entity_id": "char-1",
                            },
                        }
                    ],
                    "utterance_attribution": {
                        "kind": "direct_dialogue",
                        "speaker_surface": "甲",
                        "speaker_resolution": {
                            "mention_id": mention_id,
                            "outcome": "reuse",
                            "resolved_entity_id": "char-1",
                        },
                    },
                    "evidence_quotes": [
                        {
                            "quote": "甲说他会回来。",
                            "source_ref": {
                                "draft_id": "draft",
                                "content_hash": "a" * 64,
                                "chapter_identity": "chapter-1",
                                "start_offset": 0,
                                "end_offset": 7,
                            },
                        }
                    ],
                }
            ]
        }

    # 整稿换版只改观察/提及身份 → 指纹不变。
    assert scene_state_fingerprint(
        payload("obs-old", "mention-old")
    ) == scene_state_fingerprint(payload("obs-new", "mention-new"))

    changed = payload("obs-new", "mention-new")
    changed["compiled_observations"][0]["mentions"][0]["surface"] = "乙"
    assert scene_state_fingerprint(changed) != scene_state_fingerprint(
        payload("obs-old", "mention-old")
    )


def test_recompute_handoff_requires_the_entire_recomputed_prefix_to_match():
    from modules.evolution.pipeline import (
        equivalent_scene_state_fingerprint,
        scene_state_fingerprint,
    )
    from modules.evolution.reading import _recomputed_prefix_matches_baseline

    def payload(index, scene_id, observation_id, predicate):
        value = {
            "scene_index": index,
            "scene_id": scene_id,
            "source_binding": {"draft_id": f"draft-{index}"},
            "compiled_observations": [
                {
                    "observation_id": observation_id,
                    "predicate": predicate,
                    "modality": "event_observed",
                    "mentions": [],
                    "evidence_quotes": [],
                }
            ],
        }
        value["state_fingerprint"] = scene_state_fingerprint(value)
        return value

    baseline_payloads = [
        payload(0, "scene-0", "old-0", "旧观察"),
        payload(1, "scene-1", "old-1", "稳定观察"),
    ]
    current_payloads = [
        payload(0, "scene-0", "new-0", "新增观察"),
        payload(1, "scene-1", "new-1", "稳定观察"),
    ]
    assert (
        equivalent_scene_state_fingerprint(baseline_payloads[1], current_payloads[1])
        is not None
    )

    def pairs(run_key, payloads):
        return [
            (
                SimpleNamespace(
                    run_key=run_key,
                    attempt_key=f"{run_key}-{index}",
                    committed_scene_index=index,
                ),
                SimpleNamespace(payload_json=value),
            )
            for index, value in enumerate(payloads)
        ]

    plan = {
        "recompute_from_scene_index": 0,
        "steps": [
            {
                "scene_id": f"scene-{index}",
                "source_binding": {"draft_id": f"draft-{index}"},
            }
            for index in range(2)
        ],
        "recompute_baseline": {
            "run_key": "baseline",
            "receipts": [
                {
                    "scene_index": index,
                    "run_key": "baseline",
                    "attempt_id": f"baseline-{index}",
                    "source_matches": True,
                }
                for index in range(2)
            ],
        },
    }
    assert not _recomputed_prefix_matches_baseline(
        "current",
        plan,
        1,
        pairs("current", current_payloads),
        pairs("baseline", baseline_payloads),
    )

    assert _recomputed_prefix_matches_baseline(
        "current",
        plan,
        1,
        pairs("current", baseline_payloads),
        pairs("baseline", baseline_payloads),
    )


@pytest.mark.parametrize(
    ("revision_text", "revision_quote", "should_stop"),
    [
        ("天亮了。今天很暖。", "天亮了。", True),
        ("天黑了。", "天黑了。", False),
    ],
)
async def test_revise_stops_after_recomputed_scene_state_is_unchanged(
    db_session,
    evolution_project_id,
    account_llm_connection,
    monkeypatch,
    revision_text,
    revision_quote,
    should_stop,
):
    db, nid = db_session, evolution_project_id
    original_texts = ["天亮了。", "下雨了。", "风停了。"]
    for chapter, text in enumerate(original_texts, 1):
        await seed(db, nid, chapter, text)
    calls = []

    async def provider(self, prompt, *, complete_stream=False):
        if response := empty_world_response(prompt):
            return response
        if response := structure_response(prompt):
            return response
        calls.append(prompt)
        quote = (
            revision_quote
            if len(calls) == 4
            else original_texts[(len(calls) - 1) % len(original_texts)]
        )
        return LLMCallResponse(
            content=json.dumps(
                {
                    "observations": [
                        {
                            "predicate": f"叙述者记录：{quote}",
                            "quote": quote,
                            "modality": "event_observed",
                        }
                    ],
                    "scene_events": [],
                }
            ),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    old = (await start_reading(db, nid, await request_start(db, nid, end_chapter=3)))[
        "run"
    ]
    task_id = old["task_id"]
    for _ in range(3):
        task = await db.get(AsyncTask, UUID(task_id))
        result = await handle_evolution_scene_step(db, task)
        task.mark_done(result)
        task_id = result.get("next_task_id")
        await db.commit()
    structure = await db.get(AsyncTask, UUID(task_id))
    await handle_evolution_scene_step(db, structure)
    structure.mark_done()
    await db.commit()
    assert len(calls) == 3

    await create_draft_only(db, nid, 1, "第一章", revision_text)
    await db.commit()
    revise = await request_start(
        db,
        nid,
        mode="revise",
        run_key=old["run_key"],
        end_chapter=3,
    )
    new = (await start_reading(db, nid, revise))["run"]
    task = await db.get(AsyncTask, UUID(new["task_id"]))
    result = await handle_evolution_scene_step(db, task)
    task.mark_done(result)
    await db.commit()

    run = await PostgresAttemptStore(db, nid).load_run(new["run_key"])
    if not should_stop:
        assert run.committed_scene_index == 0
        assert not run.reading_plan_json["inherited_receipts"]
        assert not run.reading_plan_json["propagation_handoffs"]
        assert result.get("next_task_id")
        assert len(calls) == 4
        return
    assert run.committed_scene_index == 2
    assert len(run.reading_plan_json["inherited_receipts"]) == 2
    assert (
        run.reading_plan_json["propagation_handoffs"][0]["reused_through_scene_index"]
        == 2
    )
    assert len(calls) == 4

    store = PostgresAttemptStore(db, nid)
    pairs = await store.load_committed_pairs(new["run_key"])
    hashes = {
        step["source_binding"]["draft_id"]: step["source_binding"]["content_hash"]
        for step in run.reading_plan_json["steps"]
    }
    refs, omissions = await read_committed_understanding(db, nid, hashes)
    assert [receipt.committed_scene_index for receipt, _ in pairs] == [0, 1, 2]
    assert [ref.scene_index for ref in refs] == [0, 1, 2]
    assert not omissions

    proof = run.reading_plan_json["propagation_handoffs"][0]
    run.reading_plan_json = {
        **run.reading_plan_json,
        "propagation_handoffs": [{**proof, "observation_map": {"forged": "observation"}}],
    }
    await db.flush()
    refs, omissions = await read_committed_understanding(db, nid, hashes)
    assert [ref.scene_index for ref in refs] == [0]
    assert "prefix_propagation_handoff_invalid" in omissions


async def test_inherited_suffix_world_candidate_passes_adoption_gate(
    db_session, evolution_project_id, account_llm_connection, monkeypatch
):
    """修订停止传播后，继承后缀的世界候选经新 run 的传播证明通过采用门。"""
    from modules.evolution.reading import require_current_world_candidate

    db, nid = db_session, evolution_project_id
    original_texts = ["天亮了。", "下雨了。", "风停了。"]
    for chapter, text in enumerate(original_texts, 1):
        await seed(db, nid, chapter, text)
    calls = []

    async def provider(self, prompt, *, complete_stream=False):
        if response := empty_world_response(prompt):
            return response
        if response := structure_response(prompt):
            return response
        calls.append(prompt)
        quote = (
            "天亮了。"
            if len(calls) == 4
            else original_texts[(len(calls) - 1) % len(original_texts)]
        )
        return LLMCallResponse(
            content=json.dumps(
                {
                    "observations": [
                        {
                            "predicate": f"叙述者记录：{quote}",
                            "quote": quote,
                            "modality": "event_observed",
                        }
                    ],
                    "scene_events": [],
                }
            ),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    old = (await start_reading(db, nid, await request_start(db, nid, end_chapter=3)))[
        "run"
    ]
    task_id = old["task_id"]
    for _ in range(3):
        task = await db.get(AsyncTask, UUID(task_id))
        result = await handle_evolution_scene_step(db, task)
        task.mark_done(result)
        task_id = result.get("next_task_id")
        await db.commit()
    structure = await db.get(AsyncTask, UUID(task_id))
    await handle_evolution_scene_step(db, structure)
    structure.mark_done()
    await db.commit()

    await create_draft_only(db, nid, 1, "第一章", "天亮了。今天很暖。")
    await db.commit()
    revise = await request_start(
        db, nid, mode="revise", run_key=old["run_key"], end_chapter=3
    )
    new = (await start_reading(db, nid, revise))["run"]
    task = await db.get(AsyncTask, UUID(new["task_id"]))
    result = await handle_evolution_scene_step(db, task)
    task.mark_done(result)
    await db.commit()

    run = await PostgresAttemptStore(db, nid).load_run(new["run_key"])
    assert run.committed_scene_index == 2
    inherited = run.reading_plan_json["inherited_receipts"]
    assert len(inherited) == 2
    # 旧 run 已 source_stale，但新 run 的传播证明使继承候选保持可采用。
    await require_current_world_candidate(db, nid, inherited[0])
    # 篡改传播证明 → 采用门重新拒绝。
    proof = run.reading_plan_json["propagation_handoffs"][0]
    run.reading_plan_json = {
        **run.reading_plan_json,
        "propagation_handoffs": [{**proof, "observation_map": {"forged": "observation"}}],
    }
    await db.flush()
    with pytest.raises(ConflictError, match="理解"):
        await require_current_world_candidate(db, nid, inherited[0])


async def test_revise_rejects_prefix_superseded_by_another_run(
    db_session, evolution_project_id, account_llm_connection, monkeypatch
):
    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, "天亮了。")
    await seed(db, nid, 2, "下雨了。")
    calls = []

    async def provider(self, prompt, *, complete_stream=False):
        if response := empty_world_response(prompt):
            return response
        quote = (
            next(
                message.content
                for message in prompt.messages
                if "正文】\n" in message.content
            )
            .split("正文】\n", 1)[1]
            .split("\n【", 1)[0]
        )
        calls.append(quote)
        return LLMCallResponse(
            content=json.dumps(
                {
                    "observations": [
                        {"predicate": quote, "quote": quote, "modality": "event_observed"}
                    ],
                    "scene_events": [],
                }
            ),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    original = await request_start(db, nid, end_chapter=2)
    a = (await start_reading(db, nid, original))["run"]
    first = await handle_evolution_scene_step(
        db, await db.get(AsyncTask, UUID(a["task_id"]))
    )
    second = await db.get(AsyncTask, UUID(first["next_task_id"]))
    second_result = await handle_evolution_scene_step(db, second)
    second.status = "done"
    # Settle the queued structure task so the replacement can take over the run.
    structure = await db.get(AsyncTask, UUID(second_result["next_task_id"]))
    structure.status = "done"
    await db.commit()
    await create_draft_only(db, nid, 2, "第二章", "风停了。")
    await db.commit()
    replacement = await request_start(
        db,
        nid,
        mode="scoped_recompute",
        run_key=a["run_key"],
        from_scene_index=0,
        end_chapter=2,
    )
    b = (await start_reading(db, nid, replacement))["run"]
    first = await handle_evolution_scene_step(
        db, await db.get(AsyncTask, UUID(b["task_id"]))
    )
    await handle_evolution_scene_step(
        db, await db.get(AsyncTask, UUID(first["next_task_id"]))
    )
    await PostgresAttemptStore(db, nid).drain_run(b["run_key"])
    await db.commit()
    with pytest.raises(ConflictError, match="原回执前缀"):
        await request_start(db, nid, mode="revise", run_key=a["run_key"], end_chapter=2)
    assert (
        len(calls) == 3
    )  # unchanged first Scene is reused; superseded prefix still rejected


async def test_reading_does_not_skip_unmapped_text_and_pins_queued_revision(
    db_session,
    evolution_project_id,
    account_llm_connection,
    monkeypatch,
):
    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, "天亮了。")
    await seed(db, nid, 2, "下雨了。", scene=False)
    await seed(db, nid, 3, "风停了。")
    request = ReadingRequest(operation_id=uuid4(), request_limit=3, end_chapter=3)
    with pytest.raises(ConflictError, match="未整理"):
        await preview_reading(db, nid, request)
    start = await request_start(db, nid, end_chapter=1)
    result = (await start_reading(db, nid, start))["run"]
    await db.commit()
    await create_draft_only(db, nid, 1, "第一章", "天黑了。")
    await db.commit()
    calls = []

    async def forbidden(self, request, *, complete_stream=False):
        calls.append(request)
        raise AssertionError("source changed before any paid request")

    monkeypatch.setattr(OpenAIProvider, "generate", forbidden)
    task = await db.get(AsyncTask, UUID(result["task_id"]))
    with pytest.raises(CommitConflictError, match="source_changed"):
        await handle_evolution_scene_step(db, task)
    assert not calls
    run = await PostgresAttemptStore(db, nid).load_run(result["run_key"])
    assert run.budget_remaining == 10
    assert run.status == "source_stale"


async def test_reading_routes_require_project_and_explicit_authorization(
    db_session,
    test_project_id,
    async_client,
    account_llm_connection,
):
    nid = test_project_id
    root = "/api/evolution"
    assert (
        await async_client.get(f"{root}/reading?novel_id={uuid4()}")
    ).status_code == 404
    body = {"engine": "evolution", "expected_epoch": 1, "authorization_confirmed": False}
    assert (
        await async_client.post(f"{root}/engine?novel_id={nid}", json=body)
    ).status_code == 422
    body["authorization_confirmed"] = True
    switched = await async_client.post(f"{root}/engine?novel_id={nid}", json=body)
    assert switched.status_code == 200, switched.text
    await seed(db_session, nid, 1, "天亮了。")
    request = ReadingRequest(
        operation_id=uuid4(), request_limit=1, end_chapter=1
    ).model_dump(mode="json")
    preview = await async_client.post(
        f"{root}/reading/preview?novel_id={nid}", json=request
    )
    assert preview.status_code == 200, preview.text
    started = await async_client.post(
        f"{root}/reading?novel_id={nid}",
        json={
            **request,
            "expected_fingerprint": preview.json()["fingerprint"],
            "authorization_confirmed": True,
        },
    )
    assert started.status_code == 201, started.text
    assert started.json()["run"]["total_scenes"] == 1
    assert "source_binding" not in started.text and "snapshot" not in started.text
    key = started.json()["run"]["run_key"]
    targets_path = f"{root}/reading/{key}/targets"
    assert (
        await async_client.get(targets_path, params={"novel_id": nid, "kind": "entity"})
    ).json() == {"items": [], "total": 0}
    assert (
        await async_client.get(
            targets_path, params={"novel_id": str(uuid4()), "kind": "entity"}
        )
    ).status_code == 404
    assert (
        await async_client.get(targets_path, params={"novel_id": nid, "kind": "all"})
    ).status_code == 422
    assert (
        await async_client.get(
            targets_path, params={"novel_id": nid, "kind": "entity", "limit": 0}
        )
    ).status_code == 422


async def test_reading_rejects_unresolved_import_fallback_but_allows_optional_semantics(
    db_session, evolution_project_id, account_llm_connection, monkeypatch
):
    from core.errors import ValidationError
    from modules.story.facade import get_scenes_by_novel, update_scene

    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, "天亮了。")
    scene = (await get_scenes_by_novel(db, nid))[0]
    request = ReadingRequest(operation_id=uuid4(), request_limit=1, end_chapter=1)
    start = await request_start(db, nid, end_chapter=1)
    queued = (await start_reading(db, nid, start))["run"]
    await db.commit()
    fallback = {
        "phase1a_fallback": True,
        "boundary_status": "fallback",
        "needs_review": True,
        "review_issues_version": 1,
        "review_issues": [{"kind": "source_or_structure", "required": True}],
    }
    await update_scene(db, nid, scene["id"], {"structure_meta": fallback})
    await db.commit()
    with pytest.raises(ValidationError, match="场景边界尚待确认"):
        await preview_reading(db, nid, request)
    calls = []

    async def forbidden(self, request, *, complete_stream=False):
        calls.append(request)
        raise AssertionError("unreviewed source must not be sampled")

    monkeypatch.setattr(OpenAIProvider, "generate", forbidden)
    task = await db.get(AsyncTask, UUID(queued["task_id"]))
    with pytest.raises(CommitConflictError, match="场景边界尚待确认"):
        await handle_evolution_scene_step(db, task)
    assert not calls
    # The existing explicit author review can approve a whole-chapter boundary.
    await update_scene(
        db,
        nid,
        scene["id"],
        {
            "structure_meta": {
                **fallback,
                "needs_review": False,
                "reviewed_by": "manual",
                "reviewed_at": "2026-09-22T21:00:00+08:00",
            }
        },
    )
    assert (await preview_reading(db, nid, request))["scene_count"] == 1
    # Optional interpretations do not weaken a valid source boundary.
    await update_scene(
        db,
        nid,
        scene["id"],
        {
            "structure_meta": {
                "needs_review": True,
                "review_issues_version": 1,
                "review_issues": [{"kind": "optional_interpretation", "required": False}],
            }
        },
    )
    assert (await preview_reading(db, nid, request))["scene_count"] == 1
