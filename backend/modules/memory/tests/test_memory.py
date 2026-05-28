"""
Memory 模块测试

测试 MemoryRecord CRUD、提案管理、候选确认流程。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.memory.facade import (
    confirm_memory_proposal,
    create_memory_update_proposals,
    get_entity_memory,
    get_recent_story_memory,
)
from modules.memory.repositories import (
    MemoryProposalRepository,
    MemoryRecordRepository,
)
from modules.memory.schemas import (
    ChapterStateExtraction,
    MemoryRecordCreate,
    MemoryRecordUpdate,
)
from modules.memory.services import MemoryService


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def repo() -> MemoryRecordRepository:
    return MemoryRecordRepository()


@pytest.fixture
def proposal_repo() -> MemoryProposalRepository:
    return MemoryProposalRepository()


@pytest.fixture
def service() -> MemoryService:
    return MemoryService()


@pytest.fixture
def sample_record_data() -> MemoryRecordCreate:
    return MemoryRecordCreate(
        memory_type="chapter_state",
        chapter_index=5,
        title="第五章结束状态",
        summary="主角发现了古城遗迹的秘密入口",
        content_json={"location": "古城遗迹", "discovery": "秘密入口"},
        visibility="reader_known",
        related_character_ids=[str(uuid.uuid4())],
        related_entity_ids=[str(uuid.uuid4())],
        importance=0.8,
    )


@pytest.fixture
def sample_extraction_result() -> dict[str, list[dict[str, Any]]]:
    return {
        "proposals": [
            {
                "proposal_type": "create_memory",
                "payload": {
                    "memory_type": "event",
                    "title": "古城遗迹发现",
                    "summary": "主角发现了古城遗迹的秘密入口",
                    "content_json": {"location": "古城遗迹", "key": "secret_door"},
                    "chapter_index": 5,
                    "importance": 0.8,
                    "visibility": "reader_known",
                    "related_character_ids": [str(uuid.uuid4())],
                    "related_entity_ids": [str(uuid.uuid4())],
                },
                "confidence": 0.85,
                "reason": "主角在古城遗迹章节中发现了秘密入口，这是一个重要事件",
                "chapter_index": 5,
            },
            {
                "proposal_type": "update_character_state",
                "payload": {
                    "memory_type": "character_state",
                    "title": "主角状态变化",
                    "summary": "主角得知古城秘密后决心找到真相",
                    "content_json": {"emotion": "determined", "goal": "find_truth"},
                    "chapter_index": 5,
                    "importance": 0.6,
                    "visibility": "author_only",
                },
                "confidence": 0.7,
                "reason": "主角在发现秘密后态度发生变化",
                "chapter_index": 5,
            },
        ]
    }


# ============================================================
# MemoryRecordRepository 测试
# ============================================================

class TestMemoryRecordRepository:
    """测试记忆记录数据访问层"""

    @pytest.mark.asyncio
    async def test_create(
        self,
        repo: MemoryRecordRepository,
        db_session: AsyncSession,
        novel_id: str,
        sample_record_data: MemoryRecordCreate,
    ) -> None:
        """测试创建记忆记录"""
        record = await repo.create(
            db_session,
            uuid.UUID(hex=novel_id),
            sample_record_data,
        )
        assert record.id is not None
        assert record.memory_type == "chapter_state"
        assert record.chapter_index == 5
        assert record.summary == "主角发现了古城遗迹的秘密入口"
        assert record.importance == 0.8
        assert record.visibility == "reader_known"
        assert record.status == "canonical"

    @pytest.mark.asyncio
    async def test_get(
        self,
        repo: MemoryRecordRepository,
        db_session: AsyncSession,
        novel_id: str,
        sample_record_data: MemoryRecordCreate,
    ) -> None:
        """测试根据 ID 获取记忆记录"""
        created = await repo.create(
            db_session,
            uuid.UUID(hex=novel_id),
            sample_record_data,
        )
        fetched = await repo.get(db_session, created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.summary == "主角发现了古城遗迹的秘密入口"

    @pytest.mark.asyncio
    async def test_get_not_found(
        self,
        repo: MemoryRecordRepository,
        db_session: AsyncSession,
    ) -> None:
        """测试获取不存在的记忆记录"""
        fake_id = uuid.uuid4()
        fetched = await repo.get(db_session, fake_id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_get_multi(
        self,
        repo: MemoryRecordRepository,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试分页获取记忆记录"""
        nid = uuid.UUID(hex=novel_id)
        for i in range(3):
            await repo.create(
                db_session,
                nid,
                MemoryRecordCreate(
                    memory_type="event",
                    chapter_index=i + 1,
                    summary=f"事件{i + 1}",
                ),
            )
        await db_session.flush()

        items, total = await repo.get_multi(db_session, nid, limit=10)
        assert total >= 3
        assert len(items) >= 3

    @pytest.mark.asyncio
    async def test_get_multi_with_chapter_filter(
        self,
        repo: MemoryRecordRepository,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试按章节过滤"""
        nid = uuid.UUID(hex=novel_id)
        for i in range(5):
            await repo.create(
                db_session,
                nid,
                MemoryRecordCreate(
                    memory_type="event",
                    chapter_index=i + 1,
                    summary=f"第{i + 1}章事件",
                ),
            )
        await db_session.flush()

        items, total = await repo.get_multi(
            db_session,
            nid,
            before_chapter_index=3,
            limit=10,
        )
        # 应该只返回 chapter_index <= 3 的记录
        assert total <= 3
        for item in items:
            assert item.chapter_index is None or item.chapter_index <= 3

    @pytest.mark.asyncio
    async def test_update(
        self,
        repo: MemoryRecordRepository,
        db_session: AsyncSession,
        novel_id: str,
        sample_record_data: MemoryRecordCreate,
    ) -> None:
        """测试更新记忆记录"""
        created = await repo.create(
            db_session,
            uuid.UUID(hex=novel_id),
            sample_record_data,
        )
        updated = await repo.update(
            db_session,
            created.id,
            MemoryRecordUpdate(summary="更新后的摘要", importance=0.9),
        )
        assert updated is not None
        assert updated.summary == "更新后的摘要"
        assert updated.importance == 0.9
        # 未更新字段保持不变
        assert updated.memory_type == "chapter_state"

    @pytest.mark.asyncio
    async def test_delete(
        self,
        repo: MemoryRecordRepository,
        db_session: AsyncSession,
        novel_id: str,
        sample_record_data: MemoryRecordCreate,
    ) -> None:
        """测试删除记忆记录"""
        created = await repo.create(
            db_session,
            uuid.UUID(hex=novel_id),
            sample_record_data,
        )
        deleted = await repo.delete(db_session, created.id)
        assert deleted is True
        fetched = await repo.get(db_session, created.id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_get_by_entity(
        self,
        repo: MemoryRecordRepository,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试按实体 ID 查询记忆记录"""
        nid = uuid.UUID(hex=novel_id)
        entity_id = str(uuid.uuid4())

        # 创建关联该实体的记忆
        await repo.create(
            db_session,
            nid,
            MemoryRecordCreate(
                memory_type="event",
                summary="关联实体的记忆",
                related_entity_ids=[entity_id],
            ),
        )
        # 创建不关联的记忆
        await repo.create(
            db_session,
            nid,
            MemoryRecordCreate(
                memory_type="event",
                summary="不关联的记忆",
            ),
        )
        await db_session.flush()

        records = await repo.get_by_entity(
            db_session, nid, uuid.UUID(hex=entity_id)
        )
        assert len(records) == 1
        assert records[0].summary == "关联实体的记忆"


# ============================================================
# MemoryProposalRepository 测试
# ============================================================

class TestMemoryProposalRepository:
    """测试记忆提案数据访问层"""

    @pytest.mark.asyncio
    async def test_create_and_get(
        self,
        proposal_repo: MemoryProposalRepository,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试创建和获取提案"""
        proposal = await proposal_repo.create(
            db_session,
            uuid.UUID(hex=novel_id),
            proposal_type="create_memory",
            payload={"summary": "测试提案"},
            confidence=0.8,
            reason="测试理由",
        )
        assert proposal.id is not None
        assert proposal.proposal_type == "create_memory"
        assert proposal.decision == "pending"

        fetched = await proposal_repo.get(db_session, proposal.id)
        assert fetched is not None
        assert fetched.id == proposal.id

    @pytest.mark.asyncio
    async def test_get_pending(
        self,
        proposal_repo: MemoryProposalRepository,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试获取待处理的提案列表"""
        nid = uuid.UUID(hex=novel_id)
        for i in range(3):
            await proposal_repo.create(
                db_session,
                nid,
                proposal_type="create_memory",
                payload={"index": i},
                chapter_index=i + 1,
            )
        await db_session.flush()

        items, total = await proposal_repo.get_pending(db_session, nid)
        assert total == 3
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_decide(
        self,
        proposal_repo: MemoryProposalRepository,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试审批提案"""
        nid = uuid.UUID(hex=novel_id)
        proposal = await proposal_repo.create(
            db_session,
            nid,
            proposal_type="create_memory",
            payload={"summary": "测试"},
        )

        # 批准
        decided = await proposal_repo.decide(
            db_session, proposal.id, decision="approved"
        )
        assert decided is not None
        assert decided.decision == "approved"
        assert decided.decided_at is not None


# ============================================================
# MemoryService 测试
# ============================================================

class TestMemoryService:
    """测试记忆业务逻辑层"""

    @pytest.mark.asyncio
    async def test_create_memory_update_proposals(
        self,
        service: MemoryService,
        db_session: AsyncSession,
        novel_id: str,
        sample_extraction_result: dict[str, list[dict[str, Any]]],
    ) -> None:
        """测试从抽取结果创建提案"""
        proposals = await service.create_memory_update_proposals(
            db_session,
            novel_id,
            source_type="chapter_text",
            source_id=str(uuid.uuid4()),
            extraction_result=sample_extraction_result,
        )
        assert len(proposals) == 2
        assert proposals[0].proposal_type == "create_memory"
        assert proposals[1].proposal_type == "update_character_state"
        assert proposals[0].decision == "pending"
        assert proposals[0].confidence == 0.85

    @pytest.mark.asyncio
    async def test_confirm_memory_proposal(
        self,
        service: MemoryService,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试确认提案 — 写入正史"""
        nid = uuid.UUID(hex=novel_id)
        repo = MemoryProposalRepository()
        proposal = await repo.create(
            db_session,
            nid,
            proposal_type="create_memory",
            payload={
                "memory_type": "event",
                "summary": "确认测试记忆",
                "chapter_index": 3,
                "importance": 0.7,
                "visibility": "reader_known",
            },
            chapter_index=3,
        )

        # 确认提案
        result = await service.confirm_memory_proposal(
            db_session, str(proposal.id), novel_id
        )
        assert result.summary == "确认测试记忆"
        assert result.memory_type == "event"

        # 验证提案已被标记为 approved
        updated_proposal = await repo.get(db_session, proposal.id)
        assert updated_proposal is not None
        assert updated_proposal.decision == "approved"

    @pytest.mark.asyncio
    async def test_confirm_already_decided_proposal(
        self,
        service: MemoryService,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试确认已处理的提案应报错"""
        nid = uuid.UUID(hex=novel_id)
        repo = MemoryProposalRepository()
        proposal = await repo.create(
            db_session,
            nid,
            proposal_type="create_memory",
            payload={"summary": "测试"},
        )
        # 先批准一次
        await service.confirm_memory_proposal(db_session, str(proposal.id), novel_id)

        # 再次确认应报 409
        with pytest.raises(HTTPException) as exc_info:
            await service.confirm_memory_proposal(db_session, str(proposal.id), novel_id)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_confirm_not_found(
        self,
        service: MemoryService,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试确认不存在的提案"""
        fake_id = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await service.confirm_memory_proposal(db_session, fake_id, novel_id)
        assert exc_info.value.status_code == 404


# ============================================================
# Facade 测试
# ============================================================

class TestMemoryFacade:
    """测试对外入口"""

    @pytest.mark.asyncio
    async def test_get_recent_story_memory(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试获取最近故事记忆"""
        nid = uuid.UUID(hex=novel_id)
        repo = MemoryRecordRepository()

        # 创建多条记忆
        for i in range(5):
            await repo.create(
                db_session,
                nid,
                MemoryRecordCreate(
                    memory_type="event",
                    chapter_index=i + 1,
                    summary=f"第{i + 1}章事件",
                ),
            )
        await db_session.flush()

        memories = await get_recent_story_memory(
            db_session, novel_id, before_chapter_index=3, limit=5
        )
        assert len(memories) <= 5
        # 按章节倒序，最新的在前
        for m in memories:
            assert m.chapter_index is None or m.chapter_index <= 3

    @pytest.mark.asyncio
    async def test_get_entity_memory(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试获取关联实体的记忆"""
        nid = uuid.UUID(hex=novel_id)
        repo = MemoryRecordRepository()
        entity_id = str(uuid.uuid4())

        await repo.create(
            db_session,
            nid,
            MemoryRecordCreate(
                memory_type="event",
                summary="关联实体的记忆",
                related_entity_ids=[entity_id],
            ),
        )
        await db_session.flush()

        memories = await get_entity_memory(db_session, novel_id, entity_id)
        assert len(memories) == 1
        assert memories[0].summary == "关联实体的记忆"

    @pytest.mark.asyncio
    async def test_create_and_confirm_proposal_flow(
        self,
        db_session: AsyncSession,
        novel_id: str,
        sample_extraction_result: dict[str, list[dict[str, Any]]],
    ) -> None:
        """测试完整的提案创建→确认流程"""
        # 创建提案
        proposals = await create_memory_update_proposals(
            db_session,
            novel_id,
            source_type="chapter_text",
            source_id=str(uuid.uuid4()),
            extraction_result=sample_extraction_result,
        )
        assert len(proposals) == 2

        # 确认第一个提案
        result = await confirm_memory_proposal(
            db_session, proposals[0].id, novel_id
        )
        assert result.summary is not None
        assert result.memory_type == "event"
        assert result.importance == 0.8


# ============================================================
# ChapterStateExtraction Schema 测试
# ============================================================

class TestChapterStateExtraction:

    def test_chapter_state_extraction_valid(self) -> None:
        extraction = ChapterStateExtraction(
            summary="主角前往北境",
            character_shifts=[
                {
                    "character_name": "李明",
                    "destination_location_name": "北境",
                    "movement_type": "御剑飞行",
                }
            ],
            faction_shifts=[
                {
                    "faction_name": "天剑宗",
                    "target_location_name": "北境",
                    "new_relation": "controls",
                    "description": "天剑宗全面控制北境",
                }
            ],
        )
        assert extraction.summary == "主角前往北境"
        assert len(extraction.character_shifts) == 1
        assert extraction.character_shifts[0].character_name == "李明"
        assert extraction.character_shifts[0].destination_location_name == "北境"
        assert extraction.character_shifts[0].movement_type == "御剑飞行"
        assert len(extraction.faction_shifts) == 1
        assert extraction.faction_shifts[0].faction_name == "天剑宗"
        assert extraction.faction_shifts[0].new_relation == "controls"
        assert extraction.faction_shifts[0].description == "天剑宗全面控制北境"

    def test_chapter_state_extraction_invalid_relation_downgrade(self) -> None:
        extraction = ChapterStateExtraction(
            summary="测试",
            faction_shifts=[
                {
                    "faction_name": "暗影门",
                    "target_location_name": "东域",
                    "new_relation": "invalid_relation",
                    "description": "暗影门渗透东域",
                }
            ],
        )
        assert extraction.faction_shifts[0].new_relation == "stationed_at"

    def test_chapter_state_extraction_empty_shifts(self) -> None:
        extraction = ChapterStateExtraction(summary="平静的一章")
        assert extraction.character_shifts == []
        assert extraction.faction_shifts == []


class TestGeoMutationsDispatch:

    @pytest.mark.asyncio
    async def test_confirm_proposal_with_character_shift(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        from modules.character.repositories import CharacterRepository
        from modules.character.schemas import CharacterCreate
        from modules.world.repositories import WorldEntityRepository
        from modules.world.schemas import WorldEntityCreate

        char_repo = CharacterRepository()
        char = await char_repo.create(
            db_session,
            CharacterCreate(novel_id=novel_id, name="林动"),
        )

        entity_repo = WorldEntityRepository()
        nid = uuid.UUID(hex=novel_id)
        loc = await entity_repo.create(
            db_session, nid,
            WorldEntityCreate(entity_type="location", name="炎城", status="canonical"),
        )

        proposal_repo = MemoryProposalRepository()
        proposal = await proposal_repo.create(
            db_session,
            nid,
            proposal_type="create_memory",
            payload={
                "memory_type": "chapter_state",
                "summary": "林动前往炎城",
                "chapter_index": 3,
                "geo_mutations": {
                    "character_shifts": [
                        {
                            "character_name": "林动",
                            "destination_location_name": "炎城",
                            "movement_type": "御剑飞行",
                        }
                    ],
                    "faction_shifts": [],
                },
            },
            chapter_index=3,
        )

        service = MemoryService()
        result = await service.confirm_memory_proposal(
            db_session, str(proposal.id), novel_id,
        )
        assert result.summary == "林动前往炎城"

        updated = await char_repo.get(db_session, char.id)
        assert updated is not None
        assert updated.meta.get("current_location_id") == str(loc.id)
        assert "御剑飞行" in updated.current_state
        assert "炎城" in updated.current_state

    @pytest.mark.asyncio
    async def test_confirm_proposal_with_faction_shift(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        from modules.world.repositories import WorldEntityRepository, RelationshipRepository
        from modules.world.schemas import WorldEntityCreate

        entity_repo = WorldEntityRepository()
        nid = uuid.UUID(hex=novel_id)
        faction = await entity_repo.create(
            db_session, nid,
            WorldEntityCreate(entity_type="faction", name="血狼帮", status="canonical"),
        )
        loc = await entity_repo.create(
            db_session, nid,
            WorldEntityCreate(entity_type="location", name="炎城", status="canonical"),
        )

        proposal_repo = MemoryProposalRepository()
        proposal = await proposal_repo.create(
            db_session,
            nid,
            proposal_type="create_memory",
            payload={
                "memory_type": "chapter_state",
                "summary": "血狼帮驻扎炎城",
                "chapter_index": 5,
                "geo_mutations": {
                    "character_shifts": [],
                    "faction_shifts": [
                        {
                            "faction_name": "血狼帮",
                            "target_location_name": "炎城",
                            "new_relation": "stationed_at",
                            "description": "血狼帮驻扎在炎城",
                        }
                    ],
                },
            },
            chapter_index=5,
        )

        service = MemoryService()
        result = await service.confirm_memory_proposal(
            db_session, str(proposal.id), novel_id,
        )
        assert result.summary == "血狼帮驻扎炎城"

        rel_repo = RelationshipRepository()
        rels, total = await rel_repo.get_by_novel(db_session, nid)
        assert total >= 1
        matched = [r for r in rels if r.source_id == str(faction.id) and r.target_id == str(loc.id)]
        assert len(matched) == 1
        assert matched[0].relation_type == "stationed_at"

    @pytest.mark.asyncio
    async def test_confirm_proposal_character_not_found_skipped(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)

        proposal_repo = MemoryProposalRepository()
        proposal = await proposal_repo.create(
            db_session,
            nid,
            proposal_type="create_memory",
            payload={
                "memory_type": "chapter_state",
                "summary": "不存在的角色位移",
                "chapter_index": 2,
                "geo_mutations": {
                    "character_shifts": [
                        {
                            "character_name": "不存在的角色",
                            "destination_location_name": "不存在的地点",
                            "movement_type": "步行",
                        }
                    ],
                    "faction_shifts": [],
                },
            },
            chapter_index=2,
        )

        service = MemoryService()
        result = await service.confirm_memory_proposal(
            db_session, str(proposal.id), novel_id,
        )
        assert result.summary == "不存在的角色位移"
        assert result.memory_type == "chapter_state"

    @pytest.mark.asyncio
    async def test_confirm_proposal_chapter_involved_merged(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        from modules.character.repositories import CharacterRepository
        from modules.character.schemas import CharacterCreate
        from modules.world.repositories import WorldEntityRepository
        from modules.world.schemas import WorldEntityCreate
        from modules.outline.repositories import ChapterCardRepository
        from modules.outline.schemas import ChapterCardCreate

        char_repo = CharacterRepository()
        char = await char_repo.create(
            db_session,
            CharacterCreate(novel_id=novel_id, name="林动"),
        )

        entity_repo = WorldEntityRepository()
        nid = uuid.UUID(hex=novel_id)
        faction = await entity_repo.create(
            db_session, nid,
            WorldEntityCreate(entity_type="faction", name="血狼帮", status="canonical"),
        )
        loc = await entity_repo.create(
            db_session, nid,
            WorldEntityCreate(entity_type="location", name="炎城", status="canonical"),
        )

        chapter_repo = ChapterCardRepository()
        card = await chapter_repo.create(
            db_session, nid,
            ChapterCardCreate(
                chapter_index=7,
                chapter_goal="目标",
                main_conflict="冲突",
                involved_character_ids=[],
                involved_entity_ids=[],
            ),
        )

        proposal_repo = MemoryProposalRepository()
        proposal = await proposal_repo.create(
            db_session,
            nid,
            proposal_type="create_memory",
            payload={
                "memory_type": "chapter_state",
                "summary": "林动抵达炎城，血狼帮驻扎",
                "chapter_index": 7,
                "geo_mutations": {
                    "character_shifts": [
                        {
                            "character_name": "林动",
                            "destination_location_name": "炎城",
                            "movement_type": "御剑飞行",
                        }
                    ],
                    "faction_shifts": [
                        {
                            "faction_name": "血狼帮",
                            "target_location_name": "炎城",
                            "new_relation": "stationed_at",
                            "description": "血狼帮驻扎炎城",
                        }
                    ],
                },
            },
            chapter_index=7,
        )

        service = MemoryService()
        result = await service.confirm_memory_proposal(
            db_session, str(proposal.id), novel_id,
        )
        assert result.summary == "林动抵达炎城，血狼帮驻扎"

        updated_card = await chapter_repo.get(db_session, card.id)
        assert updated_card is not None
        assert str(char.id) in updated_card.involved_character_ids
        assert str(faction.id) in updated_card.involved_entity_ids
        assert str(loc.id) in updated_card.involved_entity_ids
