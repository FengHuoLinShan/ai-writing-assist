"""
CharacterKnowledge 新等级（restricted / misunderstood）行为测试。

覆盖：
- Schema 校验：misunderstood/false_belief 必须提供 misconception
- API 行为：创建 misunderstood 无 misconception 返回 422，创建 restricted 成功
- CharacterService.filter_context_by_character_knowledge 的各级行为
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import CharacterKnowledge
from modules.world.schemas import (
    CharacterKnowledgeCreate,
    CharacterKnowledgeUpdate,
)
from modules.world.services.character_service import CharacterService


def _make_knowledge(**kwargs: object) -> CharacterKnowledge:
    defaults = {
        "id": uuid.uuid4(),
        "novel_id": uuid.uuid4(),
        "character_id": uuid.uuid4(),
        "target_type": "entity",
        "target_id": uuid.uuid4(),
        "knowledge_level": "partial",
        "known_content": None,
        "misconception": None,
        "source_chapter_index": None,
        "source_memory_id": None,
        "status": "canonical",
    }
    defaults.update(kwargs)
    return CharacterKnowledge(**defaults)


# ============================================================
# Schema 校验
# ============================================================


class TestCharacterKnowledgeSchemaValidation:
    def test_create_misunderstood_without_misconception_raises_422(self) -> None:
        with pytest.raises(ValidationError):
            CharacterKnowledgeCreate(
                character_id=str(uuid.uuid4()),
                target_type="entity",
                target_id=str(uuid.uuid4()),
                knowledge_level="misunderstood",
            )

    def test_create_restricted_knowledge_succeeds(self) -> None:
        data = CharacterKnowledgeCreate(
            character_id=str(uuid.uuid4()),
            target_type="entity",
            target_id=str(uuid.uuid4()),
            knowledge_level="restricted",
            known_content="仅限角色知道的公开信息",
        )
        assert data.knowledge_level == "restricted"
        assert data.known_content == "仅限角色知道的公开信息"

    def test_update_false_belief_without_misconception_raises_422(self) -> None:
        with pytest.raises(ValidationError):
            CharacterKnowledgeUpdate(knowledge_level="false_belief")

    def test_update_misunderstood_without_misconception_raises_422(self) -> None:
        with pytest.raises(ValidationError):
            CharacterKnowledgeUpdate(knowledge_level="misunderstood")


# ============================================================
# API 行为
# ============================================================


@pytest.mark.asyncio
class TestCharacterKnowledgeApiLevels:
    async def test_api_create_misunderstood_without_misconception_returns_422(
        self,
        async_client,
        db_session: AsyncSession,
    ) -> None:
        project_resp = await async_client.post(
            "/api/projects",
            json={
                "title": "知识边界测试",
                "genre": "奇幻",
                "tone": "正剧",
                "language": "zh",
            },
        )
        assert project_resp.status_code == 201
        novel_id = project_resp.json()["id"]

        entity_resp = await async_client.post(
            f"/api/world/entities?novel_id={novel_id}",
            json={
                "entity_type": "faction",
                "name": "暗影组织",
                "status": "canonical",
            },
        )
        assert entity_resp.status_code == 201
        entity_id = entity_resp.json()["id"]

        char_resp = await async_client.post(
            f"/api/world/characters?novel_id={novel_id}",
            json={"entity_id": entity_id, "name": "POV角色"},
        )
        assert char_resp.status_code == 201
        character_id = char_resp.json()["entity_id"]

        resp = await async_client.post(
            f"/api/world/characters/{character_id}/knowledge?novel_id={novel_id}",
            json={
                "character_id": character_id,
                "target_type": "entity",
                "target_id": entity_id,
                "knowledge_level": "misunderstood",
                "known_content": "一个神秘组织",
            },
        )
        assert resp.status_code == 422

    async def test_api_create_restricted_knowledge_succeeds(
        self,
        async_client,
        db_session: AsyncSession,
    ) -> None:
        project_resp = await async_client.post(
            "/api/projects",
            json={
                "title": "知识边界测试 restricted",
                "genre": "奇幻",
                "tone": "正剧",
                "language": "zh",
            },
        )
        assert project_resp.status_code == 201
        novel_id = project_resp.json()["id"]

        entity_resp = await async_client.post(
            f"/api/world/entities?novel_id={novel_id}",
            json={
                "entity_type": "item",
                "name": "禁书",
                "status": "canonical",
            },
        )
        assert entity_resp.status_code == 201
        entity_id = entity_resp.json()["id"]

        char_resp = await async_client.post(
            f"/api/world/characters?novel_id={novel_id}",
            json={"entity_id": entity_id, "name": "守护者"},
        )
        assert char_resp.status_code == 201
        character_id = char_resp.json()["entity_id"]

        resp = await async_client.post(
            f"/api/world/characters/{character_id}/knowledge?novel_id={novel_id}",
            json={
                "character_id": character_id,
                "target_type": "entity",
                "target_id": entity_id,
                "knowledge_level": "restricted",
                "known_content": "角色只知道这是一本古书",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["knowledge_level"] == "restricted"


# ============================================================
# CharacterService 过滤行为
# ============================================================


@pytest.mark.asyncio
class TestCharacterServiceFilterContextByKnowledgeLevel:
    async def test_filter_unknown_removes_item(self, db_session: AsyncSession) -> None:
        svc = CharacterService()
        nid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        tid = str(uuid.uuid4())

        kn = _make_knowledge(
            novel_id=uuid.UUID(nid),
            character_id=uuid.UUID(cid),
            target_id=uuid.UUID(tid),
            target_type="entity",
            knowledge_level="unknown",
        )
        svc._knowledge_repo = AsyncMock()
        svc._knowledge_repo.get_by_target.return_value = [kn]

        context_items = [
            {
                "target_type": "entity",
                "target_id": tid,
                "content": "secret",
                "hidden_truth": "truth",
            },
        ]

        filtered, removed, replaced = await svc.filter_context_by_character_knowledge(
            db_session, nid, cid, context_items
        )

        assert filtered == []
        assert removed == 1
        assert replaced == 0

    async def test_filter_restricted_redacts_hidden_truth_and_uses_known_content(
        self, db_session: AsyncSession
    ) -> None:
        svc = CharacterService()
        nid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        tid = str(uuid.uuid4())

        kn = _make_knowledge(
            novel_id=uuid.UUID(nid),
            character_id=uuid.UUID(cid),
            target_id=uuid.UUID(tid),
            target_type="entity",
            knowledge_level="restricted",
            known_content="角色视角的有限信息",
        )
        svc._knowledge_repo = AsyncMock()
        svc._knowledge_repo.get_by_target.return_value = [kn]

        context_items = [
            {
                "target_type": "entity",
                "target_id": tid,
                "content": "完整内容",
                "summary": "完整摘要",
                "hidden_truth": "真实隐藏真相",
            },
        ]

        filtered, removed, replaced = await svc.filter_context_by_character_knowledge(
            db_session, nid, cid, context_items
        )

        assert len(filtered) == 1
        assert removed == 0
        assert replaced == 0
        assert "hidden_truth" not in filtered[0]
        assert filtered[0]["content"] == "角色视角的有限信息"
        assert filtered[0]["summary"] == "角色视角的有限信息"
        assert filtered[0]["knowledge_level"] == "restricted"

    async def test_filter_misunderstood_replaces_content_and_redacts_hidden_truth(
        self, db_session: AsyncSession
    ) -> None:
        svc = CharacterService()
        nid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        tid = str(uuid.uuid4())

        kn = _make_knowledge(
            novel_id=uuid.UUID(nid),
            character_id=uuid.UUID(cid),
            target_id=uuid.UUID(tid),
            target_type="entity",
            knowledge_level="misunderstood",
            known_content="一个神秘组织",
            misconception="错误认知：这是正义组织",
        )
        svc._knowledge_repo = AsyncMock()
        svc._knowledge_repo.get_by_target.return_value = [kn]

        context_items = [
            {
                "target_type": "entity",
                "target_id": tid,
                "content": "真实内容",
                "summary": "真实摘要",
                "hidden_truth": "真实隐藏真相",
            },
        ]

        filtered, removed, replaced = await svc.filter_context_by_character_knowledge(
            db_session, nid, cid, context_items
        )

        assert len(filtered) == 1
        assert removed == 0
        assert replaced == 1
        assert "hidden_truth" not in filtered[0]
        assert filtered[0]["content"] == "错误认知：这是正义组织"
        assert filtered[0]["is_misconception"] is True
        assert filtered[0]["knowledge_level"] == "misunderstood"

    async def test_filter_partial_appends_known_content_without_redacting_hidden_truth(
        self, db_session: AsyncSession
    ) -> None:
        svc = CharacterService()
        nid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        tid = str(uuid.uuid4())

        kn = _make_knowledge(
            novel_id=uuid.UUID(nid),
            character_id=uuid.UUID(cid),
            target_id=uuid.UUID(tid),
            target_type="entity",
            knowledge_level="partial",
            known_content="角色听说过的版本",
        )
        svc._knowledge_repo = AsyncMock()
        svc._knowledge_repo.get_by_target.return_value = [kn]

        context_items = [
            {
                "target_type": "entity",
                "target_id": tid,
                "content": "正史内容",
                "summary": "正史摘要",
                "hidden_truth": "隐藏真相应保留",
            },
        ]

        filtered, removed, replaced = await svc.filter_context_by_character_knowledge(
            db_session, nid, cid, context_items
        )

        assert len(filtered) == 1
        assert removed == 0
        assert replaced == 0
        assert filtered[0]["hidden_truth"] == "隐藏真相应保留"
        assert filtered[0]["content"] == "正史内容"
        assert filtered[0]["summary"] == "正史摘要"
        assert filtered[0]["character_known_content"] == "角色听说过的版本"
        assert filtered[0]["knowledge_level"] == "partial"

    async def test_filter_rumor_appends_known_content_without_redacting_hidden_truth(
        self, db_session: AsyncSession
    ) -> None:
        svc = CharacterService()
        nid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        tid = str(uuid.uuid4())

        kn = _make_knowledge(
            novel_id=uuid.UUID(nid),
            character_id=uuid.UUID(cid),
            target_id=uuid.UUID(tid),
            target_type="entity",
            knowledge_level="rumor",
            known_content="街头传闻",
        )
        svc._knowledge_repo = AsyncMock()
        svc._knowledge_repo.get_by_target.return_value = [kn]

        context_items = [
            {
                "target_type": "entity",
                "target_id": tid,
                "content": "正史内容",
                "hidden_truth": "隐藏真相应保留",
            },
        ]

        filtered, removed, replaced = await svc.filter_context_by_character_knowledge(
            db_session, nid, cid, context_items
        )

        assert len(filtered) == 1
        assert removed == 0
        assert replaced == 0
        assert filtered[0]["hidden_truth"] == "隐藏真相应保留"
        assert filtered[0]["content"] == "正史内容"
        assert filtered[0]["character_known_content"] == "街头传闻"
        assert filtered[0]["knowledge_level"] == "rumor"
