from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from modules.world.repositories import CoreEntityRepository, EntityRelationRepository
from modules.world.schemas import (
    EntityAliasReviewBatchRequest,
    EntityRelationCreate,
    EntityRelationReviewBatchRequest,
)
from modules.world.services.core.entity_alias_service import EntityAliasService
from modules.world.services.core.entity_relation_service import EntityRelationService
from modules.world.services.core.review_queue import review_type_catalog
from modules.world.tests.helpers import _create_project


def test_review_type_catalog_keeps_custom_values_open() -> None:
    catalog = review_type_catalog()

    assert catalog["custom_allowed"] is True
    assert {item["value"] for item in catalog["alias_types"]} == {
        "name",
        "title",
        "nickname",
        "alias",
        "translation",
        "abbreviation",
    }
    sibling = next(
        item for item in catalog["relation_types"] if item["value"] == "sibling_of"
    )
    assert "兄妹" in sibling["synonyms"]


def test_review_batch_schemas_reject_unconfirmed_duplicate_and_blank_values() -> None:
    relation_id = str(uuid.uuid4())
    base_relation = {
        "client_decision_id": "one",
        "action": "accept",
        "group_id": "group-one",
        "member_relation_ids": [relation_id],
        "primary_relation_id": relation_id,
        "expected_execution_fingerprint": "f" * 64,
        "source_id": str(uuid.uuid4()),
        "target_id": str(uuid.uuid4()),
        "relation_type": "friend_of",
    }
    with pytest.raises(ValueError, match="confirmed=true"):
        EntityRelationReviewBatchRequest.model_validate(
            {"confirmed": False, "decisions": [base_relation]}
        )
    with pytest.raises(ValueError, match="only appear in one"):
        EntityRelationReviewBatchRequest.model_validate(
            {
                "confirmed": True,
                "decisions": [
                    base_relation,
                    {**base_relation, "client_decision_id": "two"},
                ],
            }
        )
    with pytest.raises(ValueError, match="cannot be blank"):
        EntityRelationReviewBatchRequest.model_validate(
            {
                "confirmed": True,
                "decisions": [{**base_relation, "relation_type": "   "}],
            }
        )
    with pytest.raises(ValueError, match="cannot be blank"):
        EntityAliasReviewBatchRequest.model_validate(
            {
                "confirmed": True,
                "decisions": [
                    {
                        "client_decision_id": "alias-one",
                        "action": "accept",
                        "entity_id": str(uuid.uuid4()),
                        "original_alias": "别名",
                        "expected_execution_fingerprint": "a" * 64,
                        "alias_type": "   ",
                    }
                ],
            }
        )


@pytest.mark.asyncio
async def test_review_queue_api_routes_and_confirmation_gate(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)

    catalog = await async_client.get("/api/world/review-type-catalog")
    relation_groups = await async_client.get(
        "/api/world/relations/review-groups",
        params={"novel_id": novel_id, "limit": 20},
    )
    alias_groups = await async_client.get(
        "/api/world/aliases/review-groups",
        params={"novel_id": novel_id, "limit": 20},
    )
    relation_unconfirmed = await async_client.post(
        "/api/world/relations/review-batch",
        params={"novel_id": novel_id},
        json={"confirmed": False, "decisions": []},
    )
    alias_unconfirmed = await async_client.post(
        "/api/world/aliases/review-batch",
        params={"novel_id": novel_id},
        json={"confirmed": False, "decisions": []},
    )

    assert catalog.status_code == 200
    assert catalog.json()["custom_allowed"] is True
    assert relation_groups.status_code == 200
    assert relation_groups.json() == {
        "groups": [],
        "group_total": 0,
        "item_total": 0,
        "skip": 0,
        "limit": 20,
    }
    assert alias_groups.status_code == 200
    assert alias_groups.json()["group_total"] == 0
    assert relation_unconfirmed.status_code == 422
    assert alias_unconfirmed.status_code == 422


@pytest.mark.asyncio
async def test_alias_mutation_lock_is_scoped_to_requested_novel(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    other_novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    await _create_project(db_session, other_novel_id)
    repo = CoreEntityRepository()
    foreign_entity = await repo.create_raw(
        db_session,
        novel_id=uuid.UUID(hex=other_novel_id),
        entity_type="character",
        name="其他项目对象",
        content_json={"aliases": []},
    )

    assert (
        await repo.get_for_update(
            db_session,
            foreign_entity.id,
            novel_id=uuid.UUID(hex=novel_id),
        )
        is None
    )
    with pytest.raises(NotFoundError):
        await EntityAliasService().create_alias(
            db_session,
            novel_id,
            str(foreign_entity.id),
            "不应写入",
        )
    await db_session.refresh(foreign_entity)
    assert foreign_entity.content_json["aliases"] == []


@pytest.mark.asyncio
async def test_relation_review_group_merges_selected_evidence_and_archives_members(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    nid = uuid.UUID(hex=novel_id)
    entities = CoreEntityRepository()
    relations = EntityRelationRepository()
    source = await entities.create_raw(
        db_session,
        novel_id=nid,
        entity_type="character",
        name="克莱恩",
    )
    target = await entities.create_raw(
        db_session,
        novel_id=nid,
        entity_type="character",
        name="梅丽莎",
    )
    cause = await entities.create_raw(
        db_session,
        novel_id=nid,
        entity_type="event",
        name="兄妹生活事件",
    )
    first = await relations.create(
        db_session,
        nid,
        EntityRelationCreate(
            source_id=str(source.id),
            target_id=str(target.id),
            relation_type="sibling",
            quote="哥哥照顾妹妹。",
            status="candidate",
            review_meta={
                "scene_index": 1,
                "evidence_refs": [{"scene_index": 1, "quote": "哥哥照顾妹妹。"}],
            },
        ),
    )
    second = await relations.create(
        db_session,
        nid,
        EntityRelationCreate(
            source_id=str(source.id),
            target_id=str(target.id),
            relation_type="兄妹",
            quote="梅丽莎称他为哥哥。",
            caused_by_event_id=str(cause.id),
            status="candidate",
            review_meta={
                "scene_index": 2,
                "evidence_refs": [
                    {"scene_index": 2, "quote": "梅丽莎称他为哥哥。"}
                ],
            },
        ),
    )
    unselected = await relations.create(
        db_session,
        nid,
        EntityRelationCreate(
            source_id=str(source.id),
            target_id=str(target.id),
            relation_type="enemy_of",
            quote="这是另一种不同语义。",
            status="candidate",
        ),
    )
    context_marker = AsyncMock(return_value=0)
    service = EntityRelationService(context_marker=context_marker)
    service._mark_synopsis_changed = AsyncMock()

    page = await service.list_review_groups(db_session, novel_id)

    assert page.group_total == 1
    assert page.item_total == 3
    group = page.groups[0]
    assert group.source_name == "克莱恩"
    assert group.target_name == "梅丽莎"
    assert {
        item.suggested_relation_type
        for item in group.members
        if item.id in {str(first.id), str(second.id)}
    } == {"sibling_of"}

    result = await service.review_batch(
        db_session,
        novel_id,
        EntityRelationReviewBatchRequest.model_validate(
            {
                "confirmed": True,
                "decisions": [
                    {
                        "client_decision_id": "merge-siblings",
                        "action": "merge",
                        "group_id": group.group_id,
                        "member_relation_ids": [str(first.id), str(second.id)],
                        "primary_relation_id": str(first.id),
                        "expected_execution_fingerprint": group.execution_fingerprint,
                        "source_id": str(source.id),
                        "target_id": str(target.id),
                        "relation_type": "sibling_of",
                        "description": "兄妹",
                        "strength": 0.9,
                    }
                ],
            }
        ),
    )

    assert result.succeeded_count == 1
    await db_session.refresh(first)
    await db_session.refresh(second)
    await db_session.refresh(unselected)
    assert first.status == "canonical"
    assert first.relation_type == "sibling_of"
    assert first.quote == "哥哥照顾妹妹。\n梅丽莎称他为哥哥。"
    assert len(first.review_meta["evidence_refs"]) == 2
    assert second.status == "deprecated"
    assert second.review_meta["merged_into_relation_id"] == str(first.id)
    assert unselected.status == "candidate"
    merged_sources = first.review_meta["review_history"][-1]["merged_sources"]
    assert len(merged_sources) == 2
    assert merged_sources[0]["relation"]["quote"] == "哥哥照顾妹妹。"
    assert merged_sources[0]["relation"]["relation_type"] == "sibling"
    second_source = next(
        item["relation"]
        for item in merged_sources
        if item["relation"]["id"] == str(second.id)
    )
    assert second_source["caused_by_event_id"] == str(cause.id)
    assert second_source["review_meta"]["scene_index"] == 2
    assert context_marker.await_count == 2


@pytest.mark.asyncio
async def test_relation_review_filter_returns_complete_group_and_can_submit(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    nid = uuid.UUID(hex=novel_id)
    entities = CoreEntityRepository()
    relations = EntityRelationRepository()
    source = await entities.create_raw(
        db_session, novel_id=nid, entity_type="character", name="甲"
    )
    target = await entities.create_raw(
        db_session, novel_id=nid, entity_type="character", name="乙"
    )
    first = await relations.create(
        db_session,
        nid,
        EntityRelationCreate(
            source_id=str(source.id),
            target_id=str(target.id),
            relation_type="friend",
            status="candidate",
            review_meta={"scene_index": 1},
        ),
    )
    second = await relations.create(
        db_session,
        nid,
        EntityRelationCreate(
            source_id=str(source.id),
            target_id=str(target.id),
            relation_type="enemy_of",
            status="candidate",
            review_meta={"scene_index": 2},
        ),
    )
    service = EntityRelationService(context_marker=AsyncMock(return_value=0))
    service._mark_synopsis_changed = AsyncMock()

    page = await service.list_review_groups(db_session, novel_id, scene_index=1)

    assert page.group_total == 1
    assert page.item_total == 2
    group = page.groups[0]
    assert {item.id for item in group.members} == {str(first.id), str(second.id)}

    result = await service.review_batch(
        db_session,
        novel_id,
        EntityRelationReviewBatchRequest.model_validate(
            {
                "confirmed": True,
                "decisions": [
                    {
                        "client_decision_id": "filtered-accept",
                        "action": "accept",
                        "group_id": group.group_id,
                        "member_relation_ids": [str(first.id)],
                        "primary_relation_id": str(first.id),
                        "expected_execution_fingerprint": group.execution_fingerprint,
                        "source_id": str(source.id),
                        "target_id": str(target.id),
                        "relation_type": "friend_of",
                    }
                ],
            }
        ),
    )

    assert result.succeeded_count == 1
    await db_session.refresh(first)
    await db_session.refresh(second)
    assert first.status == "canonical"
    assert second.status == "candidate"


@pytest.mark.asyncio
async def test_relation_review_group_reports_reverse_relations(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    nid = uuid.UUID(hex=novel_id)
    entities = CoreEntityRepository()
    relations = EntityRelationRepository()
    source = await entities.create_raw(
        db_session, novel_id=nid, entity_type="character", name="甲"
    )
    target = await entities.create_raw(
        db_session, novel_id=nid, entity_type="character", name="乙"
    )
    await relations.create(
        db_session,
        nid,
        EntityRelationCreate(
            source_id=str(source.id),
            target_id=str(target.id),
            relation_type="supports",
            status="candidate",
        ),
    )
    await relations.create(
        db_session,
        nid,
        EntityRelationCreate(
            source_id=str(target.id),
            target_id=str(source.id),
            relation_type="opposes",
            status="candidate",
        ),
    )
    await relations.create(
        db_session,
        nid,
        EntityRelationCreate(
            source_id=str(target.id),
            target_id=str(source.id),
            relation_type="related_to",
            status="canonical",
        ),
    )

    page = await EntityRelationService().list_review_groups(db_session, novel_id)
    group = next(item for item in page.groups if item.source_id == str(source.id))

    assert group.reverse_candidate_count == 1
    assert group.reverse_type_variants == ["opposes"]
    assert [item.relation_type for item in group.reverse_canonical_relations] == [
        "related_to"
    ]


@pytest.mark.parametrize("retired_status", ["accepted", "rejected", "rolled_back"])
@pytest.mark.asyncio
async def test_relation_review_rejects_every_historical_endpoint_status(
    db_session: AsyncSession,
    retired_status: str,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    nid = uuid.UUID(hex=novel_id)
    entities = CoreEntityRepository()
    relations = EntityRelationRepository()
    source = await entities.create_raw(
        db_session, novel_id=nid, entity_type="character", name="甲"
    )
    active_target = await entities.create_raw(
        db_session, novel_id=nid, entity_type="character", name="乙"
    )
    retired_target = await entities.create_raw(
        db_session,
        novel_id=nid,
        entity_type="character",
        name="历史对象",
        status=retired_status,
    )
    candidate = await relations.create(
        db_session,
        nid,
        EntityRelationCreate(
            source_id=str(source.id),
            target_id=str(active_target.id),
            relation_type="friend",
            status="candidate",
        ),
    )
    service = EntityRelationService()
    group = (await service.list_review_groups(db_session, novel_id)).groups[0]

    result = await service.review_batch(
        db_session,
        novel_id,
        EntityRelationReviewBatchRequest.model_validate(
            {
                "confirmed": True,
                "decisions": [
                    {
                        "client_decision_id": f"retired-{retired_status}",
                        "action": "accept",
                        "group_id": group.group_id,
                        "member_relation_ids": [str(candidate.id)],
                        "primary_relation_id": str(candidate.id),
                        "expected_execution_fingerprint": group.execution_fingerprint,
                        "source_id": str(source.id),
                        "target_id": str(retired_target.id),
                        "relation_type": "friend_of",
                    }
                ],
            }
        ),
    )

    assert result.failed_count == 1
    await db_session.refresh(candidate)
    assert candidate.status == "candidate"


@pytest.mark.asyncio
async def test_relation_group_over_fifty_can_process_selected_subset(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    nid = uuid.UUID(hex=novel_id)
    entities = CoreEntityRepository()
    relations = EntityRelationRepository()
    source = await entities.create_raw(
        db_session, novel_id=nid, entity_type="character", name="甲"
    )
    target = await entities.create_raw(
        db_session, novel_id=nid, entity_type="character", name="乙"
    )
    candidates = []
    for index in range(51):
        candidates.append(
            await relations.create(
                db_session,
                nid,
                EntityRelationCreate(
                    source_id=str(source.id),
                    target_id=str(target.id),
                    relation_type=f"custom_{index}",
                    status="candidate",
                ),
            )
        )
    service = EntityRelationService(context_marker=AsyncMock(return_value=0))
    service._mark_synopsis_changed = AsyncMock()
    group = (await service.list_review_groups(db_session, novel_id)).groups[0]

    assert group.member_count == 51
    result = await service.review_batch(
        db_session,
        novel_id,
        EntityRelationReviewBatchRequest.model_validate(
            {
                "confirmed": True,
                "decisions": [
                    {
                        "client_decision_id": "large-group-one",
                        "action": "accept",
                        "group_id": group.group_id,
                        "member_relation_ids": [str(candidates[0].id)],
                        "primary_relation_id": str(candidates[0].id),
                        "expected_execution_fingerprint": group.execution_fingerprint,
                        "source_id": str(source.id),
                        "target_id": str(target.id),
                        "relation_type": "custom_0",
                    }
                ],
            }
        ),
    )

    assert result.succeeded_count == 1
    await db_session.refresh(candidates[0])
    await db_session.refresh(candidates[-1])
    assert candidates[0].status == "canonical"
    assert candidates[-1].status == "candidate"


@pytest.mark.asyncio
async def test_relation_review_batch_rejects_stale_group(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    nid = uuid.UUID(hex=novel_id)
    entities = CoreEntityRepository()
    relations = EntityRelationRepository()
    source = await entities.create_raw(
        db_session, novel_id=nid, entity_type="character", name="甲"
    )
    target = await entities.create_raw(
        db_session, novel_id=nid, entity_type="character", name="乙"
    )
    relation = await relations.create(
        db_session,
        nid,
        EntityRelationCreate(
            source_id=str(source.id),
            target_id=str(target.id),
            relation_type="friend",
            status="candidate",
        ),
    )
    service = EntityRelationService()
    page = await service.list_review_groups(db_session, novel_id)
    group = page.groups[0]
    relation.description = "并发更新"
    await db_session.flush()

    result = await service.review_batch(
        db_session,
        novel_id,
        EntityRelationReviewBatchRequest.model_validate(
            {
                "confirmed": True,
                "decisions": [
                    {
                        "client_decision_id": "stale",
                        "action": "accept",
                        "group_id": group.group_id,
                        "member_relation_ids": [str(relation.id)],
                        "primary_relation_id": str(relation.id),
                        "expected_execution_fingerprint": group.execution_fingerprint,
                        "source_id": str(source.id),
                        "target_id": str(target.id),
                        "relation_type": "friend_of",
                    }
                ],
            }
        ),
    )

    assert result.stale_count == 1
    await db_session.refresh(relation)
    assert relation.status == "candidate"


@pytest.mark.asyncio
async def test_relation_review_reuses_existing_canonical_relation(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    nid = uuid.UUID(hex=novel_id)
    entities = CoreEntityRepository()
    relations = EntityRelationRepository()
    source = await entities.create_raw(
        db_session, novel_id=nid, entity_type="character", name="甲"
    )
    target = await entities.create_raw(
        db_session, novel_id=nid, entity_type="character", name="乙"
    )
    canonical = await relations.create(
        db_session,
        nid,
        EntityRelationCreate(
            source_id=str(source.id),
            target_id=str(target.id),
            relation_type="friend_of",
            quote="旧证据",
            status="canonical",
        ),
    )
    candidate = await relations.create(
        db_session,
        nid,
        EntityRelationCreate(
            source_id=str(source.id),
            target_id=str(target.id),
            relation_type="friend",
            quote="新证据",
            status="candidate",
        ),
    )
    service = EntityRelationService(context_marker=AsyncMock(return_value=0))
    service._mark_synopsis_changed = AsyncMock()
    group = (await service.list_review_groups(db_session, novel_id)).groups[0]

    result = await service.review_batch(
        db_session,
        novel_id,
        EntityRelationReviewBatchRequest.model_validate(
            {
                "confirmed": True,
                "decisions": [
                    {
                        "client_decision_id": "reuse-canonical",
                        "action": "accept",
                        "group_id": group.group_id,
                        "member_relation_ids": [str(candidate.id)],
                        "primary_relation_id": str(candidate.id),
                        "expected_execution_fingerprint": group.execution_fingerprint,
                        "source_id": str(source.id),
                        "target_id": str(target.id),
                        "relation_type": "friend_of",
                        "description": "朋友",
                        "strength": 0.7,
                    }
                ],
            }
        ),
    )

    assert result.succeeded_count == 1
    assert result.results[0].canonical_relation_id == str(canonical.id)
    await db_session.refresh(canonical)
    await db_session.refresh(candidate)
    assert canonical.quote == "旧证据\n新证据"
    assert candidate.status == "deprecated"
    canonical_rows = await relations.list_by_novel(
        db_session,
        nid,
        status="canonical",
        relation_type="friend_of",
    )
    assert [row.id for row in canonical_rows] == [canonical.id]


@pytest.mark.asyncio
async def test_alias_review_preserves_custom_type_and_ignore_keeps_history(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    nid = uuid.UUID(hex=novel_id)
    entity = await CoreEntityRepository().create_raw(
        db_session,
        novel_id=nid,
        entity_type="location",
        name="源堡",
        content_json={
            "aliases": [
                {
                    "alias": "灰雾世界",
                    "type": "别称",
                    "status": "candidate",
                    "source": "deep_import",
                    "confidence": 0.95,
                    "needs_review": True,
                },
                {
                    "alias": "旧称",
                    "type": "alias",
                    "status": "candidate",
                    "source": "deep_import",
                    "needs_review": True,
                },
            ]
        },
    )
    service = EntityAliasService(context_marker=AsyncMock(return_value=0))
    page = await service.list_review_groups(db_session, novel_id)
    assert page.group_total == 1
    custom = next(item for item in page.groups[0].members if item.alias == "灰雾世界")
    ignored = next(item for item in page.groups[0].members if item.alias == "旧称")
    assert custom.alias_type == "别称"
    assert custom.suggested_alias_type == "alias"
    assert custom.type_kind == "custom"

    result = await service.review_batch(
        db_session,
        novel_id,
        EntityAliasReviewBatchRequest.model_validate(
            {
                "confirmed": True,
                "decisions": [
                    {
                        "client_decision_id": "keep-custom",
                        "action": "accept",
                        "entity_id": str(entity.id),
                        "original_alias": custom.alias,
                        "expected_execution_fingerprint": custom.execution_fingerprint,
                    },
                    {
                        "client_decision_id": "ignore-old",
                        "action": "ignore",
                        "entity_id": str(entity.id),
                        "original_alias": ignored.alias,
                        "expected_execution_fingerprint": ignored.execution_fingerprint,
                    },
                ],
            }
        ),
    )

    assert result.succeeded_count == 2
    await db_session.refresh(entity)
    aliases = entity.content_json["aliases"]
    kept = next(item for item in aliases if item["alias"] == "灰雾世界")
    historical = next(item for item in aliases if item["alias"] == "旧称")
    assert kept["type"] == "别称"
    assert kept["status"] == "canonical"
    assert historical["status"] == "ignored"
    assert historical["needs_review"] is False
    assert historical["review_history"][0]["review_action"] == "alias_review_ignored"


@pytest.mark.asyncio
async def test_alias_review_group_marks_suggestion_owned_shadow(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    suggestion_id = str(uuid.uuid4())
    await CoreEntityRepository().create_raw(
        db_session,
        novel_id=uuid.UUID(hex=novel_id),
        entity_type="character",
        name="建议影子",
        status="candidate",
        content_json={
            "_meta": {
                "compatibility_shadow": True,
                "suggestion_id": suggestion_id,
            },
            "aliases": [
                {
                    "alias": "影子别名",
                    "type": "alias",
                    "status": "candidate",
                    "needs_review": True,
                }
            ],
        },
    )

    page = await EntityAliasService().list_review_groups(db_session, novel_id)

    assert page.group_total == 1
    item = page.groups[0].members[0]
    assert item.managed_by_suggestion is True
    assert item.suggestion_id == suggestion_id


@pytest.mark.asyncio
async def test_alias_review_batch_keeps_other_items_when_one_decision_conflicts(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    nid = uuid.UUID(hex=novel_id)
    repo = CoreEntityRepository()
    source = await repo.create_raw(
        db_session,
        novel_id=nid,
        entity_type="character",
        name="源对象",
        content_json={
            "aliases": [
                {
                    "alias": "可采用",
                    "type": "alias",
                    "status": "candidate",
                    "needs_review": True,
                },
                {
                    "alias": "待冲突",
                    "type": "alias",
                    "status": "candidate",
                    "needs_review": True,
                },
            ]
        },
    )
    target = await repo.create_raw(
        db_session,
        novel_id=nid,
        entity_type="character",
        name="目标对象",
        content_json={
            "aliases": [
                {"alias": "重复别名", "type": "alias", "status": "canonical"}
            ]
        },
    )
    service = EntityAliasService(context_marker=AsyncMock(return_value=0))
    group = (await service.list_review_groups(db_session, novel_id)).groups[0]
    by_alias = {item.alias: item for item in group.members}

    result = await service.review_batch(
        db_session,
        novel_id,
        EntityAliasReviewBatchRequest.model_validate(
            {
                "confirmed": True,
                "decisions": [
                    {
                        "client_decision_id": "accept-one",
                        "action": "accept",
                        "entity_id": str(source.id),
                        "original_alias": "可采用",
                        "expected_execution_fingerprint": by_alias[
                            "可采用"
                        ].execution_fingerprint,
                    },
                    {
                        "client_decision_id": "conflict-one",
                        "action": "accept",
                        "entity_id": str(source.id),
                        "original_alias": "待冲突",
                        "expected_execution_fingerprint": by_alias[
                            "待冲突"
                        ].execution_fingerprint,
                        "target_entity_id": str(target.id),
                        "alias": "重复别名",
                        "alias_type": "alias",
                    },
                ],
            }
        ),
    )

    assert result.succeeded_count == 1
    assert result.failed_count == 1
    await db_session.refresh(source)
    aliases = {item["alias"]: item for item in source.content_json["aliases"]}
    assert aliases["可采用"]["status"] == "canonical"
    assert aliases["待冲突"]["status"] == "candidate"
