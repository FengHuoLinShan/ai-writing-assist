from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from infrastructure.llm.errors import LLMTimeoutError
from modules.world.entity_fusion import (
    EntityFusionDecision,
    WorldEntityFusionService,
    _pair_similarity,
    _workflow_dedup_groups,
)
from modules.world.models import Character, CoreEntity, EntityRelation
from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import CoreEntityCreate, EntityFusionApplyItem

pytestmark = [pytest.mark.asyncio]


async def test_entity_fusion_evidence_uses_context_planner_with_entity_anchors(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _fusion_entity(name="克莱恩", summary="占卜家")
    target = _fusion_entity(name="道恩·唐泰斯", summary="值夜者")
    source.id = uuid.uuid4()
    target.id = uuid.uuid4()
    captured = {}

    async def retrieve(_db, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            rag_chunks=[
                {
                    "source_ref": {"draft_id": "draft-1"},
                    "chapter_index": 3,
                    "scene_refs": [],
                    "text": "两人在值夜者会面。",
                }
            ]
        )

    monkeypatch.setattr(
        "modules.context.facade.retrieve_planned_context_evidence",
        retrieve,
    )

    evidence = await WorldEntityFusionService()._evidence(
        db_session,
        str(uuid.uuid4()),
        source,
        target,
    )

    assert captured["retrieval_purpose"] == "world_fusion"
    assert captured["entity_ids"] == [str(source.id), str(target.id)]
    assert evidence[0]["snippet"] == "两人在值夜者会面。"


async def test_entity_fusion_evidence_propagates_database_failures(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _fusion_entity(name="克莱恩", summary="占卜家")
    target = _fusion_entity(name="道恩·唐泰斯", summary="值夜者")
    source.id = uuid.uuid4()
    target.id = uuid.uuid4()

    async def fail_retrieval(*_args, **_kwargs):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(
        "modules.context.facade.retrieve_planned_context_evidence",
        fail_retrieval,
    )

    with pytest.raises(SQLAlchemyError, match="database unavailable"):
        await WorldEntityFusionService()._evidence(
            db_session,
            str(uuid.uuid4()),
            source,
            target,
        )


async def test_entity_fusion_service_has_no_direct_http_exception_dependency() -> None:
    source = (Path(__file__).resolve().parents[1] / "entity_fusion.py").read_text()

    assert "from fastapi import HTTPException" not in source
    assert "raise HTTPException" not in source


async def _create_entity(
    db: AsyncSession,
    novel_id: str,
    *,
    name: str,
    status: str,
    entity_type: str = "character",
    summary: str | None = None,
) -> str:
    repo = CoreEntityRepository()
    entity = await repo.create(
        db,
        uuid.UUID(hex=novel_id),
        CoreEntityCreate(
            name=name,
            entity_type=entity_type,
            summary=summary if summary is not None else f"{name} 摘要",
            status=status,
        ),
    )
    return str(entity.id)


def _fusion_entity(
    *,
    name: str,
    aliases: list[str] | None = None,
    summary: str | None = None,
) -> CoreEntity:
    return CoreEntity(
        name=name,
        entity_type="character",
        status="draft",
        summary=summary,
        content_json={
            "aliases": [{"alias": alias, "type": "name"} for alias in aliases or []]
        },
    )


async def test_pair_similarity_short_circuits_normalized_exact_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_summary_similarity(*args: object, **kwargs: object) -> float:
        raise AssertionError("exact name pair should not compare summaries")

    monkeypatch.setattr(
        "modules.world.entity_fusion._summary_similarity",
        fail_summary_similarity,
    )

    score, method = _pair_similarity(
        _fusion_entity(name=" 克莱恩 "),
        _fusion_entity(name="克莱恩"),
    )

    assert (score, method) == (1.0, "normalized_exact_name")


async def test_workflow_scan_only_recall_pairs_from_untouched_current_candidates(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    repo = CoreEntityRepository()
    entity_ids = [
        await _create_entity(
            db_session,
            project_novel_id,
            name="林七",
            status="candidate",
        )
        for _ in range(4)
    ]
    for index, entity_id in enumerate(entity_ids):
        entity = await repo.get(db_session, uuid.UUID(entity_id))
        assert entity is not None
        entity.content_json = {
            "aliases": [
                {"alias": f"已确认-{index}", "status": "canonical"},
                {"alias": f"待复核-{index}", "status": "candidate"},
            ],
            "_meta": {
                "source": "deep_import",
                "workflow_id": "wf-current" if index != 2 else "wf-old",
                "user_edited": index == 3,
            },
        }
    await db_session.flush()

    plan = await WorldEntityFusionService()._prepare_task_scan(
        db_session,
        novel_id=project_novel_id,
        entity_type=None,
        status="candidate",
        limit=20,
        max_suggestions=20,
        workflow_id="wf-current",
    )

    assert plan.total_entities_scanned == 2
    assert plan.candidate_pair_count == 1
    assert {
        plan.pairs[0].source.id,
        plan.pairs[0].target.id,
    } == set(entity_ids[:2])
    assert all(
        all(alias.startswith("已确认-") for alias in entity.aliases)
        for entity in (plan.pairs[0].source, plan.pairs[0].target)
    )


async def test_workflow_dedup_threshold_primary_and_conflict_inputs() -> None:
    def decision(
        source_id: str,
        target_id: str,
        *,
        action: str,
        confidence: float,
        source_chapter: int,
        target_chapter: int,
    ) -> dict:
        return {
            "action": action,
            "confidence": confidence,
            "source_entity_id": source_id,
            "source_entity_name": source_id,
            "target_entity_id": target_id,
            "target_entity_name": target_id,
            "source_snapshot": {
                "source_chapter_index": source_chapter,
                "source_scene_index": 1,
            },
            "target_snapshot": {
                "source_chapter_index": target_chapter,
                "source_scene_index": 1,
            },
            "source_semantic_fingerprint": f"s-{source_id}",
            "target_semantic_fingerprint": f"s-{target_id}",
            "source_execution_fingerprint": f"e-{source_id}",
            "target_execution_fingerprint": f"e-{target_id}",
        }

    decisions = [
        decision(
            "a",
            "b",
            action="merge",
            confidence=0.80,
            source_chapter=3,
            target_chapter=2,
        ),
        decision(
            "b",
            "c",
            action="alias_only",
            confidence=0.91,
            source_chapter=2,
            target_chapter=1,
        ),
        decision(
            "a",
            "c",
            action="needs_review",
            confidence=0.79,
            source_chapter=3,
            target_chapter=1,
        ),
        decision(
            "x",
            "y",
            action="merge",
            confidence=0.799,
            source_chapter=1,
            target_chapter=1,
        ),
    ]

    groups, review, kept = _workflow_dedup_groups(decisions)

    assert len(groups) == 1
    assert groups[0]["primary_entity_id"] == "c"
    assert {item["source_entity_id"] for item in groups[0]["operations"]} == {
        "a",
        "b",
    }
    assert {(item["source_entity_id"], item["target_entity_id"]) for item in review} == {
        ("a", "c"),
        ("x", "y"),
    }
    assert kept == []


async def test_workflow_dedup_done_checkpoint_skips_llm_when_state_is_unchanged(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    db_session.task_inline_execution_enabled = True
    service = WorldEntityFusionService()
    service._workflow_state_fingerprint = mock.AsyncMock(return_value="stable-state")
    service.suggest_for_task = mock.AsyncMock()

    result = await service.dedupe_workflow_candidates_for_task(
        db_session,
        novel_id=project_novel_id,
        workflow_id="workflow-1",
        checkpoint_callback=mock.MagicMock(),
        llm_execution_snapshot={"provider": "test"},
        previous_checkpoint={
            "version": "deep-import-workflow-candidate-dedup-v1",
            "workflow_id": "workflow-1",
            "stage": "done",
            "state_fingerprint": "stable-state",
            "result": {"auto_merged": 2, "review_required": 1},
        },
    )

    assert result == {
        "auto_merged": 2,
        "review_required": 1,
        "checkpoint_reused": True,
    }
    service.suggest_for_task.assert_not_awaited()


async def test_pair_similarity_short_circuits_alias_name_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_summary_similarity(*args: object, **kwargs: object) -> float:
        raise AssertionError("alias pair should not compare summaries")

    monkeypatch.setattr(
        "modules.world.entity_fusion._summary_similarity",
        fail_summary_similarity,
    )

    score, method = _pair_similarity(
        _fusion_entity(name="周明瑞"),
        _fusion_entity(name="克莱恩", aliases=["周明瑞"]),
    )

    assert (score, method) == (0.99, "alias_name_match")


async def test_pair_similarity_keeps_summary_comparison_for_substring_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def count_summary_similarity(left: str | None, right: str | None) -> float:
        nonlocal calls
        calls += 1
        assert left == "source summary"
        assert right == "target summary"
        return 0.91

    monkeypatch.setattr(
        "modules.world.entity_fusion._summary_similarity",
        count_summary_similarity,
    )

    score, method = _pair_similarity(
        _fusion_entity(name="林七", summary="source summary"),
        _fusion_entity(name="林七长老", summary="target summary"),
    )

    assert calls == 1
    assert (score, method) == (0.91, "summary_overlap")


async def test_entity_fusion_ambiguous_pair_uses_managed_llm() -> None:
    source = _fusion_entity(name="林七", summary="来源摘要")
    target = _fusion_entity(name="林七长老", summary="目标摘要")
    decision = EntityFusionDecision(
        action="alias_only",
        confidence=0.93,
        reason="LLM 判定为别名",
        alias="林七",
    )
    client = mock.MagicMock(model_name="test-model")

    with mock.patch(
        "modules.world.entity_fusion.run_managed_structured",
        autospec=True,
        return_value=decision,
    ) as run_structured:
        result = await WorldEntityFusionService(llm_client=client)._decide(
            source,
            target,
            {"similarity_score": 0.88, "match_method": "substring_name"},
            [{"source_type": "entity_summary", "snippet": "当前证据"}],
        )

    assert result == decision
    run_structured.assert_awaited_once()
    request = run_structured.await_args.args[1]
    assert request.model == "test-model"
    assert "当前证据" in request.messages[1].content


async def test_entity_fusion_llm_failure_does_not_log_provider_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-should-never-appear"

    async def fail_llm(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError(f"provider rejected {secret}")

    with (
        mock.patch(
            "modules.world.entity_fusion.run_managed_structured",
            autospec=True,
            side_effect=fail_llm,
        ),
        caplog.at_level(logging.WARNING, logger="modules.world.entity_fusion"),
    ):
        result = await WorldEntityFusionService(
            llm_client=mock.MagicMock(model_name="test-model")
        )._decide(
            _fusion_entity(name="林七"),
            _fusion_entity(name="林七长老"),
            {"similarity_score": 0.88, "match_method": "substring_name"},
            [],
        )

    assert result.action == "needs_review"
    assert secret not in caplog.text
    assert "RuntimeError" in caplog.text


async def test_task_entity_fusion_propagates_retryable_provider_failure() -> None:
    timeout = LLMTimeoutError("provider timed out")

    with mock.patch(
        "modules.world.entity_fusion.run_managed_structured",
        autospec=True,
        side_effect=timeout,
    ):
        with pytest.raises(LLMTimeoutError) as exc_info:
            await WorldEntityFusionService(
                llm_client=mock.MagicMock(model_name="test-model")
            )._decide(
                _fusion_entity(name="林七"),
                _fusion_entity(name="林七长老"),
                {"similarity_score": 0.88, "match_method": "substring_name"},
                [],
                allow_degraded=False,
            )

    assert exc_info.value is timeout


async def test_entity_fusion_alias_only_persists_alias(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    source_id = await _create_entity(
        db_session,
        project_novel_id,
        name="周明瑞",
        status="draft",
    )
    target_id = await _create_entity(
        db_session,
        project_novel_id,
        name="克莱恩",
        status="canonical",
    )

    result = await WorldEntityFusionService().apply(
        db_session,
        novel_id=project_novel_id,
        confirmed=True,
        suggestions=[
            EntityFusionApplyItem(
                action="alias_only",
                source_entity_id=source_id,
                target_entity_id=target_id,
                alias="周明瑞",
            )
        ],
    )

    assert result["applied"] == 1
    target = await CoreEntityRepository().get(db_session, uuid.UUID(hex=target_id))
    assert target is not None
    aliases = (target.content_json or {}).get("aliases", [])
    assert any(alias.get("alias") == "周明瑞" for alias in aliases)


async def test_entity_fusion_apply_requires_domain_confirmation(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        await WorldEntityFusionService().apply(
            db_session,
            novel_id=project_novel_id,
            confirmed=False,
            suggestions=[
                EntityFusionApplyItem(
                    action="alias_only",
                    source_entity_id=str(uuid.uuid4()),
                    target_entity_id=str(uuid.uuid4()),
                )
            ],
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "confirmed=true is required"


async def test_entity_fusion_canonical_merge_requires_explicit_confirmation(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    source_id = await _create_entity(
        db_session,
        project_novel_id,
        name="林七",
        status="canonical",
    )
    target_id = await _create_entity(
        db_session,
        project_novel_id,
        name="林柒",
        status="canonical",
    )

    result = await WorldEntityFusionService().apply(
        db_session,
        novel_id=project_novel_id,
        confirmed=True,
        suggestions=[
            EntityFusionApplyItem(
                action="merge",
                source_entity_id=source_id,
                target_entity_id=target_id,
            )
        ],
    )

    assert result["applied"] == 0
    assert result["skipped"] == 1
    assert "二次确认" in result["warnings"][0]


async def test_entity_fusion_canonical_alias_requires_explicit_confirmation(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    source_id = await _create_entity(
        db_session,
        project_novel_id,
        name="周明瑞",
        status="canonical",
    )
    target_id = await _create_entity(
        db_session,
        project_novel_id,
        name="克莱恩",
        status="canonical",
    )

    result = await WorldEntityFusionService().apply(
        db_session,
        novel_id=project_novel_id,
        confirmed=True,
        suggestions=[
            EntityFusionApplyItem(
                action="alias_only",
                source_entity_id=source_id,
                target_entity_id=target_id,
            )
        ],
    )

    assert result["applied"] == 0
    assert result["skipped"] == 1
    assert "二次确认" in result["warnings"][0]


async def test_entity_fusion_canonical_alias_archives_source_without_content_merge(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    source_id = await _create_entity(
        db_session,
        project_novel_id,
        name="周明瑞",
        status="canonical",
        summary="来源对象摘要不应合入",
    )
    target_id = await _create_entity(
        db_session,
        project_novel_id,
        name="克莱恩",
        status="canonical",
        summary="保留对象摘要",
    )

    result = await WorldEntityFusionService().apply(
        db_session,
        novel_id=project_novel_id,
        confirmed=True,
        suggestions=[
            EntityFusionApplyItem(
                action="alias_only",
                source_entity_id=source_id,
                target_entity_id=target_id,
                alias="周明瑞",
                allow_canonical_alias=True,
            )
        ],
    )

    repo = CoreEntityRepository()
    source = await repo.get(db_session, uuid.UUID(hex=source_id))
    target = await repo.get(db_session, uuid.UUID(hex=target_id))
    assert result["applied"] == 1
    assert source is not None and source.status == "merged"
    assert (source.content_json or {})["merged_into"] == target_id
    assert target is not None and target.summary == "保留对象摘要"
    assert any(
        alias.get("alias") == "周明瑞"
        for alias in (target.content_json or {}).get("aliases", [])
    )


async def test_entity_fusion_canonical_alias_adopts_existing_pending_alias(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    source_id = await _create_entity(
        db_session,
        project_novel_id,
        name="周明瑞",
        status="canonical",
    )
    target_id = await _create_entity(
        db_session,
        project_novel_id,
        name="克莱恩·莫雷蒂",
        status="canonical",
    )
    repo = CoreEntityRepository()
    target = await repo.get(db_session, uuid.UUID(hex=target_id))
    assert target is not None
    target.content_json = {
        **dict(target.content_json or {}),
        "aliases": [
            {
                "alias": "周明瑞",
                "type": "name",
                "status": "candidate",
                "source": "deep_import",
                "workflow_id": "wf-existing",
                "needs_review": True,
            }
        ],
    }
    db_session.add(target)
    await db_session.flush()

    result = await WorldEntityFusionService().apply(
        db_session,
        novel_id=project_novel_id,
        confirmed=True,
        suggestions=[
            EntityFusionApplyItem(
                action="alias_only",
                source_entity_id=source_id,
                target_entity_id=target_id,
                alias="周明瑞",
                allow_canonical_alias=True,
            )
        ],
    )

    source = await repo.get(db_session, uuid.UUID(hex=source_id))
    await db_session.refresh(target)
    aliases = [
        item
        for item in (target.content_json or {}).get("aliases", [])
        if item.get("alias") == "周明瑞"
    ]
    assert result["applied"] == 1
    assert source is not None and source.status == "merged"
    assert len(aliases) == 1
    assert aliases[0]["status"] == "canonical"
    assert aliases[0]["needs_review"] is False
    assert aliases[0]["workflow_id"] == "wf-existing"


async def test_entity_fusion_group_recomputes_canonical_alias_gate_and_fingerprints(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    source_id = await _create_entity(
        db_session,
        project_novel_id,
        name="周明瑞",
        status="canonical",
        summary="不应融入的来源正文",
    )
    target_id = await _create_entity(
        db_session,
        project_novel_id,
        name="克莱恩·莫雷蒂",
        status="canonical",
        summary="保留对象正文",
    )
    repo = CoreEntityRepository()
    source = await repo.get(db_session, uuid.UUID(hex=source_id))
    target = await repo.get(db_session, uuid.UUID(hex=target_id))
    assert source is not None and target is not None
    service = WorldEntityFusionService()
    source_fp = await service._entity_fingerprints(
        db_session,
        uuid.UUID(hex=project_novel_id),
        source,
    )
    target_fp = await service._entity_fingerprints(
        db_session,
        uuid.UUID(hex=project_novel_id),
        target,
    )
    operation = {
        "action": "alias_only",
        "source_entity_id": source_id,
        "alias": "周明瑞",
        "expected_source_execution_fingerprint": source_fp["execution_fingerprint"],
        "expected_target_execution_fingerprint": target_fp["execution_fingerprint"],
    }

    with pytest.raises(ValidationError, match="confirmation_required"):
        await service.apply_group(
            db_session,
            novel_id=project_novel_id,
            primary_entity_id=target_id,
            operations=[operation],
        )

    results = await service.apply_group(
        db_session,
        novel_id=project_novel_id,
        primary_entity_id=target_id,
        operations=[{**operation, "allow_canonical_alias": True}],
    )

    await db_session.refresh(source)
    await db_session.refresh(target)
    assert results[0]["action"] == "alias_only"
    assert source.status == "merged"
    assert target.summary == "保留对象正文"


async def test_entity_fusion_group_merges_candidate_pair_without_adopting_primary(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    source_id = await _create_entity(
        db_session,
        project_novel_id,
        name="意念拓印",
        status="candidate",
        summary="较短的候选摘要",
    )
    target_id = await _create_entity(
        db_session,
        project_novel_id,
        name="意念拓印",
        status="candidate",
        summary="更完整的候选摘要",
    )
    repo = CoreEntityRepository()
    source = await repo.get(db_session, uuid.UUID(source_id))
    target = await repo.get(db_session, uuid.UUID(target_id))
    assert source is not None and target is not None
    service = WorldEntityFusionService()
    source_fp = await service._entity_fingerprints(
        db_session,
        uuid.UUID(project_novel_id),
        source,
    )
    target_fp = await service._entity_fingerprints(
        db_session,
        uuid.UUID(project_novel_id),
        target,
    )

    results = await service.apply_group(
        db_session,
        novel_id=project_novel_id,
        primary_entity_id=target_id,
        operations=[
            {
                "action": "merge",
                "source_entity_id": source_id,
                "expected_source_execution_fingerprint": source_fp[
                    "execution_fingerprint"
                ],
                "expected_target_execution_fingerprint": target_fp[
                    "execution_fingerprint"
                ],
            }
        ],
    )

    await db_session.refresh(source)
    await db_session.refresh(target)
    assert results[0]["action"] == "merge"
    assert source.status == "merged"
    assert target.status == "candidate"


async def test_workflow_group_rejects_user_edited_candidate_before_apply(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    source_id = await _create_entity(
        db_session,
        project_novel_id,
        name="林七",
        status="candidate",
    )
    target_id = await _create_entity(
        db_session,
        project_novel_id,
        name="林柒",
        status="candidate",
    )
    repo = CoreEntityRepository()
    source = await repo.get(db_session, uuid.UUID(source_id))
    target = await repo.get(db_session, uuid.UUID(target_id))
    assert source is not None and target is not None
    source.content_json = {
        "_meta": {
            "source": "deep_import",
            "workflow_id": "workflow-1",
            "user_edited": True,
        }
    }
    target.content_json = {
        "_meta": {"source": "deep_import", "workflow_id": "workflow-1"}
    }
    await db_session.flush()

    with pytest.raises(ValidationError, match="workflow_candidate_changed"):
        await WorldEntityFusionService().apply_group(
            db_session,
            novel_id=project_novel_id,
            primary_entity_id=target_id,
            workflow_id="workflow-1",
            operations=[
                {
                    "action": "merge",
                    "source_entity_id": source_id,
                    "expected_source_execution_fingerprint": "unused",
                    "expected_target_execution_fingerprint": "unused",
                }
            ],
        )


async def test_entity_fusion_group_validates_keep_separate_against_current_state(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    source_id = await _create_entity(
        db_session,
        project_novel_id,
        name="奥黛丽",
        status="draft",
    )
    target_id = await _create_entity(
        db_session,
        project_novel_id,
        name="奥黛丽·霍尔",
        status="canonical",
    )
    repo = CoreEntityRepository()
    source = await repo.get(db_session, uuid.UUID(source_id))
    target = await repo.get(db_session, uuid.UUID(target_id))
    assert source is not None and target is not None
    service = WorldEntityFusionService()
    source_fp = await service._entity_fingerprints(
        db_session, uuid.UUID(project_novel_id), source
    )
    target_fp = await service._entity_fingerprints(
        db_session, uuid.UUID(project_novel_id), target
    )
    source.summary = "扫描后修改的正文"
    await db_session.flush()

    with pytest.raises(ValidationError, match="stale_suggestion"):
        await service.apply_group(
            db_session,
            novel_id=project_novel_id,
            primary_entity_id=target_id,
            operations=[
                {
                    "action": "keep_separate",
                    "source_entity_id": source_id,
                    "expected_source_execution_fingerprint": source_fp[
                        "execution_fingerprint"
                    ],
                    "expected_target_execution_fingerprint": target_fp[
                        "execution_fingerprint"
                    ],
                }
            ],
        )


async def test_entity_fusion_group_returns_post_merge_keep_separate_fingerprint(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    merge_id = await _create_entity(
        db_session,
        project_novel_id,
        name="克莱恩",
        status="draft",
    )
    keep_id = await _create_entity(
        db_session,
        project_novel_id,
        name="格尔曼·斯帕罗",
        status="draft",
    )
    target_id = await _create_entity(
        db_session,
        project_novel_id,
        name="克莱恩·莫雷蒂",
        status="canonical",
    )
    repo = CoreEntityRepository()
    entities = {
        entity_id: await repo.get(db_session, uuid.UUID(entity_id))
        for entity_id in (merge_id, keep_id, target_id)
    }
    assert all(entities.values())
    service = WorldEntityFusionService()
    fingerprints = {
        entity_id: await service._entity_fingerprints(
            db_session,
            uuid.UUID(project_novel_id),
            entity,
        )
        for entity_id, entity in entities.items()
        if entity is not None
    }

    results = await service.apply_group(
        db_session,
        novel_id=project_novel_id,
        primary_entity_id=target_id,
        operations=[
            {
                "action": "merge",
                "source_entity_id": merge_id,
                "expected_source_execution_fingerprint": fingerprints[merge_id][
                    "execution_fingerprint"
                ],
                "expected_target_execution_fingerprint": fingerprints[target_id][
                    "execution_fingerprint"
                ],
            },
            {
                "action": "keep_separate",
                "source_entity_id": keep_id,
                "expected_source_execution_fingerprint": fingerprints[keep_id][
                    "execution_fingerprint"
                ],
                "expected_target_execution_fingerprint": fingerprints[target_id][
                    "execution_fingerprint"
                ],
            },
        ],
    )

    keep_result = next(item for item in results if item["action"] == "keep_separate")
    final_target = await repo.get(db_session, uuid.UUID(target_id))
    assert final_target is not None
    final_target_fp = await service._entity_fingerprints(
        db_session,
        uuid.UUID(project_novel_id),
        final_target,
    )
    target_result_key = (
        "left_semantic_fingerprint"
        if keep_result["left_asset_id"] == target_id
        else "right_semantic_fingerprint"
    )
    assert keep_result[target_result_key] == final_target_fp["semantic_fingerprint"]
    assert (
        keep_result[target_result_key] != fingerprints[target_id]["semantic_fingerprint"]
    )


async def test_entity_fusion_group_before_budget_returns_complete_exact_name_edges(
    db_session: AsyncSession,
    project_novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for index in range(5):
        await _create_entity(
            db_session,
            project_novel_id,
            name="同名人物",
            status="draft" if index else "canonical",
        )
    service = WorldEntityFusionService(llm_client=SimpleNamespace())
    monkeypatch.setattr(service, "_evidence", mock.AsyncMock(return_value=[]))

    result = await service.suggest(
        db_session,
        novel_id=project_novel_id,
        max_suggestions=1,
        group_before_budget=True,
    )

    assert result["candidate_pair_count"] == 4
    assert result["suggestion_count"] == 4


async def test_task_entity_fusion_rejects_an_ordinary_session(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    with pytest.raises(RuntimeError, match="fenced TaskWorker handler session"):
        await WorldEntityFusionService(llm_client=mock.MagicMock()).suggest_for_task(
            db_session,
            novel_id=project_novel_id,
            checkpoint_callback=lambda _result, _progress: None,
        )


async def test_task_entity_fusion_releases_transaction_and_uses_project_first_order(
    db_session: AsyncSession,
    project_novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _create_entity(
        db_session,
        project_novel_id,
        name="长夜守望者",
        status="canonical",
        summary="已采用对象摘要",
    )
    await _create_entity(
        db_session,
        project_novel_id,
        name="长夜守望者",
        status="draft",
        summary="待处理对象摘要",
    )

    from infrastructure.tasks.worker import _TaskHandlerSession
    from modules.project import facade as project_facade

    bind = db_session.bind
    assert bind is not None
    task_session = _TaskHandlerSession(
        bind=bind,
        expire_on_commit=True,
        join_transaction_mode="create_savepoint",
    )
    events: list[str] = []
    transaction_states: list[bool] = []

    async def _checkpoint() -> bool:
        events.append("commit")
        return True

    task_session.set_task_commit_hook(_checkpoint)
    original_guard = project_facade.require_active_project

    async def _guard(db, novel_id):  # type: ignore[no-untyped-def]
        events.append("project")
        await original_guard(db, novel_id)

    service = WorldEntityFusionService(llm_client=mock.MagicMock())
    evidence_search = mock.AsyncMock(
        side_effect=AssertionError(
            "task preparation must not call provider-backed RAG evidence"
        )
    )
    original_prepare = service._prepare_task_scan
    original_revalidate = service._revalidate_task_batch

    async def _prepare(*args, **kwargs):  # type: ignore[no-untyped-def]
        events.append("prepare")
        return await original_prepare(*args, **kwargs)

    async def _revalidate(*args, **kwargs):  # type: ignore[no-untyped-def]
        events.append("revalidate")
        return await original_revalidate(*args, **kwargs)

    async def _decide(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        events.append("decide")
        transaction_states.append(task_session.in_transaction())
        return EntityFusionDecision(
            action="needs_review",
            confidence=0.88,
            reason="需要作者复核",
        )

    monkeypatch.setattr(project_facade, "require_active_project", _guard)
    monkeypatch.setattr(service, "_evidence", evidence_search)
    monkeypatch.setattr(service, "_prepare_task_scan", _prepare)
    monkeypatch.setattr(service, "_revalidate_task_batch", _revalidate)
    monkeypatch.setattr(service, "_decide", _decide)

    def _capture(_result: dict, _progress: float) -> None:
        events.append("result")

    try:
        result = await service.suggest_for_task(
            task_session,
            novel_id=project_novel_id,
            checkpoint_callback=_capture,
        )
    finally:
        await task_session.close()

    assert result["suggestion_count"] == 1
    evidence_search.assert_not_awaited()
    assert transaction_states == [False]
    assert events == [
        "project",
        "prepare",
        "result",
        "commit",
        "decide",
        "project",
        "revalidate",
        "result",
        "commit",
        "result",
    ]


async def test_task_entity_fusion_lost_lease_stops_before_llm(
    db_session: AsyncSession,
    project_novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _create_entity(
        db_session,
        project_novel_id,
        name="租约失效对象",
        status="canonical",
    )
    await _create_entity(
        db_session,
        project_novel_id,
        name="租约失效对象",
        status="draft",
    )

    from infrastructure.tasks.worker import _TaskHandlerSession

    bind = db_session.bind
    assert bind is not None
    task_session = _TaskHandlerSession(
        bind=bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    task_session.set_task_commit_hook(mock.AsyncMock(return_value=False))
    service = WorldEntityFusionService(llm_client=mock.MagicMock())
    decide = mock.AsyncMock(
        return_value=EntityFusionDecision(
            action="needs_review",
            confidence=0.8,
            reason="不应执行",
        )
    )
    monkeypatch.setattr(service, "_decide", decide)

    try:
        with pytest.raises(asyncio.CancelledError):
            await service.suggest_for_task(
                task_session,
                novel_id=project_novel_id,
                checkpoint_callback=lambda _result, _progress: None,
            )
    finally:
        await task_session.close()

    decide.assert_not_awaited()


async def test_task_entity_fusion_multi_batch_caps_results_and_isolates_novel(
    db_session: AsyncSession,
    two_projects: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id, other_novel_id = two_projects
    owned_ids = {
        await _create_entity(
            db_session,
            novel_id,
            name="多批同名对象",
            status="canonical" if index == 0 else "draft",
        )
        for index in range(31)
    }
    other_ids = {
        await _create_entity(
            db_session,
            other_novel_id,
            name="多批同名对象",
            status="canonical" if index == 0 else "draft",
        )
        for index in range(2)
    }

    from infrastructure.tasks.worker import _TaskHandlerSession

    bind = db_session.bind
    assert bind is not None
    task_session = _TaskHandlerSession(
        bind=bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    checkpoint_count = 0

    async def _checkpoint() -> bool:
        nonlocal checkpoint_count
        checkpoint_count += 1
        return True

    task_session.set_task_commit_hook(_checkpoint)
    service = WorldEntityFusionService(llm_client=mock.MagicMock())
    decide = mock.AsyncMock(
        return_value=EntityFusionDecision(
            action="needs_review",
            confidence=0.9,
            reason="多批复核",
        )
    )
    monkeypatch.setattr(service, "_decide", decide)

    try:
        result = await service.suggest_for_task(
            task_session,
            novel_id=novel_id,
            max_suggestions=20,
            checkpoint_callback=lambda _result, _progress: None,
        )
    finally:
        await task_session.close()

    result_ids = {
        entity_id
        for suggestion in result["suggestions"]
        for entity_id in (
            suggestion["source_entity_id"],
            suggestion["target_entity_id"],
        )
    }
    assert result["total_entities_scanned"] == 31
    assert result["candidate_pair_count"] == 30
    assert result["processed_pair_count"] == 24
    assert result["suggestion_count"] == 20
    assert len(result["suggestions"]) == 20
    assert checkpoint_count == 3
    assert decide.await_count == 24
    assert result_ids <= owned_ids
    assert result_ids.isdisjoint(other_ids)


async def test_task_entity_fusion_skips_asset_that_drifts_during_decision(
    db_session: AsyncSession,
    project_novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = "相同的长摘要会形成一组待复核对象，然后在决策期间模拟修改。" * 3
    await _create_entity(
        db_session,
        project_novel_id,
        name="源对象",
        status="canonical",
        summary=summary,
    )
    await _create_entity(
        db_session,
        project_novel_id,
        name="待合并对象",
        status="draft",
        summary=summary,
    )

    from infrastructure.tasks.worker import _TaskHandlerSession

    bind = db_session.bind
    assert bind is not None
    task_session = _TaskHandlerSession(
        bind=bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    checkpoint_count = 0
    captured_results: list[dict] = []

    async def _checkpoint() -> bool:
        nonlocal checkpoint_count
        checkpoint_count += 1
        return True

    task_session.set_task_commit_hook(_checkpoint)
    service = WorldEntityFusionService(llm_client=mock.MagicMock())

    async def _decide(source, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        assert task_session.in_transaction() is False
        entity = await CoreEntityRepository().get(db_session, uuid.UUID(source.id))
        assert entity is not None
        entity.summary = "在 LLM 决策窗口中已被作者修改。"
        await db_session.flush()
        return EntityFusionDecision(
            action="needs_review",
            confidence=0.88,
            reason="旧决策不应落库",
        )

    monkeypatch.setattr(service, "_decide", _decide)
    try:
        result = await service.suggest_for_task(
            task_session,
            novel_id=project_novel_id,
            checkpoint_callback=lambda value, _progress: captured_results.append(value),
        )
    finally:
        await task_session.close()

    assert checkpoint_count == 2
    assert result["suggestion_count"] == 0
    assert result["skipped_stale_count"] == 1
    assert result["stale_pairs"][0]["reason"] == "asset_changed"
    assert captured_results[-1] == result


async def test_task_entity_fusion_freezes_and_reuses_project_llm_snapshot(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    summary = "用于验证任务配置快照的长摘要，两个对象在语义上保持一致。" * 3
    await _create_entity(
        db_session,
        project_novel_id,
        name="快照对象甲",
        status="canonical",
        summary=summary,
    )
    await _create_entity(
        db_session,
        project_novel_id,
        name="快照对象乙",
        status="draft",
        summary=summary,
    )

    from infrastructure.tasks.worker import _TaskHandlerSession

    snapshot = {"version": 1, "profile_hash": "frozen"}
    restored_settings = {"llm": {"model": "snapshot-model"}}
    clients = [
        mock.MagicMock(model_name="snapshot-model", close=mock.AsyncMock()),
        mock.MagicMock(model_name="snapshot-model", close=mock.AsyncMock()),
    ]
    snapshot_events: list[str] = []

    async def _decide(
        _service,
        _source,
        _target,
        _match,
        _evidence,
        *,
        allow_degraded: bool = True,
    ) -> EntityFusionDecision:
        assert allow_degraded is False
        return EntityFusionDecision(
            action="needs_review",
            confidence=0.9,
            reason="快照配置决策",
        )

    async def _run(
        *,
        existing_snapshot: dict | None,
        snapshot_callback,
    ) -> dict:
        bind = db_session.bind
        assert bind is not None
        task_session = _TaskHandlerSession(
            bind=bind,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

        async def _checkpoint() -> bool:
            snapshot_events.append("commit")
            return True

        task_session.set_task_commit_hook(_checkpoint)
        try:
            return await WorldEntityFusionService().suggest_for_task(
                task_session,
                novel_id=project_novel_id,
                checkpoint_callback=lambda _result, _progress: None,
                llm_execution_snapshot=existing_snapshot,
                snapshot_callback=snapshot_callback,
            )
        finally:
            await task_session.close()

    with (
        mock.patch(
            "modules.project.facade.build_project_llm_execution_snapshot",
            autospec=True,
            return_value=snapshot,
        ) as build_snapshot,
        mock.patch(
            "modules.project.facade.restore_project_llm_execution_settings",
            autospec=True,
            return_value=restored_settings,
        ) as restore_snapshot,
        mock.patch(
            "modules.project.facade.create_project_snapshot_llm_client",
            autospec=True,
            side_effect=clients,
        ) as create_client,
        mock.patch.object(
            WorldEntityFusionService,
            "_decide",
            autospec=True,
            side_effect=_decide,
        ),
    ):
        first = await _run(
            existing_snapshot=None,
            snapshot_callback=lambda value: snapshot_events.append(
                "snapshot" if value == snapshot else "wrong_snapshot"
            ),
        )
        second = await _run(
            existing_snapshot=snapshot,
            snapshot_callback=lambda _value: snapshot_events.append(
                "unexpected_snapshot"
            ),
        )

    assert first["suggestion_count"] == 1
    assert second["suggestion_count"] == 1
    build_snapshot.assert_awaited_once_with(mock.ANY, project_novel_id)
    assert restore_snapshot.await_count == 2
    assert all(call.args[2] == snapshot for call in restore_snapshot.await_args_list)
    assert create_client.call_count == 2
    assert snapshot_events[0] == "snapshot"
    assert "unexpected_snapshot" not in snapshot_events
    clients[0].close.assert_awaited_once_with()
    clients[1].close.assert_awaited_once_with()


async def test_entity_fusion_apply_prefetches_suggestion_entities(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    pairs = []
    for index in range(3):
        source_id = await _create_entity(
            db_session,
            project_novel_id,
            name=f"林七-{index}",
            status="canonical",
        )
        target_id = await _create_entity(
            db_session,
            project_novel_id,
            name=f"林柒-{index}",
            status="canonical",
        )
        pairs.append((source_id, target_id))

    engine = db_session.bind.sync_engine
    entity_selects: list[str] = []

    def count_entity_selects(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from core_entities" in normalized:
            entity_selects.append(normalized)

    event.listen(engine, "before_cursor_execute", count_entity_selects)
    try:
        result = await WorldEntityFusionService().apply(
            db_session,
            novel_id=project_novel_id,
            confirmed=True,
            suggestions=[
                EntityFusionApplyItem(
                    action="merge",
                    source_entity_id=source_id,
                    target_entity_id=target_id,
                )
                for source_id, target_id in pairs
            ],
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_entity_selects)

    assert result["applied"] == 0
    assert result["skipped"] == 3
    assert len(entity_selects) == 1


async def test_entity_fusion_fingerprint_inputs_are_batch_loaded(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    novel_id = uuid.UUID(hex=project_novel_id)
    entity_ids = [
        await _create_entity(
            db_session,
            project_novel_id,
            name=f"批量人物-{index}",
            status="draft",
        )
        for index in range(6)
    ]
    parsed_ids = [uuid.UUID(entity_id) for entity_id in entity_ids]
    db_session.add_all(
        [
            Character(
                entity_id=entity_id,
                novel_id=novel_id,
                name=f"批量人物-{index}",
                status="draft",
            )
            for index, entity_id in enumerate(parsed_ids)
        ]
        + [
            EntityRelation(
                novel_id=novel_id,
                source_id=parsed_ids[index],
                target_id=parsed_ids[index + 1],
                relation_type="knows",
                status="canonical",
            )
            for index in range(len(parsed_ids) - 1)
        ]
    )
    await db_session.flush()
    entities = await CoreEntityRepository().get_by_ids(
        db_session,
        novel_id,
        parsed_ids,
    )
    service = WorldEntityFusionService()
    engine = db_session.bind.sync_engine
    relation_selects: list[str] = []
    character_selects: list[str] = []

    def count_fingerprint_selects(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from entity_relations " in normalized:
            relation_selects.append(normalized)
        if normalized.startswith("select") and " from characters " in normalized:
            character_selects.append(normalized)

    event.listen(engine, "before_cursor_execute", count_fingerprint_selects)
    try:
        prefetched = await service._load_fingerprint_inputs(
            db_session,
            novel_id,
            entities,
        )
        fingerprints = [
            await service._entity_fingerprints(
                db_session,
                novel_id,
                entity,
                prefetched=prefetched,
            )
            for entity in entities
        ]
    finally:
        event.remove(engine, "before_cursor_execute", count_fingerprint_selects)

    assert len(relation_selects) == 1
    assert len(character_selects) == 1
    assert sum(item["relation_count"] for item in fingerprints) == 10


async def test_entity_fusion_suggestion_prefers_canonical_target(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    canonical_id = await _create_entity(
        db_session,
        project_novel_id,
        name="克莱恩",
        status="canonical",
    )
    candidate_id = await _create_entity(
        db_session,
        project_novel_id,
        name="克莱恩",
        status="candidate",
    )

    result = await WorldEntityFusionService(
        llm_client=mock.MagicMock(model_name="test-model")
    ).suggest(
        db_session,
        novel_id=project_novel_id,
        max_suggestions=5,
    )

    suggestion = result["suggestions"][0]
    assert suggestion["source_entity_id"] == candidate_id
    assert suggestion["target_entity_id"] == canonical_id
    assert suggestion["source_status"] == "candidate"
    assert suggestion["target_status"] == "canonical"


async def test_entity_fusion_suggests_same_type_summary_overlap(
    db_session: AsyncSession,
    project_novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_evidence_search(*args, **kwargs):
        raise AssertionError(
            "summary_overlap suggestions should use entity summary evidence"
        )

    monkeypatch.setattr(
        "modules.context.facade.search_novel_evidence",
        fail_evidence_search,
    )

    shen_lan_id = await _create_entity(
        db_session,
        project_novel_id,
        name="沈澜",
        status="draft",
        summary=(
            "女，28岁。镜局执业修复师，擅长灵镜校准。调查北港失踪案，"
            "隐藏动机是寻找八年前失踪父亲与“归一潮”的真相。"
            "与柳烨旧识，与许筠有师门情分。"
        ),
    )
    mirror_restorer_id = await _create_entity(
        db_session,
        project_novel_id,
        name="北港镜修师",
        status="draft",
        summary=(
            "女，28岁。镜局执业修复师，擅长灵镜校准。调查北港失踪案，"
            "寻找八年前失踪父亲与归一潮真相。与柳烨旧识，与许筠有师门情分。"
        ),
    )

    with mock.patch(
        "modules.world.entity_fusion.run_managed_structured",
        autospec=True,
        return_value=EntityFusionDecision(
            action="alias_only",
            confidence=0.92,
            reason="摘要证据支持别名关系",
        ),
    ):
        result = await WorldEntityFusionService(
            llm_client=mock.MagicMock(model_name="test-model")
        ).suggest(
            db_session,
            novel_id=project_novel_id,
            max_suggestions=5,
        )

    suggestion = result["suggestions"][0]
    assert suggestion["match_method"] == "summary_overlap"
    assert suggestion["action"] == "alias_only"
    assert {
        suggestion["source_entity_id"],
        suggestion["target_entity_id"],
    } == {shen_lan_id, mirror_restorer_id}
