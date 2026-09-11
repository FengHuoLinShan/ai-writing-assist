from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from modules.imports.review_resolution import evidence_for_judgment, run_resolution
from modules.imports.review_resolution_schemas import (
    CandidateJudgment,
    ReviewJudgments,
    ReviewResolutionRequest,
    judgment_outcome,
)
from modules.imports.workflow_schemas import DeepImportProgress


def judgment(**changes):
    return CandidateJudgment.model_validate(
        {
            "candidate_key": "candidate-1",
            "support": "explicit",
            "identity": "unique",
            "persistence": "stable",
            "confidence": 0.95,
            "field_evidence": {"alias": [{"evidence_key": "e1", "quote": "简称北港"}]},
            "explanation": "原文明示简称",
            **changes,
        }
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, "eligible"),
        ({"identity": "secret"}, "decision"),
        ({"identity": "ambiguous"}, "decision"),
        ({"support": "conflict"}, "decision"),
        ({"persistence": "ended"}, "decision"),
        ({"persistence": "episodic"}, "optional"),
        ({"identity": "generic"}, "optional"),
        ({"support": "inference"}, "optional"),
        ({"confidence": 0.0}, "optional"),
        ({"uncertainties": ["归属不清"]}, "optional"),
    ],
)
def test_judgments_do_not_equate_confidence_with_admission(changes, expected):
    assert (
        judgment_outcome(
            judgment(**changes), required_fields={"alias"}, valid_evidence=True
        )[0]
        == expected
    )
    assert (
        judgment_outcome(
            judgment(**changes), required_fields={"alias"}, valid_evidence=False
        )[0]
        == "incomplete"
    )


def test_every_nonempty_field_needs_evidence_and_duplicate_keys_fail():
    assert (
        judgment_outcome(
            judgment(), required_fields={"alias", "summary"}, valid_evidence=True
        )[0]
        == "optional"
    )
    with pytest.raises(ValidationError):
        ReviewJudgments(judgments=[judgment(), judgment()])
    with pytest.raises(ValidationError):
        ReviewResolutionRequest(novel_id="p", authorization_confirmed=False)


def test_quotes_must_match_unique_supplied_source():
    selected, valid = evidence_for_judgment(
        judgment(),
        [{"key": "e1", "text": "此地简称北港。", "source_ref": {"draft_id": "d"}}],
    )
    assert valid and len(selected) == 1
    assert not evidence_for_judgment(judgment(), [])[1]
    assert not evidence_for_judgment(
        judgment(),
        [{"key": "e1", "text": "简称北港简称北港", "source_ref": {"chapter_index": 1}}],
    )[1]


async def test_resume_uses_saved_judgment_without_another_provider_call(monkeypatch):
    from modules.imports import review_resolution as module

    row = {
        "key": "candidate-1",
        "kind": "alias",
        "entity_id": "owner",
        "fields": {"alias": "北港"},
        "required_fields": ["alias"],
        "identities": [{"id": "owner", "name": "北港市"}],
        "fingerprint": "f",
        "meta": {"scene_id": "scene"},
        "protected": False,
    }
    evidence = [
        {"key": "e1", "text": "此地简称北港。", "source_ref": {"chapter_index": 1}}
    ]
    permission = {
        "version": module.VERSION,
        "items": [row],
        "authorization_id": "auth",
        "prompt_manifest": module.prompt_manifest(),
        "source_manifest": {"d": "hash"},
        "chapter_from": 1,
        "chapter_to": 1,
    }
    progress = DeepImportProgress(
        authorization_snapshot={"review_resolution": permission}
    )
    calls = []

    async def judge(*args, **kwargs):
        calls.append(1)
        return ReviewJudgments(judgments=[judgment()])

    monkeypatch.setattr(module, "audited_judgment", judge)
    monkeypatch.setattr(
        "modules.evidence.facade.read_review_resolution_sources",
        AsyncMock(return_value=evidence),
    )
    client = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(
        "modules.project.facade.create_project_snapshot_llm_client",
        lambda *args, **kwargs: client,
    )
    task = SimpleNamespace(id="task", meta={"novel_id": "project"})
    checkpoint = AsyncMock()
    await run_resolution(
        None, task=task, progress=progress, checkpoint=checkpoint, project_settings={}
    )
    assert progress.review_resolution["counts"] == {"optional": 1}
    assert progress.review_resolution["groups"][0]["reason"] == "quality_not_qualified"
    await run_resolution(
        None, task=task, progress=progress, checkpoint=checkpoint, project_settings={}
    )
    assert len(calls) == 1
    assert progress.review_resolution["requests"] == 1


def test_problem_grouping_does_not_merge_unrelated_people_or_ordinary_facts():
    from modules.imports.review_resolution import validated_problem_groups
    from modules.imports.review_resolution_schemas import ReviewProblemGroup

    first = judgment(candidate_key="a", identity="ambiguous")
    second = judgment(candidate_key="b", identity="ambiguous")
    output = ReviewJudgments(
        judgments=[first, second],
        groups=[
            ReviewProblemGroup(
                candidate_keys=["a", "b"],
                question="两个称呼是否同一个人？",
                common_basis="同一身份线索",
            )
        ],
    )
    rows = [
        {"key": "a", "identities": [{"id": "p1"}]},
        {"key": "b", "identities": [{"id": "p2"}]},
    ]
    assert validated_problem_groups(output, rows) == {}
    rows[1]["identities"] = [{"id": "p1"}]
    assert set(validated_problem_groups(output, rows)) == {"a", "b"}
    output.judgments[1] = judgment(candidate_key="b")
    assert validated_problem_groups(output, rows) == {}


async def test_schema_repair_uses_shared_budget_and_resumes_from_saved_step(monkeypatch):
    from infrastructure.llm.errors import LLMInvalidResponseError
    from modules.imports.review_resolution import initial_group_judgment

    calls = []

    async def audit(*args, **kwargs):
        calls.append(kwargs["stage"])
        if len(calls) == 1:
            raise LLMInvalidResponseError(
                "invalid enum", raw_response='{"support":"wrong"}'
            )
        return ReviewJudgments(judgments=[judgment()])

    monkeypatch.setattr("modules.imports.review_resolution.audited_judgment", audit)
    group = {"requests": 0}
    state = {"requests": 0}
    output = await initial_group_judgment(
        None,
        task=None,
        client=None,
        rows=[],
        evidence=[],
        group=group,
        state=state,
        save=AsyncMock(),
    )
    assert output.judgments[0].support == "explicit"
    assert calls == ["review", "revise", "verify"]
    assert group["requests"] == state["requests"] == 3
    await initial_group_judgment(
        None,
        task=None,
        client=None,
        rows=[],
        evidence=[],
        group=group,
        state=state,
        save=AsyncMock(),
    )
    assert len(calls) == 3


def test_supplement_does_not_requery_a_smaller_excerpt_of_existing_source():
    from modules.imports.review_resolution import is_new_source

    full = {
        "key": "full",
        "source_ref": {
            "draft_id": "d",
            "source_hash": "hash",
            "start_offset": 0,
            "end_offset": 100,
        },
    }
    subset = {
        "key": "different-search-key",
        "source_ref": {
            "draft_id": "d",
            "source_hash": "hash",
            "start_offset": 20,
            "end_offset": 50,
        },
    }
    assert not is_new_source(subset, [full])
    assert is_new_source(
        {"source_ref": {**subset["source_ref"], "draft_id": "another"}}, [full]
    )


def test_qualification_is_not_inherited_after_prompt_or_model_change(monkeypatch):
    from modules.imports import review_resolution_quality as quality

    monkeypatch.setattr(
        quality, "QUALIFIED_RUNS", {("prompt", "provider", "model"): frozenset({"alias"})}
    )
    assert quality.qualified(
        "alias", prompt_hash="prompt", profile_hash="provider", model="model"
    )
    assert not quality.qualified(
        "alias", prompt_hash="new-prompt", profile_hash="provider", model="model"
    )
    assert not quality.qualified(
        "alias", prompt_hash="prompt", profile_hash="provider", model="other"
    )
