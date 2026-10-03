"""世界关系分组成员批量维护 — EntityRelationService.membership_batch 单元测试。

覆盖 TASK.md §6 写入/失败行：默认与显式关系三元组、canonical 复用不动证据、
候选冲突拒绝整批、移出精确清单与历史保留、重复移出/陈旧指纹、重新添加、
0.0 强度复用、类型/端点/跨项目边界、Canon 校验门禁、DB 故障整批撤回、
synopsis/context 失效钩子，以及 review_edit 的可选执行指纹 CAS。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.models import CoreEntity, EntityRelation
from modules.world.repositories import (
    CoreEntityRepository,
    EntityRelationRepository,
)
from modules.world.schemas import (
    EntityRelationCreate,
    EntityRelationReviewEditRequest,
    WorldRelationMembershipBatchRequest,
)
from modules.world.services.common import entity_relation_execution_fingerprint
from modules.world.services.core.entity_relation_service import EntityRelationService
from modules.world.services.worldbuilding.world_validation_service import (
    WorldValidationService,
)
from modules.world.tests.helpers import _create_project

_entity_repo = CoreEntityRepository()
_relation_repo = EntityRelationRepository()


async def _seed_novel(db: AsyncSession) -> str:
    novel_id = uuid.uuid4().hex
    await _create_project(db, novel_id)
    return novel_id


async def _seed_entity(
    db: AsyncSession,
    novel_id: str,
    entity_type: str,
    name: str,
    *,
    status: str = "canonical",
) -> CoreEntity:
    return await _entity_repo.create_raw(
        db,
        novel_id=uuid.UUID(hex=novel_id),
        entity_type=entity_type,
        name=name,
        status=status,
    )


async def _seed_relation(
    db: AsyncSession,
    novel_id: str,
    *,
    source_id: str,
    target_id: str,
    relation_type: str,
    relation_kind: str | None = None,
    status: str = "canonical",
    strength: float = 0.8,
    description: str | None = None,
    quote: str | None = None,
    review_meta: dict | None = None,
) -> EntityRelation:
    return await _relation_repo.create(
        db,
        uuid.UUID(hex=novel_id),
        EntityRelationCreate(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            relation_kind=relation_kind,
            description=description,
            strength=strength,
            quote=quote,
            status=status,
            review_meta=review_meta,
        ),
    )


def _add_request(
    novel_id: str,
    group_id: str,
    member_ids: list[str],
    **overrides: object,
) -> WorldRelationMembershipBatchRequest:
    payload: dict[str, object] = {
        "novel_id": novel_id,
        "action": "add",
        "group_view": "affiliation",
        "group_id": group_id,
        "member_ids": member_ids,
        "confirmed": True,
    }
    payload.update(overrides)
    return WorldRelationMembershipBatchRequest.model_validate(payload)


def _remove_request(
    novel_id: str,
    group_id: str,
    member_ids: list[str],
    refs: list[dict[str, str]],
    **overrides: object,
) -> WorldRelationMembershipBatchRequest:
    payload: dict[str, object] = {
        "novel_id": novel_id,
        "action": "remove",
        "group_view": "affiliation",
        "group_id": group_id,
        "member_ids": member_ids,
        "confirmed": True,
        "relation_refs": refs,
    }
    payload.update(overrides)
    return WorldRelationMembershipBatchRequest.model_validate(payload)


def _service() -> EntityRelationService:
    service = EntityRelationService(context_marker=AsyncMock(return_value=0))
    service._mark_synopsis_changed = AsyncMock()
    return service


async def _relation_count(db: AsyncSession, novel_id: str) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(EntityRelation)
            .where(EntityRelation.novel_id == uuid.UUID(hex=novel_id))
        )
        or 0
    )


async def _seed_affiliation(
    db: AsyncSession,
) -> tuple[str, CoreEntity, CoreEntity, CoreEntity]:
    novel_id = await _seed_novel(db)
    group = await _seed_entity(db, novel_id, "organization", "天机阁")
    first = await _seed_entity(db, novel_id, "character", "克莱恩")
    second = await _seed_entity(db, novel_id, "character", "梅丽莎")
    return novel_id, group, first, second


# ============================================================
# add
# ============================================================


@pytest.mark.asyncio
async def test_membership_add_single_and_batch_use_default_triple(
    db_session: AsyncSession,
) -> None:
    novel_id, group, first, second = await _seed_affiliation(db_session)
    service = _service()

    single = await service.membership_batch(
        db_session,
        novel_id,
        _add_request(novel_id, str(group.id), [str(first.id)]),
    )
    assert (single.added_count, single.reused_count, single.removed_count) == (1, 0, 0)

    batch = await service.membership_batch(
        db_session,
        novel_id,
        _add_request(novel_id, str(group.id), [str(second.id)]),
    )
    assert batch.added_count == 1

    relations = {
        str(rel.source_id): rel
        for rel in (
            await db_session.execute(
                select(EntityRelation).where(
                    EntityRelation.novel_id == uuid.UUID(hex=novel_id)
                )
            )
        ).scalars()
    }
    assert set(relations) == {str(first.id), str(second.id)}
    for member, rel in relations.items():
        assert str(rel.target_id) == str(group.id)
        assert rel.relation_type == "member_of"
        assert rel.relation_kind == "social"
        assert rel.status == "canonical"
        assert float(rel.strength) == 0.5
        # 作者手动确认的关系不附会原文来源。
        assert rel.quote is None
        assert rel.source_chapter_id is None
        assert rel.caused_by_event_id is None
        meta = rel.review_meta or {}
        assert meta["reviewed_by"] == "manual"
        assert meta["reviewed_from"] == "world_relation_membership_batch"
        assert meta["review_action"] == "relation_membership_added"
        assert meta["review_before"] is None
        assert meta["review_after"]["id"] == str(rel.id)
        assert meta["review_after"]["status"] == "canonical"
        assert meta["group_view"] == "affiliation"
        assert meta["group_id"] == str(group.id)
        assert member  # endpoint direction asserted through the key itself


@pytest.mark.asyncio
async def test_membership_add_explicit_preset_relation_and_custom_view(
    db_session: AsyncSession,
) -> None:
    novel_id, group, first, _second = await _seed_affiliation(db_session)
    service = _service()

    explicit = await service.membership_batch(
        db_session,
        novel_id,
        _add_request(
            novel_id,
            str(group.id),
            [str(first.id)],
            relation_type="leader_of",
            relation_kind="social",
            group_side="target",
        ),
    )
    assert explicit.added_count == 1
    rel = await db_session.get(
        EntityRelation, uuid.UUID(explicit.affected_relation_ids[0])
    )
    assert rel is not None
    assert rel.relation_type == "leader_of"
    assert rel.relation_kind == "social"
    assert str(rel.source_id) == str(first.id)
    assert str(rel.target_id) == str(group.id)

    location = await _seed_entity(db_session, novel_id, "location", "贝克兰德")
    item = await _seed_entity(db_session, novel_id, "item", "银色通行符")
    custom = await service.membership_batch(
        db_session,
        novel_id,
        _add_request(
            novel_id,
            str(location.id),
            [str(item.id)],
            group_view="custom",
            group_type="location",
            member_type="item",
            relation_type="guarded_by",
            relation_kind="intentional",
            group_side="target",
        ),
    )
    assert custom.added_count == 1
    custom_rel = await db_session.get(
        EntityRelation, uuid.UUID(custom.affected_relation_ids[0])
    )
    assert custom_rel is not None
    assert custom_rel.relation_type == "guarded_by"
    assert custom_rel.relation_kind == "intentional"
    assert (custom_rel.review_meta or {})["group_view"] == "custom"


@pytest.mark.asyncio
async def test_membership_add_rejects_relation_outside_view_rules(
    db_session: AsyncSession,
) -> None:
    novel_id, group, first, second = await _seed_affiliation(db_session)
    service = _service()

    with pytest.raises(ValidationError, match="not expressible") as foreign:
        await service.membership_batch(
            db_session,
            novel_id,
            _add_request(
                novel_id,
                str(group.id),
                [str(first.id)],
                relation_type="contains",
                relation_kind="spatial",
                group_side="target",
            ),
        )
    assert foreign.value.status_code == 422

    with pytest.raises(ValidationError, match="not expressible"):
        await service.membership_batch(
            db_session,
            novel_id,
            _add_request(
                novel_id,
                str(group.id),
                [str(first.id)],
                relation_type="member_of",
                group_side="source",
            ),
        )

    with pytest.raises(ValidationError, match="Unknown group_view"):
        await service.membership_batch(
            db_session,
            novel_id,
            _add_request(novel_id, str(group.id), [str(first.id)], group_view="bogus"),
        )

    assert await _relation_count(db_session, novel_id) == 0


@pytest.mark.asyncio
async def test_membership_add_reuses_canonical_without_touching_evidence(
    db_session: AsyncSession,
) -> None:
    novel_id, group, first, second = await _seed_affiliation(db_session)
    existing = await _seed_relation(
        db_session,
        novel_id,
        source_id=str(first.id),
        target_id=str(group.id),
        relation_type="member_of",
        relation_kind="social",
        strength=0.0,
        description="既有的作者描述",
        quote="哥哥照顾妹妹。",
        review_meta={"scene_index": 3},
    )
    service = _service()

    result = await service.membership_batch(
        db_session,
        novel_id,
        _add_request(novel_id, str(group.id), [str(first.id), str(second.id)]),
    )

    assert (result.added_count, result.reused_count) == (1, 1)
    assert result.affected_relation_ids.count(str(existing.id)) == 1
    await db_session.refresh(existing)
    # 0.0 强度合法：复用不改动既有证据、强度、描述与审计元数据。
    assert float(existing.strength) == 0.0
    assert existing.description == "既有的作者描述"
    assert existing.quote == "哥哥照顾妹妹。"
    assert existing.review_meta == {"scene_index": 3}
    synopsis_mock = service._mark_synopsis_changed
    assert str(existing.id) not in {
        call.args[2] for call in synopsis_mock.call_args_list
    }


@pytest.mark.asyncio
async def test_membership_add_candidate_conflict_rejects_whole_batch(
    db_session: AsyncSession,
) -> None:
    novel_id, group, first, second = await _seed_affiliation(db_session)
    await _seed_relation(
        db_session,
        novel_id,
        source_id=str(first.id),
        target_id=str(group.id),
        relation_type="member_of",
        relation_kind="social",
        status="candidate",
    )
    service = _service()

    with pytest.raises(ConflictError) as conflict:
        await service.membership_batch(
            db_session,
            novel_id,
            _add_request(novel_id, str(group.id), [str(first.id), str(second.id)]),
        )
    assert conflict.value.code == "relation_exists_as_candidate"
    assert conflict.value.status_code == 409

    assert await _relation_count(db_session, novel_id) == 1


# ============================================================
# remove
# ============================================================


@pytest.mark.asyncio
async def test_membership_remove_exact_refs_keep_history_and_other_relations(
    db_session: AsyncSession,
) -> None:
    novel_id, group, first, _second = await _seed_affiliation(db_session)
    other_group = await _seed_entity(db_session, novel_id, "faction", "值夜者")
    member_of = await _seed_relation(
        db_session,
        novel_id,
        source_id=str(first.id),
        target_id=str(group.id),
        relation_type="member_of",
        relation_kind="social",
    )
    leader_of = await _seed_relation(
        db_session,
        novel_id,
        source_id=str(first.id),
        target_id=str(group.id),
        relation_type="leader_of",
        relation_kind="social",
    )
    other_membership = await _seed_relation(
        db_session,
        novel_id,
        source_id=str(first.id),
        target_id=str(other_group.id),
        relation_type="member_of",
        relation_kind="social",
    )
    service = _service()

    result = await service.membership_batch(
        db_session,
        novel_id,
        _remove_request(
            novel_id,
            str(group.id),
            [str(first.id)],
            [
                {
                    "id": str(member_of.id),
                    "expected_execution_fingerprint": (
                        entity_relation_execution_fingerprint(member_of)
                    ),
                }
            ],
        ),
    )

    assert result.removed_count == 1
    assert result.affected_relation_ids == [str(member_of.id)]
    await db_session.refresh(member_of)
    await db_session.refresh(leader_of)
    await db_session.refresh(other_membership)
    # 历史保留：行仍在，状态 deprecated，审计有 before/after。
    assert member_of.status == "deprecated"
    meta = member_of.review_meta or {}
    assert meta["review_action"] == "relation_membership_removed"
    assert meta["reviewed_from"] == "world_relation_membership_batch"
    assert meta["review_before"]["status"] == "canonical"
    assert meta["review_after"]["status"] == "deprecated"
    assert meta["group_view"] == "affiliation"
    assert meta["group_id"] == str(group.id)
    # 清单精确：同成员其余关系与其它分组不受影响。
    assert leader_of.status == "canonical"
    assert other_membership.status == "canonical"


@pytest.mark.asyncio
async def test_membership_remove_rejects_duplicate_remove_and_stale_fingerprint(
    db_session: AsyncSession,
) -> None:
    novel_id, group, first, _second = await _seed_affiliation(db_session)
    member_of = await _seed_relation(
        db_session,
        novel_id,
        source_id=str(first.id),
        target_id=str(group.id),
        relation_type="member_of",
        relation_kind="social",
    )
    stale_fingerprint = entity_relation_execution_fingerprint(member_of)
    service = _service()

    removed = await service.membership_batch(
        db_session,
        novel_id,
        _remove_request(
            novel_id,
            str(group.id),
            [str(first.id)],
            [
                {
                    "id": str(member_of.id),
                    "expected_execution_fingerprint": stale_fingerprint,
                }
            ],
        ),
    )
    assert removed.removed_count == 1

    # 重复移出：旧指纹过期，按 stale_execution 处理，不生成新历史。
    with pytest.raises(ConflictError) as duplicate:
        await service.membership_batch(
            db_session,
            novel_id,
            _remove_request(
                novel_id,
                str(group.id),
                [str(first.id)],
                [
                    {
                        "id": str(member_of.id),
                        "expected_execution_fingerprint": stale_fingerprint,
                    }
                ],
            ),
        )
    assert duplicate.value.code == "stale_execution"

    # 陈旧指纹：关系被并发编辑后，读取时的指纹不再匹配。
    other = await _seed_relation(
        db_session,
        novel_id,
        source_id=str(first.id),
        target_id=str(group.id),
        relation_type="leader_of",
        relation_kind="social",
    )
    old_fingerprint = entity_relation_execution_fingerprint(other)
    other.description = "并发更新后的描述"
    await db_session.flush()
    with pytest.raises(ConflictError) as stale:
        await service.membership_batch(
            db_session,
            novel_id,
            _remove_request(
                novel_id,
                str(group.id),
                [str(first.id)],
                [
                    {
                        "id": str(other.id),
                        "expected_execution_fingerprint": old_fingerprint,
                    }
                ],
            ),
        )
    assert stale.value.code == "stale_execution"
    await db_session.refresh(other)
    assert other.status == "canonical"


@pytest.mark.asyncio
async def test_membership_readd_after_remove_creates_new_canonical_row(
    db_session: AsyncSession,
) -> None:
    novel_id, group, first, _second = await _seed_affiliation(db_session)
    service = _service()

    added = await service.membership_batch(
        db_session,
        novel_id,
        _add_request(novel_id, str(group.id), [str(first.id)]),
    )
    original_id = added.affected_relation_ids[0]
    with pytest.raises(ConflictError) as stale_exc:
        await service.membership_batch(
            db_session,
            novel_id,
            _remove_request(
                novel_id,
                str(group.id),
                [str(first.id)],
                [
                    {
                        "id": original_id,
                        "expected_execution_fingerprint": "f" * 64,
                    }
                ],
            ),
        )
    assert stale_exc.value.code == "stale_execution"

    # 读取真实指纹后再移出，保证成功路径成立。
    rel = await db_session.get(EntityRelation, uuid.UUID(original_id))
    assert rel is not None
    real_removed = await service.membership_batch(
        db_session,
        novel_id,
        _remove_request(
            novel_id,
            str(group.id),
            [str(first.id)],
            [
                {
                    "id": original_id,
                    "expected_execution_fingerprint": (
                        entity_relation_execution_fingerprint(rel)
                    ),
                }
            ],
        ),
    )
    assert real_removed.removed_count == 1

    readded = await service.membership_batch(
        db_session,
        novel_id,
        _add_request(novel_id, str(group.id), [str(first.id)]),
    )
    assert readded.added_count == 1
    new_id = readded.affected_relation_ids[0]
    assert new_id != original_id
    assert await _relation_count(db_session, novel_id) == 2
    await db_session.refresh(rel)
    assert rel.status == "deprecated"
    fresh = await db_session.get(EntityRelation, uuid.UUID(new_id))
    assert fresh is not None
    assert fresh.status == "canonical"


# ============================================================
# 边界与门禁
# ============================================================


@pytest.mark.asyncio
async def test_membership_rejects_invalid_endpoints_and_cross_novel_refs(
    db_session: AsyncSession,
) -> None:
    novel_id, group, first, _second = await _seed_affiliation(db_session)
    wrong_group_type = await _seed_entity(db_session, novel_id, "character", "不是势力")
    wrong_member_type = await _seed_entity(db_session, novel_id, "item", "通行符")
    archived = await _seed_entity(
        db_session, novel_id, "character", "已归档角色", status="merged"
    )
    service = _service()

    with pytest.raises(NotFoundError):
        await service.membership_batch(
            db_session,
            novel_id,
            _add_request(novel_id, str(wrong_group_type.id), [str(first.id)]),
        )
    with pytest.raises(NotFoundError):
        await service.membership_batch(
            db_session,
            novel_id,
            _add_request(novel_id, str(group.id), [str(wrong_member_type.id)]),
        )
    with pytest.raises(NotFoundError):
        await service.membership_batch(
            db_session,
            novel_id,
            _add_request(novel_id, str(group.id), [str(archived.id)]),
        )
    with pytest.raises(ValidationError, match="cannot include the group entity"):
        await service.membership_batch(
            db_session,
            novel_id,
            _add_request(novel_id, str(group.id), [str(group.id)]),
        )

    # 跨 novel 的关系 id 不属于本批清单。
    other_novel = await _seed_novel(db_session)
    other_group = await _seed_entity(db_session, other_novel, "organization", "外域势力")
    other_member = await _seed_entity(db_session, other_novel, "character", "外来者")
    foreign = await _seed_relation(
        db_session,
        other_novel,
        source_id=str(other_member.id),
        target_id=str(other_group.id),
        relation_type="member_of",
        relation_kind="social",
    )
    with pytest.raises(NotFoundError, match="关系不存在或不属于该分组成员"):
        await service.membership_batch(
            db_session,
            novel_id,
            _remove_request(
                novel_id,
                str(group.id),
                [str(first.id)],
                [
                    {
                        "id": str(foreign.id),
                        "expected_execution_fingerprint": (
                            entity_relation_execution_fingerprint(foreign)
                        ),
                    }
                ],
            ),
        )

    # 移出清单引用了不属于所选成员的关系。
    bystander = await _seed_entity(db_session, novel_id, "character", "旁观者")
    bystander_rel = await _seed_relation(
        db_session,
        novel_id,
        source_id=str(bystander.id),
        target_id=str(group.id),
        relation_type="member_of",
        relation_kind="social",
    )
    with pytest.raises(NotFoundError, match="关系不存在或不属于该分组成员"):
        await service.membership_batch(
            db_session,
            novel_id,
            _remove_request(
                novel_id,
                str(group.id),
                [str(first.id)],
                [
                    {
                        "id": str(bystander_rel.id),
                        "expected_execution_fingerprint": (
                            entity_relation_execution_fingerprint(bystander_rel)
                        ),
                    }
                ],
            ),
        )


@pytest.mark.asyncio
async def test_membership_add_rejects_non_canonical_endpoints(
    db_session: AsyncSession,
) -> None:
    """分组读模型只归类 canonical 对象，写入端两端必须同为 canonical。

    回归：candidate/draft 端点此前可通过 membership 写入 canonical 关系，
    但随后从分组读模型中消失（组内成员数为 0），读写下口径必须一致。
    """
    novel_id, group, first, _second = await _seed_affiliation(db_session)
    candidate_member = await _seed_entity(
        db_session, novel_id, "character", "待完善成员", status="candidate"
    )
    draft_group = await _seed_entity(
        db_session, novel_id, "faction", "工作稿势力", status="draft"
    )
    service = _service()

    with pytest.raises(NotFoundError):
        await service.membership_batch(
            db_session,
            novel_id,
            _add_request(novel_id, str(group.id), [str(candidate_member.id)]),
        )
    with pytest.raises(NotFoundError):
        await service.membership_batch(
            db_session,
            novel_id,
            _add_request(novel_id, str(draft_group.id), [str(first.id)]),
        )

    assert await _relation_count(db_session, novel_id) == 0


@pytest.mark.asyncio
async def test_membership_blocked_by_validation_policy(
    db_session: AsyncSession,
) -> None:
    novel_id, group, first, _second = await _seed_affiliation(db_session)
    await WorldValidationService().activate_builtin_policy(db_session, novel_id)
    service = _service()

    with pytest.raises(ConflictError) as blocked:
        await service.membership_batch(
            db_session,
            novel_id,
            _add_request(novel_id, str(group.id), [str(first.id)]),
        )
    assert blocked.value.code == "required_validation"
    assert await _relation_count(db_session, novel_id) == 0


@pytest.mark.asyncio
async def test_membership_add_database_failure_rolls_back_whole_batch(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id, group, first, second = await _seed_affiliation(db_session)
    service = _service()
    original_flush = db_session.flush
    fail_flush = False

    async def guarded_flush(*args: object, **kwargs: object) -> None:
        if fail_flush:
            raise SQLAlchemyError("database unavailable")
        await original_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", guarded_flush)

    fail_flush = True
    with pytest.raises(SQLAlchemyError, match="database unavailable"):
        async with db_session.begin_nested():
            await service.membership_batch(
                db_session,
                novel_id,
                _add_request(novel_id, str(group.id), [str(first.id), str(second.id)]),
            )
    fail_flush = False

    # 整批撤回：失败事务不留下任何关系行。
    assert await _relation_count(db_session, novel_id) == 0


@pytest.mark.asyncio
async def test_membership_triggers_synopsis_and_context_invalidation(
    db_session: AsyncSession,
) -> None:
    novel_id, group, first, second = await _seed_affiliation(db_session)
    service = _service()

    added = await service.membership_batch(
        db_session,
        novel_id,
        _add_request(novel_id, str(group.id), [str(first.id), str(second.id)]),
    )
    synopsis_mock = service._mark_synopsis_changed
    assert {
        tuple(call.args) for call in synopsis_mock.call_args_list
    } == {
        (db_session, novel_id, relation_id)
        for relation_id in added.affected_relation_ids
    }
    marker = service._context_marker
    assert marker is not None
    assert {call.kwargs["asset_id"] for call in marker.call_args_list} == {
        str(group.id),
        str(first.id),
        str(second.id),
    }
    assert all(
        call.kwargs["reason"] == "relation_membership_batch"
        for call in marker.call_args_list
    )

    rel = await db_session.get(
        EntityRelation, uuid.UUID(added.affected_relation_ids[0])
    )
    assert rel is not None
    synopsis_mock.reset_mock()
    marker.reset_mock()
    removed = await service.membership_batch(
        db_session,
        novel_id,
        _remove_request(
            novel_id,
            str(group.id),
            [str(first.id)],
            [
                {
                    "id": str(rel.id),
                    "expected_execution_fingerprint": (
                        entity_relation_execution_fingerprint(rel)
                    ),
                }
            ],
        ),
    )
    assert removed.removed_count == 1
    assert [call.args[2] for call in synopsis_mock.call_args_list] == [str(rel.id)]
    assert {call.kwargs["asset_id"] for call in marker.call_args_list} == {
        str(group.id),
        str(first.id),
    }


# ============================================================
# review_edit 指纹 CAS
# ============================================================


@pytest.mark.asyncio
async def test_review_edit_execution_fingerprint_cas_and_legacy_compatibility(
    db_session: AsyncSession,
) -> None:
    novel_id, group, first, _second = await _seed_affiliation(db_session)
    rel = await _seed_relation(
        db_session,
        novel_id,
        source_id=str(first.id),
        target_id=str(group.id),
        relation_type="member_of",
        relation_kind="social",
    )
    service = _service()

    def _edit(
        fingerprint: str | None, description: str
    ) -> EntityRelationReviewEditRequest:
        payload: dict[str, object] = {"description": description}
        if fingerprint is not None:
            payload["expected_execution_fingerprint"] = fingerprint
        return EntityRelationReviewEditRequest.model_validate(payload)

    current = entity_relation_execution_fingerprint(rel)
    with pytest.raises(ConflictError) as stale:
        await service.review_edit(
            db_session,
            novel_id,
            str(rel.id),
            _edit("0" * 64, "陈旧指纹的编辑"),
        )
    assert stale.value.code == "stale_execution"

    updated = await service.review_edit(
        db_session,
        novel_id,
        str(rel.id),
        _edit(current, "指纹匹配的编辑"),
    )
    assert updated["relation"]["description"] == "指纹匹配的编辑"
    await db_session.refresh(rel)
    assert rel.description == "指纹匹配的编辑"

    fresh = entity_relation_execution_fingerprint(rel)
    legacy = await service.review_edit(
        db_session,
        novel_id,
        str(rel.id),
        _edit(None, "不携带指纹的兼容编辑"),
    )
    assert legacy["relation"]["description"] == "不携带指纹的兼容编辑"
    assert fresh != current


@pytest.mark.asyncio
async def test_membership_add_event_view_open_string_relations(
    db_session: AsyncSession,
) -> None:
    """event 视角的 participates_in/参与 无通用 kind 映射：缺省与显式选择都
    须回退视角注册的 state 分类落地，而不是被 canonical 校验拒绝（422）。"""
    from modules.world.tests.test_world_relation_grouping_read import (
        _entity as _grouping_entity,
    )
    from modules.world.tests.test_world_relation_grouping_read import (
        _prepare as _grouping_prepare,
    )

    novel_id = await _grouping_prepare(db_session)
    event = await _grouping_entity(db_session, novel_id, "event", "风暴之夜")
    witness = await _grouping_entity(db_session, novel_id, "character", "目击者")
    other = await _grouping_entity(db_session, novel_id, "character", "旁观者")

    default_added = await _service().membership_batch(
        db_session,
        novel_id,
        _add_request(
            novel_id,
            str(event.id),
            [str(witness.id)],
            group_view="event",
        ),
    )
    assert default_added.added_count == 1
    default_rel = await db_session.get(
        EntityRelation, uuid.UUID(default_added.affected_relation_ids[0])
    )
    assert default_rel.relation_type == "participates_in"
    assert default_rel.relation_kind == "state"

    # 显式选择开放字符串规则“参与”（无通用 kind 映射）同样回退 state。
    explicit = await _service().membership_batch(
        db_session,
        novel_id,
        _add_request(
            novel_id,
            str(event.id),
            [str(other.id)],
            group_view="event",
            relation_type="参与",
            group_side="target",
        ),
    )
    assert explicit.added_count == 1
    explicit_rel = await db_session.get(
        EntityRelation, uuid.UUID(explicit.affected_relation_ids[0])
    )
    assert explicit_rel.relation_type == "参与"
    assert explicit_rel.relation_kind == "state"
