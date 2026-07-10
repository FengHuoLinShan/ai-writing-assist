"""Unit tests for EntityExtractionService"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import pytest_asyncio
from pydantic import BaseModel

from core.errors import ValidationError as DomainValidationError
from modules.world.schemas import DuplicateSuggestionResult, WorldContextBundle
from modules.world.services.core.extraction_service import (
    EntityExtractionService,
)

pytestmark = [pytest.mark.asyncio]


async def test_extraction_service_has_no_direct_http_exception_dependency() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    source = (
        backend_root / "modules/world/services/core/extraction_service.py"
    ).read_text()

    assert "from fastapi import HTTPException" not in source
    assert "raise HTTPException" not in source


# ---------------------------------------------------------------
# Test doubles — mirror the inline schemas from extraction_service.py
# ---------------------------------------------------------------


class _TestEntity(BaseModel):
    name: str = ""
    entity_type: str = "character"
    summary: str = ""
    public_info: str = ""
    hidden_truth: str = ""
    importance: float = 0.5
    suggested_action: str = "create_new"
    suggested_existing_entity_name: str | None = None
    candidate_reason: str = ""
    confidence: float = 0.8
    source_chapter: int | None = None
    aliases: list[dict] | None = None


class _TestOutput(BaseModel):
    entities: list[_TestEntity] = []


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------

TEST_NOVEL_ID = "00000000-0000-0000-0000-000000000001"


@pytest_asyncio.fixture
def chapters():
    """Single chapter draft data."""
    return [{"chapter_index": 1, "title": "第一章", "content": "测试正文"}]


@pytest_asyncio.fixture
def multi_chapters():
    """Three chapters for context accumulation test."""
    return [
        {"chapter_index": i, "title": f"第{i}章", "content": f"正文{i}"}
        for i in range(1, 4)
    ]


@pytest.fixture(autouse=True)
def project_context_without_profile(monkeypatch):
    """Keep existing extraction tests on the legacy no-profile path by default."""

    async def _get_project_context(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "modules.project.facade.get_project_context",
        _get_project_context,
    )


@pytest_asyncio.fixture
async def service(chapters):
    """Service with mocked dependencies (single chapter)."""
    provider = mock.AsyncMock()
    provider.load_chapters.return_value = chapters
    svc = EntityExtractionService(draft_provider=provider)
    svc._dedup_service = mock.AsyncMock()
    svc._dedup_service.find_similar_entities.return_value = []
    svc._entity_repo = mock.AsyncMock()
    mock_entity = mock.MagicMock()
    mock_entity.id = uuid.uuid4()
    mock_entity.name = "白砚"
    mock_entity.entity_type = "character"
    svc._entity_repo.create.return_value = mock_entity
    return svc


@pytest_asyncio.fixture
def default_llm_response():
    """Two entities with create_new action."""
    return _TestOutput(
        entities=[
            _TestEntity(
                name="白砚",
                entity_type="character",
                summary="主角",
                suggested_action="create_new",
                confidence=0.9,
            ),
            _TestEntity(
                name="霜华剑",
                entity_type="item",
                summary="神剑",
                suggested_action="create_new",
                confidence=0.85,
            ),
        ]
    )


# ---------------------------------------------------------------
# Helper
# ---------------------------------------------------------------


def _setup_llm(mock_llm_client, *, return_value=None):
    """Configure LLMClient mock with defaults.

    Sets up generate_structured and generate_embedding as AsyncMock
    so that await works inside the service.  model_name and
    _settings.llm_model are needed because the service constructs an
    LLMCallRequest with model=llm.model_name (Pydantic validates it as str).
    """
    instance = mock_llm_client.return_value
    instance._settings = mock.MagicMock(llm_model="gpt-4o")
    instance.model_name = "gpt-4o"
    instance.generate_structured = mock.AsyncMock()
    instance.generate_structured.return_value = return_value or _TestOutput(entities=[])
    instance.generate_embedding = mock.AsyncMock()

    async def _generate_embedding(text_or_texts, *, is_query=False):
        if isinstance(text_or_texts, list):
            return [
                [float(idx) + 0.1, 0.2 if is_query else 0.4, 0.3]
                for idx, _ in enumerate(text_or_texts)
            ]
        return [0.1, 0.2 if is_query else 0.4, 0.3]

    instance.generate_embedding.side_effect = _generate_embedding
    mock_llm_client.from_project_settings.return_value = instance
    return instance


# ---------------------------------------------------------------
# Tests
# ---------------------------------------------------------------


class TestEntityExtractionService:
    """EntityExtractionService 单元测试 — 验证实体抽取、去重、错误处理与上下文累积"""

    @mock.patch("modules.project.facade.get_project_context", new_callable=mock.AsyncMock)
    @mock.patch("modules.world.facade.find_entity_id_by_name")
    @mock.patch("modules.world.facade.get_world_context")
    @mock.patch("infrastructure.llm.prompt_loader.load_prompt")
    @mock.patch("infrastructure.llm.client.LLMClient")
    async def test_extract_entities_uses_project_llm_profile(
        self,
        mock_llm_client,
        mock_load_prompt,
        mock_get_context,
        mock_find_entity,
        mock_project_context,
        service,
        default_llm_response,
    ):
        """Configured projects must use their effective LLM profile."""
        profile = {
            "llm": {
                "provider_id": "deepseek",
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-v4-flash",
                "api_key": "encrypted-test-key",
            }
        }
        _setup_llm(mock_llm_client, return_value=default_llm_response)
        mock_project_context.return_value = SimpleNamespace(settings=profile)
        mock_get_context.return_value = WorldContextBundle(novel_id="test", entities=[])
        mock_load_prompt.return_value = "system prompt base"
        mock_find_entity.return_value = None

        result = await service.extract_entities_from_chapters(
            mock.AsyncMock(),
            TEST_NOVEL_ID,
            1,
            1,
        )

        assert result.total_created == 2
        mock_llm_client.from_project_settings.assert_called_once_with(profile)

    @mock.patch("modules.world.facade.find_entity_id_by_name")
    @mock.patch("modules.world.facade.get_world_context")
    @mock.patch("infrastructure.llm.prompt_loader.load_prompt")
    @mock.patch("infrastructure.llm.client.LLMClient")
    async def test_extract_entities_from_chapters_with_create_new_action_creates_entities(
        self,
        mock_llm_client,
        mock_load_prompt,
        mock_get_context,
        mock_find_entity,
        service,
        default_llm_response,
    ):
        """Happy path — two create_new entities are created and counted."""
        # Arrange
        _setup_llm(mock_llm_client, return_value=default_llm_response)
        mock_get_context.return_value = WorldContextBundle(
            novel_id="test",
            entities=[],
        )
        mock_load_prompt.return_value = "system prompt base"
        mock_find_entity.return_value = None
        db = mock.AsyncMock()

        # Act
        result = await service.extract_entities_from_chapters(
            db,
            TEST_NOVEL_ID,
            1,
            1,
        )

        # Assert
        assert result.total_created == 2
        assert result.total_skipped == 0
        assert result.failed_chapters == []
        assert result.total_chapters == 1
        assert result.items[0]["name"] == "白砚"

    @mock.patch("modules.world.facade.find_entity_id_by_name")
    @mock.patch("modules.world.facade.get_world_context")
    @mock.patch("infrastructure.llm.prompt_loader.load_prompt")
    @mock.patch("infrastructure.llm.client.LLMClient")
    @pytest.mark.parametrize(
        "action,expected_created,expected_skipped",
        [
            ("create_new", 1, 0),
            ("ignore", 0, 1),
            ("temporary_only", 1, 0),
            ("link_to_existing", 0, 1),
        ],
    )
    async def test_extract_entities_from_chapters_with_various_actions_routes_correctly(
        self,
        mock_llm_client,
        mock_load_prompt,
        mock_get_context,
        mock_find_entity,
        service,
        action,
        expected_created,
        expected_skipped,
    ):
        """Each suggested_action routes the entity to the correct outcome."""
        # Arrange
        entity = _TestEntity(
            name="测试实体",
            suggested_action=action,
            suggested_existing_entity_name=(
                "现有实体" if action == "link_to_existing" else None
            ),
        )
        _setup_llm(mock_llm_client, return_value=_TestOutput(entities=[entity]))
        mock_get_context.return_value = WorldContextBundle(
            novel_id="test",
            entities=[],
        )
        mock_load_prompt.return_value = "system prompt"
        if action == "link_to_existing":
            mock_find_entity.return_value = str(uuid.uuid4())
        else:
            mock_find_entity.return_value = None
        db = mock.AsyncMock()

        # Act
        result = await service.extract_entities_from_chapters(
            db,
            TEST_NOVEL_ID,
            1,
            1,
        )

        # Assert
        assert result.total_created == expected_created
        assert result.total_skipped == expected_skipped

    @mock.patch("modules.world.services.core.extraction_service.logger")
    @mock.patch("modules.world.facade.find_entity_id_by_name")
    @mock.patch("modules.world.facade.get_world_context")
    @mock.patch("infrastructure.llm.prompt_loader.load_prompt")
    @mock.patch("infrastructure.llm.client.LLMClient")
    @pytest.mark.parametrize(
        "exception_cls,expected_log,want_exc_info",
        [
            ("LLMInvalidResponseError", "warning", False),
            ("ValueError", "error", True),
        ],
    )
    async def test_extract_entities_from_chapters_with_llm_error_marks_chapter_failed(
        self,
        mock_llm_client,
        mock_load_prompt,
        mock_get_context,
        mock_find_entity,
        mock_logger,
        service,
        exception_cls,
        expected_log,
        want_exc_info,
    ):
        """LLM errors produce the correct log level and populate failed_chapters."""
        # Arrange
        from infrastructure.llm.errors import LLMInvalidResponseError

        exc_map = {
            "LLMInvalidResponseError": LLMInvalidResponseError("parse error"),
            "ValueError": ValueError("unexpected"),
        }
        instance = _setup_llm(mock_llm_client)
        instance.generate_structured.side_effect = exc_map[exception_cls]
        mock_get_context.return_value = WorldContextBundle(
            novel_id="test",
            entities=[],
        )
        mock_load_prompt.return_value = "system prompt"
        mock_find_entity.return_value = None
        db = mock.AsyncMock()

        # Act
        result = await service.extract_entities_from_chapters(
            db,
            TEST_NOVEL_ID,
            1,
            1,
        )

        # Assert
        assert result.failed_chapters == [1]
        assert result.total_created == 0
        assert result.total_skipped == 0

        if expected_log == "warning":
            mock_logger.warning.assert_called_once()
            mock_logger.error.assert_not_called()
        else:
            mock_logger.error.assert_called_once()
            mock_logger.warning.assert_not_called()
            _call_kwargs = mock_logger.error.call_args
            if want_exc_info:
                assert _call_kwargs.kwargs.get("exc_info", False) is True

    @mock.patch("modules.world.facade.find_entity_id_by_name")
    @mock.patch("modules.world.facade.get_world_context")
    @mock.patch("infrastructure.llm.prompt_loader.load_prompt")
    @mock.patch("infrastructure.llm.client.LLMClient")
    async def test_extract_entities_from_chapters_with_name_embedding_match_skips_entity(
        self,
        mock_llm_client,
        mock_load_prompt,
        mock_get_context,
        mock_find_entity,
        service,
    ):
        """Layer 1 name-embedding dedup skips a high-confidence match."""
        # Arrange
        entity = _TestEntity(name="白砚", suggested_action="create_new")
        _setup_llm(mock_llm_client, return_value=_TestOutput(entities=[entity]))
        mock_get_context.return_value = WorldContextBundle(
            novel_id="test",
            entities=[],
        )
        mock_load_prompt.return_value = "system prompt"
        mock_find_entity.return_value = None

        service._dedup_service.find_similar_entities.return_value = [
            DuplicateSuggestionResult(
                candidate_name="白砚",
                existing_entity_id=str(uuid.uuid4()),
                existing_entity_name="白砚",
                similarity_score=0.95,
                match_method="name_embedding",
                action="skip",
            ),
        ]
        db = mock.AsyncMock()

        # Act
        result = await service.extract_entities_from_chapters(
            db,
            TEST_NOVEL_ID,
            1,
            1,
        )

        # Assert
        assert result.total_skipped == 1
        assert result.total_created == 0
        assert service._entity_repo.create.call_count == 0
        assert not any(
            call.kwargs.get("is_query") is False
            for call in mock_llm_client.return_value.generate_embedding.call_args_list
        )

    @mock.patch("modules.world.facade.find_entity_id_by_name")
    @mock.patch("modules.world.facade.get_world_context")
    @mock.patch("infrastructure.llm.prompt_loader.load_prompt")
    @mock.patch("infrastructure.llm.client.LLMClient")
    async def test_content_embedding_match_skips_entity(
        self,
        mock_llm_client,
        mock_load_prompt,
        mock_get_context,
        mock_find_entity,
        service,
    ):
        """Layer 2 content-embedding dedup catches what Layer 1 misses."""
        # Arrange
        entity = _TestEntity(
            name="白砚",
            summary="主角的剑",
            suggested_action="create_new",
        )
        _setup_llm(mock_llm_client, return_value=_TestOutput(entities=[entity]))
        mock_get_context.return_value = WorldContextBundle(
            novel_id="test",
            entities=[],
        )
        mock_load_prompt.return_value = "system prompt"
        mock_find_entity.return_value = None

        service._dedup_service.find_similar_entities.side_effect = [
            [],
            [
                DuplicateSuggestionResult(
                    candidate_name="白砚",
                    existing_entity_id=str(uuid.uuid4()),
                    existing_entity_name="白砚（旧版）",
                    similarity_score=0.92,
                    match_method="content_embedding",
                    action="skip",
                ),
            ],
        ]
        db = mock.AsyncMock()

        # Act
        result = await service.extract_entities_from_chapters(
            db,
            TEST_NOVEL_ID,
            1,
            1,
        )

        # Assert
        assert result.total_skipped == 1
        assert result.total_created == 0

        assert not any(
            call.kwargs.get("is_query") is False
            for call in mock_llm_client.return_value.generate_embedding.call_args_list
        )

    @mock.patch("modules.world.facade.find_entity_id_by_name")
    @mock.patch("modules.world.facade.get_world_context")
    @mock.patch("infrastructure.llm.prompt_loader.load_prompt")
    @mock.patch("infrastructure.llm.client.LLMClient")
    async def test_multiple_create_new_entities_use_batched_embeddings(
        self,
        mock_llm_client,
        mock_load_prompt,
        mock_get_context,
        mock_find_entity,
        service,
        default_llm_response,
    ):
        """Multiple create_new entities batch query and storage embeddings."""
        # Arrange
        instance = _setup_llm(mock_llm_client, return_value=default_llm_response)
        mock_get_context.return_value = WorldContextBundle(
            novel_id="test",
            entities=[],
        )
        mock_load_prompt.return_value = "system prompt"
        mock_find_entity.return_value = None
        db = mock.AsyncMock()

        # Act
        result = await service.extract_entities_from_chapters(
            db,
            TEST_NOVEL_ID,
            1,
            1,
        )

        # Assert
        assert result.total_created == 2
        assert instance.generate_embedding.call_count == 2

        query_call, storage_call = instance.generate_embedding.call_args_list
        assert query_call.args[0] == ["白砚", "主角", "霜华剑", "神剑"]
        assert query_call.kwargs == {"is_query": True}
        assert storage_call.args[0] == ["白砚", "霜华剑"]
        assert storage_call.kwargs == {"is_query": False}

    @mock.patch("modules.world.facade.find_entity_id_by_name")
    @mock.patch("modules.world.facade.get_world_context")
    @mock.patch("infrastructure.llm.prompt_loader.load_prompt")
    @mock.patch("infrastructure.llm.client.LLMClient")
    async def test_ignore_and_link_to_existing_do_not_enter_embedding_batches(
        self,
        mock_llm_client,
        mock_load_prompt,
        mock_get_context,
        mock_find_entity,
        service,
    ):
        """Only valid create_new entities contribute to chapter embedding batches."""
        # Arrange
        output = _TestOutput(
            entities=[
                _TestEntity(
                    name="白砚",
                    summary="主角",
                    suggested_action="create_new",
                ),
                _TestEntity(
                    name="路人甲",
                    summary="不应向量化",
                    suggested_action="ignore",
                ),
                _TestEntity(
                    name="霜华剑别名",
                    summary="不应向量化",
                    suggested_action="link_to_existing",
                    suggested_existing_entity_name="霜华剑",
                ),
            ]
        )
        instance = _setup_llm(mock_llm_client, return_value=output)
        mock_get_context.return_value = WorldContextBundle(
            novel_id="test",
            entities=[],
        )
        mock_load_prompt.return_value = "system prompt"
        mock_find_entity.return_value = str(uuid.uuid4())
        db = mock.AsyncMock()

        # Act
        result = await service.extract_entities_from_chapters(
            db,
            TEST_NOVEL_ID,
            1,
            1,
        )

        # Assert
        assert result.total_created == 1
        assert result.total_skipped == 2
        query_call, storage_call = instance.generate_embedding.call_args_list
        assert query_call.args[0] == ["白砚", "主角"]
        assert storage_call.args[0] == ["白砚"]

    @mock.patch("modules.world.facade.find_entity_id_by_name")
    @mock.patch("modules.world.facade.get_world_context")
    @mock.patch("infrastructure.llm.prompt_loader.load_prompt")
    @mock.patch("infrastructure.llm.client.LLMClient")
    async def test_embedding_batch_failure_still_creates_entity(
        self,
        mock_llm_client,
        mock_load_prompt,
        mock_get_context,
        mock_find_entity,
        service,
    ):
        """Batch embedding failure degrades to None and does not block creation."""
        # Arrange
        entity = _TestEntity(name="白砚", summary="主角", suggested_action="create_new")
        instance = _setup_llm(
            mock_llm_client, return_value=_TestOutput(entities=[entity])
        )
        instance.generate_embedding.side_effect = Exception("API error")
        mock_get_context.return_value = WorldContextBundle(
            novel_id="test",
            entities=[],
        )
        mock_load_prompt.return_value = "system prompt"
        mock_find_entity.return_value = None
        db = mock.AsyncMock()

        # Act
        result = await service.extract_entities_from_chapters(
            db,
            TEST_NOVEL_ID,
            1,
            1,
        )

        # Assert
        assert result.total_created == 1
        assert result.total_skipped == 0
        name_dedup_call = service._dedup_service.find_similar_entities.call_args_list[0]
        assert name_dedup_call.kwargs["query_embedding"] is None

    @mock.patch("modules.world.facade.find_entity_id_by_name")
    @mock.patch("modules.world.facade.get_world_context")
    @mock.patch("infrastructure.llm.prompt_loader.load_prompt")
    @mock.patch("infrastructure.llm.client.LLMClient")
    async def test_embedding_batch_length_mismatch_does_not_misassign_vectors(
        self,
        mock_llm_client,
        mock_load_prompt,
        mock_get_context,
        mock_find_entity,
        service,
        default_llm_response,
    ):
        """A mismatched batch result downgrades the whole batch to None."""
        # Arrange
        instance = _setup_llm(mock_llm_client, return_value=default_llm_response)

        async def _mismatched_batch(text_or_texts, *, is_query=False):
            if isinstance(text_or_texts, list):
                return [[0.9, 0.8, 0.7]]
            return [0.9, 0.8, 0.7]

        instance.generate_embedding.side_effect = _mismatched_batch

        created_entities: list[SimpleNamespace] = []

        async def _create_entity(_db, _novel_id, entity_data):
            entity = SimpleNamespace(
                id=uuid.uuid4(),
                name=entity_data.name,
                entity_type=entity_data.entity_type,
            )
            created_entities.append(entity)
            return entity

        service._entity_repo.create.side_effect = _create_entity
        mock_get_context.return_value = WorldContextBundle(
            novel_id="test",
            entities=[],
        )
        mock_load_prompt.return_value = "system prompt"
        mock_find_entity.return_value = None
        db = mock.AsyncMock()

        # Act
        result = await service.extract_entities_from_chapters(
            db,
            TEST_NOVEL_ID,
            1,
            1,
        )

        # Assert
        assert result.total_created == 2
        assert [
            call.kwargs["query_embedding"]
            for call in service._dedup_service.find_similar_entities.call_args_list
        ] == [None, None]
        assert all(not hasattr(entity, "embedding") for entity in created_entities)

    @mock.patch("modules.world.facade.find_entity_id_by_name")
    @mock.patch("modules.world.facade.get_world_context")
    @mock.patch("infrastructure.llm.prompt_loader.load_prompt")
    @mock.patch("infrastructure.llm.client.LLMClient")
    async def test_multiple_chapters_accumulate_context(
        self,
        mock_llm_client,
        mock_load_prompt,
        mock_get_context,
        mock_find_entity,
        service,
        multi_chapters,
    ):
        """Chapter context accumulates — each subsequent chapter sees prior entities."""
        # Arrange
        service._draft_provider.load_chapters.return_value = multi_chapters

        instance = _setup_llm(mock_llm_client)
        instance.generate_structured.side_effect = [
            _TestOutput(
                entities=[_TestEntity(name="白砚", suggested_action="create_new")]
            ),
            _TestOutput(
                entities=[_TestEntity(name="霜华剑", suggested_action="create_new")]
            ),
            _TestOutput(
                entities=[_TestEntity(name="墨渊", suggested_action="create_new")]
            ),
        ]

        mock_get_context.return_value = WorldContextBundle(
            novel_id="test",
            entities=[],
        )
        mock_find_entity.return_value = None

        context_snapshots: list[str] = []

        def _track_load_prompt(name, **kwargs):
            ctx = kwargs.get("existing_entities_context", "")
            context_snapshots.append(ctx)
            return f"system prompt for {name}"

        mock_load_prompt.side_effect = _track_load_prompt
        db = mock.AsyncMock()

        # Act
        result = await service.extract_entities_from_chapters(
            db,
            TEST_NOVEL_ID,
            1,
            3,
        )

        # Assert
        assert result.total_created == 3
        assert result.total_chapters == 3

        # Call 0 = initial; call 1 = after chapter 1; call 2 = after chapter 2
        assert len(context_snapshots) == 4
        assert "白砚" in context_snapshots[1]
        assert "白砚" in context_snapshots[2]
        assert "霜华剑" in context_snapshots[2]

    @mock.patch("modules.world.facade.find_entity_id_by_name")
    @mock.patch("modules.world.facade.get_world_context")
    @mock.patch("infrastructure.llm.prompt_loader.load_prompt")
    @mock.patch("infrastructure.llm.client.LLMClient")
    async def test_empty_entities_returns_zero_created(
        self,
        mock_llm_client,
        mock_load_prompt,
        mock_get_context,
        mock_find_entity,
        service,
    ):
        """Empty entities list from LLM does not crash and does not reload prompt."""
        # Arrange
        _setup_llm(mock_llm_client, return_value=_TestOutput(entities=[]))
        mock_get_context.return_value = WorldContextBundle(
            novel_id="test",
            entities=[],
        )
        mock_load_prompt.return_value = "system prompt"
        mock_find_entity.return_value = None
        db = mock.AsyncMock()

        # Act
        result = await service.extract_entities_from_chapters(
            db,
            TEST_NOVEL_ID,
            1,
            1,
        )

        # Assert
        assert result.total_created == 0
        assert result.total_skipped == 0
        assert result.total_chapters == 1
        assert mock_load_prompt.call_count == 1

    @mock.patch("modules.world.facade.find_entity_id_by_name")
    @mock.patch("modules.world.facade.get_world_context")
    @mock.patch("infrastructure.llm.prompt_loader.load_prompt")
    @mock.patch("infrastructure.llm.client.LLMClient")
    async def test_empty_name_skips_entity(
        self,
        mock_llm_client,
        mock_load_prompt,
        mock_get_context,
        mock_find_entity,
        service,
    ):
        """Entity with empty name is skipped without calling repo.create."""
        # Arrange
        entity = _TestEntity(name="", suggested_action="create_new")
        _setup_llm(mock_llm_client, return_value=_TestOutput(entities=[entity]))
        mock_get_context.return_value = WorldContextBundle(
            novel_id="test",
            entities=[],
        )
        mock_load_prompt.return_value = "system prompt"
        mock_find_entity.return_value = None
        db = mock.AsyncMock()

        # Act
        result = await service.extract_entities_from_chapters(
            db,
            TEST_NOVEL_ID,
            1,
            1,
        )

        # Assert
        assert result.total_skipped == 1
        assert result.total_created == 0
        assert service._entity_repo.create.call_count == 0

    @mock.patch("modules.world.facade.find_entity_id_by_name")
    @mock.patch("modules.world.facade.get_world_context")
    @mock.patch("infrastructure.llm.prompt_loader.load_prompt")
    @mock.patch("infrastructure.llm.client.LLMClient")
    async def test_embedding_failure_still_creates_entity(
        self,
        mock_llm_client,
        mock_load_prompt,
        mock_get_context,
        mock_find_entity,
        service,
    ):
        """Embedding API failure degrades gracefully — entity is still created."""
        # Arrange
        entity = _TestEntity(name="白砚", summary="主角", suggested_action="create_new")
        instance = _setup_llm(
            mock_llm_client, return_value=_TestOutput(entities=[entity])
        )
        instance.generate_embedding.side_effect = Exception("API error")
        mock_get_context.return_value = WorldContextBundle(
            novel_id="test",
            entities=[],
        )
        mock_load_prompt.return_value = "system prompt"
        mock_find_entity.return_value = None
        db = mock.AsyncMock()

        # Act
        result = await service.extract_entities_from_chapters(
            db,
            TEST_NOVEL_ID,
            1,
            1,
        )

        # Assert
        assert result.total_created == 1
        assert result.total_skipped == 0

    @mock.patch("modules.world.facade.find_entity_id_by_name")
    @mock.patch("modules.world.facade.get_world_context")
    @mock.patch("infrastructure.llm.prompt_loader.load_prompt")
    @mock.patch("infrastructure.llm.client.LLMClient")
    async def test_extract_entities_from_chapters_with_empty_chapters_raises_400(
        self,
        mock_llm_client,
        mock_load_prompt,
        mock_get_context,
        mock_find_entity,
        service,
    ):
        """No chapters to process raises HTTP 400."""
        # Arrange
        service._draft_provider.load_chapters.return_value = []
        mock_get_context.return_value = WorldContextBundle(
            novel_id="test",
            entities=[],
        )
        mock_load_prompt.return_value = "system prompt"
        mock_find_entity.return_value = None
        db = mock.AsyncMock()

        # Act
        with pytest.raises(DomainValidationError) as excinfo:
            await service.extract_entities_from_chapters(
                db,
                TEST_NOVEL_ID,
                1,
                1,
            )

        # Assert
        assert excinfo.value.status_code == 400
