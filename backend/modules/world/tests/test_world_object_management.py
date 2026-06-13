"""世界对象管理用户路径验收测试。

覆盖：实体列表搜索/过滤、手动创建标记、关系创建校验、人物知识边界校验。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import (
    CharacterKnowledgeCreate,
    EntityRelationCreate,
    WorldEntityCreate,
)
from modules.world.services import (
    CharacterKnowledgeService,
    EntityRelationService,
    WorldEntityService,
)

# ============================================================
# Helpers
# ============================================================


async def _create_project(db_session: AsyncSession, novel_id: str) -> None:
    """在内存数据库中创建一个测试项目，用于外键约束。"""
    import modules.project.models  # noqa: F401
    from modules.project.models import Project

    project = Project(
        id=uuid.UUID(hex=novel_id),
        title="测试项目",
        genre="fantasy",
        language="zh",
        target_length="novel",
        current_stage="worldbuilding",
    )
    db_session.add(project)
    await db_session.flush()


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

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
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

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
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

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
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
