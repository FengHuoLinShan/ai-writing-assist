from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select

from core.errors import ConflictError, ValidationError
from infrastructure.tasks.models import AsyncTask
from modules.world.models import CreationSuggestion, WorldBiblePage, WorldValidationRun
from modules.world.schemas import (
    WorldBiblePageCreate,
    WorldBiblePageDraftCreate,
    WorldBiblePageDraftUpdate,
    WorldDesignCheckpointPayload,
    WorldDesignCheckpointSaveRequest,
    WorldValidationPolicy,
    WorldValidationRunCreate,
    WorldValidationSemanticOutput,
    WorldValidationWarningAcceptRequest,
)
from modules.world.services.worldbuilding.adoption_package_service import (
    WorldAdoptionPackageService,
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

    with pytest.raises(PydanticValidationError, match="unsafe"):
        WorldValidationPolicy.model_validate(
            {
                "schema_version": "world_validation_policy.v1",
                "policy_version": "unsafe-regex",
                "rules": [
                    {
                        "rule_id": "R1",
                        "operator": "regex",
                        "value": "(?=secret)",
                        "message": "unsafe",
                    }
                ],
            }
        )

    with pytest.raises(PydanticValidationError, match="required_questions"):
        WorldValidationPolicy.model_validate(
            {
                "schema_version": "world_validation_policy.v1",
                "policy_version": "empty-semantic",
                "semantic_enabled": True,
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


def test_declarative_frontmatter_regex_and_numeric_tolerance_rules() -> None:
    policy = WorldValidationPolicy.model_validate(
        {
            **_policy().model_dump(mode="json"),
            "rules": [
                {
                    "rule_id": "frontmatter",
                    "operator": "frontmatter_required",
                    "value": "design_principle",
                    "message": "缺少设计原则",
                },
                {
                    "rule_id": "heading",
                    "operator": "regex",
                    "value": r"^## 影响范围$",
                    "message": "缺少影响范围",
                },
                {
                    "rule_id": "gravity",
                    "operator": "numeric_tolerance",
                    "value": {"field": "gravity", "expected": 9.8, "tolerance": 0.1},
                    "message": "数值超容差",
                },
            ],
        }
    )
    manifest = {
        "scope": "targeted",
        "items": [
            {
                "source_key": "page:1",
                "title": "城市",
                "page_type": "location",
                "content": "# 城市",
                "metadata": {"gravity": 10.2},
            }
        ],
    }
    categories = {
        item.category for item in deterministic_findings(policy, manifest, None)
    }
    assert {
        "policy:frontmatter",
        "policy:heading",
        "policy:gravity",
    } <= categories


def test_frontmatter_schema_and_forbidden_canon_pattern_are_declarative() -> None:
    policy = WorldValidationPolicy.model_validate(
        {
            **_policy().model_dump(mode="json"),
            "frontmatter_schemas": {
                "rule": {
                    "required": ["type", "title", "tags"],
                    "optional": ["status"],
                    "field_types": {
                        "type": "string",
                        "title": "string",
                        "tags": "array:string",
                    },
                    "enums": {"status": ["candidate", "canon"]},
                    "patterns": {"title": r"^[^!]+$"},
                    "min_items": {"tags": 2},
                    "required_items": {"tags": ["核心"]},
                    "unique_arrays": ["tags"],
                    "source_prefixes": ["wiki/rules/"],
                    "title_matches_source_stem": True,
                    "unknown_fields": "error",
                }
            },
            "rules": [
                {
                    "rule_id": "canon-overclaim",
                    "operator": "forbid_regex",
                    "value": "绝对没有代价",
                    "page_type": "rule",
                    "message": "正典规则不得无证据地宣称零代价",
                }
            ],
        }
    )
    manifest = {
        "scope": "targeted",
        "items": [
            {
                "source_key": "draft:1",
                "title": "规则!",
                "page_type": "rule",
                "content": "绝对没有代价",
                "metadata": {
                    "worldbook_import": {
                        "source_path": "wiki/other/not-the-title.md",
                        "frontmatter": {
                            "type": "rule",
                            "title": "规则!",
                            "tags": ["重复", "重复"],
                            "status": "invalid",
                            "extra": True,
                        },
                    }
                },
            }
        ],
    }
    categories = {
        item.category for item in deterministic_findings(policy, manifest, None)
    }
    assert {
        "schema-unknown-field",
        "schema-field-enum",
        "schema-string-pattern",
        "schema-array-duplicate",
        "schema-array-required-item",
        "schema-source-scope",
        "schema-title-filename",
        "policy:canon-overclaim",
    } <= categories


def test_alias_conflicts_ignore_a_draft_of_the_same_page() -> None:
    manifest = {
        "scope": "targeted",
        "lookup": [
            {
                "source_key": "page:1",
                "identity_key": "page:1",
                "target_id": "1",
                "title": "潮汐城",
                "aliases": ["潮城"],
            },
            {
                "source_key": "page:2",
                "identity_key": "page:2",
                "target_id": "2",
                "title": "其他城",
                "aliases": ["重名"],
            },
            {
                "source_key": "page:3",
                "identity_key": "page:3",
                "target_id": "3",
                "title": "重名",
                "aliases": [],
            },
        ],
        "items": [
            {
                "source_key": "draft:1",
                "identity_key": "page:1",
                "target_id": "draft-1",
                "title": "潮汐城",
                "page_type": "location",
                "body": "",
                "content": "",
                "metadata": {"aliases": ["潮城"]},
            }
        ],
    }
    findings = deterministic_findings(_policy(), manifest, None)
    alias_sources = {
        item.source_key for item in findings if item.category == "alias-conflict"
    }
    assert alias_sources == {"page:2", "page:3"}


def test_full_manifest_rejects_two_distinct_validation_policies() -> None:
    policy_meta = {"validation_policy": _policy().model_dump(mode="json")}
    manifest = {
        "scope": "full",
        "items": [
            {
                "source_key": "page:1",
                "identity_key": "page:1",
                "title": "当前策略",
                "page_type": "rule",
                "content": "当前",
                "metadata": policy_meta,
            },
            {
                "source_key": "draft:2",
                "identity_key": "draft:2",
                "title": "另一策略",
                "page_type": "rule",
                "content": "候选",
                "metadata": policy_meta,
            },
        ],
    }
    categories = {
        item.category for item in deterministic_findings(_policy(), manifest, None)
    }
    assert "validation-policy-multiple" in categories


def test_wikilink_heading_anchors_must_resolve() -> None:
    manifest = {
        "scope": "targeted",
        "lookup": [
            {
                "source_key": "page:1",
                "target_id": "1",
                "title": "潮汐城",
                "aliases": [],
                "anchors": ["规则"],
            }
        ],
        "items": [
            {
                "source_key": "draft:2",
                "target_id": "2",
                "title": "观测记录",
                "page_type": "custom",
                "body": "# 本节\n[[潮汐城#规则]] [[#本节]] [[潮汐城#不存在]]",
                "content": "# 本节\n[[潮汐城#规则]] [[#本节]] [[潮汐城#不存在]]",
                "anchors": ["本节"],
                "metadata": {"related": ["[[不存在页]]"]},
            }
        ],
    }
    findings = deterministic_findings(_policy(), manifest, None)
    anchors = [item for item in findings if item.category == "wikilink-anchor-dangling"]
    assert len(anchors) == 1
    frontmatter_links = [
        item
        for item in findings
        if item.category == "wikilink-dangling" and item.location == "frontmatter"
    ]
    assert len(frontmatter_links) == 1


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

    unsupported_pass = output.model_copy(deep=True)
    unsupported_pass.answers[0].verdict = "pass"
    unsupported_pass.answers[0].excerpt = None
    with pytest.raises(ValidationError, match="requires frozen source evidence"):
        validate_semantic_output(packet, unsupported_pass)


def test_engine_audits_all_world_state_surfaces_and_frozen_links() -> None:
    from modules.world.tests.test_adoption_package import _world_design_state

    state = _world_design_state()
    state["facets"][0]["maturity"] = {"framework": 3, "instance": 0}
    state["facets"][0]["evidence"] = ["page:1"]
    state["audit"]["valid"] = True
    checkpoint = WorldDesignCheckpointPayload.model_validate(
        {
            "schema_version": "world_design_checkpoint.v1",
            "depth": "seed",
            "round_no": 3,
            "action": "consolidate",
            "source_manifest_hash": "a" * 64,
            "world_state": state,
        }
    )
    manifest = {
        "scope": "full",
        "lookup": [],
        "items": [
            {
                "source_key": "page:1",
                "target_id": "1",
                "title": "潮汐城",
                "page_type": "location",
                "body": "[[不存在的页]]",
                "content": "[[不存在的页]]",
                "metadata": {
                    "worldbook_import": {
                        "source_path": "wiki/tide.md",
                        "frontmatter": {"title": "潮汐城"},
                    }
                },
                "linked_asset_refs": [
                    {
                        "relation": "requires",
                        "target_type": "world_bible_page",
                        "target_id": "missing",
                    }
                ],
            }
        ],
    }

    categories = {
        item.category for item in deterministic_findings(_policy(), manifest, checkpoint)
    }
    assert {
        "wikilink-dangling",
        "dependency-dangling",
        "reproduction-loop-gap",
        "facet-gap",
        "candidate-mountain",
        "coupling-chain-gap",
        "situated-test-gap",
        "pressure-not-run",
        "audit-overclaim",
    } <= categories


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
async def test_builtin_policy_activation_is_explicit_and_idempotent(
    db_session, project_novel_id: str
) -> None:
    service = WorldValidationService()

    assert not (await service.policy_status(db_session, project_novel_id)).active
    created = await service.activate_builtin_policy(db_session, project_novel_id)
    replay = await service.activate_builtin_policy(db_session, project_novel_id)

    status = await service.policy_status(db_session, project_novel_id)
    assert created.id == replay.id
    assert status.active
    assert status.policy_version == "project-default-v1"
    assert not status.semantic_enabled


@pytest.mark.asyncio
async def test_policy_status_estimates_semantic_budget_before_submit(
    db_session, project_novel_id: str
) -> None:
    policy = _policy(semantic=True).model_copy(
        update={"max_packets": 1, "max_input_characters": 4000}
    )
    lifecycle = WorldBibleLifecycleService()
    await lifecycle.create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            page_key="validation-policy",
            page_type="rule",
            title="世界书校验策略",
            status="canonical",
            page_meta_json={"validation_policy": policy.model_dump(mode="json")},
        ),
    )
    await lifecycle.create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=project_novel_id,
            page_type="location",
            title="长资料",
            free_text="x" * 5000,
        ),
    )

    status = await WorldValidationService().policy_status(db_session, project_novel_id)
    assert status.semantic_enabled
    assert status.estimated_packets >= 1
    assert status.max_packets == 1


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
            page_type="location",
            title="潮汐地理",
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
        WorldBiblePageDraftUpdate(title="潮汐地理（修订）"),
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
async def test_policy_and_rule_drafts_require_a_full_receipt(
    db_session, project_novel_id: str
) -> None:
    policy, policy_hash = await _activate_policy(db_session, project_novel_id)
    page = await db_session.scalar(
        select(WorldBiblePage).where(
            WorldBiblePage.novel_id == uuid.UUID(project_novel_id),
            WorldBiblePage.page_key == "validation-policy",
        )
    )
    assert page is not None
    lifecycle = WorldBibleLifecycleService()
    draft = await lifecycle.create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=project_novel_id,
            page_id=str(page.id),
            page_type="rule",
            title=page.title,
            page_meta_json=page.page_meta_json,
            free_text="调整后的校验策略",
        ),
    )
    service = WorldValidationService()
    (
        targeted_manifest,
        targeted_dependencies,
        target_hash,
    ) = await service._freeze_manifest(
        db_session,
        novel_id=project_novel_id,
        scope="targeted",
        target_type="world_bible_draft",
        target_id=draft.id,
    )
    targeted = WorldValidationRun(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(project_novel_id),
        trigger="test",
        scope="targeted",
        scope_json={
            "target_type": "world_bible_draft",
            "target_id": draft.id,
            "target_hash": target_hash,
        },
        status="completed",
        verdict="pass",
        gate="pass",
        policy_version=policy.policy_version,
        policy_hash=policy_hash,
        manifest_json=targeted_manifest,
        manifest_hash=stable_hash(targeted_manifest),
        dependency_hash=targeted_dependencies,
    )
    db_session.add(targeted)
    await db_session.flush()
    with pytest.raises(ConflictError) as exc_info:
        await service.require_gate(
            db_session,
            novel_id=project_novel_id,
            validation_run_id=str(targeted.id),
            target_type="world_bible_draft",
            target_id=draft.id,
            target_hash=target_hash or "",
        )
    assert exc_info.value.context["reason"] == "full_scope_required"

    full_manifest, full_dependencies, _ = await service._freeze_manifest(
        db_session,
        novel_id=project_novel_id,
        scope="full",
        target_type=None,
        target_id=None,
    )
    full = WorldValidationRun(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(project_novel_id),
        trigger="test",
        scope="full",
        scope_json={},
        status="completed",
        verdict="pass",
        gate="pass",
        policy_version=policy.policy_version,
        policy_hash=policy_hash,
        manifest_json=full_manifest,
        manifest_hash=stable_hash(full_manifest),
        dependency_hash=full_dependencies,
    )
    db_session.add(full)
    await db_session.flush()
    await service.require_gate(
        db_session,
        novel_id=project_novel_id,
        validation_run_id=str(full.id),
        target_type="world_bible_draft",
        target_id=draft.id,
        target_hash=target_hash or "",
    )


@pytest.mark.asyncio
async def test_adoption_package_requires_and_is_included_in_full_receipt(
    db_session, project_novel_id: str
) -> None:
    policy, policy_hash = await _activate_policy(db_session, project_novel_id)
    package = CreationSuggestion(
        novel_id=uuid.UUID(project_novel_id),
        source_module="world",
        review_group="world_adoption",
        target_type="world_adoption_package",
        action_schema="world_adoption_package.v1",
        payload_json={
            "schema_version": "world_adoption_package.v1",
            "source_manifest_hash": "c" * 64,
            "items": [
                {
                    "item_key": "place",
                    "kind": "core_entity",
                    "disposition": "open",
                    "authority_kind": "author_seed",
                    "source_refs": [],
                    "payload": {
                        "operation": "create",
                        "entity": {"entity_type": "location", "name": "雾港"},
                    },
                }
            ],
        },
        status="pending",
    )
    db_session.add(package)
    await db_session.flush()
    service = WorldValidationService()
    (
        targeted_manifest,
        targeted_dependency_hash,
        target_hash,
    ) = await service._freeze_manifest(
        db_session,
        novel_id=project_novel_id,
        scope="targeted",
        target_type="world_adoption_package",
        target_id=str(package.id),
    )
    targeted = WorldValidationRun(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(project_novel_id),
        trigger="test",
        scope="targeted",
        scope_json={
            "target_type": "world_adoption_package",
            "target_id": str(package.id),
            "target_hash": target_hash,
        },
        status="completed",
        verdict="pass",
        gate="pass",
        policy_version=policy.policy_version,
        policy_hash=policy_hash,
        manifest_json=targeted_manifest,
        manifest_hash=stable_hash(targeted_manifest),
        dependency_hash=targeted_dependency_hash,
    )
    db_session.add(targeted)
    await db_session.flush()
    with pytest.raises(ConflictError) as exc_info:
        await service.require_gate(
            db_session,
            novel_id=project_novel_id,
            validation_run_id=str(targeted.id),
            target_type="world_adoption_package",
            target_id=str(package.id),
            target_hash=target_hash or "",
        )
    assert exc_info.value.context["reason"] == "full_scope_required"

    manifest, dependency_hash, _ = await service._freeze_manifest(
        db_session,
        novel_id=project_novel_id,
        scope="full",
        target_type=None,
        target_id=None,
    )
    assert f"adoption:{package.id}" in {item["source_key"] for item in manifest["items"]}
    full = WorldValidationRun(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(project_novel_id),
        trigger="test",
        scope="full",
        scope_json={},
        status="completed",
        verdict="pass",
        gate="pass",
        policy_version=policy.policy_version,
        policy_hash=policy_hash,
        manifest_json=manifest,
        manifest_hash=stable_hash(manifest),
        dependency_hash=dependency_hash,
    )
    db_session.add(full)
    await db_session.flush()
    await service.require_gate(
        db_session,
        novel_id=project_novel_id,
        validation_run_id=str(full.id),
        target_type="world_adoption_package",
        target_id=str(package.id),
        target_hash=target_hash or "",
    )


@pytest.mark.asyncio
async def test_full_receipt_becomes_stale_after_world_state_checkpoint_changes(
    db_session, project_novel_id: str
) -> None:
    from modules.world.tests.test_adoption_package import _world_design_state

    adoption = WorldAdoptionPackageService()
    request = WorldDesignCheckpointSaveRequest(
        novel_id=project_novel_id,
        checkpoint=WorldDesignCheckpointPayload.model_validate(
            {
                "schema_version": "world_design_checkpoint.v1",
                "depth": "seed",
                "round_no": 3,
                "action": "consolidate",
                "source_manifest_hash": "a" * 64,
                "world_state": _world_design_state(),
            }
        ),
    )
    first = await adoption.save_design_checkpoint(db_session, request)
    service = WorldValidationService()
    manifest, dependency_hash, _ = await service._freeze_manifest(
        db_session,
        novel_id=project_novel_id,
        scope="full",
        target_type=None,
        target_id=None,
    )
    policy = service.builtin_policy()
    run = WorldValidationRun(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(project_novel_id),
        trigger="test",
        scope="full",
        scope_json={},
        status="completed",
        verdict="pass",
        gate="pass",
        policy_version=policy.policy_version,
        policy_hash=stable_hash(policy.model_dump(mode="json")),
        manifest_json=manifest,
        manifest_hash=stable_hash(manifest),
        dependency_hash=dependency_hash,
    )
    db_session.add(run)
    await db_session.flush()

    next_request = request.model_copy(deep=True)
    next_request.checkpoint.parent_checkpoint_id = first.id
    next_request.checkpoint.round_no = 6
    await adoption.save_design_checkpoint(db_session, next_request)

    refreshed = await service.get(db_session, project_novel_id, str(run.id))
    assert refreshed.status == "stale"
    assert refreshed.gate == "block"


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
    assert result["gate"] == "block"
    assert result["receipt_hash"]
    history = await service.list_runs(db_session, project_novel_id)
    assert history.total == 1
    assert history.items[0].id == created.id


@pytest.mark.asyncio
async def test_semantic_retry_resumes_after_the_last_persisted_shard(
    db_session, project_novel_id: str
) -> None:
    policy = _policy(semantic=True).model_copy(
        update={"packet_character_limit": 4000, "max_input_characters": 8000}
    )
    manifest = {
        "scope": "full",
        "items": [
            {
                "source_key": "page:1",
                "target_type": "world_bible_page",
                "target_id": "1",
                "title": "潮汐城",
                "page_type": "location",
                "status": "canonical",
                "version": 1,
                "content_hash": stable_hash("x" * 5000),
                "content": "x" * 5000,
            }
        ],
    }
    packets, _ = build_review_packets(
        run_id="run", scope="full", policy=policy, manifest=manifest
    )
    assert len(packets) == 2
    task = AsyncTask(
        task_type="world_validation",
        novel_id=uuid.UUID(project_novel_id),
        meta={"novel_id": project_novel_id},
        max_attempts=2,
        recovery_policy="auto_requeue",
    )
    db_session.add(task)
    await db_session.flush()
    task.mark_running(lease_id=str(uuid.uuid4()))
    run = WorldValidationRun(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(project_novel_id),
        task_id=task.id,
        trigger="test",
        scope="full",
        scope_json={},
        status="running",
        policy_version=policy.policy_version,
        policy_hash=stable_hash(policy.model_dump(mode="json")),
        manifest_json=manifest,
        manifest_hash=stable_hash(manifest),
        dependency_hash=stable_hash([]),
        model_snapshot_json={"llm": {"model": "test-model"}},
    )
    db_session.add(run)
    await db_session.flush()
    output = WorldValidationSemanticOutput.model_validate(
        {
            "answers": [
                {
                    "question_id": "Q1",
                    "verdict": "mixed",
                    "category": "ontology",
                    "action": "KEEP-GATE",
                    "explanation": "需继续核对",
                    "source_key": "page:1",
                    "excerpt": "x",
                }
            ]
        }
    )
    service = WorldValidationService()

    async def run_once(side_effect):
        client = AsyncMock()
        with (
            patch(
                "modules.world.services.worldbuilding.world_validation_service."
                "restore_project_llm_execution_settings",
                autospec=True,
                return_value={"llm": {"model": "test-model"}},
            ),
            patch(
                "modules.world.services.worldbuilding.world_validation_service."
                "create_project_snapshot_llm_client",
                autospec=True,
                return_value=client,
            ),
            patch(
                "modules.world.services.worldbuilding.world_validation_service."
                "run_managed_structured",
                autospec=True,
                side_effect=side_effect,
            ) as managed,
        ):
            result = await service._semantic_review(
                db_session,
                novel_id=project_novel_id,
                run_id=str(run.id),
                task_id=str(task.id),
                lease_id=str(task.lease_id),
                attempt=task.attempt,
                policy=policy,
                snapshot=run.model_snapshot_json,
                packets=packets,
            )
        return result, managed.await_count

    with pytest.raises(RuntimeError, match="interrupted"):
        await run_once([output, RuntimeError("interrupted")])
    await db_session.refresh(run)
    assert len(run.packet_hashes_json) == 1

    (findings, coverage, hashes), calls = await run_once([output])
    assert calls == 1
    assert len(hashes) == 2
    assert len(coverage) == 2
    assert len(findings) == 2
