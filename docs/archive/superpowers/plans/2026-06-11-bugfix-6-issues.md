# 六项 Bug 修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复手动发现的 6 个独立 Bug（标题重复/删除不刷新/回收站路由/关系路径/别名缺失/Worker handler）

**Architecture:** 4 个前端修复（projectView.js、api.js、状态刷新逻辑），3 个后端修复（project/api.py 路由顺序、world/api.py 新增别名端点、worker.py 导入 handler），1 个配置修复（RAG embedding 超时）。每个 Bug 独立可测试。

**Tech Stack:** JavaScript (vanilla SPA)、Python FastAPI、PostgreSQL、BGE ONNX、异步 Task Worker

---

### Task 1: Fix 首页标题重复

**Files:**
- Modify: `frontend-console/views/projectView.js:39-41`

**根因:** `projectView.js` render() 在项目列表的 header 区块输出了 `<h1>项目</h1>`，同时 `index.html:88` 的 workspace header 已有 `<h2 id="view-title">项目</h2>`（通过 `state.js:133` 动态设置文本），导致"项目"二字在页面上出现两次。

**修复方案:** 删除 projectView.js 中多余的 `<h1>项目</h1>`，保留 workspace header 的标题。

- [ ] **Step 1: 删除 projectView.js 中的重复 h1**

将 projectView.js 第 39-40 行：
```html
<div style="display:flex;align-items:center;justify-content:space-between;">
  <h1>项目</h1>
```

改为：
```html
<div style="display:flex;align-items:center;justify-content:space-between;">
```

并移除第 41 行紧跟着的 `</div>` 调整到 div 闭合的最终位置。实际需要将：
```html
          <div style="display:flex;align-items:center;justify-content:space-between;">
            <h1>项目</h1>
            <button class="btn btn-ghost btn-sm" data-action="recycle-bin" style="font-size:12px;">回收站</button>
          </div>
```
改为：
```html
          <div style="display:flex;align-items:center;justify-content:space-between;">
            <button class="btn btn-ghost btn-sm" data-action="recycle-bin" style="font-size:12px;">回收站</button>
          </div>
```

- [ ] **Step 2: 验证修复**

```bash
grep -n "<h1>项目</h1>" frontend-console/views/projectView.js
```
Expected output: 无输出（已删除）

---

### Task 2: Fix 删除项目后前端不刷新

**Files:**
- Modify: `frontend-console/views/projectView.js:242-257`

**根因:** `deleteProject()` 成功调用 `api.projects.remove(id)` 后执行 `router.navigate("project")`。但 router 的 `renderCurrentView()`（`router.js:157`）检测到当前视图已经是 "project"（`isSameRender === true`），**跳过 `onEnter()` 调用**，而 `onEnter()` 负责重新拉取项目列表。导致 `state.projects` 仍包含已删除项目。

**修复方案:** 在 `deleteProject()` 成功后，从 `state.projects` 中移除已删除的项目，而不是依赖路由刷新。

- [ ] **Step 1: 在 deleteProject 成功后更新本地状态**

在 `projectView.js` 第 246 行 `await api.projects.remove(id)` 之后添加本地状态更新。修改 `deleteProject` 方法中的成功回调：

```javascript
confirmAction(
  `确定要删除项目「${esc(name)}」吗？删除后可在回收站中恢复。`,
  async () => {
    try {
      await api.projects.remove(id)
      // 从本地列表中移除，避免依赖路由 onEnter 刷新
      state.projects = state.projects.filter(p => p.id !== id)
      toast(`项目「${name}」已移至回收站`, "success")
      if (state.currentProjectId === id) {
        state.currentProjectId = null
        state.currentProject = null
      }
      router.navigate("project")
    } catch (err) {
      toast(`删除失败：${err.message}`, "error")
    }
  },
  "移至回收站",
)
```

关键改动在第 247 行之后插入：
```javascript
state.projects = state.projects.filter(p => p.id !== id)
```

- [ ] **Step 2: 验证修复**

```bash
grep -n "state.projects = state.projects.filter" frontend-console/views/projectView.js
```
Expected output: 包含该行（确认已添加）

---

### Task 3: Fix 回收站路由优先级

**Files:**
- Modify: `backend/modules/project/api.py:47-82`

**根因:** `/{project_id}` 路由（第 47 行）在 `/recycle-bin` 路由（第 75 行）之前注册。FastAPI/Starlette 按注册顺序匹配路由，`GET /api/projects/recycle-bin` 先匹配 `/{project_id}`，将 "recycle-bin" 作为 project_id 传入 `parse_uuid()`，UUID 解析失败返回 422。

**修复方案:** 将 `/recycle-bin` 和 `/{project_id}/restore`、`/{project_id}/permanent` 等具体路径放在 `/{project_id}` 之前注册。同时将 `/{project_id}` 涉及的所有子路由分组到一起。

- [ ] **Step 1: 重排 project/api.py 的路由注册顺序**

将 `/recycle-bin`、`/{project_id}/restore`、`/{project_id}/permanent` 路由移到 `/{project_id}` 路由之前。

调整后的顺序应为（仅列出受影响路由）：

```python
@router.get("", response_model=ProjectListResponse)      # 保持不变
async def api_list_projects(...)

# ---- 具体路径路由先注册 ----

@router.get("/recycle-bin", response_model=ProjectListResponse)  # 从第75行移到此处
async def api_list_deleted_projects(...)

@router.post("", response_model=ProjectResponse, status_code=201)  # 保持不变
async def api_create_project(...)

# ---- 参数化路由后注册 ----

@router.get("/{project_id}", response_model=ProjectResponse)  # 原有的第47行
async def api_get_project(...)

@router.put("/{project_id}", response_model=ProjectResponse)
async def api_update_project(...)

@router.delete("/{project_id}", status_code=204)
async def api_delete_project(...)

@router.post("/{project_id}/restore", response_model=ProjectResponse)  # 原有的第85行
async def api_restore_project(...)

@router.delete("/{project_id}/permanent", status_code=204)  # 原有的第94行
async def api_permanent_delete_project(...)
```

具体来说，将 `api_list_deleted_projects` 函数和装饰器（原始第 75-82 行）物理移到 `api_list_projects`（原始第 32-44 行）之后、`api_create_project` 之前。

- [ ] **Step 2: 验证路由顺序**

```bash
cd backend && python -c "
from app.main import app
for r in app.routes:
    if hasattr(r, 'path') and 'projects' in r.path:
        print(r.path, r.methods)
" 2>/dev/null | grep /api/projects/
```
Expected output: `/recycle-bin` 出现在 `/{project_id}` 之前

---

### Task 4: Fix 世界对象关系 API 路径不匹配

**Files:**
- Modify: `frontend-console/api.js:256-258,260-263,269-271`

**根因:** 前端调用 `/world/relationships` 但后端路由实际为 `/world/relations`（缺少 "-ships" 后缀）。所有关系操作均返回 404。

**修复方案:** 将前端 api.js 中所有 `relationships` 路径改为 `relations`。

- [ ] **Step 1: 修改 listRelationships 路径**

api.js 第 257 行：
```javascript
return request("/world/relationships" + buildQueryString(params))
```
改为：
```javascript
return request("/world/relations" + buildQueryString(params))
```

- [ ] **Step 2: 修改 createRelationship 路径**

api.js 第 262 行：
```javascript
return request(`/world/relationships${buildQueryString({ novel_id: novelId })}`, {
```
改为：
```javascript
return request(`/world/relations${buildQueryString({ novel_id: novelId })}`, {
```

- [ ] **Step 3: 修改 deleteRelationship 路径**

api.js 第 270 行：
```javascript
return request(`/world/relationships/${id}` + buildQueryString(params), { method: "DELETE" })
```
改为：
```javascript
return request(`/world/relations/${id}` + buildQueryString(params), { method: "DELETE" })
```

- [ ] **Step 4: 验证**

```bash
grep -n "relationships" frontend-console/api.js
```
Expected output: 无输出（所有 "relationships" 已替换为 "relations"）

---

### Task 5: Fix 世界对象别名 API 完全缺失

**Files:**
- Modify: `backend/modules/world/api.py` — 新增路由
- Modify: `backend/modules/world/services/__init__.py` — 导出 alias 服务函数
- Modify: `frontend-console/api.js:287-289` — 修正 deleteAlias 路径

**根因:** 后端 `world/api.py` 没有注册任何 alias 相关路由。前端调用 `GET /world/aliases`、`POST /world/aliases`、`DELETE /world/entities/{id}/aliases?alias=X` 全部返回 404。别名存储在 `CoreEntity.content_json.aliases` JSONB 中。

**修复方案:** 在 `world/api.py` 添加三条 alias 路由，使用 `WorldEntityService` 操作 `content_json.aliases`。同时在前端修正 deleteAlias 的 API 路径以匹配后端参数格式。

- [ ] **Step 1: 在 WorldEntityService 添加别名操作方法**

在 `backend/modules/world/services/entity_service.py` 的 `WorldEntityService` 类中添加三个方法：

```python
async def list_aliases(
    self,
    db: AsyncSession,
    novel_id: str,
    *,
    skip: int = 0,
    limit: int = 100,
) -> list[dict]:
    """列出项目下所有实体的别名"""
    nid = parse_uuid(novel_id, "novel_id")
    entities, _ = await self.repo.get_by_novel(db, nid, limit=limit)
    result = []
    for entity in entities:
        aliases = (entity.content_json or {}).get("aliases", [])
        for a in aliases:
            alias_text = a if isinstance(a, str) else a.get("alias", "")
            alias_type = a.get("type", "name") if isinstance(a, dict) else "name"
            result.append({
                "entity_id": str(entity.id),
                "entity_name": entity.name,
                "alias": alias_text,
                "alias_type": alias_type,
            })
    return result[skip:skip + limit]

async def create_alias(
    self,
    db: AsyncSession,
    novel_id: str,
    entity_id: str,
    alias: str,
    alias_type: str = "name",
) -> dict:
    """为实体添加别名"""
    nid = parse_uuid(novel_id, "novel_id")
    eid = parse_uuid(entity_id, "entity_id")
    entity = await self.repo.get(db, eid)
    if entity is None or entity.novel_id != nid:
        raise HTTPException(status_code=404, detail="Entity not found")
    content = entity.content_json or {}
    aliases = content.get("aliases", [])
    # 去重检查
    for a in aliases:
        existing = a if isinstance(a, str) else a.get("alias", "")
        if existing == alias:
            raise HTTPException(status_code=409, detail=f"Alias already exists: {alias}")
    aliases.append({"alias": alias, "type": alias_type})
    content["aliases"] = aliases
    entity.content_json = content
    await db.flush()
    return {"entity_id": str(entity.id), "alias": alias, "alias_type": alias_type}

async def delete_alias(
    self,
    db: AsyncSession,
    novel_id: str,
    entity_id: str,
    alias: str,
) -> dict:
    """删除实体的指定别名"""
    nid = parse_uuid(novel_id, "novel_id")
    eid = parse_uuid(entity_id, "entity_id")
    entity = await self.repo.get(db, eid)
    if entity is None or entity.novel_id != nid:
        raise HTTPException(status_code=404, detail="Entity not found")
    content = entity.content_json or {}
    aliases = content.get("aliases", [])
    new_aliases = []
    found = False
    for a in aliases:
        existing = a if isinstance(a, str) else a.get("alias", "")
        if existing == alias:
            found = True
            continue
        new_aliases.append(a)
    if not found:
        raise HTTPException(status_code=404, detail=f"Alias not found: {alias}")
    content["aliases"] = new_aliases
    entity.content_json = content
    await db.flush()
    return {"entity_id": str(entity.id), "alias": alias, "deleted": True}
```

- [ ] **Step 2: 在 world/api.py 添加别名路由**

在 `world/api.py` 末尾，`characters` 路由之前或之后添加：

```python
# ============================================================
# Entity Alias 路由（操作 core_entities.content_json.aliases）
# ============================================================


@router.get("/aliases")
async def list_aliases(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    """列出项目下所有实体的别名"""
    return await _entity_service.list_aliases(
        db, novel_id, skip=skip, limit=limit,
    )


@router.post("/aliases", status_code=201)
async def create_alias(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: EntityAliasCreate = ...,
) -> dict:
    """为实体添加别名"""
    return await _entity_service.create_alias(
        db, novel_id, data.entity_id, data.alias, data.alias_type,
    )


@router.delete("/entities/{entity_id}/aliases")
async def delete_alias(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
    alias: str = Query(..., description="要删除的别名文本"),
) -> dict:
    """删除实体的指定别名"""
    return await _entity_service.delete_alias(
        db, novel_id, entity_id, alias,
    )
```

需要确保已在 world/api.py 顶部导入 `EntityAliasCreate`。检查导入部分，如果未导入则添加：
```python
from modules.world.schemas import (
    ...,
    EntityAliasCreate,  # 添加
)
```

- [ ] **Step 3: 修正前端 deleteAlias 的路径（非必须，如现路径匹配后端则跳过）**

检查 `frontend-console/api.js:287-289` 的 `deleteAlias`：
```javascript
async deleteAlias(entityId, alias, params = {}) {
    params.alias = alias
    return request(`/world/entities/${entityId}/aliases` + buildQueryString(params), { method: "DELETE" })
},
```
该路径与后端新增的 `DELETE /api/world/entities/{entity_id}/aliases` 匹配，无需修改。

- [ ] **Step 4: 验证**

```bash
grep -n "aliases" backend/modules/world/api.py | head -10
```
Expected output: 显示三条 alias 路由注册

---

### Task 6: Fix RAG 重建索引后 embedding 失败

**Files:**
- Modify: `backend/core/config.py:85` — 增加超时
- Modify: `backend/modules/rag/services.py:1158-1189` — 逐 chunk 重试 + 熔断

**根因:** 索引流程将章节所有 chunk 文本一次性传给 `generate_embedding()`（`services.py:1165`），默认 5s 超时在 CPU 推理时不足。且不支持逐 chunk 重试，全有或全无的失败模式导致整章 chunk 标记为 `failed`。

**修复方案:** 增大默认超时 + 逐 chunk 重试 + 索引流程接入熔断器。

- [ ] **Step 1: 增加 BGE worker 默认超时**

`backend/core/config.py:85`：
```python
inference_worker_timeout: float = float(_env("INFERENCE_WORKER_TIMEOUT", "5.0"))
```
改为：
```python
inference_worker_timeout: float = float(_env("INFERENCE_WORKER_TIMEOUT", "30.0"))
```

- [ ] **Step 2: 索引流程启用逐 chunk 重试 + 熔断器**

修改 `backend/modules/rag/services.py` 中 `index_chapter_with_report()` 方法的 embedding 生成部分（第 1158-1189 行），将：
```python
embedding_failed_count = 0
if created_chunks:
    try:
        from infrastructure.llm.client import LLMClient

        llm = LLMClient()
        texts = [chunk.text for chunk in created_chunks]
        embeddings = await llm.generate_embedding(texts)
        if (
            isinstance(embeddings, list)
            and len(embeddings) == len(created_chunks)
        ):
            for chunk, emb in zip(created_chunks, embeddings):
                await self._repo.update_embedding(db, chunk.id, emb)
                chunk.embedding_status = "succeeded"
            await db.flush()
        else:
            raise ValueError("embedding result count does not match chunk count")
    except Exception as exc:
        warning = f"embedding 生成失败，本章检索将降级为关键词/词典匹配: {exc}"
        warnings.append(warning)
        logger.warning(
            "Failed to generate embeddings for chapter %d: %s",
            chapter_index,
            exc,
        )
        embedding_failed_count = len(created_chunks)
        for chunk in created_chunks:
            chunk.embedding_status = "failed"
            chunk.embedding_error = str(exc)[:1000]
            chunk.index_warnings = [warning]
        await db.flush()
```

改为：
```python
embedding_failed_count = 0
if created_chunks:
    from modules.rag.circuit_breaker import get_circuit_breaker

    cb = get_circuit_breaker()
    from infrastructure.llm.client import LLMClient

    llm = LLMClient()

    # 逐 chunk 生成 embedding，失败不阻塞本章其他 chunk
    for chunk in created_chunks:
        if not cb.allow_request():
            chunk.embedding_status = "failed"
            chunk.embedding_error = "BGE 熔断中，跳过 embedding 生成"
            chunk.index_warnings = ["BGE 服务熔断中，embedding 跳过"]
            embedding_failed_count += 1
            continue

        try:
            embedding = await llm.generate_embedding(chunk.text)
            if isinstance(embedding, list) and embedding and isinstance(embedding[0], float):
                await self._repo.update_embedding(db, chunk.id, embedding)
                chunk.embedding_status = "succeeded"
                cb.record_success()
            else:
                raise ValueError("embedding 返回格式异常")
        except Exception as exc:
            cb.record_failure()
            chunk.embedding_status = "failed"
            chunk.embedding_error = str(exc)[:1000]
            chunk.index_warnings = [f"embedding 生成失败: {exc}"]
            embedding_failed_count += 1

    await db.flush()

    if embedding_failed_count > 0:
        warnings.append(
            f"本章 {embedding_failed_count}/{len(created_chunks)} 个片段 embedding 失败，检索将降级为关键词匹配",
        )
```

- [ ] **Step 3: 验证**

```bash
cd backend && python -c "
from core.config import get_settings
print('BGE timeout:', get_settings().inference_worker_timeout)
"
```
Expected output: `BGE timeout: 30.0`

---

### Task 7: Fix Worker 进程未注册 task handler

**Files:**
- Modify: `backend/infrastructure/tasks/worker.py:34-35`

**根因:** Worker 进程 (`run_worker.py`) 只启动了 `TaskWorker`，但从未导入各模块的 `tasks.py`，导致 `TaskRegistry` 中没有任何 handler 注册。所有异步任务（深度导入、RAG 重建索引、世界对象抽取等）均因 `"No handler registered for task type: ..."` 失败。

**修复方案:** 在 `worker.py` 中导入所有 task handler 模块（与 `main.py` 第 330-334 行一致）。

- [ ] **Step 1: 在 worker.py 导入所有 handler 模块**

修改 `backend/infrastructure/tasks/worker.py` 末尾的导入部分（第 34-35 行）：

```python
# 注册 projects 表（NovelMixin FK 依赖）
import modules.project.models  # noqa: F401

# 注册所有任务处理器（与 app/main.py 同步）
import modules.world.tasks  # noqa: F401
import modules.rag.tasks  # noqa: F401
import modules.outline.tasks  # noqa: F401
import modules.imports.tasks  # noqa: F401
import modules.writing.tasks  # noqa: F401
```

注意：如果 `worker.py` 中已有 `import modules.project.models`，保留它并在其后添加上述 5 行导入。

- [ ] **Step 2: 验证**

```bash
cd backend && python -c "
from infrastructure.tasks.registry import TaskRegistry
registry = TaskRegistry()
print('Registered handlers:', registry.registered_types)
"
```
Expected output: 应包含 `deep_import`、`rag_reindex_novel`、`rag_index_chapter`、`world_entity_extraction`、`plot_structure_generate`、`publish_chapter`
