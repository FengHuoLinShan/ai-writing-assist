from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from core.errors import ConflictError, ValidationError
from infrastructure.stable_hash import stable_hash
from modules.writing import candidate_selection as selection
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import WritingDraftCreate, WritingTargetedRevisionOutput
from modules.writing.semantic_review import (
    _apply_targeted_revision_patches,
    validate_candidate_upstream,
)
from modules.writing.services import WritingDraftService


def patches():
    return [
        {"patch_id": "first", "start": 1, "end": 3, "finding_ids": ["f1"]},
        {"patch_id": "last", "start": 5, "end": 6, "finding_ids": ["f2"]},
    ]


def test_revision_groups_preserve_exact_unselected_chinese_emoji_and_repeated_text():
    original = "甲😀乙丙甲😀乙"
    revised, applied = _apply_targeted_revision_patches(
        original,
        patches(),
        WritingTargetedRevisionOutput(
            patches=[
                {"patch_id": "first", "replacement": "坚定的😀乙"},
                {"patch_id": "last", "replacement": "🙂"},
            ],
            groups=[["first"], ["last"]],
        ),
    )
    groups = selection.revision_groups(original, revised, applied)
    assert len(groups) == 2
    assert (
        selection.compose_groups(original, groups, ["group-1"]) == "甲坚定的😀乙丙甲😀乙"
    )
    assert selection.compose_groups(original, groups, ["group-2"]) == "甲😀乙丙甲🙂乙"
    assert selection.compose_groups(original, groups, ["group-1", "group-2"]) == revised
    for invalid in [[], ["missing"], ["group-1", "group-1"]]:
        with pytest.raises(ValidationError):
            selection.compose_groups(original, groups, invalid)
    assert selection.revision_groups(original, revised + "未记录改动", applied)[0][
        "whole_only"
    ]
    assert selection.revision_groups(
        original, revised, [{**applied[0], "source_text": "伪造"}]
    )[0]["whole_only"]


def test_unknown_dependencies_stay_whole_and_invalid_group_partition_fails():
    output = WritingTargetedRevisionOutput(
        patches=[
            {"patch_id": "first", "replacement": "新"},
            {"patch_id": "last", "replacement": "后"},
        ]
    )
    revised, applied = _apply_targeted_revision_patches(
        "甲😀乙丙甲😀乙", patches(), output
    )
    assert len(selection.revision_groups("甲😀乙丙甲😀乙", revised, applied)) == 1
    output.groups = [["first"], ["first", "last"]]
    with pytest.raises(ValidationError, match="修改组"):
        _apply_targeted_revision_patches("甲😀乙丙甲😀乙", patches(), output)


async def setup_candidate(db, novel_id):
    base = await WritingDraftService().create_draft_contract(
        db,
        WritingDraftCreate(
            novel_id=novel_id, chapter_index=1, title="选组", content="甲😀乙丙甲😀乙"
        ),
    )
    output, applied = _apply_targeted_revision_patches(
        base.content,
        patches(),
        WritingTargetedRevisionOutput(
            patches=[
                {"patch_id": "first", "replacement": "坚定的😀乙"},
                {"patch_id": "last", "replacement": "🙂"},
            ],
            groups=[["first"], ["last"]],
        ),
    )
    parent = await WritingDraftRepository().create_with_status(
        db,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=1,
            title="选组",
            content=output,
            provenance_json={
                "source": "writing_comment_revision",
                "context_origin": "manual",
                "base_draft_id": base.id,
                "base_content_hash": base.content_hash,
                "applied_patches": applied,
                "independent_review": {
                    "verdict": "pass",
                    "draft_hash": "old-review",
                    "review_scope": {
                        "cutoff_chapter": 1,
                        "excluded_targets": ["world:excluded"],
                    },
                },
                "knowledge_review": {"status": "passed"},
            },
        ),
        status="candidate",
    )
    return base, parent


@pytest.mark.asyncio
async def test_selection_http_is_project_bound_versioned_and_idempotent(
    async_client, db_session, test_project_id, account_llm_connection
):
    base, parent = await setup_candidate(db_session, test_project_id)
    parent_id = str(parent.id)
    preview = await async_client.get(
        f"/api/writing/drafts/{parent_id}/revision-groups",
        params={"novel_id": test_project_id},
    )
    assert preview.status_code == 200, preview.text
    data = {
        "novel_id": test_project_id,
        "operation_id": str(uuid.uuid4()),
        "expected_preview_hash": preview.json()["preview_hash"],
        "group_ids": ["group-2"],
    }
    path = f"/api/writing/drafts/{parent_id}/revision-selections"
    first = await async_client.post(path, json=data)
    assert first.status_code == 201, first.text
    assert (await async_client.post(path, json=data)).json()["task_id"] == first.json()[
        "task_id"
    ]
    other = (await async_client.post("/api/projects", json={"title": "别的作品"})).json()[
        "id"
    ]
    assert (
        await async_client.get(
            f"/api/writing/drafts/{parent_id}/revision-groups", params={"novel_id": other}
        )
    ).status_code == 404
    assert (
        await async_client.post(
            path,
            json={**data, "operation_id": str(uuid.uuid4()), "group_ids": ["unknown"]},
        )
    ).status_code == 400
    from modules.writing.schemas import WritingDraftUpdate

    await WritingDraftService().update_draft(
        db_session, base.id, WritingDraftUpdate(content="作者并发修改"), test_project_id
    )
    assert (
        await async_client.post(path, json={**data, "operation_id": str(uuid.uuid4())})
    ).status_code == 409
    assert (await async_client.post(path, json=data)).json()["task_id"] == first.json()[
        "task_id"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("review_fails", [False, True])
async def test_composed_candidate_reruns_governance_review_and_keeps_working(
    db_session, test_project_id, monkeypatch, review_fails
):
    base, parent = await setup_candidate(db_session, test_project_id)
    parent_id = str(parent.id)
    preview = await selection.selection_preview(db_session, test_project_id, parent_id)
    world = {"items": [], "omissions": []}

    @asynccontextmanager
    async def client(*_args, **_kwargs):
        yield object()

    async def checkpoint(db, **_kwargs):
        await db.commit()

    async def governed(_client, *, hooks, **_kwargs):
        output = await hooks.generate(None, ())
        assert output == "甲😀乙丙甲🙂乙"
        return SimpleNamespace(
            passed=True, output=output, audit=object(), generator_keys=()
        )

    async def review(_self, db, *, draft_ids, manual_world_scope, **_kwargs):
        assert manual_world_scope.excluded_targets == ["world:excluded"]
        candidate = await WritingDraftRepository().get(db, uuid.UUID(draft_ids[0]))
        assert candidate.provenance_json["independent_review"] is None
        with pytest.raises(ConflictError, match="独立审稿"):
            await validate_candidate_upstream(db, candidate)
        if review_fails:
            raise RuntimeError("审查请求失败")
        candidate.provenance_json = {
            **candidate.provenance_json,
            "independent_review": {
                "draft_hash": candidate.content_hash,
                "verdict": "pass",
                "blocking_count": 0,
                "review_scope": manual_world_scope.model_dump(mode="json"),
                "context_fingerprint": stable_hash(world),
            },
        }
        await db.flush()
        return {"verdict": "pass"}

    async def world_read(*_args, **_kwargs):
        return world

    monkeypatch.setattr(selection, "open_project_snapshot_llm_client", client)
    monkeypatch.setattr(selection, "checkpoint_handler_session", checkpoint)
    monkeypatch.setattr(selection, "run_governed_generation", governed)
    monkeypatch.setattr(
        selection, "knowledge_review_payload", lambda **_kwargs: {"status": "passed"}
    )
    monkeypatch.setattr(
        selection.WritingSemanticWorkflowService, "review_for_task", review
    )
    monkeypatch.setattr(
        "modules.evidence.facade.compile_review_world_evidence", world_read
    )
    task = SimpleNamespace(
        id=uuid.uuid4(),
        meta={
            "novel_id": test_project_id,
            "draft_id": parent_id,
            "selection": True,
            "expected_preview_hash": preview["preview_hash"],
            "group_ids": ["group-2"],
        },
    )
    result = await selection.run_selection_task(db_session, task, {})
    candidate = await WritingDraftRepository().get(
        db_session, uuid.UUID(result["candidate_draft_id"])
    )
    original = await WritingDraftRepository().get(db_session, uuid.UUID(base.id))
    assert original.content == "甲😀乙丙甲😀乙"
    assert candidate.content == "甲😀乙丙甲🙂乙"
    assert candidate.status == "candidate"
    assert candidate.provenance_json["selection_source_draft_id"] == parent_id
    if review_fails:
        assert result["degraded"]
        with pytest.raises(ConflictError, match="独立审稿"):
            await validate_candidate_upstream(db_session, candidate)
    else:
        await validate_candidate_upstream(db_session, candidate)
        adopted = await WritingDraftService().adopt_candidate_to_working_contract(
            db_session, str(candidate.id), test_project_id, idempotency_key="selected"
        )
        replay = await WritingDraftService().adopt_candidate_to_working_contract(
            db_session, str(candidate.id), test_project_id, idempotency_key="selected"
        )
        assert adopted.id == replay.id
        assert adopted.content == "甲😀乙丙甲🙂乙"
