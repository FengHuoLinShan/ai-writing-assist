"""One reusable production-handler scenario; synthetic and paid evidence stay separate."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from infrastructure.tasks.models import AsyncTask
from modules.assistant.forecast import runtime as forecasts
from modules.assistant.forecast import service as forecast_service
from modules.assistant.forecast.contracts import (
    EvaluateRequest,
    FeedRequest,
    FocusRequest,
    Horizon,
)
from modules.assistant.models import AssistantRun
from modules.collaboration import cases, views
from modules.collaboration.contracts import CaseCreate, Grant, RunCreate
from modules.collaboration.facade import read_cognition_records
from modules.collaboration.models import CollaborationRun
from modules.evidence.compilation.contracts import CompileOptions, StructureContextBundle
from modules.evidence.compilation.services.loaders.memory_records_loader import (
    MemoryRecordsLoader,
)
from modules.evidence.facade import collect_creative_manifest
from modules.evolution.facade import switch_project_engine
from modules.evolution.models import EvolutionFrozenAttempt
from modules.evolution.tasks import (
    EvolutionSceneStepRequest,
    enqueue_evolution_scene_step,
)
from modules.story.facade import get_memory_panorama
from modules.story.outline_state.models import Scene
from modules.world.map_atlas_facade import get_map_scene_context
from modules.world.map_structure_schemas import MapDocument, MapNodeCreate, MapSaveRequest
from modules.world.map_structure_service import MapStructureService
from modules.world.models import CoreEntity
from modules.writing.facade import create_draft_only

PROSE = [
    "林舟出现在白石城。青竹说渡口已经封锁。林舟并没有亲眼确认这句话。",
    "三日后，林舟出现在渡口。他没有说明这三日的行程，也没有提起封锁。",
    "林舟在渡口等候。青竹的消息还没有传来。",
]
GOALS = [
    "核对林舟在两地的出现记录，以及他与青竹的知识边界。"
    "区分叙述事实、角色说法和未知行程；保留有依据且可复用的解释。",
    "我准备接着写林舟等候消息。请结合前文查证结果，整理必须保留的事实、"
    "尚待回答的问题，以及两种不预断封锁真伪的局部叙事方向；这次先不写正文。",
]


async def run_reading_slice(db, novel_id, execute, report, checkpoint):
    """Exercise the author entry, actual worker recovery and a later append."""
    from modules.evolution.workflow import (
        ReadingRequest,
        ReadingStart,
        preview_reading,
        reading_status,
        resume_reading,
        start_reading,
    )
    from modules.story import facade as story

    nid = str(novel_id)
    await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
    for index, prose in enumerate(PROSE[:2]):
        await create_draft_only(db, nid, index + 1, f"读取验收 {index + 1}", prose)
        await story.create_scene(
            db, nid, {"scene_index": index, "chapter_ids": [str(index + 1)]}
        )
    await db.commit()
    request = ReadingRequest(operation_id=uuid4(), end_chapter=2, request_limit=2)
    preview = await preview_reading(db, nid, request)
    start = ReadingStart(
        **request.model_dump(),
        expected_fingerprint=preview["fingerprint"],
        authorization_confirmed=True,
    )
    initial = (await start_reading(db, nid, start))["run"]
    key, first_task = initial["run_key"], initial["task_id"]
    duplicate = (await start_reading(db, nid, start))["run"]
    assert duplicate["task_id"] == first_task and duplicate["budget_total"] == 2
    await db.commit()
    original_apply = story.replace_scene_memory_events

    async def interrupt_apply(*args, **kwargs):
        raise RuntimeError("acceptance interruption after durable model result")

    story.replace_scene_memory_events = interrupt_apply
    try:
        await execute(first_task, expected="failed")
    finally:
        story.replace_scene_memory_events = original_apply
    db.expire_all()
    interrupted = (await reading_status(db, nid, key))["run"]
    assert interrupted["can_resume"] and interrupted["budget_remaining"] == 1
    frozen = await db.scalar(
        select(EvolutionFrozenAttempt).where(
            EvolutionFrozenAttempt.novel_id == UUID(nid),
            EvolutionFrozenAttempt.run_key == key,
        )
    )
    attempt_id = frozen.attempt_key
    await resume_reading(db, nid, key)
    await db.commit()
    await execute(first_task)
    db.expire_all()
    first = await db.get(AsyncTask, UUID(first_task))
    assert first.result["attempt_id"] == attempt_id
    next_task = first.result["next_task_id"]
    await db.commit()
    await execute(next_task)
    db.expire_all()
    completed = (await reading_status(db, nid, key))["run"]
    assert completed["status"] == "completed" and completed["budget_remaining"] == 0
    await create_draft_only(db, nid, 3, "后续章节", PROSE[2])
    await story.create_scene(db, nid, {"scene_index": 2, "chapter_ids": ["3"]})
    await db.commit()
    request = ReadingRequest(
        operation_id=uuid4(), mode="append", run_key=key, end_chapter=3, request_limit=1
    )
    preview = await preview_reading(db, nid, request)
    appended = await start_reading(
        db,
        nid,
        ReadingStart(
            **request.model_dump(),
            expected_fingerprint=preview["fingerprint"],
            authorization_confirmed=True,
        ),
    )
    await db.commit()
    await execute(appended["run"]["task_id"])
    db.expire_all()
    final = (await reading_status(db, nid, key))["run"]
    assert final["status"] == "completed" and final["completed_scenes"] == 3
    assert final["budget_total"] == 3 and final["budget_remaining"] == 0
    report.update(
        scenario_version=1,
        initial=initial,
        interrupted=interrupted,
        completed=completed,
        final=final,
        recovered_attempt_id=attempt_id,
        evolution_inputs=[
            row.payload_json
            for row in await db.scalars(
                select(EvolutionFrozenAttempt)
                .where(EvolutionFrozenAttempt.novel_id == UUID(nid))
                .order_by(EvolutionFrozenAttempt.created_at)
            )
        ],
        engineering_checks={
            "sequential_reading": True,
            "free_recovery": True,
            "append_preserves_budget": True,
            "duplicate_start": True,
        },
    )
    checkpoint("reading_verified")


async def run_preparation_slice(db, novel_id, execute, report, checkpoint):
    """Start from prose alone; replay a paid boundary result before reading it."""
    from modules.evolution.store import PostgresAttemptStore
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

    nid = str(novel_id)
    await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
    await create_draft_only(db, nid, 1, "白石城与渡口", "\n\n".join(PROSE[:2]))
    request = ReadingRequest(operation_id=uuid4(), end_chapter=1, request_limit=10)
    preview = await preview_reading(db, nid, request)
    assert preview["scene_count"] is None
    initial = (
        await start_reading(
            db,
            nid,
            ReadingStart(
                **request.model_dump(),
                expected_fingerprint=preview["fingerprint"],
                authorization_confirmed=True,
            ),
        )
    )["run"]
    key, task_id = initial["run_key"], initial["task_id"]
    await db.commit()
    original = imports.commit_scene_boundaries

    async def interrupted_commit(*args, **kwargs):
        raise RuntimeError("acceptance interruption after durable boundary result")

    imports.commit_scene_boundaries = interrupted_commit
    try:
        await execute(task_id, expected="failed")
    finally:
        imports.commit_scene_boundaries = original
    db.expire_all()
    interrupted = (await reading_status(db, nid, key))["run"]
    assert interrupted["can_resume"]
    stored = await PostgresAttemptStore(db, nid).load_run(key)
    frozen_calls = stored.reading_plan_json["preparation"]["calls"]
    await resume_reading(db, nid, key)
    await db.commit()
    await execute(task_id)
    db.expire_all()
    stored = await PostgresAttemptStore(db, nid).load_run(key)
    assert stored.reading_plan_json["preparation"]["calls"] == frozen_calls
    state = (await reading_status(db, nid, key))["run"]
    for _ in range(6):
        if state["status"] == "completed":
            break
        assert state["status"] == "pending", state
        task_id = state["task_id"]
        await db.commit()
        await execute(task_id)
        db.expire_all()
        state = (await reading_status(db, nid, key))["run"]
    assert state["status"] == "completed" and state["total_scenes"] > 0
    assert state["budget_total"] == 10
    stored = await PostgresAttemptStore(db, nid).load_run(key)
    pairs = await PostgresAttemptStore(db, nid).load_committed_pairs(key)
    expected = len(frozen_calls) + sum(
        len(receipt.receipt_json["paid_call_receipts"]) for receipt, _ in pairs
    )
    assert 10 - state["budget_remaining"] == expected
    report.update(
        scenario_version=1,
        initial=initial,
        interrupted=interrupted,
        final=state,
        preparation=stored.reading_plan_json["preparation"],
        scenes=await get_scenes_by_novel(db, nid, status_filter=["draft", "canonical"]),
        evolution_inputs=[
            row.payload_json
            for row in await db.scalars(
                select(EvolutionFrozenAttempt)
                .where(EvolutionFrozenAttempt.novel_id == UUID(nid))
                .order_by(EvolutionFrozenAttempt.created_at)
            )
        ],
        expected_transport_calls=expected,
        engineering_checks={
            "prose_only_start": True,
            "frozen_boundary_recovery": True,
            "same_root_budget": True,
            "sequential_reading": True,
        },
    )
    checkpoint("preparation_verified")


async def run_slice(db, novel_id, execute, report, checkpoint):
    """execute runs the exact queued task; it never supplies a model answer."""
    nid = str(novel_id)
    await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
    people = [
        CoreEntity(
            novel_id=UUID(nid), entity_type="character", name=name, status="canonical"
        )
        for name in ("林舟", "青竹")
    ]
    scenes = [
        Scene(
            novel_id=UUID(nid),
            scene_index=index,
            chapter_ids=[index + 1],
            scene_chunks=[],
            title=f"观察场景 {index + 1}",
            status="draft",
        )
        for index in range(2)
    ]
    db.add_all([*people, *scenes])
    await db.flush()
    scene_ids = [str(scene.id) for scene in scenes]
    drafts = [
        await create_draft_only(db, nid, index + 1, f"纵切 {index + 1}", prose)
        for index, prose in enumerate(PROSE)
    ]
    atlas = MapStructureService()
    node = await atlas.create_node(db, nid, MapNodeCreate(title="纵切人物地图"))
    await atlas.save(
        db,
        nid,
        node["id"],
        MapSaveRequest(
            base_revision_id=node["current_revision_id"],
            document=MapDocument.model_validate(
                {
                    "features": [
                        {
                            "id": f"place{index}",
                            "kind": "location",
                            "label": name,
                            "points": [{"x": index * 100, "y": 0}],
                        }
                        for index, name in enumerate(("白石城", "渡口"))
                    ]
                }
            ),
        ),
    )
    await db.commit()
    report.update(
        novel_id=nid,
        draft_ids=[draft.id for draft in drafts],
        scene_ids=scene_ids,
        scenario_version=2,
    )
    checkpoint("sources_ready")
    for index, scene_id in enumerate(scene_ids):
        task = await enqueue_evolution_scene_step(
            db,
            EvolutionSceneStepRequest(
                novel_id=nid,
                run_key="v4-vertical-slice",
                scene_index=index,
                scene_id=scene_id,
                chapter_index=index + 1,
                scene_text=PROSE[index],
                budget_total=4,
            ),
        )
        await db.commit()
        await execute(task["task_id"])
        db.expire_all()
        task_row = await db.get(AsyncTask, UUID(task["task_id"]))
        report.setdefault("evolution_tasks", []).append(
            {"id": str(task_row.id), "status": task_row.status, "result": task_row.result}
        )
        await db.commit()
        checkpoint(f"scene_{index}_finished")
    report["evolution_inputs"] = [
        row.payload_json
        for row in (
            await db.scalars(
                select(EvolutionFrozenAttempt)
                .where(EvolutionFrozenAttempt.novel_id == UUID(nid))
                .order_by(EvolutionFrozenAttempt.created_at)
            )
        ).all()
    ]
    grant = Grant(
        resources=[{"kind": "writing_draft", "id": draft.id} for draft in drafts[:2]],
        retain_understanding=True,
        expires_at=datetime.now(UTC) + timedelta(hours=4),
    )
    for index in range(2):
        created = await cases.create_case(
            db,
            nid,
            CaseCreate(
                operation_id=uuid4(),
                goal=GOALS[index],
                constraints=[
                    "不能据两次出现虚构中间路线。",
                    "青竹的说法不等于封锁的客观事实。",
                ],
                grant=grant,
                recipe_id="deep_review",
            ),
        )
        submitted = await cases.submit_run(
            db,
            nid,
            created["id"],
            RunCreate(operation_id=uuid4(), expected_goal_version=1),
        )
        await db.commit()
        await execute(submitted["task_id"])
        db.expire_all()
        run = await db.get(CollaborationRun, UUID(submitted["run_id"]))
        report.setdefault("cases", []).append(
            {
                "id": created["id"],
                "goal": GOALS[index],
                "run_id": str(run.id),
                "manifest": run.manifest_json,
                "result": run.result_json,
                "view": await views.run_view(db, nid, str(run.id)),
            }
        )
        await db.commit()
        checkpoint(f"independent_case_{index + 1}_finished")
    records = await read_cognition_records(db, nid)
    report["cognition"] = [
        {
            "record_id": str(row.record_id),
            "revision_id": str(row.id),
            "content": row.content_json,
            "evolution_refs": row.evolution_refs_json,
        }
        for row in records
    ]
    focus = FocusRequest(
        client_context_id=uuid4(),
        focus_seq=0,
        page="writing",
        draft_id=drafts[2].id,
        expected_source_hash=drafts[2].content_hash,
        task_hint="review",
        explicit_instruction="给出基于前文理解的局部方向；保留行程与封锁是否真实的未知。",
    )
    submission = await forecasts.submit(
        db,
        nid,
        EvaluateRequest(
            operation_id=uuid4(),
            context=focus,
            horizon=Horizon(unit="scene"),
            requested_capabilities=["writing.next_beat.v1"],
        ),
    )
    forecast_run = await db.get(AssistantRun, submission.run_id)
    task_id = str(forecast_run.task_id)
    await db.commit()
    await execute(task_id)
    db.expire_all()
    forecast_run = await db.get(AssistantRun, submission.run_id)
    report["forecast"] = {
        "run_id": str(submission.run_id),
        "manifest": forecast_run.request_json,
        "view": (await forecasts.view(db, nid, submission.run_id)).model_dump(
            mode="json"
        ),
        "feed": (
            await forecast_service.feed(db, nid, FeedRequest(context=focus))
        ).model_dump(mode="json"),
    }
    report["map"] = (
        await get_map_scene_context(db, nid, node["id"], scene_ids[1])
    ).model_dump(mode="json")
    report["panorama"] = (await get_memory_panorama(db, nid, 2)).model_dump(mode="json")
    bundle = StructureContextBundle(novel_id=nid, task="纵切验收", scope="chapter")
    await MemoryRecordsLoader().load(
        db,
        CompileOptions(novel_id=nid, chapter_index=2, task="纵切验收", scope="chapter"),
        bundle,
    )
    report["memory_evidence"] = bundle.memory_records
    await db.commit()
    checkpoint("consumers_finished")
    # A real source save must revoke all affected views; no manual invalidation helper.
    await create_draft_only(
        db, nid, 1, "纵切 1（修订）", "林舟没有到白石城，也没有听见青竹的消息。"
    )
    await db.commit()
    report["after_source_change"] = {
        "case": await views.run_view(db, nid, report["cases"][1]["run_id"]),
        "map": (
            await get_map_scene_context(db, nid, node["id"], scene_ids[1])
        ).model_dump(mode="json"),
        "forecast_feed": (
            await forecast_service.feed(db, nid, FeedRequest(context=focus))
        ).model_dump(mode="json"),
    }
    refreshed_grant = grant.model_copy(update={"resources": [grant.resources[1]]})
    current = await collect_creative_manifest(db, nid, refreshed_grant, 1)
    report["after_source_change"]["cognition"] = current.cognition.model_dump(mode="json")
    report["after_source_change"]["evolution"] = [
        ref.model_dump(mode="json") for ref in current.evolution
    ]
    await db.commit()
    checkpoint("source_change_checked")


def engineering_checks(report):
    cases = report.get("cases", [])
    later = report.get("after_source_change", {})
    return {
        "two_committed_scenes": len(report.get("evolution_tasks", [])) == 2
        and all(row["status"] == "done" for row in report["evolution_tasks"]),
        "independent_cases": len(cases) == 2
        and cases[0]["id"] != cases[1]["id"]
        and cases[0].get("goal") != cases[1].get("goal")
        and all(case["view"]["status"] == "completed" for case in cases),
        "case_reads_evolution": bool(cases and cases[0]["manifest"].get("evolution")),
        "second_case_reads_cognition": bool(
            len(cases) == 2 and cases[1]["manifest"].get("cognition", {}).get("records")
        ),
        "forecast_reads_cognition": bool(
            report.get("forecast", {})
            .get("manifest", {})
            .get("understanding_manifest", {})
            .get("records")
        )
        and report["forecast"]["view"]["status"] == "completed",
        "map_has_grounded_history": bool(report.get("map", {}).get("history")),
        "panorama_and_evidence_readable": bool(
            report.get("panorama", {}).get("character_locations")
        )
        and bool(report.get("memory_evidence")),
        "source_change_invalidates_case": later.get("case", {}).get("stale") is True,
        "source_change_invalidates_cognition": later.get("cognition", {}).get("records")
        == [],
        "source_change_invalidates_map": later.get("map", {}).get("history") == [],
        "source_change_invalidates_forecast": bool(
            report.get("forecast", {}).get("feed", {}).get("items")
        )
        and later.get("forecast_feed", {}).get("items") == [],
    }


async def run_world_slice(db, novel_id, execute, report, checkpoint):
    """Proxy acceptance of two real Scenes; no claim of a human author trial."""
    from modules.evolution.store import PostgresAttemptStore
    from modules.evolution.workflow import (
        ReadingRequest,
        ReadingStart,
        preview_reading,
        reading_status,
        start_reading,
    )
    from modules.story.facade import create_scene
    from modules.world.models import EntityRelation

    nid = str(novel_id)
    prose = ["林舟又名小舟。林舟和青竹是盟友。林舟在白石城。青竹是一名医生。", PROSE[1]]
    report.update(
        acceptance_type="代理验收，非人工试用",
        world_scenario_version=2,
        source_prose=prose,
        fixture_scope="两章已确认完整场景，只验World主链，不替代边界切分验收",
    )
    await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
    for index, content in enumerate(prose):
        await create_draft_only(db, nid, index + 1, f"世界理解验收{index + 1}", content)
        await create_scene(
            db, nid, {"scene_index": index, "chapter_ids": [str(index + 1)]}
        )
    await db.commit()
    request = ReadingRequest(operation_id=uuid4(), end_chapter=2, request_limit=12)
    preview = await preview_reading(db, nid, request)
    state = (
        await start_reading(
            db,
            nid,
            ReadingStart(
                **request.model_dump(),
                expected_fingerprint=preview["fingerprint"],
                authorization_confirmed=True,
            ),
        )
    )["run"]
    key = state["run_key"]
    report["run_key"] = key
    await db.commit()
    try:
        for _ in range(2):
            assert state["status"] == "pending", state
            await execute(state["task_id"])
            db.expire_all()
            state = (await reading_status(db, nid, key))["run"]
            await db.commit()
        assert state["status"] == "completed", state
    finally:
        db.expire_all()
        store = PostgresAttemptStore(db, nid)
        run = await store.load_run(key)
        pairs = await store.load_committed_pairs(key)
        frozen = list(
            await db.scalars(
                select(EvolutionFrozenAttempt)
                .where(
                    EvolutionFrozenAttempt.novel_id == UUID(nid),
                    EvolutionFrozenAttempt.run_key == key,
                )
                .order_by(EvolutionFrozenAttempt.created_at)
            )
        )
        entities = list(
            await db.scalars(select(CoreEntity).where(CoreEntity.novel_id == UUID(nid)))
        )
        relations = list(
            await db.scalars(
                select(EntityRelation).where(EntityRelation.novel_id == UUID(nid))
            )
        )
        report.update(
            world_frozen=[item.payload_json for item in frozen],
            receipts=[item.receipt_json for item, _ in pairs],
            world_entities=[
                {
                    "id": str(item.id),
                    "name": item.name,
                    "status": item.status,
                    "summary": item.summary,
                    "public_info": item.public_info,
                    "hidden_truth": item.hidden_truth,
                    "content_json": item.content_json,
                }
                for item in entities
            ],
            world_relations=[
                {
                    "id": str(item.id),
                    "status": item.status,
                    "description": item.description,
                    "review_meta": item.review_meta,
                }
                for item in relations
            ],
            budget_remaining=run.budget_remaining,
        )
        checkpoint("world_evidence_preserved")
    report["expected_transport_calls"] = sum(
        len(item.receipt_json["paid_call_receipts"]) for item, _ in pairs
    )
    assert report["expected_transport_calls"] == run.budget_total - run.budget_remaining
    assert len(pairs) == 2 and entities
    assert all(item.status == "candidate" for item in [*entities, *relations])
    assert (
        frozen[0].attempt_key
        == frozen[1].payload_json["input_manifest"]["previous_scene_attempt_id"]
    )
    assert frozen[0].attempt_key in json.dumps(
        frozen[1].payload_json["world_preparation"]["call"], ensure_ascii=False
    )
    from modules.story.facade import project_scene_presence

    presence = await project_scene_presence(db, nid, through_scene_index=1)
    report["presence"] = presence.model_dump(mode="json")
    checkpoint("world_presence_preserved")
    person = next(item for item in entities if item.name == "林舟")
    nodes = [item for item in presence.nodes if item.character_id == str(person.id)]
    assert {(item.scene_index, item.location) for item in nodes} == {
        (0, "白石城"),
        (1, "渡口"),
    }
    assert all(item.status == "unknown" for item in presence.segments)
