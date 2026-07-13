# TDD Test Plan: Refactored Entity Extraction System

> **Historical test-refactor plan**: this records a previous extraction design and test backlog. It is not a current test contract or implementation guide; use the active module tests, `testing-guide.md`, and current imports/world code instead. Do not backfill this plan after code changes.

## Overview

The extraction pipeline was refactored from batch-mode (5 chapters per LLM call) to single-chapter sequential mode with 3-layer embedding dedup and 4 action handlers. This plan covers backfill verification tests for all changed behaviors.

## File Structure Changes

| Category | File | Action |
|----------|------|--------|
| 1 | `tests/unit/__init__.py` | **New** (empty) |
| 1 | `tests/unit/test_extraction_service.py` | **New** |
| 2 | `tests/unit/test_entity_service.py` | **New** |
| 3 | `tests/unit/test_project_settings.py` | **New** |
| 4 | `tests/integration/test_extraction_pipeline.py` | **Modify** (fix `TestAmbiguousReferences`) |
| 5 | `tests/e2e/test_extraction_real_file.py` | **Optional addition** |

---

## Category 1: Unit Tests for EntityExtractionService (new file)

File: `tests/unit/test_extraction_service.py`
Class: `TestEntityExtractionService`

### Shared Fixtures

#### `service(db_session)` fixture
```python
@pytest_asyncio.fixture
async def service(self, db_session: AsyncSession):
    draft_provider = mock.AsyncMock(spec=DraftProvider)
    draft_provider.load_chapters.return_value = [
        {
            "chapter_index": 1,
            "title": "Test Chapter",
            "content": "Test content for extraction.",
        },
    ]
    svc = EntityExtractionService(draft_provider=draft_provider)
    return svc
```

#### `mock_env` context manager or fixture pattern

Pattern (follows `tests/test_outline_api.py` lines 230-232):
```python
from unittest import mock
from modules.world.schemas import (
    DuplicateSuggestionResult, WorldContextBundle, WorldEntityContext,
)
```

Mock setup for each test uses `mock.patch("path.to.module")` as a context manager.

### Test Entities (`_TestEntity` / `_TestOutput`)

Since `_ExtractionOutput` and `_ExtractedEntity` are defined inside the method body, replicate them as test doubles:

```python
class _TestExtractedEntity(BaseModel):
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

class _TestExtractionOutput(BaseModel):
    entities: list[_TestExtractedEntity] = []
```

---

### TC-1.1: Single chapter, all entities create_new

- **What**: 2 entities with `suggested_action="create_new"`, no dedup match
- **Mocks**:
  - `modules.world.facade.get_world_context` → return `WorldContextBundle(novel_id="x", entities=[...])` with 1 existing entity
  - `infrastructure.llm.prompt_loader.load_prompt` → return `"[mock prompt]"` 
  - `LLMClient` constructor → return mock client
  - `LLMClient.generate_structured` → return `_TestExtractionOutput(entities=[...])`
  - `LLMClient.generate_embedding` → return `[0.1, 0.2, 0.3]` (valid vector)
  - `EntityDedupService.find_similar_entities` → return `[]` (no match)
  - `CoreEntityRepository.create` → return mock entity with `id=uuid4()`
- **Assert**:
  ```python
  result = await svc.extract_entities_from_chapters(db, novel_id, 1, 1)
  assert result.total_created == 2
  assert result.total_skipped == 0
  assert result.failed_chapters == []
  assert result.total_chapters == 1
  assert len(result.items) == 2
  assert result.items[0]["name"] == "Alice"
  assert result.items[0]["batch_id"] is not None
  ```

---

### TC-1.2: Single chapter, ignore action

- **What**: 1 entity with `suggested_action="ignore"`
- **Mocks**: Same as TC-1.1 but entity has `suggested_action="ignore"`
- **Assert**:
  ```python
  assert result.total_created == 0
  assert result.total_skipped == 1
  assert result.failed_chapters == []
  ```
- **Verify**: `repo.create` was NOT called

---

### TC-1.3: Single chapter, temporary_only action

- **What**: 1 entity with `suggested_action="temporary_only"`, `source_chapter=1`
- **Mocks**: Same as TC-1.1 with `suggested_action="temporary_only"`
- **Assert**:
  ```python
  assert result.total_created == 1
  assert result.total_skipped == 0
  ```
- **Verify** repo.create was called with `CoreEntityCreate` where:
  - `content_json["_meta"]["temporary"]` is `True`
  - `content_json["_meta"]["source_chapter_index"]` is set
  - `content_json["_meta"]["batch_id"]` is present
  - `content_json["_meta"]["auto_ingested"]` is `True`

---

### TC-1.4: link_to_existing with successful resolution

- **What**: 1 entity with `suggested_action="link_to_existing"`, `suggested_existing_entity_name="ExistingChar"`
- **Mocks**:
  - `_find_entity_by_name` return value: `mock.MagicMock()` with `.id` = UUID string
  - Or patch: `modules.world.facade.find_entity_id_by_name` → return `str(uuid4())`
- **Assert**:
  ```python
  assert result.total_created == 0
  assert result.total_skipped == 1
  ```
- **Verify**: `_sync_aliases_to_existing` was called (if entity has aliases)

---

### TC-1.5: link_to_existing with failed resolution

- **What**: 1 entity with `suggested_action="link_to_existing"`, `suggested_existing_entity_name="NonExistent"`
- **Mocks**: `find_entity_id_by_name` → return `None`
- **Assert**:
  ```python
  assert result.total_created == 0
  assert result.total_skipped == 1  # skipped after unresolvable link
  ```
- **Verify**: `logger.warning` was called (use `mock.patch("modules.world.services.extraction_service.logger")` and check `logger.warning.called`)

---

### TC-1.6: LLMInvalidResponseError

- **What**: LLM raises `LLMInvalidResponseError` for chapter 1
- **Mocks**: `LLMClient.generate_structured.side_effect = LLMInvalidResponseError("bad response")`
- **Assert**:
  ```python
  assert result.failed_chapters == [1]
  assert result.total_created == 0
  ```
- **Verify**: `logger.warning` called with mention of chapter index and "4 attempts"

---

### TC-1.7: Generic Exception from LLM

- **What**: LLM raises e.g. `ValueError("connection lost")` 
- **Mocks**: `LLMClient.generate_structured.side_effect = ValueError("connection lost")`
- **Assert**:
  ```python
  assert result.failed_chapters == [1]
  ```
- **Verify**: `logger.error` was called with `exc_info=True`

---

### TC-1.8: Multiple chapters, sequential processing

- **What**: 2 chapters, each returns different entities
- **Mocks**:
  - `draft_provider.load_chapters` returns `[{"chapter_index":1,...}, {"chapter_index":2,...}]`
  - `LLMClient.generate_structured` returns different outputs each call (`side_effect` pattern)
  - 1st call: 1 entity "Alice", 2nd call: 1 entity "Bob"
- **Assert**:
  ```python
  assert result.total_created == 2
  assert result.total_chapters == 2
  assert result.failed_chapters == []
  ```
- **Verify** `load_prompt` was called TWICE with different `existing_entities_context` values:
  - 1st call: initial context
  - 2nd call: context includes "Alice" from chapter 1

---

### TC-1.9: Name embedding dedup (Layer 1)

- **What**: entity with `suggested_action="create_new"`, Layer 1 returns high-confidence match
- **Mocks**:
  - `generate_embedding` → return valid vector
  - `find_similar_entities` 1st call (for name) → return `[DuplicateSuggestionResult(similarity_score=0.95, ...)]`
- **Assert**:
  ```python
  assert result.total_created == 0
  assert result.total_skipped == 1  # matched via name embedding
  ```

---

### TC-1.10: Content embedding dedup (Layer 2)

- **What**: entity with `suggested_action="create_new"`, Layer 1 empty, Layer 2 matches
- **Mocks**:
  - `generate_embedding` 1st call (name) → return valid vector
  - `find_similar_entities` 1st call (name) → return `[]` 
  - `generate_embedding` 2nd call (content) → return valid vector
  - `find_similar_entities` 2nd call (content) → return `[DuplicateSuggestionResult(similarity_score=0.92, ...)]`
- **Assert**:
  ```python
  assert result.total_created == 0
  assert result.total_skipped == 1  # matched via content embedding
  ```

---

### TC-1.11: Empty name skipped

- **What**: entity with `name=""` or `name="   "`
- **Mocks**: Entity has `name=""`
- **Assert**:
  ```python
  assert result.total_skipped == 1
  assert result.total_created == 0
  ```
- **Verify**: No LLM calls for dedup, no repo.create calls

---

### TC-1.12: Empty entities list from LLM

- **What**: LLM returns `_TestExtractionOutput(entities=[])`
- **Assert**:
  ```python
  assert result.total_created == 0
  assert result.total_skipped == 0
  assert result.failed_chapters == []
  ```
- **Verify**: `load_prompt` was called only ONCE (no context update since no new entities)

---

### TC-1.13: Embedding generation failure

- **What**: `generate_embedding` raises Exception → returns `None`
- **Mocks**:
  - `LLMClient.generate_embedding.side_effect = Exception("API error")`
  - Or: `LLMClient.generate_embedding.return_value = None`
- **Assert**:
  - Dedup layers 1 and 2 are skipped
  - Entity is created (falls through to create)
  - `logger.warning` called for embedding failure

---

### TC-1.14: Aliases synced on link_to_existing

- **What**: entity with `suggested_action="link_to_existing"`, `aliases=[{"alias":"Nick", "type":"nickname"}]`
- **Mocks**: `find_entity_id_by_name` returns a valid entity_id
- **Verify**: `CoreEntityRepository.get` was called (via `_sync_aliases_to_existing`)
- **Verify**: `db.flush()` was called (inside `_sync_aliases_to_existing`)

---

### TC-1.15: Aliases synced on name dedup match

- **What**: entity with aliases, Layer 1 matches high-confidence
- **Mocks**: `find_similar_entities` returns high-confidence match
- **Verify**: `_sync_aliases_to_existing` called (assert via repo.get being called)

---

### TC-1.16: repo.create raises ValueError

- **What**: `CoreEntityRepository.create` raises `ValueError`
- **Mocks**: `repo.create.side_effect = ValueError("invalid data")`
- **Assert**:
  ```python
  assert result.total_created == 0
  assert result.total_skipped == 1  # caught and skipped
  ```
- **Verify**: Processing continues to next entity/chapter

---

### TC-1.17: Context accumulation across chapters

- **What**: 3 chapters, verify context grows
- **Mocks**:
  - Chapter 1: creates "Alice" 
  - Chapter 2: creates "Bob"  
  - Chapter 3: creates "Charlie"
  - Use `side_effect` on `load_prompt` to capture arguments
- **Assert**:
  - `load_prompt` called 3 times
  - 1st call context: starts with initial entities (no new ones yet)
  - 2nd call context: includes "Alice" from chapter 1
  - 3rd call context: includes "Alice" and "Bob"
  - Final: `result.total_created == 3`

---

### TC-1.18: batch_size parameter ignored

- **What**: call with `batch_size=100`, same behavior as default
- **Assert**: Same results as TC-1.1 (no error, batch_size is silently ignored)
- **Purpose**: Verify API backward compatibility

---

### TC-1.19: Empty chapters raises HTTPException

- **What**: `_load_chapters` returns `[]`
- **Mocks**: `draft_provider.load_chapters.return_value = []`
- **Assert**: `pytest.raises(HTTPException, match="未找到章节")`

---

### TC-1.20: Non-dict alias entries filtered

- **What**: entity has `aliases=[{"alias":"Good","type":"name"}, "bad_string", None]`
- **Assert**: Only dict entries with `alias` key are processed
- **Verify**: repo.create called with `content_json["aliases"]` containing only `[{"alias":"Good","type":"name"}]`

---

### TC-1.21: link_to_existing without suggested_existing_entity_name

- **What**: entity with `suggested_action="link_to_existing"` but `suggested_existing_entity_name=None`
- **Path through code**: Skips the direct `_find_entity_by_name` branch (line 189-191 condition fails). Falls through to Layer 1 dedup. If no dedup match, and still `link_to_existing` at line 264, logs warning and skips.
- **Mocks**:
  - `find_similar_entities` returns `[]`
- **Assert**:
  ```python
  assert result.total_skipped == 1  # unresolvable link_to_existing
  ```
- **Verify**: `logger.warning` called with "could not resolve"

---

### TC-1.22: Content embedding not generated when summary and public_info empty

- **What**: entity with `summary=""` and `public_info=""`, so `content_text` is empty
- **Path through code**: Line 239 `if content_text:` is `False`, so content embedding is skipped
- **Assert**: Entity falls through to create (if `suggested_action` is `create_new`)

---

## Category 2: Unit Tests for get_entity_context Temporary Filtering

File: `tests/unit/test_entity_service.py`
Class: `TestEntityContextTemporaryFilter`

The method `WorldEntityService.get_entity_context()` (lines 77-129 of `entity_service.py`) filters temporary entities when `current_chapter` is provided.

### Test Approach

Test by creating `CoreEntity` rows in SQLite with various `content_json._meta` configurations, then call `WorldEntityService.get_entity_context()` and assert on the returned bundle.

Since `tests/CLAUDE.md` says "notest through facades", use `modules.world.facade.get_world_context` (which delegates to the service internally). Or, if more precise mocking is needed, import the service directly (since we're testing internal business logic, not making assertions about DB state through repositories).

**Preferred**: Test through `modules.world.facade.get_world_context` (this follows the rule).

---

### TC-2.1: No current_chapter, all entities returned

- **Setup**: Create 3 entities (2 temporary, 1 canonical)
- **Call**: `get_world_context(db, novel_id, limit=100)`
- **Assert**: All 3 entities in response

### TC-2.2: Temporary entity within expiry, included

- **Setup**: 
  - Entity 1: `content_json={"_meta": {"temporary": True, "source_chapter_index": 1}}`
  - Entity 2: non-temporary
- **Call**: `get_world_context(db, novel_id, current_chapter=5)` 
- **Assert**: Both entities included (5-1=4 <= default expiry 30)

### TC-2.3: Temporary entity expired, excluded

- **Setup**:
  - Entity 1: `content_json={"_meta": {"temporary": True, "source_chapter_index": 1}}`
- **Call**: `get_world_context(db, novel_id, current_chapter=40)`
- **Assert**: Entity 1 excluded (40-1=39 > default expiry 30)

### TC-2.4: Custom expiry from project.settings

- **Setup**:
  - Create `Project` with `settings={"temporary_entity_expiry_chapters": 5}`
  - Entity 1: temporary, source_chapter_index=1
- **Call**: `get_world_context(db, novel_id, current_chapter=7)`
- **Assert**: Entity 1 excluded (7-1=6 > custom expiry 5)

### TC-2.5: Non-temporary entities not filtered

- **Setup**:
  - Entity 1: `content_json={"_meta": {"temporary": False, "source_chapter_index": 1}}`
  - Entity 2: no `_meta` at all
- **Call**: `get_world_context(db, novel_id, current_chapter=100)`
- **Assert**: Both entities included (filter only applies when `temporary==True`)

### TC-2.6: Temporary entity without source_chapter_index, not filtered

- **Setup**: Entity 1: `content_json={"_meta": {"temporary": True}}` (no `source_chapter_index`)
- **Call**: `get_world_context(db, novel_id, current_chapter=40)`
- **Assert**: Entity 1 included (safe guard for inconsistent data)

### TC-2.7: Project not found, uses default expiry 30

- **Setup**: No `Project` row in DB (delete the project), Entity 1 temporary with source_chapter_index=1
- **Call**: `get_world_context(db, novel_id, current_chapter=50)`
- **Assert**: Entity 1 excluded (50-1=49 > default 30)
- **Purpose**: Verify the `if project is not None` else-branch works

---

## Category 3: Unit Tests for Project Settings

File: `tests/unit/test_project_settings.py`
Class: `TestProjectSettings`

Test the `settings` JSONB column on the `Project` model via facade/API.

### TC-3.1: Create project with settings

- **Call**: Create project via `POST /api/projects` with `{"title": "T", "settings": {"temporary_entity_expiry_chapters": 10}}`
- **Assert**: Response has `"settings": {"temporary_entity_expiry_chapters": 10}`

### TC-3.2: Create project without settings

- **Call**: Create project via `POST /api/projects` with `{"title": "T"}` (no `settings`)
- **Assert**: Response has `"settings": {}` (default)

### TC-3.3: Create project with settings=None

- **Call**: Create project via `POST /api/projects` with `{"title": "T", "settings": null}`
- **Assert**: Response has `"settings": {}` (coerced to empty dict)

### TC-3.4: Update project settings

- **Call**: Create project, then update via `PUT /api/projects/{id}` with `{"settings": {"expiry": 5}}`
- **Assert**: GET response returns `"settings": {"expiry": 5}`

### TC-3.5: Settings serialized in project context

- **Setup**: Project with `settings={"temporary_entity_expiry_chapters": 10}`
- **Call**: `modules.project.project.get_project_context(db, novel_id)`
- **Assert**: Response has `settings == {"temporary_entity_expiry_chapters": 10}`

---

## Category 4: Fix Integration Test AmbiguousReferences

File: `tests/integration/test_extraction_pipeline.py`
Class: `TestAmbiguousReferences`

### Fix 4.1: Update `test_vague_references_flagged_or_skipped` (line 370-378)

**Current code** (lines 371-378):
```python
suggested_action in (
    "needs_user_decision",
    "ignore",
    "temporary_only",
),
```

**Change to**:
```python
suggested_action in (
    "create_new",
    "link_to_existing",
    "ignore",
    "temporary_only",
),
```

**Rationale**: The prompt's `suggested_action` enum no longer includes `needs_user_decision`. The valid values are: `create_new`, `link_to_existing`, `ignore`, `temporary_only`.

### Fix 4.2: Superseded — legacy World facade removed

The public extraction path is now the imports `world_objects` stage. Direct
service tests may still assert `ExtractionResult.failed_chapters`; no facade
dictionary contract remains.

### Fix 4.3: Optional — Add note about brittleness

The `test_vague_references_flagged_or_skipped` test depends on LLM behavior, which is probabilistic. Consider adding a `pytest.mark.skipif` flag or a comment noting that this test may need to be periodically verified for accuracy against the current LLM model.

---

## Category 5: E2E Smoke Tests (Optional)

File: `tests/e2e/test_extraction_real_file.py` (add new class)

### TC-5.1: Extraction returns failed_chapters in response

```python
class TestExtractionSmoke:
    """Smoke tests for extraction (real LLM calls)"""
    
    async def test_extraction_returns_failed_chapters(
        self, db_session: AsyncSession, novel_id: str
    ):
        result = await EntityExtractionService().extract_entities_from_chapters(
            db_session, novel_id, start_chapter=1, end_chapter=1
        )
        assert isinstance(result.failed_chapters, list)
```

### TC-5.2: Multi-chapter extraction with real LLM

- Write 2 chapter drafts
- Run extraction on both chapters
- Verify total_chapters==2
- Verify failed_chapters is a list (likely empty for well-formed text)

---

## Mock Reference: Standard Patterns

### Mocking LLMClient.generate_structured

```python
with mock.patch("infrastructure.llm.client.LLMClient") as mock_llm_cls:
    mock_client = mock.AsyncMock()
    mock_llm_cls.return_value = mock_client
    mock_client._settings.llm_model = "gpt-4o"
    mock_client.generate_structured.return_value = _TestExtractionOutput(
        entities=[_TestExtractedEntity(name="Alice", suggested_action="create_new")]
    )
```

### Mocking LLMClient.generate_embedding

```python
mock_client.generate_embedding.return_value = [0.1, 0.2, 0.3, 0.4, 0.5]
```

### Mocking get_world_context

```python
with mock.patch("modules.world.facade.get_world_context") as mock_ctx:
    from modules.world.schemas import WorldContextBundle, WorldEntityContext
    mock_ctx.return_value = WorldContextBundle(
        novel_id="test",
        entities=[WorldEntityContext(
            entity_id=str(uuid4()),
            name="白砚",
            entity_type="character",
            summary="主角",
            status="canonical",
        )],
        total_count=1,
        reveal_mode="author_safe",
    )
```

### Mocking DedupService.find_similar_entities

```python
from modules.world.schemas import DuplicateSuggestionResult

mock_high_conf = DuplicateSuggestionResult(
    candidate_name="Alice",
    existing_entity_id=str(uuid4()),
    existing_entity_name="Alice",
    similarity_score=0.95,  # >= SIMILARITY_HIGH_CONFIDENCE (0.88)
    match_method="exact_name",
    action="merge_with_existing",
)
```

### Mocking CoreEntityRepository.create

```python
mock_entity = mock.MagicMock()
mock_entity.id = uuid.uuid4()
mock_entity.name = "Alice"
mock_entity.entity_type = "character"
service._entity_repo = mock.AsyncMock()
service._entity_repo.create.return_value = mock_entity
```

---

## Run Commands

```bash
# Category 1: Unit tests for EntityExtractionService
pytest tests/unit/test_extraction_service.py -v

# Single test
pytest tests/unit/test_extraction_service.py::TestEntityExtractionService::test_single_chapter_all_create_new -xvs

# Category 2: Entity context temporary filtering
pytest tests/unit/test_entity_service.py -v

# Category 3: Project settings
pytest tests/unit/test_project_settings.py -v

# Category 4: Integration test fixes
pytest tests/integration/test_extraction_pipeline.py -v -k "TestAmbiguousReferences"

# Full integration test suite
pytest tests/integration/test_extraction_pipeline.py -v

# Category 5: E2E smoke
pytest tests/e2e/test_extraction_real_file.py -v -k "TestExtractionSmoke"
```

---

## Summary of Assertion Patterns by Method

| Method | Assertion Pattern |
|--------|------------------|
| `extract_entities_from_chapters()` return value | `assert result.total_created == N`, `result.total_skipped == N`, `result.failed_chapters == [...]`, `result.items[0]["name"] == "..."` |
| LLM error handling | `assert ch_idx in result.failed_chapters` |
| Context accumulation | Capture `load_prompt` call args; verify 2nd+ calls contain entities from previous chapters |
| Dedup layers | Assert total_skipped increments without repo.create calls |
| Temporary entity filtering | Assert entity count in `WorldContextBundle.entities` when `current_chapter` varies |
| imports `world_objects` stage | Assert workflow phase, quality status, and failed-scene diagnostics |

## Edge Cases Explicitly Covered

| Edge Case | TC |
|-----------|-----|
| Empty chapter list → HTTPException | TC-1.19 |
| Empty name string | TC-1.11 |
| Empty entities list from LLM | TC-1.12 |
| LLM returns None | TC-1.12 (None also caught by same branch) |
| Embedding API failure → graceful fallback | TC-1.13 |
| repo.create ValueError → skip, continue | TC-1.16 |
| link_to_existing without suggested name | TC-1.21 |
| Empty summary/public_info → skip content embedding | TC-1.22 |
| Malformed aliases (non-dict entries) | TC-1.20 |
| temporary entity without source_chapter_index | TC-2.6 |
| Project not found → default expiry | TC-2.7 |
