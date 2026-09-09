"""Real Imports -> focused Evidence -> World adoption, with provider-only fakes."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from infrastructure.tasks.models import AsyncTask
from modules.imports.orchestrator import DeepImportOrchestrator
from modules.imports.workflow_runs import ImportWorkflowRunService
from modules.world.facade import initialize_world_canon
from modules.world.models import CoreEntity, CreationSuggestion
from modules.writing.facade import create_published_draft_only
from tests.utils import _create_entity


@pytest.fixture
def provider(monkeypatch, db_session):
    calls = []
    state = {
        "fail_completion_once": False,
        "failed": False,
        "fail_at": None,
        "completion_calls": 0,
        "links": False,
    }

    async def structured(client, request, schema, **kwargs):
        assert not db_session.in_transaction(), "provider I/O held a DB transaction"
        payload = json.loads(request.messages[1].content)
        calls.append({"step": kwargs["step_name"], "payload": payload})
        if kwargs["step_name"] == "evidence.focused_neighbors":
            if state.get("fail_nomination"):
                raise TimeoutError("deterministic nomination interruption")
            neighbors = []
            for root in payload["roots"]:
                if root["name"] != "青港":
                    continue
                for evidence in payload["evidence"]:
                    if "青港的东边是长桥" in evidence["text"]:
                        neighbors.append(
                            {
                                "root_key": root["key"],
                                "evidence_key": evidence["key"],
                                "name": "长桥",
                                "relation": "东边",
                                "quote": "青港的东边是长桥",
                            }
                        )
            return schema.model_validate({"neighbors": neighbors})
        assert kwargs["step_name"] == "imports.targeted_completion.structured"
        assert request.max_tokens == 32_768
        assert kwargs["timeout"] == 600
        state["completion_calls"] += 1
        if (
            state["fail_completion_once"] or state["fail_at"] == state["completion_calls"]
        ) and not state["failed"]:
            state["failed"] = True
            raise TimeoutError("deterministic provider interruption")
        entities = []
        claims = {
            "青港": ("青港坐落在北岸。", "坐落在北岸。"),
            "长桥": ("长桥是一座石桥。", "是一座石桥。"),
            "古塔": ("古塔是一座圆塔。", "是一座圆塔。"),
        }
        for target in payload["targets"]:
            if target["key"] not in payload["requested_target_keys"]:
                continue
            quote, summary = claims.get(target["name"], ("", ""))
            hit = next(
                (
                    item
                    for item in payload["evidence"]
                    if item.get("source_ref") and quote and quote in item["text"]
                ),
                None,
            )
            if hit is None:
                continue
            evidence = [{"evidence_key": hit["key"], "quote": quote}]
            entities.append(
                {
                    "target_key": target["key"],
                    "entity_type": "location",
                    "summary": summary,
                    "confidence": 0.98,
                    "certainty": "explicit",
                    "uncertainties": [],
                    "field_evidence": {
                        "name": evidence,
                        "entity_type": evidence,
                        "summary": evidence,
                    },
                }
            )
        relations, aliases = [], []
        if state["links"]:
            by_name = {target["name"]: target["key"] for target in payload["targets"]}
            for evidence in payload["evidence"]:
                if "青港的东边是长桥" in evidence["text"] and {"青港", "长桥"}.issubset(
                    by_name
                ):
                    relations.append(
                        {
                            "source_key": by_name["青港"],
                            "target_key": by_name["长桥"],
                            "relation_type": "东边",
                            "relation_kind": "spatial",
                            "description": "青港的东边是长桥",
                            "confidence": 0.98,
                            "certainty": "explicit",
                            "evidence": [
                                {
                                    "evidence_key": evidence["key"],
                                    "quote": "青港的东边是长桥",
                                }
                            ],
                        }
                    )
                if "青港又名北港" in evidence["text"] and "青港" in by_name:
                    aliases.append(
                        {
                            "target_key": by_name["青港"],
                            "alias": "北港",
                            "alias_kind": "name",
                            "alias_type": "别称",
                            "confidence": 0.98,
                            "certainty": "explicit",
                            "evidence": [
                                {"evidence_key": evidence["key"], "quote": "青港又名北港"}
                            ],
                        }
                    )
        return schema.model_validate(
            {"entities": entities, "relations": relations, "aliases": aliases}
        )

    async def embed(*args, **kwargs):
        return []

    async def no_network(*args, **kwargs):
        pytest.fail("an unmocked provider tried to access the network")

    monkeypatch.setattr(
        "infrastructure.llm.agent_step_harness.run_managed_structured", structured
    )
    monkeypatch.setattr(
        "modules.evidence.compilation.services.focused_evidence.run_managed_structured",
        structured,
    )
    monkeypatch.setattr("infrastructure.llm.client.LLMClient.generate_embedding", embed)
    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", no_network)
    return calls, state


async def prepare(db, novel_id, targets, chapters):
    await initialize_world_canon(db, novel_id)
    for chapter, text in enumerate(chapters, 1):
        await create_published_draft_only(db, novel_id, chapter, content=text)
    orchestrator = DeepImportOrchestrator()
    submitted = await orchestrator.start_targeted_completion(
        db,
        novel_id=novel_id,
        targets=targets,
        start_chapter=1,
        end_chapter=len(chapters),
        authorization_confirmed=True,
    )
    task = await db.get(AsyncTask, uuid.UUID(submitted["task_id"]))
    task.mark_running()
    await db.flush()
    attempt = await ImportWorkflowRunService().claim_attempt(
        db,
        task_id=str(task.id),
        workflow_type=task.task_type,
        attempt=task.attempt,
        lease_id=task.lease_id,
    )
    return orchestrator, task, attempt


async def execute(db, orchestrator, task, attempt):
    from modules.imports.tasks import _project_task

    return await orchestrator.run_attempt(
        db,
        attempt,
        project=lambda result, progress: _project_task(task, result, progress),
    )


async def test_real_domains_fill_existing_and_replay_does_not_apply_again(
    db_session, test_project_id, account_llm_connection, provider
):
    city = await _create_entity(db_session, test_project_id, "location", "青港")
    orchestrator, task, attempt = await prepare(
        db_session, test_project_id, [{"entity_id": str(city.id)}], ["青港坐落在北岸。"]
    )
    result = await execute(db_session, orchestrator, task, attempt)
    await db_session.refresh(city)
    assert city.summary == "坐落在北岸。", result
    assert result["targeted_completion"]["status"] == "done"
    assert result["targeted_completion"]["filled"] == 1
    calls_before = len(provider[0])
    # The actual import task view restores checkpoint state; this is a domain
    # resume before worker terminal CAS, not an alternate mocked write path.
    replay = await orchestrator.run_stage_task(
        db_session, task, stage="targeted_completion"
    )
    assert replay["targeted_completion"]["filled"] == 1
    assert len(provider[0]) == calls_before
    accepted = (
        await db_session.scalars(
            select(CreationSuggestion).where(
                CreationSuggestion.novel_id == city.novel_id,
                CreationSuggestion.target_type == "world_adoption_package",
                CreationSuggestion.status == "accepted",
            )
        )
    ).all()
    assert len(accepted) == 1

    from modules.evidence.facade import list_context_snapshots

    snapshots = await list_context_snapshots(
        db_session, novel_id=test_project_id, workflow_id=str(task.id)
    )
    snapshots = [item for item in snapshots if item.prompt_name == "targeted_completion"]
    assert snapshots and all(item.status == "succeeded" for item in snapshots)
    assert all(item.rendered_context is None for item in snapshots)
    assert any(
        ref["id"] == str(city.id) for item in snapshots for ref in item.result_refs
    )


async def test_real_domains_create_unregistered_name(
    db_session, test_project_id, account_llm_connection, provider
):
    orchestrator, task, attempt = await prepare(
        db_session, test_project_id, [{"name": "古塔"}], ["古塔是一座圆塔。"]
    )
    result = await execute(db_session, orchestrator, task, attempt)
    entities = (
        await db_session.scalars(
            select(CoreEntity).where(
                CoreEntity.novel_id == uuid.UUID(test_project_id),
                CoreEntity.name == "古塔",
            )
        )
    ).all()
    assert len(entities) == 1, result
    assert entities[0].summary == "是一座圆塔。"
    assert entities[0].status == "canonical"


async def test_real_domains_new_one_hop_neighbor_uses_its_own_later_paragraph(
    db_session, test_project_id, account_llm_connection, provider
):
    city = await _create_entity(db_session, test_project_id, "location", "青港")
    orchestrator, task, attempt = await prepare(
        db_session,
        test_project_id,
        [{"entity_id": str(city.id)}],
        [
            "青港坐落在北岸。青港的东边是长桥。",
            "长桥是一座石桥。长桥通往城楼。",
            "城楼在山顶。",
        ],
    )
    result = await execute(db_session, orchestrator, task, attempt)
    entities = (
        await db_session.scalars(
            select(CoreEntity).where(
                CoreEntity.novel_id == uuid.UUID(test_project_id),
            )
        )
    ).all()
    bridge = next((entity for entity in entities if entity.name == "长桥"), None)
    assert bridge and bridge.summary == "是一座石桥。", result
    assert not any(entity.name == "城楼" for entity in entities)
    state = result["checkpoints"]["targeted_completion"]
    assert state["status"] == "done" and state["coverage"]["complete"]
    assert state["root_position"] == 1
    assert any(
        "长桥是一座石桥。" in str(call["payload"])
        for call in provider[0]
        if call["step"].startswith("imports.")
    )


async def test_real_domains_partial_provider_failure_preserves_roots_for_resume(
    db_session, test_project_id, account_llm_connection, provider, async_client
):
    city = await _create_entity(db_session, test_project_id, "location", "青港")
    orchestrator, task, attempt = await prepare(
        db_session, test_project_id, [{"entity_id": str(city.id)}], ["青港坐落在北岸。"]
    )
    provider[1]["fail_completion_once"] = True
    with pytest.raises(TimeoutError, match="deterministic"):
        await execute(db_session, orchestrator, task, attempt)
    stored = task.result["checkpoints"]["targeted_completion"]
    assert stored["status"] == "partial" and stored["roots"]
    assert stored["root_position"] == 0 and city.summary is None
    from infrastructure.tasks.lifecycle import TaskLifecycleService
    from infrastructure.tasks.worker import _handler_failure_result

    assert task.meta["recovery_required"] is True
    assert task.result["recovery_required"] is True
    await TaskLifecycleService().finalize(
        db_session,
        task_id=task.id,
        lease_id=task.lease_id,
        status="failed",
        result_data=_handler_failure_result(task, requeued=False),
        error_message="provider failed",
    )
    await db_session.refresh(task)
    status = await async_client.get(
        f"/api/tasks/{task.id}", params={"novel_id": test_project_id}
    )
    assert status.status_code == 200
    assert status.json()["available_actions"] == ["resume", "abandon"]
    resumed = await async_client.post(
        "/api/imports/deep/resume",
        json={"task_id": str(task.id)},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resumed.status_code == 201, resumed.text
    await db_session.refresh(task)
    assert task.status == "pending"
    task.mark_running()
    await db_session.flush()
    restored = await ImportWorkflowRunService().claim_attempt(
        db_session,
        task_id=str(task.id),
        workflow_type=task.task_type,
        attempt=task.attempt,
        lease_id=task.lease_id,
    )
    result = await execute(db_session, orchestrator, task, restored)
    await db_session.refresh(city)
    assert (
        city.summary == "坐落在北岸。"
        and result["targeted_completion"]["status"] == "done"
    )


async def test_real_domains_defer_links_until_new_neighbor_is_created(
    db_session, test_project_id, account_llm_connection, provider
):
    from modules.world.models import EntityRelation

    city = await _create_entity(db_session, test_project_id, "location", "青港")
    provider[1]["links"] = True
    orchestrator, task, attempt = await prepare(
        db_session,
        test_project_id,
        [{"entity_id": str(city.id)}],
        ["青港坐落在北岸。青港又名北港。青港的东边是长桥。", "长桥是一座石桥。"],
    )
    result = await execute(db_session, orchestrator, task, attempt)
    await db_session.refresh(city)
    bridge = await db_session.scalar(
        select(CoreEntity).where(
            CoreEntity.novel_id == city.novel_id, CoreEntity.name == "长桥"
        )
    )
    assert bridge is not None and bridge.status == "canonical", result
    edge = await db_session.scalar(
        select(EntityRelation).where(
            EntityRelation.novel_id == city.novel_id,
            EntityRelation.source_id == city.id,
            EntityRelation.target_id == bridge.id,
        )
    )
    assert edge is not None and edge.status == "canonical", result
    assert city.content_json["aliases"][0]["alias"] == "北港"
    assert result["checkpoints"]["targeted_completion"].get("pending_links", []) == []


async def test_real_domains_partial_after_root_write_keeps_unread_neighbor_and_receipts(
    db_session, test_project_id, account_llm_connection, provider
):
    city = await _create_entity(db_session, test_project_id, "location", "青港")
    provider[1]["fail_at"] = 2
    orchestrator, task, attempt = await prepare(
        db_session,
        test_project_id,
        [{"entity_id": str(city.id)}],
        ["青港坐落在北岸。青港的东边是长桥。", "长桥是一座石桥。"],
    )
    with pytest.raises(TimeoutError, match="deterministic"):
        await execute(db_session, orchestrator, task, attempt)
    await db_session.refresh(city)
    assert city.summary == "坐落在北岸。"
    state = task.result["checkpoints"]["targeted_completion"]
    assert state["packages"] and state["continuation"] and state["root_position"] == 0
    assert state["status"] == "partial"
    restored = await ImportWorkflowRunService().claim_attempt(
        db_session,
        task_id=str(task.id),
        workflow_type=task.task_type,
        attempt=task.attempt,
        lease_id=task.lease_id,
    )
    result = await execute(db_session, orchestrator, task, restored)
    assert result["targeted_completion"]["filled"] == 1
    assert result["targeted_completion"]["created"] == 1
    root_completions = [
        call
        for call in provider[0]
        if call["step"].startswith("imports.")
        and any(
            target["name"] == "青港"
            and target["key"] in call["payload"]["requested_target_keys"]
            for target in call["payload"]["targets"]
        )
    ]
    assert len(root_completions) == 1


async def test_real_rollback_revokes_resume_even_when_undo_has_conflicts(
    db_session, test_project_id, account_llm_connection, provider
):
    from modules.imports.targeted_completion import rollback_targeted_completion

    city = await _create_entity(db_session, test_project_id, "location", "青港")
    orchestrator, task, attempt = await prepare(
        db_session, test_project_id, [{"entity_id": str(city.id)}], ["青港坐落在北岸。"]
    )
    result = await execute(db_session, orchestrator, task, attempt)
    task.mark_done(result)
    city.summary = "作者后续改动"
    await db_session.flush()
    rollback = await rollback_targeted_completion(
        db_session, novel_id=test_project_id, task_id=str(task.id)
    )
    assert rollback["status"] == "partial" and rollback["conflicts"] == 1
    with pytest.raises(ValueError, match="已开始撤销"):
        await orchestrator.resume_interrupted(db_session, str(task.id))
    assert city.summary == "作者后续改动"
    retry = await rollback_targeted_completion(
        db_session, novel_id=test_project_id, task_id=str(task.id)
    )
    assert retry["status"] == "partial"


async def test_http_submission_freezes_authorization_and_real_worker_applies(
    async_client, db_session, test_project_id, account_llm_connection, provider
):
    await initialize_world_canon(db_session, test_project_id)
    await create_published_draft_only(
        db_session, test_project_id, 1, content="古塔是一座圆塔。"
    )
    body = {
        "novel_id": uuid.UUID(test_project_id).hex,
        "targets": [{"name": "古塔"}],
        "start_chapter": 1,
        "end_chapter": 1,
        "authorization_confirmed": True,
    }
    response = await async_client.post("/api/imports/targeted-completions", json=body)
    assert response.status_code == 201, response.text
    task_id = response.json()["task_id"]
    task = await db_session.get(AsyncTask, uuid.UUID(task_id))
    run = await ImportWorkflowRunService().get_by_task(db_session, task_id=task_id)
    assert run.authorization_snapshot["targeted_completion"]["authorization_id"]
    task.mark_running()
    await db_session.flush()
    attempt = await ImportWorkflowRunService().claim_attempt(
        db_session,
        task_id=task_id,
        workflow_type="targeted_completion",
        attempt=task.attempt,
        lease_id=task.lease_id,
    )
    result = await execute(db_session, DeepImportOrchestrator(), task, attempt)
    task.mark_done(result)
    await db_session.flush()
    response = await async_client.post(
        f"/api/imports/targeted-completions/{task_id}/rollback",
        params={"novel_id": uuid.UUID(test_project_id).hex},
        json={"confirmed": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rolled_back"
    entity = await db_session.scalar(
        select(CoreEntity).where(
            CoreEntity.novel_id == uuid.UUID(test_project_id), CoreEntity.name == "古塔"
        )
    )
    assert entity.status == "deprecated"


async def test_nomination_failure_stops_once_and_retains_real_continuation(
    db_session, test_project_id, account_llm_connection, provider
):
    city = await _create_entity(db_session, test_project_id, "location", "青港")
    provider[1]["fail_nomination"] = True
    orchestrator, task, attempt = await prepare(
        db_session,
        test_project_id,
        [{"entity_id": str(city.id)}],
        ["青港坐落在北岸。青港的东边是长桥。", "长桥是一座石桥。"],
    )
    with pytest.raises(RuntimeError, match="直接关联对象查读未完成"):
        await execute(db_session, orchestrator, task, attempt)
    state = task.result["checkpoints"]["targeted_completion"]
    assert state["status"] == "partial" and state["continuation"]["pending_nomination"]
    assert sum(call["step"] == "evidence.focused_neighbors" for call in provider[0]) == 1
    provider[1]["fail_nomination"] = False
    restored = await ImportWorkflowRunService().claim_attempt(
        db_session,
        task_id=str(task.id),
        workflow_type=task.task_type,
        attempt=task.attempt,
        lease_id=task.lease_id,
    )
    result = await execute(db_session, orchestrator, task, restored)
    assert result["targeted_completion"]["status"] == "done"
    assert result["targeted_completion"]["filled"] == 1
    assert result["targeted_completion"]["created"] == 1


async def test_real_database_neighbor_uses_canonical_edge_and_independent_text(
    db_session, test_project_id, account_llm_connection, provider
):
    from modules.world.models import EntityRelation

    city = await _create_entity(db_session, test_project_id, "location", "青港")
    bridge = await _create_entity(db_session, test_project_id, "location", "长桥")
    db_session.add(
        EntityRelation(
            novel_id=city.novel_id,
            source_id=city.id,
            target_id=bridge.id,
            status="canonical",
            relation_kind="spatial",
            relation_type="相邻",
        )
    )
    await db_session.flush()
    orchestrator, task, attempt = await prepare(
        db_session,
        test_project_id,
        [{"entity_id": str(city.id)}],
        ["青港坐落在北岸。", "长桥是一座石桥。"],
    )
    result = await execute(db_session, orchestrator, task, attempt)
    await db_session.refresh(bridge)
    assert bridge.summary == "是一座石桥。", result
    assert result["targeted_completion"]["filled"] == 2
    accepted = (
        await db_session.scalars(
            select(CreationSuggestion).where(
                CreationSuggestion.novel_id == city.novel_id,
                CreationSuggestion.target_type == "world_adoption_package",
                CreationSuggestion.status == "accepted",
            )
        )
    ).all()
    assert any(
        item.get("direct_relation_ref")
        for record in accepted
        for item in record.payload_json["items"]
    )


async def test_abandon_reports_unreverted_focused_changes_and_keeps_author_edit(
    db_session, test_project_id, account_llm_connection, provider
):
    city = await _create_entity(db_session, test_project_id, "location", "青港")
    provider[1]["fail_at"] = 2
    orchestrator, task, attempt = await prepare(
        db_session,
        test_project_id,
        [{"entity_id": str(city.id)}],
        ["青港坐落在北岸。青港的东边是长桥。", "长桥是一座石桥。"],
    )
    with pytest.raises(TimeoutError):
        await execute(db_session, orchestrator, task, attempt)
    task.mark_failed("provider interrupted")
    recovery = {"recovery_required": True, "interrupted": True, "recoverable": True}
    task.meta = {**task.meta, **recovery}
    task.result = {**task.result, **recovery}
    city.summary = "作者后续改动"
    await db_session.flush()
    result = await orchestrator.abandon_recovery(db_session, str(task.id))
    assert result["status"] == "cancelled"
    assert result["cleanup_summary"]["cleanup_status"] == "partial"
    assert result["cleanup_summary"]["unreverted_targeted_items"] == 1
    assert result["cleanup_summary"]["targeted_completion_rollback"]["conflicts"] == 1
    assert "未撤销" in result["message"]
    assert city.summary == "作者后续改动"
    run = await ImportWorkflowRunService().get_by_task(db_session, task_id=str(task.id))
    assert run.progress["targeted_completion"]["rollback_status"] == "partial"
