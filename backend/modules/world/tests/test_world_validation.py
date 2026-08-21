from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select

from core.errors import ConflictError, ValidationError
from infrastructure.tasks.models import AsyncTask
from modules.world.models import WorldValidationRun
from modules.world.schemas import (
    WorldBiblePageCreate,
    WorldBiblePageDraftCreate,
    WorldBiblePageDraftUpdate,
    WorldValidationPolicy,
    WorldValidationRunCreate,
    WorldValidationSemanticOutput,
    WorldValidationWarningAcceptRequest,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from modules.world.services.worldbuilding.world_validation_engine import (
    build_review_packets,
    deterministic_findings,
    overall_result,
    stable_hash,
    validate_semantic_output,
)
from modules.world.services.worldbuilding.world_validation_service import (
    WorldValidationService,
)


def _policy(*, semantic: bool = False) -> WorldValidationPolicy:
    return WorldValidationPolicy(
        schema_version="world_validation_policy.v1",
        policy_version="test-v1",
        semantic_enabled=semantic,
        required_questions=(
            [
                {
                    "question_id": "Q1",
                    "gate": "ontology",
                    "question": "规则与结果是否一致？",
                }
            ]
            if semantic
            else []
        ),
    )


def test_policy_is_closed_and_uses_named_operators_only() -> None:
    with pytest.raises(PydanticValidationError):
        WorldValidationPolicy.model_validate(
            {
                "schema_version": "world_validation_policy.v1",
                "policy_version": "unsafe",
                "rules": [
                    {
                        "rule_id": "R1",
                        "operator": "eval",
                        "value": "__import__('os')",
                        "message": "unsafe",
                    }
                ],
            }
        )


def test_deterministic_rules_and_verdict_precedence() -> None:
    policy = WorldValidationPolicy.model_validate(
        {
            **_policy().model_dump(mode="json"),
            "rules": [
                {
                    "rule_id": "R1",
                    "operator": "contains",
                    "value": "代价",
                    "severity": "error",
                    "message": "力量规则必须写明代价",
                }
            ],
        }
    )
    manifest = {
        "scope": "targeted",
        "items": [
            {
                "source_key": "draft:1",
                "title": "潮汐术",
                "page_type": "rule",
                "content": "潮汐术能够改变水位。",
            }
        ],
    }

    findings = deterministic_findings(policy, manifest, None)

    assert {item.category for item in findings} == {
        "policy:R1",
        "missing-world-state",
    }
    assert overall_result(findings) == ("fail", "block")


def test_review_packets_have_stable_input_hash_and_hard_budget() -> None:
    policy = _policy(semantic=True).model_copy(
        update={"packet_character_limit": 4000, "max_input_characters": 4000}
    )
    manifest = {
        "scope": "targeted",
        "items": [
            {
                "source_key": "draft:1",
                "target_type": "world_bible_draft",
                "target_id": "1",
                "title": "潮汐术",
                "page_type": "rule",
                "status": "draft",
                "version": 1,
                "content_hash": stable_hash("规则"),
                "content": "规则" * 100,
            }
        ],
    }

    first, budget = build_review_packets(
        run_id="run", scope="targeted", policy=policy, manifest=manifest
    )
    second, _ = build_review_packets(
        run_id="run", scope="targeted", policy=policy, manifest=manifest
    )
    assert first[0]["input_hash"] == second[0]["input_hash"]
    assert budget["planned_packets"] == 1

    too_large = {**manifest, "items": [{**manifest["items"][0], "content": "x" * 5000}]}
    packets, budget = build_review_packets(
        run_id="run", scope="targeted", policy=policy, manifest=too_large
    )
    assert packets == []
    assert budget["planned_input_characters"] == 5000


def test_semantic_output_must_cite_the_frozen_shard() -> None:
    packet = {
        "questions": [{"question_id": "Q1"}],
        "content": {"source_key": "page:1", "text": "潮汐有代价。"},
        "shard_index": 0,
    }
    output = WorldValidationSemanticOutput.model_validate(
        {
            "answers": [
                {
                    "question_id": "Q1",
                    "verdict": "mixed",
                    "category": "ontology",
                    "action": "KEEP-GATE",
                    "explanation": "证据不足",
                    "source_key": "page:1",
                    "excerpt": "不存在的引文",
                }
            ]
        }
    )
    with pytest.raises(ValidationError, match="excerpt"):
        validate_semantic_output(packet, output)


async def _activate_policy(
    db_session, novel_id: str
) -> tuple[WorldValidationPolicy, str]:
    policy = _policy()
    await WorldBibleLifecycleService().create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=novel_id,
            page_key="validation-policy",
            page_type="rule",
            title="世界书校验策略",
            status="canonical",
            page_meta_json={"validation_policy": policy.model_dump(mode="json")},
        ),
    )
    return policy, stable_hash(policy.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_active_policy_blocks_legacy_canon_page_writes(
    db_session, project_novel_id: str
) -> None:
    await _activate_policy(db_session, project_novel_id)

    with pytest.raises(ConflictError) as exc_info:
        await WorldBibleLifecycleService().create_page(
            db_session,
            WorldBiblePageCreate(
                novel_id=project_novel_id,
                page_type="location",
                title="绕过页面",
                status="canonical",
            ),
        )
    assert exc_info.value.code == "required_validation"


@pytest.mark.asyncio
async def test_targeted_receipt_passes_then_becomes_stale_after_draft_change(
    db_session, project_novel_id: str
) -> None:
    policy, policy_hash = await _activate_policy(db_session, project_novel_id)
    lifecycle = WorldBibleLifecycleService()
    draft = await lifecycle.create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=project_novel_id,
            page_type="rule",
            title="潮汐规则",
            free_text="潮汐术必须支付记忆代价。",
        ),
    )
    service = WorldValidationService()
    manifest, dependency_hash, target_hash = await service._freeze_manifest(
        db_session,
        novel_id=project_novel_id,
        scope="targeted",
        target_type="world_bible_draft",
        target_id=draft.id,
    )
    receipt_hash = stable_hash("receipt")
    run = WorldValidationRun(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(project_novel_id),
        trigger="manual",
        scope="targeted",
        scope_json={
            "target_type": "world_bible_draft",
            "target_id": draft.id,
            "target_hash": target_hash,
            "required_question_ids": [],
        },
        status="completed",
        verdict="pass",
        gate="pass",
        policy_version=policy.policy_version,
        policy_hash=policy_hash,
        manifest_json=manifest,
        manifest_hash=stable_hash(manifest),
        dependency_hash=dependency_hash,
        packet_hashes_json=[{"receipt_hash": receipt_hash}],
    )
    db_session.add(run)
    await db_session.flush()

    await service.require_gate(
        db_session,
        novel_id=project_novel_id,
        validation_run_id=str(run.id),
        target_type="world_bible_draft",
        target_id=draft.id,
        target_hash=target_hash or "",
    )
    await lifecycle.update_draft(
        db_session,
        project_novel_id,
        draft.id,
        WorldBiblePageDraftUpdate(title="潮汐规则（修订）"),
    )

    with pytest.raises(ConflictError) as exc_info:
        await service.require_gate(
            db_session,
            novel_id=project_novel_id,
            validation_run_id=str(run.id),
            target_type="world_bible_draft",
            target_id=draft.id,
            target_hash=target_hash or "",
        )
    assert exc_info.value.code == "required_validation"
    assert run.status == "stale"


@pytest.mark.asyncio
async def test_warning_acceptance_requires_exact_receipt_and_findings(
    db_session, project_novel_id: str
) -> None:
    policy, policy_hash = await _activate_policy(db_session, project_novel_id)
    lifecycle = WorldBibleLifecycleService()
    draft = await lifecycle.create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=project_novel_id,
            page_type="rule",
            title="潮汐规则",
        ),
    )
    service = WorldValidationService()
    manifest, dependency_hash, target_hash = await service._freeze_manifest(
        db_session,
        novel_id=project_novel_id,
        scope="targeted",
        target_type="world_bible_draft",
        target_id=draft.id,
    )
    receipt_hash = stable_hash("warning-receipt")
    run = WorldValidationRun(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(project_novel_id),
        trigger="manual",
        scope="targeted",
        scope_json={
            "target_type": "world_bible_draft",
            "target_id": draft.id,
            "target_hash": target_hash,
        },
        status="completed",
        verdict="mixed",
        gate="warn",
        policy_version=policy.policy_version,
        policy_hash=policy_hash,
        manifest_json=manifest,
        manifest_hash=stable_hash(manifest),
        dependency_hash=dependency_hash,
        packet_hashes_json=[{"receipt_hash": receipt_hash}],
        findings_json=[
            {
                "finding_id": "finding:warning",
                "layer": "structure",
                "severity": "warning",
                "category": "gap",
                "action": "KEEP-GATE",
                "message": "需作者确认",
            }
        ],
    )
    db_session.add(run)
    await db_session.flush()

    with pytest.raises(ValidationError):
        await service.accept_warnings(
            db_session,
            project_novel_id,
            str(run.id),
            WorldValidationWarningAcceptRequest(
                expected_receipt_hash=receipt_hash,
                finding_ids=["finding:other"],
                reason="确认风险",
            ),
        )
    accepted = await service.accept_warnings(
        db_session,
        project_novel_id,
        str(run.id),
        WorldValidationWarningAcceptRequest(
            expected_receipt_hash=receipt_hash,
            finding_ids=["finding:warning"],
            reason="作者接受该未决风险",
        ),
    )
    assert accepted.warning_receipt["receipt_hash"] == receipt_hash


@pytest.mark.asyncio
async def test_deterministic_run_uses_operation_receipt_and_finishes(
    db_session, project_novel_id: str
) -> None:
    service = WorldValidationService()
    operation_id = uuid.uuid4()
    created = await service.create_run(
        db_session,
        WorldValidationRunCreate(
            novel_id=project_novel_id,
            operation_id=operation_id,
            scope="full",
        ),
    )
    replay = await service.create_run(
        db_session,
        WorldValidationRunCreate(
            novel_id=project_novel_id,
            operation_id=operation_id,
            scope="full",
        ),
    )
    assert replay.id == created.id
    assert replay.task_id == created.task_id

    task = await db_session.scalar(
        select(AsyncTask).where(AsyncTask.id == uuid.UUID(created.task_id or ""))
    )
    assert task is not None
    task.mark_running(lease_id=str(uuid.uuid4()))
    await db_session.flush()
    result = await service.execute_run(
        db_session,
        novel_id=project_novel_id,
        run_id=created.id,
        attempt=task.attempt,
        task_id=str(task.id),
        lease_id=str(task.lease_id),
    )

    assert result["status"] == "completed"
    assert result["gate"] == "warn"
    assert result["receipt_hash"]
