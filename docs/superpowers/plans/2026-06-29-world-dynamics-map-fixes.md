# World Dynamics Map Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the world dynamics map from a partial scaffold to the P0/P1 user paths: default dashboard entry, contextual map opening, object info, inspector editing, candidate review, batch actions, and risk handling.

**Architecture:** Extend the existing `world/map` subsystem instead of creating a new module. Keep `MapObservation -> MapFact` as the trusted candidate-to-fact path, and add focused dashboard/open-target/batch behavior around it. Frontend changes stay in the vanilla JS console views and reuse existing API clients, toast, modal, and route helpers.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic, SQLite-backed pytest, vanilla JS, Vitest, Playwright for E2E when PostgreSQL is healthy.

---

## Task 1: Backend P0/P1 Contract Repairs

**Files:**
- Modify: `backend/modules/world/map_schemas.py`
- Modify: `backend/modules/world/map_api.py`
- Modify: `backend/modules/world/services/map_service.py`
- Modify: `backend/modules/world/services/map_scene_summary.py`
- Test: `backend/modules/world/tests/test_map_dynamic_facts.py`
- Test: `backend/modules/world/tests/test_map_scene_summary.py`

- [x] Add failing tests for `GET /api/world/maps/open-target`, scene summary `crises/risks`, dashboard `scene_id` filtering, enriched queue labels, focused inspector, batch actions, and cross-novel rejection.
- [x] Implement schema extensions without breaking existing response fields.
- [x] Implement `MapDynamicFactService.get_open_target` and route it before `/{map_id}` routes.
- [x] Extend dashboard queue and inspector object info fields.
- [x] Add `batch-actions` facade in the map API for candidate review, fact status, and layer visibility metadata.
- [x] Re-run focused backend tests.

## Task 2: Frontend P0/P1 User Paths

**Files:**
- Modify: `frontend-console/api.js`
- Modify: `frontend-console/views/mapWorkspaceView.js`
- Modify: `frontend-console/views/worldView.js`
- Modify: `frontend-console/views/writingView.js`
- Test: `frontend-console/tests/mapWorkspaceView.test.js`
- Test: `frontend-console/tests/worldView.test.js`
- Test: `frontend-console/tests/writingView.test.js`

- [x] Add failing tests for default dashboard opening from recent map, world object “打开地图”, scene risks/crises rendering, object info “修改/打开检查器”, batch group hierarchy, and no default technical IDs.
- [x] Add API client methods for open target, batch actions, and map fact patching.
- [x] Make `#workbench/:projectId/map` open the recent valid map into dashboard when available; keep empty overview if no map exists.
- [x] Add “打开地图” to character/location/organization/event rows and visible fallback text when no target map exists.
- [x] Render crises/risks in the writing page map summary.
- [x] Add object info fields and a minimal edit modal for fact/observation status plus visible spatial/source context. Full value/spatial patching remains follow-up.
- [x] Re-run focused frontend tests.

## Task 3: Layout and Dynamic Playback Completion

Status: not implemented in this pass. P3 `MapDelta` / `WorldDynamic` remains a follow-up; current playback is still derived from observations/facts.

**Files:**
- Modify: `frontend-console/views/mapLayoutEngine.js`
- Modify: `frontend-console/views/mapWorkspaceView.js`
- Modify: `backend/modules/world/map_schemas.py`
- Modify: `backend/modules/world/services/map_service.py`
- Test: `frontend-console/tests/mapLayoutEngine.test.js`
- Test: `frontend-console/tests/mapWorkspaceView.test.js`
- Test: `backend/modules/world/tests/test_map_dynamic_facts.py`

- [ ] Add failing tests for full/short/icon/cluster/hidden degradation order, semantic anchor coordinates, deterministic layout, and playback delta events.
- [ ] Extend layout input/output so dashboard/living-atlas/narrative-lens share the same data but differ by weight and density.
- [ ] Add derived `MapDelta` / `WorldDynamic` response types and playback computation from confirmed facts, without adding a new runtime dependency.
- [ ] Mark playback as derived from facts/candidates and exclude rolled-back facts.
- [ ] Re-run focused backend and frontend tests.

## Task 4: Verification and Documentation

**Files:**
- Modify: `docs/modules/15_map.md`
- Modify: `docs/modules/14_frontend.md`

- [x] Update docs to reflect the repaired P0/P1 paths and any P2/P3 behavior that remains derived rather than fully persisted.
- [x] Run the final focused gate:

```bash
cd backend && pytest -q modules/world/tests/test_map_dynamic_facts.py modules/world/tests/test_map_scene_summary.py modules/world/tests/test_map_api.py
cd frontend-console && npm test -- mapWorkspaceView.test.js mapView.test.js mapLayoutEngine.test.js mapRouteContext.test.js writingView.test.js worldView.test.js xss-rendering.test.js
git diff --check
```

- [ ] Run Playwright only after `/api/health` is healthy with PostgreSQL available.
