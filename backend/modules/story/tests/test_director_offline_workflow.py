"""Exercise the real workflow with synthetic transport and rollback-only SQLite data."""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from infrastructure.llm.schemas import read_ai_run_envelope
from infrastructure.llm.workflow_budget import AIRunEnvelope, ai_run_scope
from infrastructure.tasks.models import AsyncTask
from modules.evidence.compilation.services.compiled_context import CompiledContext
from modules.story import director_api, director_tasks
from modules.story.director_budget import preview_director_budget
from modules.story.director_context import read_director_source
from modules.story.director_operations import _continuation_preview
from modules.story.director_schemas import DirectorContinueRequest, DirectorStartRequest
from modules.story.models import StorySceneDirectorRoot, StorySceneDirectorRound
from modules.story.outline_state.models import Scene
from modules.story.tests.director_test_support import DirectorOfflineProvider
from modules.story.tests.test_run_envelope_story import _chain_client


@pytest.fixture
async def director_workflow(db_session, test_project_id, test_character_id, monkeypatch):
    from core.config import get_settings
    from modules.world.models import Character

    settings = replace(get_settings(), story_scene_director_enabled=True)
    monkeypatch.setattr("modules.story.director_feature.get_settings", lambda: settings)
    db_session.add(
        Character(
            entity_id=UUID(str(test_character_id)),
            novel_id=UUID(test_project_id),
            name="守门人",
            status="canonical",
        )
    )
    scene = Scene(novel_id=UUID(test_project_id), scene_index=0, title="离线导演回归")
    db_session.add(scene)
    await db_session.flush()
    scene_id, actor = str(scene.id), str(test_character_id)
    source = await read_director_source(
        db_session,
        novel_id=test_project_id,
        scene_id=scene_id,
        character_ids=[actor],
        related_object_ids=[],
    )
    confirmation = SimpleNamespace(
        compiled=CompiledContext(sections=[]),
        rendered_markdown="经作者确认的场景资料",
        compile_options={
            "scene_id": scene_id,
            "character_ids": [actor],
            "entity_ids": [],
        },
    )

    async def confirmed(*_args, **_kwargs):
        return confirmation

    snapshot = {
        "novel_id": test_project_id,
        "profile": {"provider_id": "deepseek", "model": "deepseek-flash"},
    }

    async def llm_snapshot(*_args):
        return snapshot

    async def checkpoint(db, **_kwargs):
        await db.commit()

    provider = DirectorOfflineProvider(actor)
    client = _chain_client(monkeypatch, provider)

    @asynccontextmanager
    async def offline_client(*_args, **_kwargs):
        yield client

    monkeypatch.setattr(director_api, "require_fresh_confirmation", confirmed)
    monkeypatch.setattr(director_api, "prepare_confirmed_ai_action", confirmed)
    monkeypatch.setattr(director_api, "attach_result_ref", confirmed)
    monkeypatch.setattr(
        director_api, "build_project_llm_execution_snapshot", llm_snapshot
    )
    monkeypatch.setattr(director_tasks, "prepare_confirmed_ai_action", confirmed)
    monkeypatch.setattr(
        director_tasks, "require_task_checkpoint_session", lambda _db: None
    )
    monkeypatch.setattr(director_tasks, "checkpoint_handler_session", checkpoint)
    monkeypatch.setattr(
        director_tasks, "open_project_snapshot_llm_client", offline_client
    )

    async def execute(accepted):
        task = await db_session.get(AsyncTask, accepted.task_id)
        root = await db_session.get(StorySceneDirectorRoot, accepted.root_id)

        async def mirror(snapshot):
            await director_tasks._mirror_run_envelope(
                db_session, task, snapshot.model_dump(mode="json")
            )
            await db_session.commit()

        envelope = AIRunEnvelope(
            read_ai_run_envelope(root.run_envelope_json), on_change=mirror
        )
        with ai_run_scope(envelope):
            result = await director_tasks.handle_scene_director(db_session, task)
        task.status = "done"
        await db_session.flush()
        return result

    start = DirectorStartRequest(
        operation_id=uuid4(),
        novel_id=test_project_id,
        scene_id=scene_id,
        character_ids=[actor],
        request_limit=100,
        token_limit=100_000,
        time_budget_seconds=3600,
        context_confirmation_id=str(uuid4()),
        budget_preview_hash="0" * 64,
    )
    start.budget_preview_hash = preview_director_budget(start, source)["preview_hash"]
    try:
        yield SimpleNamespace(
            db=db_session,
            novel_id=test_project_id,
            actor=actor,
            scene_id=scene_id,
            start=start,
            execute=execute,
            provider=provider,
            confirmation=confirmation,
        )
    finally:
        await client.close()


@pytest.mark.parametrize(
    "basis,branch_kind",
    [("current", "continue"), ("frozen", "intervene"), ("frozen", "rewrite_character")],
)
async def test_confirmed_workflow_start_continue_and_rewrite(
    director_workflow, basis, branch_kind
):
    flow = director_workflow
    accepted = await director_api.submit_director_start(flow.db, flow.start)
    repeated = await director_api.submit_director_start(flow.db, flow.start)
    assert repeated.task_id == accepted.task_id
    assert flow.provider.calls == 0
    result = await flow.execute(accepted)
    assert result["status"] == "complete" and result["completed_rounds"] == 1
    parent = await flow.db.scalar(
        select(StorySceneDirectorRound).where(
            StorySceneDirectorRound.root_id == accepted.root_id
        )
    )
    assert parent.input_json["source_snapshot"]["confirmation_scope_hash"]
    assert len(parent.output_json["performances"]) == 1
    assert len(flow.provider.requests) == 4
    assert any(
        "经作者确认的场景资料" in message.content
        for request in flow.provider.requests
        for message in request.messages
    ), [request.model_dump(mode="json") for request in flow.provider.requests]
    continued = DirectorContinueRequest(
        operation_id=uuid4(),
        novel_id=flow.novel_id,
        parent_round_id=parent.id,
        context_confirmation_id=flow.start.context_confirmation_id,
        branch_kind=branch_kind,
        basis_choice=basis,
        intervention="保持谨慎" if branch_kind == "intervene" else "",
        selected_alternative="a" if branch_kind == "intervene" else None,
        rewrite_character_id=flow.actor if branch_kind == "rewrite_character" else None,
        budget_preview_hash="0" * 64,
    )
    _, _, preview = await _continuation_preview(flow.db, flow.novel_id, continued)
    continued.budget_preview_hash = preview["preview_hash"]
    next_task = await director_api.continue_director_root(
        flow.db, root_id=str(accepted.root_id), data=continued
    )
    duplicate = await director_api.continue_director_root(
        flow.db, root_id=str(accepted.root_id), data=continued
    )
    assert duplicate.task_id == next_task.task_id
    result = await flow.execute(next_task)
    assert result["status"] == "complete"
    assert flow.provider.calls == (5 if branch_kind == "rewrite_character" else 8)
    rows = list(
        (
            await flow.db.scalars(
                select(StorySceneDirectorRound).where(
                    StorySceneDirectorRound.root_id == accepted.root_id
                )
            )
        ).all()
    )
    assert len(rows) == 2
    if branch_kind == "rewrite_character":
        rewritten = next(row for row in rows if row.id != parent.id)
        assert rewritten.input_json["rewrite_of_round_id"] == str(parent.id)
        assert rewritten.state_json == parent.state_json
        assert rewritten.output_json["materials"] == parent.output_json["materials"]
    else:
        assert any(row.parent_round_id == parent.id for row in rows)
    root = await flow.db.get(StorySceneDirectorRoot, accepted.root_id)
    assert root.current_task_id is None and root.status == "ready"
    assert (
        read_ai_run_envelope(root.run_envelope_json).requests_settled
        == flow.provider.calls
    )

    # Reject old state/output before authorizing budget for a narrower confirmation.
    before = json.dumps(root.run_envelope_json, sort_keys=True)
    flow.confirmation.rendered_markdown = "缩小后的资料范围"
    continued.operation_id = uuid4()
    continued.additional_requests = 10
    calls = flow.provider.calls
    with pytest.raises(ValueError, match="新建导演运行"):
        await director_api.continue_director_root(
            flow.db, root_id=str(root.id), data=continued
        )
    assert flow.provider.calls == calls
    assert json.dumps(root.run_envelope_json, sort_keys=True) == before


@pytest.mark.parametrize("legacy", [False, True])
async def test_worker_rechecks_scope_before_using_parent_state(
    director_workflow, monkeypatch, legacy
):
    flow = director_workflow
    accepted = await director_api.submit_director_start(flow.db, flow.start)
    await flow.execute(accepted)
    parent = await flow.db.scalar(
        select(StorySceneDirectorRound).where(
            StorySceneDirectorRound.root_id == accepted.root_id
        )
    )
    data = DirectorContinueRequest(
        operation_id=uuid4(),
        novel_id=flow.novel_id,
        parent_round_id=parent.id,
        context_confirmation_id=flow.start.context_confirmation_id,
        basis_choice="frozen",
        budget_preview_hash="0" * 64,
    )
    _, _, preview = await _continuation_preview(flow.db, flow.novel_id, data)
    data.budget_preview_hash = preview["preview_hash"]
    continued = await director_api.continue_director_root(
        flow.db, root_id=str(accepted.root_id), data=data
    )
    root = await flow.db.get(StorySceneDirectorRoot, accepted.root_id)
    before = json.dumps(root.run_envelope_json, sort_keys=True)
    if legacy:

        async def old_parent(*_args, **_kwargs):
            return SimpleNamespace(
                root_id=root.id, input_json={"source_snapshot": {}}
            ), None

        monkeypatch.setattr(director_tasks, "get_director_round", old_parent)
    else:
        flow.confirmation.rendered_markdown = "排除了父回合依赖的资料"
    with pytest.raises(ValueError, match="新建导演运行"):
        await flow.execute(continued)
    assert flow.provider.calls == 4
    assert json.dumps(root.run_envelope_json, sort_keys=True) == before


async def test_director_http_history_and_reference_lifecycle(
    director_workflow, async_client
):
    flow = director_workflow
    accepted = await director_api.submit_director_start(flow.db, flow.start)
    await flow.execute(accepted)
    parent = await flow.db.scalar(
        select(StorySceneDirectorRound).where(
            StorySceneDirectorRound.root_id == accepted.root_id
        )
    )
    base = "/api/story"
    identity = {"novel_id": flow.novel_id}
    history_url = f"{base}/scenes/{flow.scene_id}/director/history"
    history = await async_client.get(history_url, params=identity)
    assert history.status_code == 200, history.text
    assert len(history.json()["rounds"]) == 1
    assert history.json()["rounds"][0]["basis_status"] == "current"
    checked = await async_client.get(
        f"{base}/director/rounds/{parent.id}/consistency", params=identity
    )
    assert checked.status_code == 200, checked.text
    for kind, row_id in (("rounds", parent.id), ("branches", parent.branch_id)):
        changed = await async_client.patch(
            f"{base}/director/{kind}/{row_id}",
            json={**identity, "name": "保留版本", "note": "作者手记", "starred": True},
        )
        assert changed.status_code == 200 and changed.json()["starred"]
    reference = await async_client.post(
        f"{base}/director/rounds/{parent.id}/references",
        json={
            **identity,
            "name": "北门参考",
            "source_round_id": str(parent.id),
            "material_ids": ["north-gate-wind"],
            "angle": parent.output_json["recommended_angles"][1],
        },
    )
    assert reference.status_code == 201, reference.text
    reference_id = reference.json()["id"]
    changed = await async_client.patch(
        f"{base}/director/references/{reference_id}",
        json={**identity, "name": "修订参考", "annotation": "只借鉴节奏"},
    )
    assert changed.status_code == 200 and changed.json()["name"] == "修订参考"
    for action in ("delete", "restore"):
        result = await async_client.post(
            f"{base}/director/references/{reference_id}/{action}", json=identity
        )
        assert result.status_code == 200, result.text
    preferences = await async_client.put(
        f"{base}/director/preferences",
        json={**identity, "cliche_phrases": ["眼神一凛", "眼神一凛"]},
    )
    assert preferences.status_code == 400
    preferences = await async_client.put(
        f"{base}/director/preferences",
        json={**identity, "cliche_phrases": ["眼神一凛"]},
    )
    assert preferences.status_code == 200, preferences.text
    fetched = await async_client.get(f"{base}/director/preferences", params=identity)
    assert fetched.status_code == 200
    assert fetched.json()["cliche_phrases"] == ["眼神一凛"]
    branch_url = f"{base}/director/branches/{parent.branch_id}"
    denied = await async_client.post(f"{branch_url}/delete", json=identity)
    assert denied.status_code == 400
    removed = await async_client.post(
        f"{branch_url}/delete", json={**identity, "confirm": True}
    )
    assert removed.status_code == 200, removed.text
    hidden = await async_client.get(history_url, params=identity)
    assert hidden.status_code == 200 and hidden.json()["rounds"] == []
    # Copied reference text survives deletion of its source branch.
    assert hidden.json()["references"][0]["content_copy"]["materials"][0]["content"]
    from modules.story.facade import read_scene_director_references_for_writing

    copied = await read_scene_director_references_for_writing(
        flow.db,
        novel_id=flow.novel_id,
        scene_id=flow.scene_id,
        reference_ids=[reference_id],
        consumer_action="writing.generate",
        max_chars=10000,
    )
    copied = copied.model_dump(mode="json")
    assert copied["items"][0]["source_deleted"] is True
    assert copied["items"][0]["advisory_only"] is True
    omitted = await read_scene_director_references_for_writing(
        flow.db,
        novel_id=flow.novel_id,
        scene_id=flow.scene_id,
        reference_ids=[reference_id],
        consumer_action="writing.generate",
        max_chars=1,
    )
    omitted = omitted.model_dump(mode="json")
    assert omitted["items"] == [] and omitted["omitted"] == [reference_id]
    restored = await async_client.post(f"{branch_url}/restore", json=identity)
    assert restored.status_code == 200, restored.text
    assert (
        len((await async_client.get(history_url, params=identity)).json()["rounds"]) == 1
    )
    batch_url = f"{base}/scenes/{flow.scene_id}/director/delete-unstarred"
    batch_data = {**identity, "scene_id": flow.scene_id, "confirm": True}
    protected = await async_client.post(batch_url, json=batch_data)
    assert protected.status_code == 200 and protected.json()["deleted_branch_ids"] == []
    await async_client.patch(branch_url, json={**identity, "starred": False})
    refused = await async_client.post(batch_url, json={**batch_data, "confirm": False})
    assert refused.status_code == 400
    batch = await async_client.post(batch_url, json=batch_data)
    assert batch.status_code == 200, batch.text
    assert batch.json()["deleted_branch_ids"] == [str(parent.branch_id)]
    recovered = await async_client.post(f"{branch_url}/restore", json=identity)
    assert recovered.status_code == 200
    assert flow.provider.calls == 4


@pytest.mark.parametrize("failure", ["unknown", "budget", "invalid_output"])
async def test_director_failure_keeps_checkpoint_and_stops_requests(
    director_workflow, monkeypatch, failure
):
    from infrastructure.llm.errors import LLMInvalidResponseError
    from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
    from modules.story.models import StorySceneDirectorBranch

    flow = director_workflow
    if failure == "budget":
        flow.start.request_limit = 2
    elif failure == "unknown":
        flow.provider.fail_next = True
    else:

        async def invalid(request):
            flow.provider.calls += 1
            return LLMCallResponse(
                content="invalid synthetic output",
                model="deepseek-flash",
                provider="offline-director",
                finish_reason="stop",
                usage=LLMUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            )

        monkeypatch.setattr(flow.provider, "generate", invalid)
    accepted = await director_api.submit_director_start(flow.db, flow.start)
    if failure == "invalid_output":
        with pytest.raises(LLMInvalidResponseError, match="JSON|json|structured|结构"):
            await flow.execute(accepted)
    else:
        result = await flow.execute(accepted)
        assert result["status"] == (
            "paused_unknown" if failure == "unknown" else "paused_budget"
        )
        assert result["completed_rounds"] == 0
    root = await flow.db.get(StorySceneDirectorRoot, accepted.root_id)
    branch = await flow.db.scalar(
        select(StorySceneDirectorBranch).where(
            StorySceneDirectorBranch.root_id == root.id
        )
    )
    assert branch.pending_round_json["source_snapshot"]["confirmation_scope_hash"]
    assert root.current_task_id is None and branch.current_task_id is None
    assert flow.provider.calls == (2 if failure == "budget" else 1)
    ledger = read_ai_run_envelope(root.run_envelope_json)
    assert ledger.requests_started == flow.provider.calls
    if failure == "unknown":
        assert ledger.requests_unknown == 1
        again = await flow.execute(accepted)
        assert again["status"] == "paused_unknown" and flow.provider.calls == 1
    elif failure == "invalid_output":
        assert root.status == branch.status == "failed"
        assert "invalid synthetic output" not in branch.pending_round_json["safe_error"]


async def test_director_http_preview_advance_and_budget_extension(
    director_workflow, async_client
):
    from modules.story.director_schemas import (
        DirectorBudgetPreviewRequest,
        DirectorTaskAccepted,
    )

    flow = director_workflow
    base = "/api/story"
    preview = await async_client.post(
        f"{base}/scenes/director/budget-preview",
        json=DirectorBudgetPreviewRequest.model_validate(
            flow.start.model_dump(include=set(DirectorBudgetPreviewRequest.model_fields))
        ).model_dump(mode="json"),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["preview_hash"] == flow.start.budget_preview_hash
    payload = flow.start.model_dump(mode="json")
    wrong_path = await async_client.post(
        f"{base}/scenes/{uuid4()}/director", json=payload
    )
    assert wrong_path.status_code == 400
    accepted_http = await async_client.post(
        f"{base}/scenes/{flow.scene_id}/director", json=payload
    )
    assert accepted_http.status_code == 202, accepted_http.text
    accepted = DirectorTaskAccepted.model_validate(accepted_http.json())
    await flow.execute(accepted)
    parent = await flow.db.scalar(
        select(StorySceneDirectorRound).where(
            StorySceneDirectorRound.root_id == accepted.root_id
        )
    )
    root_url = f"{base}/director/roots/{accepted.root_id}"
    continuation = {
        "operation_id": str(uuid4()),
        "novel_id": flow.novel_id,
        "parent_round_id": str(parent.id),
        "basis_choice": "frozen",
        "branch_kind": "intervene",
        "selected_alternative": "a",
    }
    preview = await async_client.post(f"{root_url}/budget-preview", json=continuation)
    assert preview.status_code == 200, preview.text
    assert preview.json()["current_budget"]["requests_used"] == 4
    invalid = await async_client.post(
        f"{root_url}/budget-preview",
        json={**continuation, "selected_alternative": "missing"},
    )
    assert invalid.status_code == 400
    request = {
        **continuation,
        "context_confirmation_id": flow.start.context_confirmation_id,
        "budget_preview_hash": preview.json()["preview_hash"],
    }
    no_extension = await async_client.post(f"{root_url}/branches", json=request)
    assert no_extension.status_code == 400
    advanced = await async_client.post(f"{root_url}/advance", json=request)
    assert advanced.status_code == 202, advanced.text
    await flow.execute(DirectorTaskAccepted.model_validate(advanced.json()))
    parent = await flow.db.scalar(
        select(StorySceneDirectorRound).where(
            StorySceneDirectorRound.root_id == accepted.root_id,
            StorySceneDirectorRound.round_number == 2,
        )
    )
    continuation.update(parent_round_id=str(parent.id), operation_id=str(uuid4()))
    preview = await async_client.post(f"{root_url}/budget-preview", json=continuation)
    assert preview.status_code == 200, preview.text
    request.update(
        **continuation,
        budget_preview_hash=preview.json()["preview_hash"],
        additional_requests=10,
        additional_tokens=1000,
    )
    extended = await async_client.post(f"{root_url}/branches", json=request)
    assert extended.status_code == 202, extended.text
    await flow.execute(DirectorTaskAccepted.model_validate(extended.json()))
    root = await flow.db.get(StorySceneDirectorRoot, accepted.root_id)
    ledger = read_ai_run_envelope(root.run_envelope_json)
    assert ledger.request_limit == 110 and ledger.token_limit == 101000
    assert ledger.requests_started == ledger.requests_settled == 12
    assert ledger.authorization_revision == 1
    missing = await async_client.get(
        f"{base}/director/rounds/{uuid4()}/consistency",
        params={"novel_id": flow.novel_id},
    )
    assert missing.status_code == 404
