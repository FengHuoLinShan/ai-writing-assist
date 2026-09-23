"""Structure batches keep the Scene prefix, budget and free recovery contract."""

import json
from uuid import UUID

import pytest
from sqlalchemy import select

from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.tasks.models import AsyncTask
from modules.evolution.store import BudgetExhaustedError, PostgresAttemptStore
from modules.evolution.structure import prepare_structure
from modules.evolution.tasks import handle_evolution_scene_step
from modules.evolution.tests.test_workflow import request_start, seed
from modules.evolution.workflow import start_reading
from modules.story.outline_state.models import PlotThread


@pytest.mark.parametrize("failure", [None, "domain", "budget", "source"])
async def test_structure_frozen_calls_and_drafts_share_the_reading_owner(
    db_session, evolution_project_id, account_llm_connection, monkeypatch, failure
):
    from modules.story import facade as story
    from modules.writing.facade import create_draft_only

    db, nid = db_session, evolution_project_id
    texts = ["林舟在城门等候。", "三日后，林舟仍在等待。"]
    for index, prose in enumerate(texts, 1):
        await seed(db, nid, index, prose)
    calls = []

    async def provider(self, request):
        assert not db.in_transaction()
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])["title"]
        prompt = next(item.content for item in request.messages if item.role == "user")
        calls.append(schema)
        if schema == "SceneSample":
            quote = prompt.splitlines()[1]
            result = {"observations": [{"predicate": quote, "quote": quote}]}
        elif schema == "Phase2aSceneExtractionOutput":
            result = {}
        elif schema == "SimpleStructureOutput":
            cards = json.loads(
                prompt.split("【Scene卡片 JSON】\n", 1)[1].split("\n\n", 1)[0]
            )
            result = {
                "plot_threads": [
                    {
                        "title": "等待",
                        "summary": "林舟持续等待。",
                        "confidence": 0.95,
                        "supporting_scene_ids": [item["scene_id"] for item in cards],
                    }
                ]
            }
            if failure == "source":
                await create_draft_only(db, nid, 1, "改稿", "林舟已经离开。")
                await db.commit()
        else:
            assert schema == "StructureEvidenceReviewOutput"
            units = json.loads(prompt)["review_items"]
            result = {
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
        return LLMCallResponse(
            content=json.dumps(result),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    run = (
        await start_reading(
            db,
            nid,
            await request_start(
                db,
                nid,
                end_chapter=2,
                request_limit=5 if failure == "budget" else 10,
            ),
        )
    )["run"]
    task_id = run["task_id"]
    for _ in range(2):
        task = await db.get(AsyncTask, UUID(task_id))
        result = await handle_evolution_scene_step(db, task)
        task.status = "done"
        task_id = result.get("next_task_id")
        await db.commit()
    store = PostgresAttemptStore(db, nid)
    prefix = (await store.load_head_receipt(run["run_key"])).model_dump()
    original = story.persist_reading_structure_drafts
    if failure == "domain":

        async def broken(*args, **kwargs):
            await original(*args, **kwargs)
            raise RuntimeError("structure domain rollback")

        monkeypatch.setattr(story, "persist_reading_structure_drafts", broken)
        with pytest.raises(RuntimeError, match="domain rollback"):
            await prepare_structure(db, nid, run["run_key"])
        await db.rollback()
        assert not (await db.scalars(select(PlotThread))).all()
        monkeypatch.setattr(story, "persist_reading_structure_drafts", original)
    elif failure == "budget":
        with pytest.raises(BudgetExhaustedError):
            await prepare_structure(db, nid, run["run_key"])
        await db.rollback()
        current = await store.load_run(run["run_key"])
        assert (
            current.reading_plan_json["structure"]["current"]["calls"]["generate"][
                "stage"
            ]
            == "sampled"
        )
        current.budget_total += 1
        current.budget_remaining += 1
        await db.commit()
    elif failure == "source":
        from core.errors import ConflictError

        with pytest.raises(ConflictError):
            await prepare_structure(db, nid, run["run_key"])
        await db.rollback()
        assert calls.count("SimpleStructureOutput") == 1
        assert not (await db.scalars(select(PlotThread))).all()
        return
    await prepare_structure(db, nid, run["run_key"])
    await prepare_structure(db, nid, run["run_key"])
    assert calls.count("SimpleStructureOutput") == 1
    assert calls.count("StructureEvidenceReviewOutput") == 1
    assert (await store.load_head_receipt(run["run_key"])).model_dump() == prefix
    current = await store.load_run(run["run_key"])
    stage = current.reading_plan_json["structure"]
    assert stage["complete"] and len(stage["batches"]) == 1
    drafts = (await db.scalars(select(PlotThread))).all()
    assert len(drafts) == 1 and drafts[0].status == "draft"
    assert drafts[0].provenance_meta["needs_review"]
    assert stage["batches"][0]["result_refs"][0]["id"] == str(drafts[0].id)
    if failure in {None, "domain"}:
        from core.errors import ConflictError
        from modules.story.outline_state.schemas import PlotThreadUpdate
        from modules.story.outline_state.services import PlotThreadService

        service = PlotThreadService()
        draft_id = str(drafts[0].id)
        source_ref = drafts[0].provenance_meta["evolution_structure_ref"]
        await service.update(
            db,
            draft_id,
            PlotThreadUpdate(
                provenance_meta={"evolution_structure_ref": None},
            ),
            novel_id=nid,
        )
        assert drafts[0].provenance_meta["evolution_structure_ref"] == source_ref
        if failure == "domain":
            await service.update(
                db, draft_id, PlotThreadUpdate(status="canonical"), novel_id=nid
            )
        await db.commit()
        await create_draft_only(db, nid, 1, "改稿", "林舟早已离开。")
        await db.commit()
        if failure is None:
            with pytest.raises(ConflictError, match="来源已变化"):
                await service.update(
                    db,
                    draft_id,
                    PlotThreadUpdate(
                        provenance_meta={"needs_review": False},
                    ),
                    novel_id=nid,
                )
        else:
            # An already adopted author's structure is not locked to its old draft.
            await service.update(
                db, draft_id, PlotThreadUpdate(summary="作者的新说明"), novel_id=nid
            )
