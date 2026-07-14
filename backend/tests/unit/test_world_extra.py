"""
Extra unit tests for modules.world — edge cases and uncovered code paths.

Covers:
- entity_types.py (pure functions)
- entity_context_service.py (EntityContextService)
- entity_embedding_service.py (EntityEmbeddingService)
- entity_service.py (WorldEntityService — list)
- dedup_service.py (internal merge helpers, cascade paths, resolve)
- contracts.py (dataclass construction defaults)
- tasks.py (task handler)
- repositories.py (SQLite fallback, edge-case methods)

All external dependencies (DB, BGE, etc.) are mocked.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError as PydanticValidationError

from core.errors import ConflictError, NotFoundError
from core.errors import ValidationError as DomainValidationError
from modules.world.contracts import (
    CharacterContract,
    CharacterKnowledgeContract,
    CoreEntityContract,
    EntityRelationContract,
    EntityRevisionContract,
    EventContract,
    MergeResult,
    ResolveResult,
)
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityUpdate,
    EntityPromoteRequest,
    ExtractedEntity,
)
from modules.world.services.core.dedup_scorer import DedupSignals
from modules.world.services.core.dedup_service import EntityDedupService
from modules.world.services.core.entity_context_service import (
    EntityContextService,
    _entity_to_context,
)
from modules.world.services.core.entity_embedding_service import EntityEmbeddingService
from modules.world.services.core.entity_service import WorldEntityService
from modules.world.services.core.entity_types import (
    is_entity_type_valid,
    map_entity_type,
    normalize_entity_type,
)
from modules.world.tasks import handle_world_entity_extraction
from shared.enums import CandidateAction

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# ============================================================
# entity_types.py — pure function mapping
# ============================================================


class TestMapEntityType:
    """map_entity_type: LLM 中文 -> 标准英文类型"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("人物", "character"),
            ("人", "character"),
            ("角色", "character"),
            ("地点", "location"),
            ("场所", "location"),
            ("组织", "organization"),
            ("势力", "faction"),
            ("物品", "item"),
            ("物体", "object"),
            ("事件", "event"),
            ("规则", "rule"),
            ("力量体系", "power_system"),
            ("秘密", "secret"),
            ("概念", "concept"),
            ("传说", "legend"),
            ("资源", "resource"),
            ("生物", "creature"),
            ("怪物", "creature"),
            ("技能", "skill"),
            ("能力", "ability"),
            ("神器", "artifact"),
            ("rule/power_system", "rule"),
            ("secret/legend", "secret"),
            ("其他", "other"),
        ],
    )
    def test_mapped_types_return_canonical_english(self, raw: str, expected: str) -> None:
        assert map_entity_type(raw) == expected

    def test_character_ref_maps_to_character(self) -> None:
        assert map_entity_type("character_ref") == "character"

    def test_unmapped_type_raw_returned(self) -> None:
        assert map_entity_type("corgi") == "corgi"

    def test_empty_string_returns_empty(self) -> None:
        assert map_entity_type("") == ""


class TestIsEntityTypeValid:
    """is_entity_type_valid: whitelist validation"""

    def test_valid_types_return_true(self) -> None:
        for t in (
            "character",
            "location",
            "faction",
            "organization",
            "item",
            "object",
            "event",
            "rule",
            "power_system",
            "secret",
            "legend",
            "resource",
            "concept",
            "creature",
            "skill",
            "ability",
            "artifact",
            "other",
        ):
            assert is_entity_type_valid(t) is True

    def test_invalid_type_returns_false(self) -> None:
        assert is_entity_type_valid("corgi") is False

    def test_empty_string_returns_false(self) -> None:
        assert is_entity_type_valid("") is False

    def test_relation_is_not_core_entity_type(self) -> None:
        assert is_entity_type_valid("relation") is False


class TestNormalizeEntityType:
    """normalize_entity_type: schema-facing normalization."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (" 人物 ", "character"),
            (" CHARACTER ", "character"),
            ("character_ref", "character"),
            ("组织", "organization"),
            ("物体", "object"),
            ("能力", "ability"),
            ("神器", "artifact"),
        ],
    )
    def test_normalizes_supported_types(self, raw: str, expected: str) -> None:
        assert normalize_entity_type(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        ["organization", "object", "ability", "artifact"],
    )
    def test_compatible_types_are_not_remapped(self, raw: str) -> None:
        assert normalize_entity_type(raw) == raw

    def test_invalid_type_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unsupported entity_type"):
            normalize_entity_type("corgi")


class TestEntityTypeSchemaValidation:
    """Pydantic schemas normalize and validate supported entity types."""

    def test_core_entity_create_normalizes_type(self) -> None:
        model = CoreEntityCreate(entity_type=" CHARACTER ", name="Hero")
        assert model.entity_type == "character"

    def test_core_entity_create_accepts_safe_author_custom_type(self) -> None:
        model = CoreEntityCreate(entity_type=" Corgi ", name="Hero")
        assert model.entity_type == "corgi"

    def test_core_entity_update_allows_none_entity_type(self) -> None:
        model = CoreEntityUpdate(entity_type=None)
        assert model.entity_type is None

    def test_core_entity_update_normalizes_type(self) -> None:
        model = CoreEntityUpdate(entity_type="character_ref")
        assert model.entity_type == "character"

    def test_core_entity_update_accepts_safe_author_custom_type(self) -> None:
        model = CoreEntityUpdate(entity_type=" Corgi ")
        assert model.entity_type == "corgi"

    def test_extracted_entity_normalizes_type(self) -> None:
        model = ExtractedEntity(entity_type="能力", name="Magic")
        assert model.entity_type == "ability"

    def test_extracted_entity_rejects_invalid_type(self) -> None:
        with pytest.raises(PydanticValidationError):
            ExtractedEntity(entity_type="corgi", name="Unknown")


# ============================================================
# entity_service.py — WorldEntityService.list
# ============================================================


def _mock_entity(**overrides) -> MagicMock:
    defaults = {
        "id": uuid.uuid4(),
        "novel_id": uuid.uuid4(),
        "entity_type": "character",
        "name": "Test",
        "summary": None,
        "public_info": None,
        "hidden_truth": None,
        "content_json": {},
        "importance": 0.5,
        "importance_level": "normal",
        "reveal_level": "author_only",
        "status": "draft",
        "display_state": None,
        "source": None,
        "attention_reasons": [],
        "suggested_action": None,
        "embedding_text": None,
        "created_by": None,
        "approved_by": None,
        "created_at": None,
        "updated_at": None,
    }
    defaults.update(overrides)
    e = MagicMock()
    for k, v in defaults.items():
        setattr(e, k, v)
    return e


class TestEntityServiceList:
    """WorldEntityService.list — override with filters + ListResponse wrapper"""

    async def test_entity_service_has_no_direct_http_exception_dependency(self) -> None:
        source = (
            BACKEND_ROOT / "modules/world/services/core/entity_service.py"
        ).read_text()

        assert "from fastapi import HTTPException" not in source
        assert "raise HTTPException" not in source

    async def test_forwards_filters_to_repo(self) -> None:
        db = MagicMock()
        nid = str(uuid.uuid4())
        with patch.object(WorldEntityService, "repo", autospec=True) as mock_repo:
            mock_repo.get_by_novel = AsyncMock(return_value=([], 0))
            svc = WorldEntityService()
            await svc.list(
                db, nid, entity_type="location", status="canonical", skip=5, limit=20
            )

            _, kwargs = svc.repo.get_by_novel.await_args
            assert kwargs["entity_type"] == "location"
            assert kwargs["status"] == "canonical"
            assert kwargs["skip"] == 5
            assert kwargs["limit"] == 20

    async def test_clamps_limit_to_max(self) -> None:
        db = MagicMock()
        with patch.object(WorldEntityService, "repo", autospec=True) as mock_repo:
            mock_repo.get_by_novel = AsyncMock(return_value=([], 0))
            svc = WorldEntityService()
            await svc.list(db, str(uuid.uuid4()), limit=9999)

            _, kwargs = svc.repo.get_by_novel.await_args
            assert kwargs["limit"] <= 500

    async def test_returns_list_response(self) -> None:
        db = MagicMock()
        with patch.object(WorldEntityService, "repo", autospec=True) as mock_repo:
            mock_repo.get_by_novel = AsyncMock(return_value=([_mock_entity()], 1))
            svc = WorldEntityService()
            result = await svc.list(db, str(uuid.uuid4()))

            assert result.total == 1
            assert len(result.items) == 1
            assert result.items[0].name == "Test"

    async def test_create_duplicate_requires_domain_confirmation(self) -> None:
        db = MagicMock()
        nid = str(uuid.uuid4())
        duplicate = _mock_entity(name="Hero")
        with patch.object(WorldEntityService, "repo", autospec=True) as mock_repo:
            mock_repo.find_similar_by_search_text = AsyncMock(
                return_value=[(duplicate, 0.96)]
            )
            mock_repo.create = AsyncMock()
            svc = WorldEntityService()

            with pytest.raises(ConflictError) as exc_info:
                await svc.create(
                    db,
                    nid,
                    CoreEntityCreate(entity_type="character", name="Hero"),
                )

            assert exc_info.value.status_code == 409
            assert exc_info.value.detail["requires_confirmation"] is True
            mock_repo.create.assert_not_called()

    async def test_update_direct_promote_raises_domain_validation(self) -> None:
        db = MagicMock()
        nid = str(uuid.uuid4())
        entity_id = str(uuid.uuid4())
        existing = _mock_entity(id=uuid.UUID(entity_id), novel_id=uuid.UUID(nid))
        existing.status = "draft"
        with patch.object(WorldEntityService, "repo", autospec=True) as mock_repo:
            mock_repo.get_for_update = AsyncMock(return_value=existing)
            mock_repo.update = AsyncMock()
            svc = WorldEntityService()

            with pytest.raises(DomainValidationError) as exc_info:
                await svc.update(
                    db,
                    entity_id,
                    CoreEntityUpdate(status="canonical", approved_by="manual"),
                    novel_id=nid,
                )

            assert exc_info.value.status_code == 400
            assert "Use /entities/{entity_id}/promote" in exc_info.value.message
            mock_repo.update.assert_not_called()

    async def test_update_reuses_loaded_entity_for_repo_update(self) -> None:
        db = MagicMock()
        nid = str(uuid.uuid4())
        entity_id = str(uuid.uuid4())
        existing = _mock_entity(id=uuid.UUID(entity_id), novel_id=uuid.UUID(nid))
        with patch.object(WorldEntityService, "repo", autospec=True) as mock_repo:
            mock_repo.get_for_update = AsyncMock(return_value=existing)
            mock_repo.update = AsyncMock(return_value=existing)
            with patch(
                "modules.world.services.core.entity_revision_service."
                "EntityRevisionService.create_snapshot",
                autospec=True,
            ):
                svc = WorldEntityService()
                result = await svc.update(
                    db,
                    entity_id,
                    CoreEntityUpdate(summary="新摘要"),
                    novel_id=nid,
                )

            assert result.id == entity_id
            mock_repo.update.assert_awaited_once()
            assert mock_repo.update.await_args.args[1] is existing

    async def test_promote_canonical_entity_raises_domain_validation(self) -> None:
        db = MagicMock()
        nid = str(uuid.uuid4())
        entity_id = str(uuid.uuid4())
        existing = _mock_entity(
            id=uuid.UUID(entity_id),
            novel_id=uuid.UUID(nid),
            status="canonical",
        )
        with patch.object(WorldEntityService, "repo", autospec=True) as mock_repo:
            mock_repo.get_for_update = AsyncMock(return_value=existing)
            mock_repo.update = AsyncMock()
            svc = WorldEntityService()

            with pytest.raises(DomainValidationError) as exc_info:
                await svc.promote(
                    db,
                    entity_id,
                    EntityPromoteRequest(approved_by="manual"),
                    novel_id=nid,
                )

            assert exc_info.value.status_code == 400
            assert "只有待处理的 draft/candidate 实体可以采用" in exc_info.value.message
            mock_repo.update.assert_not_called()

    async def test_promote_reuses_loaded_entity_for_repo_update(self) -> None:
        db = MagicMock()
        nid = str(uuid.uuid4())
        entity_id = str(uuid.uuid4())
        existing = _mock_entity(
            id=uuid.UUID(entity_id),
            novel_id=uuid.UUID(nid),
            status="candidate",
        )
        with patch.object(WorldEntityService, "repo", autospec=True) as mock_repo:
            mock_repo.get_for_update = AsyncMock(return_value=existing)
            mock_repo.update = AsyncMock(return_value=existing)
            svc = WorldEntityService()

            result = await svc.promote(
                db,
                entity_id,
                EntityPromoteRequest(approved_by="manual"),
                novel_id=nid,
            )

            assert result.entity_id == entity_id
            mock_repo.update.assert_awaited_once()
            assert mock_repo.update.await_args.args[1] is existing


# ============================================================
# entity_context_service.py — EntityContextService
# ============================================================


class TestEntityContextServiceGetEntityContext:
    """EntityContextService.get_entity_context"""

    async def test_with_entity_ids_filters_by_ids(self) -> None:
        db = MagicMock()
        nid = str(uuid.uuid4())
        eid = str(uuid.uuid4())
        svc = EntityContextService()
        with patch.object(svc, "_repo", autospec=True) as mock_repo:
            mock_repo.get_by_ids = AsyncMock(return_value=[_mock_entity()])
            result = await svc.get_entity_context(db, nid, entity_ids=[eid])
            assert result.total_count == 1
            mock_repo.get_by_ids.assert_awaited_once()

    async def test_without_entity_ids_uses_status_filtered_query(self) -> None:
        db = MagicMock()
        svc = EntityContextService()
        with patch.object(svc, "_repo", autospec=True) as mock_repo:
            mock_repo.get_by_type_and_status = AsyncMock(return_value=[])
            result = await svc.get_entity_context(db, str(uuid.uuid4()), entity_ids=None)
            assert result.total_count == 0
            mock_repo.get_by_type_and_status.assert_awaited_once()
            assert mock_repo.get_by_type_and_status.await_args.kwargs["statuses"] == (
                "canonical",
            )
            mock_repo.get_by_ids.assert_not_called()

    async def test_author_only_reveal_mode_includes_hidden_truth(self) -> None:
        db = MagicMock()
        ent = _mock_entity(hidden_truth="deep secret")
        svc = EntityContextService()
        with patch.object(svc, "_repo", autospec=True) as mock_repo:
            mock_repo.get_by_type_and_status = AsyncMock(return_value=[ent])
            result = await svc.get_entity_context(
                db,
                str(uuid.uuid4()),
                reveal_mode="author_only",
            )
            assert result.entities[0].hidden_truth == "deep secret"

    async def test_author_safe_reveal_mode_excludes_hidden_truth(self) -> None:
        db = MagicMock()
        ent = _mock_entity(hidden_truth="secret")
        svc = EntityContextService()
        with patch.object(svc, "_repo", autospec=True) as mock_repo:
            mock_repo.get_by_type_and_status = AsyncMock(return_value=[ent])
            result = await svc.get_entity_context(
                db,
                str(uuid.uuid4()),
                reveal_mode="author_safe",
            )
            assert result.entities[0].hidden_truth is None

    async def test_expired_temp_entity_filtered_out(self) -> None:
        db = MagicMock()
        db.execute = AsyncMock()
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
        old_temp = _mock_entity(
            content_json={"_meta": {"temporary": True, "source_chapter_index": 1}},
        )
        svc = EntityContextService()
        with patch.object(svc, "_repo", autospec=True) as mock_repo:
            mock_repo.get_by_type_and_status = AsyncMock(return_value=[old_temp])
            result = await svc.get_entity_context(
                db,
                str(uuid.uuid4()),
                current_chapter=100,
            )
            assert result.total_count == 0

    async def test_non_temp_entity_always_included(self) -> None:
        db = MagicMock()
        db.execute = AsyncMock()
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
        normal = _mock_entity(content_json={"_meta": {}})
        svc = EntityContextService()
        with patch.object(svc, "_repo", autospec=True) as mock_repo:
            mock_repo.get_by_type_and_status = AsyncMock(return_value=[normal])
            result = await svc.get_entity_context(
                db,
                str(uuid.uuid4()),
                current_chapter=100,
            )
            assert result.total_count == 1


class TestEntityContextServiceListEntitySummaries:
    async def test_returns_id_name_type_dicts(self) -> None:
        db = MagicMock()
        nid = str(uuid.uuid4())
        ent = _mock_entity(name="Sword", entity_type="item")
        svc = EntityContextService()
        with patch.object(svc, "_repo", autospec=True) as mock_repo:
            mock_repo.get_by_type_and_status = AsyncMock(return_value=[ent])
            result = await svc.list_entity_summaries(
                db, nid, entity_type="item", limit=50
            )
            assert len(result) == 1
            assert result[0]["name"] == "Sword"
            assert result[0]["entity_type"] == "item"
            mock_repo.get_by_type_and_status.assert_awaited_once_with(
                db,
                uuid.UUID(hex=nid),
                entity_type="item",
                limit=50,
            )

    async def test_passes_statuses_when_filter_provided(self) -> None:
        db = MagicMock()
        nid = str(uuid.uuid4())
        ent = _mock_entity(name="Sword", entity_type="item")
        svc = EntityContextService()
        with patch.object(svc, "_repo", autospec=True) as mock_repo:
            mock_repo.get_by_type_and_status = AsyncMock(return_value=[ent])
            await svc.list_entity_summaries(
                db,
                nid,
                entity_type="item",
                statuses=["canonical", "draft"],
                limit=50,
            )
            mock_repo.get_by_type_and_status.assert_awaited_once_with(
                db,
                uuid.UUID(hex=nid),
                entity_type="item",
                statuses=["canonical", "draft"],
                limit=50,
            )


class TestEntityContextServiceListEntityTerms:
    async def test_only_canonical_entities_included(self) -> None:
        db = MagicMock()
        canonical = _mock_entity(name="Hero", status="canonical")
        draft = _mock_entity(name="Sidekick", status="draft")
        merged = _mock_entity(name="Gone", status="merged")
        svc = EntityContextService()
        with patch.object(svc, "_repo", autospec=True) as mock_repo:
            mock_repo.list_by_novel = AsyncMock(return_value=[canonical, draft, merged])
            result = await svc.list_entity_terms(db, str(uuid.uuid4()))
            assert len(result) == 1
            assert result[0]["name"] == "Hero"

    async def test_extracts_aliases_from_content_json(self) -> None:
        db = MagicMock()
        ent1 = _mock_entity(
            name="Arthur",
            status="canonical",
            content_json={"aliases": ["King", {"alias": "Once and Future King"}]},
        )
        ent2 = _mock_entity(
            name="Merlin",
            status="canonical",
            content_json={"aliases": []},
        )
        svc = EntityContextService()
        with patch.object(svc, "_repo", autospec=True) as mock_repo:
            mock_repo.list_by_novel = AsyncMock(return_value=[ent1, ent2])
            result = await svc.list_entity_terms(db, str(uuid.uuid4()))

            assert len(result) == 2
            arthur_terms = [t for t in result if t["name"] == "Arthur"][0]
            assert "Arthur" in arthur_terms["terms"]
            assert "King" in arthur_terms["terms"]
            assert "Once and Future King" in arthur_terms["terms"]
            merlin_terms = [t for t in result if t["name"] == "Merlin"][0]
            assert merlin_terms["terms"] == ["Merlin"]


class TestEntityContextServiceFindByName:
    async def test_found_returns_entity_id_str(self) -> None:
        db = MagicMock()
        eid = str(uuid.uuid4())
        svc = EntityContextService()
        with patch.object(svc, "_repo", autospec=True) as mock_repo:
            mock_repo.find_entity_by_name = AsyncMock(return_value=eid)
            result = await svc.find_by_name(db, str(uuid.uuid4()), "Arthur")
            assert result == eid

    async def test_not_found_returns_none(self) -> None:
        db = MagicMock()
        svc = EntityContextService()
        with patch.object(svc, "_repo", autospec=True) as mock_repo:
            mock_repo.find_entity_by_name = AsyncMock(return_value=None)
            result = await svc.find_by_name(db, str(uuid.uuid4()), "Nobody")
            assert result is None


# ============================================================
# entity_embedding_service.py — EntityEmbeddingService
# ============================================================


class TestEntityEmbeddingServiceBackfillEmbeddings:
    """EntityEmbeddingService.backfill_embeddings — BGE client and batch logic"""

    def _make_db(self, entities: list) -> MagicMock:
        """Create a db mock that returns entities via execute()->scalars().all()."""
        db = MagicMock()
        query_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = entities
        query_result.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=query_result)
        db.flush = AsyncMock()
        return db

    async def test_no_entities_needing_backfill_returns_zero(self) -> None:
        db = self._make_db([])
        result = await EntityEmbeddingService().backfill_embeddings(db, str(uuid.uuid4()))
        assert result == 0

    @patch(
        "modules.world.services.core.entity_embedding_service.BgeEmbeddingClient.get_instance",
        autospec=True,
    )
    async def test_bge_unavailable_returns_zero(self, mock_get_instance) -> None:
        mock_get_instance.side_effect = RuntimeError("BGE not available")
        db = self._make_db([_mock_entity(name="Arthur")])
        result = await EntityEmbeddingService().backfill_embeddings(db, str(uuid.uuid4()))
        assert result == 0

    @patch(
        "modules.world.services.core.entity_embedding_service.BgeEmbeddingClient.get_instance",
        autospec=True,
    )
    async def test_happy_path_backfills_in_batches(self, mock_get_instance) -> None:
        bge = AsyncMock()
        bge.generate_embedding = AsyncMock(return_value=[[0.1], [0.2], [0.3], [0.4]])
        mock_get_instance.return_value = bge
        ents = [_mock_entity(name=f"E{i}") for i in range(4)]
        db = self._make_db(ents)

        result = await EntityEmbeddingService().backfill_embeddings(
            db, str(uuid.uuid4()), batch_size=4
        )

        assert result == 4
        for e, expected_val in zip(ents, [0.1, 0.2, 0.3, 0.4]):
            assert e.embedding == [expected_val]
            assert e.embedding_text == e.name

    @patch(
        "modules.world.services.core.entity_embedding_service.BgeEmbeddingClient.get_instance",
        autospec=True,
    )
    async def test_skips_empty_name_entities(self, mock_get_instance) -> None:
        bge = AsyncMock()
        bge.generate_embedding = AsyncMock(return_value=[[0.5]])
        mock_get_instance.return_value = bge
        valid = _mock_entity(name="E1")
        empty = _mock_entity(name="")
        db = self._make_db([valid, empty])

        result = await EntityEmbeddingService().backfill_embeddings(
            db, str(uuid.uuid4()), batch_size=8
        )

        assert result == 1
        assert valid.embedding == [0.5]

    @patch(
        "modules.world.services.core.entity_embedding_service.BgeEmbeddingClient.get_instance",
        autospec=True,
    )
    async def test_batch_failure_continues_to_next_batch(self, mock_get_instance) -> None:
        bge = AsyncMock()
        bge.generate_embedding = AsyncMock(
            side_effect=[
                RuntimeError("API error"),
                [[0.9], [1.0]],
            ]
        )
        mock_get_instance.return_value = bge
        ents = [_mock_entity(name=f"E{i}") for i in range(4)]
        db = self._make_db(ents)

        result = await EntityEmbeddingService().backfill_embeddings(
            db, str(uuid.uuid4()), batch_size=2
        )

        assert result == 2  # second batch succeeded


class TestEntityToContext:
    """_entity_to_context private helper"""

    def test_author_only_includes_hidden_truth(self) -> None:
        entity = _mock_entity(hidden_truth="deep secret", status="canonical")
        ctx = _entity_to_context(entity, reveal_mode="author_only")
        assert ctx.hidden_truth == "deep secret"
        assert ctx.status == "canonical"

    def test_author_safe_excludes_hidden_truth(self) -> None:
        entity = _mock_entity(hidden_truth="secret")
        ctx = _entity_to_context(entity, reveal_mode="author_safe")
        assert ctx.hidden_truth is None

    def test_author_safe_default(self) -> None:
        entity = _mock_entity(hidden_truth="secret")
        ctx = _entity_to_context(entity, reveal_mode="unknown")
        assert ctx.hidden_truth is None

    def test_fields_mapped_correctly(self) -> None:
        eid = uuid.uuid4()
        entity = _mock_entity(
            id=eid,
            entity_type="location",
            name="Middle-earth",
            summary="A continent",
            public_info="Known to all",
            importance=0.9,
            importance_level="core",
            reveal_level="hinted",
            status="canonical",
        )
        ctx = _entity_to_context(entity, reveal_mode="author_only")
        assert ctx.entity_id == str(eid)
        assert ctx.entity_type == "location"
        assert ctx.name == "Middle-earth"
        assert ctx.summary == "A continent"
        assert ctx.public_info == "Known to all"
        assert ctx.importance == 0.9
        assert ctx.importance_level == "core"
        assert ctx.reveal_level == "hinted"


# ============================================================
# dedup_service.py — EntityDedupService internal methods
# ============================================================


class TestDedupCascadeScore:
    """EntityDedupService._cascade_score — all decision paths"""

    def test_substring_path_returns_merge(self) -> None:
        sim, method, action = EntityDedupService._cascade_score(
            DedupSignals(substring_match=0.85),
        )
        assert sim == 0.95
        assert method == "substring"
        assert action == CandidateAction.merge_with_existing

    def test_fuzzy_pinyin_path_returns_merge(self) -> None:
        sim, method, action = EntityDedupService._cascade_score(
            DedupSignals(rapidfuzz_ratio=0.92, pinyin_jaro=0.90),
        )
        assert sim == 0.90
        assert method == "fuzzy_pinyin"
        assert action == CandidateAction.merge_with_existing

    def test_fuzzy_pinyin_below_threshold_does_not_short_circuit(self) -> None:
        sim, method, action = EntityDedupService._cascade_score(
            DedupSignals(rapidfuzz_ratio=0.91, pinyin_jaro=0.90),
        )
        # Falls through to lexical_fusion
        assert method == "lexical_fusion"
        assert sim <= 0.88

    def test_semantic_high_confidence_returns_merge(self) -> None:
        sim, method, action = EntityDedupService._cascade_score(
            DedupSignals(semantic_cosine=0.85),
        )
        assert sim == 0.90
        assert method == "semantic"
        assert action == CandidateAction.merge_with_existing

    def test_semantic_medium_with_sufficient_signals_returns_merge(self) -> None:
        sim, method, action = EntityDedupService._cascade_score(
            DedupSignals(
                semantic_cosine=0.80,
                rapidfuzz_ratio=0.30,
            ),
        )
        # sim = round(0.50 + 0.80 * 0.35, 4) = 0.78, below merge threshold 0.88
        # But >= review threshold 0.70 → returns (0.78, "semantic", needs_user_decision)
        assert method == "semantic"
        assert action == CandidateAction.needs_user_decision
        assert sim == 0.78

    def test_semantic_medium_above_merge(self) -> None:
        sim, method, action = EntityDedupService._cascade_score(
            DedupSignals(
                semantic_cosine=0.95,
                rapidfuzz_ratio=0.30,
            ),
        )
        # sim = round(0.50 + 0.95 * 0.35, 4) = 0.8325
        # 0.8325 > 0.88? No -> falls through
        # Wait: if semantic_cosine >= 0.85 -> already handled.
        # 0.95 >= 0.85 -> returns (0.90, "semantic", merge)
        assert sim == 0.90
        assert method == "semantic"

    def test_semantic_in_review_range(self) -> None:
        # semantic_cosine = 0.70 (below 0.75), so falls through to lexical
        signals = DedupSignals(
            semantic_cosine=0.70,
            rapidfuzz_ratio=0.75,
            pinyin_jaro=0.50,
            rapidfuzz_token_sort=0.65,
            substring_match=0.10,
        )
        sim, method, action = EntityDedupService._cascade_score(signals)
        assert method == "lexical_fusion"
        # lexical = 0.50*0.75 + 0.20*0.50 + 0.20*0.65 + 0.10*0.10
        #         = 0.375 + 0.10 + 0.13 + 0.01 = 0.615
        # Between discard (0.58) and review (0.70) -> needs_user_decision
        assert sim == 0.615
        assert action == CandidateAction.needs_user_decision

    def test_lexical_path_returns_merge_when_high(self) -> None:
        signals = DedupSignals(
            rapidfuzz_ratio=0.95,
            pinyin_jaro=0.85,
            rapidfuzz_token_sort=0.90,
            substring_match=0.80,
        )
        sim, method, action = EntityDedupService._cascade_score(signals)
        # lexical = 0.50*0.95 + 0.20*0.85 + 0.20*0.90 + 0.10*0.80
        #         = 0.475 + 0.17 + 0.18 + 0.08 = 0.905
        assert sim >= 0.88
        assert method == "lexical_fusion"
        assert action == CandidateAction.merge_with_existing

    def test_lexical_path_discard_when_low(self) -> None:
        signals = DedupSignals(
            rapidfuzz_ratio=0.20,
            pinyin_jaro=0.10,
            rapidfuzz_token_sort=0.15,
            substring_match=0.0,
        )
        sim, method, action = EntityDedupService._cascade_score(signals)
        # lexical = 0.50*0.20 + 0.20*0.10 + 0.20*0.15 + 0.10*0.0
        #         = 0.10 + 0.02 + 0.03 + 0.0 = 0.15
        assert sim < 0.58
        assert method == "lexical_fusion"
        assert action == CandidateAction.ignore

    def test_prefix_conflict_downgrades_to_discard(self) -> None:
        signals = DedupSignals(
            rapidfuzz_ratio=0.80,
            pinyin_jaro=0.60,
            rapidfuzz_token_sort=0.75,
            substring_match=0.30,
            prefix_conflict=True,
        )
        sim, method, action = EntityDedupService._cascade_score(signals)
        assert method == "lexical_fusion"
        # lexical before clamp = 0.655, but clamped to < 0.58
        assert sim < 0.58

    def test_semantic_just_below_075_falls_through_to_lexical(self) -> None:
        signals = DedupSignals(
            semantic_cosine=0.74,
            rapidfuzz_ratio=0.5,
            pinyin_jaro=0.5,
            rapidfuzz_token_sort=0.5,
            substring_match=0.0,
        )
        sim, method, action = EntityDedupService._cascade_score(signals)
        assert method == "lexical_fusion"
        # lexical = 0.50*0.5 + 0.20*0.5 + 0.20*0.5 + 0.10*0.0 = 0.45
        # Below discard threshold (0.58) → ignore
        assert action == CandidateAction.ignore


class TestDedupGetAliases:
    """EntityDedupService._get_aliases"""

    def test_string_aliases_converted_to_lower(self) -> None:
        entity = _mock_entity(content_json={"aliases": ["AliasA", "AliasB"]})
        result = EntityDedupService._get_aliases(entity)
        assert result == ["aliasa", "aliasb"]

    def test_dict_aliases_extract_alias_key(self) -> None:
        entity = _mock_entity(
            content_json={
                "aliases": [{"alias": "Nick"}, {"alias": "Name"}],
            }
        )
        result = EntityDedupService._get_aliases(entity)
        assert result == ["nick", "name"]

    def test_mixed_aliases_handled(self) -> None:
        entity = _mock_entity(
            content_json={
                "aliases": ["Simple", {"alias": "Complex"}],
            }
        )
        result = EntityDedupService._get_aliases(entity)
        assert result == ["simple", "complex"]

    def test_empty_content_json_returns_empty_list(self) -> None:
        entity = _mock_entity(content_json={})
        assert EntityDedupService._get_aliases(entity) == []

    def test_missing_aliases_key_returns_empty(self) -> None:
        entity = _mock_entity(content_json={"other": "data"})
        assert EntityDedupService._get_aliases(entity) == []


class TestDedupGetAliasesRaw:
    """EntityDedupService()._get_aliases_raw — preserves original format"""

    def test_dict_entries_preserved(self) -> None:
        entity = _mock_entity(
            content_json={
                "aliases": [{"alias": "Nick", "type": "name"}],
            }
        )
        result = EntityDedupService()._get_aliases_raw(entity)
        assert result == [{"alias": "Nick", "type": "name"}]

    def test_string_entries_wrapped(self) -> None:
        entity = _mock_entity(content_json={"aliases": ["Nick"]})
        result = EntityDedupService()._get_aliases_raw(entity)
        assert result == [{"alias": "Nick", "type": "unknown"}]

    def test_empty_returns_empty(self) -> None:
        entity = _mock_entity(content_json={})
        assert EntityDedupService()._get_aliases_raw(entity) == []

    def test_mixed_handled(self) -> None:
        entity = _mock_entity(
            content_json={
                "aliases": ["Str", {"alias": "Dict"}],
            }
        )
        result = EntityDedupService()._get_aliases_raw(entity)
        assert len(result) == 2
        assert {"alias": "Str", "type": "unknown"} in result
        assert {"alias": "Dict"} in result


class TestDedupMergeTextFields:
    """EntityDedupService._merge_text_fields — delegates to helper"""

    async def test_both_none_does_not_update(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()
        candidate = _mock_entity(summary=None)
        target = _mock_entity(summary=None)

        await svc._merge_text_fields(MagicMock(), candidate, target)

        svc._entity_repo.update.assert_not_called()

    async def test_candidate_summary_appended(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()
        candidate = _mock_entity(summary="extra detail")
        target = _mock_entity(summary="existing")

        await svc._merge_text_fields(MagicMock(), candidate, target)

        svc._entity_repo.update.assert_awaited_once()
        assert svc._entity_repo.update.call_args[0][1] is target
        call_data = svc._entity_repo.update.call_args[0][2]
        assert "existing" in call_data.summary
        assert "extra detail" in call_data.summary

    async def test_public_info_and_hidden_truth_merged(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()
        candidate = _mock_entity(public_info="c", hidden_truth="h")
        target = _mock_entity(public_info=None, hidden_truth=None)

        await svc._merge_text_fields(MagicMock(), candidate, target)

        assert svc._entity_repo.update.await_count == 1
        assert svc._entity_repo.update.call_args[0][1] is target
        call_data = svc._entity_repo.update.call_args[0][2]
        assert call_data.public_info == "c"
        assert call_data.hidden_truth == "h"


class TestDedupArchiveConflicts:
    """EntityDedupService._archive_conflicts"""

    async def test_no_conflicts_when_fields_match(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()
        candidate = _mock_entity(content_json={"weapon": "sword", "age": "30"})
        target = _mock_entity(content_json={"weapon": "sword", "age": "30"})

        result = await svc._archive_conflicts(MagicMock(), candidate, target)

        assert result == 0
        svc._entity_repo.update.assert_not_called()

    async def test_conflicts_detected_and_archived(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()
        candidate = _mock_entity(content_json={"weapon": "axe", "age": "30"})
        target = _mock_entity(content_json={"weapon": "sword", "age": "30"})

        result = await svc._archive_conflicts(MagicMock(), candidate, target)

        assert result == 1  # only weapon conflicts
        svc._entity_repo.update.assert_awaited_once()
        assert svc._entity_repo.update.call_args[0][1] is target
        call_data = svc._entity_repo.update.call_args[0][2]
        meta = call_data.content_json.get("meta", {})
        assert len(meta["conflict_notes"]) == 1
        assert meta["conflict_notes"][0]["field"] == "weapon"
        assert meta["conflict_notes"][0]["canonical_value"] == "sword"

    async def test_skips_when_both_none(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()
        candidate = _mock_entity(content_json={})
        target = _mock_entity(content_json={})

        result = await svc._archive_conflicts(MagicMock(), candidate, target)

        assert result == 0
        svc._entity_repo.update.assert_not_called()

    async def test_skips_when_one_none(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()
        candidate = _mock_entity(content_json={"weapon": "sword"})
        target = _mock_entity(content_json={})

        result = await svc._archive_conflicts(MagicMock(), candidate, target)

        assert result == 0
        svc._entity_repo.update.assert_not_called()


class TestDedupInheritAliases:
    """EntityDedupService._inherit_aliases"""

    async def test_new_alias_added_to_target(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()

        candidate = _mock_entity(
            content_json={
                "aliases": [{"alias": "NewAlias"}],
            }
        )
        target = _mock_entity(
            content_json={
                "aliases": [{"alias": "ExistingAlias"}],
            }
        )

        count = await svc._inherit_aliases(MagicMock(), candidate, target)

        assert count == 1
        svc._entity_repo.update.assert_awaited_once()
        assert svc._entity_repo.update.call_args[0][1] is target
        call_data = svc._entity_repo.update.call_args[0][2]
        assert len(call_data.content_json["aliases"]) == 2

    async def test_duplicate_alias_skipped(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()

        candidate = _mock_entity(
            content_json={
                "aliases": [{"alias": "ExistingAlias"}],
            }
        )
        target = _mock_entity(
            content_json={
                "aliases": [{"alias": "ExistingAlias"}],
            }
        )

        count = await svc._inherit_aliases(MagicMock(), candidate, target)

        assert count == 0
        svc._entity_repo.update.assert_not_called()

    async def test_case_insensitive_dedup(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()

        candidate = _mock_entity(
            content_json={
                "aliases": [{"alias": "existingalias"}],
            }
        )
        target = _mock_entity(
            content_json={
                "aliases": [{"alias": "ExistingAlias"}],
            }
        )

        count = await svc._inherit_aliases(MagicMock(), candidate, target)

        assert count == 0  # case-insensitive match
        svc._entity_repo.update.assert_not_called()

    async def test_string_alias_from_candidate_wrapped(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()

        candidate = _mock_entity(
            content_json={
                "aliases": ["PlainString"],
            }
        )
        target = _mock_entity(
            content_json={
                "aliases": [{"alias": "Existing"}],
            }
        )

        count = await svc._inherit_aliases(MagicMock(), candidate, target)

        assert count == 1
        call_data = svc._entity_repo.update.call_args[0][2]
        # String alias stored as-is via append
        assert len(call_data.content_json["aliases"]) == 2


class TestDedupMigrateRelations:
    """EntityDedupService._migrate_relations"""

    async def test_self_loop_marked_deprecated(self) -> None:
        svc = EntityDedupService()
        svc._relation_repo = AsyncMock()
        cid = uuid.uuid4()
        rel = MagicMock()
        rel.id = uuid.uuid4()
        rel.source_id = cid
        rel.target_id = cid

        svc._relation_repo.get_all_for_entity = AsyncMock(return_value=[rel])

        result = await svc._migrate_relations(
            MagicMock(),
            str(uuid.uuid4()),
            str(cid),
            str(uuid.uuid4()),
        )

        assert result["migrated"] == 0
        assert result["deduplicated"] == 1
        assert result["created_self_loop_ids"] == []
        svc._relation_repo.deprecate_many.assert_awaited_once()
        call_args = svc._relation_repo.deprecate_many.call_args[0]
        assert call_args[1] == [rel.id]
        svc._relation_repo.update.assert_not_awaited()

    async def test_relation_redirected(self) -> None:
        svc = EntityDedupService()
        svc._relation_repo = AsyncMock()
        cid = uuid.uuid4()
        tid = uuid.uuid4()
        other_id = uuid.uuid4()
        rel = MagicMock()
        rel.id = uuid.uuid4()
        rel.source_id = cid
        rel.target_id = other_id

        svc._relation_repo.get_all_for_entity = AsyncMock(return_value=[rel])
        svc._relation_repo.find_duplicate_relation = AsyncMock(return_value=None)

        result = await svc._migrate_relations(
            MagicMock(),
            str(uuid.uuid4()),
            str(cid),
            str(tid),
        )

        assert result["migrated"] == 1
        assert result["deduplicated"] == 0

    async def test_duplicate_relation_updates_loaded_relation_objects(self) -> None:
        svc = EntityDedupService()
        svc._relation_repo = AsyncMock()
        cid = uuid.uuid4()
        tid = uuid.uuid4()
        other_id = uuid.uuid4()
        rel = MagicMock()
        rel.id = uuid.uuid4()
        rel.source_id = cid
        rel.target_id = other_id
        rel.relation_type = "ally"
        rel.description = "candidate edge"
        existing = MagicMock()
        existing.id = uuid.uuid4()
        existing.description = "existing edge"

        svc._relation_repo.get_all_for_entity = AsyncMock(return_value=[rel])
        svc._relation_repo.find_duplicate_relation = AsyncMock(return_value=existing)
        svc._relation_repo.update = AsyncMock()

        result = await svc._migrate_relations(
            MagicMock(),
            str(uuid.uuid4()),
            str(cid),
            str(tid),
        )

        assert result["migrated"] == 0
        assert result["deduplicated"] == 1
        assert svc._relation_repo.update.await_count == 2
        merge_call, deprecate_call = svc._relation_repo.update.await_args_list
        assert merge_call.args[1] is existing
        assert "existing edge" in merge_call.args[2].description
        assert "candidate edge" in merge_call.args[2].description
        assert deprecate_call.args[1] is rel
        assert deprecate_call.args[2].status == "deprecated"
        svc._relation_repo.update_endpoint.assert_not_awaited()


class TestDedupSyncCharacterOnMerge:
    """EntityDedupService._sync_character_on_merge"""

    async def test_no_candidate_char_returns_false(self) -> None:
        svc = EntityDedupService()
        char_repo = MagicMock()
        char_repo.get = AsyncMock(return_value=None)
        with patch.object(
            svc,
            "_sync_character_on_merge",
            wraps=svc._sync_character_on_merge,
            autospec=True,
        ) as _:
            # Cannot easily mock CharacterRepository directly since it's created inside
            pass

    async def test_missing_candidate_character_returns_false(self) -> None:
        svc = EntityDedupService()
        char_repo = AsyncMock()
        char_repo.get.return_value = None
        with patch(
            "modules.world.services.core.dedup_service.CharacterRepository",
            return_value=char_repo,
            autospec=True,
        ):
            result = await svc._sync_character_on_merge(
                MagicMock(),
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                str(uuid.uuid4()),
            )
        assert result is False

    async def test_both_characters_exist_merges_aliases(self) -> None:
        svc = EntityDedupService()
        char_repo = AsyncMock()
        candidate_char = MagicMock()
        candidate_char.aliases = [{"alias": "Nick"}]
        candidate_char.appearance = "tall"
        candidate_char.personality = "brave"
        candidate_char.desire = "power"
        candidate_char.fear = None
        candidate_char.secret = None
        candidate_char.weakness = None
        candidate_char.current_goal = None
        candidate_char.relationship_summary = None
        candidate_char.meta = {}

        target_char = MagicMock()
        target_char.aliases = [{"alias": "Original"}]
        target_char.appearance = "short"
        target_char.personality = "cunning"
        target_char.desire = None
        target_char.fear = None
        target_char.secret = None
        target_char.weakness = "pride"
        target_char.current_goal = None
        target_char.relationship_summary = None
        target_char.meta = {}

        char_repo.get.side_effect = [candidate_char, target_char]
        char_repo.update = AsyncMock()

        with patch(
            "modules.world.services.core.dedup_service.CharacterRepository",
            return_value=char_repo,
            autospec=True,
        ):
            result = await svc._sync_character_on_merge(
                MagicMock(),
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                str(uuid.uuid4()),
            )

        assert result is True
        char_repo.update.assert_awaited_once()
        assert char_repo.update.call_args[0][1] is target_char
        call_data = char_repo.update.call_args[0][2]
        # Aliases merged
        assert len(call_data.aliases) == 2
        # Text fields merged
        assert call_data.appearance == "short\n\ntall"
        assert call_data.personality == "cunning\n\nbrave"
        assert call_data.desire == "power"
        assert call_data.weakness == "pride"


def _scalar_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


class TestDedupMergeCandidate:
    """EntityDedupService.merge_candidate_into_entity — error boundaries"""

    async def test_dedup_service_has_no_direct_http_exception_dependency(self) -> None:
        source = (
            BACKEND_ROOT / "modules/world/services/core/dedup_service.py"
        ).read_text()

        assert "from fastapi import HTTPException" not in source
        assert "raise HTTPException" not in source

    async def test_merge_missing_target_raises_domain_not_found(self) -> None:
        svc = EntityDedupService()
        db = MagicMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(NotFoundError) as exc:
            await svc.merge_candidate_into_entity(
                db,
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                str(uuid.uuid4()),
            )

        assert exc.value.status_code == 404
        assert "Target entity" in exc.value.message

    async def test_merge_self_raises_domain_validation(self) -> None:
        svc = EntityDedupService()
        entity_id = uuid.uuid4()
        db = MagicMock()
        db.execute = AsyncMock(return_value=_scalar_result(_mock_entity(id=entity_id)))

        with pytest.raises(DomainValidationError) as exc:
            await svc.merge_candidate_into_entity(
                db,
                str(uuid.uuid4()),
                str(entity_id),
                str(entity_id),
            )

        assert exc.value.status_code == 400
        assert "itself" in exc.value.message

    async def test_merge_missing_candidate_raises_domain_not_found(self) -> None:
        svc = EntityDedupService()
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(_mock_entity()),
                _scalar_result(None),
            ]
        )

        with pytest.raises(NotFoundError) as exc:
            await svc.merge_candidate_into_entity(
                db,
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                str(uuid.uuid4()),
            )

        assert exc.value.status_code == 404
        assert "Candidate entity" in exc.value.message

    async def test_merge_rejects_entities_outside_requested_novel(self) -> None:
        svc = EntityDedupService()
        entity_novel_id = uuid.uuid4()
        target = _mock_entity(novel_id=entity_novel_id)
        candidate = _mock_entity(novel_id=entity_novel_id)
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(target),
                _scalar_result(candidate),
            ]
        )

        with pytest.raises(DomainValidationError) as exc:
            await svc.merge_candidate_into_entity(
                db,
                str(uuid.uuid4()),
                str(candidate.id),
                str(target.id),
            )

        assert exc.value.status_code == 400
        assert "requested novel" in exc.value.message

    async def test_merge_invalid_candidate_status_raises_domain_validation(self) -> None:
        svc = EntityDedupService()
        novel_id = uuid.uuid4()
        target = _mock_entity(novel_id=novel_id, status="canonical")
        candidate = _mock_entity(novel_id=novel_id, status="merged")
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(target),
                _scalar_result(candidate),
            ]
        )

        with pytest.raises(DomainValidationError) as exc:
            await svc.merge_candidate_into_entity(
                db,
                str(novel_id),
                str(candidate.id),
                str(target.id),
            )

        assert exc.value.status_code == 422
        assert "Merge candidate must be draft or candidate" in exc.value.message

    async def test_merge_updates_loaded_candidate_and_target_objects(self) -> None:
        svc = EntityDedupService()
        novel_id = uuid.uuid4()
        target = _mock_entity(novel_id=novel_id, status="draft")
        candidate = _mock_entity(novel_id=novel_id, status="candidate")
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(target),
                _scalar_result(candidate),
            ]
        )
        db.flush = AsyncMock()
        svc._entity_repo = AsyncMock()
        svc._entity_repo.update = AsyncMock()
        svc._inherit_aliases = AsyncMock(return_value=0)
        svc._migrate_relations = AsyncMock(
            return_value={
                "migrated": 0,
                "deduplicated": 0,
                "created_self_loop_ids": [],
            }
        )
        svc._sync_character_on_merge = AsyncMock(return_value=False)
        svc._merge_text_fields = AsyncMock()
        svc._archive_conflicts = AsyncMock(return_value=0)

        result = await svc.merge_candidate_into_entity(
            db,
            str(novel_id),
            str(candidate.id),
            str(target.id),
        )

        assert result.candidate_entity_id == str(candidate.id)
        assert result.target_entity_id == str(target.id)
        assert svc._entity_repo.update.await_count == 2
        first_call, second_call = svc._entity_repo.update.await_args_list
        assert first_call.args[1] is candidate
        assert first_call.args[2].status == "merged"
        assert second_call.args[1] is target
        assert second_call.args[2].status == "canonical"


class TestDedupFindDuplicates:
    """EntityDedupService.find_duplicates — edge cases"""

    async def test_candidate_not_found_returns_empty(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()
        svc._entity_repo.get = AsyncMock(return_value=None)
        db = MagicMock()

        result = await svc.find_duplicates(db, str(uuid.uuid4()), str(uuid.uuid4()))

        assert result == []


class TestDedupResolveCandidate:
    """EntityDedupService.resolve_candidate — decision paths"""

    async def test_candidate_not_found_raises_404(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()
        svc._entity_repo.get = AsyncMock(return_value=None)
        db = MagicMock()

        with pytest.raises(NotFoundError) as exc:
            await svc.resolve_candidate(db, str(uuid.uuid4()), str(uuid.uuid4()))
        assert exc.value.status_code == 404

    async def test_no_suggestions_promotes_to_canonical(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()
        candidate = _mock_entity(entity_type="character", name="NewOne", status="draft")
        svc._entity_repo.get = AsyncMock(return_value=candidate)
        svc.find_similar_entities = AsyncMock(return_value=[])
        svc._entity_repo.update = AsyncMock()
        db = MagicMock()
        db.flush = AsyncMock()

        result = await svc.resolve_candidate(db, str(uuid.uuid4()), str(uuid.uuid4()))

        assert result.action == "promoted"
        svc._entity_repo.update.assert_awaited_once()
        assert svc._entity_repo.update.call_args[0][1] is candidate

    async def test_high_confidence_auto_merges(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()
        candidate = _mock_entity(entity_type="character", name="Dupe", status="draft")
        svc._entity_repo.get = AsyncMock(return_value=candidate)
        svc._entity_repo.get = AsyncMock(return_value=candidate)

        from modules.world.schemas import DuplicateSuggestionResult

        svc.find_similar_entities = AsyncMock(
            return_value=[
                DuplicateSuggestionResult(
                    candidate_name="Dupe",
                    existing_entity_id=str(uuid.uuid4()),
                    existing_entity_name="Existing",
                    similarity_score=0.95,
                    match_method="exact_name",
                    action="merge_with_existing",
                ),
            ]
        )
        svc.merge_candidate_into_entity = AsyncMock(return_value=MagicMock())
        db = MagicMock()

        result = await svc.resolve_candidate(db, str(uuid.uuid4()), str(uuid.uuid4()))

        assert result.action == "merged"

    async def test_medium_confidence_returns_suggestions(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()
        candidate = _mock_entity(entity_type="character", name="Maybe", status="draft")
        svc._entity_repo.get = AsyncMock(return_value=candidate)

        from modules.world.schemas import DuplicateSuggestionResult

        svc.find_similar_entities = AsyncMock(
            return_value=[
                DuplicateSuggestionResult(
                    candidate_name="Maybe",
                    existing_entity_id=str(uuid.uuid4()),
                    existing_entity_name="Similar",
                    similarity_score=0.75,
                    match_method="lexical_fusion",
                    action="needs_user_decision",
                ),
            ]
        )
        db = MagicMock()

        result = await svc.resolve_candidate(db, str(uuid.uuid4()), str(uuid.uuid4()))

        assert result.action == "needs_user_decision"
        assert len(result.suggestions) == 1


class TestDedupFindSimilarEntities:
    """EntityDedupService.find_similar_entities — pipeline paths"""

    async def test_exact_name_match_returns_merge_suggestion(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()
        svc._entity_repo.find_similar_by_search_text = AsyncMock(return_value=[])
        svc._entity_repo.find_similar_by_embedding = AsyncMock(return_value=[])

        nid = str(uuid.uuid4())
        result = await svc.find_similar_entities(MagicMock(), nid, "Arthur")

        assert result == []  # no lexical candidates to compare

    async def test_with_lexical_candidates_scored(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()

        existing_entity = _mock_entity(
            name="ExistingEntity",
            entity_type="character",
            status="canonical",
            content_json={"aliases": []},
        )
        svc._entity_repo.find_similar_by_search_text = AsyncMock(
            return_value=[(existing_entity, 0.5)],
        )
        svc._entity_repo.find_similar_by_embedding = AsyncMock(return_value=[])

        nid = str(uuid.uuid4())
        # "Existing" is a substring of "ExistingEntity" → substring_match=0.85
        result = await svc.find_similar_entities(
            MagicMock(),
            nid,
            "Existing",
            entity_type="character",
        )

        assert len(result) >= 1
        assert result[0].match_method == "substring"

    async def test_skips_candidate_status_entity(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()

        pending_entity = _mock_entity(
            name="Pending",
            entity_type="character",
            status="pending",
        )
        svc._entity_repo.find_similar_by_search_text = AsyncMock(
            return_value=[(pending_entity, 0.5)],
        )
        svc._entity_repo.find_similar_by_embedding = AsyncMock(return_value=[])

        result = await svc.find_similar_entities(
            MagicMock(),
            str(uuid.uuid4()),
            "New",
        )

        assert result == []  # pending entities are skipped

    async def test_exact_alias_match_returns_merge(self) -> None:
        svc = EntityDedupService()
        svc._entity_repo = AsyncMock()

        existing = _mock_entity(
            name="Arthur",
            entity_type="character",
            status="canonical",
            content_json={"aliases": [{"alias": "King Arthur"}]},
        )
        svc._entity_repo.find_similar_by_search_text = AsyncMock(
            return_value=[(existing, 0.5)],
        )
        svc._entity_repo.find_similar_by_embedding = AsyncMock(return_value=[])

        result = await svc.find_similar_entities(
            MagicMock(),
            str(uuid.uuid4()),
            "New",
            aliases=["King Arthur"],
        )

        assert len(result) == 1
        assert result[0].match_method == "exact_alias"
        assert result[0].action == "merge_with_existing"


# ============================================================
# contracts.py — frozen dataclass construction
# ============================================================


class TestContractsConstruction:
    """Contract dataclasses — default values and frozen nature"""

    def test_core_entity_contract_defaults(self) -> None:
        c = CoreEntityContract(
            novel_id="n1", entity_id="e1", entity_type="char", name="Test"
        )
        assert c.novel_id == "n1"
        assert c.summary is None
        assert c.importance == 0.5
        assert c.importance_level == "normal"
        assert c.reveal_level == "author_only"
        assert c.status == "canonical"

    def test_core_entity_contract_frozen(self) -> None:
        c = CoreEntityContract(
            novel_id="n1", entity_id="e1", entity_type="char", name="T"
        )
        with pytest.raises(AttributeError):
            c.name = "New"  # type: ignore[misc]

    def test_event_contract_defaults(self) -> None:
        e = EventContract(novel_id="n1", entity_id="e1", entity_name="War")
        assert e.entity_type == "event"
        assert e.timeline_order == 0
        assert e.occurrence_time_label is None
        assert e.location_entity_id is None
        assert e.location_name is None

    def test_entity_relation_contract_defaults(self) -> None:
        r = EntityRelationContract(
            novel_id="n1",
            relation_id="r1",
            source_id="s1",
            target_id="t1",
            relation_type="friend",
        )
        assert r.description is None
        assert r.strength == 0.5
        assert r.quote is None
        assert r.status == "canonical"

    def test_entity_revision_contract_defaults(self) -> None:
        r = EntityRevisionContract(entity_id="e1", revision_id="r1")
        assert r.revision_reason == "ai_import"
        assert r.created_at is None

    def test_character_contract_defaults(self) -> None:
        c = CharacterContract(character_id="c1", name="Hero")
        assert c.role is None
        assert c.current_goal is None
        assert c.current_state is None
        assert c.current_emotion is None
        assert c.stance is None
        assert c.voice_style is None
        assert c.behavior_rules == []
        assert c.relationship_summary is None

    def test_character_knowledge_contract_defaults(self) -> None:
        k = CharacterKnowledgeContract(
            target_type="entity",
            target_id="e1",
            knowledge_level="partial",
        )
        assert k.known_content is None
        assert k.misconception is None

    def test_merge_result_defaults(self) -> None:
        m = MergeResult(target_entity_id="t1", candidate_entity_id="c1")
        assert m.aliases_inherited == 0
        assert m.relations_migrated == 0
        assert m.relations_deduplicated == 0
        assert m.self_loops_cleaned == 0
        assert m.character_synced is False
        assert m.conflicts_archived == 0

    def test_resolve_result_defaults(self) -> None:
        r = ResolveResult(action="promoted")
        assert r.merge_result is None
        assert r.promoted_entity_id is None
        assert r.suggestions == []


# ============================================================
# tasks.py — world_entity_extraction handler
# ============================================================


class TestHandleWorldEntityExtraction:
    async def test_happy_path_calls_service_and_returns_result(self) -> None:
        task = MagicMock()
        task.meta = {
            "novel_id": str(uuid.uuid4()),
            "start_chapter": 1,
            "end_chapter": 3,
            "batch_size": 5,
        }

        mock_result = MagicMock()
        mock_result.total_chapters = 3
        mock_result.total_created = 5
        mock_result.total_skipped = 2
        mock_result.failed_chapters = []
        mock_result.items = []

        with patch(
            "modules.world.tasks.EntityExtractionService",
            autospec=True,
        ) as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc_cls.return_value = mock_svc
            mock_svc.extract_entities_from_chapters = AsyncMock(return_value=mock_result)

            result = await handle_world_entity_extraction(MagicMock(), task)

        assert result["total_chapters"] == 3
        assert result["total_created"] == 5
        assert result["total_skipped"] == 2
        assert result["failed_chapters"] == []
        assert result["items"] == []

    async def test_missing_novel_id_raises_value_error(self) -> None:
        task = MagicMock()
        task.meta = {"start_chapter": 1}

        with pytest.raises(ValueError, match="novel_id is required"):
            await handle_world_entity_extraction(MagicMock(), task)

    async def test_default_values_when_meta_partial(self) -> None:
        task = MagicMock()
        task.meta = {"novel_id": str(uuid.uuid4())}

        mock_result = MagicMock()
        mock_result.total_chapters = 0
        mock_result.total_created = 0
        mock_result.total_skipped = 0
        mock_result.failed_chapters = []
        mock_result.items = []

        with patch(
            "modules.world.tasks.EntityExtractionService",
            autospec=True,
        ) as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc_cls.return_value = mock_svc
            mock_svc.extract_entities_from_chapters = AsyncMock(return_value=mock_result)

            result = await handle_world_entity_extraction(MagicMock(), task)

        # Defaults: start=1, end=10, batch=5
        args, kwargs = mock_svc.extract_entities_from_chapters.call_args
        assert kwargs["start_chapter"] == 1
        assert kwargs["end_chapter"] == 10
        assert kwargs["batch_size"] == 5
        assert result is not None

    async def test_context_result_refs_are_attached_in_one_batch(self) -> None:
        task = MagicMock()
        task.id = uuid.uuid4()
        task.meta = {
            "novel_id": str(uuid.uuid4()),
            "context_confirmation_id": str(uuid.uuid4()),
        }

        mock_result = MagicMock()
        mock_result.total_chapters = 1
        mock_result.total_created = 2
        mock_result.total_skipped = 0
        mock_result.failed_chapters = []
        mock_result.items = [{"id": "entity-1"}, {"id": "entity-2"}]

        with (
            patch(
                "modules.world.tasks.EntityExtractionService", autospec=True
            ) as mock_svc_cls,
            patch(
                "modules.world.tasks.context_facade.compile_from_confirmation",
                autospec=True,
            ),
            patch(
                "modules.world.tasks.context_facade.attach_result_refs",
                autospec=True,
            ) as mock_attach_refs,
            patch(
                "modules.world.tasks.context_facade.attach_result_ref",
                autospec=True,
            ) as mock_attach_ref,
        ):
            mock_svc = AsyncMock()
            mock_svc_cls.return_value = mock_svc
            mock_svc.extract_entities_from_chapters = AsyncMock(return_value=mock_result)

            await handle_world_entity_extraction(MagicMock(), task)

        mock_attach_refs.assert_awaited_once_with(
            ANY,
            confirmation_id=task.meta["context_confirmation_id"],
            result_refs=[
                {"type": "world_entity", "id": "entity-1"},
                {"type": "world_entity", "id": "entity-2"},
            ],
            status="done",
        )
        mock_attach_ref.assert_not_awaited()
