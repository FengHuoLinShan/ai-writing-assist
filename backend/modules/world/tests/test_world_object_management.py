"""世界对象管理用户路径验收测试。

覆盖：实体列表搜索/过滤、手动创建标记、关系创建校验、人物知识边界校验。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import (
    CharacterKnowledgeCreate,
    EntityRelationCreate,
    EntityRelationUpdate,
    WorldEntityCreate,
)
from modules.world.services import (
    CharacterKnowledgeService,
    EntityRelationService,
    WorldEntityService,
)
from modules.world.tests.helpers import _create_project

# ============================================================
# 实体搜索/过滤
# ============================================================


class TestEntitySearchAndFilter:
    @pytest.mark.asyncio
    async def test_list_entities_filter_by_entity_type(
        self,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        service = WorldEntityService()

        await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="location", name="王都"),
        )
        await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="faction", name="骑士团"),
        )

        result = await service.list(db_session, novel_id, entity_type="location")
        assert result.total == 1
        assert result.items[0].name == "王都"

    @pytest.mark.asyncio
    async def test_list_entities_search_by_name(
        self,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        service = WorldEntityService()

        await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="location", name="黑暗森林"),
        )
        await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="faction", name="光明教廷"),
        )

        result = await service.list(db_session, novel_id, q="黑暗")
        assert result.total == 1
        assert result.items[0].name == "黑暗森林"

    @pytest.mark.asyncio
    async def test_list_entities_search_by_alias(
        self,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        service = WorldEntityService()

        await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="character",
                name="克莱恩",
                content_json={"aliases": [{"alias": "小克", "type": "nickname"}]},
            ),
        )
        await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="faction", name="塔罗会"),
        )

        result = await service.list(db_session, novel_id, q="小克")
        assert result.total == 1
        assert result.items[0].name == "克莱恩"

    @pytest.mark.asyncio
    async def test_list_entities_searches_descriptions_without_matching_import_evidence(
        self,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        service = WorldEntityService()

        await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="faction",
                name="值夜者",
                summary="处理超自然事件的队伍",
            ),
        )
        await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="character",
                name="伦纳德",
                summary="廷根市值夜者成员",
            ),
        )
        await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="item",
                name="封印物",
                content_json={"evidence": "曾由值夜者保管"},
            ),
        )

        result = await service.list(db_session, novel_id, q="值夜者")

        assert result.total == 2
        assert [item.name for item in result.items] == ["值夜者", "伦纳德"]

    @pytest.mark.asyncio
    async def test_list_entities_fuzzy_searches_name_and_alias(
        self,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        service = WorldEntityService()

        await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="faction", name="值夜者"),
        )
        await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="character",
                name="克莱恩",
                content_json={"aliases": [{"alias": "周明瑞", "type": "name"}]},
            ),
        )

        name_result = await service.list(db_session, novel_id, q="值夜着")
        alias_result = await service.list(db_session, novel_id, q="周明睿")

        assert [item.name for item in name_result.items] == ["值夜者"]
        assert [item.name for item in alias_result.items] == ["克莱恩"]

    @pytest.mark.asyncio
    async def test_list_entities_filters_deep_import_workflow_metadata(
        self,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        other_novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        await _create_project(db_session, other_novel_id)
        service = WorldEntityService()

        matching = await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="location",
                name="廷根市",
                status="deprecated",
                content_json={
                    "_meta": {
                        "source": "deep_import",
                        "workflow_id": "wf-world-filter",
                        "needs_review": True,
                        "auto_ingested": True,
                    }
                },
            ),
        )
        await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="location",
                name="贝克兰德",
                status="deprecated",
                content_json={
                    "_meta": {
                        "source": "deep_import",
                        "workflow_id": "wf-other",
                        "needs_review": True,
                        "auto_ingested": True,
                    }
                },
            ),
        )
        await service.create(
            db_session,
            other_novel_id,
            WorldEntityCreate(
                entity_type="location",
                name="其他小说地点",
                status="deprecated",
                content_json={
                    "_meta": {
                        "source": "deep_import",
                        "workflow_id": "wf-world-filter",
                        "needs_review": True,
                        "auto_ingested": True,
                    }
                },
            ),
        )

        result = await service.list(
            db_session,
            novel_id,
            status="deprecated",
            source="deep_import",
            workflow_id="wf-world-filter",
            needs_review=True,
            auto_ingested=True,
        )

        assert result.total == 1
        assert result.items[0].id == matching.id


# ============================================================
# 手动创建标记
# ============================================================


class TestManualCreate:
    @pytest.mark.asyncio
    async def test_manual_create_defaults_created_by(
        self,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        service = WorldEntityService()

        result = await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="item", name="测试物品"),
        )

        assert result.created_by == "manual"

    @pytest.mark.asyncio
    async def test_explicit_created_by_preserved(
        self,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        service = WorldEntityService()

        result = await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="item",
                name="测试物品",
                created_by="测试用户",
            ),
        )

        assert result.created_by == "测试用户"


# ============================================================
# 关系创建校验
# ============================================================


class TestRelationValidation:
    @pytest.fixture
    def relation_service(self) -> EntityRelationService:
        return EntityRelationService()

    @pytest.mark.asyncio
    async def test_create_relation_success(
        self,
        db_session: AsyncSession,
        relation_service: EntityRelationService,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        entity_service = WorldEntityService()

        source = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="主角"),
        )
        target = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="faction", name="组织"),
        )

        result = await relation_service.create(
            db_session,
            novel_id,
            EntityRelationCreate(
                source_id=source.id,
                target_id=target.id,
                relation_type="member_of",
            ),
        )

        assert result.source_id == source.id
        assert result.target_id == target.id
        assert result.relation_type == "member_of"

    @pytest.mark.asyncio
    async def test_list_relations_includes_endpoint_names(
        self,
        db_session: AsyncSession,
        relation_service: EntityRelationService,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        entity_service = WorldEntityService()
        source = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="克莱恩"),
        )
        target = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="邓恩"),
        )
        await relation_service.create(
            db_session,
            novel_id,
            EntityRelationCreate(
                source_id=source.id,
                target_id=target.id,
                relation_type="member_of",
            ),
        )

        result = await relation_service.list(db_session, novel_id)

        assert result.total == 1
        assert result.items[0].source_name == "克莱恩"
        assert result.items[0].target_name == "邓恩"

    @pytest.mark.asyncio
    async def test_get_and_update_relation_include_endpoint_names(
        self,
        db_session: AsyncSession,
        relation_service: EntityRelationService,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        entity_service = WorldEntityService()
        source = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="克莱恩"),
        )
        target = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="伦纳德"),
        )
        created = await relation_service.create(
            db_session,
            novel_id,
            EntityRelationCreate(
                source_id=source.id,
                target_id=target.id,
                relation_type="ally_of",
            ),
        )

        fetched = await relation_service.get(db_session, created.id, novel_id=novel_id)
        updated = await relation_service.update(
            db_session,
            created.id,
            EntityRelationUpdate(description="并肩调查"),
            novel_id=novel_id,
        )

        assert fetched.source_name == "克莱恩"
        assert fetched.target_name == "伦纳德"
        assert updated.source_name == "克莱恩"
        assert updated.target_name == "伦纳德"

    @pytest.mark.asyncio
    async def test_create_relation_self_loop_rejected(
        self,
        db_session: AsyncSession,
        relation_service: EntityRelationService,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        entity_service = WorldEntityService()
        entity = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="主角"),
        )

        with pytest.raises(ValidationError) as exc:
            await relation_service.create(
                db_session,
                novel_id,
                EntityRelationCreate(
                    source_id=entity.id,
                    target_id=entity.id,
                    relation_type="related_to",
                ),
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_relation_cross_novel_rejected(
        self,
        db_session: AsyncSession,
        relation_service: EntityRelationService,
    ) -> None:
        novel_a = str(uuid.uuid4())
        novel_b = str(uuid.uuid4())
        await _create_project(db_session, novel_a)
        await _create_project(db_session, novel_b)
        entity_service = WorldEntityService()

        source = await entity_service.create(
            db_session,
            novel_a,
            WorldEntityCreate(entity_type="character", name="A"),
        )
        target = await entity_service.create(
            db_session,
            novel_b,
            WorldEntityCreate(entity_type="faction", name="B"),
        )

        with pytest.raises(NotFoundError) as exc:
            await relation_service.create(
                db_session,
                novel_a,
                EntityRelationCreate(
                    source_id=source.id,
                    target_id=target.id,
                    relation_type="related_to",
                ),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_create_relation_duplicate_rejected(
        self,
        db_session: AsyncSession,
        relation_service: EntityRelationService,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        entity_service = WorldEntityService()

        source = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="主角"),
        )
        target = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="faction", name="组织"),
        )

        await relation_service.create(
            db_session,
            novel_id,
            EntityRelationCreate(
                source_id=source.id,
                target_id=target.id,
                relation_type="member_of",
            ),
        )

        with pytest.raises(ConflictError) as exc:
            await relation_service.create(
                db_session,
                novel_id,
                EntityRelationCreate(
                    source_id=source.id,
                    target_id=target.id,
                    relation_type="member_of",
                ),
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_create_or_merge_relation_merges_duplicate_evidence(
        self,
        db_session: AsyncSession,
        relation_service: EntityRelationService,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        entity_service = WorldEntityService()
        source = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="克莱恩"),
        )
        target = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="梅丽莎"),
        )

        first = await relation_service.create_or_merge(
            db_session,
            novel_id,
            EntityRelationCreate(
                source_id=source.id,
                target_id=target.id,
                relation_type="sibling",
                description="兄妹",
                quote="哥哥与妹妹",
                strength=0.4,
                status="candidate",
            ),
        )
        second = await relation_service.create_or_merge(
            db_session,
            novel_id,
            EntityRelationCreate(
                source_id=source.id,
                target_id=target.id,
                relation_type="sibling",
                description="共同生活",
                quote="家人相依",
                strength=0.8,
                status="candidate",
            ),
        )

        assert first["action"] == "created"
        assert second["action"] == "merged"
        relation = second["relation"]
        assert "兄妹" in relation.description
        assert "共同生活" in relation.description
        assert "哥哥与妹妹" in relation.quote
        assert "家人相依" in relation.quote
        assert relation.strength == 0.8

    @pytest.mark.asyncio
    async def test_import_candidate_does_not_mutate_existing_canonical_relation(
        self,
        db_session: AsyncSession,
        relation_service: EntityRelationService,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        entity_service = WorldEntityService()
        source = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="甲"),
        )
        target = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="乙"),
        )
        created = await relation_service.create_or_merge(
            db_session,
            novel_id,
            EntityRelationCreate(
                source_id=source.id,
                target_id=target.id,
                relation_type="ally_of",
                description="已采用描述",
                quote="已采用证据",
                strength=0.4,
                status="canonical",
                review_meta={"source": "manual"},
            ),
        )

        duplicate = await relation_service.create_or_merge(
            db_session,
            novel_id,
            EntityRelationCreate(
                source_id=source.id,
                target_id=target.id,
                relation_type="ally_of",
                description="未采用导入描述",
                quote="未采用证据",
                strength=0.9,
                status="candidate",
                review_meta={"source": "deep_import", "workflow_id": "wf-1"},
            ),
        )

        assert duplicate["action"] == "deduplicated"
        relation = await relation_service.repo.get(
            db_session,
            uuid.UUID(str(created["relation"].id)),
        )
        assert relation is not None
        assert relation.status == "canonical"
        assert relation.description == "已采用描述"
        assert relation.quote == "已采用证据"
        assert relation.strength == 0.4
        assert relation.review_meta == {"source": "manual"}

    @pytest.mark.asyncio
    async def test_relation_candidate_rollback_is_workflow_scoped_and_idempotent(
        self,
        db_session: AsyncSession,
        relation_service: EntityRelationService,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        entity_service = WorldEntityService()
        source = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="甲"),
        )
        target = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="乙"),
        )
        created = await relation_service.create_or_merge(
            db_session,
            novel_id,
            EntityRelationCreate(
                source_id=source.id,
                target_id=target.id,
                relation_type="knows",
                status="candidate",
                review_meta={"source": "deep_import", "workflow_id": "wf-1"},
            ),
        )

        assert (
            await relation_service.rollback_deep_import_candidates_by_workflow(
                db_session,
                novel_id,
                "wf-1",
            )
            == 1
        )
        relation = await relation_service.repo.get(
            db_session,
            uuid.UUID(str(created["relation"].id)),
        )
        assert relation is not None
        assert relation.status == "deprecated"
        assert relation.review_meta["rolled_back"] is True
        assert (
            await relation_service.rollback_deep_import_candidates_by_workflow(
                db_session,
                novel_id,
                "wf-1",
            )
            == 0
        )


# ============================================================
# 人物知识边界 false_belief 校验
# ============================================================


class TestKnowledgeBoundary:
    @pytest.fixture
    def knowledge_service(self) -> CharacterKnowledgeService:
        return CharacterKnowledgeService()

    @pytest.fixture
    def character_repo(self) -> CoreEntityRepository:
        return CoreEntityRepository()

    @pytest.mark.asyncio
    async def test_create_false_belief_with_misconception_allowed(
        self,
        db_session: AsyncSession,
        knowledge_service: CharacterKnowledgeService,
        character_repo: CoreEntityRepository,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        entity_service = WorldEntityService()

        char_entity = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="主角"),
        )
        from modules.world.models import Character

        character = Character(
            entity_id=uuid.UUID(hex=char_entity.id),
            novel_id=uuid.UUID(hex=novel_id),
            name=char_entity.name,
        )
        db_session.add(character)
        await db_session.flush()

        target = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="faction", name="秘密组织"),
        )

        result = await knowledge_service.create(
            db_session,
            novel_id,
            CharacterKnowledgeCreate(
                character_id=char_entity.id,
                target_type="entity",
                target_id=target.id,
                knowledge_level="false_belief",
                known_content="他以为组织是正义的",
                misconception="组织实际上是邪恶的",
            ),
        )

        assert result.knowledge_level == "false_belief"
        assert result.misconception == "组织实际上是邪恶的"


# ============================================================
# API 层验收
# ============================================================


class TestWorldObjectManagementAPI:
    @pytest.mark.asyncio
    async def test_api_list_entities_with_search(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        service = WorldEntityService()
        await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="克莱恩"),
        )

        response = await async_client.get(
            "/api/world/entities",
            params={"novel_id": novel_id, "q": "克莱"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "克莱恩"

    @pytest.mark.asyncio
    async def test_api_list_entities_filters_deep_import_workflow_metadata(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        service = WorldEntityService()
        matching = await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="location",
                name="廷根市",
                status="deprecated",
                content_json={
                    "_meta": {
                        "source": "deep_import",
                        "workflow_id": "wf-world-api",
                        "needs_review": True,
                        "auto_ingested": True,
                    }
                },
            ),
        )
        await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="location",
                name="无关地点",
                status="deprecated",
                content_json={
                    "_meta": {
                        "source": "deep_import",
                        "workflow_id": "wf-other",
                        "needs_review": True,
                        "auto_ingested": True,
                    }
                },
            ),
        )

        response = await async_client.get(
            "/api/world/entities",
            params={
                "novel_id": novel_id,
                "status": "deprecated",
                "source": "deep_import",
                "workflow_id": "wf-world-api",
                "needs_review": "true",
                "auto_ingested": "true",
            },
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == matching.id

    @pytest.mark.asyncio
    async def test_api_create_relation_duplicate_returns_409(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        service = WorldEntityService()
        source = await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="主角"),
        )
        target = await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="faction", name="组织"),
        )

        payload = {
            "source_id": source.id,
            "target_id": target.id,
            "relation_type": "member_of",
        }
        first = await async_client.post(
            "/api/world/relations",
            params={"novel_id": novel_id},
            json=payload,
        )
        assert first.status_code == 201

        second = await async_client.post(
            "/api/world/relations",
            params={"novel_id": novel_id},
            json=payload,
        )
        assert second.status_code == 409

    @pytest.mark.asyncio
    async def test_api_create_relation_self_loop_returns_400(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        service = WorldEntityService()
        entity = await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="主角"),
        )

        response = await async_client.post(
            "/api/world/relations",
            params={"novel_id": novel_id},
            json={
                "source_id": entity.id,
                "target_id": entity.id,
                "relation_type": "related_to",
            },
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_api_promote_draft_entity_to_canonical(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        service = WorldEntityService()
        entity = await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="character",
                name="草稿角色",
                status="draft",
            ),
        )
        assert entity.status == "draft"

        response = await async_client.post(
            f"/api/world/entities/{entity.id}/promote",
            params={"novel_id": novel_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["entity_id"] == entity.id
        assert data["status"] == "canonical"
        assert data["approved_by"] == "manual"

    @pytest.mark.asyncio
    async def test_api_promote_canonical_entity_returns_400(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        service = WorldEntityService()
        entity = await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="character",
                name="正史角色",
                status="canonical",
            ),
        )

        response = await async_client.post(
            f"/api/world/entities/{entity.id}/promote",
            params={"novel_id": novel_id},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_api_promote_entity_wrong_novel_returns_404(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        other_novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        await _create_project(db_session, other_novel_id)
        service = WorldEntityService()
        entity = await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="草稿角色"),
        )

        response = await async_client.post(
            f"/api/world/entities/{entity.id}/promote",
            params={"novel_id": other_novel_id},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_api_create_knowledge_false_belief_without_misconception_returns_422(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        await _create_project(db_session, novel_id)
        service = WorldEntityService()
        char_entity = await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="character", name="主角"),
        )
        from modules.world.models import Character

        character = Character(
            entity_id=uuid.UUID(hex=char_entity.id),
            novel_id=uuid.UUID(hex=novel_id),
            name=char_entity.name,
        )
        db_session.add(character)
        await db_session.flush()

        target = await service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="faction", name="秘密组织"),
        )

        response = await async_client.post(
            f"/api/world/characters/{char_entity.id}/knowledge",
            params={"novel_id": novel_id},
            json={
                "character_id": char_entity.id,
                "target_type": "entity",
                "target_id": target.id,
                "knowledge_level": "false_belief",
                "known_content": "他以为组织是正义的",
            },
        )
        assert response.status_code == 422
