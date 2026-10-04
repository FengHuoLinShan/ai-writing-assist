# 深度导入流水线（三遍 Workflow）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐现有深度导入三阶段流水线，使其满足 Pydantic 校验、关系持久化、自动元数据、章节范围覆盖检测、降级容错、真实 LLM 验收等全部要求。

**Architecture:** 保留 `DeepImportWorkflow` + 异步 worker + 前端轮询的现有骨架；在 `backend/modules/imports/` 内新增 `llm_schemas.py` 做 LLM 输出校验；精确修改 `scene_segmentation.py`、`scene_entity_extraction.py`、`facade.py`、`api.py`；通过 facade 扩展实现章节范围检测与旧数据 deprecation；最后补充单元/集成/E2E/真实 LLM 验收脚本。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Pydantic v2, pytest, Playwright, vanilla JS.

---

## 前置检查

- [ ] **Step 0.1:** 确认当前分支干净，且不在 `main` 上直接开发。
  - Run: `git status --short`
  - Expected: empty or only expected untracked files.
- [ ] **Step 0.2:** 运行一次现有相关测试，确保基线通过。
  - Run: `cd backend && python -m pytest modules/imports/tests/test_workflow.py modules/imports/tests/test_imports_integration.py -xvs`
  - Expected: all pass.

---

## Task 1: 新增 Phase 1/2 LLM 输出 Pydantic schema

**Files:**
- Create: `backend/modules/imports/llm_schemas.py`

**上下文:** 当前 Phase 1 与 Phase 2 直接 `parse_llm_json` 后按 key 取值，没有 schema 校验。验收要求“真实 LLM 输出必须使用 Pydantic schema 校验后入库”。

- [ ] **Step 1.1: 编写 schema 文件**

Create `backend/modules/imports/llm_schemas.py`:

```python
"""深度导入流水线 LLM 结构化输出 Schema"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SceneChunk(BaseModel):
    chapter_index: int = Field(..., ge=1)
    start_paragraph: int = Field(default=0, ge=0)
    end_paragraph: int | None = Field(default=None, ge=0)


class SceneItem(BaseModel):
    title: str = Field(default="")
    goal: str = Field(default="")
    core_conflict: str = Field(default="")
    emotional_beat: str = Field(default="")
    narrative_tag: str = Field(default="draft")
    scene_chunks: list[SceneChunk] = Field(default_factory=list)

    @field_validator("scene_chunks")
    @classmethod
    def _ensure_at_least_one_chunk(cls, v: list[SceneChunk]) -> list[SceneChunk]:
        if not v:
            return [SceneChunk(chapter_index=1)]
        return v


class SceneSegmentationOutput(BaseModel):
    scenes: list[SceneItem] = Field(default_factory=list)


class ExtractedEntity(BaseModel):
    name: str = Field(..., min_length=1)
    entity_type: str = Field(default="character")
    summary: str = Field(default="")
    public_info: str = Field(default="")
    hidden_truth: str = Field(default="")
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    suggested_action: str = Field(default="create_new")
    suggested_existing_entity_name: str | None = Field(default=None)
    candidate_reason: str = Field(default="")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    aliases: list[dict] | None = Field(default=None)


class ExtractedRelation(BaseModel):
    source_name: str = Field(..., min_length=1)
    target_name: str = Field(..., min_length=1)
    relation_type: str = Field(..., min_length=1)
    description: str | None = Field(default=None)
    quote: str | None = Field(default=None)
    strength: float = Field(default=0.5, ge=0.0, le=1.0)


class DeltaEvent(BaseModel):
    category: str = Field(default="ENTITY_UPDATED")
    field: str | None = Field(default=None)
    old: Any | None = Field(default=None)
    new: Any | None = Field(default=None)
    meta: dict = Field(default_factory=dict)


class SceneEntityExtractionOutput(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    delta_events: list[DeltaEvent] = Field(default_factory=list)
```

Note: `DeltaEvent.old`/`new` use `Any`; add `from typing import Any` at top.

- [ ] **Step 1.2: 运行 schema 自测试**

Create a temporary sanity test or run in a Python shell:

```python
from modules.imports.llm_schemas import SceneSegmentationOutput, SceneEntityExtractionOutput

sample = {"scenes": [{"title": "x", "scene_chunks": [{"chapter_index": 1}]}]}
assert len(SceneSegmentationOutput.model_validate(sample).scenes) == 1

sample2 = {
    "entities": [{"name": "Klein", "entity_type": "character"}],
    "relations": [{"source_name": "Klein", "target_name": "Melissa", "relation_type": "sibling"}],
    "delta_events": [{"category": "ENTITY_CREATED", "field": "summary"}],
}
assert SceneEntityExtractionOutput.model_validate(sample2)
```

Run: `cd backend && python -c "..."`
Expected: no exception.

- [ ] **Step 1.3: Commit**

```bash
git add backend/modules/imports/llm_schemas.py
git commit -m "feat(imports): add Pydantic schemas for deep-import LLM outputs"
```

---

## Task 2: Phase 1 使用 schema 校验并补齐 mechanical fallback

**Files:**
- Modify: `backend/modules/imports/scene_segmentation.py`

- [ ] **Step 2.1: 修改 `_process_batch` 以使用 schema**

Replace the section after `parsed = parse_llm_json(...)` with:

```python
from modules.imports.llm_schemas import SceneSegmentationOutput

output = SceneSegmentationOutput.model_validate(parsed)
scenes_data = [s.model_dump() for s in output.scenes]
if not scenes_data:
    raise ValueError("LLM returned empty scenes list")
return scenes_data
```

- [ ] **Step 2.2: 修改 `_process_batch_single_chapter` 以使用 schema**

Same pattern:

```python
output = SceneSegmentationOutput.model_validate(parsed)
scenes = [s.model_dump() for s in output.scenes]
if scenes:
    all_scenes.extend(scenes)
    break
```

- [ ] **Step 2.3: 补齐 mechanical fallback 的默认字段**

In the `mech_data` dict inside the mechanical fallback block, ensure it has all fields required by `SceneCreate`:

```python
mech_data = {
    "scene_index": next_scene_index,
    "title": ch.get("title") or f"第{ch['chapter_index']}章",
    "goal": "",
    "core_conflict": "",
    "emotional_beat": "",
    "must_happen": "",
    "must_not_happen": "",
    "narrative_tag": "draft",
    "source": "deep_import",
    "scene_chunks": [{"chapter_index": ch["chapter_index"], "start_paragraph": 0}],
    "chapter_ids": [str(ch["chapter_index"])],
    "status": "draft",
}
```

- [ ] **Step 2.4: 运行 Phase 1 测试**

Run: `cd backend && python -m pytest modules/imports/tests/test_workflow.py::TestSceneSegmentationProgress modules/imports/tests/test_imports_integration.py::TestSceneSegmentationIntegration -xvs`
Expected: pass.

- [ ] **Step 2.5: Commit**

```bash
git add backend/modules/imports/scene_segmentation.py
git commit -m "feat(imports): validate scene segmentation LLM output with Pydantic schema"
```

---

## Task 3: Phase 2 校验 LLM 输出、持久化关系、写 auto_ingested 元数据、每 Scene 快照

**Files:**
- Create: `backend/prompts/scene_entity_extraction.md`
- Modify: `backend/modules/imports/scene_entity_extraction.py`
- Modify: `backend/modules/imports/workflow.py`
- Modify: `backend/modules/imports/tasks.py`
- Modify: `backend/infrastructure/tasks/worker.py` (if needed for container signature)
- Modify: `backend/app/main.py` (if needed for container signature)

- [ ] **Step 3.1: 创建 Scene 级实体提取 Prompt**

Create `backend/prompts/scene_entity_extraction.md`:

```markdown
# 任务
你是网络小说世界观编辑。请从以下 Scene 正文中提取长期创作资产：人物、地点、势力、物品、事件、规则/力量体系、秘密/传说等。

# 输出格式
返回 JSON 对象，顶层字段：
- `entities`: 对象数组
- `relations`: 关系数组（可选）
- `delta_events`: 变化事件数组（可选）

## entities 元素
- `name`: 对象名称（必填）
- `entity_type`: 类型，可选 character/location/faction/item/event/rule/power_system/secret/legend/resource/concept
- `summary`: 一句话概要
- `public_info`: 公开信息
- `hidden_truth`: 仅作者知道的隐藏信息
- `importance`: 0.0~1.0
- `suggested_action`: create_new / link_to_existing / ignore / temporary_only
- `suggested_existing_entity_name`: link_to_existing 时填写
- `candidate_reason`: 抽取理由
- `confidence`: 置信度
- `aliases`: 别名数组 `[{"alias": "...", "type": "..."}]`

## relations 元素
- `source_name`: 源对象名（必填）
- `target_name`: 目标对象名（必填）
- `relation_type`: 关系类型（必填）
- `description`: 描述
- `quote`: 原文引用
- `strength`: 0.0~1.0

## delta_events 元素
- `category`: ENTITY_CREATED / ENTITY_UPDATED / RELATION_CREATED 等
- `field`: 变化字段路径
- `old`: 旧值
- `new`: 新值
- `meta`: 附加元数据

# 规则
- 只抽取会在后续章节反复出现、影响剧情的长期资产。
- 不抽取路人、一次性道具、代词、一次性场景元素。
- 别名不创建新对象；放入 aliases。
- 如果对象已存在（名称或别名相同），使用 suggested_action=link_to_existing。
```

- [ ] **Step 3.2: 修改 `SceneEntityExtractionService.extract_by_scenes` 接受 workflow_id**

Signature:

```python
async def extract_by_scenes(
    self,
    db: AsyncSession,
    novel_id: str,
    *,
    workflow_id: str | None = None,
    on_scene_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> dict[str, Any]:
```

Pass `workflow_id` into `_process_scene`.

- [ ] **Step 3.3: 修改 `_process_scene` 以使用 schema 并传入 workflow_id**

```python
async def _process_scene(
    self,
    db: AsyncSession,
    nid,
    scene: dict[str, Any],
    scene_idx: int,
    existing_context: str,
    accumulated_memory: list[dict],
    workflow_id: str | None = None,
) -> dict[str, Any]:
    ...
    extraction = await self._call_llm_extraction(
        chapters_text,
        existing_context,
        memory_context,
    )
    entities = extraction.entities
    relations = extraction.relations
    delta_events = extraction.delta_events

    created_count = await self._persist_entities(
        db, nid, entities, scene_index, workflow_id
    )
    relation_count = await self._persist_relations(
        db, nid, relations, scene_index, workflow_id
    )
    delta_count = await self._record_deltas(
        db, nid, delta_events, scene_index
    )
    ...
    # snapshot after every scene
    try:
        from modules.memory.services import MemoryService
        await MemoryService().capture_snapshot(db, str(nid), scene_index)
    except Exception as exc:
        logger.warning("Memory snapshot after scene %d failed: %s", scene_index, exc)
    ...
```

- [ ] **Step 3.4: 修改 `_call_llm_extraction` 使用 schema 和新 prompt**

```python
from modules.imports.llm_schemas import SceneEntityExtractionOutput

async def _call_llm_extraction(...):
    system_prompt = load_prompt("scene_entity_extraction")
    ...
    raw = await llm_client.generate(request)
    parsed = parse_llm_json(raw.content, "Entity extraction")
    output = SceneEntityExtractionOutput.model_validate(parsed)
    return output
```

- [ ] **Step 3.5: 修改 `_persist_entities` 写入 `_meta` 元数据**

```python
from datetime import datetime, timezone

async def _persist_entities(
    self,
    db: AsyncSession,
    nid,
    entities: list[ExtractedEntity],
    scene_index: int,
    workflow_id: str | None = None,
) -> int:
    from modules.world.facade import create_entity, find_similar_entities

    created = 0
    for ent in entities:
        action = ent.suggested_action
        if action in ("ignore", "temporary_only", "link_to_existing"):
            continue
        if not ent.name:
            continue

        similar = await find_similar_entities(db, str(nid), ent.name)
        if similar and similar.get("score", 0) >= 0.88:
            continue

        content_json = {
            "_meta": {
                "auto_ingested": True,
                "source_scene_index": scene_index,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
                "batch_id": workflow_id or "",
            },
            "aliases": ent.aliases or [],
        }
        try:
            await create_entity(
                db,
                str(nid),
                {
                    "name": ent.name,
                    "entity_type": ent.entity_type,
                    "summary": ent.summary or None,
                    "public_info": ent.public_info or None,
                    "hidden_truth": ent.hidden_truth or None,
                    "importance": ent.importance,
                    "content_json": content_json,
                    "status": "canonical",
                    "created_by": "ai_import",
                },
            )
            created += 1
        except Exception as exc:
            logger.warning("Failed to create entity '%s': %s", ent.name, exc)
    return created
```

- [ ] **Step 3.6: 新增 `_persist_relations` 方法**

```python
async def _persist_relations(
    self,
    db: AsyncSession,
    nid,
    relations: list[ExtractedRelation],
    scene_index: int,
    workflow_id: str | None = None,
) -> int:
    from modules.world.facade import create_relation, find_entity_id_by_name

    created = 0
    for rel in relations:
        source_id = await find_entity_id_by_name(db, str(nid), rel.source_name)
        target_id = await find_entity_id_by_name(db, str(nid), rel.target_name)
        if not source_id or not target_id:
            continue
        try:
            await create_relation(
                db,
                str(nid),
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "relation_type": rel.relation_type,
                    "description": rel.description,
                    "quote": rel.quote,
                    "strength": rel.strength,
                    "status": "canonical",
                },
            )
            created += 1
        except Exception as exc:
            logger.warning(
                "Failed to create relation %s -> %s: %s",
                rel.source_name,
                rel.target_name,
                exc,
            )
    return created
```

- [ ] **Step 3.7: 更新 workflow 以传递 workflow_id**

In `backend/modules/imports/workflow.py`, `_extract_entities_by_scene` should accept a `workflow_id` parameter and pass it:

```python
async def _extract_entities_by_scene(
    self,
    db: AsyncSession,
    novel_id: str,
    workflow_id: str | None = None,
    on_scene_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    try:
        handler = _container_get("world.run_scene_entity_extraction")
        result = await handler(
            db,
            novel_id=novel_id,
            workflow_id=workflow_id,
            on_scene_progress=on_scene_progress,
        )
        return result
    except Exception as exc:
        logger.warning("Phase 2 entity extraction failed: %s", exc)
        return {"total_created": 0, "total_relations": 0, "total_deltas": 0}
```

Also update `run_step` to pass `workflow_id` argument. The `workflow_id` can be passed into `run_step` as a new keyword argument and threaded through.

- [ ] **Step 3.8: 更新 task handler 传递 workflow_id**

In `backend/modules/imports/tasks.py`, `handle_deep_import`:

```python
workflow = DeepImportWorkflow()
progress = DeepImportProgress(workflow_id=str(task.id))
...
progress = await workflow.run_step(
    db,
    novel_id=novel_id,
    start_chapter=start_chapter,
    end_chapter=end_chapter,
    workflow_id=str(task.id),
    progress=progress,
    on_progress=_record_progress,
)
```

- [ ] **Step 3.9: 同步 DI 注册签名**

Ensure `backend/infrastructure/tasks/worker.py` and `backend/app/main.py` still register `world.run_scene_entity_extraction` to the updated `extract_by_scenes` method. No signature changes in registration needed because we added keyword-only args.

- [ ] **Step 3.10: 运行 Phase 2 相关测试**

Run: `cd backend && python -m pytest modules/imports/tests/test_workflow.py::TestSceneEntityExtractionProgress -xvs`
Expected: pass.

- [ ] **Step 3.11: Commit**

```bash
git add backend/modules/imports/scene_entity_extraction.py backend/modules/imports/workflow.py backend/modules/imports/tasks.py backend/prompts/scene_entity_extraction.md
git commit -m "feat(imports): validate phase-2 LLM output, persist relations, auto_ingested meta, per-scene snapshot"
```

---

## Task 4: 章节范围感知的重复导入检测与旧数据 deprecation

**Files:**
- Modify: `backend/modules/imports/facade.py`
- Modify: `backend/modules/outline/facade.py` (add `update_scene`)

- [ ] **Step 4.1: 在 outline facade 增加 `update_scene` 用于 deprecation**

Add to `backend/modules/outline/facade.py`:

```python
async def update_scene(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    """更新 Scene 字段（仅允许 status 等少量字段）。"""
    from modules.outline.repositories import SceneRepository
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    sid = parse_uuid(scene_id, "scene_id")
    repo = SceneRepository()
    scene = await repo.get(db, sid)
    if scene is None or scene.novel_id != nid:
        return None
    for key, value in data.items():
        if hasattr(scene, key):
            setattr(scene, key, value)
    await db.flush()
    return _scene_to_dict(scene)
```

- [ ] **Step 4.2: 修改 imports facade 的重复检测逻辑**

Replace `_check_duplicate_import` with range-aware detection:

```python
async def _check_duplicate_import(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
) -> str | None:
    """检查指定章节范围内是否已有派生数据。"""
    from modules.outline.facade import get_scenes_by_novel
    from modules.world.facade import list_entities

    scenes = await get_scenes_by_novel(
        db, novel_id, status_filter=["draft", "canonical"]
    )
    overlapping_scenes = [
        s for s in scenes
        if _scene_overlaps_range(s, start_chapter, end_chapter)
    ]

    entities = await list_entities(db, novel_id, limit=10000)
    overlapping_entities = [
        e for e in entities
        if _entity_in_range(e, start_chapter, end_chapter)
    ]

    if overlapping_scenes or overlapping_entities:
        return (
            f"第 {start_chapter}-{end_chapter} 章已有 "
            f"{len(overlapping_scenes)} 个 Scene、"
            f"{len(overlapping_entities)} 个实体。重新导入将覆盖/刷新该范围数据。是否继续？"
        )
    return None


def _scene_overlaps_range(scene: dict, start: int, end: int) -> bool:
    chapter_ids = scene.get("chapter_ids") or []
    try:
        indices = [int(x) for x in chapter_ids if x is not None]
    except (ValueError, TypeError):
        return False
    if not indices:
        return False
    return any(start <= idx <= end for idx in indices)


def _entity_in_range(entity: dict, start: int, end: int) -> bool:
    content_json = entity.get("content_json") or {}
    meta = content_json.get("_meta") or {}
    source = meta.get("source_scene_index")
    if source is not None and start <= int(source) <= end:
        return True
    return False
```

Note: `source_scene_index` is the scene index; range is chapter range. This is intentionally approximate: it flags entities auto-ingested from scenes within the chapter range because scene indices are monotonic and bounded by the range. If this proves too broad, we can instead store `source_chapter_index` in `_meta` during Phase 2 and use that. Prefer storing `source_chapter_index`:

Update `_persist_entities` in Task 3 to include `source_chapter_index` (max chapter id in the scene) and use that here.

- [ ] **Step 4.3: 新增 `_deprecate_derived_data`**

In `backend/modules/imports/facade.py`:

```python
async def _deprecate_derived_data(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
) -> None:
    """将指定章节范围内的旧派生 Scene 和自动实体标记为 deprecated。"""
    from modules.outline.facade import get_scenes_by_novel, update_scene
    from modules.world.facade import list_entities

    scenes = await get_scenes_by_novel(
        db, novel_id, status_filter=["draft", "canonical"]
    )
    for scene in scenes:
        if _scene_overlaps_range(scene, start_chapter, end_chapter):
            await update_scene(db, novel_id, scene["id"], {"status": "deprecated"})

    entities = await list_entities(db, novel_id, limit=10000)
    for entity in entities:
        if entity.get("status") not in ("canonical", "draft"):
            continue
        content_json = entity.get("content_json") or {}
        meta = content_json.get("_meta") or {}
        if meta.get("auto_ingested") and _entity_in_range(entity, start_chapter, end_chapter):
            # Use entity service update via facade; since facade lacks update_entity,
            # we can directly import service here (rare exception) or add update_entity to facade.
            from modules.world.services import WorldEntityService
            svc = WorldEntityService()
            await svc.update(db, novel_id, entity["id"], {"status": "deprecated"})
```

Because facade-only rule applies to other modules, but inside imports facade calling world service directly is still a cross-module service import. Better: add `update_entity` to world facade. Include that as a sub-step.

- [ ] **Step 4.4: 在 world facade 增加 `update_entity`**

Add to `backend/modules/world/entity_facade.py`:

```python
async def update_entity(
    db: AsyncSession,
    novel_id: str,
    entity_id: str,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    """更新实体（仅允许 status 等自由字段）。"""
    from shared.utils import parse_uuid

    eid = parse_uuid(entity_id, "entity_id")
    result = await _entity_service.update(db, novel_id, eid, data)
    return result.model_dump() if result else None
```

Then replace direct service import in `_deprecate_derived_data` with `update_entity`.

- [ ] **Step 4.5: 在 `start_deep_import` 中调用 deprecation**

```python
if warning and not force:
    return {...}

if force:
    await _deprecate_derived_data(db, novel_id, start_chapter, end_chapter)

task_id = enqueue_task(...)
```

- [ ] **Step 4.6: 运行 facade 相关测试**

Run: `cd backend && python -m pytest modules/imports/tests/test_imports_facade.py -xvs` (if exists) or `modules/imports/tests/ -k "duplicate"`.
Expected: pass.

- [ ] **Step 4.7: Commit**

```bash
git add backend/modules/imports/facade.py backend/modules/outline/facade.py backend/modules/world/entity_facade.py
git commit -m "feat(imports): range-aware duplicate detection and deprecation on force"
```

---

## Task 5: API 返回 workflow_id

**Files:**
- Modify: `backend/modules/imports/facade.py`
- Modify: `backend/modules/imports/api.py`
- Modify: `backend/modules/imports/workflow_schemas.py`

- [ ] **Step 5.1: 在 `DeepImportProgress` 增加 `workflow_id`**

```python
class DeepImportProgress(BaseModel):
    workflow_id: str | None = Field(default=None)
    ...
```

- [ ] **Step 5.2: 修改 `start_deep_import` 返回 `workflow_id`**

```python
result: dict[str, Any] = {
    "workflow_id": str(task_id),
    "task_id": str(task_id),
    "status": "pending",
    "requires_confirmation": False,
    "message": f"深度导入任务已提交（第{start_chapter}-{end_chapter}章）",
}
```

- [ ] **Step 5.3: 修改 `/deep/sync` 返回 `workflow_id`**

For sync path there is no task; generate a fresh uuid:

```python
from uuid import uuid4

workflow_id = str(uuid4())
progress = DeepImportProgress(workflow_id=workflow_id)
...
return {
    "workflow_id": workflow_id,
    "phase": progress.phase,
    ...
}
```

- [ ] **Step 5.4: 更新 task handler 把 workflow_id 写入 progress**

Already in Step 3.8.

- [ ] **Step 5.5: 运行 API 测试**

Run: `cd backend && python -m pytest modules/imports/tests/test_import_api.py -xvs`
Expected: pass.

- [ ] **Step 5.6: Commit**

```bash
git add backend/modules/imports/facade.py backend/modules/imports/api.py backend/modules/imports/workflow_schemas.py
git commit -m "feat(imports): return workflow_id alongside task_id from deep import endpoints"
```

---

## Task 6: 补齐后端测试

**Files:**
- Modify: `backend/modules/imports/tests/test_workflow.py`
- Modify: `backend/modules/imports/tests/test_imports_integration.py`
- Create: `backend/modules/imports/tests/test_scene_entity_extraction.py`

- [ ] **Step 6.1: 在 `test_workflow.py` 增加降级与状态机测试**

Add tests:

```python
async def test_phase1_batch_failure_degrades_to_mechanical(db, novel_id):
    """Mock LLM 全部失败，验证最终仍创建机械 Scene 且 degraded=True。"""
    from unittest.mock import patch
    from modules.imports.scene_segmentation import SceneSegmentationService

    svc = SceneSegmentationService()
    with patch.object(svc, "_process_batch", side_effect=RuntimeError("LLM fail")):
        with patch.object(svc, "_process_batch_single_chapter", side_effect=RuntimeError("single fail")):
            result = await svc.segment_chapters(db, novel_id, 1, 2)
    assert result["total_scenes"] == 2
    assert result["degraded"] is True
```

- [ ] **Step 6.2: 在 `test_imports_integration.py` 增加重复导入与 novel_id 隔离测试**

Add tests:

```python
async def test_duplicate_import_requires_confirmation(db, novel_id):
    from modules.imports.facade import start_deep_import
    from modules.outline.facade import create_scene

    await create_scene(db, novel_id, {
        "scene_index": 0, "title": "old", "narrative_tag": "draft",
        "source": "deep_import", "scene_chunks": [{"chapter_index": 1}],
        "chapter_ids": ["1"], "status": "draft",
    })
    result = await start_deep_import(db, novel_id, 1, 1)
    assert result["requires_confirmation"] is True

    result2 = await start_deep_import(db, novel_id, 1, 1, force=True)
    assert result2["requires_confirmation"] is False
    assert "task_id" in result2

async def test_novel_isolation_for_deep_import(db, novel_a, novel_b):
    from modules.imports.facade import start_deep_import
    # create scene in novel_a
    from modules.outline.facade import create_scene
    await create_scene(db, novel_a, {
        "scene_index": 0, "title": "a", "narrative_tag": "draft",
        "source": "deep_import", "scene_chunks": [{"chapter_index": 1}],
        "chapter_ids": ["1"], "status": "draft",
    })
    result = await start_deep_import(db, novel_b, 1, 1)
    assert result["requires_confirmation"] is False
```

- [ ] **Step 6.3: 创建 `test_scene_entity_extraction.py` 覆盖关系/元数据/快照**

```python
import pytest
from unittest.mock import AsyncMock, patch

from modules.imports.scene_entity_extraction import SceneEntityExtractionService

@pytest.mark.asyncio
async def test_persist_entities_writes_auto_ingested_meta(db, novel_id):
    svc = SceneEntityExtractionService()
    from modules.imports.llm_schemas import ExtractedEntity

    entity = ExtractedEntity(name="Klein", entity_type="character", suggested_action="create_new")
    created = await svc._persist_entities(db, novel_id, [entity], scene_index=1, workflow_id="wf-1")
    assert created == 1
    from modules.world.facade import list_entities
    entities = await list_entities(db, novel_id)
    assert any(
        e["name"] == "Klein"
        and (e.get("content_json") or {}).get("_meta", {}).get("auto_ingested") is True
        for e in entities
    )
```

Add similar tests for relations and snapshot.

- [ ] **Step 6.4: 运行新增测试**

Run: `cd backend && python -m pytest modules/imports/tests/ -xvs`
Expected: pass.

- [ ] **Step 6.5: Commit**

```bash
git add backend/modules/imports/tests/
git commit -m "test(imports): deep import degradation, confirmation, isolation, relations, snapshot"
```

---

## Task 7: 真实 LLM 验收脚本

**Files:**
- Create: `backend/scripts/acceptance_deep_import.py`

- [ ] **Step 7.1: 编写脚本**

Script flow:
1. Connect to DB using `core.database.DatabaseManager`.
2. Find project named `《诡秘之主 第一部》` or create it.
3. Ensure writing_drafts for chapters 1-3 exist (import from file if not).
4. Clear prior auto-ingested data for chapters 1-3 (optional).
5. Call `POST /api/imports/deep/sync` or directly run `DeepImportWorkflow` with chapters 1-3.
6. Query and print counts of scenes, entities, relations, plot_threads, outline_arcs, foreshadowing_plans, reveal_plans, delta_logs, memory_snapshots.
7. Assert at least one scene and one entity created.

Use direct service invocation to avoid needing a running server. Import `DeepImportWorkflow` and `DeepImportProgress`.

- [ ] **Step 7.2: 运行脚本（需要真实 LLM + DB）**

Run: `cd backend && python scripts/acceptance_deep_import.py`
Expected: prints counts, exits 0.

- [ ] **Step 7.3: Commit**

```bash
git add backend/scripts/acceptance_deep_import.py
git commit -m "chore(acceptance): real-LLM deep import acceptance script for 诡秘之主 1-3"
```

---

## Task 8: 前端 E2E 验证与补齐

**Files:**
- Modify (if needed): `frontend-console/views/writingView.js`
- Modify: `frontend-console/e2e/deep-import.spec.js`

- [ ] **Step 8.1: 确认现有 UI 已满足 spec**

From inspection:
- 入口：`writingView.js` 编辑器按钮提供 `data-action="deep-import"`。
- 进度条：`_renderDeepImportBar` 已存在。
- 恢复：`_recoverDeepImportTask` 在 `onEnter`/`onActivate` 调用。
- 无章节：空状态只渲染新建章节按钮，深度导入按钮不显示。

If any of these is not true after backend changes, fix.

- [ ] **Step 8.2: 补齐 E2E 测试**

In `frontend-console/e2e/deep-import.spec.js`, add or ensure:

```js
test("从写作视图启动深度导入并展示三阶段进度", async ({ page }) => {
  await createDraft(testProjectId, 1, "第一章 绯红", "...")
  await openWorkbench(page, { id: testProjectId }, "writing")
  await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)

  await page.route("/api/imports/deep", async (route) => {
    await route.fulfill({ status: 201, json: { workflow_id: "wf-1", task_id: "task-1", status: "pending" } })
  })
  await page.route("/api/tasks/task-1", async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        id: "task-1", status: "running", progress: 0.4,
        result: {
          phase: "running", current_step: "entity_extraction",
          completed_steps: ["scene_segmentation"],
          phase1_completed_batches: 1, phase1_total_batches: 1,
          message: "Phase 2/3: 实体提取",
        },
      },
    })
  })

  await page.click('[data-action="deep-import"]')
  await page.fill('#deep-import-start', '1')
  await page.fill('#deep-import-end', '1')
  await page.click('.modal-content .btn-primary')

  await expect(page.locator("#writing-deep-import-bar-container")).toContainText("Phase 2/3")
  await expect(page.locator("#writing-deep-import-bar-container")).toContainText("实体提取")
})
```

- [ ] **Step 8.3: 运行前端单元测试**

Run: `cd frontend-console && npm run test`
Expected: pass.

- [ ] **Step 8.4: 运行 E2E（mock）**

Run: `cd frontend-console && npm run test:e2e deep-import.spec.js`
Expected: pass.

- [ ] **Step 8.5: Commit**

```bash
git add frontend-console/
git commit -m "test(frontend): deep import progress and recovery E2E coverage"
```

---

## Task 9: 最终验证与收尾

- [ ] **Step 9.1: 后端全量测试**
  - Run: `cd backend && python -m pytest modules/imports/tests/ modules/world/tests/test_world.py modules/outline/tests/test_tasks.py -x`
  - Expected: pass.
- [ ] **Step 9.2: Lint/format**
  - Run: `cd backend && ruff check modules/imports modules/outline modules/world`
  - Run: `cd backend && ruff format modules/imports modules/outline modules/world`
  - Expected: clean.
- [ ] **Step 9.3: 真实 LLM 验收**
  - Run: `cd backend && python scripts/acceptance_deep_import.py`
  - Record output counts in a comment or `docs/superpowers/acceptance/2026-06-13-deep-import-acceptance.md`.
- [ ] **Step 9.4: 最终代码审查 subagent**
  - Dispatch final reviewer subagent per `subagent-driven-development`.
- [ ] **Step 9.5: Commit 验收记录**
  - Commit any new docs.

---

## 执行选项

Plan complete and saved to `docs/superpowers/plans/2026-06-13-deep-import-three-pass-plan.md`.

**Recommended execution:** Subagent-Driven Development — dispatch fresh implementer subagents per task, followed by spec compliance and code quality reviewers.
