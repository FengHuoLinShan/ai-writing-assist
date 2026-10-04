# Phase2 Batch Parallel World Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 2 world-object extraction as batch-level parallel execution with serial Scene processing inside each batch, adjacent-boundary supplementation, and detailed action/dedup/audit diagnostics.

**Architecture:** Keep the public staged workflow unchanged and implement the new behavior inside `SceneEntityExtractionService`. Phase 2 reads committed Scenes, splits them into ordered batches, runs batches concurrently, preserves local rolling context inside each batch, then runs adjacent-boundary supplementation and exposes richer progress/result statistics through the existing `DeepImportProgress.quality_stats["phase2"]` path.

**Tech Stack:** Python 3.12, FastAPI backend modules, SQLAlchemy async sessions, pytest/pytest-asyncio, existing PostgreSQL async task queue, existing LLM client and Pydantic schemas.

---

## File Structure

- Modify `backend/modules/imports/scene_entity_extraction.py`
  - Add Phase 2 batch constants.
  - Add batch/window helper methods.
  - Add `_process_scenes_batched`.
  - Add `_process_scene_batch_serial`.
  - Add `_run_boundary_supplements`.
  - Add action/dedup stats collection while preserving existing return shape.
- Modify `backend/modules/imports/workflow.py`
  - Include new Phase 2 batch/boundary/action/dedup stats in `_phase2_quality_stats`.
  - Ensure staged world-object progress exposes the new stats through existing progress/result paths.
- Modify `backend/modules/imports/tests/test_workflow.py`
  - Add unit tests for batch splitting, batch concurrency with serial in-batch order, boundary windows, boundary failure degradation, stats merging, and no-Scene failure behavior.
- Modify `backend/modules/imports/tests/test_deep_import_real_llm.py`
  - Log new Phase 2 batch/boundary/action/dedup fields in real LLM JSONL summaries.
- Modify `backend/modules/imports/README.md`
  - Document the Phase 2 batch-parallel extraction semantics.

Do not modify frontend behavior in this implementation pass. Existing progress renderers already display task progress and summary fields; richer UI can be a later task.

---

### Task 1: Add Batch Constants And Pure Helpers

**Files:**
- Modify: `backend/modules/imports/scene_entity_extraction.py`
- Test: `backend/modules/imports/tests/test_workflow.py`

- [ ] **Step 1: Write failing tests for batch and boundary helpers**

Append these tests to `TestSceneEntityExtractionProgress` in `backend/modules/imports/tests/test_workflow.py`:

```python
    def test_phase2_splits_scenes_into_fixed_size_batches(self):
        service = SceneEntityExtractionService()
        scenes = [
            {"id": f"scene-{idx}", "scene_index": idx}
            for idx in range(1, 31)
        ]

        batches = service._split_scene_batches(scenes, batch_size=12)

        assert [[scene["scene_index"] for scene in batch] for batch in batches] == [
            list(range(1, 13)),
            list(range(13, 25)),
            list(range(25, 31)),
        ]

    def test_phase2_boundary_windows_use_adjacent_batch_edges_only(self):
        service = SceneEntityExtractionService()
        batches = [
            [{"scene_index": idx} for idx in range(1, 13)],
            [{"scene_index": idx} for idx in range(13, 25)],
            [{"scene_index": idx} for idx in range(25, 31)],
        ]

        windows = service._phase2_boundary_windows(batches, boundary_size=2)

        assert [
            [scene["scene_index"] for scene in window["scenes"]]
            for window in windows
        ] == [
            [11, 12, 13, 14],
            [23, 24, 25, 26],
        ]
        assert windows[0]["left_batch_index"] == 0
        assert windows[0]["right_batch_index"] == 1
        assert windows[1]["left_batch_index"] == 1
        assert windows[1]["right_batch_index"] == 2
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
cd backend
pytest modules/imports/tests/test_workflow.py::TestSceneEntityExtractionProgress::test_phase2_splits_scenes_into_fixed_size_batches modules/imports/tests/test_workflow.py::TestSceneEntityExtractionProgress::test_phase2_boundary_windows_use_adjacent_batch_edges_only -q
```

Expected: both tests fail with `AttributeError` for missing helper methods.

- [ ] **Step 3: Add constants and helper methods**

In `backend/modules/imports/scene_entity_extraction.py`, add constants after the existing Phase 2 constants:

```python
PHASE2_BATCH_SIZE_SCENES = 12
PHASE2_BATCH_CONCURRENCY = 6
PHASE2_BOUNDARY_SCENES = 2
```

Inside `SceneEntityExtractionService`, add these helper methods near `_phase2_checkpoint_by_scene`:

```python
    @staticmethod
    def _split_scene_batches(
        scenes: list[dict[str, Any]],
        *,
        batch_size: int = PHASE2_BATCH_SIZE_SCENES,
    ) -> list[list[dict[str, Any]]]:
        ordered = sorted(
            scenes,
            key=lambda scene: int(scene.get("scene_index") or 0),
        )
        size = max(1, int(batch_size or PHASE2_BATCH_SIZE_SCENES))
        return [
            ordered[index : index + size]
            for index in range(0, len(ordered), size)
        ]

    @staticmethod
    def _phase2_boundary_windows(
        batches: list[list[dict[str, Any]]],
        *,
        boundary_size: int = PHASE2_BOUNDARY_SCENES,
    ) -> list[dict[str, Any]]:
        size = max(1, int(boundary_size or PHASE2_BOUNDARY_SCENES))
        windows: list[dict[str, Any]] = []
        for index in range(len(batches) - 1):
            left = batches[index][-size:]
            right = batches[index + 1][:size]
            scenes = [*left, *right]
            if not scenes:
                continue
            windows.append(
                {
                    "window_index": len(windows),
                    "left_batch_index": index,
                    "right_batch_index": index + 1,
                    "scenes": scenes,
                }
            )
        return windows
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
cd backend
pytest modules/imports/tests/test_workflow.py::TestSceneEntityExtractionProgress::test_phase2_splits_scenes_into_fixed_size_batches modules/imports/tests/test_workflow.py::TestSceneEntityExtractionProgress::test_phase2_boundary_windows_use_adjacent_batch_edges_only -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/imports/scene_entity_extraction.py backend/modules/imports/tests/test_workflow.py
git commit -m "feat: add phase2 batch helper primitives"
```

---

### Task 2: Route Large Phase2 Runs Through Batch-Level Parallelism

**Files:**
- Modify: `backend/modules/imports/scene_entity_extraction.py`
- Test: `backend/modules/imports/tests/test_workflow.py`

- [ ] **Step 1: Write failing test for batch-level parallelism and serial in-batch order**

Append this test to `TestSceneEntityExtractionProgress`:

```python
    @pytest.mark.asyncio
    @patch("modules.world.facade.get_world_context", new_callable=AsyncMock)
    async def test_phase2_runs_batches_in_parallel_but_scenes_serial_within_batch(
        self,
        mock_ctx,
    ):
        mock_ctx.return_value = Mock(entities=[])
        service = SceneEntityExtractionService()
        service._get_scenes = AsyncMock(
            return_value=[
                {"id": f"scene-{idx}", "scene_index": idx, "chapter_ids": [str(idx)]}
                for idx in range(1, 25)
            ]
        )
        service._run_alias_relation_phase = AsyncMock(
            return_value={
                "total_aliases": 0,
                "total_relations": 0,
                "alias_relation_scenes": 0,
                "alias_relation_failed_scenes": [],
                "checkpoints": {"phase2b": {"scenes": []}},
            }
        )

        active_batches: set[int] = set()
        max_active_batches = 0
        scene_order_by_batch: dict[int, list[int]] = {}

        async def fake_process_scene(
            db,
            nid,
            scene,
            scene_idx,
            existing_context,
            accumulated_memory,
            seen_entity_keys,
            workflow_id,
            checkpoint,
        ):
            nonlocal max_active_batches
            batch_index = (int(scene["scene_index"]) - 1) // 12
            active_batches.add(batch_index)
            max_active_batches = max(max_active_batches, len(active_batches))
            scene_order_by_batch.setdefault(batch_index, []).append(
                int(scene["scene_index"])
            )
            await asyncio.sleep(0)
            active_batches.discard(batch_index)
            return {
                "created": 0,
                "relations": 0,
                "deltas": 0,
                "updated_context": existing_context,
                "updated_memory": accumulated_memory,
                "checkpoint": service._build_scene_checkpoint(
                    scene,
                    status="done",
                    workflow_id="wf",
                    scene_provenance_key=f"wf:scene:{scene['scene_index']}",
                    retry_count=0,
                ),
                "created_entity_ids": [],
                "created_relation_ids": [],
                "created_delta_ids": [],
            }

        service._process_scene = fake_process_scene
        progress_calls = []

        async def on_progress(completed, total):
            progress_calls.append((completed, total))

        result = await service.extract_by_scenes(
            AsyncMock(),
            str(uuid.uuid4()),
            workflow_id="wf",
            on_scene_progress=on_progress,
            existing_checkpoints={},
        )

        assert max_active_batches > 1
        assert scene_order_by_batch[0] == list(range(1, 13))
        assert scene_order_by_batch[1] == list(range(13, 25))
        assert result["phase2_batches_total"] == 2
        assert result["phase2_batches_completed"] == 2
        assert result["phase2_batch_size_scenes"] == 12
        assert result["phase2_batch_concurrency"] == 6
        assert progress_calls[0] == (0, 24)
        assert progress_calls[-1] == (24, 24)
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
cd backend
pytest modules/imports/tests/test_workflow.py::TestSceneEntityExtractionProgress::test_phase2_runs_batches_in_parallel_but_scenes_serial_within_batch -q
```

Expected: fail because large Phase 2 still uses the old global serial path and does not expose batch stats.

- [ ] **Step 3: Route large non-checkpointed runs into `_process_scenes_batched`**

In `extract_by_scenes`, after the small-sample/bulk path and before the existing global serial loop, add:

```python
        if total_scenes > PHASE2_BULK_MAX_SCENES and not checkpoint_by_scene:
            return await self._process_scenes_batched(
                db,
                nid,
                scenes,
                existing_context,
                workflow_id=workflow_id,
                on_scene_progress=on_scene_progress,
            )
```

- [ ] **Step 4: Implement `_process_scenes_batched` and `_process_scene_batch_serial`**

Add these methods before `_process_scenes_parallel_llm`:

```python
    async def _process_scenes_batched(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        existing_context: str,
        *,
        workflow_id: str | None,
        on_scene_progress: Callable[[int, int], Awaitable[None]] | None,
    ) -> dict[str, Any]:
        batches = self._split_scene_batches(scenes)
        semaphore = asyncio.Semaphore(PHASE2_BATCH_CONCURRENCY)
        completed_counter = {"value": 0}
        total_scenes = len(scenes)

        async def run_batch(batch_index: int, batch: list[dict[str, Any]]) -> dict[str, Any]:
            async with semaphore:
                return await self._process_scene_batch_serial(
                    db,
                    nid,
                    batch,
                    batch_index=batch_index,
                    existing_context=existing_context,
                    workflow_id=workflow_id,
                    completed_counter=completed_counter,
                    total_scenes=total_scenes,
                    on_scene_progress=on_scene_progress,
                )

        if on_scene_progress is not None:
            await on_scene_progress(0, total_scenes)

        batch_results = await asyncio.gather(
            *(run_batch(index, batch) for index, batch in enumerate(batches)),
            return_exceptions=True,
        )

        total_created = 0
        total_relations = 0
        total_deltas = 0
        failed_scene_indices: list[int] = []
        scene_checkpoints: list[dict[str, Any]] = []
        failed_batches: list[int] = []
        degraded_batches: list[int] = []
        error_kind: str | None = None
        error_message: str | None = None

        for batch_index, result in enumerate(batch_results):
            if isinstance(result, Exception):
                failed_batches.append(batch_index)
                degraded_batches.append(batch_index)
                error_kind = self._error_kind(result)
                error_message = str(result)[:300]
                for scene in batches[batch_index]:
                    failed_scene_indices.append(
                        int(scene.get("scene_index") or len(failed_scene_indices))
                    )
                    scene_checkpoints.append(
                        self._build_scene_checkpoint(
                            scene,
                            status="failed",
                            workflow_id=workflow_id,
                            scene_provenance_key=self._scene_provenance_key(
                                workflow_id,
                                scene,
                            ),
                            retry_count=1,
                            error=error_message,
                            error_kind=error_kind,
                        )
                    )
                continue

            total_created += int(result.get("created", 0) or 0)
            total_relations += int(result.get("relations", 0) or 0)
            total_deltas += int(result.get("deltas", 0) or 0)
            failed_scene_indices.extend(result.get("failed_scene_indices") or [])
            scene_checkpoints.extend(result.get("checkpoints") or [])
            if result.get("degraded"):
                degraded_batches.append(batch_index)
            if result.get("error_kind"):
                error_kind = result.get("error_kind")
                error_message = result.get("error_message")

        scene_checkpoints.sort(
            key=lambda checkpoint: int(checkpoint.get("scene_index") or 0),
        )

        audit_summary = await self._phase2_audit_summary(
            db,
            str(nid),
            workflow_id=workflow_id,
        )
        snapshot_health_summary = await self._phase2_snapshot_health_summary(
            db,
            str(nid),
            workflow_id=workflow_id,
        )
        phase2_result = {
            "total_created": total_created,
            "total_relations": total_relations,
            "total_aliases": 0,
            "total_deltas": total_deltas,
            "total_scenes": total_scenes,
            "degraded": bool(failed_scene_indices or degraded_batches),
            "error_kind": error_kind,
            "error_message": error_message,
            "failed_scene_indices": failed_scene_indices,
            "completed_scenes": total_scenes - len(failed_scene_indices),
            "skipped_scenes": 0,
            "rerun_scenes": 0,
            "stopped_early": False,
            "audit_summary": audit_summary,
            "snapshot_health_summary": snapshot_health_summary,
            "checkpoints": {"phase2": {"scenes": scene_checkpoints}},
            "phase2_batches_total": len(batches),
            "phase2_batches_completed": len(batches) - len(failed_batches),
            "phase2_batch_size_scenes": PHASE2_BATCH_SIZE_SCENES,
            "phase2_batch_concurrency": PHASE2_BATCH_CONCURRENCY,
            "phase2_failed_batches": failed_batches,
            "phase2_degraded_batches": degraded_batches,
            "phase2_boundary_windows_total": 0,
            "phase2_boundary_windows_completed": 0,
            "phase2_boundary_supplement_counts": {},
            "phase2_action_counts": {},
            "phase2_dedup_counts": {},
        }
        alias_result = await self._run_alias_relation_phase(
            db,
            nid,
            scenes,
            workflow_id=workflow_id,
        )
        return self._merge_alias_relation_result(phase2_result, alias_result)

    async def _process_scene_batch_serial(
        self,
        db: AsyncSession,
        nid,
        batch: list[dict[str, Any]],
        *,
        batch_index: int,
        existing_context: str,
        workflow_id: str | None,
        completed_counter: dict[str, int],
        total_scenes: int,
        on_scene_progress: Callable[[int, int], Awaitable[None]] | None,
    ) -> dict[str, Any]:
        local_context = existing_context
        local_memory: list[dict[str, Any]] = []
        seen_entity_keys: set[tuple[str, str]] = set()
        created = 0
        relations = 0
        deltas = 0
        failed_scene_indices: list[int] = []
        checkpoints: list[dict[str, Any]] = []
        error_kind: str | None = None
        error_message: str | None = None

        for scene_idx, scene in enumerate(batch):
            try:
                scene_result = await self._process_scene(
                    db,
                    nid,
                    scene,
                    scene_idx,
                    local_context,
                    local_memory,
                    seen_entity_keys,
                    workflow_id,
                    None,
                )
            except Exception as exc:
                error_kind = self._error_kind(exc)
                error_message = str(exc)[:300]
                scene_index = int(scene.get("scene_index") or scene_idx)
                failed_scene_indices.append(scene_index)
                checkpoints.append(
                    self._build_scene_checkpoint(
                        scene,
                        status="failed",
                        workflow_id=workflow_id,
                        scene_provenance_key=self._scene_provenance_key(
                            workflow_id,
                            scene,
                        ),
                        retry_count=1,
                        error=error_message,
                        error_kind=error_kind,
                    )
                )
            else:
                created += int(scene_result.get("created", 0) or 0)
                relations += int(scene_result.get("relations", 0) or 0)
                deltas += int(scene_result.get("deltas", 0) or 0)
                local_context = scene_result.get("updated_context") or local_context
                local_memory = scene_result.get("updated_memory") or local_memory
                checkpoint = scene_result.get("checkpoint")
                if checkpoint is not None:
                    checkpoints.append(checkpoint)

            completed_counter["value"] += 1
            if on_scene_progress is not None:
                await on_scene_progress(completed_counter["value"], total_scenes)

        return {
            "batch_index": batch_index,
            "created": created,
            "relations": relations,
            "deltas": deltas,
            "failed_scene_indices": failed_scene_indices,
            "checkpoints": checkpoints,
            "degraded": bool(failed_scene_indices),
            "error_kind": error_kind,
            "error_message": error_message,
        }
```

- [ ] **Step 5: Run target test and fix signature mismatches**

Run:

```bash
cd backend
pytest modules/imports/tests/test_workflow.py::TestSceneEntityExtractionProgress::test_phase2_runs_batches_in_parallel_but_scenes_serial_within_batch -q
```

Expected: `1 passed`.

- [ ] **Step 6: Run adjacent Phase 2 progress tests**

Run:

```bash
cd backend
pytest modules/imports/tests/test_workflow.py::TestSceneEntityExtractionProgress -q
```

Expected: all tests in the class pass.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/imports/scene_entity_extraction.py backend/modules/imports/tests/test_workflow.py
git commit -m "feat: run phase2 extraction by parallel batches"
```

---

### Task 3: Add Adjacent Boundary Supplement Pass

**Files:**
- Modify: `backend/modules/imports/scene_entity_extraction.py`
- Test: `backend/modules/imports/tests/test_workflow.py`

- [ ] **Step 1: Write failing tests for boundary supplementation**

Append these tests to `TestSceneEntityExtractionProgress`:

```python
    @pytest.mark.asyncio
    async def test_phase2_boundary_supplement_receives_only_adjacent_edges(self):
        service = SceneEntityExtractionService()
        batches = [
            [{"scene_index": idx, "id": f"scene-{idx}"} for idx in range(1, 13)],
            [{"scene_index": idx, "id": f"scene-{idx}"} for idx in range(13, 25)],
        ]
        seen_windows = []

        async def fake_process_boundary(db, nid, window, workflow_id):
            seen_windows.append(
                [scene["scene_index"] for scene in window["scenes"]]
            )
            return {
                "created": 1,
                "aliases": 1,
                "relations": 1,
                "link_suggestions": 1,
                "conflicts": 0,
                "failed": False,
            }

        service._process_boundary_window = fake_process_boundary

        result = await service._run_boundary_supplements(
            AsyncMock(),
            uuid.uuid4(),
            batches,
            workflow_id="wf",
        )

        assert seen_windows == [[11, 12, 13, 14]]
        assert result["phase2_boundary_windows_total"] == 1
        assert result["phase2_boundary_windows_completed"] == 1
        assert result["phase2_boundary_supplement_counts"] == {
            "created": 1,
            "aliases": 1,
            "relations": 1,
            "link_suggestions": 1,
            "conflicts": 0,
            "failed": 0,
        }

    @pytest.mark.asyncio
    async def test_phase2_boundary_failure_degrades_without_rollback(self):
        service = SceneEntityExtractionService()
        batches = [
            [{"scene_index": idx, "id": f"scene-{idx}"} for idx in range(1, 13)],
            [{"scene_index": idx, "id": f"scene-{idx}"} for idx in range(13, 25)],
        ]

        async def fail_boundary(db, nid, window, workflow_id):
            raise RuntimeError("boundary llm failed")

        service._process_boundary_window = fail_boundary

        result = await service._run_boundary_supplements(
            AsyncMock(),
            uuid.uuid4(),
            batches,
            workflow_id="wf",
        )

        assert result["phase2_boundary_windows_total"] == 1
        assert result["phase2_boundary_windows_completed"] == 0
        assert result["phase2_boundary_supplement_counts"]["failed"] == 1
        assert result["degraded"] is True
        assert result["error_kind"] == "unexpected"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd backend
pytest modules/imports/tests/test_workflow.py::TestSceneEntityExtractionProgress::test_phase2_boundary_supplement_receives_only_adjacent_edges modules/imports/tests/test_workflow.py::TestSceneEntityExtractionProgress::test_phase2_boundary_failure_degrades_without_rollback -q
```

Expected: fail with missing `_run_boundary_supplements`.

- [ ] **Step 3: Implement boundary supplement methods**

Add methods before `_process_scenes_bulk`:

```python
    async def _run_boundary_supplements(
        self,
        db: AsyncSession,
        nid,
        batches: list[list[dict[str, Any]]],
        *,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        windows = self._phase2_boundary_windows(batches)
        counts = {
            "created": 0,
            "aliases": 0,
            "relations": 0,
            "link_suggestions": 0,
            "conflicts": 0,
            "failed": 0,
        }
        completed = 0
        error_kind: str | None = None
        error_message: str | None = None

        for window in windows:
            try:
                result = await self._process_boundary_window(
                    db,
                    nid,
                    window,
                    workflow_id=workflow_id,
                )
            except Exception as exc:
                counts["failed"] += 1
                error_kind = self._error_kind(exc)
                error_message = str(exc)[:300]
                continue
            completed += 1
            counts["created"] += int(result.get("created", 0) or 0)
            counts["aliases"] += int(result.get("aliases", 0) or 0)
            counts["relations"] += int(result.get("relations", 0) or 0)
            counts["link_suggestions"] += int(
                result.get("link_suggestions", 0) or 0
            )
            counts["conflicts"] += int(result.get("conflicts", 0) or 0)
            if result.get("failed"):
                counts["failed"] += 1

        return {
            "phase2_boundary_windows_total": len(windows),
            "phase2_boundary_windows_completed": completed,
            "phase2_boundary_supplement_counts": counts,
            "degraded": counts["failed"] > 0,
            "error_kind": error_kind,
            "error_message": error_message,
        }

    async def _process_boundary_window(
        self,
        db: AsyncSession,
        nid,
        window: dict[str, Any],
        *,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        scenes = window["scenes"]
        entity_result = await self._process_scenes_bulk(
            db,
            nid,
            scenes,
            "边界补充：仅补相邻 batch 边界漏抽对象，不重写主 batch 结果。",
            workflow_id=workflow_id,
        )
        alias_result = await self._run_alias_relation_phase(
            db,
            nid,
            scenes,
            workflow_id=workflow_id,
        )
        return {
            "created": int(entity_result.get("created", 0) or 0),
            "aliases": int(alias_result.get("total_aliases", 0) or 0),
            "relations": int(alias_result.get("total_relations", 0) or 0),
            "link_suggestions": 0,
            "conflicts": 0,
            "failed": False,
        }
```

- [ ] **Step 4: Merge boundary result into batched Phase 2 result**

In `_process_scenes_batched`, before alias phase, add:

```python
        boundary_result = await self._run_boundary_supplements(
            db,
            nid,
            batches,
            workflow_id=workflow_id,
        )
        total_created += int(
            boundary_result["phase2_boundary_supplement_counts"].get("created", 0)
            or 0
        )
```

Then set these fields in `phase2_result`:

```python
            "degraded": bool(
                failed_scene_indices
                or degraded_batches
                or boundary_result.get("degraded")
            ),
            "error_kind": error_kind or boundary_result.get("error_kind"),
            "error_message": error_message or boundary_result.get("error_message"),
            "phase2_boundary_windows_total": boundary_result[
                "phase2_boundary_windows_total"
            ],
            "phase2_boundary_windows_completed": boundary_result[
                "phase2_boundary_windows_completed"
            ],
            "phase2_boundary_supplement_counts": boundary_result[
                "phase2_boundary_supplement_counts"
            ],
```

- [ ] **Step 5: Run boundary tests**

Run:

```bash
cd backend
pytest modules/imports/tests/test_workflow.py::TestSceneEntityExtractionProgress::test_phase2_boundary_supplement_receives_only_adjacent_edges modules/imports/tests/test_workflow.py::TestSceneEntityExtractionProgress::test_phase2_boundary_failure_degrades_without_rollback -q
```

Expected: `2 passed`.

- [ ] **Step 6: Run batch test again**

Run:

```bash
cd backend
pytest modules/imports/tests/test_workflow.py::TestSceneEntityExtractionProgress::test_phase2_runs_batches_in_parallel_but_scenes_serial_within_batch -q
```

Expected: pass. If this test now triggers real boundary work, stub `service._run_boundary_supplements = AsyncMock(return_value={...})` in the test with zero counts.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/imports/scene_entity_extraction.py backend/modules/imports/tests/test_workflow.py
git commit -m "feat: add phase2 adjacent boundary supplements"
```

---

### Task 4: Add Action And Dedup Statistics

**Files:**
- Modify: `backend/modules/imports/scene_entity_extraction.py`
- Modify: `backend/modules/imports/workflow.py`
- Test: `backend/modules/imports/tests/test_workflow.py`

- [ ] **Step 1: Write failing test for action/dedup stats**

Append this test to `TestSceneEntityExtractionProgress`:

```python
    @pytest.mark.asyncio
    @patch("modules.world.facade.find_similar_entities", new_callable=AsyncMock)
    @patch("modules.world.facade.create_entity", new_callable=AsyncMock)
    async def test_phase2_persist_entities_collects_action_and_dedup_stats(
        self,
        mock_create,
        mock_find_similar,
    ):
        service = SceneEntityExtractionService()
        mock_find_similar.return_value = [
            Mock(similarity_score=0.96, match_method="exact_name")
        ]
        mock_create.return_value = {"id": str(uuid.uuid4())}
        stats = service._empty_phase2_persistence_stats()

        entities = [
            ExtractedEntity(
                name="克莱恩",
                entity_type="character",
                summary="主角",
                suggested_action="create_new",
                confidence=0.92,
            ),
            ExtractedEntity(
                name="廷根市",
                entity_type="location",
                summary="城市",
                suggested_action="link_to_existing",
                suggested_existing_entity_name="廷根",
                confidence=0.76,
            ),
            ExtractedEntity(
                name="路人甲",
                entity_type="character",
                summary="一次性人物",
                suggested_action="ignore",
                confidence=0.3,
            ),
            ExtractedEntity(
                name="普通晚餐",
                entity_type="item",
                summary="临时道具",
                suggested_action="temporary_only",
                confidence=0.52,
            ),
        ]

        created = await service._persist_entities(
            AsyncMock(),
            uuid.uuid4(),
            entities,
            scene_index=1,
            source_chapter_index=1,
            persistence_stats=stats,
        )

        assert created == 2
        assert stats["action_counts"] == {
            "create_new": 1,
            "link_to_existing": 1,
            "ignore": 1,
            "temporary_only": 1,
        }
        assert stats["dedup_counts"]["skipped"] == 1
        assert stats["linked_to_existing"] == 1
        assert stats["ignored"] == 1
        assert stats["temporary_only"] == 1
        assert stats["low_confidence"] == 2
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
cd backend
pytest modules/imports/tests/test_workflow.py::TestSceneEntityExtractionProgress::test_phase2_persist_entities_collects_action_and_dedup_stats -q
```

Expected: fail because `_empty_phase2_persistence_stats` and `persistence_stats` do not exist.

- [ ] **Step 3: Add persistence stats helper**

In `SceneEntityExtractionService`, add:

```python
    @staticmethod
    def _empty_phase2_persistence_stats() -> dict[str, Any]:
        return {
            "action_counts": {
                "create_new": 0,
                "link_to_existing": 0,
                "ignore": 0,
                "temporary_only": 0,
            },
            "dedup_counts": {
                "checked": 0,
                "skipped": 0,
                "degraded": 0,
            },
            "linked_to_existing": 0,
            "ignored": 0,
            "temporary_only": 0,
            "low_confidence": 0,
        }

    @staticmethod
    def _merge_phase2_persistence_stats(
        target: dict[str, Any],
        source: dict[str, Any],
    ) -> dict[str, Any]:
        for key, value in (source.get("action_counts") or {}).items():
            target.setdefault("action_counts", {}).setdefault(key, 0)
            target["action_counts"][key] += int(value or 0)
        for key, value in (source.get("dedup_counts") or {}).items():
            target.setdefault("dedup_counts", {}).setdefault(key, 0)
            target["dedup_counts"][key] += int(value or 0)
        for key in ("linked_to_existing", "ignored", "temporary_only", "low_confidence"):
            target[key] = int(target.get(key, 0) or 0) + int(source.get(key, 0) or 0)
        return target
```

- [ ] **Step 4: Extend `_persist_entities` signature and counters**

Change `_persist_entities` signature:

```python
        result_refs: list[dict[str, str]] | None = None,
        persistence_stats: dict[str, Any] | None = None,
```

Inside the loop, immediately after `action = ent.suggested_action`, add:

```python
            if persistence_stats is not None:
                persistence_stats.setdefault("action_counts", {}).setdefault(action, 0)
                persistence_stats["action_counts"][action] += 1
                if ent.confidence < 0.6:
                    persistence_stats["low_confidence"] = (
                        int(persistence_stats.get("low_confidence", 0) or 0) + 1
                    )
                if action == "link_to_existing":
                    persistence_stats["linked_to_existing"] = (
                        int(persistence_stats.get("linked_to_existing", 0) or 0) + 1
                    )
                if action == "ignore":
                    persistence_stats["ignored"] = (
                        int(persistence_stats.get("ignored", 0) or 0) + 1
                    )
                if action == "temporary_only":
                    persistence_stats["temporary_only"] = (
                        int(persistence_stats.get("temporary_only", 0) or 0) + 1
                    )
```

Replace the dedup check block with:

```python
            if action == "create_new":
                try:
                    similar = await find_similar_entities(
                        db,
                        str(nid),
                        ent.name,
                        aliases=[
                            alias.get("alias", "")
                            for alias in (ent.aliases or [])
                            if isinstance(alias, dict)
                        ],
                        entity_type=ent.entity_type,
                    )
                    if persistence_stats is not None:
                        persistence_stats["dedup_counts"]["checked"] += 1
                except Exception:
                    similar = []
                    if persistence_stats is not None:
                        persistence_stats["dedup_counts"]["degraded"] += 1
                high_confidence_duplicate = any(
                    (
                        getattr(item, "similarity_score", None)
                        if not isinstance(item, dict)
                        else item.get("similarity_score", item.get("score", 0))
                    )
                    >= 0.88
                    for item in similar
                )
                if high_confidence_duplicate:
                    seen_entity_keys.add(entity_key)
                    if persistence_stats is not None:
                        persistence_stats["dedup_counts"]["skipped"] += 1
                    continue
```

- [ ] **Step 5: Thread stats through batch and existing paths**

In `_process_scene_batch_serial`, initialize:

```python
        persistence_stats = self._empty_phase2_persistence_stats()
```

Pass it into `_process_scene` by adding a new optional argument only if `_process_scene` is updated to accept it. Prefer updating `_process_scene` signature with:

```python
        persistence_stats: dict[str, Any] | None = None,
```

Then pass `persistence_stats=persistence_stats` into `_persist_entities` inside `_process_scene`.

Return it from `_process_scene_batch_serial`:

```python
            "persistence_stats": persistence_stats,
```

In `_process_scenes_batched`, initialize:

```python
        persistence_stats = self._empty_phase2_persistence_stats()
```

When folding batch results, add:

```python
            self._merge_phase2_persistence_stats(
                persistence_stats,
                result.get("persistence_stats") or self._empty_phase2_persistence_stats(),
            )
```

Set:

```python
            "phase2_action_counts": persistence_stats["action_counts"],
            "phase2_dedup_counts": persistence_stats["dedup_counts"],
            "phase2_linked_to_existing": persistence_stats["linked_to_existing"],
            "phase2_ignored": persistence_stats["ignored"],
            "phase2_temporary_only": persistence_stats["temporary_only"],
            "phase2_low_confidence": persistence_stats["low_confidence"],
```

- [ ] **Step 6: Extend workflow quality stats**

In `backend/modules/imports/workflow.py`, update `_phase2_quality_stats` to include:

```python
            "phase2_batches_total": int(phase2_result.get("phase2_batches_total", 0) or 0),
            "phase2_batches_completed": int(
                phase2_result.get("phase2_batches_completed", 0) or 0
            ),
            "phase2_batch_size_scenes": int(
                phase2_result.get("phase2_batch_size_scenes", 0) or 0
            ),
            "phase2_batch_concurrency": int(
                phase2_result.get("phase2_batch_concurrency", 0) or 0
            ),
            "phase2_boundary_windows_total": int(
                phase2_result.get("phase2_boundary_windows_total", 0) or 0
            ),
            "phase2_boundary_windows_completed": int(
                phase2_result.get("phase2_boundary_windows_completed", 0) or 0
            ),
            "phase2_action_counts": phase2_result.get("phase2_action_counts") or {},
            "phase2_dedup_counts": phase2_result.get("phase2_dedup_counts") or {},
            "phase2_boundary_supplement_counts": (
                phase2_result.get("phase2_boundary_supplement_counts") or {}
            ),
            "phase2_failed_batches": phase2_result.get("phase2_failed_batches") or [],
            "phase2_degraded_batches": (
                phase2_result.get("phase2_degraded_batches") or []
            ),
```

- [ ] **Step 7: Run stats tests**

Run:

```bash
cd backend
pytest modules/imports/tests/test_workflow.py::TestSceneEntityExtractionProgress::test_phase2_persist_entities_collects_action_and_dedup_stats -q
```

Expected: `1 passed`.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/imports/scene_entity_extraction.py backend/modules/imports/workflow.py backend/modules/imports/tests/test_workflow.py
git commit -m "feat: add phase2 action and dedup diagnostics"
```

---

### Task 5: Preserve Existing Stage Behavior And Progress Contracts

**Files:**
- Modify: `backend/modules/imports/tests/test_workflow.py`
- Modify: `backend/modules/imports/workflow.py`
- Test: `backend/modules/imports/tests/test_workflow.py`

- [ ] **Step 1: Write failing workflow stats test**

Append this test near existing Phase 2 workflow stats tests:

```python
    def test_phase2_quality_stats_include_batch_boundary_and_action_counts(self):
        workflow = DeepImportWorkflow()
        stats = workflow._phase2_quality_stats(
            {
                "total_created": 3,
                "total_relations": 2,
                "total_aliases": 1,
                "total_deltas": 4,
                "total_scenes": 24,
                "completed_scenes": 24,
                "phase2_batches_total": 2,
                "phase2_batches_completed": 2,
                "phase2_batch_size_scenes": 12,
                "phase2_batch_concurrency": 6,
                "phase2_boundary_windows_total": 1,
                "phase2_boundary_windows_completed": 1,
                "phase2_action_counts": {"create_new": 3, "ignore": 1},
                "phase2_dedup_counts": {"checked": 3, "skipped": 1},
                "phase2_boundary_supplement_counts": {
                    "created": 1,
                    "aliases": 1,
                    "relations": 0,
                    "link_suggestions": 1,
                    "conflicts": 0,
                    "failed": 0,
                },
                "phase2_failed_batches": [],
                "phase2_degraded_batches": [],
            }
        )

        assert stats["phase2_batches_total"] == 2
        assert stats["phase2_batches_completed"] == 2
        assert stats["phase2_batch_size_scenes"] == 12
        assert stats["phase2_batch_concurrency"] == 6
        assert stats["phase2_boundary_windows_total"] == 1
        assert stats["phase2_boundary_windows_completed"] == 1
        assert stats["phase2_action_counts"]["create_new"] == 3
        assert stats["phase2_dedup_counts"]["skipped"] == 1
        assert stats["phase2_boundary_supplement_counts"]["created"] == 1
```

- [ ] **Step 2: Run test and verify it fails before Task 4 Step 6 or passes after it**

Run:

```bash
cd backend
pytest modules/imports/tests/test_workflow.py::TestDeepImportWorkflow::test_phase2_quality_stats_include_batch_boundary_and_action_counts -q
```

Expected: pass if Task 4 already extended `_phase2_quality_stats`; otherwise fail and then apply Task 4 Step 6.

- [ ] **Step 3: Run world-stage tests to prevent staged workflow regressions**

Run:

```bash
cd backend
pytest modules/imports/tests/test_workflow.py -k "world_object_stage or phase2_quality_stats or extract_by_scenes_reports_scene_progress" -q
```

Expected: all selected tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/imports/workflow.py backend/modules/imports/tests/test_workflow.py
git commit -m "test: cover phase2 batch progress stats"
```

---

### Task 6: Enhance Real LLM JSONL Diagnostics

**Files:**
- Modify: `backend/modules/imports/tests/test_deep_import_real_llm.py`
- Test: `backend/modules/imports/tests/test_deep_import_real_llm.py`

- [ ] **Step 1: Add real LLM log field assertions**

Find the helper that serializes progress/final summaries in `backend/modules/imports/tests/test_deep_import_real_llm.py`. Extend the Phase 2 payload with:

```python
        "phase2_batches": {
            "total": phase2_stats.get("phase2_batches_total"),
            "completed": phase2_stats.get("phase2_batches_completed"),
            "batch_size_scenes": phase2_stats.get("phase2_batch_size_scenes"),
            "concurrency": phase2_stats.get("phase2_batch_concurrency"),
            "failed_batches": phase2_stats.get("phase2_failed_batches"),
            "degraded_batches": phase2_stats.get("phase2_degraded_batches"),
        },
        "phase2_boundary": {
            "windows_total": phase2_stats.get("phase2_boundary_windows_total"),
            "windows_completed": phase2_stats.get(
                "phase2_boundary_windows_completed"
            ),
            "supplement_counts": phase2_stats.get(
                "phase2_boundary_supplement_counts"
            ),
        },
        "phase2_actions": phase2_stats.get("phase2_action_counts"),
        "phase2_dedup": phase2_stats.get("phase2_dedup_counts"),
```

If the file has explicit acceptance checks, add checks that these keys exist when Phase 2 ran:

```python
    _record_acceptance_check(
        checks,
        name="phase2_batch_diagnostics_recorded",
        expected="phase2 batch/boundary/action/dedup diagnostics present",
        actual={
            "phase2_batches": bool(phase2_stats.get("phase2_batches_total") is not None),
            "phase2_boundary": bool(
                phase2_stats.get("phase2_boundary_windows_total") is not None
            ),
            "phase2_actions": bool(phase2_stats.get("phase2_action_counts") is not None),
            "phase2_dedup": bool(phase2_stats.get("phase2_dedup_counts") is not None),
        },
        status=(
            "passed"
            if phase2_stats.get("phase2_batches_total") is not None
            and phase2_stats.get("phase2_boundary_windows_total") is not None
            else "failed"
        ),
    )
```

- [ ] **Step 2: Run non-real test mode**

Run:

```bash
cd backend
pytest modules/imports/tests/test_deep_import_real_llm.py -q
```

Expected: pass or skip real LLM execution unless the real env flags are set.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/imports/tests/test_deep_import_real_llm.py
git commit -m "test: log phase2 batch diagnostics in real llm tests"
```

---

### Task 7: Update Module Documentation

**Files:**
- Modify: `backend/modules/imports/README.md`
- Test: documentation and diff checks

- [ ] **Step 1: Update README Phase 2 section**

In `backend/modules/imports/README.md`, update the Phase 2 responsibility bullets to include:

```markdown
- 分阶段世界对象自动提取执行 Phase 2a / 2b：先基于已提交 Scene 抽取世界对象与 Delta，再补抽别名 / 关系。
- Phase 2 对大量 Scene 使用 batch 间并发、batch 内 Scene 串行的调度：默认 12 Scene / batch、6 batch 并发；每个 batch 保留局部 rolling context。
- Phase 2 只对相邻 batch 边界执行补充抽取：前批最后 2 个 Scene + 后批最前 2 个 Scene；不做全局对象融合扫描。
- Phase 2 入库前通过 world facade 使用名称 / 别名 / embedding 去重能力，并在 progress/result 中记录 action、dedup、boundary supplement 和 degraded 统计。
```

- [ ] **Step 2: Run markdown diff check**

Run:

```bash
git diff --check -- backend/modules/imports/README.md docs/superpowers/specs/2026-07-01-phase2-batch-parallel-world-extraction-design.md
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/imports/README.md
git commit -m "docs: document phase2 batch extraction behavior"
```

---

### Task 8: Final Verification

**Files:**
- Verify all touched backend files.

- [ ] **Step 1: Run targeted backend tests**

Run:

```bash
cd backend
pytest modules/imports/tests/test_workflow.py modules/imports/tests/test_deep_import_real_llm.py -q
```

Expected: all tests pass; real LLM cases skip unless enabled by env flags.

- [ ] **Step 2: Run scene entity extraction focused tests**

Run:

```bash
cd backend
pytest modules/imports/tests/test_scene_entity_extraction.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Run ruff on touched backend files**

Run:

```bash
cd backend
ruff check modules/imports/scene_entity_extraction.py modules/imports/workflow.py modules/imports/tests/test_workflow.py modules/imports/tests/test_deep_import_real_llm.py
```

Expected: no lint errors.

- [ ] **Step 4: Run diff check**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 5: Inspect final staged scope before any final commit**

Run:

```bash
git status --short
git diff --stat
```

Expected: only Phase 2 batch extraction implementation, tests, and docs are changed in addition to any unrelated pre-existing worktree changes. Do not revert unrelated changes.

- [ ] **Step 6: Final commit if previous tasks were not committed individually**

If tasks were implemented without per-task commits, commit the final scope:

```bash
git add backend/modules/imports/scene_entity_extraction.py backend/modules/imports/workflow.py backend/modules/imports/tests/test_workflow.py backend/modules/imports/tests/test_deep_import_real_llm.py backend/modules/imports/README.md
git commit -m "feat: batch phase2 world object extraction"
```

---

## Self-Review Notes

- Spec coverage: the plan covers batch splitting, batch-level concurrency, serial in-batch extraction, adjacent-only 4-Scene boundary supplementation, facade-only dedup, suggested actions, audit counts, progress/result diagnostics, real LLM logging, and documentation.
- Scope check: this is one backend-focused subsystem. It does not include frontend UI changes or global object fusion, matching the spec non-goals.
- Type consistency: all new result fields use `phase2_*` names matching the spec and are routed through `phase2_result` into `_phase2_quality_stats`.
- Risk: Task 2 uses existing `_process_scene` internals. If `_process_scene` currently does not return `checkpoint`, adjust the implementation by building the checkpoint in `_process_scene_batch_serial` from created refs, matching the existing global serial loop behavior.
