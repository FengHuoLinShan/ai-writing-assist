"""
Character 模块测试

测试 CRUD 各路径、知识边界过滤、facade 和边界情况。
使用 pytest-asyncio 测试异步数据库操作。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.character.facade import (
    filter_context_by_character_knowledge,
    get_character_knowledge_context,
    get_characters_context,
)
from modules.character.repositories import (
    CharacterKnowledgeRepository,
    CharacterRepository,
)
from modules.character.schemas import (
    CharacterContextBundle,
    CharacterCreate,
    CharacterKnowledgeContext,
    CharacterKnowledgeCreate,
    CharacterUpdate,
)


# ============================================================
# Repository 测试
# ============================================================

class TestCharacterRepository:
    """测试数据访问层"""

    @pytest.mark.asyncio
    async def test_create(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """测试创建人物"""
        repo = CharacterRepository()
        data = CharacterCreate(
            novel_id=sample_novel_id,
            name="测试人物",
            role="supporting",
        )
        character = await repo.create(db_session, data)
        assert character.id is not None
        assert character.name == "测试人物"
        assert character.role == "supporting"
        assert character.status == "canonical"

    @pytest.mark.asyncio
    async def test_create_with_full_fields(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """测试创建全字段人物"""
        repo = CharacterRepository()
        data = CharacterCreate(
            novel_id=sample_novel_id,
            name="林月",
            role="protagonist",
            appearance="黑发碧眸",
            personality="冷静果断",
            desire="寻找真相",
            fear="失去同伴",
            secret="拥有预知能力",
            weakness="过于信任他人",
            current_goal="调查异变",
            current_state="前往旧城区",
            current_emotion="警惕",
            stance="中立善良",
            voice_style="简洁有力",
            behavior_rules=[
                {"rule": "不透露身份", "context": "与陌生人交谈"},
            ],
            relationship_summary="与陈锋搭档",
        )
        character = await repo.create(db_session, data)
        assert character.id is not None
        assert character.name == "林月"
        assert character.role == "protagonist"
        assert character.current_goal == "调查异变"
        assert len(character.behavior_rules) == 1

    @pytest.mark.asyncio
    async def test_get(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """测试根据 ID 获取人物"""
        repo = CharacterRepository()
        data = CharacterCreate(novel_id=sample_novel_id, name="获取测试")
        created = await repo.create(db_session, data)

        fetched = await repo.get(db_session, created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == "获取测试"

    @pytest.mark.asyncio
    async def test_get_not_found(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试获取不存在的人物"""
        repo = CharacterRepository()
        fake_id = uuid.uuid4()
        fetched = await repo.get(db_session, fake_id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_get_by_novel(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """测试按小说获取人物列表"""
        repo = CharacterRepository()
        for i in range(3):
            data = CharacterCreate(
                novel_id=sample_novel_id,
                name=f"人物{i}",
            )
            await repo.create(db_session, data)

        items, total = await repo.get_by_novel(
            db_session, uuid.UUID(hex=sample_novel_id),
        )
        assert total >= 3
        assert len(items) >= 3

    @pytest.mark.asyncio
    async def test_get_by_ids(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """测试批量获取人物"""
        repo = CharacterRepository()
        ids = []
        for i in range(3):
            data = CharacterCreate(
                novel_id=sample_novel_id,
                name=f"批量{i}",
            )
            char = await repo.create(db_session, data)
            ids.append(char.id)

        fetched = await repo.get_by_ids(
            db_session,
            uuid.UUID(hex=sample_novel_id),
            ids,
        )
        assert len(fetched) == 3

    @pytest.mark.asyncio
    async def test_update(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """测试更新人物"""
        repo = CharacterRepository()
        data = CharacterCreate(novel_id=sample_novel_id, name="更新前")
        created = await repo.create(db_session, data)

        update_data = CharacterUpdate(name="更新后", current_state="新状态")
        updated = await repo.update(db_session, created.id, update_data)
        assert updated is not None
        assert updated.name == "更新后"
        assert updated.current_state == "新状态"

    @pytest.mark.asyncio
    async def test_update_not_found(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试更新不存在的人物"""
        repo = CharacterRepository()
        fake_id = uuid.uuid4()
        update_data = CharacterUpdate(name="不存在")
        updated = await repo.update(db_session, fake_id, update_data)
        assert updated is None

    @pytest.mark.asyncio
    async def test_delete(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """测试删除人物"""
        repo = CharacterRepository()
        data = CharacterCreate(novel_id=sample_novel_id, name="待删除")
        created = await repo.create(db_session, data)

        deleted = await repo.delete(db_session, created.id)
        assert deleted is True

        fetched = await repo.get(db_session, created.id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_delete_not_found(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试删除不存在的人物"""
        repo = CharacterRepository()
        fake_id = uuid.uuid4()
        deleted = await repo.delete(db_session, fake_id)
        assert deleted is False


class TestCharacterKnowledgeRepository:
    """测试人物知识数据访问层"""

    @pytest.mark.asyncio
    async def test_create(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        sample_character_id: str,
    ) -> None:
        """测试创建知识记录"""
        repo = CharacterKnowledgeRepository()
        data = CharacterKnowledgeCreate(
            novel_id=sample_novel_id,
            character_id=sample_character_id,
            target_type="entity",
            target_id=str(uuid.uuid4()),
            knowledge_level="full",
            known_content="完全知道这个秘密",
            source_chapter_index=3,
        )
        knowledge = await repo.create(db_session, data)
        assert knowledge.id is not None
        assert knowledge.knowledge_level == "full"
        assert knowledge.known_content == "完全知道这个秘密"

    @pytest.mark.asyncio
    async def test_create_false_belief(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        sample_character_id: str,
    ) -> None:
        """测试创建误解型知识记录"""
        repo = CharacterKnowledgeRepository()
        data = CharacterKnowledgeCreate(
            novel_id=sample_novel_id,
            character_id=sample_character_id,
            target_type="character",
            target_id=str(uuid.uuid4()),
            knowledge_level="false_belief",
            known_content="认为陈锋是叛徒",
            misconception="实际上陈锋是卧底，角色误以为他是叛徒",
            source_chapter_index=5,
        )
        knowledge = await repo.create(db_session, data)
        assert knowledge.knowledge_level == "false_belief"
        assert knowledge.misconception is not None

    @pytest.mark.asyncio
    async def test_get_by_character(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        sample_character_id: str,
    ) -> None:
        """测试获取人物所有知识"""
        repo = CharacterKnowledgeRepository()
        # 创建多条知识
        for i in range(2):
            data = CharacterKnowledgeCreate(
                novel_id=sample_novel_id,
                character_id=sample_character_id,
                target_type="entity",
                target_id=str(uuid.uuid4()),
                knowledge_level="partial",
                known_content=f"知识{i}",
            )
            await repo.create(db_session, data)

        items, total = await repo.get_by_character(
            db_session,
            uuid.UUID(hex=sample_novel_id),
            uuid.UUID(hex=sample_character_id),
        )
        assert total >= 2
        assert len(items) >= 2

    @pytest.mark.asyncio
    async def test_get_by_target(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        sample_character_id: str,
    ) -> None:
        """测试按目标获取知识"""
        repo = CharacterKnowledgeRepository()
        target_id = str(uuid.uuid4())

        data = CharacterKnowledgeCreate(
            novel_id=sample_novel_id,
            character_id=sample_character_id,
            target_type="entity",
            target_id=target_id,
            knowledge_level="unknown",
        )
        await repo.create(db_session, data)

        target_uuids = [uuid.UUID(hex=target_id)]
        results = await repo.get_by_target(
            db_session,
            uuid.UUID(hex=sample_novel_id),
            uuid.UUID(hex=sample_character_id),
            target_ids=target_uuids,
        )
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_update(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        sample_character_id: str,
    ) -> None:
        """测试更新知识记录"""
        repo = CharacterKnowledgeRepository()
        data = CharacterKnowledgeCreate(
            novel_id=sample_novel_id,
            character_id=sample_character_id,
            target_type="entity",
            target_id=str(uuid.uuid4()),
            knowledge_level="rumor",
            known_content="听到了一点风声",
        )
        created = await repo.create(db_session, data)

        from modules.character.schemas import CharacterKnowledgeUpdate

        update_data = CharacterKnowledgeUpdate(
            knowledge_level="full",
            known_content="现在全知道了",
        )
        updated = await repo.update(db_session, created.id, update_data)
        assert updated is not None
        assert updated.knowledge_level == "full"
        assert updated.known_content == "现在全知道了"

    @pytest.mark.asyncio
    async def test_delete(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        sample_character_id: str,
    ) -> None:
        """测试删除知识记录"""
        repo = CharacterKnowledgeRepository()
        data = CharacterKnowledgeCreate(
            novel_id=sample_novel_id,
            character_id=sample_character_id,
            target_type="entity",
            target_id=str(uuid.uuid4()),
            knowledge_level="unknown",
        )
        created = await repo.create(db_session, data)

        deleted = await repo.delete(db_session, created.id)
        assert deleted is True

        fetched = await repo.get(db_session, created.id)
        assert fetched is None


# ============================================================
# Service 测试
# ============================================================

class TestCharacterService:
    """测试业务逻辑层"""

    @pytest.mark.asyncio
    async def test_create_character(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """测试服务层创建人物"""
        from modules.character.services import CharacterService

        service = CharacterService()
        data = CharacterCreate(
            novel_id=sample_novel_id,
            name="服务测试人物",
        )
        resp = await service.create_character(db_session, data)
        assert resp.id is not None
        assert resp.name == "服务测试人物"

    @pytest.mark.asyncio
    async def test_get_character_not_found(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试服务层获取不存在的人物"""
        from modules.character.services import CharacterService

        service = CharacterService()
        fake_id = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await service.get_character(db_session, fake_id)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_character_state(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        sample_character_id: str,
    ) -> None:
        """测试更新人物状态"""
        from modules.character.services import CharacterService

        service = CharacterService()
        resp = await service.update_character_state(
            db_session,
            sample_character_id,
            current_state="到达新地点",
            current_emotion="紧张",
            current_goal="寻找线索",
        )
        assert resp.current_state == "到达新地点"
        assert resp.current_emotion == "紧张"
        assert resp.current_goal == "寻找线索"

    @pytest.mark.asyncio
    async def test_get_characters_context(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        sample_character_id: str,
    ) -> None:
        """测试获取人物上下文"""
        from modules.character.services import CharacterService

        service = CharacterService()
        bundle = await service.get_characters_context(
            db_session,
            sample_novel_id,
            [sample_character_id],
        )
        assert isinstance(bundle, CharacterContextBundle)
        assert bundle.total == 1
        assert bundle.characters[0].character_id == sample_character_id
        assert bundle.characters[0].name == "林月"

    @pytest.mark.asyncio
    async def test_get_characters_context_author_only(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        sample_character_id: str,
    ) -> None:
        """测试 author_only 模式返回 secret"""
        from modules.character.services import CharacterService

        service = CharacterService()
        bundle = await service.get_characters_context(
            db_session,
            sample_novel_id,
            [sample_character_id],
            reveal_mode="author_only",
        )
        assert bundle.characters[0].secret == "拥有预知未来的能力"


# ============================================================
# 知识边界过滤测试（核心功能）
# ============================================================

class TestCharacterKnowledgeFilter:
    """测试人物知识边界过滤功能"""

    @pytest.mark.asyncio
    async def test_filter_unknown_removes_item(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        sample_character_id: str,
    ) -> None:
        """测试 knowledge_level=unknown 时移除项"""
        from modules.character.services import CharacterService

        service = CharacterService()
        target_id = str(uuid.uuid4())

        # 创建一条 unknown 知识
        from modules.character.repositories import CharacterKnowledgeRepository
        from modules.character.schemas import CharacterKnowledgeCreate

        k_repo = CharacterKnowledgeRepository()
        await k_repo.create(db_session, CharacterKnowledgeCreate(
            novel_id=sample_novel_id,
            character_id=sample_character_id,
            target_type="entity",
            target_id=target_id,
            knowledge_level="unknown",
        ))

        context_items = [
            {"target_type": "entity", "target_id": target_id, "content": "秘密信息"},
        ]
        filtered, removed, replaced = (
            await service.filter_context_by_character_knowledge(
                db_session, sample_novel_id, sample_character_id, context_items,
            )
        )
        assert len(filtered) == 0
        assert removed == 1
        assert replaced == 0

    @pytest.mark.asyncio
    async def test_filter_false_belief_replaces_content(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        sample_character_id: str,
    ) -> None:
        """测试 false_belief 时替换为误解内容"""
        from modules.character.services import CharacterService
        from modules.character.repositories import CharacterKnowledgeRepository
        from modules.character.schemas import CharacterKnowledgeCreate

        service = CharacterService()
        k_repo = CharacterKnowledgeRepository()
        target_id = str(uuid.uuid4())

        await k_repo.create(db_session, CharacterKnowledgeCreate(
            novel_id=sample_novel_id,
            character_id=sample_character_id,
            target_type="entity",
            target_id=target_id,
            knowledge_level="false_belief",
            known_content="认为这个组织是正义的",
            misconception="角色被误导，认为这个组织是光明磊落的",
        ))

        context_items = [
            {"target_type": "entity", "target_id": target_id, "content": "这个组织实际上是邪恶的"},
        ]
        filtered, removed, replaced = (
            await service.filter_context_by_character_knowledge(
                db_session, sample_novel_id, sample_character_id, context_items,
            )
        )
        assert len(filtered) == 1
        assert removed == 0
        assert replaced == 1
        assert filtered[0].get("is_misconception") is True
        assert "邪恶" not in filtered[0].get("content", "")
        assert "光明磊落" in filtered[0].get("content", "")

    @pytest.mark.asyncio
    async def test_filter_full_keeps_item(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        sample_character_id: str,
    ) -> None:
        """测试 knowledge_level=full 时保留项"""
        from modules.character.services import CharacterService
        from modules.character.repositories import CharacterKnowledgeRepository
        from modules.character.schemas import CharacterKnowledgeCreate

        service = CharacterService()
        k_repo = CharacterKnowledgeRepository()
        target_id = str(uuid.uuid4())

        await k_repo.create(db_session, CharacterKnowledgeCreate(
            novel_id=sample_novel_id,
            character_id=sample_character_id,
            target_type="entity",
            target_id=target_id,
            knowledge_level="full",
            known_content="完全了解这个组织",
        ))

        context_items = [
            {"target_type": "entity", "target_id": target_id, "content": "组织信息"},
        ]
        filtered, removed, replaced = (
            await service.filter_context_by_character_knowledge(
                db_session, sample_novel_id, sample_character_id, context_items,
            )
        )
        assert len(filtered) == 1
        assert removed == 0
        assert replaced == 0
        assert filtered[0].get("knowledge_level") == "full"

    @pytest.mark.asyncio
    async def test_filter_mixed_knowledge(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        sample_character_id: str,
    ) -> None:
        """测试混合知识的过滤场景"""
        from modules.character.services import CharacterService
        from modules.character.repositories import CharacterKnowledgeRepository
        from modules.character.schemas import CharacterKnowledgeCreate

        service = CharacterService()
        k_repo = CharacterKnowledgeRepository()

        known_id = str(uuid.uuid4())
        unknown_id = str(uuid.uuid4())
        false_id = str(uuid.uuid4())

        # full 知识
        await k_repo.create(db_session, CharacterKnowledgeCreate(
            novel_id=sample_novel_id,
            character_id=sample_character_id,
            target_type="entity",
            target_id=known_id,
            knowledge_level="full",
            known_content="已知信息",
        ))
        # unknown 知识
        await k_repo.create(db_session, CharacterKnowledgeCreate(
            novel_id=sample_novel_id,
            character_id=sample_character_id,
            target_type="entity",
            target_id=unknown_id,
            knowledge_level="unknown",
        ))
        # false_belief 知识
        await k_repo.create(db_session, CharacterKnowledgeCreate(
            novel_id=sample_novel_id,
            character_id=sample_character_id,
            target_type="entity",
            target_id=false_id,
            knowledge_level="false_belief",
            known_content="表面说法",
            misconception="角色的误解",
        ))

        context_items = [
            {"target_type": "entity", "target_id": known_id, "content": "A"},
            {"target_type": "entity", "target_id": unknown_id, "content": "B"},
            {"target_type": "entity", "target_id": false_id, "content": "C"},
        ]
        filtered, removed, replaced = (
            await service.filter_context_by_character_knowledge(
                db_session, sample_novel_id, sample_character_id, context_items,
            )
        )
        assert len(filtered) == 2  # unknown 被移除
        assert removed == 1
        assert replaced == 1


# ============================================================
# Facade 测试
# ============================================================

class TestCharacterFacade:
    """测试对外入口"""

    @pytest.mark.asyncio
    async def test_get_characters_context(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        sample_character_id: str,
    ) -> None:
        """测试 facade.get_characters_context"""
        bundle = await get_characters_context(
            db_session, sample_novel_id, [sample_character_id],
        )
        assert isinstance(bundle, CharacterContextBundle)
        assert bundle.total == 1

    @pytest.mark.asyncio
    async def test_get_character_knowledge_context(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        sample_character_id: str,
        sample_target_entity_id: str,
    ) -> None:
        """测试 facade.get_character_knowledge_context"""
        # 先创建一条知识
        from modules.character.repositories import CharacterKnowledgeRepository
        from modules.character.schemas import CharacterKnowledgeCreate

        k_repo = CharacterKnowledgeRepository()
        await k_repo.create(db_session, CharacterKnowledgeCreate(
            novel_id=sample_novel_id,
            character_id=sample_character_id,
            target_type="entity",
            target_id=sample_target_entity_id,
            knowledge_level="full",
            known_content="测试知识",
        ))

        result = await get_character_knowledge_context(
            db_session, sample_novel_id, sample_character_id,
            target_ids=[sample_target_entity_id],
        )
        assert len(result) == 1
        assert isinstance(result[0], CharacterKnowledgeContext)
        assert result[0].knowledge_level == "full"

    @pytest.mark.asyncio
    async def test_filter_context_by_character_knowledge(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        sample_character_id: str,
    ) -> None:
        """测试 facade.filter_context_by_character_knowledge"""
        from modules.character.repositories import CharacterKnowledgeRepository
        from modules.character.schemas import CharacterKnowledgeCreate

        k_repo = CharacterKnowledgeRepository()
        target_id = str(uuid.uuid4())
        await k_repo.create(db_session, CharacterKnowledgeCreate(
            novel_id=sample_novel_id,
            character_id=sample_character_id,
            target_type="entity",
            target_id=target_id,
            knowledge_level="unknown",
        ))

        context_items = [
            {"target_type": "entity", "target_id": target_id, "content": "秘密"},
        ]
        result = await filter_context_by_character_knowledge(
            db_session, sample_novel_id, sample_character_id, context_items,
        )
        assert len(result) == 0  # unknown -> 移除


# ============================================================
# API Schema 测试
# ============================================================

class TestCharacterSchemas:
    """测试 Pydantic schema"""

    def test_character_create_validation(self) -> None:
        """测试创建人物 schema 校验"""
        data = CharacterCreate(
            novel_id=str(uuid.uuid4()),
            name="测试",
        )
        assert data.name == "测试"
        assert data.status == "canonical"  # 默认值

    def test_character_update_partial(self) -> None:
        """测试部分更新 schema"""
        data = CharacterUpdate(name="新名字")
        assert data.name == "新名字"
        assert data.current_goal is None  # 未设置

    def test_character_knowledge_create_validation(self) -> None:
        """测试创建知识 schema 校验"""
        data = CharacterKnowledgeCreate(
            novel_id=str(uuid.uuid4()),
            character_id=str(uuid.uuid4()),
            target_type="entity",
            target_id=str(uuid.uuid4()),
            knowledge_level="full",
        )
        assert data.knowledge_level == "full"
        assert data.status == "canonical"
