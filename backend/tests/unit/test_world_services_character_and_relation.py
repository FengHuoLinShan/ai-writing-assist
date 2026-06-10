"""
Unit tests for world module internal services.

Covers:
- CharacterService
- CharacterKnowledgeService
- EntityRelationService

All DB access is mocked via AsyncMock / MagicMock.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import Character, CharacterKnowledge, EntityRelation
from modules.world.schemas import (
    CharacterContextBundle,
    CharacterContextItem,
    CharacterCreate,
    CharacterKnowledgeContext,
    CharacterKnowledgeCreate,
    CharacterKnowledgeListResponse,
    CharacterKnowledgeResponse,
    CharacterKnowledgeUpdate,
    CharacterResponse,
    CharacterUpdate,
    EntityRelationCreate,
    EntityRelationListResponse,
    EntityRelationResponse,
    EntityRelationUpdate,
    WorldEntityContext,
)
from modules.world.services.character_knowledge_service import (
    CharacterKnowledgeService,
)
from modules.world.services.character_service import CharacterService
from modules.world.services.entity_relation_service import EntityRelationService

pytestmark = [pytest.mark.asyncio]


# ============================================================
# Helpers
# ============================================================


def _make_character(**kwargs) -> Character:
    defaults = {
        "entity_id": uuid.uuid4(),
        "novel_id": uuid.uuid4(),
        "name": "Test Character",
        "aliases": [],
        "role": "protagonist",
        "appearance": None,
        "personality": None,
        "desire": None,
        "fear": None,
        "secret": None,
        "weakness": None,
        "current_goal": None,
        "current_state": None,
        "current_emotion": None,
        "stance": None,
        "voice_style": None,
        "behavior_rules": [],
        "relationship_summary": None,
        "meta": {},
        "status": "canonical",
    }
    defaults.update(kwargs)
    return Character(**defaults)


def _make_knowledge(**kwargs) -> CharacterKnowledge:
    defaults = {
        "id": uuid.uuid4(),
        "novel_id": uuid.uuid4(),
        "character_id": uuid.uuid4(),
        "target_type": "character",
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


def _make_relation(**kwargs) -> EntityRelation:
    defaults = {
        "id": uuid.uuid4(),
        "novel_id": uuid.uuid4(),
        "source_id": uuid.uuid4(),
        "target_id": uuid.uuid4(),
        "relation_type": "friend",
        "description": None,
        "strength": 0.5,
        "source_chapter_id": None,
        "caused_by_event_id": None,
        "quote": None,
        "status": "canonical",
    }
    defaults.update(kwargs)
    return EntityRelation(**defaults)


# ============================================================
# CharacterService
# ============================================================


class TestCharacterServiceList:
    async def test_list_returns_items_and_total(self, db_session: AsyncSession):
        """Happy path: list returns (items, total) tuple."""
        # Arrange
        svc = CharacterService()
        novel_id = str(uuid.uuid4())
        char = _make_character()
        svc.repo = AsyncMock()
        svc.repo.get_by_novel.return_value = ([char], 1)

        # Act
        items, total = await svc.list(db_session, novel_id)

        # Assert
        assert total == 1
        assert len(items) == 1
        assert isinstance(items[0], CharacterResponse)
        svc.repo.get_by_novel.assert_awaited_once()

    async def test_list_clamps_limit_to_max_page_size(self, db_session: AsyncSession):
        """Boundary: limit > MAX_PAGE_SIZE is clamped."""
        # Arrange
        svc = CharacterService()
        novel_id = str(uuid.uuid4())
        svc.repo = AsyncMock()
        svc.repo.get_by_novel.return_value = ([], 0)

        # Act
        await svc.list(db_session, novel_id, skip=0, limit=9999)

        # Assert
        _, kwargs = svc.repo.get_by_novel.await_args
        assert kwargs["limit"] <= 500

    async def test_list_with_empty_result_returns_zero_total(self, db_session: AsyncSession):
        """Boundary: empty repo result returns ([], 0)."""
        # Arrange
        svc = CharacterService()
        svc.repo = AsyncMock()
        svc.repo.get_by_novel.return_value = ([], 0)

        # Act
        items, total = await svc.list(db_session, str(uuid.uuid4()))

        # Assert
        assert items == []
        assert total == 0


class TestCharacterServiceUpdateCharacterState:
    async def test_update_character_state_with_all_fields(self, db_session: AsyncSession):
        """Happy path: updates state, emotion, goal."""
        # Arrange
        svc = CharacterService()
        cid = str(uuid.uuid4())
        nid = str(uuid.uuid4())
        char = _make_character(entity_id=uuid.UUID(cid), novel_id=uuid.UUID(nid))
        svc.repo = AsyncMock()
        svc.repo.get.return_value = char
        svc.repo.update.return_value = char

        # Act
        result = await svc.update_character_state(
            db_session, cid, current_state="injured", current_emotion="angry",
            current_goal="revenge", novel_id=nid,
        )

        # Assert
        assert isinstance(result, CharacterResponse)
        svc.repo.update.assert_awaited_once()
        call_data = svc.repo.update.await_args[0][2]
        assert call_data.current_state == "injured"
        assert call_data.current_emotion == "angry"
        assert call_data.current_goal == "revenge"

    async def test_update_character_state_partial_fields(self, db_session: AsyncSession):
        """Boundary: only provided fields are updated."""
        # Arrange
        svc = CharacterService()
        cid = str(uuid.uuid4())
        nid = str(uuid.uuid4())
        char = _make_character(entity_id=uuid.UUID(cid), novel_id=uuid.UUID(nid))
        svc.repo = AsyncMock()
        svc.repo.get.return_value = char
        svc.repo.update.return_value = char

        # Act
        result = await svc.update_character_state(
            db_session, cid, current_state="tired", novel_id=nid,
        )

        # Assert
        call_data = svc.repo.update.await_args[0][2]
        assert call_data.current_state == "tired"
        assert call_data.current_emotion is None
        assert call_data.current_goal is None

    async def test_update_character_state_not_found_raises_404(self, db_session: AsyncSession):
        """Error: character not found raises 404."""
        # Arrange
        svc = CharacterService()
        cid = str(uuid.uuid4())
        nid = str(uuid.uuid4())
        svc.repo = AsyncMock()
        svc.repo.get.return_value = None

        # Act / Assert
        with pytest.raises(HTTPException) as exc_info:
            await svc.update_character_state(
                db_session, cid, current_state="x", novel_id=nid,
            )
        assert exc_info.value.status_code == 404

    async def test_update_character_state_wrong_novel_raises_404(self, db_session: AsyncSession):
        """Error: character belongs to different novel raises 404."""
        # Arrange
        svc = CharacterService()
        cid = str(uuid.uuid4())
        nid = str(uuid.uuid4())
        char = _make_character(entity_id=uuid.UUID(cid), novel_id=uuid.uuid4())
        svc.repo = AsyncMock()
        svc.repo.get.return_value = char

        # Act / Assert
        with pytest.raises(HTTPException) as exc_info:
            await svc.update_character_state(
                db_session, cid, current_state="x", novel_id=nid,
            )
        assert exc_info.value.status_code == 404

    async def test_update_character_state_repo_returns_none_raises_404(self, db_session: AsyncSession):
        """Error: repo.update returns None raises 404."""
        # Arrange
        svc = CharacterService()
        cid = str(uuid.uuid4())
        nid = str(uuid.uuid4())
        char = _make_character(entity_id=uuid.UUID(cid), novel_id=uuid.UUID(nid))
        svc.repo = AsyncMock()
        svc.repo.get.return_value = char
        svc.repo.update.return_value = None

        # Act / Assert
        with pytest.raises(HTTPException) as exc_info:
            await svc.update_character_state(
                db_session, cid, current_state="x", novel_id=nid,
            )
        assert exc_info.value.status_code == 404


class TestCharacterServiceGetCharactersContext:
    async def test_get_characters_context_author_safe_excludes_secret(self, db_session: AsyncSession):
        """Happy path: author_safe mode does not include secret."""
        # Arrange
        svc = CharacterService()
        nid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        char = _make_character(
            entity_id=uuid.UUID(cid),
            novel_id=uuid.UUID(nid),
            name="Hero",
            secret="Dark secret",
        )
        svc.repo = AsyncMock()
        svc.repo.get_by_ids.return_value = [char]

        # Act
        bundle = await svc.get_characters_context(db_session, nid, [cid])

        # Assert
        assert isinstance(bundle, CharacterContextBundle)
        assert bundle.total == 1
        assert bundle.reveal_mode == "author_safe"
        assert bundle.characters[0].secret is None

    async def test_get_characters_context_author_only_includes_secret(self, db_session: AsyncSession):
        """Boundary: author_only reveal_mode includes secret."""
        # Arrange
        svc = CharacterService()
        nid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        char = _make_character(
            entity_id=uuid.UUID(cid),
            novel_id=uuid.UUID(nid),
            name="Hero",
            secret="Dark secret",
        )
        svc.repo = AsyncMock()
        svc.repo.get_by_ids.return_value = [char]

        # Act
        bundle = await svc.get_characters_context(
            db_session, nid, [cid], reveal_mode="author_only",
        )

        # Assert
        assert bundle.characters[0].secret == "Dark secret"

    async def test_get_characters_context_empty_ids_returns_empty_bundle(self, db_session: AsyncSession):
        """Boundary: empty character_ids returns empty bundle."""
        # Arrange
        svc = CharacterService()
        svc.repo = AsyncMock()
        svc.repo.get_by_ids.return_value = []

        # Act
        bundle = await svc.get_characters_context(db_session, str(uuid.uuid4()), [])

        # Assert
        assert bundle.characters == []
        assert bundle.total == 0


class TestCharacterServiceGetCharacterKnowledgeContext:
    async def test_get_character_knowledge_context_with_target_ids(self, db_session: AsyncSession):
        """Happy path: returns knowledge context with target_ids filter."""
        # Arrange
        svc = CharacterService()
        nid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        kn = _make_knowledge(
            novel_id=uuid.UUID(nid),
            character_id=uuid.UUID(cid),
            target_id=uuid.UUID(tid),
            target_type="character",
            knowledge_level="full",
            known_content="Knows everything",
        )
        svc._knowledge_repo = AsyncMock()
        svc._knowledge_repo.get_by_target.return_value = [kn]

        # Act
        result = await svc.get_character_knowledge_context(
            db_session, nid, cid, target_ids=[tid],
        )

        # Assert
        assert len(result) == 1
        assert isinstance(result[0], CharacterKnowledgeContext)
        assert result[0].knowledge_level == "full"

    async def test_get_character_knowledge_context_none_target_ids(self, db_session: AsyncSession):
        """Boundary: target_ids=None passes None to repo."""
        # Arrange
        svc = CharacterService()
        svc._knowledge_repo = AsyncMock()
        svc._knowledge_repo.get_by_target.return_value = []

        # Act
        result = await svc.get_character_knowledge_context(
            db_session, str(uuid.uuid4()), str(uuid.uuid4()), target_ids=None,
        )

        # Assert
        assert result == []
        _, kwargs = svc._knowledge_repo.get_by_target.await_args
        assert kwargs.get("target_ids") is None


class TestCharacterServiceFilterContextByCharacterKnowledge:
    async def test_filter_removes_unknown_and_missing(self, db_session: AsyncSession):
        """Happy path: unknown / missing knowledge items are removed."""
        # Arrange
        svc = CharacterService()
        nid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        tid_known = str(uuid.uuid4())
        tid_unknown = str(uuid.uuid4())
        tid_missing = str(uuid.uuid4())

        kn_known = _make_knowledge(
            novel_id=uuid.UUID(nid),
            character_id=uuid.UUID(cid),
            target_id=uuid.UUID(tid_known),
            target_type="character",
            knowledge_level="partial",
            known_content="something",
        )
        kn_unknown = _make_knowledge(
            novel_id=uuid.UUID(nid),
            character_id=uuid.UUID(cid),
            target_id=uuid.UUID(tid_unknown),
            target_type="character",
            knowledge_level="unknown",
        )

        svc._knowledge_repo = AsyncMock()
        svc._knowledge_repo.get_by_target.side_effect = [
            [kn_known],   # character target
            [kn_unknown], # event target
            [],           # location target (no knowledge)
        ]

        context_items = [
            {"target_type": "character", "target_id": tid_known, "content": "A"},
            {"target_type": "event", "target_id": tid_unknown, "content": "B"},
            {"target_type": "location", "target_id": tid_missing, "content": "C"},
        ]

        # Act
        filtered, removed, replaced = await svc.filter_context_by_character_knowledge(
            db_session, nid, cid, context_items,
        )

        # Assert
        assert len(filtered) == 1
        assert removed == 2
        assert replaced == 0
        assert filtered[0]["knowledge_level"] == "partial"

    async def test_filter_false_belief_replaces_content(self, db_session: AsyncSession):
        """Boundary: false_belief replaces content with misconception."""
        # Arrange
        svc = CharacterService()
        nid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        kn = _make_knowledge(
            novel_id=uuid.UUID(nid),
            character_id=uuid.UUID(cid),
            target_id=uuid.UUID(tid),
            target_type="character",
            knowledge_level="false_belief",
            known_content="truth",
            misconception="lie",
        )
        svc._knowledge_repo = AsyncMock()
        svc._knowledge_repo.get_by_target.return_value = [kn]

        context_items = [
            {"target_type": "character", "target_id": tid, "content": "original"},
        ]

        # Act
        filtered, removed, replaced = await svc.filter_context_by_character_knowledge(
            db_session, nid, cid, context_items,
        )

        # Assert
        assert len(filtered) == 1
        assert replaced == 1
        assert filtered[0]["content"] == "lie"
        assert filtered[0]["is_misconception"] is True
        assert filtered[0]["original_content"] == "original"

    async def test_filter_false_belief_fallback_to_known_content(self, db_session: AsyncSession):
        """Boundary: false_belief without misconception falls back to known_content."""
        # Arrange
        svc = CharacterService()
        nid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        kn = _make_knowledge(
            novel_id=uuid.UUID(nid),
            character_id=uuid.UUID(cid),
            target_id=uuid.UUID(tid),
            target_type="character",
            knowledge_level="false_belief",
            known_content="truth",
            misconception=None,
        )
        svc._knowledge_repo = AsyncMock()
        svc._knowledge_repo.get_by_target.return_value = [kn]

        context_items = [
            {"target_type": "character", "target_id": tid, "content": "original"},
        ]

        # Act
        filtered, removed, replaced = await svc.filter_context_by_character_knowledge(
            db_session, nid, cid, context_items,
        )

        # Assert
        assert filtered[0]["content"] == "truth"

    async def test_filter_empty_context_items_returns_empty(self, db_session: AsyncSession):
        """Boundary: empty context_items returns ([], 0, 0)."""
        # Arrange
        svc = CharacterService()
        svc._knowledge_repo = AsyncMock()

        # Act
        filtered, removed, replaced = await svc.filter_context_by_character_knowledge(
            db_session, str(uuid.uuid4()), str(uuid.uuid4()), [],
        )

        # Assert
        assert filtered == []
        assert removed == 0
        assert replaced == 0
        svc._knowledge_repo.get_by_target.assert_not_awaited()


class TestCharacterServiceFacadeLeaks:
    async def test_get_id_by_world_entity_found(self, db_session: AsyncSession):
        """Happy path: returns entity_id as str."""
        # Arrange
        svc = CharacterService()
        weid = str(uuid.uuid4())
        char = _make_character(entity_id=uuid.UUID(weid))
        svc.repo = AsyncMock()
        svc.repo.get.return_value = char

        # Act
        result = await svc.get_id_by_world_entity(db_session, str(uuid.uuid4()), weid)

        # Assert
        assert result == weid

    async def test_get_id_by_world_entity_not_found_returns_none(self, db_session: AsyncSession):
        """Boundary: not found returns None."""
        # Arrange
        svc = CharacterService()
        svc.repo = AsyncMock()
        svc.repo.get.return_value = None

        # Act
        result = await svc.get_id_by_world_entity(
            db_session, str(uuid.uuid4()), str(uuid.uuid4()),
        )

        # Assert
        assert result is None

    async def test_find_by_name_found(self, db_session: AsyncSession):
        """Happy path: returns character entity_id."""
        # Arrange
        svc = CharacterService()
        nid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        svc.repo = AsyncMock()
        svc.repo.find_character_by_name.return_value = cid

        # Act
        result = await svc.find_by_name(db_session, nid, "Hero")

        # Assert
        assert result == cid
        svc.repo.find_character_by_name.assert_awaited_once_with(db_session, uuid.UUID(nid), "Hero")

    async def test_find_by_name_not_found_returns_none(self, db_session: AsyncSession):
        """Boundary: not found returns None."""
        # Arrange
        svc = CharacterService()
        svc.repo = AsyncMock()
        svc.repo.find_character_by_name.return_value = None

        # Act
        result = await svc.find_by_name(db_session, str(uuid.uuid4()), "Nobody")

        # Assert
        assert result is None

    async def test_update_location_calls_repo(self, db_session: AsyncSession):
        """Happy path: delegates to repo.update_character_meta_location."""
        # Arrange
        svc = CharacterService()
        cid = str(uuid.uuid4())
        loc_id = str(uuid.uuid4())
        svc.repo = AsyncMock()

        # Act
        await svc.update_location(db_session, str(uuid.uuid4()), cid, loc_id, "forest", 3)

        # Assert
        svc.repo.update_character_meta_location.assert_awaited_once()

    async def test_get_characters_at_location_delegates_to_repo(self, db_session: AsyncSession):
        """Happy path: delegates to repo.find_characters_by_location."""
        # Arrange
        svc = CharacterService()
        nid = str(uuid.uuid4())
        loc_id = str(uuid.uuid4())
        expected = [{"id": str(uuid.uuid4()), "name": "A"}]
        svc.repo = AsyncMock()
        svc.repo.find_characters_by_location.return_value = expected

        # Act
        result = await svc.get_characters_at_location(db_session, nid, loc_id)

        # Assert
        assert result == expected

    async def test_get_location_id_found(self, db_session: AsyncSession):
        """Happy path: returns location_id string."""
        # Arrange
        svc = CharacterService()
        cid = str(uuid.uuid4())
        loc_id = str(uuid.uuid4())
        char = _make_character(entity_id=uuid.UUID(cid), meta={"location_id": loc_id})
        svc.repo = AsyncMock()
        svc.repo.get_character_location_id.return_value = loc_id

        # Act
        result = await svc.get_location_id(db_session, str(uuid.uuid4()), cid)

        # Assert
        assert result == loc_id

    async def test_get_location_id_not_found_returns_none(self, db_session: AsyncSession):
        """Boundary: returns None when repo returns None."""
        # Arrange
        svc = CharacterService()
        svc.repo = AsyncMock()
        svc.repo.get_character_location_id.return_value = None

        # Act
        result = await svc.get_location_id(
            db_session, str(uuid.uuid4()), str(uuid.uuid4()),
        )

        # Assert
        assert result is None


class TestCharacterServiceInheritedVerbs:
    async def test_get_found_returns_response(self, db_session: AsyncSession):
        """Base get: found and novel match returns response."""
        # Arrange
        svc = CharacterService()
        nid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        char = _make_character(entity_id=uuid.UUID(cid), novel_id=uuid.UUID(nid))
        svc.repo = AsyncMock()
        svc.repo.get.return_value = char

        # Act
        result = await svc.get(db_session, cid, novel_id=nid)

        # Assert
        assert isinstance(result, CharacterResponse)

    async def test_get_wrong_novel_raises_404(self, db_session: AsyncSession):
        """Base get: novel mismatch raises 404."""
        # Arrange
        svc = CharacterService()
        nid = str(uuid.uuid4())
        char = _make_character(novel_id=uuid.uuid4())
        svc.repo = AsyncMock()
        svc.repo.get.return_value = char

        # Act / Assert
        with pytest.raises(HTTPException) as exc_info:
            await svc.get(db_session, str(uuid.uuid4()), novel_id=nid)
        assert exc_info.value.status_code == 404

    async def test_create_returns_response(self, db_session: AsyncSession):
        """Base create: returns validated response."""
        # Arrange
        svc = CharacterService()
        nid = str(uuid.uuid4())
        char = _make_character(novel_id=uuid.UUID(nid))
        svc.repo = AsyncMock()
        svc.repo.create.return_value = char
        data = CharacterCreate(entity_id=str(uuid.uuid4()), name="New")

        # Act
        result = await svc.create(db_session, nid, data)

        # Assert
        assert isinstance(result, CharacterResponse)

    async def test_delete_found_deletes(self, db_session: AsyncSession):
        """Base delete: found character is deleted."""
        # Arrange
        svc = CharacterService()
        nid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        char = _make_character(entity_id=uuid.UUID(cid), novel_id=uuid.UUID(nid))
        svc.repo = AsyncMock()
        svc.repo.get.return_value = char
        svc.repo.delete.return_value = True

        # Act
        await svc.delete(db_session, cid, novel_id=nid)

        # Assert
        svc.repo.delete.assert_awaited_once()


# ============================================================
# CharacterKnowledgeService
# ============================================================


class TestCharacterKnowledgeServiceCreate:
    async def test_create_when_character_belongs_to_novel(self, db_session: AsyncSession):
        """Happy path: creates knowledge when character belongs to novel."""
        # Arrange
        svc = CharacterKnowledgeService()
        nid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        char = _make_character(entity_id=uuid.UUID(cid), novel_id=uuid.UUID(nid))
        svc._character_repo = AsyncMock()
        svc._character_repo.get.return_value = char
        svc.repo = AsyncMock()
        kn = _make_knowledge(novel_id=uuid.UUID(nid), character_id=uuid.UUID(cid))
        svc.repo.create.return_value = kn

        data = CharacterKnowledgeCreate(
            character_id=cid,
            target_type="character",
            target_id=str(uuid.uuid4()),
            knowledge_level="full",
        )

        # Act
        result = await svc.create(db_session, nid, data)

        # Assert
        assert isinstance(result, CharacterKnowledgeResponse)
        svc.repo.create.assert_awaited_once()

    async def test_create_character_not_found_raises_404(self, db_session: AsyncSession):
        """Error: character not found raises 404."""
        # Arrange
        svc = CharacterKnowledgeService()
        svc._character_repo = AsyncMock()
        svc._character_repo.get.return_value = None
        svc.repo = AsyncMock()

        data = CharacterKnowledgeCreate(
            character_id=str(uuid.uuid4()),
            target_type="character",
            target_id=str(uuid.uuid4()),
            knowledge_level="full",
        )

        # Act / Assert
        with pytest.raises(HTTPException) as exc_info:
            await svc.create(db_session, str(uuid.uuid4()), data)
        assert exc_info.value.status_code == 404
        assert "Character not found" in exc_info.value.detail

    async def test_create_character_wrong_novel_raises_404(self, db_session: AsyncSession):
        """Error: character belongs to different novel raises 404."""
        # Arrange
        svc = CharacterKnowledgeService()
        char = _make_character(novel_id=uuid.uuid4())
        svc._character_repo = AsyncMock()
        svc._character_repo.get.return_value = char
        svc.repo = AsyncMock()

        data = CharacterKnowledgeCreate(
            character_id=str(uuid.uuid4()),
            target_type="character",
            target_id=str(uuid.uuid4()),
            knowledge_level="full",
        )

        # Act / Assert
        with pytest.raises(HTTPException) as exc_info:
            await svc.create(db_session, str(uuid.uuid4()), data)
        assert exc_info.value.status_code == 404


class TestCharacterKnowledgeServiceList:
    async def test_list_by_character_returns_list_response(self, db_session: AsyncSession):
        """Happy path: list by character_id returns ListResponse."""
        # Arrange
        svc = CharacterKnowledgeService()
        nid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        kn = _make_knowledge(novel_id=uuid.UUID(nid), character_id=uuid.UUID(cid))
        svc.repo = AsyncMock()
        svc.repo.get_by_character.return_value = ([kn], 1)

        # Act
        result = await svc.list(db_session, nid, cid)

        # Assert
        assert isinstance(result, CharacterKnowledgeListResponse)
        assert result.total == 1
        assert len(result.items) == 1

    async def test_list_clamps_limit(self, db_session: AsyncSession):
        """Boundary: limit > MAX_PAGE_SIZE is clamped."""
        # Arrange
        svc = CharacterKnowledgeService()
        svc.repo = AsyncMock()
        svc.repo.get_by_character.return_value = ([], 0)

        # Act
        await svc.list(db_session, str(uuid.uuid4()), str(uuid.uuid4()), limit=9999)

        # Assert
        _, kwargs = svc.repo.get_by_character.await_args
        assert kwargs["limit"] <= 500


class TestCharacterKnowledgeServiceInheritedVerbs:
    async def test_get_found_returns_response(self, db_session: AsyncSession):
        """Base get: found returns response."""
        # Arrange
        svc = CharacterKnowledgeService()
        nid = str(uuid.uuid4())
        kid = str(uuid.uuid4())
        kn = _make_knowledge(id=uuid.UUID(kid), novel_id=uuid.UUID(nid))
        svc.repo = AsyncMock()
        svc.repo.get.return_value = kn

        # Act
        result = await svc.get(db_session, kid, novel_id=nid)

        # Assert
        assert isinstance(result, CharacterKnowledgeResponse)

    async def test_update_returns_response(self, db_session: AsyncSession):
        """Base update: returns validated response."""
        # Arrange
        svc = CharacterKnowledgeService()
        nid = str(uuid.uuid4())
        kid = str(uuid.uuid4())
        kn = _make_knowledge(id=uuid.UUID(kid), novel_id=uuid.UUID(nid))
        svc.repo = AsyncMock()
        svc.repo.get.return_value = kn
        svc.repo.update.return_value = kn

        # Act
        result = await svc.update(
            db_session, kid, CharacterKnowledgeUpdate(knowledge_level="full"), novel_id=nid,
        )

        # Assert
        assert isinstance(result, CharacterKnowledgeResponse)

    async def test_delete_found(self, db_session: AsyncSession):
        """Base delete: found is deleted."""
        # Arrange
        svc = CharacterKnowledgeService()
        nid = str(uuid.uuid4())
        kid = str(uuid.uuid4())
        kn = _make_knowledge(id=uuid.UUID(kid), novel_id=uuid.UUID(nid))
        svc.repo = AsyncMock()
        svc.repo.get.return_value = kn
        svc.repo.delete.return_value = True

        # Act
        await svc.delete(db_session, kid, novel_id=nid)

        # Assert
        svc.repo.delete.assert_awaited_once()


# ============================================================
# EntityRelationService
# ============================================================


class TestEntityRelationServiceGetTraceableRelations:
    async def test_get_traceable_relations_returns_list_response(self, db_session: AsyncSession):
        """Happy path: returns EntityRelationListResponse."""
        # Arrange
        svc = EntityRelationService()
        nid = str(uuid.uuid4())
        chid = str(uuid.uuid4())
        rel = _make_relation(novel_id=uuid.UUID(nid), source_chapter_id=uuid.UUID(chid))
        svc.repo = AsyncMock()
        svc.repo.get_traceable_relations.return_value = [rel]

        # Act
        result = await svc.get_traceable_relations(db_session, nid, chid)

        # Assert
        assert isinstance(result, EntityRelationListResponse)
        assert result.total == 1

    async def test_get_traceable_relations_empty_returns_zero_total(self, db_session: AsyncSession):
        """Boundary: no relations returns empty list response."""
        # Arrange
        svc = EntityRelationService()
        svc.repo = AsyncMock()
        svc.repo.get_traceable_relations.return_value = []

        # Act
        result = await svc.get_traceable_relations(
            db_session, str(uuid.uuid4()), str(uuid.uuid4()),
        )

        # Assert
        assert result.items == []
        assert result.total == 0


class TestEntityRelationServiceExpandRelated:
    async def test_expand_related_with_related_entities(self, db_session: AsyncSession):
        """Happy path: returns WorldEntityContext list."""
        # Arrange
        svc = EntityRelationService()
        nid = str(uuid.uuid4())
        seed_id = str(uuid.uuid4())
        related_id = uuid.uuid4()
        svc.repo = AsyncMock()
        svc.repo.get_related_entity_ids.return_value = {related_id}

        entity = SimpleNamespace(
            id=related_id,
            entity_type="character",
            name="Related",
            summary=None,
            public_info=None,
            importance=0.5,
            importance_level="normal",
            reveal_level="author_only",
            status="canonical",
        )
        svc._entity_repo = AsyncMock()
        svc._entity_repo.get_by_ids.return_value = [entity]

        # Act
        result = await svc.expand_related(db_session, nid, [seed_id])

        # Assert
        assert len(result) == 1
        assert isinstance(result[0], WorldEntityContext)
        assert result[0].entity_id == str(related_id)

    async def test_expand_related_empty_seed_returns_empty(self, db_session: AsyncSession):
        """Boundary: empty seed_ids returns empty list."""
        # Arrange
        svc = EntityRelationService()

        # Act
        result = await svc.expand_related(db_session, str(uuid.uuid4()), [])

        # Assert
        assert result == []

    async def test_expand_related_no_related_returns_empty(self, db_session: AsyncSession):
        """Boundary: no related entities returns empty list."""
        # Arrange
        svc = EntityRelationService()
        svc.repo = AsyncMock()
        svc.repo.get_related_entity_ids.return_value = set()

        # Act
        result = await svc.expand_related(db_session, str(uuid.uuid4()), [str(uuid.uuid4())])

        # Assert
        assert result == []
        svc._entity_repo = AsyncMock()
        svc._entity_repo.get_by_ids.assert_not_awaited()

    async def test_expand_related_limits_result(self, db_session: AsyncSession):
        """Boundary: result is limited to max limit."""
        # Arrange
        svc = EntityRelationService()
        nid = str(uuid.uuid4())
        svc.repo = AsyncMock()
        svc.repo.get_related_entity_ids.return_value = {uuid.uuid4() for _ in range(10)}

        svc._entity_repo = AsyncMock()
        svc._entity_repo.get_by_ids.return_value = []

        # Act
        await svc.expand_related(db_session, nid, [str(uuid.uuid4())], limit=5)

        # Assert
        args, _ = svc._entity_repo.get_by_ids.await_args
        assert len(args[2]) <= 5


class TestEntityRelationServiceUpsert:
    async def test_upsert_returns_response(self, db_session: AsyncSession):
        """Happy path: upsert returns EntityRelationResponse."""
        # Arrange
        svc = EntityRelationService()
        nid = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        rel = _make_relation(novel_id=uuid.UUID(nid), source_id=uuid.UUID(sid), target_id=uuid.UUID(tid))
        svc.repo = AsyncMock()
        svc.repo.upsert.return_value = rel

        # Act
        result = await svc.upsert(db_session, nid, sid, tid, "friend", description="Best buds")

        # Assert
        assert isinstance(result, EntityRelationResponse)
        svc.repo.upsert.assert_awaited_once_with(
            db_session, uuid.UUID(nid), uuid.UUID(sid), uuid.UUID(tid), "friend", description="Best buds",
        )


class TestEntityRelationServiceInheritedVerbs:
    async def test_get_found_returns_response(self, db_session: AsyncSession):
        """Base get: found and novel match returns response."""
        # Arrange
        svc = EntityRelationService()
        nid = str(uuid.uuid4())
        rid = str(uuid.uuid4())
        rel = _make_relation(id=uuid.UUID(rid), novel_id=uuid.UUID(nid))
        svc.repo = AsyncMock()
        svc.repo.get.return_value = rel

        # Act
        result = await svc.get(db_session, rid, novel_id=nid)

        # Assert
        assert isinstance(result, EntityRelationResponse)

    async def test_get_wrong_novel_raises_404(self, db_session: AsyncSession):
        """Base get: novel mismatch raises 404."""
        # Arrange
        svc = EntityRelationService()
        nid = str(uuid.uuid4())
        rel = _make_relation(novel_id=uuid.uuid4())
        svc.repo = AsyncMock()
        svc.repo.get.return_value = rel

        # Act / Assert
        with pytest.raises(HTTPException) as exc_info:
            await svc.get(db_session, str(uuid.uuid4()), novel_id=nid)
        assert exc_info.value.status_code == 404

    async def test_create_returns_response(self, db_session: AsyncSession):
        """Base create: returns validated response."""
        # Arrange
        svc = EntityRelationService()
        nid = str(uuid.uuid4())
        rel = _make_relation(novel_id=uuid.UUID(nid))
        svc.repo = AsyncMock()
        svc.repo.create.return_value = rel
        data = EntityRelationCreate(
            source_id=str(uuid.uuid4()),
            target_id=str(uuid.uuid4()),
            relation_type="enemy",
        )

        # Act
        result = await svc.create(db_session, nid, data)

        # Assert
        assert isinstance(result, EntityRelationResponse)

    async def test_update_returns_response(self, db_session: AsyncSession):
        """Base update: returns validated response."""
        # Arrange
        svc = EntityRelationService()
        nid = str(uuid.uuid4())
        rid = str(uuid.uuid4())
        rel = _make_relation(id=uuid.UUID(rid), novel_id=uuid.UUID(nid))
        svc.repo = AsyncMock()
        svc.repo.get.return_value = rel
        svc.repo.update.return_value = rel

        # Act
        result = await svc.update(
            db_session, rid, EntityRelationUpdate(description="updated"), novel_id=nid,
        )

        # Assert
        assert isinstance(result, EntityRelationResponse)

    async def test_delete_found(self, db_session: AsyncSession):
        """Base delete: found relation is deleted."""
        # Arrange
        svc = EntityRelationService()
        nid = str(uuid.uuid4())
        rid = str(uuid.uuid4())
        rel = _make_relation(id=uuid.UUID(rid), novel_id=uuid.UUID(nid))
        svc.repo = AsyncMock()
        svc.repo.get.return_value = rel
        svc.repo.delete.return_value = True

        # Act
        await svc.delete(db_session, rid, novel_id=nid)

        # Assert
        svc.repo.delete.assert_awaited_once()
