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
            meta={"ai_suggestions": {"desire": "寻找真相"}},
        )
        character = await repo.create(db_session, data)
        assert character.id is not None
        assert character.name == "林月"
        assert character.role == "protagonist"
        assert character.current_goal == "调查异变"
        assert len(character.behavior_rules) == 1
        assert character.meta == {"ai_suggestions": {"desire": "寻找真相"}}

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
            db_session,
            uuid.UUID(hex=sample_novel_id),
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

        update_data = CharacterUpdate(
            name="更新后",
            current_state="新状态",
            meta={"review": {"source": "manual"}},
        )
        updated = await repo.update(db_session, created.id, update_data)
        assert updated is not None
        assert updated.name == "更新后"
        assert updated.current_state == "新状态"
        assert updated.meta == {"review": {"source": "manual"}}

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
        await k_repo.create(
            db_session,
            CharacterKnowledgeCreate(
                novel_id=sample_novel_id,
                character_id=sample_character_id,
                target_type="entity",
                target_id=target_id,
                knowledge_level="unknown",
            ),
        )

        context_items = [
            {"target_type": "entity", "target_id": target_id, "content": "秘密信息"},
        ]
        filtered, removed, replaced = await service.filter_context_by_character_knowledge(
            db_session,
            sample_novel_id,
            sample_character_id,
            context_items,
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
        from modules.character.repositories import CharacterKnowledgeRepository
        from modules.character.schemas import CharacterKnowledgeCreate
        from modules.character.services import CharacterService

        service = CharacterService()
        k_repo = CharacterKnowledgeRepository()
        target_id = str(uuid.uuid4())

        await k_repo.create(
            db_session,
            CharacterKnowledgeCreate(
                novel_id=sample_novel_id,
                character_id=sample_character_id,
                target_type="entity",
                target_id=target_id,
                knowledge_level="false_belief",
                known_content="认为这个组织是正义的",
                misconception="角色被误导，认为这个组织是光明磊落的",
            ),
        )

        context_items = [
            {
                "target_type": "entity",
                "target_id": target_id,
                "content": "这个组织实际上是邪恶的",
            },
        ]
        filtered, removed, replaced = await service.filter_context_by_character_knowledge(
            db_session,
            sample_novel_id,
            sample_character_id,
            context_items,
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
        from modules.character.repositories import CharacterKnowledgeRepository
        from modules.character.schemas import CharacterKnowledgeCreate
        from modules.character.services import CharacterService

        service = CharacterService()
        k_repo = CharacterKnowledgeRepository()
        target_id = str(uuid.uuid4())

        await k_repo.create(
            db_session,
            CharacterKnowledgeCreate(
                novel_id=sample_novel_id,
                character_id=sample_character_id,
                target_type="entity",
                target_id=target_id,
                knowledge_level="full",
                known_content="完全了解这个组织",
            ),
        )

        context_items = [
            {"target_type": "entity", "target_id": target_id, "content": "组织信息"},
        ]
        filtered, removed, replaced = await service.filter_context_by_character_knowledge(
            db_session,
            sample_novel_id,
            sample_character_id,
            context_items,
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
        from modules.character.repositories import CharacterKnowledgeRepository
        from modules.character.schemas import CharacterKnowledgeCreate
        from modules.character.services import CharacterService

        service = CharacterService()
        k_repo = CharacterKnowledgeRepository()

        known_id = str(uuid.uuid4())
        unknown_id = str(uuid.uuid4())
        false_id = str(uuid.uuid4())

        # full 知识
        await k_repo.create(
            db_session,
            CharacterKnowledgeCreate(
                novel_id=sample_novel_id,
                character_id=sample_character_id,
                target_type="entity",
                target_id=known_id,
                knowledge_level="full",
                known_content="已知信息",
            ),
        )
        # unknown 知识
        await k_repo.create(
            db_session,
            CharacterKnowledgeCreate(
                novel_id=sample_novel_id,
                character_id=sample_character_id,
                target_type="entity",
                target_id=unknown_id,
                knowledge_level="unknown",
            ),
        )
        # false_belief 知识
        await k_repo.create(
            db_session,
            CharacterKnowledgeCreate(
                novel_id=sample_novel_id,
                character_id=sample_character_id,
                target_type="entity",
                target_id=false_id,
                knowledge_level="false_belief",
                known_content="表面说法",
                misconception="角色的误解",
            ),
        )

        context_items = [
            {"target_type": "entity", "target_id": known_id, "content": "A"},
            {"target_type": "entity", "target_id": unknown_id, "content": "B"},
            {"target_type": "entity", "target_id": false_id, "content": "C"},
        ]
        filtered, removed, replaced = await service.filter_context_by_character_knowledge(
            db_session,
            sample_novel_id,
            sample_character_id,
            context_items,
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
            db_session,
            sample_novel_id,
            [sample_character_id],
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
        await k_repo.create(
            db_session,
            CharacterKnowledgeCreate(
                novel_id=sample_novel_id,
                character_id=sample_character_id,
                target_type="entity",
                target_id=sample_target_entity_id,
                knowledge_level="full",
                known_content="测试知识",
            ),
        )

        result = await get_character_knowledge_context(
            db_session,
            sample_novel_id,
            sample_character_id,
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
        await k_repo.create(
            db_session,
            CharacterKnowledgeCreate(
                novel_id=sample_novel_id,
                character_id=sample_character_id,
                target_type="entity",
                target_id=target_id,
                knowledge_level="unknown",
            ),
        )

        context_items = [
            {"target_type": "entity", "target_id": target_id, "content": "秘密"},
        ]
        result = await filter_context_by_character_knowledge(
            db_session,
            sample_novel_id,
            sample_character_id,
            context_items,
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


class TestFindCharacterByName:
    @pytest.mark.asyncio
    async def test_find_character_by_name_exact(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        repo = CharacterRepository()
        data = CharacterCreate(novel_id=sample_novel_id, name="林动")
        char = await repo.create(db_session, data)

        nid = uuid.UUID(hex=sample_novel_id)
        result = await repo.find_character_by_name(db_session, nid, "林动")
        assert result == str(char.id)

    @pytest.mark.asyncio
    async def test_find_character_by_name_alias(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        repo = CharacterRepository()
        data = CharacterCreate(
            novel_id=sample_novel_id,
            name="林动",
            aliases=[{"alias": "动哥", "type": "nickname"}],
        )
        char = await repo.create(db_session, data)

        nid = uuid.UUID(hex=sample_novel_id)
        result = await repo.find_character_by_name(db_session, nid, "动哥")
        assert result == str(char.id)

    @pytest.mark.asyncio
    async def test_find_character_by_name_not_found(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        repo = CharacterRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        result = await repo.find_character_by_name(db_session, nid, "不存在")
        assert result is None


class TestUpdateCharacterLocation:
    @pytest.mark.asyncio
    async def test_update_character_location(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        repo = CharacterRepository()
        data = CharacterCreate(novel_id=sample_novel_id, name="测试角色")
        char = await repo.create(db_session, data)

        location_id = str(uuid.uuid4())
        await repo.update_character_meta_location(
            db_session,
            char.id,
            location_id,
            "在炎城",
            5,
        )

        updated = await repo.get(db_session, char.id)
        assert updated is not None
        assert updated.current_state == "在炎城"
        assert updated.meta["current_location_id"] == location_id
        assert updated.meta["last_updated_chapter"] == 5


class TestCharacterExtract:
    """测试人物档案抽取任务 — handle_character_extract 正确写入 ai_suggestions"""

    @pytest.mark.asyncio
    async def test_extract_writes_ai_suggestions_to_db(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from unittest import mock

        from infrastructure.tasks.models import AsyncTask
        from modules.character.schemas import CharacterResponse
        from modules.rag.contracts import RagChunkContract, RagResultBundle

        repo = CharacterRepository()
        data = CharacterCreate(
            novel_id=sample_novel_id,
            name="周明瑞",
            role="protagonist",
        )
        character = await repo.create(db_session, data)
        await db_session.flush()

        char_resp = CharacterResponse.model_validate(character)
        task = AsyncTask(
            id=uuid.uuid4(),
            task_type="character_extract",
            status="pending",
            meta={"novel_id": sample_novel_id, "character_id": str(character.id)},
            progress=0.0,
        )

        mock_chunks = RagResultBundle(
            chunks=[
                RagChunkContract(
                    id="chunk-1",
                    novel_id=sample_novel_id,
                    source_type="chapter",
                    text="周明瑞追求武道巅峰，内心深处害怕失去至亲之人。",
                ),
            ],
            total=1,
            query="周明瑞 渴望 目标 欲望 追求 动机",
        )

        class _MockExtractOutput:
            desire = "追求武道巅峰"
            fear = "失去至亲之人"
            secret = None
            weakness = None
            current_goal = None
            current_state = None
            current_emotion = None
            stance = None
            voice_style = None
            role = "protagonist"

        with (
            mock.patch(
                "modules.character.facade.list_characters", return_value=([char_resp], 1)
            ),
            mock.patch("modules.rag.facade.retrieve", return_value=mock_chunks),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured",
                return_value=_MockExtractOutput(),
            ),
            mock.patch(
                "infrastructure.llm.prompt_loader.load_prompt", return_value="test prompt"
            ),
            mock.patch("core.config.get_settings") as mock_settings,
        ):
            mock_settings.return_value.llm_model = "test-model"

            from modules.character.tasks import handle_character_extract

            result = await handle_character_extract(db_session, task)

        assert result["status"] == "ok"
        assert "desire" in result["fields"]
        assert "fear" in result["fields"]

        updated = await repo.get(db_session, character.id)
        assert updated is not None
        assert updated.meta is not None
        assert "ai_suggestions" in updated.meta
        assert updated.meta["ai_suggestions"]["desire"] == "追求武道巅峰"
        assert updated.meta["ai_suggestions"]["fear"] == "失去至亲之人"
        assert "ai_suggestions_at" in updated.meta

    @pytest.mark.asyncio
    async def test_apply_suggestions_updates_formal_fields_and_clears(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.character.services import CharacterService
        from modules.character.tasks import _EXTRACTABLE_FIELDS

        repo = CharacterRepository()
        data = CharacterCreate(
            novel_id=sample_novel_id,
            name="周明瑞",
            role="protagonist",
            desire="",
            fear="",
            meta={
                "ai_suggestions": {
                    "desire": "追求武道巅峰",
                    "fear": "失去至亲之人",
                    "weakness": "过于重情",
                },
                "ai_suggestions_at": "2025-01-01T00:00:00+00:00",
            },
        )
        character = await repo.create(db_session, data)
        await db_session.flush()
        char_id = str(character.id)

        service = CharacterService()
        char = await service.get_character(db_session, char_id, novel_id=sample_novel_id)
        meta = dict(getattr(char, "meta", {}) or {})
        suggestions = meta.get("ai_suggestions", {})

        fields_to_apply = ["desire", "fear"]
        updates: dict[str, object] = {}
        for field in fields_to_apply:
            if field in suggestions and suggestions[field]:
                if field in _EXTRACTABLE_FIELDS:
                    updates[field] = suggestions[field]

        remaining_suggestions = {
            k: v for k, v in suggestions.items() if k not in fields_to_apply
        }
        meta["ai_suggestions"] = remaining_suggestions
        if not remaining_suggestions:
            meta.pop("ai_suggestions", None)
            meta.pop("ai_suggestions_at", None)
        updates["meta"] = meta

        update_data = CharacterUpdate(**updates)
        result = await service.update_character(
            db_session, char_id, update_data, novel_id=sample_novel_id
        )

        assert result.desire == "追求武道巅峰"
        assert result.fear == "失去至亲之人"
        assert result.meta.get("ai_suggestions") == {"weakness": "过于重情"}
        assert "ai_suggestions_at" in result.meta

        updated = await repo.get(db_session, character.id)
        assert updated.desire == "追求武道巅峰"
        assert updated.fear == "失去至亲之人"
        assert updated.meta["ai_suggestions"] == {"weakness": "过于重情"}

    @pytest.mark.asyncio
    async def test_apply_all_suggestions_clears_at_timestamp(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.character.services import CharacterService
        from modules.character.tasks import _EXTRACTABLE_FIELDS

        repo = CharacterRepository()
        data = CharacterCreate(
            novel_id=sample_novel_id,
            name="周明瑞2",
            desire="",
            meta={
                "ai_suggestions": {
                    "desire": "追求武道巅峰",
                },
                "ai_suggestions_at": "2025-01-01T00:00:00+00:00",
            },
        )
        character = await repo.create(db_session, data)
        await db_session.flush()
        char_id = str(character.id)

        service = CharacterService()
        char = await service.get_character(db_session, char_id, novel_id=sample_novel_id)
        meta = dict(getattr(char, "meta", {}) or {})
        suggestions = meta.get("ai_suggestions", {})

        fields_to_apply = list(suggestions.keys())
        updates: dict[str, object] = {}
        for field in fields_to_apply:
            if field in suggestions and suggestions[field]:
                if field in _EXTRACTABLE_FIELDS:
                    updates[field] = suggestions[field]

        remaining_suggestions = {
            k: v for k, v in suggestions.items() if k not in fields_to_apply
        }
        meta["ai_suggestions"] = remaining_suggestions
        if not remaining_suggestions:
            meta.pop("ai_suggestions", None)
            meta.pop("ai_suggestions_at", None)
        updates["meta"] = meta

        update_data = CharacterUpdate(**updates)
        result = await service.update_character(
            db_session, char_id, update_data, novel_id=sample_novel_id
        )

        assert result.desire == "追求武道巅峰"
        assert (
            result.meta.get("ai_suggestions") is None
            or result.meta.get("ai_suggestions") == {}
        )
        assert "ai_suggestions_at" not in result.meta

    @pytest.mark.asyncio
    async def test_extract_rag_fallback_without_character_filter(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from unittest import mock

        from infrastructure.tasks.models import AsyncTask
        from modules.character.schemas import CharacterResponse
        from modules.rag.contracts import RagChunkContract, RagResultBundle

        repo = CharacterRepository()
        data = CharacterCreate(
            novel_id=sample_novel_id,
            name="周明瑞",
            role="protagonist",
        )
        character = await repo.create(db_session, data)
        await db_session.flush()

        char_resp = CharacterResponse.model_validate(character)
        task = AsyncTask(
            id=uuid.uuid4(),
            task_type="character_extract",
            status="pending",
            meta={"novel_id": sample_novel_id, "character_id": str(character.id)},
            progress=0.0,
        )

        empty_result = RagResultBundle(chunks=[], total=0, query="test")
        fallback_result = RagResultBundle(
            chunks=[
                RagChunkContract(
                    id="chunk-1",
                    novel_id=sample_novel_id,
                    source_type="chapter",
                    text="周明瑞追求武道巅峰。",
                ),
            ],
            total=1,
            query="test",
        )

        class _MockExtractOutput:
            desire = "追求武道巅峰"
            fear = None
            secret = None
            weakness = None
            current_goal = None
            current_state = None
            current_emotion = None
            stance = None
            voice_style = None
            role = None

        call_count = 0

        async def _mock_retrieve(db, novel_id, query, **kwargs):
            nonlocal call_count
            call_count += 1
            if kwargs.get("character_ids"):
                return empty_result
            return fallback_result

        with (
            mock.patch(
                "modules.character.facade.list_characters", return_value=([char_resp], 1)
            ),
            mock.patch("modules.rag.facade.retrieve", side_effect=_mock_retrieve),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured",
                return_value=_MockExtractOutput(),
            ),
            mock.patch(
                "infrastructure.llm.prompt_loader.load_prompt", return_value="test prompt"
            ),
            mock.patch("core.config.get_settings") as mock_settings,
        ):
            mock_settings.return_value.llm_model = "test-model"

            from modules.character.tasks import handle_character_extract

            result = await handle_character_extract(db_session, task)

        assert result["status"] == "ok", f"Expected ok, got {result}"
        assert "desire" in result["fields"]

    @pytest.mark.asyncio
    async def test_extract_llm_retry_on_failure(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from unittest import mock

        from infrastructure.tasks.models import AsyncTask
        from modules.character.schemas import CharacterResponse
        from modules.rag.contracts import RagChunkContract, RagResultBundle

        repo = CharacterRepository()
        data = CharacterCreate(
            novel_id=sample_novel_id,
            name="周明瑞",
            role="protagonist",
        )
        character = await repo.create(db_session, data)
        await db_session.flush()

        char_resp = CharacterResponse.model_validate(character)
        task = AsyncTask(
            id=uuid.uuid4(),
            task_type="character_extract",
            status="pending",
            meta={"novel_id": sample_novel_id, "character_id": str(character.id)},
            progress=0.0,
        )

        mock_chunks = RagResultBundle(
            chunks=[
                RagChunkContract(
                    id="chunk-1",
                    novel_id=sample_novel_id,
                    source_type="chapter",
                    text="周明瑞追求武道巅峰。",
                ),
            ],
            total=1,
            query="test",
        )

        class _MockExtractOutput:
            desire = "追求武道巅峰"
            fear = None
            secret = None
            weakness = None
            current_goal = None
            current_state = None
            current_emotion = None
            stance = None
            voice_style = None
            role = None

        llm_call_count = 0

        def _mock_generate_structured(request, schema):
            nonlocal llm_call_count
            llm_call_count += 1
            if llm_call_count == 1:
                raise RuntimeError("LLM temporarily unavailable")
            return _MockExtractOutput()

        with (
            mock.patch(
                "modules.character.facade.list_characters", return_value=([char_resp], 1)
            ),
            mock.patch("modules.rag.facade.retrieve", return_value=mock_chunks),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured",
                side_effect=_mock_generate_structured,
            ),
            mock.patch(
                "infrastructure.llm.prompt_loader.load_prompt", return_value="test prompt"
            ),
            mock.patch("core.config.get_settings") as mock_settings,
            mock.patch("asyncio.sleep", new_callable=mock.AsyncMock),
        ):
            mock_settings.return_value.llm_model = "test-model"

            from modules.character.tasks import handle_character_extract

            result = await handle_character_extract(db_session, task)

        assert result["status"] == "ok", f"Expected ok after retry, got {result}"
        assert llm_call_count == 2

    @pytest.mark.asyncio
    async def test_extract_indexes_existing_draft_when_rag_is_empty(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """历史导入未建 RAG 时，应从已有草稿补索引后再抽取人物档案。"""
        from unittest import mock

        from infrastructure.tasks.models import AsyncTask
        from modules.rag.repositories import RagChunkRepository
        from modules.writing.schemas import WritingDraftCreate
        from modules.writing.services import WritingDraftService

        repo = CharacterRepository()
        data = CharacterCreate(
            novel_id=sample_novel_id,
            name="周明瑞",
            role="protagonist",
        )
        character = await repo.create(db_session, data)

        writing = WritingDraftService()
        await writing.create_draft(
            db_session,
            WritingDraftCreate(
                novel_id=sample_novel_id,
                chapter_index=1,
                title="第一章",
                content="熟睡中的周明瑞只觉脑袋抽痛异常。他想要回家，也害怕失去对身体的控制。",
            ),
        )
        await db_session.flush()

        task = AsyncTask(
            id=uuid.uuid4(),
            task_type="character_extract",
            status="pending",
            meta={"novel_id": sample_novel_id, "character_id": str(character.id)},
            progress=0.0,
        )

        class _MockExtractOutput:
            desire = "回到原本的世界"
            fear = "失去对身体的控制"
            secret = None
            weakness = None
            current_goal = None
            current_state = None
            current_emotion = None
            stance = None
            voice_style = None
            role = None

        with (
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured",
                return_value=_MockExtractOutput(),
            ),
            mock.patch(
                "infrastructure.llm.prompt_loader.load_prompt", return_value="test prompt"
            ),
            mock.patch("core.config.get_settings") as mock_settings,
        ):
            mock_settings.return_value.llm_model = "test-model"

            from modules.character.tasks import handle_character_extract

            result = await handle_character_extract(db_session, task)

        assert result["status"] == "ok"
        assert result["fields"] == ["desire", "fear"]

        chunks, total = await RagChunkRepository().get_multi(
            db_session,
            uuid.UUID(hex=sample_novel_id),
        )
        assert total == 1
        assert str(character.id) in (chunks[0].character_ids or [])

        updated = await repo.get(db_session, character.id)
        assert updated is not None
        assert updated.meta["ai_suggestions"]["desire"] == "回到原本的世界"


class TestGetCharacterLocationId:
    """测试 character.facade.get_character_location_id"""

    @pytest.mark.asyncio
    async def test_get_character_location_id_returns_location(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.character.facade import get_character_location_id

        repo = CharacterRepository()
        data = CharacterCreate(novel_id=sample_novel_id, name="定位角色")
        char = await repo.create(db_session, data)

        location_id = str(uuid.uuid4())
        await repo.update_character_meta_location(
            db_session,
            char.id,
            location_id,
            "在炎城",
            3,
        )

        result = await get_character_location_id(
            db_session,
            sample_novel_id,
            str(char.id),
        )
        assert result == location_id

    @pytest.mark.asyncio
    async def test_get_character_location_id_returns_none_when_no_location(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.character.facade import get_character_location_id

        repo = CharacterRepository()
        data = CharacterCreate(novel_id=sample_novel_id, name="无定位角色")
        char = await repo.create(db_session, data)

        result = await get_character_location_id(
            db_session,
            sample_novel_id,
            str(char.id),
        )
        assert result is None
