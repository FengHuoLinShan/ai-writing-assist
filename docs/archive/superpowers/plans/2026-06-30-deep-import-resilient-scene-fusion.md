# Deep Import Resilient Scene Fusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement resilient deep import: two-round Scene prefetch, Phase 1a reinforcement, Phase 1b fusion/reducer, interruption recovery, provenance-safe writes, triage filters, and Playwright acceptance coverage.

**Architecture:** Keep FastAPI + PostgreSQL async task queue + vanilla JS. Split current Phase 1 from “LLM batch directly writes Scene” into “intermediate candidates -> reducer -> idempotent Scene commit”. Recovery semantics remain in existing task statuses plus `result/meta` flags; no new queue, task status enum, or runtime infrastructure.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Pydantic v2, PostgreSQL/SQLite test mode, pytest, vanilla JS, Playwright.

---

## Source Documents

- Spec: `docs/superpowers/specs/2026-06-30-deep-import-resilient-scene-fusion-design.md`
- Playwright acceptance: `docs/superpowers/acceptance/2026-06-30-deep-import-resilient-scene-fusion-playwright-acceptance.md`
- Module docs: `backend/modules/imports/CLAUDE.md`, `CLAUDE.md`, `AGENTS.md`

## Implementation Order

This is a large change. Do not start with UI. The correct order is:

1. Backend progress/result contract.
2. Intermediate Scene candidate model and retry diagnostics.
3. Phase 0 / Phase 1a / Phase 1b.
4. Scene commit provenance and idempotency.
5. Recovery and abandon semantics.
6. Phase 2 / Phase 3 provenance and cleanup.
7. Backend filtering APIs.
8. Frontend progress/recovery/filtering/manual fusion.
9. Playwright and real LLM acceptance.

## Global Guardrails

- Do not add a new task status enum. Keep `pending / running / done / failed / cancelled`.
- Do not create a new recovery task. Continuing recovery must reuse the original `deep_import` task.
- Do not let worker auto-continue stale `deep_import`; it may only mark it recoverable.
- Do not write Phase 0 or Phase 1a candidates to the formal `Scene` table.
- Do not silently overwrite or hard-delete user-visible assets.
- Do not directly import other modules' repositories/services from imports production code unless it is already an allowed composition-root/test exception. Add or extend facade functions instead.
- Preserve `novel_id` isolation in every query and cleanup.

---

## File Map

### Backend Imports

- Modify: `backend/modules/imports/workflow_schemas.py` — progress/result/checkpoint schema.
- Modify: `backend/modules/imports/workflow.py` — orchestrate Phase 0 -> 1a -> 1b -> commit -> Phase 2 -> Phase 3.
- Modify: `backend/modules/imports/orchestrator.py` — task result shaping, duplicate/deprecate policy, resume/abandon policy.
- Modify: `backend/modules/imports/api.py` — continue/abandon recovery endpoints and `/deep/resume` semantic correction.
- Modify: `backend/modules/imports/tasks.py` — retain compatibility, route deep import task handling through orchestrator.
- Modify: `backend/modules/imports/scene_segmentation.py` — stop formal Scene writes from candidate phases; reuse chapter loading and LLM prompting.
- Modify: `backend/modules/imports/llm_schemas.py` — add intermediate candidate/reducer schemas.
- Create: `backend/modules/imports/deep_import_retry.py` — classify LLM failures and collect retry diagnostics.
- Create: `backend/modules/imports/scene_candidates.py` — batch/window/candidate dataclasses or Pydantic models.
- Create: `backend/modules/imports/scene_prefetch.py` — Phase 0 two-round prefetch.
- Create: `backend/modules/imports/scene_reinforcement.py` — Phase 1a text-backed candidate reinforcement.
- Create: `backend/modules/imports/scene_fusion.py` — Phase 1b windowed reducer.
- Create: `backend/modules/imports/scene_commit.py` — provenance key, idempotent formal Scene writes.

### Backend Task Queue

- Modify: `backend/infrastructure/tasks/worker.py` — stale deep_import detection without auto-resume.
- Modify: `backend/run_worker.py` — trigger interrupted task scan at startup and loop.
- Modify: `backend/infrastructure/tasks/api.py` — expose task result/meta recovery fields unchanged.

### Backend Phase 2 / 3 / Assets

- Modify: `backend/modules/imports/scene_entity_extraction.py` — per Scene checkpoint and provenance.
- Modify: `backend/modules/world/api.py`, `backend/modules/world/schemas.py`, `backend/modules/world/repositories.py`, `backend/modules/world/services/entity_stats_service.py` — world object filters and provenance query support.
- Modify: `backend/modules/outline/models.py`, `backend/modules/outline/schemas.py`, `backend/modules/outline/repositories.py`, `backend/modules/outline/api.py`, `backend/modules/outline/generation/persister.py` — structure asset provenance/filtering.
- Create: `backend/alembic/versions/20260630_add_deep_import_structure_provenance.py` — add `provenance_meta` JSON columns to `plot_threads`, `outline_arcs`, `foreshadowing_plans`, and `reveal_plans`.

### Frontend

- Modify: `frontend-console/api.js` — recovery APIs, filter query params, manual fusion APIs.
- Modify: `frontend-console/views/writingView.js` — resilient progress, interruption prompts, continue/abandon.
- Modify: `frontend-console/shared/workflowProgress.js` — normalize new deep import result shape.
- Modify: `frontend-console/shared/progressRenderer.js` — display quality stats/current position.
- Modify: `frontend-console/styles.css` — restrained alive/glow state and responsive filter chips.
- Modify: `frontend-console/views/sceneWorkbenchView.js` — filters, multi-select, manual LLM fusion save choices.
- Modify: `frontend-console/views/worldView.js`, `frontend-console/router.js` — world-object filter UI and independent bug fix for forced map navigation.
- Modify: `frontend-console/views/outlineView.js` — structure asset filters and Phase 3 partial state.

### Tests and Acceptance

- Modify/add backend tests under `backend/modules/imports/tests/`.
- Modify/add outline/world/memory tests for filters/provenance.
- Create: `frontend-console/e2e/deep-import-resilient.spec.js`.
- Create: `frontend-console/e2e/deep-import-resilient-worker.spec.js`.
- Create or extend: `frontend-console/e2e/world-objects.spec.js`.
- Create optional real LLM test: `backend/modules/imports/tests/test_deep_import_real_llm.py`.

---

## Task 0: Baseline And Safety Check

**Files:** none.

- [ ] **Step 0.1: Inspect dirty worktree before editing**

Run:

```bash
git status --short
```

Expected: note existing unrelated changes. Do not revert them.

- [ ] **Step 0.2: Run current import workflow tests**

Run:

```bash
cd backend && pytest modules/imports/tests/test_workflow.py -q
```

Expected: current baseline either passes or failures are recorded before editing.

- [ ] **Step 0.3: Run current frontend deep import smoke**

Run:

```bash
cd frontend-console && npx playwright test deep-import.spec.js --reporter=list
```

Expected: establishes existing UI baseline. If environment cannot start services, record the failure and continue with unit-level work.

---

## Task 1: Deep Import Result Contract

**Files:**
- Modify: `backend/modules/imports/workflow_schemas.py`
- Modify: `backend/modules/imports/orchestrator.py`
- Test: `backend/modules/imports/tests/test_workflow.py`

**Purpose:** Add the task result fields that frontend, recovery, and acceptance tests depend on before implementing new phases.

- [ ] **Step 1.1: Write RED test for result contract**

Add tests in `backend/modules/imports/tests/test_workflow.py`:

```python
async def test_deep_import_progress_exposes_resilient_result_contract():
    progress = DeepImportProgress(workflow_id="task-1")
    progress.current_phase = "phase0_prefetch"
    progress.current_round = "A"
    progress.current_chapter_range = "1-5"
    progress.current_operation = "scene_prefetch"
    progress.quality_stats["phase0"] = {
        "total_batches": 4,
        "completed_batches": 1,
        "success": 1,
        "final_422_rate": 0.0,
    }

    dumped = progress.model_dump(mode="json")

    assert dumped["current_phase"] == "phase0_prefetch"
    assert dumped["current_round"] == "A"
    assert dumped["current_chapter_range"] == "1-5"
    assert dumped["current_operation"] == "scene_prefetch"
    assert dumped["quality_stats"]["phase0"]["total_batches"] == 4
```

Expected before implementation: fails because fields do not exist.

- [ ] **Step 1.2: Extend `DeepImportProgress`**

Add these fields to `DeepImportProgress`:

```python
current_phase: str | None = None
current_round: str | None = None
current_chapter_range: str | None = None
current_chapter: int | None = None
current_scene_candidate_id: str | None = None
current_window: str | None = None
current_operation: str | None = None
quality_stats: dict = Field(default_factory=dict)
checkpoints: dict = Field(default_factory=dict)
recovery_summary: dict = Field(default_factory=dict)
interrupted: bool = False
recoverable: bool = False
recovery_required: bool = False
interrupted_at: str | None = None
last_heartbeat_at: str | None = None
degraded_reason: str | None = None
phase1a_fallback: bool = False
```

Keep existing `current_step`, `phase1_total_batches`, `phase2_total_scenes`, and `completed_steps` for compatibility.

- [ ] **Step 1.3: Extend orchestrator result projection**

Update `_result_from_progress()` in `backend/modules/imports/orchestrator.py` to include all new fields. Keep old keys unchanged.

- [ ] **Step 1.4: Verify**

Run:

```bash
cd backend && pytest modules/imports/tests/test_workflow.py -k resilient_result_contract -q
```

Expected: pass.

---

## Task 2: Retry Diagnostics And Quality Gate Primitives

**Files:**
- Create: `backend/modules/imports/deep_import_retry.py`
- Modify: `backend/modules/imports/llm_schemas.py`
- Test: `backend/modules/imports/tests/test_workflow.py`

**Purpose:** Centralize retry rules so Phase 0, Phase 1a, and Phase 1b do not each invent slightly different 422 semantics.

- [ ] **Step 2.1: Write RED tests**

Add tests:

```python
def test_retry_policy_retries_422_network_and_timeout_once():
    assert should_retry_deep_import_error("422", attempt=0, max_retries=1)
    assert should_retry_deep_import_error("network", attempt=0, max_retries=1)
    assert should_retry_deep_import_error("timeout", attempt=0, max_retries=1)
    assert not should_retry_deep_import_error("422", attempt=1, max_retries=1)


def test_retry_policy_does_not_retry_schema_empty_or_quality_gate():
    assert not should_retry_deep_import_error("schema", attempt=0, max_retries=1)
    assert not should_retry_deep_import_error("empty", attempt=0, max_retries=1)
    assert not should_retry_deep_import_error("quality_gate", attempt=0, max_retries=1)
```

- [ ] **Step 2.2: Add retry helper**

Create `backend/modules/imports/deep_import_retry.py`:

```python
from __future__ import annotations

RETRYABLE_ERROR_KINDS = {"422", "network", "timeout"}
NON_RETRYABLE_ERROR_KINDS = {"schema", "empty", "quality_gate"}


def should_retry_deep_import_error(
    error_kind: str,
    *,
    attempt: int,
    max_retries: int = 1,
) -> bool:
    if error_kind in NON_RETRYABLE_ERROR_KINDS:
        return False
    return error_kind in RETRYABLE_ERROR_KINDS and attempt < max_retries


def final_422_rate(*, final_422_batches: int, total_batches: int) -> float:
    if total_batches <= 0:
        return 0.0
    return final_422_batches / total_batches


def exceeds_422_threshold(
    *,
    final_422_batches: int,
    total_batches: int,
    threshold: float = 0.40,
) -> bool:
    return final_422_rate(
        final_422_batches=final_422_batches,
        total_batches=total_batches,
    ) > threshold
```

- [ ] **Step 2.3: Add intermediate schema fields**

In `backend/modules/imports/llm_schemas.py`, add or extend models for:

```python
class SceneCandidateOutput(BaseModel):
    scenes: list[dict] = Field(default_factory=list)
    boundary_status: str | None = None
    evidence_anchors: list[dict] = Field(default_factory=list)
    merge_hints: list[dict] = Field(default_factory=list)
    split_hints: list[dict] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    missing_or_uncertain_items: list[str] = Field(default_factory=list)
```

If existing `llm_schemas.py` already has Scene models, extend rather than duplicate.

- [ ] **Step 2.4: Verify**

Run:

```bash
cd backend && pytest modules/imports/tests/test_workflow.py -k "retry_policy or final_422" -q
```

Expected: pass.

---

## Task 3: Phase 0 Batch Planner And Prefetch

**Files:**
- Create: `backend/modules/imports/scene_candidates.py`
- Create: `backend/modules/imports/scene_prefetch.py`
- Modify: `backend/modules/imports/workflow.py`
- Test: `backend/modules/imports/tests/test_workflow.py`

**Purpose:** Implement two-round offset prefetch without writing formal Scene rows.

- [ ] **Step 3.1: Write RED tests for batch layout and no formal Scene writes**

Add tests:

```python
def test_phase0_builds_two_offset_rounds_for_213_chapters():
    batches = build_phase0_prefetch_batches(start_chapter=1, end_chapter=213, window=5)

    assert batches[0].round_name == "A"
    assert batches[0].chapter_indices == [1, 2, 3, 4, 5]
    assert batches[1].round_name == "A"
    assert batches[1].chapter_indices == [6, 7, 8, 9, 10]
    round_b_first = next(b for b in batches if b.round_name == "B")
    assert round_b_first.chapter_indices == [3, 4, 5, 6, 7]


async def test_phase0_prefetch_does_not_create_formal_scenes(db, novel_id):
    result = await Phase0ScenePrefetcher(llm=FakeLLM.success()).run(
        db,
        novel_id=novel_id,
        start_chapter=1,
        end_chapter=10,
    )

    assert result.quality_stats["total_batches"] > 0
    assert await count_scenes_by_novel(db, novel_id) == 0
```

- [ ] **Step 3.2: Implement `scene_candidates.py`**

Add focused Pydantic/dataclass models:

```python
class SceneCandidateBatch(BaseModel):
    batch_id: str
    round_name: Literal["A", "B"]
    batch_index: int
    chapter_indices: list[int]


class SceneCandidate(BaseModel):
    candidate_id: str
    source_round: Literal["A", "B"]
    source_batch_id: str
    source_chapter_indices: list[int]
    quality: Literal["high", "low", "failed"]
    payload: dict = Field(default_factory=dict)
    diagnostics: dict = Field(default_factory=dict)
```

- [ ] **Step 3.3: Implement Phase 0 planner**

`build_phase0_prefetch_batches(start_chapter, end_chapter, window=5)` must produce:

- Round A: 1-5, 6-10, ...
- Round B: 3-7, 8-12, ...
- Tail short batch allowed.
- No extra head patch.

- [ ] **Step 3.4: Implement prefetch runner with concurrency setting**

Use config with default `50`. If adding settings is too invasive for this task, define module constants first:

```python
PHASE0_PREFETCH_CONCURRENCY = 50
DEEP_IMPORT_LLM_RETRY_COUNT = 1
DEEP_IMPORT_422_BLOCK_THRESHOLD = 0.40
```

The runner returns intermediate candidates and stats; it never calls `outline.create_scene`.

- [ ] **Step 3.5: Verify**

Run:

```bash
cd backend && pytest modules/imports/tests/test_workflow.py -k phase0 -q
```

Expected: pass.

---

## Task 4: Phase 0 422 Blocking And Diagnostics

**Files:**
- Modify: `backend/modules/imports/scene_prefetch.py`
- Modify: `backend/modules/imports/workflow.py`
- Test: `backend/modules/imports/tests/test_workflow.py`

**Purpose:** Phase 0 blocks only when final 422 rate exceeds 40%; timeout/schema/empty are diagnostics, not standalone blockers.

- [ ] **Step 4.1: Write RED tests**

```python
async def test_phase0_blocks_only_on_final_422_rate_over_40_percent():
    prefetcher = Phase0ScenePrefetcher(
        llm=FakeLLM.sequence([
            FakeLLMError("422"), FakeLLMError("422"),
            FakeLLMError("422"), FakeLLMError("422"),
            FakeLLMResult.valid_scene(),
        ])
    )

    result = await prefetcher.run(..., total_batches_override=5)

    assert result.blocked is True
    assert result.block_reason == "phase0_422_rate_exceeded"
    assert result.quality_stats["final_422_rate"] > 0.40


async def test_phase0_schema_failures_are_diagnostics_not_blockers():
    result = await Phase0ScenePrefetcher(llm=FakeLLM.schema_failures()).run(...)

    assert result.blocked is False
    assert result.quality_stats["schema_failed"] > 0
```

- [ ] **Step 4.2: Wire blocker in workflow**

In `DeepImportWorkflow.run_step`, after Phase 0:

- Set `progress.current_phase = "phase0_prefetch"`.
- Merge `quality_stats.phase0`.
- If blocked:
  - `phase = "failed"`
  - `quality_status = "failed"`
  - `degraded = True`
  - add `phase_errors` with `error_kind="phase0_422_rate_exceeded"`
  - message includes official API recommendation.
  - return without Phase 1a/1b/2/3.

- [ ] **Step 4.3: Verify**

Run:

```bash
cd backend && pytest modules/imports/tests/test_workflow.py -k "phase0 and 422" -q
```

Expected: pass.

---

## Task 5: Phase 1a Reinforcement

**Files:**
- Create: `backend/modules/imports/scene_reinforcement.py`
- Modify: `backend/modules/imports/llm_schemas.py`
- Modify: `backend/prompts/scene_segmentation.md` or the active scene segmentation prompt file found by `rg "scene_segmentation" backend/prompts backend/modules`
- Test: `backend/modules/imports/tests/test_workflow.py`

**Purpose:** Reinforce Round A/B separately with正文 and Phase 0 references.

- [ ] **Step 5.1: Write RED tests**

```python
async def test_phase1a_reinforces_rounds_separately():
    result = await Phase1aSceneReinforcer(llm=FakeLLM.success()).run(
        phase0_candidates=[
            make_candidate(source_round="A", source_batch_id="A-0001"),
            make_candidate(source_round="B", source_batch_id="B-0001"),
        ],
        chapters=make_chapters(1, 7),
    )

    assert {c.source_round for c in result.candidates} == {"A", "B"}
    assert result.did_merge_rounds is False


async def test_phase1a_blocks_on_final_422_rate_over_40_percent():
    result = await Phase1aSceneReinforcer(llm=FakeLLM.final_422_rate(0.50)).run(...)

    assert result.blocked is True
    assert result.block_reason == "phase1a_422_rate_exceeded"
```

- [ ] **Step 5.2: Implement Phase 1a service**

`Phase1aSceneReinforcer.run()` must:

- Load batch正文.
- Include Phase 0 high-quality candidates as strong references.
- Include low-quality parseable candidates as weak references.
- Include previous/next batch summaries by chapter order, not completion time.
- Produce enhanced candidate fields: `boundary_status`, `evidence_anchors`, `merge_hints`, `split_hints`, `confidence`, `missing_or_uncertain_items`.
- Never write formal Scene rows.

- [ ] **Step 5.3: Enhance prompt**

Update the active scene extraction prompt to require:

- chapter/paragraph source anchors.
- boundary status and uncertainty reason.
- merge/split hints.
- missing/uncertain items.
- no source-detached pretty summaries.

- [ ] **Step 5.4: Verify**

Run:

```bash
cd backend && pytest modules/imports/tests/test_workflow.py -k phase1a -q
```

Expected: pass.

---

## Task 6: Phase 1b Windowed Fusion / Reducer

**Files:**
- Create: `backend/modules/imports/scene_fusion.py`
- Modify: `backend/modules/imports/llm_schemas.py`
- Modify: `backend/modules/imports/workflow.py`
- Test: `backend/modules/imports/tests/test_workflow.py`

**Purpose:** Produce official Scene candidates from Phase 1a observations without正文.

- [ ] **Step 6.1: Write RED tests**

```python
def test_phase1b_windows_are_30_chapters_with_3_overlap():
    windows = build_phase1b_windows(start_chapter=1, end_chapter=80)

    assert windows[0].core_range == (1, 30)
    assert windows[0].covered_range == (1, 33)
    assert windows[1].core_range == (31, 60)
    assert windows[1].covered_range == (28, 63)


async def test_phase1b_422_over_threshold_degrades_to_phase1a_fallback():
    result = await Phase1bSceneFusion(llm=FakeLLM.final_422_rate(0.50)).run(...)

    assert result.degraded is True
    assert result.phase1a_fallback is True
    assert result.blocked is False
```

- [ ] **Step 6.2: Implement window planner**

Constants:

```python
PHASE1B_WINDOW_CHAPTERS = 30
PHASE1B_WINDOW_OVERLAP = 3
PHASE1B_CONCURRENCY = 4
```

- [ ] **Step 6.3: Implement reducer output validation**

Each output Scene candidate must include:

- `source_candidate_ids`
- `source_rounds`
- `source_chapter_indices`
- `operation`: `kept / merged / split / reordered / rewritten`
- `confidence`
- `fallback_required`
- `boundary_status`
- `boundary_reason`
- `needs_review`
- `review_reason`

Discard reasons must be one of:

```python
{"merged", "split", "duplicate_candidate", "low_confidence_unusable", "outside_scope"}
```

- [ ] **Step 6.4: Implement local fallback**

If a window output misses coverage:

- Use valid Phase 1a candidates for missing local coverage.
- Mark fallback candidate `phase="phase1a_fallback"`.
- Do not roll back the whole batch/window unless Phase 1b final 422 rate exceeds threshold.

- [ ] **Step 6.5: Verify**

Run:

```bash
cd backend && pytest modules/imports/tests/test_workflow.py -k phase1b -q
```

Expected: pass.

---

## Task 7: Scene Commit Provenance And Idempotency

**Files:**
- Create: `backend/modules/imports/scene_commit.py`
- Modify: `backend/modules/outline/facade.py`
- Modify: `backend/modules/outline/repositories.py`
- Test: `backend/modules/imports/tests/test_workflow.py`
- Test: `backend/modules/outline/tests/test_scene.py`

**Purpose:** Formal Scene writes happen once, after reducer, with stable `provenance_key`.

- [ ] **Step 7.1: Write RED tests**

```python
async def test_scene_commit_writes_provenance_and_skips_existing_key(db, novel_id):
    candidate = make_final_scene_candidate(
        workflow_id="wf-1",
        source_candidate_ids=["a", "b"],
        source_chapter_indices=[1, 2],
        fusion_operation="merged",
    )

    first = await SceneCommitter().commit(db, novel_id, [candidate])
    second = await SceneCommitter().commit(db, novel_id, [candidate])

    assert first.created_count == 1
    assert second.skipped_count == 1
    assert await count_scenes_by_novel(db, novel_id) == 1
```

- [ ] **Step 7.2: Implement provenance key**

Use deterministic JSON or joined normalized fields:

```python
def build_scene_provenance_key(workflow_id, source_candidate_ids, fusion_operation, source_chapter_indices):
    raw = {
        "workflow_id": workflow_id,
        "source_candidate_ids": sorted(source_candidate_ids),
        "fusion_operation": fusion_operation,
        "source_chapter_indices": sorted(source_chapter_indices),
    }
    return hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()
```

- [ ] **Step 7.3: Store provenance in `structure_meta`**

Formal Scene `structure_meta` must include:

```python
{
    "auto_ingested": True,
    "workflow_id": workflow_id,
    "phase": "phase1b_fusion",
    "source_candidate_ids": [...],
    "source_rounds": ["A", "B"],
    "source_chapter_indices": [...],
    "fusion_operation": "merged",
    "confidence": 0.86,
    "degraded_reason": None,
    "boundary_status": "uncertain",
    "boundary_reason": "...",
    "needs_review": True,
    "review_reason": "...",
    "provenance_key": "...",
}
```

- [ ] **Step 7.4: Handle deprecated conflict**

If same `provenance_key` exists with `status="deprecated"`:

- Do not revive it.
- Return conflict count.
- Write fallback/needs_review marker in commit result.

- [ ] **Step 7.5: Verify**

Run:

```bash
cd backend && pytest modules/imports/tests/test_workflow.py modules/outline/tests/test_scene.py -k "provenance or commit" -q
```

Expected: pass.

---

## Task 8: Wire Workflow Phase 0 -> 1a -> 1b -> Commit

**Files:**
- Modify: `backend/modules/imports/workflow.py`
- Modify: `backend/modules/imports/orchestrator.py`
- Test: `backend/modules/imports/tests/test_workflow.py`

**Purpose:** Replace old `_segment_scenes()` direct write path.

- [ ] **Step 8.1: Write RED orchestration tests**

```python
async def test_phase0_block_stops_before_phase1a_phase2_phase3():
    workflow = DeepImportWorkflow(services=FakeServices(phase0_blocked=True))
    result = await workflow.run_step(...)

    assert result.phase == "failed"
    assert "scene_segmentation" not in result.completed_steps
    assert FakeServices.phase1a_called is False
    assert FakeServices.phase2_called is False


async def test_phase1b_degraded_still_runs_phase2_and_phase3():
    workflow = DeepImportWorkflow(services=FakeServices(phase1b_degraded=True))
    result = await workflow.run_step(...)

    assert result.phase == "done"
    assert result.phase1a_fallback is True
    assert "entity_extraction" in result.completed_steps
    assert "structure_analysis" in result.completed_steps
```

- [ ] **Step 8.2: Change phase labels**

Use `current_phase` values:

- `phase0_prefetch`
- `phase1a_reinforce`
- `phase1b_fusion`
- `scene_commit`
- `entity_extraction`
- `structure_analysis`

Keep `current_step=scene_segmentation` during Phase 0/1a/1b/commit for compatibility.

- [ ] **Step 8.3: Preserve old result fields**

Map new stats to old fields for backward compatibility:

- `phase1_total_batches = phase0.total_batches + phase1a.total_batches + phase1b.total_windows`
- `phase1_completed_batches = aggregate completed`
- `degraded_batches` remains for compatibility, but new UI should prefer `quality_stats`.

- [ ] **Step 8.4: Verify**

Run:

```bash
cd backend && pytest modules/imports/tests/test_workflow.py -q
```

Expected: all imports workflow tests pass.

---

## Task 9: Worker Interrupted Deep Import Detection

**Files:**
- Modify: `backend/infrastructure/tasks/worker.py`
- Modify: `backend/run_worker.py`
- Test: `backend/tests/unit/test_infra_tasks.py` or existing task worker test file found by `rg "TaskWorker" backend/tests backend -g '*test*.py'`

**Purpose:** Stale deep import is marked recoverable, not auto-resumed.

- [ ] **Step 9.1: Write RED tests**

```python
async def test_recover_stale_tasks_marks_deep_import_recovery_required_without_pending(worker, db):
    task = await create_running_task(
        db,
        task_type="deep_import",
        heartbeat_stale=True,
        result={"current_phase": "phase1b_fusion"},
    )

    recovered = await worker.recover_stale_tasks()
    refreshed = await get_task(db, task.id)

    assert recovered == 0
    assert refreshed.status == "running"
    assert refreshed.result["interrupted"] is True
    assert refreshed.result["recoverable"] is True
    assert refreshed.result["recovery_required"] is True


async def test_recover_stale_tasks_keeps_non_deep_import_auto_recovery(worker, db):
    task = await create_running_task(db, task_type="rag_index", heartbeat_stale=True)

    recovered = await worker.recover_stale_tasks()
    refreshed = await get_task(db, task.id)

    assert recovered == 1
    assert refreshed.status == "pending"
```

- [ ] **Step 9.2: Implement deep import special case**

`recover_stale_tasks()` should:

- Update stale `running` `deep_import` rows with result/meta flags.
- Not set them to `pending`.
- Return count of tasks auto-reset to pending, not interrupted deep imports.

- [ ] **Step 9.3: Call stale scan on startup and loop**

In `run_forever()`:

- call stale scan once before loop.
- call periodically when no pending task is found.

Do not auto-continue `deep_import`.

- [ ] **Step 9.4: Verify**

Run:

```bash
cd backend && pytest -q tests/unit/test_infra_tasks.py -k stale
```

Expected: pass. If file path differs, use the actual worker test file found in Step 9.1.

---

## Task 10: Continue And Abandon Recovery APIs

**Files:**
- Modify: `backend/modules/imports/api.py`
- Modify: `backend/modules/imports/facade.py`
- Modify: `backend/modules/imports/orchestrator.py`
- Test: `backend/modules/imports/tests/test_workflow.py`
- Test: `backend/tests/unit/test_imports_facade.py` if present.

**Purpose:** User controls recovery.

- [ ] **Step 10.1: Write RED tests for continue**

```python
async def test_resume_reuses_original_recoverable_deep_import_task(db):
    task = await create_recoverable_deep_import_task(db, task_id="task-1")

    result = await DeepImportOrchestrator().resume_interrupted(db, str(task.id))

    assert result["task_id"] == str(task.id)
    assert result["workflow_id"] == str(task.id)
    assert result["status"] == "pending"
```

- [ ] **Step 10.2: Write RED tests for abandon**

```python
async def test_abandon_recovery_marks_original_task_cancelled_and_returns_cleanup_summary(db):
    task = await create_recoverable_deep_import_task(db)

    result = await DeepImportOrchestrator().abandon_recovery(db, str(task.id))

    assert result["task_id"] == str(task.id)
    assert result["status"] == "cancelled"
    assert "deprecated_scenes" in result["cleanup_summary"]
```

- [ ] **Step 10.3: Implement continue**

`resume_interrupted()` must:

- Fetch original task.
- Require `task_type == "deep_import"`.
- Require `result.recovery_required == True`.
- Set status to `pending`.
- Clear `interrupted/recovery_required` only after it is claimed or in the returned result according to implementation consistency.
- Preserve task id and workflow id.

- [ ] **Step 10.4: Implement abandon**

`abandon_recovery()` must:

- Run cleanup by `novel_id + workflow_id`.
- Mark original task `cancelled`.
- Return cleanup summary.

- [ ] **Step 10.5: API routes**

Keep old `/api/imports/deep/resume` path if frontend already uses it, but change semantics to reuse original task. Add an explicit abandon endpoint:

- `POST /api/imports/deep/resume`
- `POST /api/imports/deep/abandon`

- [ ] **Step 10.6: Verify**

Run:

```bash
cd backend && pytest modules/imports/tests/test_workflow.py -k "resume or abandon or recovery" -q
```

Expected: pass.

---

## Task 11: Phase 2 Per-Scene Checkpoints And Provenance

**Files:**
- Modify: `backend/modules/imports/scene_entity_extraction.py`
- Modify: `backend/modules/imports/workflow_schemas.py`
- Test: `backend/modules/imports/tests/test_scene_entity_extraction.py`

**Purpose:** Recovery can skip successful Scene extraction and rerun failed/stale Scene extraction.

- [ ] **Step 11.1: Write RED tests**

```python
async def test_phase2_records_checkpoint_for_each_scene(db, novel_id):
    result = await SceneEntityExtractionService().extract_by_scenes(
        db,
        novel_id=novel_id,
        workflow_id="wf-1",
    )

    checkpoint = result["checkpoints"]["phase2"]["scenes"][0]
    assert checkpoint["scene_id"]
    assert checkpoint["status"] == "done"
    assert "created_entity_ids" in checkpoint
    assert "created_relation_ids" in checkpoint
    assert "created_delta_ids" in checkpoint


async def test_phase2_recovery_skips_successful_scene_and_reruns_failed_scene(db, novel_id):
    result = await SceneEntityExtractionService().extract_by_scenes(
        db,
        novel_id=novel_id,
        workflow_id="wf-1",
        existing_checkpoints={
            "scene-a": {"status": "done"},
            "scene-b": {"status": "failed", "retry_count": 0},
        },
    )

    assert result["skipped_scenes"] == 1
    assert result["rerun_scenes"] == 1
```

- [ ] **Step 11.2: Add checkpoint input/output**

Extend `extract_by_scenes()` to accept optional existing checkpoint data from workflow result/checkpoints. Return updated checkpoint summary.

- [ ] **Step 11.3: Add provenance to created assets**

Ensure created entities, relations, deltas, and map observations carry:

- `workflow_id`
- `scene_id`
- `scene_provenance_key`
- `source=deep_import`
- `auto_ingested=true` where applicable.

- [ ] **Step 11.4: Verify**

Run:

```bash
cd backend && pytest modules/imports/tests/test_scene_entity_extraction.py -q
```

Expected: pass.

---

## Task 12: Phase 3 Structure Asset Provenance

**Files:**
- Modify: `backend/modules/outline/models.py`
- Modify: `backend/modules/outline/schemas.py`
- Modify: `backend/modules/outline/repositories.py`
- Modify: `backend/modules/outline/generation/persister.py`
- Create: `backend/alembic/versions/20260630_add_deep_import_structure_provenance.py`
- Test: `backend/modules/outline/tests/test_foreshadowing_reveal.py`
- Test: `backend/modules/outline/tests/test_tasks.py`

**Purpose:** PlotThread, OutlineArc, ForeshadowingPlan, and RevealPlan can be filtered, cleaned, and protected from unsafe overwrite.

- [ ] **Step 12.1: Add explicit storage shape**

Add a nullable JSON column named `provenance_meta` to `plot_threads`, `outline_arcs`, `foreshadowing_plans`, and `reveal_plans`.

Each generated structure asset stores:

```python
{
    "source": "deep_import",
    "workflow_id": "wf-1",
    "auto_ingested": True,
    "needs_review": False,
    "user_edited": False,
    "phase": "structure_analysis",
}
```

Scene already uses `structure_meta`; do not add a duplicate Scene column.

- [ ] **Step 12.2: Write RED tests**

```python
async def test_phase3_persists_structure_assets_with_deep_import_provenance(db, novel_id):
    result = await PlotStructureGenerator().generate(
        db,
        novel_id,
        start_chapter=1,
        end_chapter=3,
        workflow_id="wf-1",
        context_mode="working",
        include_pending_objects=True,
    )

    thread = await get_first_plot_thread(db, novel_id)
    assert thread.source == "deep_import"
    assert thread.workflow_id == "wf-1"
    assert thread.auto_ingested is True
```

Adapt field access to the chosen storage shape.

- [ ] **Step 12.3: Mark generated structure assets**

In persister, write provenance for all four asset types.

- [ ] **Step 12.4: Verify**

Run:

```bash
cd backend && pytest modules/outline/tests/test_foreshadowing_reveal.py modules/outline/tests/test_tasks.py -q
```

Expected: pass.

---

## Task 13: Safe Cleanup For Abandon And Phase 3 Rerun

**Files:**
- Modify: `backend/modules/imports/orchestrator.py`
- Modify or add facade helpers in `backend/modules/outline/facade.py`
- Modify or add facade helpers in `backend/modules/world/entity_facade.py`
- Modify or add facade helpers in `backend/modules/memory/facade.py`
- Test: `backend/modules/imports/tests/test_workflow.py`
- Test: `backend/modules/imports/tests/test_imports_integration.py`

**Purpose:** Cleanup touches only current workflow auto-derived assets.

- [ ] **Step 13.1: Write RED cleanup isolation test**

```python
async def test_abandon_recovery_deprecates_only_same_workflow_auto_assets(db):
    current = await seed_deep_import_assets(db, workflow_id="wf-current", auto=True)
    other_workflow = await seed_deep_import_assets(db, workflow_id="wf-other", auto=True)
    canonical = await seed_deep_import_assets(db, workflow_id="wf-current", status="canonical")
    user_edited = await seed_deep_import_assets(db, workflow_id="wf-current", user_edited=True)

    summary = await DeepImportOrchestrator().cleanup_workflow_assets(
        db,
        novel_id=current.novel_id,
        workflow_id="wf-current",
    )

    assert summary["deprecated_scenes"] > 0
    assert await asset_status(db, other_workflow.scene_id) != "deprecated"
    assert await asset_status(db, canonical.scene_id) == "canonical"
    assert await asset_status(db, user_edited.scene_id) != "deprecated"
```

- [ ] **Step 13.2: Implement cleanup policy**

Allowed:

- Deprecated: same workflow, auto-ingested, draft/candidate/deep_import Scene/entity/relation/structure assets.
- Ignored: same workflow candidate/conflicted map observations.
- Meta-mark deprecated: delta logs without status.
- Hard delete: only pure intermediate task result/checkpoint artifacts that were never exposed as business assets.

Forbidden:

- canonical assets.
- user-edited assets.
- different workflow assets.
- different novel assets.
- confirmed map facts.

- [ ] **Step 13.3: Verify**

Run:

```bash
cd backend && pytest modules/imports/tests/test_workflow.py modules/imports/tests/test_imports_integration.py -k "cleanup or abandon or workflow" -q
```

Expected: pass.

---

## Task 14: Backend Filtering APIs

**Files:**
- Modify: `backend/modules/outline/api.py`
- Modify: `backend/modules/outline/repositories.py`
- Modify: `backend/modules/world/api.py`
- Modify: `backend/modules/world/services/entity_stats_service.py`
- Modify: `backend/modules/world/repositories.py`
- Test: `backend/modules/outline/tests/test_scene.py`
- Test: `backend/modules/outline/tests/test_foreshadowing_reveal.py`
- Test: `backend/modules/world/tests/test_entity_stats_service.py`

**Purpose:** Large imports must be triaged by backend query parameters with pagination.

- [ ] **Step 14.1: Write RED tests for Scene filters**

```python
async def test_list_scenes_filters_by_workflow_phase_and_needs_review(client, novel_id):
    response = await client.get(
        "/api/outline/scenes",
        params={
            "novel_id": novel_id,
            "source": "deep_import",
            "workflow_id": "wf-1",
            "phase1a_fallback": "true",
            "needs_review": "true",
            "skip": 0,
            "limit": 20,
        },
    )

    assert response.status_code == 200
    assert all(item["structure_meta"]["workflow_id"] == "wf-1" for item in response.json())
```

- [ ] **Step 14.2: Write RED tests for world filters**

```python
async def test_world_objects_filter_by_deep_import_metadata(client, novel_id):
    response = await client.get(
        "/api/world/entities",
        params={
            "novel_id": novel_id,
            "source": "deep_import",
            "workflow_id": "wf-1",
            "auto_ingested": "true",
            "needs_review": "true",
            "status": "candidate",
            "skip": 0,
            "limit": 20,
        },
    )

    assert response.status_code == 200
```

- [ ] **Step 14.3: Implement DB-level filtering**

Do not implement by fetching all rows and filtering in frontend. Filtering must happen in repository/service queries.

- [ ] **Step 14.4: Verify**

Run:

```bash
cd backend && pytest modules/outline/tests/test_scene.py modules/outline/tests/test_foreshadowing_reveal.py modules/world/tests/test_entity_stats_service.py -k "filter or workflow or needs_review" -q
```

Expected: pass.

---

## Task 15: Frontend Deep Import Progress, Blocking, And Degradation

**Files:**
- Modify: `frontend-console/views/writingView.js`
- Modify: `frontend-console/shared/workflowProgress.js`
- Modify: `frontend-console/shared/progressRenderer.js`
- Modify: `frontend-console/styles.css`
- Create: `frontend-console/e2e/deep-import-resilient.spec.js`

**Purpose:** Implement DI-PW-001 through DI-PW-005.

- [ ] **Step 15.1: Write Playwright tests first**

In `deep-import-resilient.spec.js`, add tests for:

- Phase 0 running display.
- Phase 0 422 blocker.
- Phase 1a 422 blocker.
- Phase 1b 422 degradation.
- Phase 1b local fallback count.

Use `page.route()` to mock:

- `POST /api/imports/deep`
- `GET /api/tasks/{task_id}`

- [ ] **Step 15.2: Normalize new task result**

In `writingView.js`, preserve current recovery path but read:

- `current_phase`
- `current_round`
- `current_chapter_range`
- `current_chapter`
- `current_scene_candidate_id`
- `current_window`
- `current_operation`
- `quality_stats`
- `degraded_reason`
- `phase1a_fallback`

- [ ] **Step 15.3: Render quality stats**

Show:

- Phase 0 request/success/422/timeout/schema failures.
- Phase 1a success/fallback/422.
- Phase 1b window success/degraded/422.
- final Scene count.
- needs_review count.

- [ ] **Step 15.4: Add restrained alive state**

Use CSS animation inside the progress bar/hint only. Respect reduced motion:

```css
@media (prefers-reduced-motion: reduce) {
  .deep-import-progress--alive {
    animation: none;
  }
}
```

- [ ] **Step 15.5: Verify**

Run:

```bash
cd frontend-console && npx playwright test deep-import-resilient.spec.js --grep "DI-PW-00[1-5]" --reporter=list
```

Expected: pass.

---

## Task 16: Frontend Recovery Continue / Abandon

**Files:**
- Modify: `frontend-console/views/writingView.js`
- Modify: `frontend-console/api.js`
- Modify: `frontend-console/e2e/deep-import-resilient.spec.js`

**Purpose:** Implement DI-PW-006 through DI-PW-009 and DI-PW-019 UI side.

- [ ] **Step 16.1: Add API methods**

In `api.imports`, add:

```javascript
async resumeDeepImport(taskId) {
  return request("/imports/deep/resume", {
    method: "POST",
    body: JSON.stringify({ task_id: taskId }),
  })
},

async abandonDeepImport(taskId) {
  return request("/imports/deep/abandon", {
    method: "POST",
    body: JSON.stringify({ task_id: taskId }),
  })
},
```

- [ ] **Step 16.2: Write Playwright tests**

Test:

- refresh/route recovery only calls GET task.
- recovery_required displays checkpoint summary.
- continue calls resume API and keeps same task id.
- abandon opens warning; cancel does not call API; confirm calls abandon API and shows cleanup summary.

- [ ] **Step 16.3: Implement UI**

In `writingView.js`:

- If task result has `recovery_required`, stop normal polling UI and show recovery prompt.
- Display checkpoint summary from `recovery_summary`.
- Add buttons: continue, abandon.
- Preserve localStorage task id on continue.
- Clear localStorage only after terminal done/cancelled/explicit dismiss.

- [ ] **Step 16.4: Verify**

Run:

```bash
cd frontend-console && npx playwright test deep-import-resilient.spec.js --grep "DI-PW-00[6-9]|DI-PW-019" --reporter=list
```

Expected: pass.

---

## Task 17: Scene Workbench Filters And Manual LLM Fusion

**Files:**
- Modify: `frontend-console/views/sceneWorkbenchView.js`
- Modify: `frontend-console/api.js`
- Modify: `frontend-console/styles.css`
- Modify or add backend endpoint in `backend/modules/outline/api.py`
- Modify or add service in `backend/modules/outline/scene_workbench.py`
- Test: `backend/modules/outline/tests/test_scene_workbench.py`
- Test: `frontend-console/e2e/deep-import-resilient.spec.js`

**Purpose:** Implement DI-PW-010 and DI-PW-012 through DI-PW-014.

- [ ] **Step 17.1: Backend RED tests for manual fusion**

```python
async def test_manual_scene_fusion_preview_does_not_modify_original_scenes(db, novel_id):
    original_ids = await seed_two_scenes(db, novel_id)

    preview = await SceneWorkbenchService().preview_llm_fusion(
        db,
        novel_id,
        source_scene_ids=original_ids,
    )

    assert preview["source_scene_ids"] == original_ids
    assert await scenes_statuses(db, original_ids) == ["draft", "draft"]
```

- [ ] **Step 17.2: Backend fusion save choices**

Support save modes:

- `keep_originals`
- `deprecate_originals`
- `discard`
- `edit_then_save`

Only `deprecate_originals` changes original Scene status.

- [ ] **Step 17.3: Frontend filters**

Add filter UI and API query params:

- `status`
- `needs_review`
- `boundary_status`
- `review_reason`
- `source`
- `workflow_id`
- `auto_ingested`
- `chapter_range`
- `phase1a_fallback`
- `phase1b_fusion`
- `recovery_conflict`
- `pending_confirmation`
- `skip`
- `limit`

- [ ] **Step 17.4: Frontend multi-select and fusion modal**

Fusion button enabled only when `selectedSceneIds.length >= 2`.

Fusion result modal must show editable fields and choices:

- 保留原 Scene + 保存融合 Scene
- 保存融合 Scene，并将原 Scene 标记为 deprecated
- 放弃融合结果
- 继续编辑融合结果后再保存

- [ ] **Step 17.5: Verify**

Run:

```bash
cd backend && pytest modules/outline/tests/test_scene_workbench.py -k "fusion or filter" -q
cd frontend-console && npx playwright test deep-import-resilient.spec.js --grep "DI-PW-010|DI-PW-01[2-4]" --reporter=list
```

Expected: pass.

---

## Task 18: World Object Filters And Forced Map Navigation Bug

**Files:**
- Modify: `backend/modules/world/api.py`
- Modify: `backend/modules/world/services/entity_stats_service.py`
- Modify: `frontend-console/views/worldView.js`
- Modify: `frontend-console/router.js`
- Create or modify: `frontend-console/e2e/world-objects.spec.js`
- Modify: `frontend-console/e2e/deep-import-resilient.spec.js`

**Purpose:** Implement DI-PW-011 and fix the independent “world objects jumps to map” bug.

- [ ] **Step 18.1: Backend filter tests**

Add tests for query params:

- `source=deep_import`
- `workflow_id`
- `auto_ingested=true`
- `needs_review=true`
- `entity_type`
- `status`
- pagination.

- [ ] **Step 18.2: Frontend world object filter UI**

Show filters in world object management view. Do not route to map when filtering or clicking world object management.

- [ ] **Step 18.3: Forced map navigation test**

Playwright:

```javascript
test("world objects entry stays on object management instead of forcing map", async ({ page }) => {
  await page.goto(`/#workbench/${project.id}/world/objects`)
  await expect(page.locator("[data-view='world-objects']")).toBeVisible()
  await expect(page).not.toHaveURL(/\/map/)
})
```

Only an explicit “打开地图” action may navigate to the map.

- [ ] **Step 18.4: Verify**

Run:

```bash
cd backend && pytest modules/world/tests/test_entity_stats_service.py -k "filter or workflow" -q
cd frontend-console && npx playwright test world-objects.spec.js deep-import-resilient.spec.js --grep "DI-PW-011|world objects" --reporter=list
```

Expected: pass.

---

## Task 19: Outline Structure Asset Filters And Phase 3 UI

**Files:**
- Modify: `backend/modules/outline/api.py`
- Modify: `backend/modules/outline/repositories.py`
- Modify: `frontend-console/views/outlineView.js`
- Modify: `frontend-console/api.js`
- Modify: `frontend-console/e2e/deep-import-resilient.spec.js`

**Purpose:** Implement DI-PW-016 through DI-PW-018.

- [ ] **Step 19.1: Backend filter tests for all four structure asset types**

Test `source`, `workflow_id`, `status`, `needs_review`, `deprecated`, and pagination for:

- plot threads.
- outline arcs.
- foreshadowing plans.
- reveal plans.

- [ ] **Step 19.2: Frontend list rendering**

Each list shows:

- title/name/description.
- status.
- source/deep import marker.
- workflow marker when filter is active.
- needs_review marker.

- [ ] **Step 19.3: Phase 3 partial display**

When task result has `quality_status=partial` and `phase_errors.structure_analysis`, show:

- structure analysis incomplete.
- generated assets still visible.
- empty asset types show “可重新分析 / 重新生成” entry.

- [ ] **Step 19.4: Verify**

Run:

```bash
cd backend && pytest modules/outline/tests/test_foreshadowing_reveal.py modules/outline/tests/test_tasks.py -k "workflow or source or needs_review" -q
cd frontend-console && npx playwright test deep-import-resilient.spec.js outline-threads-arcs.spec.js outline-foreshadowing-reveal.spec.js --grep "DI-PW-01[6-8]|剧情线|伏笔" --reporter=list
```

Expected: pass.

---

## Task 20: Worker And Browser-Close E2E

**Files:**
- Create: `frontend-console/e2e/deep-import-resilient-worker.spec.js`
- Modify: `frontend-console/e2e/deep-import-worker.spec.js` only to share helper code; otherwise leave it unchanged and keep the new resilient-worker spec separate.

**Purpose:** Keep worker behavior separate from normal mock Playwright.

- [ ] **Step 20.1: Create worker E2E**

Guard with:

```javascript
test.skip(
  process.env.RUN_WORKER_E2E !== "1",
  "requires RUN_WORKER_E2E=1 and a running backend worker",
)
```

- [ ] **Step 20.2: Cover browser close**

Flow:

1. create project.
2. upload small novel.
3. submit deep import.
4. close page.
5. poll task via API helper.
6. assert terminal status and result shape.

- [ ] **Step 20.3: Cover interrupted prompt with mock task**

Use route mock rather than actually killing worker. Real process kill is not a normal Playwright responsibility.

- [ ] **Step 20.4: Verify**

Run:

```bash
cd frontend-console && RUN_WORKER_E2E=1 npx playwright test deep-import-resilient-worker.spec.js --reporter=list
```

Expected: pass when worker is running; skipped otherwise.

---

## Task 21: Mobile And Layout Verification

**Files:**
- Modify: `frontend-console/styles.css`
- Modify: `frontend-console/e2e/deep-import-resilient.spec.js`

**Purpose:** Implement DI-PW-015 and prevent progress/filter UI overlap.

- [ ] **Step 21.1: Add Playwright viewport test**

```javascript
test("DI-PW-015 mobile progress and filters do not overlap", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockRunningDeepImport(page)
  await openWritingView(page, project)

  await expect(page.locator("#writing-deep-import-bar-container")).toBeVisible()
  await expectNoOverlaps(page.locator("#writing-deep-import-bar-container *"))
})
```

Use or copy a small `expectNoOverlaps` helper from existing E2E if available.

- [ ] **Step 21.2: CSS rules**

Use wrapping chips, max-width, and scrollable filter rows. Do not scale font size with viewport width.

- [ ] **Step 21.3: Verify**

Run:

```bash
cd frontend-console && npx playwright test deep-import-resilient.spec.js --grep "DI-PW-015" --reporter=list
```

Expected: pass.

---

## Task 22: Real LLM 213-Chapter Acceptance

**Files:**
- Create: `backend/modules/imports/tests/test_deep_import_real_llm.py` or `backend/scripts/acceptance_deep_import_resilient.py`
- Modify: `docs/superpowers/acceptance/2026-06-30-deep-import-resilient-scene-fusion-playwright-acceptance.md` only if final command/output changes.

**Purpose:** Manual/nightly proof that the full design handles real long text and unstable LLM APIs.

- [ ] **Step 22.1: Add guarded test/script**

Guard with `ENABLE_REAL_LLM=1`. Input:

```text
/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt
```

- [ ] **Step 22.2: Record required metrics**

Output must include:

- parsed chapter count, expected `213`.
- Phase 0 total/success/final_422_rate/timeout/schema_failed.
- Phase 1a total/success/final_422_rate/timeout/schema_failed.
- Phase 1b windows/success/degraded/final_422_rate.
- blocked/degraded reason.
- final Scene count.
- world object count.
- relation count.
- delta count.
- map observation count.
- Phase 2 completed/failed/skipped Scene checkpoint counts.
- Phase 3 thread/arc/foreshadowing/reveal counts.
- needs_review Scene count.
- workflow_id.

- [ ] **Step 22.3: Acceptance rules**

The script should assert:

- parsed chapters == 213.
- If Phase 0 or Phase 1a final 422 rate > 40%, task blocks and official API recommendation is present.
- If Phase 1b final 422 rate > 40%, task degrades but continues.
- If task completes, final Scene count > 0 and world object count > 0.
- At least one Phase 3 structure asset type count > 0; if not, result must include Phase 3 quality reason and reanalysis entry data.

- [ ] **Step 22.4: Verify manually**

Run:

```bash
ENABLE_REAL_LLM=1 cd backend && pytest modules/imports/tests/test_deep_import_real_llm.py -m real_llm -q -s
```

If shell syntax is rejected by local shell, use:

```bash
cd backend && ENABLE_REAL_LLM=1 pytest modules/imports/tests/test_deep_import_real_llm.py -m real_llm -q -s
```

Expected: passes or blocks with explicit API instability message.

---

## Task 23: Full Regression And Documentation Sync

**Files:**
- Modify: `docs/modules/13_imports.md`
- Modify: `docs/modules/14_frontend.md`
- Review: `CONTEXT.md`; edit only if implementation changes accepted terminology.

- [ ] **Step 23.1: Backend targeted suite**

Run:

```bash
cd backend && pytest modules/imports/tests modules/outline/tests/test_scene.py modules/outline/tests/test_scene_workbench.py modules/outline/tests/test_foreshadowing_reveal.py modules/world/tests/test_entity_stats_service.py -q
```

Expected: pass.

- [ ] **Step 23.2: Frontend targeted suite**

Run:

```bash
cd frontend-console && npx playwright test deep-import-resilient.spec.js world-objects.spec.js outline-threads-arcs.spec.js outline-foreshadowing-reveal.spec.js --reporter=list
```

Expected: pass.

- [ ] **Step 23.3: Lint and diff check**

Run:

```bash
cd backend && ruff check .
cd /Users/tywww/Desktop/项目/ai-writing-assist && git diff --check
```

Expected: pass.

- [ ] **Step 23.4: Docs sync**

Update module docs only for actual implemented behavior:

- `docs/modules/13_imports.md` for new deep import phases/recovery.
- `docs/modules/14_frontend.md` for progress/recovery UI if that doc tracks frontend workflows.

- [ ] **Step 23.5: Final status**

Report:

- tests run and pass/fail.
- whether real LLM acceptance was run.
- any skipped worker E2E due to missing worker.
- migration notes if structure asset provenance required schema changes.

---

## Suggested Subagent Assignment

These tasks are not all independent. Use these batches:

### Batch A: Backend Foundation

- Task 1: Result contract.
- Task 2: Retry diagnostics.
- Task 3: Phase 0 batch planner.

One backend worker can do these sequentially.

### Batch B: Scene Candidate Pipeline

- Task 4: Phase 0 blocking.
- Task 5: Phase 1a.
- Task 6: Phase 1b.
- Task 7: Scene commit.
- Task 8: Workflow wiring.

Use one worker or two workers with disjoint files only after Task 3 lands. Do not let two workers edit `workflow.py` simultaneously.

### Batch C: Recovery

- Task 9: Worker stale detection.
- Task 10: Continue/abandon API.
- Task 13: Cleanup policy.

Can run after Task 1 and Task 7 define result/provenance shape.

### Batch D: Phase 2 / Phase 3 Assets

- Task 11: Phase 2 checkpoint/provenance.
- Task 12: Phase 3 provenance.
- Task 14: Backend filtering APIs.

Can run partly in parallel with Batch C if write scopes are kept separate.

### Batch E: Frontend

- Task 15: progress display.
- Task 16: recovery UI.
- Task 17: Scene filters/manual fusion.
- Task 18: World filters/forced-map bug.
- Task 19: Outline filters/Phase 3 UI.
- Task 21: mobile layout.

Start after backend result/API shapes are stable. Mock Playwright can begin earlier using agreed contract, but expect one integration pass.

### Batch F: Acceptance

- Task 20: worker E2E.
- Task 22: real LLM 213-chapter acceptance.
- Task 23: full regression/docs.

Run last.

---

## Self-Review Checklist

- [ ] Phase 0 two-round offset prefetch is implemented and does not write formal Scene.
- [ ] Phase 0 and Phase 1a block only on final 422 rate > 40%.
- [ ] Phase 1b degrades, not blocks, when final 422 rate > 40%.
- [ ] Phase 1a uses正文; Phase 1b does not.
- [ ] Phase 1b windows are 30 chapters with 3 chapter overlap and concurrency 4.
- [ ] Formal Scene writes include provenance_key and are idempotent.
- [ ] Worker marks stale deep_import recoverable without auto-continuing.
- [ ] Continue recovery reuses original task_id.
- [ ] Abandon recovery deprecates/ignores only same workflow auto-derived assets.
- [ ] Phase 2 checkpoint lets recovery skip successful Scenes.
- [ ] Phase 3 structure assets carry provenance and can be filtered.
- [ ] Scene/world/outline management filters use backend query params with pagination.
- [ ] Manual Scene fusion offers all four user choices and never silently overwrites originals.
- [ ] World object management no longer forces navigation to map.
- [ ] Playwright covers DI-PW-001 through DI-PW-019.
- [ ] Real LLM acceptance records 213-chapter metrics.
