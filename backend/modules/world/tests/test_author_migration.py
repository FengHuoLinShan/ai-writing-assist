"""表格迁移 world 落库（ADR-0030 / 计划 §4 L2）的计划、采用与回滚测试。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError
from modules.world.contracts import (
    AuthorMigrationEntityInput,
    AuthorMigrationRelationInput,
    AuthorMigrationWorldRequest,
)
from modules.world.facade import (
    apply_author_migration_world,
    plan_author_migration_world,
    rollback_author_migration_world,
)
from modules.world.models import Character, CoreEntity, EntityRelation
from modules.world.services.core.entity_service import WorldEntityService
from modules.world.services.worldbuilding.world_validation_service import (
    WorldValidationService,
)
from tests.utils import _create_entity

OWNER = "owner-1"


def _entity(
    item_key: str = "e1",
    name: str = "林澈",
    entity_type: str = "character",
    **kwargs,
) -> AuthorMigrationEntityInput:
    payload = {
        "item_key": item_key,
        "source_ref": "f0s0:r2",
        "source_hash": "a" * 64,
        "name": name,
        "entity_type": entity_type,
    }
    payload.update(kwargs)
    return AuthorMigrationEntityInput.model_validate(payload)


def _relation(
    item_key: str = "r1",
    source_name: str = "林澈",
    target_name: str = "沈青",
    **kwargs,
) -> AuthorMigrationRelationInput:
    payload = {
        "item_key": item_key,
        "source_ref": "f0s1:r2",
        "source_hash": "b" * 64,
        "source_name": source_name,
        "target_name": target_name,
        "relation_type": "盟友",
    }
    payload.update(kwargs)
    return AuthorMigrationRelationInput.model_validate(payload)


def _request(entities=(), relations=()) -> AuthorMigrationWorldRequest:
    return AuthorMigrationWorldRequest(
        migration_id="m1",
        entities=list(entities),
        relations=list(relations),
    )


def _item(plan, item_key):
    matched = [item for item in plan.items if item.item_key == item_key]
    assert len(matched) == 1
    return matched[0]


async def _get_entity(db: AsyncSession, novel_id: str, name: str) -> CoreEntity | None:
    return (
        (
            await db.execute(
                select(CoreEntity).where(
                    CoreEntity.novel_id == uuid.UUID(hex=novel_id),
                    CoreEntity.name == name,
                )
            )
        )
        .scalars()
        .unique()
        .first()
    )


async def _seed_entity(
    db: AsyncSession,
    novel_id: str,
    entity_type: str,
    name: str,
    *,
    status: str = "canonical",
    **kwargs,
) -> CoreEntity:
    entity = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        entity_type=entity_type,
        name=name,
        status=status,
        **kwargs,
    )
    db.add(entity)
    await db.flush()
    return entity


# ============================================================
# plan：动作判定
# ============================================================


@pytest.mark.asyncio
async def test_plan_new_entity_is_create(db_session, project_novel_id):
    plan = await plan_author_migration_world(
        db_session, project_novel_id, _request([_entity()])
    )
    item = _item(plan, "e1")
    assert item.action == "create"
    assert item.target_id is None
    assert plan.validation_policy_active is False
    assert len(plan.fingerprint) == 64


@pytest.mark.asyncio
async def test_plan_same_name_canonical_fills_only_empty(db_session, project_novel_id):
    await _seed_entity(
        db_session, project_novel_id, "character", "林澈"
    )
    plan = await plan_author_migration_world(
        db_session,
        project_novel_id,
        _request([_entity(summary="北境剑客", hidden_truth="身负血仇")]),
    )
    item = _item(plan, "e1")
    assert item.action == "fill_empty"
    assert set(item.fills) == {"summary", "hidden_truth"}
    assert item.target_id


@pytest.mark.asyncio
async def test_plan_existing_ref_when_nothing_to_fill(db_session, project_novel_id):
    await _seed_entity(
        db_session, project_novel_id, "character", "林澈",
            summary="北境剑客", hidden_truth="身负血仇",
        )
    plan = await plan_author_migration_world(
        db_session,
        project_novel_id,
        _request([_entity(summary="北境剑客", hidden_truth="身负血仇")]),
    )
    item = _item(plan, "e1")
    assert item.action == "existing_ref"
    assert item.fills == []


@pytest.mark.asyncio
async def test_plan_field_conflict_and_append_note(db_session, project_novel_id):
    await _seed_entity(
        db_session, project_novel_id, "character", "林澈",
            summary="北境剑客", hidden_truth="身负血仇",
        )
    plan = await plan_author_migration_world(
        db_session,
        project_novel_id,
        _request([_entity(summary="南境刀客", hidden_truth="新秘密")]),
    )
    item = _item(plan, "e1")
    assert item.action == "conflict"
    assert {c.field for c in item.conflicts} == {"summary", "hidden_truth"}

    plan = await plan_author_migration_world(
        db_session,
        project_novel_id,
        _request(
            [_entity(summary="南境刀客", hidden_truth="新秘密", decision="append_note")]
        ),
    )
    item = _item(plan, "e1")
    assert item.action == "conflict"  # summary 仍冲突
    assert {c.field for c in item.conflicts} == {"summary"}

    plan = await plan_author_migration_world(
        db_session,
        project_novel_id,
        _request(
            [
                _entity(
                    summary="北境剑客",
                    hidden_truth="新秘密",
                    decision="append_note",
                )
            ]
        ),
    )
    item = _item(plan, "e1")
    assert item.action == "fill_empty"
    assert item.fills == ["hidden_truth"]


@pytest.mark.asyncio
async def test_plan_candidate_adoption_and_stale(db_session, project_novel_id):
    await _create_entity(
        db_session, project_novel_id, "character", "林澈", status="candidate"
    )
    plan = await plan_author_migration_world(
        db_session, project_novel_id, _request([_entity(summary="北境剑客")])
    )
    item = _item(plan, "e1")
    assert item.action == "adopt_existing"

    stale = await _create_entity(
        db_session, project_novel_id, "character", "沈青", status="candidate"
    )
    stale.content_json = {
        "_meta": {"evolution_ref": {"run_key": "rk", "attempt_id": 1}}
    }
    plan = await plan_author_migration_world(
        db_session, project_novel_id, _request([_entity(name="沈青")])
    )
    item = _item(plan, "e1")
    assert item.action == "conflict"
    assert item.reason_code == "stale_candidate"


@pytest.mark.asyncio
async def test_plan_pending_suggestion_shadow_needs_review(
    db_session, project_novel_id
):
    shadow = await _create_entity(
        db_session, project_novel_id, "character", "林澈", status="candidate"
    )
    shadow.content_json = {
        "_meta": {"compatibility_shadow": True, "suggestion_id": str(uuid.uuid4())}
    }
    plan = await plan_author_migration_world(
        db_session, project_novel_id, _request([_entity()])
    )
    item = _item(plan, "e1")
    assert item.action == "needs_review"
    assert item.reason_code == "compatibility_shadow"


@pytest.mark.asyncio
async def test_plan_similar_name_requires_author_decision(db_session, project_novel_id):
    await _create_entity(db_session, project_novel_id, "character", "林澈儿")
    plan = await plan_author_migration_world(
        db_session, project_novel_id, _request([_entity()])
    )
    item = _item(plan, "e1")
    assert item.action == "similar_name"
    assert item.similar and item.similar[0]["name"] == "林澈儿"

    plan = await plan_author_migration_world(
        db_session, project_novel_id, _request([_entity(decision="different_object")])
    )
    assert _item(plan, "e1").action == "create"


@pytest.mark.asyncio
async def test_plan_alias_collision(db_session, project_novel_id):
    await _create_entity(db_session, project_novel_id, "character", "小林")
    plan = await plan_author_migration_world(
        db_session, project_novel_id, _request([_entity(aliases=["小林"])])
    )
    item = _item(plan, "e1")
    assert item.action == "alias_collision"
    assert item.reason_code == "alias_collision"


@pytest.mark.asyncio
async def test_plan_ignores_same_name_in_other_novel(db_session, two_projects):
    novel_a, novel_b = two_projects
    await _create_entity(db_session, novel_b, "character", "林澈", summary="已有")
    plan = await plan_author_migration_world(
        db_session, novel_a, _request([_entity()])
    )
    assert _item(plan, "e1").action == "create"


@pytest.mark.asyncio
async def test_plan_duplicate_names_in_file_conflict(db_session, project_novel_id):
    plan = await plan_author_migration_world(
        db_session,
        project_novel_id,
        _request([_entity(item_key="e1"), _entity(item_key="e2")]),
    )
    assert _item(plan, "e1").action == "create"
    assert _item(plan, "e2").action == "conflict"
    assert _item(plan, "e2").reason_code == "duplicate_in_file"


# ============================================================
# plan：关系处理
# ============================================================


@pytest.mark.asyncio
async def test_plan_relation_kind_resolution_order(db_session, project_novel_id):
    source = await _create_entity(db_session, project_novel_id, "character", "林澈")
    target = await _create_entity(db_session, project_novel_id, "character", "沈青")
    request = _request(
        relations=[
            _relation(item_key="r1", relation_type="盟友"),
            _relation(item_key="r2", relation_type="追杀"),
            _relation(item_key="r3", relation_type="随便什么", relation_kind="causal"),
        ]
    )
    plan = await plan_author_migration_world(db_session, project_novel_id, request)
    catalog = _item(plan, "r1")
    assert catalog.relation_kind == "social"
    assert catalog.relation_kind_guessed is False
    guessed = _item(plan, "r2")
    assert guessed.relation_kind == "intentional"
    assert guessed.relation_kind_guessed is True
    override = _item(plan, "r3")
    assert override.relation_kind == "causal"
    assert override.relation_kind_guessed is False
    assert source and target


@pytest.mark.asyncio
async def test_plan_relation_endpoints_and_dedup(db_session, project_novel_id):
    request = _request(
        entities=[_entity(item_key="e1"), _entity(item_key="e2", name="沈青")],
        relations=[
            _relation(item_key="r1"),
            _relation(item_key="r2", symmetric=True),
            _relation(
                item_key="r3", source_name="林澈", target_name="不存在的人"
            ),
        ],
    )
    plan = await plan_author_migration_world(db_session, project_novel_id, request)
    assert _item(plan, "r1").action == "create"
    duplicate = _item(plan, "r2")
    assert duplicate.action == "skip"
    assert duplicate.reason_code == "duplicate"
    missing = _item(plan, "r3")
    assert missing.action == "conflict"
    assert missing.reason_code == "endpoint_missing"


@pytest.mark.asyncio
async def test_plan_existing_canonical_edge_variants(db_session, project_novel_id):
    source = await _create_entity(db_session, project_novel_id, "character", "林澈")
    target = await _create_entity(db_session, project_novel_id, "character", "沈青")
    relation = EntityRelation(
        novel_id=uuid.UUID(hex=project_novel_id),
        source_id=source.id,
        target_id=target.id,
        relation_type="ally_of",
        relation_kind="social",
        description="旧描述",
        status="canonical",
    )
    db_session.add(relation)
    await db_session.flush()

    base = dict(source_name="林澈", target_name="沈青", relation_type="盟友")
    plan = await plan_author_migration_world(
        db_session,
        project_novel_id,
        _request(
            relations=[
                _relation(item_key="r1", description="旧描述", **base),
                _relation(item_key="r2", description="新描述", **base),
            ]
        ),
    )
    assert _item(plan, "r1").action == "existing_ref"
    conflict = _item(plan, "r2")
    assert conflict.action == "conflict"
    assert conflict.reason_code == "description_conflict"

    plan = await plan_author_migration_world(
        db_session,
        project_novel_id,
        _request(relations=[_relation(item_key="r3", description=None, **base)]),
    )
    assert _item(plan, "r3").action == "existing_ref"

    relation.description = None
    await db_session.flush()
    plan = await plan_author_migration_world(
        db_session,
        project_novel_id,
        _request(
            relations=[_relation(item_key="r1", description="新描述", **base)]
        ),
    )
    fill = _item(plan, "r1")
    assert fill.action == "fill_empty"
    assert fill.target_id == str(relation.id)


# ============================================================
# apply
# ============================================================


@pytest.mark.asyncio
async def test_apply_creates_canonical_entity_with_provenance(
    db_session, project_novel_id
):
    plan = await plan_author_migration_world(
        db_session,
        project_novel_id,
        _request(
            [
                _entity(
                    summary="北境剑客",
                    hidden_truth="身负血仇",
                    aliases=["小林"],
                    author_notes=[{"label": "口头禅", "value": "无妨"}],
                    character_fields={"role": "剑客", "fear": "火"},
                )
            ]
        ),
    )
    receipt = await apply_author_migration_world(
        db_session,
        project_novel_id,
        _request(
            [
                _entity(
                    summary="北境剑客",
                    hidden_truth="身负血仇",
                    aliases=["小林"],
                    author_notes=[{"label": "口头禅", "value": "无妨"}],
                    character_fields={"role": "剑客", "fear": "火"},
                )
            ]
        ),
        expected_fingerprint=plan.fingerprint,
        authorized_by=OWNER,
    )

    entity = await _get_entity(db_session, project_novel_id, "林澈")
    assert entity is not None and entity.status == "canonical"
    assert entity.created_by == "spreadsheet_migration"
    assert entity.approved_by == OWNER
    meta = (entity.content_json or {}).get("_meta")
    assert meta["source"] == "spreadsheet_migration"
    block = meta["spreadsheet_migration"]
    assert block["migration_id"] == "m1"
    assert block["source_ref"] == "f0s0:r2"
    assert block["authorized_by"] == OWNER
    assert "【表格·口头禅】无妨" in entity.hidden_truth

    aliases = (entity.content_json or {}).get("aliases")
    assert [a["alias"] for a in aliases] == ["小林"]
    assert aliases[0]["status"] == "confirmed"
    assert aliases[0]["source"] == "spreadsheet_migration"

    character = await db_session.get(Character, entity.id)
    assert character is not None and character.role == "剑客" and character.fear == "火"

    assert receipt.entity_ids["e1"] == str(entity.id)
    operations = {change.operation for change in receipt.applied_changes}
    assert {"create", "alias", "fill_empty"} <= operations
    create_change = next(
        c for c in receipt.applied_changes if c.operation == "create"
    )
    assert create_change.before == {}
    fill_change = next(
        c for c in receipt.applied_changes if c.kind == "character"
    )
    assert set(fill_change.before) == {"role", "fear"}
    assert all(value is None for value in fill_change.before.values())


@pytest.mark.asyncio
async def test_apply_creates_relation_between_new_entities(
    db_session, project_novel_id
):
    entities = [_entity(item_key="e1"), _entity(item_key="e2", name="沈青")]
    relations = [
        _relation(
            item_key="r1",
            source_item_key="e1",
            target_item_key="e2",
            description="并肩作战",
        )
    ]
    request = _request(entities, relations)
    plan = await plan_author_migration_world(db_session, project_novel_id, request)
    receipt = await apply_author_migration_world(
        db_session,
        project_novel_id,
        request,
        expected_fingerprint=plan.fingerprint,
        authorized_by=OWNER,
    )
    row = (
        await db_session.execute(select(EntityRelation))
    ).scalars().first()
    assert row is not None
    assert row.status == "canonical"
    assert row.relation_kind == "social"
    assert row.description == "并肩作战"
    assert str(row.source_id) == receipt.entity_ids["e1"]
    assert str(row.target_id) == receipt.entity_ids["e2"]
    assert row.review_meta["source"] == "spreadsheet_migration"


@pytest.mark.asyncio
async def test_apply_fills_existing_entity_and_appends_note(
    db_session, project_novel_id
):
    await _seed_entity(
        db_session, project_novel_id, "character", "林澈", hidden_truth="身负血仇"
    )
    item = _entity(summary="北境剑客", decision="append_note")
    request = _request([item])
    plan = await plan_author_migration_world(db_session, project_novel_id, request)
    await apply_author_migration_world(
        db_session,
        project_novel_id,
        request,
        expected_fingerprint=plan.fingerprint,
        authorized_by=OWNER,
    )
    entity = await _get_entity(db_session, project_novel_id, "林澈")
    assert entity.summary == "北境剑客"
    assert entity.hidden_truth.startswith("身负血仇")
    assert "新秘密" not in entity.hidden_truth  # 未提供新秘密时不追加

    item = _entity(summary="北境剑客", hidden_truth="新秘密", decision="append_note")
    request = _request([item])
    plan = await plan_author_migration_world(db_session, project_novel_id, request)
    await apply_author_migration_world(
        db_session,
        project_novel_id,
        request,
        expected_fingerprint=plan.fingerprint,
        authorized_by=OWNER,
    )
    entity = await _get_entity(db_session, project_novel_id, "林澈")
    assert "身负血仇" in entity.hidden_truth
    assert "新秘密" in entity.hidden_truth


@pytest.mark.asyncio
async def test_apply_promotes_candidate_then_fills(db_session, project_novel_id):
    candidate = await _create_entity(
        db_session, project_novel_id, "character", "林澈", status="candidate"
    )
    item = _entity(summary="北境剑客")
    request = _request([item])
    plan = await plan_author_migration_world(db_session, project_novel_id, request)
    receipt = await apply_author_migration_world(
        db_session,
        project_novel_id,
        request,
        expected_fingerprint=plan.fingerprint,
        authorized_by=OWNER,
    )
    entity = await _get_entity(db_session, project_novel_id, "林澈")
    assert entity.status == "canonical"
    assert entity.summary == "北境剑客"
    operations = [c.operation for c in receipt.applied_changes]
    assert "promote" in operations and "fill_empty" in operations
    promote_change = next(c for c in receipt.applied_changes if c.operation == "promote")
    assert promote_change.before == {"status": "candidate"}
    assert receipt.entity_ids["e1"] == str(candidate.id)


@pytest.mark.asyncio
async def test_apply_relation_fill_and_description_conflict(
    db_session, project_novel_id
):
    source = await _create_entity(db_session, project_novel_id, "character", "林澈")
    target = await _create_entity(db_session, project_novel_id, "character", "沈青")
    relation = EntityRelation(
        novel_id=uuid.UUID(hex=project_novel_id),
        source_id=source.id,
        target_id=target.id,
        relation_type="ally_of",
        relation_kind="social",
        description=None,
        status="canonical",
    )
    db_session.add(relation)
    await db_session.flush()

    relations = [
        _relation(
            item_key="r1",
            source_name="林澈",
            target_name="沈青",
            relation_type="盟友",
            description="旧交情",
        ),
        _relation(
            item_key="r2",
            source_name="林澈",
            target_name="沈青",
            relation_type="盟友",
            description="另一段描述",
        ),
    ]
    request = _request(relations=relations)
    plan = await plan_author_migration_world(db_session, project_novel_id, request)
    receipt = await apply_author_migration_world(
        db_session,
        project_novel_id,
        request,
        expected_fingerprint=plan.fingerprint,
        authorized_by=OWNER,
    )
    await db_session.refresh(relation)
    assert relation.description == "旧交情"
    assert relation.relation_type == "ally_of"
    total = (
        await db_session.execute(select(EntityRelation))
    ).scalars().all()
    assert len(total) == 1
    assert receipt.entity_ids == {}


@pytest.mark.asyncio
async def test_apply_stale_fingerprint_writes_nothing(db_session, project_novel_id):
    target = await _seed_entity(
        db_session, project_novel_id, "character", "林澈"
    )
    request = _request([_entity(summary="北境剑客")])
    plan = await plan_author_migration_world(db_session, project_novel_id, request)
    # 预览后作者补充了该对象的资料，指纹过期
    target.hidden_truth = "预览后修改"
    await db_session.flush()
    with pytest.raises(ConflictError) as exc_info:
        await apply_author_migration_world(
            db_session,
            project_novel_id,
            _request([_entity(summary="北境剑客")]),
            expected_fingerprint=plan.fingerprint,
            authorized_by=OWNER,
        )
    assert exc_info.value.code == "migration_preview_stale"
    assert target.summary is None
    assert await _get_entity(db_session, project_novel_id, "新对象") is None


@pytest.mark.asyncio
async def test_apply_policy_active_fails_closed_without_writes(
    db_session, project_novel_id
):
    from unittest.mock import patch

    request = _request([_entity()])
    plan = await plan_author_migration_world(db_session, project_novel_id, request)
    assert plan.validation_policy_active is False

    with patch.object(
        WorldValidationService,
        "active_policy",
        autospec=True,
        return_value=({"enabled": True}, "policy-hash"),
    ):
        policy_plan = await plan_author_migration_world(
            db_session, project_novel_id, request
        )
        assert policy_plan.validation_policy_active is True
        with pytest.raises(ConflictError) as exc_info:
            await apply_author_migration_world(
                db_session,
                project_novel_id,
                request,
                expected_fingerprint=plan.fingerprint,
                authorized_by=OWNER,
            )
    assert exc_info.value.code == "required_validation"
    assert await _get_entity(db_session, project_novel_id, "林澈") is None


@pytest.mark.asyncio
async def test_apply_flush_exception_propagates(db_session, project_novel_id):
    from unittest.mock import patch

    request = _request([_entity()])
    plan = await plan_author_migration_world(db_session, project_novel_id, request)
    with (
        patch.object(
            WorldEntityService,
            "create",
            autospec=True,
            side_effect=SQLAlchemyError("boom"),
        ),
        pytest.raises(SQLAlchemyError),
    ):
        await apply_author_migration_world(
            db_session,
            project_novel_id,
            request,
            expected_fingerprint=plan.fingerprint,
            authorized_by=OWNER,
        )


# ============================================================
# rollback
# ============================================================


async def _apply_simple(db: AsyncSession, novel_id: str):
    entities = [_entity(item_key="e1"), _entity(item_key="e2", name="沈青")]
    relations = [
        _relation(
            item_key="r1",
            source_item_key="e1",
            target_item_key="e2",
            description="并肩作战",
        )
    ]
    request = _request(entities, relations)
    plan = await plan_author_migration_world(db, novel_id, request)
    receipt = await apply_author_migration_world(
        db,
        novel_id,
        request,
        expected_fingerprint=plan.fingerprint,
        authorized_by=OWNER,
    )
    return request, receipt


@pytest.mark.asyncio
async def test_rollback_reverts_in_reverse_order(db_session, project_novel_id):
    _, receipt = await _apply_simple(db_session, project_novel_id)
    entity = await _get_entity(db_session, project_novel_id, "林澈")
    relation = (
        await db_session.execute(select(EntityRelation))
    ).scalars().first()

    dry = await rollback_author_migration_world(
        db_session, project_novel_id, receipt, dry_run=True
    )
    assert set(dry.reverted) == {c.item_key for c in receipt.applied_changes}
    await db_session.refresh(entity)
    await db_session.refresh(relation)
    assert entity.status == "canonical" and relation.status == "canonical"

    result = await rollback_author_migration_world(
        db_session, project_novel_id, receipt, dry_run=False
    )
    assert result.kept == []
    assert set(result.reverted) == {c.item_key for c in receipt.applied_changes}
    await db_session.refresh(entity)
    await db_session.refresh(relation)
    assert entity.status == "deprecated"
    assert relation.status == "deprecated"


@pytest.mark.asyncio
async def test_rollback_keeps_modified_entities(db_session, project_novel_id):
    _, receipt = await _apply_simple(db_session, project_novel_id)
    entity = await _get_entity(db_session, project_novel_id, "林澈")
    entity.summary = "作者后来补充的简介"
    await db_session.flush()

    result = await rollback_author_migration_world(
        db_session, project_novel_id, receipt, dry_run=False
    )
    kept_keys = {entry["item_key"] for entry in result.kept}
    assert any(
        entry["reason_code"] == "modified_after_migration" for entry in result.kept
    )
    await db_session.refresh(entity)
    assert entity.status == "canonical"
    assert entity.summary == "作者后来补充的简介"
    # 关系先于实体回滚，不受实体保留影响
    relation = (
        await db_session.execute(select(EntityRelation))
    ).scalars().first()
    assert relation.status == "deprecated"
    assert kept_keys


@pytest.mark.asyncio
async def test_rollback_keeps_referenced_entities(db_session, project_novel_id):
    _, receipt = await _apply_simple(db_session, project_novel_id)
    created = await _get_entity(db_session, project_novel_id, "林澈")
    anchor = await _create_entity(db_session, project_novel_id, "location", "北境")
    external = EntityRelation(
        novel_id=uuid.UUID(hex=project_novel_id),
        source_id=anchor.id,
        target_id=created.id,
        relation_type="located_at",
        relation_kind="spatial",
        status="canonical",
    )
    db_session.add(external)
    await db_session.flush()

    result = await rollback_author_migration_world(
        db_session, project_novel_id, receipt, dry_run=False
    )
    assert {
        entry["reason_code"] for entry in result.kept if "e1" in entry["item_key"]
    } == {"referenced"}
    await db_session.refresh(created)
    assert created.status == "canonical"


@pytest.mark.asyncio
async def test_apply_queries_writing_progress_once_for_all_fills(
    db_session, project_novel_id
):
    """批量补齐只在循环前查一次写作进度，逐项传给实体快照（TASK §6.3）。"""
    from unittest.mock import patch

    from modules.world.models import EntityRevision
    from modules.writing import facade as writing_facade

    names = ("林澈", "沈青", "周岚")
    for name in names:
        await _seed_entity(db_session, project_novel_id, "character", name)
    request = _request(
        [
            _entity(f"e{index}", name, summary=f"{name}的概要")
            for index, name in enumerate(names)
        ]
    )
    plan = await plan_author_migration_world(db_session, project_novel_id, request)
    real_query = writing_facade.get_latest_effective_chapter_index
    with patch.object(
        writing_facade,
        "get_latest_effective_chapter_index",
        autospec=True,
        side_effect=real_query,
    ) as progress_query:
        await apply_author_migration_world(
            db_session,
            project_novel_id,
            request,
            expected_fingerprint=plan.fingerprint,
            authorized_by=OWNER,
        )
    assert progress_query.await_count == 1
    revisions = (
        (
            await db_session.execute(
                select(EntityRevision).where(
                    EntityRevision.novel_id == uuid.UUID(hex=project_novel_id)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(revisions) == len(names)
    assert {revision.writing_chapter_index for revision in revisions} == {0}
