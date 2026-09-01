from __future__ import annotations

import json
import uuid
from copy import deepcopy
from types import SimpleNamespace
from unittest import mock

import pytest

from core.errors import ConflictError
from modules.writing.schemas import (
    WritingSemanticReviewRequest,
    WritingTargetedRevisionOutput,
    WritingTargetedRevisionRequest,
    project_writing_draft_state,
)
from modules.writing.semantic_review import (
    WritingSemanticWorkflowService,
    _apply_targeted_revision_patches,
    _review_set_fingerprint,
    _targeted_revision_ranges,
    validate_candidate_upstream,
)


def test_semantic_review_requests_are_bounded_and_deduplicated() -> None:
    request = WritingSemanticReviewRequest(
        novel_id="00000000-0000-0000-0000-000000000001",
        draft_ids=["00000000-0000-0000-0000-000000000002"],
        scope="book",
    )
    assert request.scope == "book"

    with pytest.raises(ValueError, match="draft_ids must be unique"):
        WritingSemanticReviewRequest(
            novel_id=request.novel_id,
            draft_ids=[request.draft_ids[0], request.draft_ids[0]],
        )

    revision = WritingTargetedRevisionRequest(
        novel_id=request.novel_id,
        draft_id=request.draft_ids[0],
        review_task_id="00000000-0000-0000-0000-000000000003",
        finding_ids=["finding_123"],
    )
    assert revision.finding_ids == ["finding_123"]


def test_candidate_projection_exposes_independent_review_gate() -> None:
    pending = project_writing_draft_state(
        "candidate",
        {"source": "writing_generate", "review_required": True},
    )
    assert pending["attention_reasons"] == ["semantic_review_required"]

    blocked = project_writing_draft_state(
        "candidate",
        {
            "source": "writing_generate",
            "review_required": True,
            "independent_review": {
                "verdict": "needs_revision",
                "blocking_count": 2,
            },
        },
    )
    assert blocked["attention_reasons"] == ["semantic_review_blocked"]


@pytest.mark.anyio
async def test_generated_candidate_without_confirmation_fails_closed() -> None:
    draft = SimpleNamespace(
        novel_id="00000000-0000-0000-0000-000000000001",
        content_hash="a" * 64,
        provenance_json={
            "source": "writing_generate",
            "review_required": True,
        },
    )
    with pytest.raises(ConflictError, match="缺少已确认参考资料"):
        await validate_candidate_upstream(None, draft)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_generated_candidate_requires_context_aware_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.evidence import facade as evidence_facade

    fresh = mock.AsyncMock()
    monkeypatch.setattr(evidence_facade, "require_fresh_confirmation", fresh)
    draft = SimpleNamespace(
        novel_id="00000000-0000-0000-0000-000000000001",
        content_hash="a" * 64,
        provenance_json={
            "source": "writing_generate",
            "context_confirmation_id": "00000000-0000-0000-0000-000000000004",
            "review_required": True,
        },
    )
    with pytest.raises(ConflictError, match="独立语义审查"):
        await validate_candidate_upstream(None, draft)  # type: ignore[arg-type]

    draft.provenance_json["independent_review"] = {
        "draft_hash": draft.content_hash,
        "verdict": "pass",
        "blocking_count": 0,
    }
    with pytest.raises(ConflictError, match="旧审查未核对"):
        await validate_candidate_upstream(None, draft)  # type: ignore[arg-type]

    draft.provenance_json["independent_review"].update(
        {
            "context_checked": True,
            "context_fingerprint": "context-fingerprint",
        }
    )
    await validate_candidate_upstream(None, draft)  # type: ignore[arg-type]
    assert fresh.await_count == 3


@pytest.mark.anyio
async def test_review_materializes_context_without_sending_hidden_guard_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.evidence import facade as evidence_facade

    novel_id = "00000000-0000-0000-0000-000000000001"
    confirmation_id = "00000000-0000-0000-0000-000000000004"
    options = {
        "reveal_mode": "character",
        "viewpoint_character_id": "character-1",
        "scene_id": "scene-1",
    }
    confirmed = SimpleNamespace(
        rendered_markdown="秦岚只知道钟楼警报已经响起。",
        compile_options=options,
        confirmation=SimpleNamespace(
            id=confirmation_id,
            action="writing.generate",
            selected_asset_ids={"character": ["character-1"]},
            excluded_asset_ids={"entity": ["hidden-1"]},
            warnings=[],
        ),
    )
    hidden_term = SimpleNamespace(
        phrase="绝密守卫词",
        rule="hidden_truth_match",
        severity="error",
        source_type="core_entity",
        source_id="hidden-1",
        source_label="隐藏事实",
    )
    monkeypatch.setattr(
        evidence_facade,
        "require_fresh_confirmation",
        mock.AsyncMock(),
    )
    monkeypatch.setattr(
        evidence_facade,
        "prepare_confirmed_ai_action",
        mock.AsyncMock(return_value=confirmed),
    )
    monkeypatch.setattr(
        evidence_facade,
        "build_hidden_guard_context",
        mock.AsyncMock(return_value=[hidden_term]),
    )
    draft = SimpleNamespace(
        novel_id=novel_id,
        content="秦岚听见警报后停在钟楼门外。",
        provenance_json={
            "source": "writing_generate",
            "context_confirmation_id": confirmation_id,
            "generation_profile": "pov_character",
            "viewpoint_character_id": "character-1",
            "pov_view": {"pov_state": {"current_intention": "先观察绝密守卫词"}},
        },
    )
    service = WritingSemanticWorkflowService()
    context, _guard_terms = await service._materialize_review_context(
        None,  # type: ignore[arg-type]
        novel_id=novel_id,
        draft=draft,
        provenance=draft.provenance_json,
    )
    item = {
        "draft_id": "00000000-0000-0000-0000-000000000002",
        "chapter_index": 3,
        "title": "第三章",
        "content": draft.content,
        "content_hash": "a" * 64,
        "role": "target",
        "scene_id": "scene-1",
        "scene_execution_bundle": {"execution_contract": {"goal": "查明警报"}},
        "upstream_manifest": [],
        "review_context": context,
    }
    request = service._review_request(
        model="test-model",
        scope="selection",
        chunk=[item],
        adjacent=[],
    )
    payload_text = request.messages[-1].content
    payload = json.loads(payload_text)

    assert "秦岚只知道钟楼警报已经响起" in payload_text
    assert "current_intention" in payload_text
    assert "[已过滤的角色知识]" in payload_text
    assert "查明警报" in payload_text
    assert "绝密守卫词" not in payload_text
    assert "hidden-1" not in payload_text
    assert payload["targets"][0]["review_context"]["knowledge_boundary_checked"] is True
    assert context["context_fingerprint"]


@pytest.mark.anyio
async def test_manual_draft_review_degrades_to_prose_only() -> None:
    service = WritingSemanticWorkflowService()
    context, guard_terms = await service._materialize_review_context(
        None,  # type: ignore[arg-type]
        novel_id="00000000-0000-0000-0000-000000000001",
        draft=SimpleNamespace(content="人工正文"),
        provenance={"source": "manual"},
    )

    assert context["status"] == "not_available"
    assert context["review_mode"] == "prose_only"
    assert context["knowledge_boundary_checked"] is False
    assert guard_terms == ()


def test_review_chunk_budget_counts_context_and_scene_payload() -> None:
    def _item(draft_id: str) -> dict:
        return {
            "draft_id": draft_id,
            "chapter_index": 1,
            "title": None,
            "content": "正文",
            "content_hash": "a" * 64,
            "role": "target",
            "scene_id": None,
            "scene_execution_bundle": {"notes": "y" * 1000},
            "upstream_manifest": [],
            "review_context": {
                "status": "checked",
                "review_mode": "narrative_only",
                "confirmed_context": "x" * 50_000,
                "generation_profile": "default",
                "viewpoint_character_id": None,
                "pov_view": None,
                "knowledge_boundary_checked": False,
                "deterministic_pov_validation": {
                    "status": "passed",
                    "warnings": [],
                    "findings": [],
                },
            },
        }

    chunks = WritingSemanticWorkflowService._chunks(
        [_item(str(uuid.uuid4())), _item(str(uuid.uuid4()))]
    )
    assert [len(chunk) for chunk in chunks] == [1, 1]


def test_deterministic_guard_findings_and_context_drift_are_enforced() -> None:
    target = {
        "draft_id": "00000000-0000-0000-0000-000000000002",
        "chapter_index": 3,
        "content": "她说出了隐藏真相。",
        "content_hash": "a" * 64,
        "scene_execution_bundle_hash": None,
        "role": "target",
        "review_context": {
            "context_fingerprint": "context-a",
            "pov_view": None,
            "deterministic_pov_validation": {
                "status": "failed",
                "warnings": [],
                "findings": [
                    {
                        "rule": "hidden_truth_match",
                        "severity": "error",
                        "field_path": "draft_prose",
                        "generated_excerpt": "她说出了隐藏真相。",
                    }
                ],
            },
        },
    }
    findings = WritingSemanticWorkflowService._deterministic_findings([target])
    assert findings[0]["severity"] == "blocker"
    assert findings[0]["category"] == "pov_boundary"

    changed = deepcopy(target)
    changed["review_context"]["context_fingerprint"] = "context-b"
    assert _review_set_fingerprint([target]) != _review_set_fingerprint([changed])


def test_targeted_revision_changes_only_selected_exact_range() -> None:
    content = "范围外前文。需要修复的句子。范围外后文。"
    ranges = _targeted_revision_ranges(
        [
            {
                "finding_id": "finding-1",
                "location": {"excerpt": "需要修复的句子。"},
            }
        ],
        content,
    )

    revised, applied = _apply_targeted_revision_patches(
        content,
        ranges,
        WritingTargetedRevisionOutput.model_validate(
            {
                "patches": [
                    {
                        "patch_id": "patch-1",
                        "replacement": "已经修复的句子。",
                    }
                ]
            }
        ),
    )

    assert revised == "范围外前文。已经修复的句子。范围外后文。"
    assert content[: ranges[0]["start"]] == revised[: ranges[0]["start"]]
    assert revised.endswith(content[ranges[0]["end"] :])
    assert applied[0]["finding_ids"] == ["finding-1"]


class _TaskDb:
    task_checkpoint_enabled = True

    def __init__(self) -> None:
        self._in_transaction = True

    async def commit(self) -> None:
        self._in_transaction = False

    def in_transaction(self) -> bool:
        return self._in_transaction

    def expire_all(self) -> None:
        return None

    def add(self, _value) -> None:
        return None

    async def flush(self) -> None:
        return None


class _RevisionClient:
    model_name = "test-model"
    profile_summary = {"model": "test-model"}
    runtime_scope = {"profile_source": "test"}

    def __init__(self) -> None:
        self.requests = []

    async def generate_structured(self, request, schema, **_kwargs):
        self.requests.append(request)
        payload = json.loads(request.messages[-1].content)
        if schema.__name__ == "WritingTargetedRevisionOutput":
            return schema.model_validate(
                {
                    "patches": [
                        {
                            "patch_id": item["patch_id"],
                            "replacement": "修订后正文。",
                        }
                        for item in payload["editable_ranges"]
                    ]
                }
            )
        return schema.model_validate(
            {
                "findings": [],
                "not_checked": [],
                "coverage": [
                    {
                        "draft_id": item["draft_id"],
                        "scene_contract": (
                            "checked"
                            if item.get("scene_execution_bundle")
                            else "not_applicable"
                        ),
                        "timeline_location": "checked",
                        "identity_relation": "checked",
                        "ability_world_rule": "checked",
                        "knowledge_boundary": (
                            "checked"
                            if (item.get("review_context") or {}).get(
                                "knowledge_boundary_checked"
                            )
                            else "not_applicable"
                        ),
                    }
                    for item in payload["targets"]
                ],
            }
        )


@pytest.mark.anyio
async def test_review_discards_result_when_context_changes_during_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.project import facade as project_facade

    monkeypatch.setattr(
        project_facade,
        "require_active_project",
        mock.AsyncMock(),
    )
    target = {
        "draft_id": "00000000-0000-0000-0000-000000000002",
        "chapter_index": 3,
        "title": "第三章",
        "content": "正文",
        "content_hash": "a" * 64,
        "status": "candidate",
        "role": "target",
        "source_task_id": "generation-task",
        "scene_id": None,
        "scene_execution_bundle": None,
        "scene_execution_bundle_hash": None,
        "upstream_manifest": [],
        "review_context": {
            "status": "checked",
            "review_mode": "narrative_only",
            "context_fingerprint": "context-before",
            "confirmed_context": "已确认资料",
            "generation_profile": "default",
            "viewpoint_character_id": None,
            "pov_view": None,
            "deterministic_pov_validation": {
                "status": "passed",
                "findings": [],
                "warnings": [],
            },
            "knowledge_boundary_checked": False,
        },
    }
    changed = deepcopy(target)
    changed["review_context"]["context_fingerprint"] = "context-after"
    repo = SimpleNamespace(get_for_update=mock.AsyncMock())
    client = _RevisionClient()
    service = WritingSemanticWorkflowService(repo=repo, llm_client=client)
    freeze = mock.AsyncMock(side_effect=[([target], []), ([changed], [])])
    monkeypatch.setattr(service, "_freeze_review_set", freeze)

    with pytest.raises(ConflictError, match="审查期间正文、AI 参考资料"):
        await service.review_for_task(
            _TaskDb(),  # type: ignore[arg-type]
            task_id="review-task",
            novel_id="00000000-0000-0000-0000-000000000001",
            draft_ids=[target["draft_id"]],
            scope="selection",
            llm_execution_snapshot={"profile": {"model": "test-model"}},
        )

    assert len(client.requests) == 1
    repo.get_for_update.assert_not_awaited()


@pytest.mark.anyio
async def test_manual_review_reports_knowledge_boundary_not_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.project import facade as project_facade

    monkeypatch.setattr(
        project_facade,
        "require_active_project",
        mock.AsyncMock(),
    )
    draft_id = "00000000-0000-0000-0000-000000000002"
    target = {
        "draft_id": draft_id,
        "chapter_index": 3,
        "title": "第三章",
        "content": "人工正文",
        "content_hash": "a" * 64,
        "status": "draft",
        "role": "target",
        "source_task_id": None,
        "scene_id": None,
        "scene_execution_bundle": None,
        "scene_execution_bundle_hash": None,
        "upstream_manifest": [],
        "review_context": {
            "status": "not_available",
            "review_mode": "prose_only",
            "context_fingerprint": None,
            "confirmed_context": None,
            "generation_profile": None,
            "viewpoint_character_id": None,
            "pov_view": None,
            "deterministic_pov_validation": None,
            "knowledge_boundary_checked": False,
        },
    }
    draft = SimpleNamespace(content_hash=target["content_hash"], provenance_json={})
    repo = SimpleNamespace(get_for_update=mock.AsyncMock(return_value=draft))
    service = WritingSemanticWorkflowService(
        repo=repo,
        llm_client=_RevisionClient(),
    )
    freeze = mock.AsyncMock(side_effect=[([target], []), ([target], [])])
    monkeypatch.setattr(service, "_freeze_review_set", freeze)

    result = await service.review_for_task(
        _TaskDb(),  # type: ignore[arg-type]
        task_id="review-task",
        novel_id="00000000-0000-0000-0000-000000000001",
        draft_ids=[draft_id],
        scope="selection",
        llm_execution_snapshot={"profile": {"model": "test-model"}},
    )

    assert result["verdict"] == "pass"
    assert result["coverage"]["context_not_checked_draft_ids"] == [draft_id]
    assert any("未检查角色知识边界" in item for item in result["not_checked"])
    assert draft.provenance_json["independent_review"]["context_checked"] is False


@pytest.mark.anyio
async def test_review_without_structured_coverage_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.project import facade as project_facade

    monkeypatch.setattr(
        project_facade,
        "require_active_project",
        mock.AsyncMock(),
    )
    draft_id = "00000000-0000-0000-0000-000000000002"
    target = {
        "draft_id": draft_id,
        "chapter_index": 3,
        "title": "第三章",
        "content": "冻结正文",
        "content_hash": "a" * 64,
        "status": "candidate",
        "role": "target",
        "source_task_id": "generation-task",
        "scene_id": None,
        "scene_execution_bundle": None,
        "scene_execution_bundle_hash": None,
        "upstream_manifest": [],
        "review_context": {
            "status": "checked",
            "review_mode": "narrative_only",
            "context_fingerprint": "context-fingerprint",
            "confirmed_context": "已确认资料",
            "generation_profile": "default",
            "viewpoint_character_id": None,
            "pov_view": None,
            "deterministic_pov_validation": {
                "status": "passed",
                "findings": [],
                "warnings": [],
            },
            "knowledge_boundary_checked": False,
        },
    }
    draft = SimpleNamespace(content_hash=target["content_hash"], provenance_json={})
    repo = SimpleNamespace(get_for_update=mock.AsyncMock(return_value=draft))
    client = _RevisionClient()

    async def without_coverage(request, schema, **_kwargs):
        client.requests.append(request)
        return schema.model_validate({"findings": [], "not_checked": []})

    client.generate_structured = without_coverage
    service = WritingSemanticWorkflowService(repo=repo, llm_client=client)
    monkeypatch.setattr(
        service,
        "_freeze_review_set",
        mock.AsyncMock(side_effect=[([target], []), ([target], [])]),
    )

    result = await service.review_for_task(
        _TaskDb(),  # type: ignore[arg-type]
        task_id="review-task",
        novel_id="00000000-0000-0000-0000-000000000001",
        draft_ids=[draft_id],
        scope="selection",
        llm_execution_snapshot={"profile": {"model": "test-model"}},
    )

    assert result["verdict"] == "incomplete"
    assert result["coverage"]["incomplete_draft_ids"] == [draft_id]
    assert draft.provenance_json["independent_review"]["verdict"] == "incomplete"


@pytest.mark.anyio
async def test_review_rejects_coverage_from_another_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.project import facade as project_facade

    monkeypatch.setattr(project_facade, "require_active_project", mock.AsyncMock())
    draft_ids = [
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000003",
    ]
    targets = [
        {
            "draft_id": draft_id,
            "chapter_index": index,
            "title": f"第{index}章",
            "content": f"第{index}章冻结正文",
            "content_hash": str(index) * 64,
            "status": "candidate",
            "role": "target",
            "source_task_id": "generation-task",
            "scene_id": None,
            "scene_execution_bundle": None,
            "scene_execution_bundle_hash": None,
            "upstream_manifest": [],
            "review_context": {
                "status": "checked",
                "review_mode": "narrative_only",
                "context_fingerprint": f"context-{index}",
                "confirmed_context": "已确认资料",
                "generation_profile": "default",
                "viewpoint_character_id": None,
                "pov_view": None,
                "deterministic_pov_validation": {
                    "status": "passed",
                    "findings": [],
                    "warnings": [],
                },
                "knowledge_boundary_checked": False,
            },
        }
        for index, draft_id in enumerate(draft_ids, start=1)
    ]
    drafts = {
        item["draft_id"]: SimpleNamespace(
            content_hash=item["content_hash"],
            provenance_json={},
        )
        for item in targets
    }

    class CrossChunkClient(_RevisionClient):
        async def generate_structured(self, request, schema, **_kwargs):
            self.requests.append(request)
            current_id = json.loads(request.messages[-1].content)["targets"][0][
                "draft_id"
            ]
            other_id = draft_ids[1] if current_id == draft_ids[0] else draft_ids[0]
            return schema.model_validate(
                {
                    "findings": [],
                    "not_checked": [],
                    "coverage": [
                        {
                            "draft_id": other_id,
                            "scene_contract": "not_applicable",
                            "timeline_location": "checked",
                            "identity_relation": "checked",
                            "ability_world_rule": "checked",
                            "knowledge_boundary": "not_applicable",
                        }
                    ],
                }
            )

    async def get_for_update(_db, draft_uuid):
        return drafts[str(draft_uuid)]

    service = WritingSemanticWorkflowService(
        repo=SimpleNamespace(get_for_update=get_for_update),
        llm_client=CrossChunkClient(),
    )
    monkeypatch.setattr(
        service,
        "_freeze_review_set",
        mock.AsyncMock(side_effect=[(targets, []), (targets, [])]),
    )
    monkeypatch.setattr(
        service,
        "_chunks",
        lambda items, adjacent=None: [[items[0]], [items[1]]],
    )

    result = await service.review_for_task(
        _TaskDb(),  # type: ignore[arg-type]
        task_id="review-task",
        novel_id="00000000-0000-0000-0000-000000000001",
        draft_ids=draft_ids,
        scope="selection",
        llm_execution_snapshot={"profile": {"model": "test-model"}},
    )

    assert result["verdict"] == "incomplete"
    assert result["coverage"]["incomplete_draft_ids"] == draft_ids
    assert all(
        draft.provenance_json["independent_review"]["verdict"] == "incomplete"
        for draft in drafts.values()
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("frozen_context", "final_context", "expected"),
    [
        (None, "context-fingerprint", "old_review"),
        ("context-fingerprint", "context-fingerprint", "success"),
        ("context-fingerprint", "changed-context", "drift"),
    ],
)
async def test_targeted_revision_requires_and_reuses_review_context(
    monkeypatch: pytest.MonkeyPatch,
    frozen_context: str | None,
    final_context: str,
    expected: str,
) -> None:
    import modules.writing.semantic_review as semantic_module
    from infrastructure.tasks import facade as task_facade
    from modules.project import facade as project_facade

    novel_id = "00000000-0000-0000-0000-000000000001"
    draft_id = "00000000-0000-0000-0000-000000000002"
    review_task_id = "00000000-0000-0000-0000-000000000003"
    base = SimpleNamespace(
        id=uuid.UUID(draft_id),
        novel_id=uuid.UUID(novel_id),
        chapter_index=3,
        title="第三章",
        content="原始正文。",
        content_hash="a" * 64,
        status="candidate",
        provenance_json={
            "source": "writing_generate",
            "context_confirmation_id": ("00000000-0000-0000-0000-000000000004"),
            "generation_profile": "pov_character",
            "viewpoint_character_id": "character-1",
            "pov_view": {"pov_state": {"current_intention": "旧目标"}},
            "review_required": True,
        },
    )
    review_result = {
        "findings": [
            {
                "finding_id": "finding-1",
                "severity": "major",
                "location": {
                    "draft_id": draft_id,
                    "chapter_index": 3,
                    "excerpt": "原始正文。",
                },
                "preserve": ["保留钟楼警报"],
            }
        ],
        "frozen_manifest": [
            {
                "draft_id": draft_id,
                "content_hash": base.content_hash,
                "scene_execution_bundle_hash": None,
                "context_fingerprint": frozen_context,
            }
        ],
    }
    monkeypatch.setattr(
        task_facade,
        "get_completed_task_payload",
        mock.AsyncMock(return_value=SimpleNamespace(result=review_result)),
    )
    monkeypatch.setattr(
        project_facade,
        "require_active_project",
        mock.AsyncMock(),
    )
    monkeypatch.setattr(
        semantic_module,
        "validate_candidate_upstream",
        mock.AsyncMock(),
    )
    monkeypatch.setattr(
        semantic_module,
        "_scene_bundle",
        mock.AsyncMock(return_value=None),
    )
    created = []

    async def _create(_db, data, *, status):
        created.append(data)
        return SimpleNamespace(
            id=uuid.UUID("00000000-0000-0000-0000-000000000005"),
            novel_id=uuid.UUID(data.novel_id),
            chapter_index=data.chapter_index,
            title=data.title,
            content=data.content,
            content_hash="b" * 64,
            version_number=2,
            status=status,
            conflict_check_snapshot_json=None,
            provenance_json=data.provenance_json,
            created_at=None,
            updated_at=None,
        )

    repo = SimpleNamespace(
        get=mock.AsyncMock(return_value=base),
        get_for_update=mock.AsyncMock(return_value=base),
        create_with_status=mock.AsyncMock(side_effect=_create),
    )
    client = _RevisionClient()
    service = WritingSemanticWorkflowService(repo=repo, llm_client=client)
    term = SimpleNamespace(
        phrase="绝密守卫词",
        rule="hidden_truth_match",
        severity="error",
        source_type="core_entity",
        source_id="hidden-1",
        source_label="隐藏事实",
    )
    context = {
        "status": "checked",
        "review_mode": "character_knowledge",
        "context_fingerprint": "context-fingerprint",
        "hidden_guard_fingerprint": "guard-fingerprint",
        "confirmed_context": "锁定资料：秦岚只知道钟楼警报。",
        "generation_profile": "pov_character",
        "viewpoint_character_id": "character-1",
        "pov_view": base.provenance_json["pov_view"],
        "deterministic_pov_validation": {
            "status": "passed",
            "findings": [],
            "warnings": [],
        },
        "knowledge_boundary_checked": True,
    }
    final_materialized = {**context, "context_fingerprint": final_context}
    materialize = mock.AsyncMock(
        side_effect=[(context, (term,)), (final_materialized, (term,))]
    )
    monkeypatch.setattr(service, "_materialize_review_context", materialize)

    if expected == "old_review":
        with pytest.raises(ConflictError, match="旧审查未冻结"):
            await service.revise_for_task(
                _TaskDb(),  # type: ignore[arg-type]
                task_id="revision-task",
                novel_id=novel_id,
                draft_id=draft_id,
                review_task_id=review_task_id,
                finding_ids=["finding-1"],
                instruction=None,
                llm_execution_snapshot={"profile": {"model": "test-model"}},
            )
        assert client.requests == []
        return

    if expected == "drift":
        with pytest.raises(ConflictError, match="返修期间 AI 参考资料已变化"):
            await service.revise_for_task(
                _TaskDb(),  # type: ignore[arg-type]
                task_id="revision-task",
                novel_id=novel_id,
                draft_id=draft_id,
                review_task_id=review_task_id,
                finding_ids=["finding-1"],
                instruction=None,
                llm_execution_snapshot={"profile": {"model": "test-model"}},
            )
        assert len(client.requests) == 1
        assert created == []
        return

    result = await service.revise_for_task(
        _TaskDb(),  # type: ignore[arg-type]
        task_id="revision-task",
        novel_id=novel_id,
        draft_id=draft_id,
        review_task_id=review_task_id,
        finding_ids=["finding-1"],
        instruction="只改问题段落",
        llm_execution_snapshot={"profile": {"model": "test-model"}},
    )

    assert result.status == "candidate"
    assert "锁定资料：秦岚只知道钟楼警报" in client.requests[0].messages[-1].content
    provenance = created[0].provenance_json
    assert provenance["source_review_context_fingerprint"] == frozen_context
    assert provenance["pov_view"] is None
    assert provenance["pov_validation"]["status"] == "passed"
    assert provenance["independent_review"] is None
    assert materialize.await_count == 2
