# Scenario Gap Closure Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining code/document gaps after the post-acceptance-fixes round so the implementation matches the documented scenario paths.

**Architecture:** Keep each fix as a vertical slice through the existing modules. `writing` owns chapter text and version records; `outline` owns Scene and `scene_chunks`; `world` owns entities, merge, rollback, and CharacterKnowledge; `rag` and `context` keep their existing backend services and gain scenario-level regression coverage. Cross-module calls must go through `facade.py`, not internal repositories/services.

**Tech Stack:** FastAPI, async SQLAlchemy, pytest, vanilla JS, Vitest, Playwright.

---

## Verified Baseline

Fresh commands run on 2026-06-12:

```bash
cd backend && pytest modules/project/tests/test_project.py modules/imports/tests/test_imports.py modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py modules/world/tests/test_world.py -q --tb=short
# 159 passed

cd backend && pytest tests/unit/test_world_services_revision_event_helpers.py -q --tb=short
# 43 passed

cd frontend-console && npm test -- --run projectView.test.js writingView.test.js worldView.test.js xss-rendering.test.js
# 4 files, 55 tests passed

node --check frontend-console/api.js
# exit 0
```

Do not reimplement the already-verified items from the previous plan unless a regression test in this plan proves they are still incomplete.

## File Structure

Modify these files:

- `backend/modules/writing/schemas.py` — request/response schemas for splitting a chapter at an editor offset.
- `backend/modules/writing/repositories.py` — helpers to shift chapter indices and update latest draft content without creating a publish task.
- `backend/modules/writing/services.py` — orchestrate draft split and call outline facade for Scene chunk remapping.
- `backend/modules/writing/api.py` — expose `POST /api/writing/chapters/{chapter_index}/split`.
- `backend/modules/writing/tests/test_writing.py` — backend split tests.
- `backend/modules/outline/facade.py` — public split helper used by writing.
- `backend/modules/outline/services.py` — support splitting a chunk into a newly inserted chapter.
- `backend/modules/outline/tests/test_scene.py` — mapping tests for new-chapter split.
- `frontend-console/api.js` — add writing split and world operation clients.
- `frontend-console/views/writingView.js` — call writing split, refresh chapter tree, and resolve current Scene by cursor offset.
- `frontend-console/tests/writingView.test.js` — split and cursor-panel unit tests.
- `frontend-console/e2e/writing.spec.js` — scenario 4 E2E for true chapter split and cursor panel switching.
- `backend/modules/world/api.py` — add active merge route.
- `backend/modules/world/tests/test_world.py` — API/service tests for merge, rollback, and CharacterKnowledge validation.
- `frontend-console/views/worldView.js` — entity merge, rollback, and CharacterKnowledge user paths.
- `frontend-console/tests/worldView.test.js` — frontend unit tests for those paths.
- `frontend-console/e2e/world.spec.js` and `frontend-console/e2e/world-relations-aliases.spec.js` — scenario 5 E2E gaps.
- `frontend-console/views/outlineView.js` — drag reorder, AI generation, foreshadow/reveal user paths.
- `frontend-console/tests/outlineView.test.js` — unit tests for outline paths.
- `frontend-console/e2e/outline-scenes.spec.js` and `frontend-console/e2e/outline-threads-arcs.spec.js` — scenario 6 E2E gaps.
- `frontend-console/e2e/rag.spec.js` and `frontend-console/e2e/context.spec.js` — scenario-level RAG/Context regressions.
- `docs/modules/02_world.md`, `backend/modules/world/README.md`, `docs/modules/11_writing.md`, `frontend-console/e2e/scenario-coverage.md` — sync docs after code changes.

## Task 1: Implement True Chapter Split From Writing View

**Files:**
- Modify: `backend/modules/writing/schemas.py`
- Modify: `backend/modules/writing/repositories.py`
- Modify: `backend/modules/writing/services.py`
- Modify: `backend/modules/writing/api.py`
- Modify: `backend/modules/writing/tests/test_writing.py`
- Modify: `backend/modules/outline/facade.py`
- Modify: `backend/modules/outline/services.py`
- Modify: `backend/modules/outline/tests/test_scene.py`
- Modify: `frontend-console/api.js`
- Modify: `frontend-console/views/writingView.js`
- Modify: `frontend-console/tests/writingView.test.js`
- Modify: `frontend-console/e2e/writing.spec.js`

- [ ] **Step 1: Add backend failing test for draft split**

Append to `backend/modules/writing/tests/test_writing.py`:

```python
@pytest.mark.asyncio
async def test_split_chapter_at_offset_creates_new_chapter_without_publish_task(
    service: WritingDraftService,
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    original = await service.create_draft(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=5,
            title="第五章",
            content="前半段内容。后半段内容。",
        ),
    )

    result = await service.split_chapter_at_offset(
        db_session,
        novel_id=novel_id,
        chapter_index=5,
        split_pos=6,
        source_scene_id=None,
    )

    assert result.source_chapter_index == 5
    assert result.new_chapter_index == 6
    assert result.source_draft.content == "前半段内容"
    assert result.new_draft.content == "。后半段内容。"
    assert result.source_draft.version_number == original.version_number
    assert result.new_draft.version_number == 1
```

- [ ] **Step 2: Add backend failing test for shifting later chapters**

Append:

```python
@pytest.mark.asyncio
async def test_split_chapter_shifts_later_chapters(
    service: WritingDraftService,
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    await service.create_draft(
        db_session,
        WritingDraftCreate(novel_id=novel_id, chapter_index=5, title="第五章", content="甲乙丙丁"),
    )
    await service.create_draft(
        db_session,
        WritingDraftCreate(novel_id=novel_id, chapter_index=6, title="第六章", content="原第六章"),
    )

    result = await service.split_chapter_at_offset(
        db_session,
        novel_id=novel_id,
        chapter_index=5,
        split_pos=2,
        source_scene_id=None,
    )

    assert result.new_chapter_index == 6
    indices = await service.list_chapter_indices(db_session, novel_id)
    assert indices == [5, 6, 7]
    shifted = await service.get_latest_draft(db_session, novel_id, 7)
    assert shifted.content == "原第六章"
```

- [ ] **Step 3: Run writing tests and confirm failure**

Run:

```bash
cd backend && pytest modules/writing/tests/test_writing.py::test_split_chapter_at_offset_creates_new_chapter_without_publish_task modules/writing/tests/test_writing.py::test_split_chapter_shifts_later_chapters -q --tb=short
```

Expected: fail because `split_chapter_at_offset` and response schema do not exist.

- [ ] **Step 4: Add split schemas**

In `backend/modules/writing/schemas.py`, add:

```python
class ChapterSplitRequest(BaseModel):
    split_pos: int = Field(..., ge=1, description="编辑器 offset，必须位于正文中间")
    source_scene_id: str | None = Field(None, description="当前 Scene ID，用于同步 scene_chunks")


class ChapterSplitResponse(BaseModel):
    source_chapter_index: int
    new_chapter_index: int
    source_draft: WritingDraftResponse
    new_draft: WritingDraftResponse
    scenes: list[dict] = Field(default_factory=list)
```

- [ ] **Step 5: Add repository helpers**

In `WritingDraftRepository`, add:

```python
async def update_latest_content(
    self,
    db: AsyncSession,
    novel_id: uuid.UUID,
    chapter_index: int,
    *,
    title: str | None,
    content: str,
) -> WritingDraft:
    draft = await self.get_latest_by_chapter(db, novel_id, chapter_index)
    if draft is None:
        raise ValueError(f"No draft found for chapter {chapter_index}")
    draft.title = title
    draft.content = content
    db.add(draft)
    await db.flush()
    return draft

async def shift_chapter_indices_from(
    self,
    db: AsyncSession,
    novel_id: uuid.UUID,
    start_index: int,
) -> None:
    stmt = (
        select(WritingDraft.chapter_index)
        .where(
            WritingDraft.novel_id == novel_id,
            WritingDraft.chapter_index >= start_index,
        )
        .distinct()
        .order_by(WritingDraft.chapter_index.desc())
    )
    result = await db.execute(stmt)
    indices = [row[0] for row in result.all()]
    for idx in indices:
        await db.execute(
            update(WritingDraft)
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.chapter_index == idx,
            )
            .values(chapter_index=idx + 1)
        )
    await db.flush()
```

- [ ] **Step 6: Add outline facade helper**

In `backend/modules/outline/facade.py`, add:

```python
async def split_scene_chunk_to_new_chapter(
    db: AsyncSession,
    novel_id: str,
    *,
    source_scene_id: str,
    source_chapter_id: str,
    source_chapter_index: int,
    new_chapter_id: str,
    new_chapter_index: int,
    split_pos: int,
    new_chapter_length: int,
) -> list[dict[str, Any]]:
    from modules.outline.services import SceneService

    scenes = await SceneService().split_scene_chunk_to_new_chapter(
        db,
        novel_id=novel_id,
        source_scene_id=source_scene_id,
        source_chapter_id=source_chapter_id,
        source_chapter_index=source_chapter_index,
        new_chapter_id=new_chapter_id,
        new_chapter_index=new_chapter_index,
        split_pos=split_pos,
        new_chapter_length=new_chapter_length,
    )
    return [scene.__dict__ for scene in scenes]
```

- [ ] **Step 7: Implement outline chunk remap**

In `SceneService`, add `split_scene_chunk_to_new_chapter(...)`. It must:

1. Load `source_scene_id` and verify same `novel_id`.
2. Find the chunk matching `source_chapter_id` or `source_chapter_index`.
3. Validate `start_pos < split_pos < end_pos`.
4. Set source chunk `end_pos = split_pos`.
5. Create a new Scene at `source.scene_index + 1` with:

```python
chapter_ids=[new_chapter_id]
scene_chunks=[
    {
        "chapter_id": new_chapter_id,
        "chapter_index": new_chapter_index,
        "start_pos": 0,
        "end_pos": new_chapter_length,
    }
],
source="manual",
narrative_tag="draft",
```

6. Shift later `scene_index` values exactly as `split_scene_chunk()` does.
7. Return ordered scenes.

- [ ] **Step 8: Implement writing service orchestration**

In `WritingDraftService`, add:

```python
async def split_chapter_at_offset(
    self,
    db: AsyncSession,
    *,
    novel_id: str,
    chapter_index: int,
    split_pos: int,
    source_scene_id: str | None,
) -> ChapterSplitResponse:
    nid = parse_uuid(novel_id, "novel")
    latest = await self._repo.get_latest_by_chapter(db, nid, chapter_index)
    if latest is None:
        raise HTTPException(status_code=404, detail=f"No draft found for chapter {chapter_index}")
    content = latest.content or ""
    if not (0 < split_pos < len(content)):
        raise HTTPException(status_code=422, detail="split_pos must be inside the chapter content")

    head = content[:split_pos]
    tail = content[split_pos:]
    new_chapter_index = chapter_index + 1

    await self._repo.shift_chapter_indices_from(db, nid, new_chapter_index)
    source = await self._repo.update_latest_content(
        db,
        nid,
        chapter_index,
        title=latest.title,
        content=head,
    )
    new_draft = await self._repo.create(
        db,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=new_chapter_index,
            title=f"第{new_chapter_index}章",
            content=tail,
        ),
    )

    scenes: list[dict] = []
    if source_scene_id:
        from modules.outline.facade import split_scene_chunk_to_new_chapter

        scenes = await split_scene_chunk_to_new_chapter(
            db,
            novel_id,
            source_scene_id=source_scene_id,
            source_chapter_id=str(chapter_index),
            source_chapter_index=chapter_index,
            new_chapter_id=str(new_chapter_index),
            new_chapter_index=new_chapter_index,
            split_pos=split_pos,
            new_chapter_length=len(tail),
        )

    return ChapterSplitResponse(
        source_chapter_index=chapter_index,
        new_chapter_index=new_chapter_index,
        source_draft=WritingDraftResponse.model_validate(source),
        new_draft=WritingDraftResponse.model_validate(new_draft),
        scenes=scenes,
    )
```

- [ ] **Step 9: Add API route**

In `backend/modules/writing/api.py`, import `ChapterSplitRequest` and `ChapterSplitResponse`, then add:

```python
@router.post(
    "/chapters/{chapter_index}/split",
    response_model=ChapterSplitResponse,
)
async def split_chapter(
    db: DbSession,
    data: ChapterSplitRequest,
    chapter_index: int = Path(..., ge=1, description="章节索引"),
    novel_id: str = Query(..., description="小说项目 ID"),
) -> ChapterSplitResponse:
    return await _service.split_chapter_at_offset(
        db,
        novel_id=novel_id,
        chapter_index=chapter_index,
        split_pos=data.split_pos,
        source_scene_id=data.source_scene_id,
    )
```

- [ ] **Step 10: Add frontend API client**

In `frontend-console/api.js`, add under `writing`:

```javascript
async splitChapter(chapterIndex, payload, novelId) {
  return request(`/writing/chapters/${chapterIndex}/split${buildQueryString({ novel_id: novelId })}`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
},
```

- [ ] **Step 11: Update writing view split behavior**

In `writingView._showSplitSceneForm()`, replace the direct `api.outline.splitSceneChunk(...)` call with:

```javascript
const result = await api.writing.splitChapter(
  this._currentChapter,
  { split_pos: splitPos, source_scene_id: currentScene.id },
  state.currentProjectId,
)
this._scenes = result.scenes || this._scenes
this._chapters[result.new_chapter_index] = { draftCount: 1 }
this._chapterList = [...new Set([...this._chapterList, result.new_chapter_index])].sort((a, b) => a - b)
this._currentChapter = result.new_chapter_index
this._currentDraftId = result.new_draft.id
this._currentContent = result.new_draft.content || ""
this._currentTitle = result.new_draft.title || ""
this._currentVersionNumber = result.new_draft.version_number
toast("断章完成", "success")
await this._rerender()
```

- [ ] **Step 12: Verify Task 1**

Run:

```bash
cd backend && pytest modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py -q --tb=short
cd frontend-console && npm test -- --run writingView.test.js
```

Expected: all selected tests pass.

## Task 2: Make Writing Scene Panel Cursor-Position Aware

**Files:**
- Modify: `frontend-console/views/writingView.js`
- Modify: `frontend-console/tests/writingView.test.js`
- Modify: `frontend-console/e2e/writing.spec.js`

- [ ] **Step 1: Add failing unit test**

In `frontend-console/tests/writingView.test.js`, add:

```javascript
it("selects the scene matching the editor cursor offset", () => {
  writingView._currentChapter = 5
  writingView._cursorOffset = 1700
  writingView._scenes = [
    { id: "s1", title: "前段", scene_chunks: [{ chapter_index: 5, start_pos: 0, end_pos: 1500 }] },
    { id: "s2", title: "后段", scene_chunks: [{ chapter_index: 5, start_pos: 1500, end_pos: 3000 }] },
  ]

  expect(writingView._findCurrentScene()?.id).toBe("s2")
})
```

- [ ] **Step 2: Track cursor offset**

In `writingView`, add `_cursorOffset: 0` to the state object. In `_bindEvents()`, attach these listeners to `#writing-editor`:

```javascript
const editor = document.getElementById("writing-editor")
if (editor) {
  const updateCursorScene = () => {
    this._cursorOffset = editor.selectionStart || 0
    const panelEl = document.getElementById("writing-panel-container")
    if (panelEl) panelEl.innerHTML = this._renderScenePanel()
  }
  editor.addEventListener("click", updateCursorScene)
  editor.addEventListener("keyup", updateCursorScene)
  editor.addEventListener("select", updateCursorScene)
}
```

- [ ] **Step 3: Resolve scene by chunk offset**

Update `_findCurrentScene()` so chunk lookup runs before broad `chapter_ids` matching:

```javascript
const offset = this._cursorOffset || 0
const byOffset = this._scenes.find((s) =>
  (s.scene_chunks || []).some((c) =>
    String(c.chapter_index) === chStr &&
    Number(c.start_pos || 0) <= offset &&
    offset < Number(c.end_pos || 0)
  )
)
if (byOffset) return byOffset
```

Only fall back to `chapter_ids` if no offset chunk matches.

- [ ] **Step 4: Verify Task 2**

Run:

```bash
cd frontend-console && npm test -- --run writingView.test.js
```

Expected: all writing view tests pass.

## Task 3: Complete World Merge, Rollback, and CharacterKnowledge User Paths

**Files:**
- Modify: `backend/modules/world/api.py`
- Modify: `backend/modules/world/schemas.py`
- Modify: `backend/modules/world/tests/test_world.py`
- Modify: `frontend-console/api.js`
- Modify: `frontend-console/views/worldView.js`
- Modify: `frontend-console/tests/worldView.test.js`
- Modify: `frontend-console/e2e/world.spec.js`
- Modify: `frontend-console/e2e/world-relations-aliases.spec.js`

- [ ] **Step 1: Add backend merge API test**

Add to `backend/modules/world/tests/test_world.py`:

```python
@pytest.mark.asyncio
async def test_merge_entity_api_service_marks_candidate_merged(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    entity_service = WorldEntityService()
    target = await entity_service.create(
        db_session,
        sample_novel_id,
        WorldEntityCreate(entity_type="character", name="张三", status="canonical"),
    )
    candidate = await entity_service.create(
        db_session,
        sample_novel_id,
        WorldEntityCreate(entity_type="character", name="张老三", status="draft", force_create=True),
    )

    from modules.world.services.dedup_service import EntityDedupService

    result = await EntityDedupService().merge_candidate_into_entity(
        db_session,
        sample_novel_id,
        candidate.id,
        target.id,
    )

    assert result.target_entity_id == target.id
    merged = await entity_service.get(db_session, candidate.id, novel_id=sample_novel_id)
    assert merged.status == "merged"
```

- [ ] **Step 2: Add public merge route**

In `backend/modules/world/schemas.py`, add:

```python
class EntityMergeRequest(BaseModel):
    target_entity_id: str = Field(..., description="合并目标实体 ID")
```

In `backend/modules/world/api.py`, import `EntityDedupService` and `EntityMergeRequest`, instantiate `_dedup_service = EntityDedupService()`, then add:

```python
@router.post("/entities/{candidate_id}/merge")
async def merge_entity(
    db: DbSession,
    candidate_id: str,
    data: EntityMergeRequest,
    novel_id: str = Query(..., description="项目 ID"),
):
    return await _dedup_service.merge_candidate_into_entity(
        db,
        novel_id,
        candidate_id,
        data.target_entity_id,
    )
```

- [ ] **Step 3: Add frontend API methods**

In `frontend-console/api.js` under `world`, add:

```javascript
async mergeEntity(candidateId, targetEntityId, novelId) {
  return request(`/world/entities/${candidateId}/merge${buildQueryString({ novel_id: novelId })}`, {
    method: "POST",
    body: JSON.stringify({ target_entity_id: targetEntityId }),
  })
},
async rollbackEntity(entityId, targetSceneIndex, novelId) {
  return request(`/world/entities/${entityId}/rollback${buildQueryString({ novel_id: novelId })}`, {
    method: "POST",
    body: JSON.stringify({ target_scene_index: targetSceneIndex }),
  })
},
async listKnowledge(characterId, novelId) {
  return request(`/world/characters/${characterId}/knowledge${buildQueryString({ novel_id: novelId })}`)
},
async createKnowledge(characterId, payload, novelId) {
  return request(`/world/characters/${characterId}/knowledge${buildQueryString({ novel_id: novelId })}`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
},
```

- [ ] **Step 4: Add frontend unit tests**

Add tests in `frontend-console/tests/worldView.test.js` that assert:

```javascript
await worldView._mergeEntity("candidate-1", "target-1")
expect(api.world.mergeEntity).toHaveBeenCalledWith("candidate-1", "target-1", "p1")

await worldView._rollbackEntity("entity-1", 12)
expect(api.world.rollbackEntity).toHaveBeenCalledWith("entity-1", 12, "p1")

await worldView._createKnowledge("char-1", {
  target_entity_id: "entity-1",
  knowledge_level: "false_belief",
  known_content: "他以为真相如此",
  misconception: "错误认知",
})
expect(api.world.createKnowledge).toHaveBeenCalled()
```

- [ ] **Step 5: Implement worldView helpers**

Add helpers that the tests call:

```javascript
async _mergeEntity(candidateId, targetId) {
  await api.world.mergeEntity(candidateId, targetId, state.currentProjectId)
  toast("实体已合并", "success")
  router.refresh()
},

async _rollbackEntity(entityId, targetSceneIndex) {
  const result = await api.world.rollbackEntity(entityId, targetSceneIndex, state.currentProjectId)
  toast((result.warnings || []).length ? "回滚完成，存在警告" : "回滚完成", (result.warnings || []).length ? "warning" : "success")
  router.refresh()
},

async _createKnowledge(characterId, payload) {
  if (payload.knowledge_level === "false_belief" && !payload.misconception) {
    toast("错误认知必须填写误解内容", "warning")
    return
  }
  await api.world.createKnowledge(characterId, payload, state.currentProjectId)
  toast("知识边界已添加", "success")
}
```

Wire these helpers from visible buttons/modals in `worldView`.

- [ ] **Step 6: Verify Task 3**

Run:

```bash
cd backend && pytest modules/world/tests/test_world.py -q --tb=short
cd frontend-console && npm test -- --run worldView.test.js
```

Expected: all selected tests pass.

## Task 4: Complete Outline Scenario 6 User Paths

**Files:**
- Modify: `frontend-console/views/outlineView.js`
- Modify: `frontend-console/api.js`
- Modify: `frontend-console/tests/outlineView.test.js`
- Modify: `frontend-console/e2e/outline-scenes.spec.js`
- Modify: `frontend-console/e2e/outline-threads-arcs.spec.js`
- Modify: `backend/modules/outline/api.py`
- Modify: `backend/modules/outline/schemas.py`

- [ ] **Step 1: Add outline unit tests**

Create or extend `frontend-console/tests/outlineView.test.js` with:

```javascript
it("reorders scenes through the API", async () => {
  state.currentProjectId = "p1"
  outlineView._scenes = [{ id: "s1" }, { id: "s2" }]
  api.outline.reorderScenes.mockResolvedValue({ updated: 2, total: 2 })

  await outlineView._reorderScenes(["s2", "s1"])

  expect(api.outline.reorderScenes).toHaveBeenCalledWith("p1", ["s2", "s1"])
})

it("generates structure from outline view", async () => {
  state.currentProjectId = "p1"
  api.outline.generate.mockResolvedValue({ plot_threads: [], outline_arcs: [] })

  await outlineView._generateStructure(1, 5)

  expect(api.outline.generate).toHaveBeenCalledWith("p1", 1, 5)
})
```

- [ ] **Step 2: Implement outline helpers**

In `outlineView.js`, add:

```javascript
async _reorderScenes(sceneIds) {
  await api.outline.reorderScenes(state.currentProjectId, sceneIds)
  toast("Scene 顺序已更新", "success")
  await this.onEnter?.()
  router.refresh()
},

async _generateStructure(startChapter, endChapter) {
  const result = await api.outline.generate(state.currentProjectId, startChapter, endChapter)
  toast("结构生成完成", "success")
  await this.onEnter?.()
  router.refresh()
  return result
},
```

Add visible controls for moving a Scene up/down and for AI structure generation. Drag-and-drop can call the same `_reorderScenes()` helper after the final order is computed.

- [ ] **Step 3: Add foreshadow/reveal paths**

Add explicit list/update routes for `foreshadowing_plans` and `reveal_plans` in `backend/modules/outline/api.py`; use existing models/repositories and validate `novel_id`.

Add these frontend API methods:

```javascript
async listForeshadowing(novelId) {
  return request("/outline/foreshadowing" + buildQueryString({ novel_id: novelId }))
},
async updateForeshadowing(id, novelId, payload) {
  return request(`/outline/foreshadowing/${id}${buildQueryString({ novel_id: novelId })}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  })
},
```

Also add:

```javascript
async listReveals(novelId) {
  return request("/outline/reveals" + buildQueryString({ novel_id: novelId }))
},
async updateReveal(id, novelId, payload) {
  return request(`/outline/reveals/${id}${buildQueryString({ novel_id: novelId })}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  })
},
```

- [ ] **Step 4: Verify Task 4**

Run:

```bash
cd frontend-console && npm test -- --run outlineView.test.js
cd backend && pytest modules/outline/tests -q --tb=short
```

Expected: all selected tests pass.

## Task 5: Add Scenario-Level RAG and Context Regressions

**Files:**
- Modify: `backend/modules/rag/tests/`
- Modify: `backend/modules/context/tests/` or `backend/tests/unit/test_context.py`
- Modify: `frontend-console/e2e/rag.spec.js`
- Modify: `frontend-console/e2e/context.spec.js`

- [ ] **Step 1: Add RAG stale chunk regression**

Add a backend test that creates a chapter, runs `rag_index_chapter`, updates the same chapter, runs `rag_index_chapter` again, and asserts no old chunk text remains.

Expected assertion:

```python
assert all("旧正文片段" not in c.text for c in chunks)
assert any("新正文片段" in c.text for c in chunks)
```

- [ ] **Step 2: Add RAG degraded warning regression**

Mock embedding failure in a backend test and assert:

```python
assert any(c.embedding_status == "failed" for c in chunks)
assert result.warnings
```

- [ ] **Step 3: Add context knowledge-boundary regression**

Add a context test with a POV character and a target entity with `hidden_truth`. For `knowledge_level="false_belief"`, assert the compiled context contains the misconception and does not expose raw hidden truth.

Expected assertion:

```python
assert "错误认知" in rendered
assert "真实隐藏真相" not in rendered
```

- [ ] **Step 4: Verify Task 5**

Run:

```bash
cd backend && pytest modules/rag/tests modules/context/tests tests/unit/test_context.py -q --tb=short
```

Expected: selected backend tests pass.

## Task 6: Sync Docs and Scenario Coverage

**Files:**
- Modify: `docs/modules/02_world.md`
- Modify: `backend/modules/world/README.md`
- Modify: `docs/modules/11_writing.md`
- Modify: `frontend-console/e2e/scenario-coverage.md`
- Modify: `docs/核心业务场景与预期行为.md`

- [ ] **Step 1: Fix world rollback docs**

Update both world docs so they say:

```markdown
- `POST /api/world/entities/{entity_id}/rollback` is the active Delta Log + Text Archive rollback route. Request body: `{ "target_scene_index": 12 }`.
- `POST /api/world/entities/{entity_id}/rollback-by-revision` is legacy compatibility for `entity_revisions`.
- `EntityRevisionService` is read/compat only and must not be used for new rollback UI.
```

- [ ] **Step 2: Fix writing split docs**

Update `docs/modules/11_writing.md` to record:

```markdown
`POST /api/writing/chapters/{chapter_index}/split?novel_id=...` splits the latest draft at `split_pos`, creates the next chapter draft, shifts later chapter indices, and delegates Scene chunk remapping to outline facade. It does not enqueue `publish_chapter`; RAG indexing waits for an explicit save/publish.
```

- [ ] **Step 3: Update scenario coverage only for verified paths**

In `frontend-console/e2e/scenario-coverage.md`:

- Move writing split from partial to covered only after the Playwright test verifies draft split and cursor Scene panel switching.
- Move world merge/rollback/knowledge paths from uncovered to covered only after E2E tests exist.
- Keep real deep import workflow, RAG degraded warning, and context knowledge-boundary items marked partial until their E2E or backend scenario tests pass.

- [ ] **Step 4: Verify docs do not contradict code**

Run:

```bash
rg -n "rollback.*legacy|后续替换为 Delta Replay|EntityRevisionService.*版本管理|scene_chunks.*未覆盖|T[O]DO|延后" docs/modules backend/modules/world/README.md frontend-console/e2e/scenario-coverage.md
```

Expected: no stale rollback wording; any remaining `延后` has a reason in the owning spec.

## Final Verification

Run these commands before claiming completion:

```bash
cd backend && pytest modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py modules/world/tests/test_world.py modules/rag/tests modules/context/tests tests/unit/test_context.py -q --tb=short
cd frontend-console && npm test
node --check frontend-console/api.js
cd frontend-console && npx playwright test writing.spec.js world.spec.js world-relations-aliases.spec.js outline-scenes.spec.js outline-threads-arcs.spec.js rag.spec.js context.spec.js --reporter=list
```

Expected:

- Backend selected tests pass.
- Frontend Vitest suite passes.
- `api.js` syntax check exits 0.
- Selected Playwright E2E specs pass or any environment-dependent failures are documented with exact error output.
