"""Durable understanding must reach a new real task, with no authorization shortcuts."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select

from core.errors import ConflictError
from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.tasks.models import AsyncTask
from modules.collaboration import cases, runtime
from modules.collaboration.cognition import (
    commit_changes,
    correct_record,
    current_records,
    read_head,
    record_ref,
    source_dependency,
)
from modules.collaboration.contracts import (
    CaseCreate,
    CognitionCorrection,
    Grant,
    InputManifest,
    RunCreate,
    SubjectView,
)
from modules.collaboration.models import (
    CognitionCommit,
    CognitionRecord,
    CollaborationCase,
    CollaborationRun,
)
from modules.collaboration.recipes import RECIPES
from modules.collaboration.tests.test_workspaces import setup_trial
from modules.evidence.facade import (
    collect_creative_manifest,
    creative_context_text,
    revalidate_creative_manifest,
)
from modules.writing.facade import create_draft_only


async def seed_understanding(
    db, nid, grant, *, query=None, text="合作并不等于放下戒心。"
):
    manifest = await collect_creative_manifest(db, nid, grant, 1, query=query)
    record_id = uuid4()
    change = {
        "record_id": str(record_id),
        "content": {"schema_version": 1, "kind": "interpretation", "text": text},
        "dependencies": [source_dependency(source) for source in manifest.resources],
        "author_status": "derived",
        "query_dependencies": [
            {"scope_hash": manifest.query_scope_hash, "receipt": manifest.query_receipt}
        ]
        if query
        else [],
        "cognition_refs": [],
    }
    result = await commit_changes(
        db,
        nid,
        operation_id=uuid4(),
        expected_commit_id=manifest.cognition.head_commit_id,
        changes=[change],
        read_set=[manifest.model_dump(mode="json")],
        method_version="test/v1",
    )
    return result, record_id, change


@pytest.mark.parametrize("replace_work", [False, True])
async def test_two_independent_cases_really_consume_durable_understanding(
    db_session,
    test_project_id,
    account_llm_connection,
    monkeypatch,
    async_client,
    replace_work,
):
    db, nid = db_session, test_project_id
    case, _, drafts, _ = await setup_trial(db, nid, monkeypatch)
    row = await db.get(CollaborationCase, UUID(case["id"]))
    row.recipe_json = RECIPES["deep_review"].model_dump(mode="json")
    row.grant_json = {**row.grant_json, "retain_understanding": True}
    grant = Grant.model_validate(row.grant_json)
    monkeypatch.setattr(db, "task_checkpoint_enabled", True, raising=False)
    prompts = []
    understanding = "合作并不等于放下戒心。"

    async def provider(self, request):
        assert not db.in_transaction()
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])["title"]
        user = next(
            message.content for message in request.messages if message.role == "user"
        )
        if schema == "GraphDelta":
            revision = json.loads(user)["expected_plan_revision"]
            result = {
                "expected_plan_revision": revision,
                "reason": "核对动机",
                "finish": revision > int(replace_work),
                "items": []
                if revision > int(replace_work)
                else [
                    {
                        "logical_key": "inspect",
                        "capability": "investigate",
                        "question": "重新核对合作的反证"
                        if revision
                        else "合作意味着什么？",
                    }
                ],
            }
        elif schema == "WorkOutput":
            prompts.append(user)
            text = (
                "她已经毫无保留地信任旧敌。"
                if replace_work and json.loads(user)["question"] == "合作意味着什么？"
                else understanding
            )
            result = {
                "summary": text,
                "claims": [
                    {
                        "kind": "interpretation",
                        "text": text,
                        "evidence_keys": [f"writing_draft:{drafts[0].id}"],
                    }
                ],
            }
        elif schema == "AuditVerdictOutput":
            result = {
                "verdict": "pass",
                "findings": [],
                "dimensions": [
                    {"dimension": name, "checked": True}
                    for name in ("prior_prose", "world_rules", "outline")
                ],
            }
        else:
            raise AssertionError(schema)
        return LLMCallResponse(
            content=json.dumps(result, ensure_ascii=False),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)

    async def execute(case_id):
        submitted = await cases.submit_run(
            db, nid, case_id, RunCreate(operation_id=uuid4(), expected_goal_version=1)
        )
        await db.commit()
        result = await runtime.execute(
            db, await db.get(AsyncTask, UUID(submitted["task_id"]))
        )
        assert result["status"] == "completed"
        return await db.get(CollaborationRun, UUID(submitted["run_id"]))

    first = await execute(case["id"])
    assert first.result_json["understanding"]["outcome"] == "updated"
    saved = (await current_records(db, nid))[0]
    assert len(await current_records(db, nid)) == 1
    assert saved.content_json["text"] == understanding
    first_commit = saved.commit_id
    assert understanding not in prompts[0]
    # Run retention does not own either record or its read-set receipt.
    await db.execute(delete(CollaborationRun).where(CollaborationRun.id == first.id))
    await db.commit()
    assert (await current_records(db, nid))[0].commit_id == first_commit
    second_case = await cases.create_case(
        db,
        nid,
        CaseCreate(
            operation_id=uuid4(),
            goal="继续检查人物合作",
            grant=grant,
            recipe_id="deep_review",
        ),
    )
    second = await execute(second_case["id"])
    assert len(prompts) == 2 * (1 + int(replace_work)) and understanding in prompts[-1]
    assert str(first_commit) in prompts[-1] and str(saved.id) in prompts[-1]
    assert "不作为独立事实证据" in prompts[-1]
    assert second.result_json["understanding"]["outcome"] == "no_change"
    assert (await read_head(db, nid)).commit_id == first_commit
    frozen = InputManifest.model_validate(second.manifest_json)
    assert len(frozen.cognition.records) == 1

    body = {
        "operation_id": str(uuid4()),
        "expected_commit_id": str(first_commit),
        "expected_revision_id": str(saved.id),
        "action": "correct",
        "text": "她只同意交换线索。",
    }
    response = await async_client.post(
        f"/api/collaboration/understanding/{saved.record_id}",
        params={"novel_id": nid},
        json=body,
    )
    assert response.status_code == 200, response.text
    replay = await async_client.post(
        f"/api/collaboration/understanding/{saved.record_id}",
        params={"novel_id": nid},
        json=body,
    )
    assert replay.json()["replayed"] is True
    with pytest.raises(ConflictError, match="理解已被修正"):
        await revalidate_creative_manifest(db, nid, grant, frozen)
    history = await async_client.get(
        f"/api/collaboration/understanding/{saved.record_id}/history",
        params={"novel_id": nid},
    )
    assert {item["text"] for item in history.json()["items"]} == {
        understanding,
        body["text"],
    }
    corrected = await collect_creative_manifest(db, nid, grant, 1)
    assert corrected.cognition.records[0].author_status == "corrected"
    assert corrected.cognition.records[0].content["kind"] == "interpretation"
    assert "尚未经原文语义复核" in creative_context_text(corrected)


async def test_exclusions_cutoffs_source_changes_and_unrelated_commits(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    first = await create_draft_only(db, nid, 1, content="她接受了旧敌的帮助。")
    second = await create_draft_only(db, nid, 2, content="她保留了退路。")
    grant = Grant(
        resources=[{"kind": "writing_draft", "id": first.id}],
        read_scope="project",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    _, _, _ = await seed_understanding(db, nid, grant)
    frozen = await collect_creative_manifest(db, nid, grant, 1)
    await seed_understanding(db, nid, grant, text="另一条无关解释。")
    await revalidate_creative_manifest(db, nid, grant, frozen)
    denied = Grant.model_validate(
        {
            **grant.model_dump(),
            "resources": [{"kind": "writing_draft", "id": second.id}],
            "excluded": [{"kind": "writing_draft", "id": first.id}],
        }
    )
    excluded = await collect_creative_manifest(db, nid, denied, 1)
    assert not excluded.cognition.records
    assert "合作并不等于放下戒心" not in creative_context_text(excluded)
    reader = await collect_creative_manifest(
        db, nid, grant, 1, subject=SubjectView(kind="reader", cutoff_chapter=1)
    )
    assert not reader.cognition.records
    assert "合作并不等于放下戒心" not in creative_context_text(reader)
    await create_draft_only(db, nid, 1, content="她拒绝了旧敌的帮助。")
    fresh_grant = Grant(
        resources=[{"kind": "writing_draft", "id": second.id}],
        read_scope="project",
        expires_at=grant.expires_at,
    )
    current = await collect_creative_manifest(db, nid, fresh_grant, 1)
    assert not current.cognition.records
    assert await db.scalar(select(func.count()).select_from(CognitionRecord)) == 2


async def test_query_dependencies_invalidate_but_positive_sources_remain(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    first = await create_draft_only(db, nid, 1, content="唯一写出的桥在北边。")
    grant = Grant(
        resources=[{"kind": "writing_draft", "id": first.id}],
        read_scope="project",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await seed_understanding(db, nid, grant, text="文中有一座北桥。")
    await seed_understanding(db, nid, grant, query="桥", text="所查范围未写出第二座桥。")
    await create_draft_only(db, nid, 2, content="南方还有另一座桥。")
    new_case = await collect_creative_manifest(db, nid, grant, 1)
    assert [ref.content["text"] for ref in new_case.cognition.records] == [
        "文中有一座北桥。"
    ]
    assert any(
        item["reason"] == "query_scope_changed" for item in new_case.cognition.excluded
    )


async def test_no_change_does_not_advance_head_or_create_record(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    operation = uuid4()
    result = await commit_changes(
        db,
        nid,
        operation_id=operation,
        expected_commit_id=None,
        changes=[],
        read_set=[],
        method_version="test/v1",
    )
    replay = await commit_changes(
        db,
        nid,
        operation_id=operation,
        expected_commit_id=None,
        changes=[],
        read_set=[],
        method_version="test/v1",
    )
    assert result["outcome"] == "no_change" and replay["replayed"]
    assert await read_head(db, nid) is None and not await current_records(db, nid)
    assert await db.scalar(select(func.count()).select_from(CognitionCommit)) == 1


async def test_rechecking_identical_text_repairs_stale_inherited_understanding(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    draft = await create_draft_only(
        db, nid, 1, content="她答应交换线索，却没有交出钥匙。"
    )
    grant = Grant(
        resources=[{"kind": "writing_draft", "id": draft.id}],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    _, aid, _ = await seed_understanding(db, nid, grant, text="她答应合作。")
    a1 = (await current_records(db, nid))[0]
    manifest = await collect_creative_manifest(db, nid, grant, 1)
    b = {
        "record_id": str(uuid4()),
        "content": {"kind": "interpretation", "text": "她保留戒心。"},
        "dependencies": [source_dependency(value) for value in manifest.resources],
        "author_status": "derived",
        "cognition_refs": [record_ref(a1).model_dump(mode="json")],
    }
    await commit_changes(
        db,
        nid,
        operation_id=uuid4(),
        expected_commit_id=(await read_head(db, nid)).commit_id,
        changes=[b],
        read_set=[],
        method_version="test/v1",
    )
    await correct_record(
        db,
        nid,
        aid,
        CognitionCorrection(
            operation_id=uuid4(),
            expected_commit_id=(await read_head(db, nid)).commit_id,
            expected_revision_id=a1.id,
            action="correct",
            text="她只答应交换线索。",
        ),
    )
    current = await collect_creative_manifest(db, nid, grant, 1)
    assert len(current.cognition.records) == 1
    b["cognition_refs"] = [
        value.model_dump(mode="json") for value in current.cognition.records
    ]
    result = await commit_changes(
        db,
        nid,
        operation_id=uuid4(),
        expected_commit_id=(await read_head(db, nid)).commit_id,
        changes=[b],
        read_set=[],
        method_version="test/v1",
    )
    assert result["outcome"] == "updated"
    after = await collect_creative_manifest(db, nid, grant, 1)
    assert len(after.cognition.records) == 2
    b2 = next(
        value
        for value in await current_records(db, nid)
        if str(value.record_id) == b["record_id"]
    )
    assert b2.cognition_refs_json[0]["revision_id"] != str(a1.id)


async def test_repeated_understanding_has_no_cycles_or_context_overflow(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    draft = await create_draft_only(db, nid, 1, content="她没有交出钥匙。")
    grant = Grant(
        resources=[{"kind": "writing_draft", "id": draft.id}],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    changes = []
    for index in range(8):
        _, _, change = await seed_understanding(
            db, nid, grant, text=f"解释{index}：" + "她" * 2990
        )
        changes.append(change)
    manifest = await collect_creative_manifest(db, nid, grant, 1)
    assert 0 < len(manifest.cognition.records) < 8
    assert len(creative_context_text(manifest)) <= 24000
    assert not manifest.cognition.complete
    assert any(
        value["reason"] == "not_selected_capacity"
        for value in manifest.cognition.excluded
    )
    head = (await read_head(db, nid)).commit_id
    for change in changes:
        change["cognition_refs"] = [
            value.model_dump(mode="json") for value in manifest.cognition.records
        ]
    result = await commit_changes(
        db,
        nid,
        operation_id=uuid4(),
        expected_commit_id=head,
        changes=changes,
        read_set=[],
        method_version="test/v1",
    )
    assert result["outcome"] == "no_change"
    assert (await read_head(db, nid)).commit_id == head
    assert all(not value.cognition_refs_json for value in await current_records(db, nid))
    assert len(
        (await collect_creative_manifest(db, nid, grant, 1)).cognition.records
    ) == len(manifest.cognition.records)


def test_legacy_grant_and_frozen_manifest_keep_original_hashes():
    raw_grant = Grant(
        resources=[{"kind": "writing_draft", "id": uuid4()}],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    ).model_dump(mode="json")
    raw_grant.pop("retain_understanding", None)
    assert content_hash(
        Grant.model_validate(raw_grant).model_dump(mode="json")
    ) == content_hash(raw_grant)
    raw_manifest = {
        "protocol": "collaboration_v2",
        "goal_version": 1,
        "grant_hash": content_hash(raw_grant),
        "resources": [],
        "query_receipt": None,
        "query_scope_hash": "a" * 64,
        "workspace_revision_id": None,
        "subject": SubjectView().model_dump(mode="json"),
    }
    restored = InputManifest.model_validate(raw_manifest)
    assert restored.model_dump(mode="json") == raw_manifest
    assert restored.fingerprint == content_hash(raw_manifest)
