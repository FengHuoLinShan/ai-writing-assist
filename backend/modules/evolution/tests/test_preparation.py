"""Automatic boundaries use the real gateway, frozen replay and the root budget."""

import json
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from core.errors import ConflictError, ValidationError
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.tasks.models import AsyncTask
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tasks import handle_evolution_scene_step
from modules.evolution.tests.test_workflow import seed
from modules.evolution.workflow import (
    ReadingRequest,
    ReadingStart,
    preview_reading,
    reading_status,
    resume_reading,
    start_reading,
)
from modules.imports import facade as imports
from modules.story.facade import get_scenes_by_novel


async def start(db, nid, limit, *, end_chapter=1, **kwargs):
    request = ReadingRequest(
        operation_id=uuid4(), request_limit=limit, end_chapter=end_chapter, **kwargs
    )
    preview = await preview_reading(db, nid, request)
    body = ReadingStart(
        **request.model_dump(),
        expected_fingerprint=preview["fingerprint"],
        authorization_confirmed=True,
    )
    return body, (await start_reading(db, nid, body))["run"]


def provider_stub(db, calls):
    async def provider(self, request):
        assert not db.in_transaction(), "provider call must not hold source/project locks"
        assert request.model, (
            "pure request builders must preserve the project model default"
        )
        text = next(
            message.content for message in request.messages if message.role == "user"
        )
        calls.append(text)
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])["title"]
        if schema == "SimpleStructureOutput":
            cards = json.loads(
                text.split("【Scene卡片 JSON】\n", 1)[1].split("\n\n", 1)[0]
            )
            return LLMCallResponse(
                content=json.dumps(
                    {
                        "plot_threads": [
                            {
                                "title": "出门与归来",
                                "summary": "主角在家门与外界之间往返。",
                                "confidence": 0.95,
                                "supporting_scene_ids": [
                                    item["scene_id"] for item in cards
                                ],
                            }
                        ]
                    }
                ),
                finish_reason="stop",
                usage=LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
            )
        if schema == "StructureEvidenceReviewOutput":
            units = json.loads(text)["review_items"]
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
                usage=LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
            )
        if "CHAPTER_TEXT_JSON" in text:
            chapters = json.loads(
                text.split("<CHAPTER_TEXT_JSON>", 1)[1].split("</CHAPTER_TEXT_JSON>", 1)[
                    0
                ]
            )
            chapter = chapters[0]["chapter_index"]
            items = [
                ("归来", "回到家", "天黑了，他回到家中。"),
                ("出门", "离开家", "天亮了，他走出家门。"),
            ]
            if chapter != 1:
                items = [("再出门", "出门", chapters[0]["content"])]
            payload = {
                "window_edges": {
                    "leading_relation": "new_scene",
                    "trailing_relation": "ends_in_input",
                },
                "scenes": [
                    {
                        "title": title,
                        "goal": goal,
                        "core_conflict_status": "not_applicable",
                        "start_chapter": chapter,
                        "end_chapter": chapter,
                        "start_anchor": quote,
                        "end_anchor": quote,
                        "boundary_status": "complete",
                        "confidence": 0.95,
                    }
                    for title, goal, quote in items
                ],
            }
        elif schema in {"Phase2aSceneExtractionOutput", "AliasRelationExtractionOutput"}:
            payload = {}
        elif schema == "SceneEnrichmentOutput":
            quote = next(
                item
                for item in (
                    "天亮了，他走出家门。",
                    "天黑了，他回到家中。",
                    "雨停了，他再次出门。",
                )
                if item in text
            )
            payload = {
                "must_happen": quote,
                "field_evidence": {"must_happen": [quote]},
                "narrative_tag": "transition",
                "narrative_function": "承接人物行动",
                "confidence": 0.95,
            }
        elif schema == "AuditVerdictOutput":
            payload = {
                "verdict": "pass",
                "findings": [],
                "dimensions": [
                    {"dimension": dimension, "checked": True}
                    for dimension in ("prior_prose", "scene_state", "imported_assets")
                ],
            }
        else:
            payload = {"observations": [], "scene_events": []}
        return LLMCallResponse(
            content=json.dumps(payload),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )

    return provider


async def test_prepare_replays_then_budget_continuation_reads_exact_scenes(
    db_session,
    evolution_project_id,
    account_llm_connection,
    monkeypatch,
):
    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, "天亮了，他走出家门。\n天黑了，他回到家中。", scene=False)
    calls = []
    monkeypatch.setattr(OpenAIProvider, "generate", provider_stub(db, calls))
    _, run = await start(db, nid, 1)
    assert run["preparing_scenes"] and run["status"] == "pending"
    key = run["run_key"]
    task = await db.get(AsyncTask, UUID(run["task_id"]))
    assert task.meta["operation"] == "prepare_scenes"
    original = imports.commit_scene_boundaries

    async def broken(*args, **kwargs):
        raise RuntimeError("injected after paid boundary response")

    monkeypatch.setattr(imports, "commit_scene_boundaries", broken)
    with pytest.raises(RuntimeError, match="injected"):
        await handle_evolution_scene_step(db, task)
    await db.rollback()
    monkeypatch.setattr(imports, "commit_scene_boundaries", original)
    task = await db.get(AsyncTask, UUID(run["task_id"]))
    await handle_evolution_scene_step(db, task)
    assert len(calls) == 1
    # The old preparation task must become terminal before a new budget segment
    # can enqueue work with the same scope (the real Worker does this itself).
    with pytest.raises(ConflictError, match="不需要追加"):
        await start(db, nid, 2, mode="continue", run_key=key)
    task.status = "done"
    await db.commit()
    state = (await reading_status(db, nid, key))["run"]
    assert state["status"] == "needs_budget" and state["total_scenes"] == 2
    scenes = await get_scenes_by_novel(db, nid, status_filter=["draft", "canonical"])
    assert len(scenes) == 2
    assert [scene["title"] for scene in scenes] == ["出门", "归来"]
    assert all(
        scene["source"] == "evolution"
        and scene["structure_meta"]["semantic_origin"] == "boundary_only"
        for scene in scenes
    )
    body, continued = await start(db, nid, 10, mode="continue", run_key=key)
    assert (await start_reading(db, nid, body))["run"]["budget_total"] == 11
    first = await db.get(AsyncTask, UUID(continued["task_id"]))
    result = await handle_evolution_scene_step(db, first)
    assert "天亮了，他走出家门。" in calls[1] and "天黑了，他回到家中。" not in calls[1]
    second = await db.get(AsyncTask, UUID(result["next_task_id"]))
    second_result = await handle_evolution_scene_step(db, second)
    # The reading completes through the structure stage over the same budget.
    structure = await db.get(AsyncTask, UUID(second_result["next_task_id"]))
    await handle_evolution_scene_step(db, structure)
    state = (await reading_status(db, nid, key))["run"]
    assert state["status"] == "completed" and state["completed_scenes"] == 2
    assert len(calls) == 11 and state["budget_remaining"] == 0
    scenes = await get_scenes_by_novel(db, nid, status_filter=["draft", "canonical"])
    assert all(
        scene["structure_meta"]["semantic_origin"] == "phase1b_enrichment"
        for scene in scenes
    )
    assert [scene["must_happen"] for scene in scenes] == [
        "天亮了，他走出家门。",
        "天黑了，他回到家中。",
    ]
    first_receipt = await PostgresAttemptStore(db, nid).load_committed_scene_receipt(
        key, 0
    )
    assert first_receipt.attempt_id in calls[6]
    stored = await PostgresAttemptStore(db, nid).load_run(key)
    receipt = next(iter(stored.reading_plan_json["preparation"]["calls"].values()))[
        "paid_call_receipt"
    ]
    assert receipt["usage"]["attempts"] == 1
    old_calls = stored.reading_plan_json["preparation"]["calls"]
    await seed(db, nid, 2, "雨停了，他再次出门。", scene=False)
    _, appended = await start(db, nid, 5, mode="append", run_key=key, end_chapter=2)
    preparing = await db.get(AsyncTask, UUID(appended["task_id"]))
    result = await handle_evolution_scene_step(db, preparing)
    final = await db.get(AsyncTask, UUID(result["next_task_id"]))
    await handle_evolution_scene_step(db, final)
    stored = await PostgresAttemptStore(db, nid).load_run(key)
    assert stored.reading_plan_json["preparation_history"][0]["calls"] == old_calls
    assert len(calls) == 16 and stored.budget_remaining == 0
    assert (await reading_status(db, nid, key))["run"]["completed_scenes"] == 3

    # Recompute an already enriched automatic Scene; its previous semantic
    # fields must not silently exempt it from the new source-bound review.
    for queued_task in (task, first, second, preparing, final):
        queued_task.status = "done"
    await db.commit()
    _, recomputed = await start(
        db,
        nid,
        4,
        mode="scoped_recompute",
        run_key=key,
        end_chapter=2,
        from_scene_index=2,
    )
    queued_task = await db.get(AsyncTask, UUID(recomputed["task_id"]))
    await handle_evolution_scene_step(db, queued_task)
    assert len(calls) == 20
    assert (await reading_status(db, nid, recomputed["run_key"]))["run"][
        "completed_scenes"
    ] == 3


async def test_preparation_source_change_fences_before_provider(
    db_session,
    evolution_project_id,
    account_llm_connection,
    monkeypatch,
):
    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, "天亮了，他走出家门。", scene=False)
    _, run = await start(db, nid, 3)
    await db.commit()
    await seed(db, nid, 1, "天黑了，他回到家中。", scene=False)
    calls = []
    monkeypatch.setattr(OpenAIProvider, "generate", provider_stub(db, calls))
    task = await db.get(AsyncTask, UUID(run["task_id"]))
    with pytest.raises(ConflictError):
        await handle_evolution_scene_step(db, task)
    state = (await reading_status(db, nid, run["run_key"]))["run"]
    assert state["status"] == "source_changed" and state["budget_remaining"] == 3
    assert not calls


async def test_enrichment_budget_pause_resumes_only_audit_and_keeps_original_sample(
    db_session, evolution_project_id, account_llm_connection, monkeypatch
):
    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, "天亮了，他走出家门。\n天黑了，他回到家中。", scene=False)
    calls = []
    monkeypatch.setattr(OpenAIProvider, "generate", provider_stub(db, calls))
    _, run = await start(db, nid, 3)
    prep = await db.get(AsyncTask, UUID(run["task_id"]))
    queued = await handle_evolution_scene_step(db, prep)
    prep.status = "done"
    await db.commit()
    task = await db.get(AsyncTask, UUID(queued["next_task_id"]))
    result = await handle_evolution_scene_step(db, task)
    assert not result["reading_complete"]
    task.status = "done"
    await db.commit()
    store = PostgresAttemptStore(db, nid)
    pending = await store.load_pending_frozen(run["run_key"], 0)
    assert pending.payload["scene_enrichment"]["stage"] == "sampled"
    assert "scene_enrichment_review" not in pending.payload
    assert (await reading_status(db, nid, run["run_key"]))["run"][
        "status"
    ] == "needs_budget"
    _, continued = await start(db, nid, 2, mode="continue", run_key=run["run_key"])
    recovery = await db.get(AsyncTask, UUID(continued["task_id"]))
    result = await handle_evolution_scene_step(db, recovery)
    assert result["attempt_id"] == pending.attempt_id and len(calls) == 5
    receipt = await store.load_receipt(run["run_key"], pending.attempt_id)
    assert len(receipt.paid_call_receipts) == 4
    assert (await store.load_run(run["run_key"])).committed_scene_index == 0


@pytest.mark.parametrize(
    "failure", ["blocked", "low_confidence", "author_edit", "domain_write"]
)
async def test_enrichment_rejection_edit_and_domain_rollback_preserve_authorship(
    db_session, evolution_project_id, account_llm_connection, monkeypatch, failure
):
    from modules.evolution.commit import CommitConflictError
    from modules.story.outline_state.schemas import SceneUpdate
    from modules.story.outline_state.services import SceneService

    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, "天亮了，他走出家门。\n天黑了，他回到家中。", scene=False)
    calls = []
    base = provider_stub(db, calls)

    async def provider(self, request):
        response = await base(self, request)
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])["title"]
        if schema == "SceneEnrichmentOutput" and failure == "low_confidence":
            response.content = json.dumps(
                {**json.loads(response.content), "confidence": 0.6}
            )
        if schema == "AuditVerdictOutput" and failure == "blocked":
            response.content = json.dumps(
                {
                    "verdict": "blocked",
                    "findings": [],
                    "dimensions": [
                        {"dimension": key, "checked": True}
                        for key in ("prior_prose", "scene_state", "imported_assets")
                    ],
                }
            )
        if schema == "SceneEnrichmentOutput" and failure == "author_edit":
            scene = (await get_scenes_by_novel(db, nid))[0]
            await SceneService().update(
                db, scene["id"], SceneUpdate(emotional_beat="作者的情绪稿"), novel_id=nid
            )
            await db.commit()
        return response

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    _, run = await start(db, nid, 7)
    prep = await db.get(AsyncTask, UUID(run["task_id"]))
    queued = await handle_evolution_scene_step(db, prep)
    task = await db.get(AsyncTask, UUID(queued["next_task_id"]))
    store = PostgresAttemptStore(db, nid)
    if failure == "domain_write":
        with patch(
            "modules.story.facade.replace_scene_memory_events",
            autospec=True,
            side_effect=RuntimeError("write failed after enrichment"),
        ):
            with pytest.raises(RuntimeError, match="write failed"):
                await handle_evolution_scene_step(db, task)
        await db.rollback()
        scene = (await get_scenes_by_novel(db, nid))[0]
        assert scene["must_happen"] is None
        assert scene["structure_meta"]["semantic_origin"] == "boundary_only"
        frozen = await store.load_pending_frozen(run["run_key"], 0)
        assert frozen.payload["enrichment_result"]["review"]["status"] == "passed"
        task = await db.get(AsyncTask, UUID(queued["next_task_id"]))
        result = await handle_evolution_scene_step(db, task)
        assert result["attempt_id"] == frozen.attempt_id and len(calls) == 5
        assert (await get_scenes_by_novel(db, nid))[0][
            "must_happen"
        ] == "天亮了，他走出家门。"
    elif failure == "author_edit":
        with pytest.raises(CommitConflictError, match="scene_changed"):
            await handle_evolution_scene_step(db, task)
        await db.rollback()
        assert (await get_scenes_by_novel(db, nid))[0]["emotional_beat"] == "作者的情绪稿"
        assert (await store.load_run(run["run_key"])).committed_scene_index == -1
        frozen = await store.load_pending_frozen(run["run_key"], 0)
        assert frozen.payload["scene_enrichment"]["stage"] == "sampled"
        assert len(calls) == 3  # no paid audit after the edit
    else:
        result = await handle_evolution_scene_step(db, task)
        receipt = await store.load_receipt(run["run_key"], result["attempt_id"])
        assert "scene_enrichment_requires_review" in receipt.pending_decisions
        scene = (await get_scenes_by_novel(db, nid))[0]
        assert scene["must_happen"] is None
        assert scene["structure_meta"]["semantic_origin"] == "boundary_only"


async def test_bootstrap_reuses_existing_scenes_and_prepares_only_missing_tail(
    db_session,
    evolution_project_id,
    account_llm_connection,
    monkeypatch,
):
    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, "天亮了。")
    await seed(db, nid, 2, "雨停了，他再次出门。", scene=False)
    calls = []
    monkeypatch.setattr(OpenAIProvider, "generate", provider_stub(db, calls))
    _, run = await start(db, nid, 9, end_chapter=2)
    task = await db.get(AsyncTask, UUID(run["task_id"]))
    result = await handle_evolution_scene_step(db, task)
    assert (
        "天亮了。"
        not in calls[0]
        .split("<CHAPTER_TEXT_JSON>", 1)[1]
        .split("</CHAPTER_TEXT_JSON>", 1)[0]
    )
    assert (
        "天亮了。"
        in calls[0]
        .split("<LEFT_BOUNDARY_CONTEXT_JSON>", 1)[1]
        .split("</LEFT_BOUNDARY_CONTEXT_JSON>", 1)[0]
    )
    while not result["reading_complete"]:
        task = await db.get(AsyncTask, UUID(result["next_task_id"]))
        result = await handle_evolution_scene_step(db, task)
    stored = await PostgresAttemptStore(db, nid).load_run(run["run_key"])
    assert [step["scene_index"] for step in stored.reading_plan_json["steps"]] == [0, 1]
    assert len(calls) == 9 and stored.budget_remaining == 0


@pytest.mark.parametrize(
    "decision", ["continues_right", "continues_from_left", "low_confidence"]
)
async def test_unclosed_or_uncertain_boundaries_need_author_review(
    db_session,
    evolution_project_id,
    account_llm_connection,
    monkeypatch,
    decision,
):
    from modules.story.outline_state.scene_workbench import SceneWorkbenchService
    from modules.story.outline_state.schemas import SceneReviewRequest, SceneWorkbenchItem

    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, "天亮了，他走出家门。\n天黑了，他回到家中。", scene=False)
    calls = []
    provider = provider_stub(db, calls)

    async def unresolved(self, request):
        response = await provider(self, request)
        value = json.loads(response.content)
        if "scenes" in value:
            if decision == "continues_from_left":
                value["window_edges"]["leading_relation"] = decision
            elif decision == "continues_right":
                value["window_edges"]["trailing_relation"] = decision
                value["scenes"][0]["boundary_status"] = decision
            else:
                value["scenes"][0]["confidence"] = 0.2
            response.content = json.dumps(value)
        return response

    monkeypatch.setattr(OpenAIProvider, "generate", unresolved)
    _, run = await start(db, nid, 3)
    task = await db.get(AsyncTask, UUID(run["task_id"]))
    await handle_evolution_scene_step(db, task)
    task.status = "done"
    await db.commit()
    state = (await reading_status(db, nid, run["run_key"]))["run"]
    assert state["status"] == "needs_scene_review" and state["completed_scenes"] == 0
    assert len(calls) == 1 and state["budget_remaining"] == 2
    with pytest.raises(ValidationError, match="边界尚待确认"):
        await resume_reading(db, nid, run["run_key"])
    scenes = await get_scenes_by_novel(db, nid, status_filter=["draft", "canonical"])
    fingerprints = {
        scene["id"]: SceneWorkbenchItem(scene=scene).boundary_fingerprint
        for scene in scenes
    }
    with pytest.raises(ValueError, match="场景边界已变化"):
        await SceneWorkbenchService().review_scenes(
            db,
            nid,
            SceneReviewRequest(
                scene_ids=list(fingerprints),
                decision="review_boundary",
                boundary_fingerprints={key: "f" * 64 for key in fingerprints},
            ),
        )
    await SceneWorkbenchService().review_scenes(
        db,
        nid,
        SceneReviewRequest(
            scene_ids=[scene["id"] for scene in scenes],
            decision="review_boundary",
            boundary_fingerprints=fingerprints,
        ),
    )
    reviewed = await get_scenes_by_novel(db, nid)
    assert all(scene["status"] == "draft" for scene in reviewed)
    assert all(
        scene["structure_meta"]["semantic_origin"] == "boundary_only"
        for scene in reviewed
    )
    assert all(
        "semantic_reviewed_by" not in scene["structure_meta"] for scene in reviewed
    )
    # Reopening revokes the boundary decision too; it cannot silently continue.
    await SceneWorkbenchService().review_scenes(
        db,
        nid,
        SceneReviewRequest(
            scene_ids=[scene["id"] for scene in scenes],
            decision="reopen",
        ),
    )
    with pytest.raises(ValidationError, match="边界尚待确认"):
        await resume_reading(db, nid, run["run_key"])
    await SceneWorkbenchService().review_scenes(
        db,
        nid,
        SceneReviewRequest(
            scene_ids=[scene["id"] for scene in scenes],
            decision="review_boundary",
            boundary_fingerprints=fingerprints,
        ),
    )
    resumed = (await resume_reading(db, nid, run["run_key"]))["run"]
    assert resumed["total_scenes"] == 2 and resumed["task_id"] != run["task_id"]
    assert len(calls) == 1 and resumed["budget_remaining"] == 2
