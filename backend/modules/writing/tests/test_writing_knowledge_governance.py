"""Writing 知识治理接入测试：导演审查链路、阻断候选与 POV 截止点硬校验。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from core.errors import ConflictError, ValidationError
from modules.evidence.compilation.knowledge.llm_schemas import (
    AuditDimensionCheck,
    AuditFindingOutput,
    AuditVerdictOutput,
    DirectorShardDisposition,
    DirectorShardPlan,
)
from modules.writing.semantic_review import validate_candidate_upstream
from modules.writing.services import WritingGenerationService
from modules.writing.tests.test_writing_generate_task_transactions import (
    _CheckpointSession,
    _Client,
    _confirmed,
    _patch_facades,
    _repo,
    _snapshot,
)


class _BlockedAuditClient(_Client):
    """导演正常、审查恒 blocker 的合成 client。"""

    async def generate_structured(self, request, schema, **kwargs):  # noqa: ANN001
        if schema is DirectorShardPlan:
            keys = []
            for message in request.messages:
                for line in message.content.splitlines():
                    line = line.strip()
                    if line.startswith("- ") and "|" in line:
                        keys.append(line[2:].split("|")[0].strip())
            return DirectorShardPlan(
                dispositions=[
                    DirectorShardDisposition(
                        source_key=key,
                        disposition="required_for_generation",
                    )
                    for key in keys
                ]
            )
        if schema is AuditVerdictOutput:
            return AuditVerdictOutput(
                findings=[
                    AuditFindingOutput(
                        kind="premature_reveal",
                        severity="blocker",
                        message="正文提前揭示了隐藏事实",
                    )
                ],
                dimensions=[AuditDimensionCheck(dimension="prior_prose", checked=True)],
                verdict="blocked",
            )
        raise AssertionError(f"unexpected schema: {schema}")


class _PartialCoverageAuditClient(_Client):
    """BR-0c：审查自报 pass 但漏报必查维度（只查 prior_prose）的合成 client。"""

    async def generate_structured(self, request, schema, **kwargs):  # noqa: ANN001
        if schema is DirectorShardPlan:
            keys = []
            for message in request.messages:
                for line in message.content.splitlines():
                    line = line.strip()
                    if line.startswith("- ") and "|" in line:
                        keys.append(line[2:].split("|")[0].strip())
            return DirectorShardPlan(
                dispositions=[
                    DirectorShardDisposition(
                        source_key=key,
                        disposition="required_for_generation",
                    )
                    for key in keys
                ]
            )
        if schema is AuditVerdictOutput:
            return AuditVerdictOutput(
                findings=[],
                dimensions=[AuditDimensionCheck(dimension="prior_prose", checked=True)],
                verdict="pass",
            )
        raise AssertionError(f"unexpected schema: {schema}")


def _draft_from(repo: SimpleNamespace) -> SimpleNamespace:
    assert repo.created, "candidate 未创建"
    data = repo.created[0]
    return SimpleNamespace(
        novel_id=data.novel_id,
        content_hash="a" * 64,
        provenance_json=data.provenance_json,
    )


async def test_generation_records_knowledge_review_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    _patch_facades(
        monkeypatch, _confirmed("governed context"), _confirmed("governed context")
    )
    repo = _repo()
    client = _Client(db, "治理通过的正文")
    result = await WritingGenerationService(
        repo=repo, llm_client=client
    ).generate_candidate_for_task(
        db,
        novel_id="11111111-1111-1111-1111-111111111111",
        chapter_index=3,
        title=None,
        instruction=None,
        context_confirmation_id="33333333-3333-3333-3333-333333333333",
        source_task_id="task-1",
        llm_execution_snapshot=_snapshot(),
    )
    assert result.status == "candidate"
    knowledge = repo.created[0].provenance_json["knowledge_review"]
    assert knowledge["status"] == "passed"
    assert knowledge["repaired"] is False
    assert knowledge["scope_receipt_fingerprint"]
    assert knowledge["director_plan_fingerprint"]
    assert knowledge["audit_fingerprint"]
    assert knowledge["stage_trace"] == ["directing", "generating", "reviewing"]


async def test_blocked_knowledge_review_keeps_candidate_unadoptable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    _patch_facades(
        monkeypatch, _confirmed("governed context"), _confirmed("governed context")
    )
    repo = _repo()
    client = _BlockedAuditClient(db, "剧透正文")
    service = WritingGenerationService(repo=repo, llm_client=client)
    await service.generate_candidate_for_task(
        db,
        novel_id="11111111-1111-1111-1111-111111111111",
        chapter_index=3,
        title=None,
        instruction=None,
        context_confirmation_id="33333333-3333-3333-3333-333333333333",
        source_task_id="task-1",
        llm_execution_snapshot=_snapshot(),
    )
    draft = _draft_from(repo)
    assert draft.provenance_json["knowledge_review"]["status"] == "blocked"
    # 正文仍保存为候选（作者可作手工素材），但采用门禁失败关闭
    assert "剧透正文" in repo.created[0].content
    from modules.evidence import facade as evidence_facade

    monkeypatch.setattr(
        evidence_facade,
        "require_fresh_confirmation",
        mock.AsyncMock(),
    )
    with pytest.raises(ConflictError, match="知识审查未通过"):
        await validate_candidate_upstream(None, draft)  # type: ignore[arg-type]


async def test_partial_coverage_pass_is_unverifiable_and_unadoptable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BR-0c：审查者自报 pass 但漏报必查维度 → 候选记为 unverifiable 且不可采用。"""
    db = _CheckpointSession()
    _patch_facades(
        monkeypatch, _confirmed("governed context"), _confirmed("governed context")
    )
    repo = _repo()
    client = _PartialCoverageAuditClient(db, "覆盖不全的正文")
    service = WritingGenerationService(repo=repo, llm_client=client)
    await service.generate_candidate_for_task(
        db,
        novel_id="11111111-1111-1111-1111-111111111111",
        chapter_index=3,
        title=None,
        instruction=None,
        context_confirmation_id="33333333-3333-3333-3333-333333333333",
        source_task_id="task-1",
        llm_execution_snapshot=_snapshot(),
    )
    draft = _draft_from(repo)
    knowledge = draft.provenance_json["knowledge_review"]
    assert knowledge["status"] == "unverifiable"
    coverage = {item["dimension"]: item for item in knowledge["coverage"]}
    omitted = [d for d, item in coverage.items() if item["omitted"]]
    assert omitted, "漏报的必查维度必须在覆盖回执中标明遗漏"
    assert "覆盖不全的正文" in repo.created[0].content
    from modules.evidence import facade as evidence_facade

    monkeypatch.setattr(
        evidence_facade,
        "require_fresh_confirmation",
        mock.AsyncMock(),
    )
    with pytest.raises(ConflictError, match="知识审查未通过"):
        await validate_candidate_upstream(None, draft)  # type: ignore[arg-type]


async def test_pov_character_mode_requires_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    before = _confirmed("POV context", pov=True)
    del before.compile_options["visible_until_scene_id"]
    after = SimpleNamespace(**{**before.__dict__})
    repo = _repo()
    _patch_facades(monkeypatch, before, after)
    with pytest.raises(ValidationError, match="截止点"):
        service = WritingGenerationService(repo=repo, llm_client=_Client(db))
        await service.generate_candidate_for_task(
            db,
            novel_id="11111111-1111-1111-1111-111111111111",
            chapter_index=3,
            title=None,
            instruction=None,
            context_confirmation_id="33333333-3333-3333-3333-333333333333",
            source_task_id="task-1",
            llm_execution_snapshot=_snapshot(),
        )
    repo.create_with_status.assert_not_awaited


def test_author_edit_marks_knowledge_review_stale() -> None:
    from modules.writing.services import (
        _mark_knowledge_review_stale,
        _mark_knowledge_review_stale_in_place,
    )

    provenance = {
        "source": "writing_generate",
        "knowledge_review": {"status": "passed", "issue_counts": {}},
    }
    marked = _mark_knowledge_review_stale(dict(provenance), changed=True)
    assert marked["knowledge_review"]["stale_after_edit"] is True
    assert marked["knowledge_review"]["status"] == "passed", "历史结论保留"
    unchanged = _mark_knowledge_review_stale(dict(provenance), changed=False)
    assert "stale_after_edit" not in unchanged["knowledge_review"]

    draft = SimpleNamespace(provenance_json=dict(provenance))
    _mark_knowledge_review_stale_in_place(draft)
    assert draft.provenance_json["knowledge_review"]["stale_after_edit"] is True

    from modules.writing.schemas import project_writing_draft_state

    projection = project_writing_draft_state("draft", draft.provenance_json)
    assert projection["knowledge_review"]["status"] == "legacy_unchecked"
    assert "knowledge_review_stale" in projection["attention_reasons"]


async def test_director_steps_use_governance_naming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """生成任务内恰好发生导演与审查两次结构化调用（step 命名在 workflow 固定）。"""
    captured: list[type] = []
    db = _CheckpointSession()
    _patch_facades(
        monkeypatch,
        _confirmed("naming context"),
        _confirmed("naming context"),
    )
    repo = _repo()

    class _NamingClient(_Client):
        async def generate_structured(self, request, schema, **kwargs):  # noqa: ANN001
            captured.append(schema)
            return await super().generate_structured(request, schema, **kwargs)

    await WritingGenerationService(
        repo=repo, llm_client=_NamingClient(db, "正文")
    ).generate_candidate_for_task(
        db,
        novel_id="11111111-1111-1111-1111-111111111111",
        chapter_index=3,
        title=None,
        instruction=None,
        context_confirmation_id="33333333-3333-3333-3333-333333333333",
        source_task_id="task-1",
        llm_execution_snapshot=_snapshot(),
    )
    from modules.evidence.compilation.knowledge.llm_schemas import (
        AuditVerdictOutput as _Audit,
    )
    from modules.evidence.compilation.knowledge.llm_schemas import (
        DirectorShardPlan as _Plan,
    )

    assert captured == [_Plan, _Audit]


async def test_blocked_knowledge_review_rejects_adoption_at_service_gate(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
    test_project_id,
) -> None:
    """候选已存但知识审查未通过：服务端采用门禁失败关闭，不产生工作稿。"""
    from modules.writing.models import WritingDraft
    from modules.writing.repositories import WritingDraftRepository
    from modules.writing.schemas import WritingDraftCreate

    candidate = await WritingDraftRepository().create_with_status(
        db_session,
        WritingDraftCreate(
            novel_id=test_project_id,
            chapter_index=1,
            title="阻断候选",
            content="知识审查未通过的候选正文",
            provenance_json={
                "source": "writing_generate",
                "context_confirmation_id": "33333333-3333-3333-3333-333333333333",
                "knowledge_review": {
                    "status": "blocked",
                    "repaired": False,
                    "issue_counts": {"blocker": 1},
                },
            },
        ),
        status="candidate",
    )
    async def accept_candidate(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "modules.writing.semantic_review.validate_candidate_upstream",
        accept_candidate,
    )
    from modules.writing.services import WritingDraftService

    with pytest.raises(ValidationError, match="未通过知识审查"):
        await WritingDraftService().adopt_candidate_to_working(
            db_session,
            str(candidate.id),
            test_project_id,
        )

    stored = await WritingDraftRepository().get(db_session, candidate.id)
    assert stored is not None
    assert stored.status == "candidate"
    import uuid

    from sqlalchemy import select

    drafts = list(
        (
            await db_session.execute(
                select(WritingDraft).where(
                    WritingDraft.novel_id == uuid.UUID(test_project_id),
                    WritingDraft.chapter_index == 1,
                )
            )
        ).scalars()
    )
    assert len(drafts) == 1
