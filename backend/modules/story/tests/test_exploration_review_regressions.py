"""Review counterexamples: actual provider boundary, governance and same-run recovery."""

import json
import uuid

import pytest
from sqlalchemy import select

from core.errors import ConflictError
from infrastructure.llm.schemas import read_ai_run_envelope
from modules.story import exploration_api, exploration_tasks
from modules.story.exploration_api import ExplorationResumeRequest
from modules.story.models import StorySceneDirectorRoot, StorySceneDirectorRound
from modules.story.tests.test_exploration_worker import _provisional_start
from modules.story.world_progression_models import StoryWorldProgressionStep

pytest_plugins = ["modules.story.tests.test_exploration_worker"]


def test_locked_hash_must_match_parent_before_generation():
    from modules.story.exploration_schemas import SANDBOX_OUTPUT_KIND
    from modules.story.tests.exploration_test_support import sandbox_payload

    parent = sandbox_payload("规则有什么影响？")
    pinned = exploration_tasks.content_hash(parent["influence_chain"][0])
    parent["influence_chain"][0]["effect"] = "后来生成的不同内容"
    with pytest.raises(ValueError, match="锁定条目"):
        exploration_tasks._enforce_locked_items(
            parent, parent, [("chain:0", pinned)], SANDBOX_OUTPUT_KIND
        )


@pytest.mark.parametrize(
    "shape",
    ["variants", "spatial", "performance", "material", "observation", "author_edit"],
)
async def test_complex_result_local_revision_uses_typed_item_and_keeps_other_fields(
    exploration_flow, shape
):
    from modules.story.exploration_schemas import (
        FULL_REHEARSAL_OUTPUT_KIND,
        PAYLOAD_MODELS_BY_BASE_KIND,
        SCENE_LINE_OUTPUT_KIND,
        ExplorationOutputEnvelope,
    )
    from modules.story.exploration_service import (
        pack_exploration_output,
        unpack_exploration_output,
    )
    from modules.story.tests.exploration_test_support import (
        full_rehearsal_card,
        scene_line_payload,
    )

    flow = exploration_flow
    spec, envelope = await flow.setup(chain="scene", scale="scene_line")
    kind = SCENE_LINE_OUTPUT_KIND
    if shape == "variants":
        payload = {
            "variants": [scene_line_payload("c_baker"), scene_line_payload("c_other")],
            "rationale": "独立差异",
        }
        key, field = "variant:0", "line"
        item = {**payload["variants"][0], "line": "修订后只说可知之事"}
    elif shape == "spatial":
        payload = {
            "line": "",
            "rationale": "空间未知",
            "spatial_assessment": {
                "supported": None,
                "constraints": [],
                "unknowns": ["尺寸未知"],
            },
        }
        key, field = "spatial", "unknowns"
        item = {"supported": None, "constraints": [], "unknowns": ["修订后仍需尺寸"]}
    else:
        kind = FULL_REHEARSAL_OUTPUT_KIND
        payload = {
            "targets": ["c_baker"],
            "rounds": [
                {
                    "round_number": 1,
                    "performances": [full_rehearsal_card("c_baker")],
                    "materials": [
                        {
                            "kind": "environment",
                            "text": "桌边传来雨声",
                            "perceiver_refs": ["c_baker"],
                        }
                    ],
                    "observations": [{"target_ref": "c_baker", "observed": "听到雨声"}],
                }
            ],
        }
        family = "performance" if shape == "author_edit" else shape
        plural, field = {
            "performance": ("performances", "line_or_beat"),
            "material": ("materials", "text"),
            "observation": ("observations", "observed"),
        }[family]
        key = f"{family}:0:0"
        item = {**payload["rounds"][0][plural][0], field: "修订后的局部内容"}
    model = PAYLOAD_MODELS_BY_BASE_KIND[kind].model_validate(payload)
    parent = ExplorationOutputEnvelope(output_kind=kind, payload=model)
    if shape == "author_edit":
        parent = ExplorationOutputEnvelope(
            output_kind="story.exploration.author_edit",
            payload={
                "base_output_kind": kind,
                "base_result_id": str(uuid.uuid4()),
                "edited_payload": model,
            },
        )
    async with flow.sessions.begin() as db:
        row = StorySceneDirectorRound(
            novel_id=spec.novel_id,
            root_id=spec.root_id,
            branch_id=spec.branch_id,
            round_number=1,
            source_hash="a" * 64,
            input_hash="b" * 64,
            output_hash="c" * 64,
            input_json={},
            output_json=pack_exploration_output(parent),
            state_json={},
            run_envelope_json={},
        )
        db.add(row)
        await db.flush()
        parent_id = str(row.id)
    flow.provider.override = item
    task = await flow.run(
        await flow.enqueue(
            spec,
            envelope,
            action=exploration_tasks.SCENE_LINE_ACTION,
            mode="revise",
            parent_result_id=parent_id,
            base_output_kind=kind,
            item_path=key,
            instruction="仅修改选中条目",
        )
    )
    assert task.status == "done", task.error_message
    async with flow.sessions() as db:
        result = await db.scalar(
            select(StorySceneDirectorRound).where(
                StorySceneDirectorRound.id != uuid.UUID(parent_id)
            )
        )
        output = unpack_exploration_output(result).payload.model_dump(mode="json")
        if shape == "variants":
            assert output["variants"][0][field] == item[field]
            assert output["variants"][1] == model.model_dump(mode="json")["variants"][1]
        elif shape == "spatial":
            assert output["spatial_assessment"] == item
        else:
            assert output["rounds"][0][plural][0][field] == item[field]
            assert output["targets"] == payload["targets"]
        assert result.input_json["knowledge_reviews"][0]["status"] == "passed"
    assert flow.provider.calls == 3


async def test_character_provider_never_receives_author_question_or_assumptions(
    exploration_flow,
):
    flow = exploration_flow
    start = _provisional_start("密令在钟楼：作者问题包含人物不知道的事")
    start.author_private = ["掌柜实际是密探"]
    spec, envelope = await flow.setup(chain="scene", scale="scene_line", start=start)
    task = await flow.run(
        await flow.enqueue(
            spec,
            envelope,
            action=exploration_tasks.SCENE_LINE_ACTION,
            target_ref="c_baker",
        )
    )
    assert task.status == "done", task.error_message
    packet = json.loads(flow.provider.generation_requests[0].messages[1].content)
    assert packet["target_knowledge"]["knows"] == ["自己每天三点起床"]
    assert packet["confirmed_material"] == ""
    text = json.dumps(packet, ensure_ascii=False)
    assert "密令在钟楼" not in text and "掌柜实际是密探" not in text
    assert "每天只有一小时重力减半" not in text
    async with flow.sessions() as db:
        row = await db.scalar(select(StorySceneDirectorRound))
        assert row.input_json["knowledge_reviews"][0]["status"] == "passed"


async def test_independent_audit_blocks_after_one_repair_without_result(exploration_flow):
    flow = exploration_flow
    spec, envelope = await flow.setup(chain="progression", scale="sandbox")
    original = flow.provider.generate
    audits = 0

    async def blocked(request):
        nonlocal audits
        response = await original(request)
        if "独立审查者" in request.messages[0].content:
            audits += 1
            verdict = json.loads(response.content)
            verdict.update(
                verdict="blocked",
                findings=[
                    {
                        "kind": "unsupported_fact",
                        "severity": "major",
                        "dimension": "world_entities",
                        "message": "候选影响冒充已确认的事实：掌柜实际是密探",
                    }
                ],
            )
            response.content = json.dumps(verdict, ensure_ascii=False)
        return response

    flow.provider.generate = blocked
    task = await flow.run(
        await flow.enqueue(spec, envelope, action=exploration_tasks.SANDBOX_ACTION)
    )
    assert task.status == "failed"
    assert audits == 2 and flow.provider.calls == 5
    assert all(
        "掌柜实际是密探"
        not in json.dumps(request.model_dump(mode="json"), ensure_ascii=False)
        for request in flow.provider.generation_requests
    )
    async with flow.sessions() as db:
        assert await db.scalar(select(StoryWorldProgressionStep.id)) is None


@pytest.mark.parametrize("change_after", [1, 2, 3])
async def test_source_change_between_calls_or_before_persist_fails_closed(
    exploration_flow, monkeypatch, change_after
):
    flow = exploration_flow
    spec, envelope = await flow.setup(chain="progression", scale="sandbox")
    original = exploration_tasks.prepare_confirmed_ai_action

    async def fresh(*args, **kwargs):
        if flow.provider.calls >= change_after:
            raise ConflictError("确认来源已变化", code="context_changed")
        return await original(*args, **kwargs)

    monkeypatch.setattr(exploration_tasks, "prepare_confirmed_ai_action", fresh)
    task = await flow.run(
        await flow.enqueue(spec, envelope, action=exploration_tasks.SANDBOX_ACTION)
    )
    assert task.status == "failed"
    assert flow.provider.calls == change_after
    async with flow.sessions() as db:
        assert await db.scalar(select(StoryWorldProgressionStep.id)) is None


async def test_unknown_resume_requires_ack_and_reuses_original_root_ledger(
    exploration_flow, monkeypatch
):
    flow = exploration_flow
    spec, envelope = await flow.setup(chain="scene", scale="scene_line")
    flow.provider.fail_next = True
    first = await flow.run(
        await flow.enqueue(
            spec,
            envelope,
            action=exploration_tasks.SCENE_LINE_ACTION,
            target_ref="c_baker",
        )
    )
    assert first.result["status"] == "paused_unknown"

    async def active(*args, **kwargs):
        return None

    monkeypatch.setattr(exploration_api, "require_active_project", active)
    monkeypatch.setattr(
        exploration_api.evidence_facade,
        "prepare_confirmed_ai_action",
        exploration_tasks.prepare_confirmed_ai_action,
    )
    async with flow.sessions.begin() as db:
        (
            root,
            branch,
            _chain,
            raw,
            fingerprint,
        ) = await exploration_api._exploration_resume_state(
            db,
            novel_id=str(spec.novel_id),
            root_id=str(spec.root_id),
            branch_id=str(spec.branch_id),
        )
        assert raw.requests_unknown == 1
        request = ExplorationResumeRequest(
            novel_id=str(spec.novel_id),
            operation_id=uuid.uuid4(),
            checkpoint_hash=fingerprint,
            additional_requests=5,
            additional_tokens=30000,
        )
        with pytest.raises(ConflictError, match="重复计费"):
            await exploration_api.resume_exploration(
                db, root_id=str(root.id), branch_id=str(branch.id), data=request
            )
        request.acknowledge_unknown_requests = 1
        request.allow_possible_duplicate_charge = True
        receipt = await exploration_api.resume_exploration(
            db, root_id=str(root.id), branch_id=str(branch.id), data=request
        )
        repeated = await exploration_api.resume_exploration(
            db, root_id=str(root.id), branch_id=str(branch.id), data=request
        )
        assert repeated["task_id"] == receipt["task_id"]
    resumed = await flow.run(uuid.UUID(receipt["task_id"]))
    assert resumed.result["status"] == "completed", resumed.error_message
    async with flow.sessions() as db:
        root = await db.get(StorySceneDirectorRoot, spec.root_id)
        ledger = read_ai_run_envelope(root.run_envelope_json)
        assert ledger.run_id == str(spec.root_id)
        assert ledger.requests_started == 4 and ledger.requests_unknown == 1
        assert ledger.authorization_revision == 1


async def test_scene_handoff_fingerprint_tracks_output_and_confirmed_characters(
    monkeypatch,
):
    from types import SimpleNamespace

    from modules.story import exploration_service
    from modules.story.exploration_schemas import (
        SCENE_LINE_OUTPUT_KIND,
        ExplorationOutputEnvelope,
    )
    from modules.story.tests.exploration_test_support import scene_line_payload

    target, selected = str(uuid.uuid4()), str(uuid.uuid4())
    output = ExplorationOutputEnvelope(
        output_kind=SCENE_LINE_OUTPUT_KIND, payload=scene_line_payload(target)
    )
    row = SimpleNamespace(
        id=uuid.uuid4(), root_id=uuid.uuid4(), branch_id=uuid.uuid4(), input_json={}
    )
    confirmed = SimpleNamespace(
        compile_options={"character_ids": [selected]},
        confirmation=SimpleNamespace(context_fingerprint="unchanged-author-context"),
    )
    boundary = "旧可知资料"
    calls = []

    async def branch(*args):
        return SimpleNamespace(
            request_json={
                "context_confirmation_id": "original",
                "confirmation_action": exploration_tasks.SCENE_LINE_ACTION,
            }
        )

    async def root(*args):
        return SimpleNamespace(
            request_json={
                "exploration_start": {
                    "kind": "scene_anchor",
                    "scene_id": str(uuid.uuid4()),
                }
            }
        )

    scene_root = await root()

    async def fixed_root(*args):
        return scene_root

    async def prepare(*args, **kwargs):
        return confirmed

    async def projection(*args, character_id, **kwargs):
        calls.append(character_id)
        return SimpleNamespace(rendered_markdown=boundary)

    async def guard(*args, **kwargs):
        return [SimpleNamespace(phrase=boundary)]

    monkeypatch.setattr(exploration_service, "get_director_branch", branch)
    monkeypatch.setattr(exploration_service, "_root_for_chain", fixed_root)
    monkeypatch.setattr(
        exploration_service, "unpack_exploration_output", lambda _: output
    )
    monkeypatch.setattr(
        exploration_service.evidence, "prepare_confirmed_ai_action", prepare
    )
    monkeypatch.setattr(
        exploration_service.evidence, "project_confirmed_character_context", projection
    )
    monkeypatch.setattr(exploration_service.evidence, "build_hidden_guard_context", guard)
    first, _ = await exploration_service._handoff_source_fingerprint(
        None, "novel", row, "scene", "scene_line", ""
    )
    assert set(calls) == {target, selected}
    boundary = "人物获得了新知识"
    second, _ = await exploration_service._handoff_source_fingerprint(
        None, "novel", row, "scene", "scene_line", ""
    )
    assert first != second


@pytest.mark.parametrize("mode", ["start", "detail"])
async def test_multi_item_resume_skips_completed_generation_units(
    exploration_flow, monkeypatch, mode
):
    from modules.story.exploration_schemas import (
        SCENE_LINE_OUTPUT_KIND,
        ExplorationOutputEnvelope,
        SceneLineOutputV1,
    )
    from modules.story.exploration_service import (
        pack_exploration_output,
        unpack_exploration_output,
    )
    from modules.story.models import StorySceneDirectorBranch
    from modules.story.tests.exploration_test_support import scene_line_payload

    flow = exploration_flow
    start = _provisional_start()
    start.candidates.append(
        start.candidates[0].model_copy(
            update={"ref_id": "c_other", "label": "另一位人物"}
        )
    )
    start.knowledge.append(
        start.knowledge[0].model_copy(update={"subject_ref": "c_other"})
    )
    spec, envelope = await flow.setup(
        chain="scene", scale="scene_line", start=start, request_limit=3
    )
    extra = {"multi_targets": ["c_baker", "c_other"]}
    if mode == "detail":
        parent = ExplorationOutputEnvelope(
            output_kind=SCENE_LINE_OUTPUT_KIND,
            payload=SceneLineOutputV1(
                rationale="逐目标差异",
                variants=[scene_line_payload("c_baker"), scene_line_payload("c_other")],
            ),
        )
        async with flow.sessions.begin() as db:
            row = StorySceneDirectorRound(
                novel_id=spec.novel_id,
                root_id=spec.root_id,
                branch_id=spec.branch_id,
                round_number=1,
                source_hash="a" * 64,
                input_hash="b" * 64,
                output_hash="c" * 64,
                input_json={},
                output_json=pack_exploration_output(parent),
                state_json={},
                run_envelope_json={},
            )
            db.add(row)
            await db.flush()
            parent_id = str(row.id)
        extra = {
            "parent_result_id": parent_id,
            "base_output_kind": SCENE_LINE_OUTPUT_KIND,
        }
    first = await flow.run(
        await flow.enqueue(
            spec, envelope, action=exploration_tasks.SCENE_LINE_ACTION, mode=mode, **extra
        )
    )
    assert first.result["status"] == "paused_budget", first.error_message
    async with flow.sessions() as db:
        branch = await db.get(StorySceneDirectorBranch, spec.branch_id)
        completed = branch.pending_round_json.get(
            "completed_variants" if mode == "start" else "completed_items"
        )
        assert len(completed) == 1
    assert flow.provider.calls == 3

    async def active(*args, **kwargs):
        return None

    monkeypatch.setattr(exploration_api, "require_active_project", active)
    monkeypatch.setattr(
        exploration_api.evidence_facade,
        "prepare_confirmed_ai_action",
        exploration_tasks.prepare_confirmed_ai_action,
    )
    async with flow.sessions.begin() as db:
        (
            root,
            branch,
            _chain,
            _raw,
            fingerprint,
        ) = await exploration_api._exploration_resume_state(
            db,
            novel_id=str(spec.novel_id),
            root_id=str(spec.root_id),
            branch_id=str(spec.branch_id),
        )
        receipt = await exploration_api.resume_exploration(
            db,
            root_id=str(root.id),
            branch_id=str(branch.id),
            data=ExplorationResumeRequest(
                novel_id=str(spec.novel_id),
                operation_id=uuid.uuid4(),
                checkpoint_hash=fingerprint,
                additional_requests=3,
                additional_tokens=30000,
            ),
        )
    resumed = await flow.run(uuid.UUID(receipt["task_id"]))
    assert resumed.result["status"] == "completed", resumed.error_message
    assert flow.provider.calls == 6
    async with flow.sessions() as db:
        row = await db.get(
            StorySceneDirectorRound, uuid.UUID(resumed.result["result_id"])
        )
        output = unpack_exploration_output(row)
        assert [item.target_ref for item in output.payload.variants] == [
            "c_baker",
            "c_other",
        ]
        assert len(row.input_json["knowledge_reviews"]) == 2


async def test_scene_result_rejects_a_parent_superseded_by_author_edit(
    db_session, test_project_id, monkeypatch
):
    from types import SimpleNamespace

    from modules.account.settings_constants import LOCAL_OWNER_ID
    from modules.story.exploration_service import save_exploration_author_edit
    from modules.story.tests.test_exploration_locks import _seed_scene_line_result

    root, branch, original, output = await _seed_scene_line_result(
        db_session, test_project_id
    )
    root.status = branch.status = "running"
    root.current_task_id = branch.current_task_id = uuid.uuid4()
    changed = output.payload.model_copy(deep=True)
    changed.line = "作者在生成期间保存的新内容"
    author_row, _ = await save_exploration_author_edit(
        db_session,
        novel_id=str(test_project_id),
        owner_id=str(LOCAL_OWNER_ID),
        base_result_id=str(original.id),
        edited_payload=changed,
    )

    async def fresh(*args, **kwargs):
        return None

    monkeypatch.setattr(exploration_tasks, "_revalidate_result_context", fresh)
    with pytest.raises(ConflictError, match="父结果已变化"):
        await exploration_tasks._write_scene_result(
            db_session,
            root=root,
            branch=branch,
            parent_id=str(original.id),
            envelope=output,
            mode="detail",
            item_path=None,
            item_content_hash=None,
            envelope_run=SimpleNamespace(snapshot=lambda: None),
        )
    latest = await db_session.scalar(
        select(StorySceneDirectorRound)
        .where(StorySceneDirectorRound.branch_id == branch.id)
        .order_by(StorySceneDirectorRound.round_number.desc())
        .limit(1)
    )
    assert latest.id == author_row.id


async def test_author_save_is_rejected_while_follow_up_is_pending(exploration_flow):
    flow = exploration_flow
    spec, envelope = await flow.setup(chain="scene", scale="scene_line")
    first = await flow.run(
        await flow.enqueue(
            spec,
            envelope,
            action=exploration_tasks.SCENE_LINE_ACTION,
            target_ref="c_baker",
        )
    )
    await flow.enqueue(
        spec,
        envelope,
        action=exploration_tasks.SCENE_LINE_ACTION,
        mode="detail",
        target_ref="c_baker",
        parent_result_id=first.result["result_id"],
    )
    async with flow.sessions.begin() as db:
        with pytest.raises(ConflictError, match="仍在执行"):
            await exploration_api.save_exploration_edit(
                db,
                result_id=first.result["result_id"],
                data=exploration_api.ExplorationSaveEditApiRequest(
                    novel_id=str(spec.novel_id),
                    base_output_kind=first.result["output_kind"],
                    edited_payload=first.result["payload"],
                ),
            )


async def test_cancelled_multi_target_task_resumes_saved_units_with_unknown_ack(
    exploration_flow, monkeypatch
):
    import asyncio

    from infrastructure.tasks.facade import get_completed_task_payload
    from modules.evidence.contracts import CandidateRef
    from modules.story.models import StorySceneDirectorBranch

    flow = exploration_flow
    start = _provisional_start()
    start.candidates.append(
        CandidateRef(ref_id="c_other", label="另一人", role="character")
    )
    spec, envelope = await flow.setup(chain="scene", scale="scene_line", start=start)
    generate = flow.provider.generate

    async def interrupted(request):
        if flow.provider.calls >= 3:
            raise asyncio.CancelledError()
        return await generate(request)

    monkeypatch.setattr(flow.provider, "generate", interrupted)
    first = await flow.run(
        await flow.enqueue(
            spec,
            envelope,
            action=exploration_tasks.SCENE_LINE_ACTION,
            multi_targets=["c_baker", "c_other"],
        )
    )
    assert first.status == "cancelled"
    assert first.meta["recovery_receipt"]["needs_author_resume"] is True
    async with flow.sessions() as db:
        root = await db.get(StorySceneDirectorRoot, spec.root_id)
        branch = await db.get(StorySceneDirectorBranch, spec.branch_id)
        assert root.status == branch.status == "paused_unknown"
        assert root.current_task_id is branch.current_task_id is None
        assert len(branch.pending_round_json["completed_variants"]) == 1
        assert read_ai_run_envelope(root.run_envelope_json).requests_unknown == 1
        assert (
            await get_completed_task_payload(
                db,
                task_id=str(first.id),
                task_type=first.task_type,
                novel_id=str(spec.novel_id),
            )
            is None
        )
        receipt = await get_completed_task_payload(
            db,
            task_id=str(first.id),
            task_type=first.task_type,
            novel_id=str(spec.novel_id),
            include_cancelled=True,
        )
        assert receipt.result["root_id"] == str(spec.root_id)
    monkeypatch.setattr(flow.provider, "generate", generate)
    monkeypatch.setattr(
        exploration_api.evidence_facade,
        "prepare_confirmed_ai_action",
        exploration_tasks.prepare_confirmed_ai_action,
    )
    async with flow.sessions.begin() as db:
        (
            root,
            branch,
            _,
            raw,
            fingerprint,
        ) = await exploration_api._exploration_resume_state(
            db,
            novel_id=str(spec.novel_id),
            root_id=str(spec.root_id),
            branch_id=str(spec.branch_id),
        )
        request = ExplorationResumeRequest(
            novel_id=str(spec.novel_id),
            operation_id=uuid.uuid4(),
            checkpoint_hash=fingerprint,
            additional_requests=3,
            additional_tokens=30000,
        )
        with pytest.raises(ConflictError, match="重复计费"):
            await exploration_api.resume_exploration(
                db, root_id=str(root.id), branch_id=str(branch.id), data=request
            )
        request.acknowledge_unknown_requests = raw.requests_unknown
        request.allow_possible_duplicate_charge = True
        resumed = await exploration_api.resume_exploration(
            db, root_id=str(root.id), branch_id=str(branch.id), data=request
        )
    finished = await flow.run(uuid.UUID(resumed["task_id"]))
    assert finished.result["status"] == "completed", finished.error_message
    assert flow.provider.calls == 6
    assert "recovery_receipt" not in finished.meta


@pytest.mark.parametrize(
    "scale,chain", [("sandbox", "progression"), ("scene_line", "scene")]
)
async def test_explicit_cancel_mirrors_recovery_before_worker_claim(
    exploration_flow, scale, chain
):
    from infrastructure.tasks.lifecycle import TaskLifecycleService
    from infrastructure.tasks.models import AsyncTask
    from modules.story.models import StorySceneDirectorBranch
    from modules.story.world_progression_models import (
        StoryWorldProgressionBranch,
        StoryWorldProgressionRoot,
    )

    flow = exploration_flow
    spec, envelope = await flow.setup(chain=chain, scale=scale)
    task_id = await flow.enqueue(
        spec,
        envelope,
        action=(
            exploration_tasks.SCENE_LINE_ACTION
            if chain == "scene"
            else "story.exploration.sandbox.generate"
        ),
        **({"target_ref": "c_baker"} if chain == "scene" else {}),
    )
    async with flow.sessions.begin() as db:
        task = await db.get(AsyncTask, task_id)
        await TaskLifecycleService().cancel(db, task=task)
    async with flow.sessions() as db:
        root = await db.get(
            StorySceneDirectorRoot if chain == "scene" else StoryWorldProgressionRoot,
            spec.root_id,
        )
        branch = await db.get(
            StorySceneDirectorBranch if chain == "scene" else StoryWorldProgressionBranch,
            spec.branch_id,
        )
        assert root.status == branch.status == "paused_budget"
        assert root.current_task_id is branch.current_task_id is None
        task = await db.get(AsyncTask, task_id)
        assert task.status == "cancelled"
        assert task.meta["recovery_receipt"]["branch_id"] == str(spec.branch_id)
        assert flow.provider.calls == 0
