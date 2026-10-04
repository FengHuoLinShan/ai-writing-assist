# Writing Cross-Module Conflict Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build reusable cross-module evidence support for writing conflict checks, including candidate-aware map evidence, memory continuity evidence, frontend evidence drawers, realistic user-path validation, and real LLM acceptance.

**Architecture:** `writing` owns conflict-check persistence and orchestration, while `outline`, `world.map`, `memory`, and `context` provide stable evidence through contracts/facades. Evidence is persisted in `writing_conflict_items.location_json` as a backwards-compatible JSON payload, avoiding a new trace table.

**Tech Stack:** FastAPI, async SQLAlchemy, Pydantic, pytest, vanilla JS, Vitest, Playwright, existing OpenAI-compatible LLM infrastructure.

---

## File Structure

- Create `backend/modules/writing/conflict_evidence.py`
  - Owns the small evidence payload helpers used by `writing`.
  - Does not import other modules.
- Create `backend/modules/writing/tests/test_conflict_evidence.py`
  - Unit tests for evidence payload and snapshot trimming.
- Modify `backend/modules/writing/services.py`
  - Uses evidence helpers in `_scene_rule_items`, `_map_rule_items`, `_memory_rule_items`.
  - Calls `memory.facade.get_continuity_evidence_for_writing`.
- Modify `backend/modules/writing/repositories.py`
  - Preserves lightweight evidence in publish snapshots.
- Modify `backend/modules/writing/tests/test_conflict_checks.py`
  - Adds cross-module evidence assertions and include-candidates checks.
- Modify `backend/modules/world/map_schemas.py`
  - Adds candidate-support and evidence/open-target fields to scene summary items/warnings.
- Modify `backend/modules/world/services/map_scene_summary.py`
  - Makes `include_candidates` real and marks candidate/conflicted observation dependencies.
- Modify `backend/modules/world/map_facade.py`
  - Passes `include_candidates` to `MapSceneSummaryService`.
- Modify `backend/modules/world/tests/test_map_scene_summary.py`
  - Tests confirmed-only vs candidate-aware map summary behavior.
- Modify `backend/modules/memory/contracts.py`
  - Adds a `MemoryContinuityEvidenceContract` dataclass.
- Modify `backend/modules/memory/facade.py`
  - Adds `get_continuity_evidence_for_writing`.
- Modify `backend/modules/memory/tests/test_services.py`
  - Tests memory continuity evidence shape and empty evidence fallback.
- Modify `frontend-console/views/writingView.js`
  - Adds check options modal, passes `include_candidates`, supports memory source opening.
- Modify `frontend-console/views/writingConflictModal.js`
  - Adds evidence drawer rendering and open-target actions.
- Modify `frontend-console/tests/writingView.test.js`
  - Tests option modal, candidate flag, open-target feedback.
- Modify `frontend-console/tests/writingConflictModal.test.js`
  - Tests evidence drawer rendering, escaping, and AI pending-object confirmation.
- Modify `frontend-console/e2e/writing-conflict.spec.js`
  - Adds realistic user-path coverage for canonical, candidate-aware, source opening, publish snapshot, and degradation.
- Modify `frontend-console/e2e/writing-conflict-real-llm.spec.js`
  - Ensures real LLM smoke includes evidence and no-side-effect checks.
- Modify docs after implementation:
  - `backend/modules/writing/README.md`
  - `backend/modules/world/README.md`
  - `backend/modules/memory/README.md`
  - `docs/modules/11_writing.md`

Implementation workers must not stage unrelated dirty files. Use path-limited `git add` for each task.

---

### Task 1: Writing Evidence Helper

**Files:**
- Create: `backend/modules/writing/conflict_evidence.py`
- Create: `backend/modules/writing/tests/test_conflict_evidence.py`

- [ ] **Step 1: Write the failing evidence helper tests**

Create `backend/modules/writing/tests/test_conflict_evidence.py` with:

```python
from modules.writing.conflict_evidence import (
    evidence_location,
    snapshot_location,
)


def test_evidence_location_builds_stable_payload() -> None:
    payload = evidence_location(
        source_module="outline",
        source_type="scene.must_not_happen",
        source_id="scene-1",
        source_label="Scene：东门交涉",
        source_field="禁止发生",
        source_excerpt="主角死亡",
        open_target={"kind": "outline_scene", "scene_id": "scene-1"},
        text_range={"start": 3, "end": 7},
        needs_review_reason=None,
    )

    assert payload == {
        "text_range": {"start": 3, "end": 7},
        "source": {
            "module": "outline",
            "type": "scene.must_not_happen",
            "id": "scene-1",
            "label": "Scene：东门交涉",
            "field": "禁止发生",
            "excerpt": "主角死亡",
        },
        "open_target": {"kind": "outline_scene", "scene_id": "scene-1"},
        "needs_review_reason": None,
    }


def test_snapshot_location_keeps_lightweight_evidence() -> None:
    location = evidence_location(
        source_module="world",
        source_type="map.scene_summary",
        source_id="scene-1",
        source_label="地图：九州",
        source_field="地图风险",
        source_excerpt="粮仓起火：待确认",
        open_target={"kind": "map_object", "map_id": "map-1", "observation_id": "obs-1"},
        text_range=None,
        needs_review_reason="依赖待确认地图观察",
    )

    trimmed = snapshot_location(location)

    assert trimmed == {
        "source": location["source"],
        "open_target": location["open_target"],
        "needs_review_reason": "依赖待确认地图观察",
    }
    assert "text_range" not in trimmed
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd backend
pytest modules/writing/tests/test_conflict_evidence.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'modules.writing.conflict_evidence'`.

- [ ] **Step 3: Implement the evidence helper**

Create `backend/modules/writing/conflict_evidence.py`:

```python
"""Conflict evidence payload helpers for writing checks."""

from __future__ import annotations

from typing import Any


def evidence_location(
    *,
    source_module: str,
    source_type: str,
    source_id: str | None,
    source_label: str,
    source_field: str,
    source_excerpt: str,
    open_target: dict[str, Any],
    text_range: dict[str, int] | None = None,
    needs_review_reason: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": {
            "module": source_module,
            "type": source_type,
            "id": source_id,
            "label": source_label,
            "field": source_field,
            "excerpt": source_excerpt,
        },
        "open_target": open_target,
        "needs_review_reason": needs_review_reason,
    }
    if text_range is not None:
        payload["text_range"] = text_range
    return payload


def snapshot_location(location_json: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(location_json, dict):
        return None
    result: dict[str, Any] = {}
    source = location_json.get("source")
    open_target = location_json.get("open_target")
    if isinstance(source, dict):
        result["source"] = source
    if isinstance(open_target, dict):
        result["open_target"] = open_target
    if "needs_review_reason" in location_json:
        result["needs_review_reason"] = location_json.get("needs_review_reason")
    return result or None
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
cd backend
pytest modules/writing/tests/test_conflict_evidence.py -q
```

Expected: PASS, `2 passed`.

- [ ] **Step 5: Commit**

Run:

```bash
git add backend/modules/writing/conflict_evidence.py backend/modules/writing/tests/test_conflict_evidence.py
git commit -m "feat(writing): add conflict evidence helpers"
```

---

### Task 2: Outline Evidence in Writing Rules

**Files:**
- Modify: `backend/modules/writing/services.py`
- Modify: `backend/modules/writing/tests/test_conflict_checks.py`

- [ ] **Step 1: Add failing assertions for outline evidence**

In `backend/modules/writing/tests/test_conflict_checks.py`, extend `test_conflict_check_persists_rule_hits_and_summary` after the existing `forbidden_present` assertions:

```python
    forbidden_location = kinds["forbidden_present"]["location_json"]
    assert forbidden_location["source"] == {
        "module": "outline",
        "type": "scene.must_not_happen",
        "id": scene["id"],
        "label": "Scene：东门交涉",
        "field": "禁止发生",
        "excerpt": "主角死亡",
    }
    assert forbidden_location["open_target"] == {
        "kind": "outline_scene",
        "scene_id": scene["id"],
    }
    assert forbidden_location["text_range"]["start"] == 0
    assert forbidden_location["needs_review_reason"] is None
```

Also extend the required-missing assertion:

```python
    required_items = [
        item for item in body["items"] if item["kind"] == "required_missing"
    ]
    assert all(
        item["location_json"]["open_target"]["kind"] == "outline_scene"
        for item in required_items
    )
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
cd backend
pytest modules/writing/tests/test_conflict_checks.py::test_conflict_check_persists_rule_hits_and_summary -q
```

Expected: FAIL because `location_json.source` and `open_target` are missing.

- [ ] **Step 3: Update `_scene_rule_items` to emit evidence payloads**

In `backend/modules/writing/services.py`, import the helper near existing writing imports:

```python
from modules.writing.conflict_evidence import evidence_location
```

Replace the body of `_scene_rule_items` with:

```python
    def _scene_rule_items(self, scene: object, content: str) -> list[dict]:
        items = []
        scene_id = getattr(scene, "id", None)
        title = getattr(scene, "title", None) or "未命名 Scene"
        scene_label = f"Scene：{title}"
        for phrase in _split_rule_phrases(getattr(scene, "must_not_happen", None)):
            text_range = _locate_phrase(content, phrase)
            if phrase in content:
                items.append(
                    {
                        "kind": "forbidden_present",
                        "severity": "high",
                        "source_module": "outline",
                        "source_type": "scene.must_not_happen",
                        "source_id": scene_id,
                        "evidence_summary": f"正文出现 Scene 禁止发生项：{phrase}",
                        "location_json": evidence_location(
                            source_module="outline",
                            source_type="scene.must_not_happen",
                            source_id=scene_id,
                            source_label=scene_label,
                            source_field="禁止发生",
                            source_excerpt=phrase,
                            open_target={
                                "kind": "outline_scene",
                                "scene_id": scene_id,
                            },
                            text_range=text_range,
                        ),
                    }
                )
        for phrase in _split_rule_phrases(getattr(scene, "must_happen", None)):
            if phrase not in content:
                items.append(
                    {
                        "kind": "required_missing",
                        "severity": "medium",
                        "source_module": "outline",
                        "source_type": "scene.must_happen",
                        "source_id": scene_id,
                        "evidence_summary": f"正文尚未覆盖 Scene 必须发生项：{phrase}",
                        "location_json": evidence_location(
                            source_module="outline",
                            source_type="scene.must_happen",
                            source_id=scene_id,
                            source_label=scene_label,
                            source_field="必须发生",
                            source_excerpt=phrase,
                            open_target={
                                "kind": "outline_scene",
                                "scene_id": scene_id,
                            },
                        ),
                    }
                )
        return items
```

- [ ] **Step 4: Run the focused test**

Run:

```bash
cd backend
pytest modules/writing/tests/test_conflict_checks.py::test_conflict_check_persists_rule_hits_and_summary -q
```

Expected: PASS.

- [ ] **Step 5: Run writing evidence tests**

Run:

```bash
cd backend
pytest modules/writing/tests/test_conflict_evidence.py modules/writing/tests/test_conflict_checks.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add backend/modules/writing/services.py backend/modules/writing/tests/test_conflict_checks.py
git commit -m "feat(writing): attach outline evidence to conflict items"
```

---

### Task 3: Candidate-Aware World Map Summary

**Files:**
- Modify: `backend/modules/world/map_schemas.py`
- Modify: `backend/modules/world/services/map_scene_summary.py`
- Modify: `backend/modules/world/map_facade.py`
- Modify: `backend/modules/world/tests/test_map_scene_summary.py`

- [ ] **Step 1: Add failing map summary tests**

In `backend/modules/world/tests/test_map_scene_summary.py`, add:

```python
@pytest.mark.asyncio
async def test_scene_summary_excludes_candidate_observations_by_default(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    scene = await _create_scene(db_session, novel_id, scene_index=1)
    map_resp = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    await async_client.post(
        f"/api/world/maps/{map_resp.id}/observations",
        params={"novel_id": novel_id},
        json={
            "target_name": "粮仓起火",
            "target_entity_type": "event",
            "dynamic_type": "risk",
            "review_state": "candidate",
            "scene_id": str(scene.id),
            "scene_index": 1,
            "spatial_anchor": {"hex_q": 2, "hex_r": 3},
            "evidence_text": "粮仓火势正在扩大",
        },
    )

    summary = await summarize_scene_map_for_writing(
        db_session,
        novel_id,
        str(scene.id),
        include_candidates=False,
    )

    assert summary["candidate_support"] == "supported"
    assert summary["risks"] == []


@pytest.mark.asyncio
async def test_scene_summary_marks_candidate_observation_evidence(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    scene = await _create_scene(db_session, novel_id, scene_index=1)
    map_resp = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    observation_resp = await async_client.post(
        f"/api/world/maps/{map_resp.id}/observations",
        params={"novel_id": novel_id},
        json={
            "target_name": "粮仓起火",
            "target_entity_type": "event",
            "dynamic_type": "risk",
            "review_state": "candidate",
            "scene_id": str(scene.id),
            "scene_index": 1,
            "spatial_anchor": {"hex_q": 2, "hex_r": 3},
            "evidence_text": "粮仓火势正在扩大",
        },
    )
    observation_id = observation_resp.json()["id"]

    summary = await summarize_scene_map_for_writing(
        db_session,
        novel_id,
        str(scene.id),
        include_candidates=True,
    )

    assert summary["candidate_support"] == "supported"
    assert summary["risks"][0]["depends_on_candidate"] is True
    assert summary["risks"][0]["candidate_review_state"] == "candidate"
    assert summary["risks"][0]["evidence_excerpt"] == "粮仓火势正在扩大"
    assert summary["risks"][0]["open_target"]["observation_id"] == observation_id
```

- [ ] **Step 2: Run the tests to verify failure**

Run:

```bash
cd backend
pytest modules/world/tests/test_map_scene_summary.py -q
```

Expected: FAIL because `candidate_support`, `depends_on_candidate`, `evidence_excerpt`, and `open_target` do not exist.

- [ ] **Step 3: Extend map summary schemas**

In `backend/modules/world/map_schemas.py`, update the summary models:

```python
class MapOpenTarget(BaseModel):
    """前端打开地图时使用的稳定目标。"""

    mode: Literal["overview", "recent", "map"]
    map_id: str | None = None
    scene_id: str | None = None
    focus_entity_id: str | None = None
    observation_id: str | None = None
    fallback_reason: str | None = None
    fallback_message: str | None = None


class MapSceneSummaryItem(BaseModel):
    """Scene 摘要里的地点/人物/事件/势力项。"""

    entity_id: str
    name: str
    map_id: str
    hex_q: int | None = None
    hex_r: int | None = None
    depends_on_candidate: bool = False
    candidate_review_state: str | None = None
    evidence_excerpt: str | None = None
    open_target: dict | None = None


class MapSceneSummaryWarning(BaseModel):
    """保守的一致性提示。"""

    level: Literal["info", "warning"] = "info"
    code: str
    message: str
    depends_on_candidate: bool = False
    candidate_review_state: str | None = None
    evidence_excerpt: str | None = None
    open_target: dict | None = None


class MapSceneSummaryResponse(BaseModel):
    """写作页 Scene 面板消费的轻量地图摘要。"""

    scene_id: str
    primary_location: MapSceneSummaryItem | None = None
    characters: list[MapSceneSummaryItem] = Field(default_factory=list)
    events: list[MapSceneSummaryItem] = Field(default_factory=list)
    factions: list[MapSceneSummaryItem] = Field(default_factory=list)
    crises: list[MapSceneSummaryItem] = Field(default_factory=list)
    risks: list[MapSceneSummaryWarning] = Field(default_factory=list)
    warnings: list[MapSceneSummaryWarning] = Field(default_factory=list)
    open_target: MapOpenTarget
    candidate_support: Literal["supported", "unsupported"] = "supported"
```

- [ ] **Step 4: Make `include_candidates` reach the service**

In `backend/modules/world/services/map_scene_summary.py`, change `summarize` signature:

```python
    async def summarize(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
        *,
        include_candidates: bool = False,
    ) -> MapSceneSummaryResponse:
```

Change the dynamic call:

```python
        crises, risks = await self._dynamic_scene_items(
            db,
            nid,
            selected_map_id,
            sid,
            include_candidates=include_candidates,
        )
```

Change `_dynamic_scene_items` signature and filtering:

```python
    async def _dynamic_scene_items(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        scene_id: uuid.UUID,
        *,
        include_candidates: bool,
    ) -> tuple[list[MapSceneSummaryItem], list[MapSceneSummaryWarning]]:
        observations = await self._observation_repo.list_for_dashboard(
            db,
            novel_id,
            map_id=map_id,
            limit=80,
        )
        crises: list[MapSceneSummaryItem] = []
        risks: list[MapSceneSummaryWarning] = []
        for observation in observations:
            if observation.scene_id != scene_id:
                continue
            if observation.dynamic_type not in {
                "crisis",
                "crisis_spread",
                "risk",
                "conflict",
            }:
                continue
            if observation.review_state in {"candidate", "conflicted"} and not include_candidates:
                continue
            anchor = observation.spatial_anchor or {}
            title = (
                observation.target_name
                or observation.target_entity_type
                or "地图风险"
            )
            depends_on_candidate = observation.review_state in {"candidate", "conflicted"}
            open_target = {
                "kind": "map_object",
                "map_id": str(observation.map_id or map_id),
                "scene_id": str(scene_id),
                "observation_id": str(observation.id),
                "focus_entity_id": (
                    str(observation.target_entity_id)
                    if observation.target_entity_id
                    else None
                ),
            }
            crises.append(
                MapSceneSummaryItem(
                    entity_id=str(observation.target_entity_id or observation.id),
                    name=title,
                    map_id=str(observation.map_id or map_id),
                    hex_q=anchor.get("hex_q"),
                    hex_r=anchor.get("hex_r"),
                    depends_on_candidate=depends_on_candidate,
                    candidate_review_state=observation.review_state,
                    evidence_excerpt=observation.evidence_text,
                    open_target=open_target,
                )
            )
            risks.append(
                MapSceneSummaryWarning(
                    level="warning",
                    code="map_dynamic_risk",
                    message=f"{title}：{self._status_label(observation.review_state)}",
                    depends_on_candidate=depends_on_candidate,
                    candidate_review_state=observation.review_state,
                    evidence_excerpt=observation.evidence_text,
                    open_target=open_target,
                )
            )
        return crises, risks
```

In `backend/modules/world/map_facade.py`, change:

```python
    summary = await MapSceneSummaryService().summarize(
        db,
        novel_id,
        scene_id,
        include_candidates=include_candidates,
    )
```

- [ ] **Step 5: Run map summary tests**

Run:

```bash
cd backend
pytest modules/world/tests/test_map_scene_summary.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add backend/modules/world/map_schemas.py backend/modules/world/services/map_scene_summary.py backend/modules/world/map_facade.py backend/modules/world/tests/test_map_scene_summary.py
git commit -m "feat(map): support candidate-aware writing summaries"
```

---

### Task 4: Memory Continuity Evidence Facade

**Files:**
- Modify: `backend/modules/memory/contracts.py`
- Modify: `backend/modules/memory/facade.py`
- Modify: `backend/modules/memory/tests/test_services.py`

- [ ] **Step 1: Add failing memory facade tests**

In `backend/modules/memory/tests/test_services.py`, add:

```python
@pytest.mark.asyncio
async def test_continuity_evidence_for_writing_returns_memory_chapter_target(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    from modules.memory.facade import get_continuity_evidence_for_writing
    from modules.memory.models import MemoryEvent

    db_session.add(
        MemoryEvent(
            novel_id=sample_novel_id,
            chapter_index=2,
            sequence=1,
            event_type="entity_moved",
            entity_id="char-1",
            entity_type="character",
            snapshot_before={},
            snapshot_after={
                "character_locations": {
                    "char-1": {
                        "location_id": "loc-old",
                        "text_state": "上一章在旧城门",
                        "chapter_index": 2,
                    }
                }
            },
            source="manual_edit",
        )
    )
    await db_session.flush()

    evidence = await get_continuity_evidence_for_writing(
        db_session,
        novel_id=sample_novel_id,
        chapter_index=3,
        pov_character_id="char-1",
        current_location_id="loc-new",
        current_location_name="王城内门",
    )

    assert evidence is not None
    assert evidence.source_module == "memory"
    assert evidence.source_type == "memory.character_location"
    assert evidence.source_id == "char-1"
    assert evidence.source_label == "章节记忆：第 2 章"
    assert evidence.source_field == "角色位置"
    assert "上一章在旧城门" in evidence.source_excerpt
    assert evidence.open_target == {
        "kind": "memory_chapter",
        "chapter_index": 2,
        "character_id": "char-1",
    }
```

- [ ] **Step 2: Run the test to verify failure**

Run:

```bash
cd backend
pytest modules/memory/tests/test_services.py::test_continuity_evidence_for_writing_returns_memory_chapter_target -q
```

Expected: FAIL because `get_continuity_evidence_for_writing` is missing.

- [ ] **Step 3: Add the memory contract**

In `backend/modules/memory/contracts.py`, add:

```python
@dataclass(frozen=True)
class MemoryContinuityEvidenceContract:
    """Stable memory continuity evidence for writing conflict checks."""

    source_module: str
    source_type: str
    source_id: str
    source_label: str
    source_field: str
    source_excerpt: str
    open_target: dict[str, Any]
```

- [ ] **Step 4: Add the memory facade function**

In `backend/modules/memory/facade.py`, import the contract:

```python
from modules.memory.contracts import MemoryContinuityEvidenceContract
```

Add:

```python
async def get_continuity_evidence_for_writing(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
    *,
    pov_character_id: str | None,
    current_location_id: str | None,
    current_location_name: str | None = None,
) -> MemoryContinuityEvidenceContract | None:
    """Return previous-location evidence for writing continuity checks."""
    if not pov_character_id or not current_location_id or chapter_index <= 1:
        return None
    previous_chapter = chapter_index - 1
    panorama = await get_memory_panorama(db, novel_id, previous_chapter)
    character_locations = getattr(panorama, "character_locations", None) or {}
    if not isinstance(character_locations, dict):
        return None
    previous_location = character_locations.get(pov_character_id)
    if previous_location is None:
        return None
    previous_location_id = getattr(previous_location, "location_id", None)
    if previous_location_id is None and isinstance(previous_location, dict):
        previous_location_id = previous_location.get("location_id")
    if not previous_location_id or previous_location_id == current_location_id:
        return None
    previous_text = getattr(previous_location, "text_state", None)
    if previous_text is None and isinstance(previous_location, dict):
        previous_text = previous_location.get("text_state")
    previous_text = previous_text or str(previous_location_id)
    current_text = current_location_name or current_location_id
    return MemoryContinuityEvidenceContract(
        source_module="memory",
        source_type="memory.character_location",
        source_id=pov_character_id,
        source_label=f"章节记忆：第 {previous_chapter} 章",
        source_field="角色位置",
        source_excerpt=f"上一章 {previous_text}，当前 {current_text}",
        open_target={
            "kind": "memory_chapter",
            "chapter_index": previous_chapter,
            "character_id": pov_character_id,
        },
    )
```

- [ ] **Step 5: Run memory tests**

Run:

```bash
cd backend
pytest modules/memory/tests/test_services.py::test_continuity_evidence_for_writing_returns_memory_chapter_target -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add backend/modules/memory/contracts.py backend/modules/memory/facade.py backend/modules/memory/tests/test_services.py
git commit -m "feat(memory): expose writing continuity evidence"
```

---

### Task 5: Writing Orchestration Uses Map and Memory Evidence

**Files:**
- Modify: `backend/modules/writing/services.py`
- Modify: `backend/modules/writing/repositories.py`
- Modify: `backend/modules/writing/tests/test_conflict_checks.py`

- [ ] **Step 1: Add failing writing integration tests**

In `backend/modules/writing/tests/test_conflict_checks.py`, add:

```python
@pytest.mark.asyncio
async def test_conflict_check_marks_candidate_map_evidence_for_review(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)

    async def fake_map_summary(_db, _novel_id, _scene_id, *, include_candidates=False):
        assert include_candidates is True
        return {
            "primary_location": {"entity_id": "loc-1", "name": "东门"},
            "risks": [
                {
                    "level": "warning",
                    "code": "map_dynamic_risk",
                    "message": "粮仓起火：待确认",
                    "depends_on_candidate": True,
                    "candidate_review_state": "candidate",
                    "evidence_excerpt": "粮仓火势正在扩大",
                    "open_target": {
                        "kind": "map_object",
                        "map_id": "map-1",
                        "scene_id": scene["id"],
                        "observation_id": "obs-1",
                    },
                }
            ],
            "warnings": [],
            "candidate_support": "supported",
        }

    monkeypatch.setattr(
        "modules.world.map_facade.summarize_scene_map_for_writing",
        fake_map_summary,
    )

    resp = await async_client.post(
        "/api/writing/conflict-checks",
        json={
            "novel_id": novel_id,
            "chapter_index": 1,
            "scene_id": scene["id"],
            "content": "正文",
            "include_candidates": True,
        },
    )

    assert resp.status_code == 201, resp.text
    map_item = next(item for item in resp.json()["items"] if item["kind"] == "map_risk")
    assert map_item["needs_review"] is True
    assert map_item["location_json"]["needs_review_reason"] == "依赖待确认地图观察"
    assert map_item["location_json"]["source"]["field"] == "地图风险"
    assert map_item["location_json"]["source"]["excerpt"] == "粮仓火势正在扩大"
    assert map_item["location_json"]["open_target"]["observation_id"] == "obs-1"


@pytest.mark.asyncio
async def test_publish_snapshot_keeps_lightweight_evidence(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])

    published = await async_client.post(
        "/api/writing/drafts",
        json={
            "novel_id": novel_id,
            "chapter_index": 1,
            "scene_id": scene["id"],
            "title": "第一章",
            "content": "发布正文",
        },
    )

    assert published.status_code == 201, published.text
    snapshot = published.json()["draft"]["conflict_check_snapshot_json"]
    first_item = snapshot["items"][0]
    assert "location_json" in first_item
    assert "source" in first_item["location_json"]
    assert "open_target" in first_item["location_json"]
    assert "text_range" not in first_item["location_json"]
    assert snapshot["check_id"] == check["id"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend
pytest modules/writing/tests/test_conflict_checks.py::test_conflict_check_marks_candidate_map_evidence_for_review modules/writing/tests/test_conflict_checks.py::test_publish_snapshot_keeps_lightweight_evidence -q
```

Expected: FAIL because map evidence and snapshot evidence trimming are missing.

- [ ] **Step 3: Update writing map risk conversion**

In `backend/modules/writing/services.py`, update `_map_rule_items` loop:

```python
        for warning in [*risks, *warnings]:
            message = (
                _read_field(warning, "message")
                or _read_field(warning, "code")
                or "地图状态需复核"
            )
            depends_on_candidate = bool(_read_field(warning, "depends_on_candidate"))
            evidence_excerpt = _read_field(warning, "evidence_excerpt") or message
            open_target = _read_field(warning, "open_target") or {
                "kind": "map_scene",
                "scene_id": scene_id,
            }
            needs_review_reason = (
                "依赖待确认地图观察" if depends_on_candidate else None
            )
            severity = "medium" if _read_field(warning, "level") == "warning" else "low"
            items.append(
                {
                    "kind": "map_risk",
                    "severity": severity,
                    "source_module": "world",
                    "source_type": "map.scene_summary",
                    "source_id": scene_id,
                    "evidence_summary": message,
                    "location_json": evidence_location(
                        source_module="world",
                        source_type="map.scene_summary",
                        source_id=scene_id,
                        source_label="地图摘要",
                        source_field="地图风险",
                        source_excerpt=evidence_excerpt,
                        open_target=open_target,
                        needs_review_reason=needs_review_reason,
                    ),
                    "needs_review": include_candidates or depends_on_candidate,
                }
            )
```

Also after loading summary, add candidate support degradation:

```python
        candidate_support = _read_field(summary, "candidate_support")
        degraded = []
        if include_candidates and candidate_support == "unsupported":
            degraded.append("world.map.candidates")
        return items, degraded, summary
```

- [ ] **Step 4: Update writing memory conversion**

Replace `_memory_rule_items` internals after map/scene checks with:

```python
        try:
            from modules.memory.facade import get_continuity_evidence_for_writing

            primary_location = _read_field(map_summary, "primary_location")
            current_location_id = _read_field(primary_location, "entity_id")
            current_label = _read_field(primary_location, "name") or current_location_id
            evidence = await get_continuity_evidence_for_writing(
                db,
                novel_id,
                chapter_index,
                pov_character_id=getattr(scene, "pov_character_id", None),
                current_location_id=current_location_id,
                current_location_name=current_label,
            )
        except Exception:
            logger.exception("Failed to load memory continuity evidence")
            return [], ["memory"]
        if evidence is None:
            return [], []
        return [
            {
                "kind": "continuity_location_mismatch",
                "severity": "medium",
                "source_module": evidence.source_module,
                "source_type": evidence.source_type,
                "source_id": evidence.source_id,
                "evidence_summary": evidence.source_excerpt,
                "location_json": evidence_location(
                    source_module=evidence.source_module,
                    source_type=evidence.source_type,
                    source_id=evidence.source_id,
                    source_label=evidence.source_label,
                    source_field=evidence.source_field,
                    source_excerpt=evidence.source_excerpt,
                    open_target=evidence.open_target,
                ),
            }
        ], []
```

- [ ] **Step 5: Trim snapshot evidence**

In `backend/modules/writing/repositories.py`, import:

```python
from modules.writing.conflict_evidence import snapshot_location
```

In `build_latest_snapshot`, add `location_json` to each item:

```python
                    "location_json": snapshot_location(item.location_json),
```

- [ ] **Step 6: Run writing conflict tests**

Run:

```bash
cd backend
pytest modules/writing/tests/test_conflict_evidence.py modules/writing/tests/test_conflict_checks.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add backend/modules/writing/services.py backend/modules/writing/repositories.py backend/modules/writing/tests/test_conflict_checks.py
git commit -m "feat(writing): aggregate cross-module conflict evidence"
```

---

### Task 6: Frontend Check Options and Evidence Drawer

**Files:**
- Modify: `frontend-console/views/writingView.js`
- Modify: `frontend-console/views/writingConflictModal.js`
- Modify: `frontend-console/tests/writingView.test.js`
- Modify: `frontend-console/tests/writingConflictModal.test.js`

- [ ] **Step 1: Add failing writing view tests for check options**

In `frontend-console/tests/writingView.test.js`, add:

```javascript
it("opens conflict check options and passes include_candidates", async () => {
  api.writing.autosave.mockResolvedValue({
    id: "d1",
    version_number: 2,
    updated_at: "2026-06-29T00:00:01Z",
  })
  api.writing.createConflictCheck.mockResolvedValue({
    id: "c1",
    items: [],
    summary_json: { total: 0 },
  })
  api.writing.listConflictChecks.mockResolvedValue({ items: [], total: 0 })
  document.body.innerHTML = `
    <div id="modal-overlay" class="hidden">
      <div id="modal-title"></div>
      <div id="modal-body"></div>
      <div id="modal-footer"></div>
    </div>
    <input id="writing-title-input" value="第一章" />
    <textarea id="writing-editor">新正文</textarea>
  `

  const promise = writingView._runConflictCheck()
  document.querySelector("#writing-conflict-include-candidates").checked = true
  document.querySelector("#modal-footer .btn-primary").click()
  await promise

  expect(api.writing.createConflictCheck).toHaveBeenCalledWith(
    expect.objectContaining({ include_candidates: true }),
  )
})
```

- [ ] **Step 2: Add failing modal tests for evidence drawer**

In `frontend-console/tests/writingConflictModal.test.js`, add:

```javascript
it("renders escaped evidence drawer and open target action", () => {
  showWritingConflictModal({
    novelId: "p1",
    check: {
      id: "c1",
      chapter_index: 1,
      items: [{
        id: "i1",
        kind: "map_risk",
        severity: "medium",
        source_module: "world",
        evidence_summary: "<script>alert(1)</script>",
        status: "open",
        location_json: {
          source: {
            module: "world",
            type: "map.scene_summary",
            id: "s1",
            label: "地图<script>",
            field: "地图风险",
            excerpt: "粮仓<script>",
          },
          open_target: { kind: "map_object", map_id: "m1", observation_id: "obs1" },
          needs_review_reason: "依赖待确认地图观察",
        },
      }],
    },
  })

  const html = showModal.mock.calls[0][1]
  expect(html).toContain("证据")
  expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;")
  expect(html).toContain("依赖待确认地图观察")
  expect(html).toContain('data-conflict-open-source="i1"')
  expect(html).not.toContain("<script>alert(1)</script>")
})
```

- [ ] **Step 3: Run frontend tests to verify failure**

Run:

```bash
cd frontend-console
npx vitest run tests/writingView.test.js tests/writingConflictModal.test.js
```

Expected: FAIL because options modal and evidence drawer are missing.

- [ ] **Step 4: Add check options modal**

In `frontend-console/views/writingView.js`, add helper:

```javascript
  _confirmConflictCheckOptions() {
    return new Promise((resolve) => {
      const body = `
        <div class="writing-conflict-options">
          <label class="checkbox-row">
            <input id="writing-conflict-include-candidates" type="checkbox" />
            <span>包含待确认对象</span>
          </label>
          <p class="muted" style="font-size:12px;margin-top:8px;">
            包含待确认对象后，相关结果会标记为需复核，不会自动修改正文、Scene、地图或正史。
          </p>
        </div>
      `
      showModal("剧情设定冲突检查", body, [
        { text: "取消", class: "btn-ghost", handler: () => { closeModal(); resolve(null) } },
        {
          text: "开始检查",
          class: "btn-primary",
          handler: () => {
            const includeCandidates = Boolean(
              document.getElementById("writing-conflict-include-candidates")?.checked,
            )
            closeModal()
            resolve({ includeCandidates })
          },
        },
      ])
    })
  },
```

Update `_runConflictCheck` before autosave:

```javascript
      const options = await this._confirmConflictCheckOptions()
      if (!options) return
      await this._saveDraftForConflictCheck()
```

Change request payload:

```javascript
        include_candidates: options.includeCandidates,
```

- [ ] **Step 5: Render evidence drawer**

In `frontend-console/views/writingConflictModal.js`, inside `renderConflictItem`, after evidence paragraph and before actions, add:

```javascript
      ${renderEvidence(item)}
```

Add functions:

```javascript
function renderEvidence(item) {
  const location = item.location_json || {}
  const source = location.source || {}
  const openTarget = location.open_target || {}
  if (!source.module && !openTarget.kind && !location.needs_review_reason) return ""
  return `
    <details class="writing-conflict-evidence-drawer">
      <summary>证据</summary>
      <div class="writing-conflict-evidence-grid">
        <div><span>来源</span><strong>${esc(source.module || item.source_module || "-")}</strong></div>
        <div><span>对象</span><strong>${esc(source.label || "-")}</strong></div>
        <div><span>字段</span><strong>${esc(source.field || "-")}</strong></div>
        <div><span>类型</span><strong>${esc(source.type || item.source_type || "-")}</strong></div>
      </div>
      ${source.excerpt ? `<p>${esc(source.excerpt)}</p>` : ""}
      ${location.needs_review_reason ? `<p class="pill pill-warning">${esc(location.needs_review_reason)}</p>` : ""}
      ${openTarget.kind ? `<small>打开目标：${esc(openTarget.kind)}</small>` : ""}
    </details>
  `
}
```

In `bindConflictModalEvents`, the existing `data-conflict-open-source` handler stays unchanged because `writingView` owns source opening.

- [ ] **Step 6: Update source opening in writing view**

Replace `_openConflictSource` with:

```javascript
  _openConflictSource(check, itemId) {
    const item = (check.items || []).find((entry) => entry.id === itemId)
    const target = item?.location_json?.open_target || {}
    if (target.kind === "text_range") {
      this._locateConflictItem(check, itemId)
      return
    }
    if (target.kind === "map_scene" || target.kind === "map_object") {
      this._openMapForCurrentScene()
      return
    }
    if (target.kind === "outline_scene") {
      router.navigate("outline", null)
      toast("已打开大纲，请在 Scene 列表中定位该 Scene", "info")
      return
    }
    if (target.kind === "memory_chapter") {
      showModal(
        "章节记忆摘要",
        `<p>第 ${esc(target.chapter_index || "-")} 章记忆来源</p><p class="muted">角色：${esc(target.character_id || "-")}</p>`,
        [{ text: "关闭", class: "btn-ghost", handler: closeModal }],
      )
      return
    }
    toast("该来源暂无可打开视图", "info")
  },
```

- [ ] **Step 7: Run frontend unit tests**

Run:

```bash
cd frontend-console
npx vitest run tests/writingView.test.js tests/writingConflictModal.test.js
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add frontend-console/views/writingView.js frontend-console/views/writingConflictModal.js frontend-console/tests/writingView.test.js frontend-console/tests/writingConflictModal.test.js
git commit -m "feat(writing): add conflict evidence UI"
```

---

### Task 7: Realistic User Paths and Real LLM Acceptance

**Files:**
- Modify: `frontend-console/e2e/writing-conflict.spec.js`
- Modify: `frontend-console/e2e/writing-conflict-real-llm.spec.js`
- Modify: `backend/modules/writing/tests/test_conflict_checks_real_llm.py`

- [ ] **Step 1: Add realistic Playwright path coverage**

In `frontend-console/e2e/writing-conflict.spec.js`, add a test that mocks the API at the browser boundary:

```javascript
test("writing conflict check supports candidate evidence and source opening", async ({ page }) => {
  await page.route("**/api/writing/conflict-checks", async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON()
      expect(body.include_candidates).toBe(true)
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "check-1",
          novel_id: testProjectId,
          chapter_index: 1,
          scene_id: "scene-1",
          include_candidates: true,
          status: "completed",
          summary_json: { total: 1, open_high_count: 0 },
          items: [{
            id: "item-1",
            check_id: "check-1",
            novel_id: testProjectId,
            kind: "map_risk",
            severity: "medium",
            source_module: "world",
            evidence_summary: "粮仓起火：待确认",
            needs_review: true,
            status: "open",
            location_json: {
              source: {
                module: "world",
                type: "map.scene_summary",
                id: "scene-1",
                label: "地图摘要",
                field: "地图风险",
                excerpt: "粮仓火势正在扩大",
              },
              open_target: { kind: "map_object", map_id: "map-1", observation_id: "obs-1" },
              needs_review_reason: "依赖待确认地图观察",
            },
          }],
        }),
      })
      return
    }
    await route.continue()
  })

  await page.locator("#writing-editor").fill("粮仓起火的新正文")
  await page.getByRole("button", { name: "剧情设定冲突检查" }).click()
  await page.getByLabel("包含待确认对象").check()
  await page.getByRole("button", { name: "开始检查" }).click()
  await expect(page.getByText("粮仓起火：待确认")).toBeVisible()
  await page.getByText("证据").click()
  await expect(page.getByText("粮仓火势正在扩大")).toBeVisible()
  await expect(page.getByText("依赖待确认地图观察")).toBeVisible()
})
```

- [ ] **Step 2: Add real LLM evidence assertions**

In `backend/modules/writing/tests/test_conflict_checks_real_llm.py`, extend the real LLM test after AI review:

```python
    assert all("location_json" in item for item in reviewed["items"])
    assert all(
        item["location_json"] is None
        or "source" in item["location_json"]
        or item["is_ai_judgment"]
        for item in reviewed["items"]
    )
```

Extend snapshot assertions:

```python
    assert any(
        "location_json" in item and item["location_json"] is not None
        for item in snapshot["items"]
    )
```

- [ ] **Step 3: Run mock e2e and unit tests**

Run:

```bash
cd frontend-console
npx vitest run tests/writingView.test.js tests/writingConflictModal.test.js
npx playwright test e2e/writing-conflict.spec.js --reporter=list
```

Expected: PASS.

- [ ] **Step 4: Run real LLM acceptance when credentials are available**

Run:

```bash
cd backend
RUN_REAL_LLM_TESTS=1 pytest modules/writing/tests/test_conflict_checks_real_llm.py -q -s
```

Expected with configured LLM: PASS. Without configured LLM: tests are skipped by existing guard.

Run frontend real LLM smoke when backend and credentials are available:

```bash
cd frontend-console
ENABLE_REAL_LLM=1 npx playwright test e2e/writing-conflict-real-llm.spec.js --reporter=list --timeout=300000
```

Expected with configured LLM and backend: PASS. Without configured LLM: skip or report the missing configuration.

- [ ] **Step 5: Commit**

Run:

```bash
git add frontend-console/e2e/writing-conflict.spec.js frontend-console/e2e/writing-conflict-real-llm.spec.js backend/modules/writing/tests/test_conflict_checks_real_llm.py
git commit -m "test(writing): cover realistic conflict evidence paths"
```

---

### Task 8: Documentation and Final Verification

**Files:**
- Modify: `backend/modules/writing/README.md`
- Modify: `backend/modules/world/README.md`
- Modify: `backend/modules/memory/README.md`
- Modify: `docs/modules/11_writing.md`

- [ ] **Step 1: Update writing module docs**

In `backend/modules/writing/README.md`, replace the conflict-check section with:

```markdown
`POST /api/writing/conflict-checks` runs a rule-layer check and stores lightweight cross-module evidence in each item:

- `location_json.source` identifies the source module, object, field, and excerpt.
- `location_json.open_target` tells the frontend where the author can inspect the source.
- `needs_review=true` means the item depends on candidate/conflicted data or AI judgment.
- `include_candidates=false` is the default; `true` asks supporting modules to include candidate/conflicted evidence and mark dependent results.

`writing` owns check history, item status, and publish snapshots. It does not own or interpret `outline`, `world.map`, or `memory` internals; it consumes stable facades/contracts only.
```

- [ ] **Step 2: Update world module docs**

In `backend/modules/world/README.md`, update the map facade entry:

```markdown
`summarize_scene_map_for_writing(db, novel_id, scene_id, include_candidates=False)` returns confirmed map context by default. When `include_candidates=True`, candidate/conflicted map observations may be included, and each dependent risk carries `depends_on_candidate`, `candidate_review_state`, `evidence_excerpt`, and `open_target`.
```

- [ ] **Step 3: Update memory module docs**

In `backend/modules/memory/README.md`, add:

```markdown
`get_continuity_evidence_for_writing(...)` returns lightweight previous-location evidence for writing conflict checks. The output is a stable contract with source label, field, excerpt, and `memory_chapter` open target. The writing module uses it for continuity checks without importing memory internals.
```

- [ ] **Step 4: Update authoritative writing docs**

In `docs/modules/11_writing.md`, add a subsection:

```markdown
### 跨模块冲突证据

写作冲突检查使用 `location_json` 保存轻量证据：

- `source`：来源模块、类型、对象、字段和证据片段。
- `open_target`：前端打开来源的稳定目标。
- `needs_review_reason`：依赖待确认对象或 AI 判断时的复核原因。

发布快照归档轻量证据摘要，不归档完整上下文或 prompt。
```

- [ ] **Step 5: Run backend verification**

Run:

```bash
cd backend
pytest modules/writing/tests/test_conflict_evidence.py modules/writing/tests/test_conflict_checks.py modules/world/tests/test_map_scene_summary.py modules/memory/tests/test_services.py -q
ruff check .
```

Expected: PASS.

- [ ] **Step 6: Run frontend verification**

Run:

```bash
cd frontend-console
npx vitest run tests/writingView.test.js tests/writingConflictModal.test.js
npx playwright test e2e/writing-conflict.spec.js --reporter=list
```

Expected: PASS.

- [ ] **Step 7: Run diff check**

Run:

```bash
git diff --check HEAD
```

Expected: no output.

- [ ] **Step 8: Commit docs and verification updates**

Run:

```bash
git add backend/modules/writing/README.md backend/modules/world/README.md backend/modules/memory/README.md docs/modules/11_writing.md
git commit -m "docs(writing): document cross-module conflict evidence"
```

---

## Self-Review Notes

Spec coverage:

- Cross-module evidence shape: Task 1 and Task 5.
- Outline evidence: Task 2.
- Candidate-aware world map support: Task 3.
- Memory continuity open target: Task 4.
- Writing orchestration and publish snapshot: Task 5.
- Check options modal and evidence drawer: Task 6.
- Realistic user paths and real LLM participation: Task 7.
- Docs and verification: Task 8.

Scope check:

- This plan does not build a trace graph, independent Scene整理工作台, or AI writing capsule.
- It keeps persistence in `location_json`, matching the accepted design.

Type consistency:

- `open_target.kind` values used here are `outline_scene`, `map_scene`, `map_object`, `memory_chapter`, and `text_range`.
- `needs_review_reason` lives inside `location_json`.
- `include_candidates` remains the API field; `include_pending_objects` remains the context confirmation field.
