from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from modules.world.repositories import CoreEntityRepository, EntityRelationRepository
from modules.world.schemas import (
    EntityAliasReviewBatchRequest,
    EntityRelationCreate,
    EntityRelationReviewBatchRequest,
)
from modules.world.services.core.entity_alias_service import EntityAliasService
from modules.world.services.core.entity_relation_service import EntityRelationService
from modules.world.services.core.review_queue import (
    default_alias_kind,
    default_relation_kind,
    review_type_catalog,
)
from modules.world.tests.helpers import _create_project


def test_review_type_catalog_keeps_custom_values_open() -> None:
    catalog = review_type_catalog()

    assert catalog["version"] == 2
    assert catalog["custom_allowed"] is True
    assert {item["value"] for item in catalog["relation_kinds"]} == {
        "state",
        "social",
        "spatial",
        "causal",
        "temporal",
        "epistemic",
        "intentional",
    }
    assert {item["value"] for item in catalog["alias_kinds"]} == {
        "name",
        "title",
        "identity",
    }
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
    assert sibling["default_kind"] == "social"
    assert (
        next(item for item in catalog["alias_types"] if item["value"] == "title")[
            "default_kind"
        ]
        == "title"
    )


@pytest.mark.parametrize(
    ("detail_type", "expected"),
    [
        ("member_of", "social"),
        ("located_at", "spatial"),
        ("causes", "causal"),
        ("sequence_progression", "temporal"),
        ("knows_about", "epistemic"),
        ("seeks", "intentional"),
        ("related_to", "state"),
        ("未收录关系", None),
    ],
)
def test_relation_kind_defaults_are_deterministic(
    detail_type: str, expected: str | None
) -> None:
    assert default_relation_kind(detail_type) == expected


@pytest.mark.parametrize(
    ("detail_type", "expected"),
    [
        ("nickname", "name"),
        ("尊称", "title"),
        ("穿越前身份", "identity"),
        ("未收录别名类型", None),
    ],
)
def test_alias_kind_defaults_are_deterministic(
    detail_type: str, expected: str | None
) -> None:
    assert default_alias_kind(detail_type) == expected


def test_explicit_kind_wins_and_custom_canonical_requires_kind() -> None:
    assert (
        EntityRelationService._resolve_relation_kind("member_of", "causal", "canonical")
        == "causal"
    )
    assert (
        EntityAliasService._resolve_alias_kind("nickname", "identity", "canonical")
        == "identity"
    )
    assert (
        EntityRelationService._resolve_relation_kind("自定义", None, "candidate") is None
    )
    assert EntityAliasService._resolve_alias_kind("自定义", None, "candidate") is None
    with pytest.raises(ValidationError, match="relation_kind is required"):
        EntityRelationService._resolve_relation_kind("自定义", None, "canonical")
    with pytest.raises(ValidationError, match="alias_kind is required"):
        EntityAliasService._resolve_alias_kind("自定义", None, "canonical")


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
    with pytest.raises(ValueError):
        EntityRelationReviewBatchRequest.model_validate(
            {
                "confirmed": True,
                "decisions": [
                    {
                        "client_decision_id": "too-many",
                        "action": "ignore",
                        "group_id": "group-one",
                        "member_relation_ids": [str(uuid.uuid4()) for _ in range(51)],
                        "expected_execution_fingerprint": "f" * 64,
                    }
                ],
            }
        )

    second_relation_id = str(uuid.uuid4())
    separate_base = {
        "confirmed": True,
        "decisions": [
            {
                "client_decision_id": "separate",
                "action": "accept_separately",
                "group_id": "group-one",
                "member_relation_ids": [relation_id, second_relation_id],
                "expected_execution_fingerprint": "f" * 64,
                "separate_relations": [
                    {
                        "candidate_relation_id": relation_id,
                        "source_id": base_relation["source_id"],
                        "target_id": base_relation["target_id"],
                        "relation_type": "friend_of",
                    },
                    {
                        "candidate_relation_id": second_relation_id,
                        "source_id": base_relation["source_id"],
                        "target_id": base_relation["target_id"],
                        "relation_type": "enemy_of",
                    },
                ],
            }
        ],
    }
    parsed = EntityRelationReviewBatchRequest.model_validate(separate_base)
    assert parsed.decisions[0].unselected_action == "keep_pending"
    with pytest.raises(ValueError, match="final keys must be unique"):
        EntityRelationReviewBatchRequest.model_validate(
            {
                **separate_base,
                "decisions": [
                    {
                        **separate_base["decisions"][0],
                        "separate_relations": [
                            separate_base["decisions"][0]["separate_relations"][0],
                            {
                                **separate_base["decisions"][0]["separate_relations"][0],
                                "candidate_relation_id": second_relation_id,
                            },
                        ],
                    }
                ],
            }
        )


@pytest.mark.asyncio
async def test_relation_review_batch_propagates_database_failures(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relation_id = str(uuid.uuid4())
    service = EntityRelationService()

    async def fail_write(*_args, **_kwargs):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(service, "_apply_review_decision", fail_write)
    request = EntityRelationReviewBatchRequest.model_validate(
        {
            "confirmed": True,
            "decisions": [
                {
                    "client_decision_id": "db-failure",
                    "action": "accept",
                    "group_id": "group-db-failure",
                    "member_relation_ids": [relation_id],
                    "primary_relation_id": relation_id,
                    "expected_execution_fingerprint": "f" * 64,
                    "source_id": str(uuid.uuid4()),
                    "target_id": str(uuid.uuid4()),
                    "relation_type": "friend_of",
                }
            ],
        }
    )

    with pytest.raises(SQLAlchemyError, match="database unavailable"):
        await service.review_batch(db_session, uuid.uuid4().hex, request)


@pytest.mark.asyncio
async def test_alias_review_batch_propagates_database_failures(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = EntityAliasService()

    async def fail_write(*_args, **_kwargs):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(service, "_apply_review_decision", fail_write)
    request = EntityAliasReviewBatchRequest.model_validate(
        {
            "confirmed": True,
            "decisions": [
                {
                    "client_decision_id": "db-failure",
                    "action": "accept",
                    "entity_id": str(uuid.uuid4()),
                    "original_alias": "待处理别名",
                    "expected_execution_fingerprint": "a" * 64,
                    "alias_type": "alias",
                }
            ],
        }
    )

    with pytest.raises(SQLAlchemyError, match="database unavailable"):
        await service.review_batch(db_session, uuid.uuid4().hex, request)


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
async def test_entity_review_filters_alias_actions_scene_keys_and_novel(
    async_client: AsyncClient,
) -> None:
    project_ids = []
    for title in ("对象筛选主项目", "对象筛选其他项目"):
        response = await async_client.post(
            "/api/projects",
            json={"title": title, "language": "zh"},
        )
        assert response.status_code == 201
        project_ids.append(response.json()["id"])

    primary_id, other_id = project_ids
    primary_entities = (
        ("链接建议", "link_to_existing", {"source_scene_index": 8}),
        ("别名建议", "alias_of_existing", {"scene_index": 8}),
        ("新建建议", "create_new", {"scene_index": 9}),
    )
    for name, action, source_meta in primary_entities:
        response = await async_client.post(
            "/api/world/entities",
            params={"novel_id": primary_id},
            json={
                "entity_type": "location",
                "name": name,
                "status": "candidate",
                "force_create": True,
                "content_json": {"_meta": {"suggested_action": action, **source_meta}},
            },
        )
        assert response.status_code == 201, response.text
    foreign = await async_client.post(
        "/api/world/entities",
        params={"novel_id": other_id},
        json={
            "entity_type": "location",
            "name": "其他项目别名",
            "status": "candidate",
            "force_create": True,
            "content_json": {
                "_meta": {
                    "suggested_action": "link_to_existing",
                    "source_scene_index": 8,
                }
            },
        },
    )
    assert foreign.status_code == 201, foreign.text

    alias_filter = await async_client.get(
        "/api/world/entities",
        params={
            "novel_id": primary_id,
            "display_state": "review",
            "suggested_action": "alias",
            "limit": 50,
        },
    )
    legacy_filter = await async_client.get(
        "/api/world/entities",
        params={
            "novel_id": primary_id,
            "display_state": "review",
            "suggested_action": "link_to_existing",
        },
    )
    scene_filter = await async_client.get(
        "/api/world/entities",
        params={
            "novel_id": primary_id,
            "display_state": "review",
            "scene_index": 8,
            "limit": 50,
        },
    )

    assert alias_filter.status_code == 200
    assert alias_filter.json()["total"] == 2
    assert {item["name"] for item in alias_filter.json()["items"]} == {
        "链接建议",
        "别名建议",
    }
    assert [item["name"] for item in legacy_filter.json()["items"]] == ["链接建议"]
    assert scene_filter.json()["total"] == 2
    assert {item["name"] for item in scene_filter.json()["items"]} == {
        "链接建议",
        "别名建议",
    }


@pytest.mark.asyncio
async def test_alias_review_batch_wire_keeps_additive_relation_result_fields(
    async_client: AsyncClient,
) -> None:
    project = await async_client.post(
        "/api/projects",
        json={"title": "别名回执兼容", "language": "zh"},
    )
    assert project.status_code == 201
    novel_id = project.json()["id"]
    created = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={
            "entity_type": "character",
            "name": "源对象",
            "status": "canonical",
            "force_create": True,
            "content_json": {
                "aliases": [
                    {
                        "alias": "待采用别名",
                        "type": "alias",
                        "status": "candidate",
                        "needs_review": True,
                    }
                ]
            },
        },
    )
    assert created.status_code == 201, created.text
    entity_id = created.json()["id"]
    groups = await async_client.get(
        "/api/world/aliases/review-groups",
        params={"novel_id": novel_id},
    )
    assert groups.status_code == 200, groups.text
    member = groups.json()["groups"][0]["members"][0]

    response = await async_client.post(
        "/api/world/aliases/review-batch",
        params={"novel_id": novel_id},
        json={
            "confirmed": True,
            "decisions": [
                {
                    "client_decision_id": "accept-alias-wire",
                    "action": "accept",
                    "entity_id": entity_id,
                    "original_alias": member["alias"],
                    "expected_execution_fingerprint": member["execution_fingerprint"],
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["status"] == "success"
    assert result["canonical_relation_id"] is None
    assert result["canonical_relation_ids"] == []
    assert result["reused_canonical_relation_ids"] == []
    assert result["ignored_relation_ids"] == []
    assert result["remaining_candidate_ids"] == []


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
                "evidence_refs": [{"scene_index": 2, "quote": "梅丽莎称他为哥哥。"}],
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
    assert result.results[0].canonical_relation_ids == [str(first.id)]
    assert result.results[0].remaining_candidate_ids == [str(unselected.id)]
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
            relation_kind="state",
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


@pytest.mark.asyncio
async def test_relation_review_group_attention_filters_precede_pagination_and_count(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    other_novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    await _create_project(db_session, other_novel_id)
    entities = CoreEntityRepository()
    relations = EntityRelationRepository()

    async def make_pair(
        target_novel_id: str,
        name: str,
        *,
        reverse: bool = False,
        canonical: bool = False,
    ) -> tuple[str, str]:
        nid = uuid.UUID(hex=target_novel_id)
        source = await entities.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name=f"{name}甲",
        )
        target = await entities.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name=f"{name}乙",
        )
        await relations.create(
            db_session,
            nid,
            EntityRelationCreate(
                source_id=str(source.id),
                target_id=str(target.id),
                relation_type="related_to",
                status="candidate",
            ),
        )
        if reverse:
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
        if canonical:
            await relations.create(
                db_session,
                nid,
                EntityRelationCreate(
                    source_id=str(source.id),
                    target_id=str(target.id),
                    relation_type="friend_of",
                    relation_kind="social",
                    status="canonical",
                ),
            )
        return str(source.id), str(target.id)

    reverse_pair = await make_pair(novel_id, "反向", reverse=True)
    canonical_pair = await make_pair(novel_id, "正式", canonical=True)
    plain_pair = await make_pair(novel_id, "普通")
    await make_pair(other_novel_id, "其他项目", reverse=True, canonical=True)
    await db_session.flush()

    reverse_page = await async_client.get(
        "/api/world/relations/review-groups",
        params={
            "novel_id": novel_id,
            "has_reverse_candidates": True,
            "skip": 1,
            "limit": 1,
        },
    )
    assert reverse_page.status_code == 200, reverse_page.text
    reverse_payload = reverse_page.json()
    assert reverse_payload["group_total"] == 2
    assert reverse_payload["item_total"] == 2
    assert len(reverse_payload["groups"]) == 1
    assert {
        reverse_payload["groups"][0]["source_id"],
        reverse_payload["groups"][0]["target_id"],
    } == set(reverse_pair)

    service = EntityRelationService()
    canonical_only = await service.list_review_groups(
        db_session,
        novel_id,
        has_reverse_candidates=False,
        has_canonical_relation=True,
    )
    plain_only = await service.list_review_groups(
        db_session,
        novel_id,
        has_reverse_candidates=False,
        has_canonical_relation=False,
    )
    no_canonical = await service.list_review_groups(
        db_session,
        novel_id,
        has_canonical_relation=False,
    )

    assert canonical_only.group_total == canonical_only.item_total == 1
    assert (
        canonical_only.groups[0].source_id,
        canonical_only.groups[0].target_id,
    ) == canonical_pair
    assert plain_only.group_total == plain_only.item_total == 1
    assert (plain_only.groups[0].source_id, plain_only.groups[0].target_id) == plain_pair
    assert no_canonical.group_total == no_canonical.item_total == 3
    assert {
        endpoint_id
        for group in no_canonical.groups
        for endpoint_id in (group.source_id, group.target_id)
    }.isdisjoint(
        {
            entity_id
            for group in (
                await EntityRelationService().list_review_groups(
                    db_session, other_novel_id
                )
            ).groups
            for entity_id in (group.source_id, group.target_id)
        }
    )


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
                        "relation_kind": "state",
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
            relation_kind="social",
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
    assert result.results[0].canonical_relation_ids == [str(canonical.id)]
    assert result.results[0].reused_canonical_relation_ids == [str(canonical.id)]
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
async def test_relation_review_accepts_selected_relations_separately_and_ignores_rest(
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
            relation_kind="social",
            quote="旧证据",
            status="canonical",
        ),
    )
    first = await relations.create(
        db_session,
        nid,
        EntityRelationCreate(
            source_id=str(source.id),
            target_id=str(target.id),
            relation_type="related_to",
            quote="朋友证据",
            status="candidate",
        ),
    )
    second = await relations.create(
        db_session,
        nid,
        EntityRelationCreate(
            source_id=str(source.id),
            target_id=str(target.id),
            relation_type="opposes",
            quote="对抗证据",
            status="candidate",
        ),
    )
    unselected = await relations.create(
        db_session,
        nid,
        EntityRelationCreate(
            source_id=str(source.id),
            target_id=str(target.id),
            relation_type="unknown",
            status="candidate",
        ),
    )
    context_marker = AsyncMock(return_value=0)
    service = EntityRelationService(context_marker=context_marker)
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
                        "client_decision_id": "separate-two",
                        "action": "accept_separately",
                        "group_id": group.group_id,
                        "member_relation_ids": [str(first.id), str(second.id)],
                        "expected_execution_fingerprint": group.execution_fingerprint,
                        "unselected_action": "ignore",
                        "separate_relations": [
                            {
                                "candidate_relation_id": str(first.id),
                                "source_id": str(source.id),
                                "target_id": str(target.id),
                                "relation_type": "friend_of",
                                "description": "朋友",
                                "strength": 0.8,
                            },
                            {
                                "candidate_relation_id": str(second.id),
                                "source_id": str(target.id),
                                "target_id": str(source.id),
                                "relation_type": "enemy_of",
                                "description": "敌对",
                                "strength": 0.9,
                            },
                        ],
                    }
                ],
            }
        ),
    )

    item = result.results[0]
    assert item.status == "success"
    assert item.canonical_relation_id == str(canonical.id)
    assert item.canonical_relation_ids == [str(canonical.id), str(second.id)]
    assert item.reused_canonical_relation_ids == [str(canonical.id)]
    assert item.ignored_relation_ids == [str(unselected.id)]
    assert item.remaining_candidate_ids == []
    assert set(item.archived_relation_ids) == {str(first.id), str(unselected.id)}
    await db_session.refresh(canonical)
    await db_session.refresh(first)
    await db_session.refresh(second)
    await db_session.refresh(unselected)
    assert canonical.quote == "旧证据\n朋友证据"
    assert first.status == "deprecated"
    assert second.status == "canonical"
    assert (second.source_id, second.target_id, second.relation_type) == (
        target.id,
        source.id,
        "enemy_of",
    )
    assert unselected.status == "deprecated"
    assert unselected.review_meta["review_action"] == "relation_review_ignored"
    assert context_marker.await_count == 2


@pytest.mark.asyncio
async def test_relation_review_separate_apply_rolls_back_the_whole_group(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    other_novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    await _create_project(db_session, other_novel_id)
    nid = uuid.UUID(hex=novel_id)
    entities = CoreEntityRepository()
    relations = EntityRelationRepository()
    source = await entities.create_raw(
        db_session, novel_id=nid, entity_type="character", name="甲"
    )
    target = await entities.create_raw(
        db_session, novel_id=nid, entity_type="character", name="乙"
    )
    foreign = await entities.create_raw(
        db_session,
        novel_id=uuid.UUID(hex=other_novel_id),
        entity_type="character",
        name="其他项目对象",
    )
    candidates = [
        await relations.create(
            db_session,
            nid,
            EntityRelationCreate(
                source_id=str(source.id),
                target_id=str(target.id),
                relation_type=relation_type,
                status="candidate",
            ),
        )
        for relation_type in ("friend", "enemy")
    ]
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
                        "client_decision_id": "atomic-separate",
                        "action": "accept_separately",
                        "group_id": group.group_id,
                        "member_relation_ids": [str(item.id) for item in candidates],
                        "expected_execution_fingerprint": group.execution_fingerprint,
                        "separate_relations": [
                            {
                                "candidate_relation_id": str(candidates[0].id),
                                "source_id": str(source.id),
                                "target_id": str(target.id),
                                "relation_type": "friend_of",
                            },
                            {
                                "candidate_relation_id": str(candidates[1].id),
                                "source_id": str(source.id),
                                "target_id": str(foreign.id),
                                "relation_type": "enemy_of",
                            },
                        ],
                    }
                ],
            }
        ),
    )

    assert result.failed_count == 1
    for candidate in candidates:
        await db_session.refresh(candidate)
        assert candidate.status == "candidate"
    service._mark_synopsis_changed.assert_not_awaited()


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
async def test_alias_review_requires_kind_only_when_accepting_unknown_detail(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    entity = await CoreEntityRepository().create_raw(
        db_session,
        novel_id=uuid.UUID(hex=novel_id),
        entity_type="character",
        name="源对象",
        content_json={
            "aliases": [
                {
                    "alias": "镜中人",
                    "type": "镜中身份",
                    "status": "candidate",
                    "needs_review": True,
                }
            ]
        },
    )
    service = EntityAliasService(context_marker=AsyncMock(return_value=0))
    member = (await service.list_review_groups(db_session, novel_id)).groups[0].members[0]

    def request(alias_kind: str | None = None) -> EntityAliasReviewBatchRequest:
        decision = {
            "client_decision_id": f"accept-{alias_kind or 'missing'}",
            "action": "accept",
            "entity_id": str(entity.id),
            "original_alias": member.alias,
            "expected_execution_fingerprint": member.execution_fingerprint,
        }
        if alias_kind:
            decision["alias_kind"] = alias_kind
        return EntityAliasReviewBatchRequest.model_validate(
            {"confirmed": True, "decisions": [decision]}
        )

    failed = await service.review_batch(db_session, novel_id, request())
    assert failed.failed_count == 1
    await db_session.refresh(entity)
    assert entity.content_json["aliases"][0]["status"] == "candidate"

    accepted = await service.review_batch(db_session, novel_id, request("identity"))
    assert accepted.succeeded_count == 1
    await db_session.refresh(entity)
    assert entity.content_json["aliases"][0]["kind"] == "identity"
    assert entity.content_json["aliases"][0]["type"] == "镜中身份"


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
            "aliases": [{"alias": "重复别名", "type": "alias", "status": "canonical"}]
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
