"""Provider-only replacement: real gateway budgeting, SQL and output governance."""

import json
from uuid import UUID, uuid4

from sqlalchemy import select

from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.tasks.models import AsyncTask
from modules.collaboration import cases, runtime
from modules.collaboration.contracts import RunCreate
from modules.collaboration.models import (
    CollaborationCase,
    CollaborationRun,
    CollaborationWorkItem,
)
from modules.collaboration.tests.test_workspaces import setup_trial


async def test_blind_reading_freezes_prefix_before_revelation(
    db_session, test_project_id, account_llm_connection, monkeypatch
):
    from modules.collaboration.models import CollaborationArtifact
    from modules.collaboration.recipes import RECIPES

    db, nid = db_session, test_project_id
    case, _, drafts, _ = await setup_trial(db, nid, monkeypatch, two=True)
    from modules.writing.models import WritingDraft

    drafts = [await db.get(WritingDraft, UUID(str(draft.id))) for draft in drafts]
    first = "她把铜钥匙放进信封。"
    revelation = "信封里其实还有一把银钥匙。"
    drafts[0].content = first + revelation
    drafts[1].content = "次日，她重新打开信封。"
    row = await db.get(CollaborationCase, UUID(case["id"]))
    row.recipe_json = RECIPES["blind_reader"].model_dump(mode="json")
    row.goal = "作者幕后真相：钥匙是伪造的"
    row.grant_json = {
        **row.grant_json,
        "cutoff_chapter": 2,
        "reading_stops": {f"writing_draft:{drafts[0].id}": [len(first)]},
    }
    monkeypatch.setattr(db, "task_checkpoint_enabled", True, raising=False)
    prose_seen = []

    async def provider(self, request):
        assert not db.in_transaction()
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])["title"]
        user = next(
            message.content for message in request.messages if message.role == "user"
        )
        assert "钥匙是伪造的" not in user
        if schema == "ReadingNode":
            data = json.loads(user)
            prose_seen.append(data["prose"])
            if len(prose_seen) == 1:
                assert revelation not in user and "次日" not in user
            if len(prose_seen) == 2:
                assert data["prior_reading"][0]["beliefs"]["unanswered"] == [
                    "信封还有什么？"
                ]
            result = {
                "known": [{"belief": data["prose"], "excerpt": data["prose"]}],
                "unanswered": ["信封还有什么？"] if len(prose_seen) == 1 else [],
            }
        elif schema == "GraphDelta":
            assert len(prose_seen) == 3
            revision = json.loads(user)["expected_plan_revision"]
            result = {
                "expected_plan_revision": revision,
                "reason": "对照冻结猜测",
                "finish": revision > 0,
                "items": []
                if revision
                else [
                    {
                        "logical_key": "compare",
                        "capability": "compare",
                        "question": "揭示之前有何依据？",
                    }
                ],
            }
        elif schema == "WorkOutput":
            result = {"summary": "第一段尚不知道第二把钥匙，过去的未知保持不变。"}
        elif schema == "AuditVerdictOutput":
            if len(prose_seen) == 1:
                assert revelation not in user
            result = {
                "verdict": "pass",
                "findings": [],
                "dimensions": [
                    {"dimension": value, "checked": True}
                    for value in ("prior_prose", "world_rules", "outline")
                ],
            }
        else:
            raise AssertionError(schema)
        return LLMCallResponse(
            content=json.dumps(result, ensure_ascii=False),
            usage=LLMUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
            finish_reason="stop",
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    result = await cases.submit_run(
        db, nid, case["id"], RunCreate(operation_id=uuid4(), expected_goal_version=1)
    )
    await db.commit()
    await runtime.execute(db, await db.get(AsyncTask, UUID(result["task_id"])))
    points = (
        await db.scalars(
            select(CollaborationArtifact).where(
                CollaborationArtifact.run_id == UUID(result["run_id"]),
                CollaborationArtifact.kind == "reading_point",
            )
        )
    ).all()
    points.sort(key=lambda item: item.payload_json["point"])
    assert prose_seen == [first, revelation, "次日，她重新打开信封。"]
    assert points[0].payload_json["beliefs"]["unanswered"] == ["信封还有什么？"]
    assert points[1].manifest_json["resources"][0]["read_range"] == [
        len(first),
        len(first + revelation),
    ]
    assert len(points) == 3


async def test_adaptive_run_adds_countercheck_and_preserves_root_budget(
    db_session, test_project_id, account_llm_connection, monkeypatch
):
    db, nid = db_session, test_project_id
    case, _, drafts, _ = await setup_trial(db, nid, monkeypatch)
    monkeypatch.setattr(db, "task_checkpoint_enabled", True, raising=False)
    from modules.collaboration.recipes import RECIPES

    case_row = await db.get(CollaborationCase, UUID(case["id"]))
    case_row.recipe_json = RECIPES["deep_review"].model_dump(mode="json")
    seen = []

    async def provider(self, request):
        assert not db.in_transaction(), "Provider I/O must not hold a DB transaction"
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])
        seen.append(schema["title"])
        if schema["title"] == "GraphDelta":
            payload = json.loads(
                next(
                    message.content
                    for message in request.messages
                    if message.role == "user"
                )
            )
            revision = payload["expected_plan_revision"]
            result = {
                "expected_plan_revision": revision,
                "reason": "检验竞争解释",
                "items": [
                    {
                        "logical_key": "investigate" if revision == 0 else "counter",
                        "capability": "investigate" if revision == 0 else "countercheck",
                        "question": "是否存在有限合作的解释？",
                        "depends_on": [] if revision == 0 else ["investigate"],
                    }
                ]
                if revision < 2
                else [],
                "finish": revision >= 2,
            }
        elif schema["title"] == "WorkOutput":
            result = {
                "summary": "可能是有限合作，动机仍待表达。",
                "claims": [
                    {
                        "kind": "source_statement",
                        "text": "她接受了帮助。",
                        "evidence_keys": [f"writing_draft:{drafts[0].id}"],
                    }
                ],
            }
        elif schema["title"] == "AuditVerdictOutput":
            result = {
                "verdict": "pass",
                "findings": [],
                "dimensions": [
                    {"dimension": value, "checked": True}
                    for value in ("prior_prose", "world_rules", "outline")
                ],
            }
        else:
            raise AssertionError(schema["title"])
        return LLMCallResponse(
            content=json.dumps(result, ensure_ascii=False),
            usage=LLMUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
            finish_reason="stop",
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    submission = await cases.submit_run(
        db, nid, case["id"], RunCreate(operation_id=uuid4(), expected_goal_version=1)
    )
    await db.commit()
    task = await db.get(AsyncTask, UUID(submission["task_id"]))
    result = await runtime.execute(db, task)
    assert result["status"] == "completed"
    work = (
        await db.scalars(
            select(CollaborationWorkItem)
            .where(CollaborationWorkItem.run_id == UUID(result["run_id"]))
            .order_by(CollaborationWorkItem.logical_key)
        )
    ).all()
    assert len(work) == 2 and all(row.status == "succeeded" for row in work)
    run = await db.get(CollaborationRun, UUID(result["run_id"]))
    case_row = await db.get(CollaborationCase, UUID(case["id"]))
    assert seen == [
        "GraphDelta",
        "WorkOutput",
        "AuditVerdictOutput",
        "GraphDelta",
        "WorkOutput",
        "AuditVerdictOutput",
        "GraphDelta",
    ]
    assert run.budget_json["requests"] == case_row.requests_used == 7
    assert run.budget_json["pending_usage"] == 0
    assert run.budget_json["usage_complete"] is True


async def test_full_revision_recipe_checks_two_trials_and_merges_only_after_confirmation(
    db_session, test_project_id, account_llm_connection, monkeypatch
):
    from modules.collaboration.contracts import MergeRequest, RevisionRequest
    from modules.collaboration.merge import merge_workspace
    from modules.collaboration.models import CollaborationArtifact
    from modules.collaboration.workspaces import seal_workspace, workspace_view
    from modules.writing.facade import get_latest_draft_for_chapter

    db, nid = db_session, test_project_id
    case, _, drafts, _ = await setup_trial(db, nid, monkeypatch)
    monkeypatch.setattr(db, "task_checkpoint_enabled", True, raising=False)
    source_key = f"writing_draft:{drafts[0].id}"
    calls = []

    async def provider(self, request):
        assert not db.in_transaction()
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])
        kind = schema["title"]
        calls.append(kind)
        payload = (
            json.loads(
                next(
                    message.content
                    for message in request.messages
                    if message.role == "user"
                )
            )
            if kind != "AuditVerdictOutput"
            else {}
        )
        if kind == "GraphDelta":
            revision = payload["expected_plan_revision"]
            work = []
            if revision == 0:
                work = [
                    {
                        "logical_key": "cause",
                        "capability": "investigate",
                        "question": "寻找动机",
                    }
                ]
            elif revision == 1:
                work = [
                    {
                        "logical_key": key,
                        "capability": "revise",
                        "question": key,
                        "depends_on": ["cause"],
                    }
                    for key in ("cautious", "shared_need")
                ]
            elif revision == 2:
                artifacts = [
                    item for item in payload["new_artifacts"] if item["kind"] == "revise"
                ]
                work = [
                    {
                        "logical_key": f"check_{index}",
                        "capability": "test",
                        "question": "检查具体试改",
                        "workspace_revision_id": item["workspace_revision_id"],
                    }
                    for index, item in enumerate(artifacts)
                ]
                work.append(
                    {
                        "logical_key": "compare",
                        "capability": "compare",
                        "question": "比较两种修法与原文",
                        "depends_on": ["check_0", "check_1", "cautious", "shared_need"],
                        "dependency_policy": "all_terminal",
                    }
                )
            value = {
                "expected_plan_revision": revision,
                "items": work,
                "finish": revision >= 3,
                "reason": "保留两种独立解释",
            }
        elif kind == "WorkOutput":
            value = {
                "summary": payload["question"],
                "claims": [
                    {
                        "kind": "source_statement",
                        "text": "她接受了帮助。",
                        "evidence_keys": [source_key],
                    }
                ],
            }
            if payload["question"] in {"cautious", "shared_need"}:
                value["patches"] = [
                    {
                        "kind": "writing_draft",
                        "id": drafts[0].id,
                        "value": {
                            "title": drafts[0].title,
                            "content": drafts[0].content
                            + (
                                "她仍保留退路。"
                                if payload["question"] == "cautious"
                                else "他们都需要离开这里。"
                            ),
                        },
                    }
                ]
        elif kind == "CheckOutput":
            value = {
                "verdict": "passed",
                "preserved_constraints": payload["constraints"],
                "completed_checks": payload["checks"],
            }
        else:
            assert kind == "AuditVerdictOutput"
            value = {
                "verdict": "pass",
                "dimensions": [
                    {"dimension": key, "checked": True}
                    for key in ("prior_prose", "world_rules", "outline")
                ],
            }
        return LLMCallResponse(
            content=json.dumps(value, ensure_ascii=False),
            usage=LLMUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
            finish_reason="stop",
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    submission = await cases.submit_run(
        db, nid, case["id"], RunCreate(operation_id=uuid4(), expected_goal_version=1)
    )
    await db.commit()
    task = await db.get(AsyncTask, UUID(submission["task_id"]))
    result = await runtime.execute(db, task)
    assert result["status"] == "completed"
    assert calls.count("CheckOutput") == 2 and len(calls) == 16
    assert (await get_latest_draft_for_chapter(db, nid, 1)).id == drafts[0].id
    artifacts = (
        await db.scalars(
            select(CollaborationArtifact).where(
                CollaborationArtifact.run_id == UUID(result["run_id"]),
                CollaborationArtifact.kind == "revise",
            )
        )
    ).all()
    from modules.collaboration.workspaces import require_revision

    workspace, revision = await require_revision(
        db, nid, artifacts[0].workspace_revision_id
    )
    view = await workspace_view(db, nid, workspace.id)
    assert view["can_seal"]
    await seal_workspace(
        db,
        nid,
        workspace.id,
        RevisionRequest(revision_id=revision.id, expected_digest=revision.digest),
    )
    receipt = await merge_workspace(
        db,
        nid,
        workspace.id,
        MergeRequest(
            operation_id=uuid4(),
            revision_id=revision.id,
            expected_digest=revision.digest,
            confirmed=True,
            editor_state="saved",
        ),
    )
    assert receipt["domain_write_performed"]
    assert (await get_latest_draft_for_chapter(db, nid, 1)).id != drafts[0].id
    owner = await db.get(CollaborationCase, UUID(case["id"]))
    assert owner.requests_used == 16


async def test_world_trial_retests_exact_frozen_scenario_without_publishing(
    db_session, test_project_id, account_llm_connection, monkeypatch
):
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta

    from core.config import get_settings
    from infrastructure.llm.collaboration import content_hash
    from modules.collaboration import workspaces
    from modules.collaboration.contracts import (
        CaseCreate,
        Grant,
        ResourcePatch,
        WorkspaceCreate,
        WorkspaceEdit,
    )
    from modules.collaboration.models import CollaborationArtifact
    from modules.world.models import WorldBiblePageDraft

    db, nid = db_session, test_project_id
    settings = replace(
        get_settings(), assistant_enabled=True, collaboration_v2_enabled=True
    )
    monkeypatch.setattr(cases, "get_settings", lambda: settings)
    monkeypatch.setattr(db, "task_checkpoint_enabled", True, raising=False)
    original = WorldBiblePageDraft(
        novel_id=UUID(nid),
        title="钥匙规则",
        page_type="rule",
        free_text="铜钥匙开门后会复制出一把相同钥匙。",
        sections_json=[],
    )
    db.add(original)
    await db.flush()
    case = await cases.create_case(
        db,
        nid,
        CaseCreate(
            operation_id=uuid4(),
            goal="保留能开门的作用，但钥匙总量始终为一把",
            recipe_id="world_stress",
            grant=Grant(
                resources=[{"kind": "world_bible_draft", "id": original.id}],
                read_kinds=["world_bible_draft"],
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
        ),
    )
    trial = await workspaces.create_workspace(
        db, nid, case["id"], WorkspaceCreate(operation_id=uuid4(), label="不复制钥匙")
    )
    trial = await workspaces.edit_workspace(
        db,
        nid,
        trial["id"],
        WorkspaceEdit(
            expected_revision_id=trial["revision_id"],
            patches=[
                ResourcePatch(
                    kind="world_bible_draft",
                    id=original.id,
                    value={
                        "title": original.title,
                        "free_text": "铜钥匙开门后仍只有这一把，不会复制。",
                        "sections_json": [],
                    },
                )
            ],
        ),
    )
    _, revision = await workspaces.require_revision(db, nid, trial["revision_id"])
    earlier = CollaborationRun(
        id=uuid4(),
        novel_id=UUID(nid),
        case_id=UUID(case["id"]),
        operation_id=uuid4(),
        request_hash="a" * 64,
        request_json={},
        manifest_json=revision.manifest_json,
        llm_snapshot_json={},
        status="completed",
    )
    db.add(earlier)
    await db.flush()
    key = f"world_bible_draft:{original.id}"
    scenario = {
        "key": "one_key",
        "title": "两人先后开门",
        "invariant": "铜钥匙总数始终等于一",
        "source_keys": [key],
        "assumptions": ["开始时仅有一把铜钥匙"],
        "actions": ["甲用钥匙开门", "乙再次用它开门"],
        "expected": "holds",
    }
    payload = {
        "summary": "复制规则会增加钥匙数量。",
        "scenarios": [scenario],
        "knowledge_review": {"status": "passed"},
    }
    artifact = CollaborationArtifact(
        id=uuid4(),
        novel_id=UUID(nid),
        run_id=earlier.id,
        kind="investigate",
        manifest_json=revision.manifest_json,
        payload_json=payload,
        output_hash=content_hash(payload),
    )
    db.add(artifact)
    await db.flush()
    calls = []

    async def provider(self, request):
        assert not db.in_transaction()
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])
        calls.append(schema["title"])
        if schema["title"] == "WorldScenarioCheck":
            data = json.loads(
                next(
                    message.content
                    for message in request.messages
                    if message.role == "user"
                )
            )
            assert data["scenarios"] == [scenario]
            assert "复制出" in data["original"] and "不会复制" in data["candidate"]
            value = {
                "verdict": "passed",
                "preserved_constraints": [],
                "completed_checks": data["checks"],
                "scenario_results": [
                    {
                        "key": "one_key",
                        "baseline": "violated",
                        "candidate": "holds",
                        "baseline_reason": "开门增加钥匙数量。",
                        "candidate_reason": "开门不再复制。",
                        "source_keys": [key],
                    }
                ],
            }
        else:
            assert schema["title"] == "AuditVerdictOutput"
            value = {
                "verdict": "pass",
                "dimensions": [
                    {"dimension": dimension, "checked": True}
                    for dimension in ("prior_prose", "world_rules", "outline")
                ],
            }
        return LLMCallResponse(
            content=json.dumps(value, ensure_ascii=False),
            usage=LLMUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
            finish_reason="stop",
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    submitted = await cases.submit_run(
        db,
        nid,
        case["id"],
        RunCreate(
            operation_id=uuid4(),
            expected_goal_version=1,
            workspace_revision_id=trial["revision_id"],
        ),
    )
    await db.commit()
    task = await db.get(AsyncTask, UUID(submitted["task_id"]))
    result = await runtime.execute(db, task)
    assert result["status"] == "completed" and calls == [
        "WorldScenarioCheck",
        "AuditVerdictOutput",
    ]
    current = await workspaces.workspace_view(db, nid, trial["id"])
    assert current["can_seal"]
    assert original.free_text == "铜钥匙开门后会复制出一把相同钥匙。"


async def test_two_verified_connections_share_one_case_budget(
    db_session, test_project_id, account_llm_connection, monkeypatch
):
    from datetime import UTC, datetime

    from infrastructure.llm.secret_store import encrypt_secret, fingerprint_secret
    from modules.account.settings_models import AccountLLMCredential
    from modules.collaboration.recipes import RECIPES
    from tests.support.creative_browser_provider import structured_reply

    monkeypatch.setenv(
        "ENABLE_ACCOUNT_KIMI_K3", "1"
    )  # Synthetic transport; not a real-provider release claim.
    db, nid = db_session, test_project_id
    case, _, _, _ = await setup_trial(db, nid, monkeypatch)
    owned = await db.get(CollaborationCase, UUID(case["id"]))
    db.add(
        AccountLLMCredential(
            owner_id=owned.owner_id,
            provider_id="kimi",
            encrypted_api_key=encrypt_secret("synthetic-second-provider"),
            key_fingerprint=fingerprint_secret(
                "synthetic-second-provider", purpose="account-llm-api-key"
            ),
            verified_at=datetime.now(UTC),
        )
    )
    owned.recipe_json = RECIPES["deep_review"].model_dump(mode="json")
    owned.grant_json = {**owned.grant_json, "model_connections": {"check": "kimi"}}
    seen = []

    async def provider(self, request):
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])["title"]
        seen.append((schema, request.model))
        if schema == "GraphDelta":
            payload = json.loads(
                next(item.content for item in request.messages if item.role == "user")
            )
            revision = payload["expected_plan_revision"]
            value = {
                "expected_plan_revision": revision,
                "reason": "一次调查",
                "finish": revision > 0,
                "items": []
                if revision
                else [
                    {
                        "logical_key": "read",
                        "capability": "investigate",
                        "question": "核对动机",
                    }
                ],
            }
            return LLMCallResponse(
                content=json.dumps(value),
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                finish_reason="stop",
            )
        return structured_reply(request)

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    monkeypatch.setattr(db, "task_checkpoint_enabled", True, raising=False)
    result = await cases.submit_run(
        db, nid, case["id"], RunCreate(operation_id=uuid4(), expected_goal_version=1)
    )
    await db.commit()
    await runtime.execute(db, await db.get(AsyncTask, UUID(result["task_id"])))
    assert len({model for _, model in seen}) == 2
    assert next(model for name, model in seen if name == "AuditVerdictOutput").startswith(
        "kimi"
    )
    owned = await db.get(CollaborationCase, UUID(case["id"]))
    assert owned.requests_used == len(seen) == 4
