# 混乱测试发现的问题修复清单

以下问题来自 chaos testing 会话（2026-06-24），按优先级排列。每个问题包含复现步骤、根因分析和修复建议。

---

## P0 级（优先修复）

### Bug 1: 空字节注入崩溃后端

**模块**: `modules/project`

**问题**: 标题含空字节 `\x00` 时后端返回 500，服务不可用

**复现**:
```python
requests.post("http://localhost:8000/api/projects", json={"title": "test\x00xyz", "language": "zh"})
# → 500 InternalServerError
```

**根因**: 输入管道未处理 `\x00` 字符，Pydantic schema 无特殊校验

**修复要求**:
1. 在 `schemas.py` 的 title 字段或 validator 中 reject 或 strip 空字节
2. 或者全局添加中间件过滤请求中的空字节
3. 不要返回 500，应为 422 Validation Error 或自动 sanitize

**相关文件**: `backend/modules/project/schemas.py`

---

### Bug 2: PUT 暂存冲突检测失效 → 静默覆盖丢数据

**模块**: `modules/writing`

**问题**: 多 Tab 编辑时，PUT（暂存）不递增 `version_number`，乐观锁 `expected_version` 检查永远通过。Tab B 静默覆盖 Tab A 的内容，无 409 警告。违反 Spec 场景 4 多 Tab 冲突段（预期 409）。

**复现**:
```python
# Tab A 保存
PUT /writing/drafts/:id  {"content": "A的内容", "expected_version": 1}
# → 200, version 仍然是 1

# Tab B 用 stale expected_version 保存
PUT /writing/drafts/:id  {"content": "B覆盖A", "expected_version": 1}
# → 200 (本应 409), A 的内容永久丢失
```

**根因**: `backend/modules/writing/services.py:80-84`

```python
# services.py 中 update_draft()
# PUT 从不递增 version_number，所以 latest_version 始终 == expected_version
# 检查永远通过
if data.expected_version is not None and latest_version != data.expected_version:
    raise HTTPException(status_code=409, ...)
```

**修复要求**:
1. PUT 暂存时也应某种方式标记版本变化，使乐观锁生效
2. 设计要点：暂存UPDATE不应自增主版本号（vs 发布时INSERT新版本），但需要能检测到"在我之后有人写了"
3. 方案选择：
   - 暂存时递增 version_number（最简单，但暂存也算一个"版本"）
   - 引入 `draft_version` 或 `updated_at` 时间戳作为冲突检测依据
   - 用 `updated_at` 比较：如果数据库中的 `updated_at` 晚于客户端读取的时间 → 冲突

**相关文件**:
- `backend/modules/writing/services.py`（入口）
- `backend/modules/writing/repositories.py`
- `docs/核心业务场景与预期行为.md` 场景 4 多 Tab 冲突段

---

### Bug 3: 为已删除/不存在的实体创建角色返回 500

**模块**: `modules/world`

**问题**: 传入已删除或不存在的 `entity_id` 给 `POST /api/world/characters` 时，返回 500 而非 404/400

**复现**:
```python
# 创建实体，再删除
r = requests.post(url, json={"name": "test", "entity_type": "character"})
eid = r.json()["id"]
requests.delete(f"{url}/{eid}?novel_id={pid}")

# 为已删除实体创建角色 → 500
requests.post(f"{API}/world/characters", json={"entity_id": eid, "name": "Ghost"})
# 不存在的 UUID → 也是 500
requests.post(f"{API}/world/characters", json={"entity_id": "00000000-0000-0000-0000-000000000000", "name": "Ghost"})
```

**根因**: `CharacterService.create()`（继承自 `core/crud.py`）直接调用 repo 创建，不校验 `entity_id` 是否存在。数据库 FK 约束违反抛 IntegrityError，FastAPI 兜底返回 500。

**修复要求**:
1. 在 `CharacterService.create()` 中，创建前校验 `entity_id` 对应的 `CoreEntity` 是否存在
2. 不存在时返回 404 `"CoreEntity {id} not found"`
3. 在 service 层 catch IntegrityError 转换为友好错误（4xx）

**相关文件**:
- `backend/modules/world/services/character_service.py`
- `backend/core/crud.py`（父类 create 方法）

---

## P1 级（次优先）

### Bug 4: 纯空格标题入库为空字符串

**模块**: `modules/project`

**问题**: 标题 `"   "`（纯空格）通过 Pydantic 校验后变 `""` 入库，前端显示项目无标题

**复现**:
```python
requests.post("http://localhost:8000/api/projects", json={"title": "   ", "language": "zh"})
# → 201, title 为 "" (空字符串)
```

**根因**: `schemas.py` 中 `_sanitize_title_field` 在 `Field(min_length=1)` 之后运行。原始字符串长度 3 通过 min_length，strip 后变空不触发重新校验。

**修复要求**: 在 `_sanitize_title_field` 中 strip 后检查是否为空，空则 raise ValueError

**相关文件**: `backend/modules/project/schemas.py`

---

### Bug 5: 手动编辑实体不创建回滚快照

**模块**: `modules/world`

**问题**: `WorldEntityService.update()` 不触发 `EntityRevisionService.create_snapshot()`，只有 AI 导入流程的实体才支持回滚。UI 上回滚功能对手动创建实体不可用。

**复现**:
```python
# 创建实体
r = requests.post(f"{API}/world/entities", json={"name": "测试", "entity_type": "character"})
eid = r.json()["id"]

# 编辑实体
requests.put(f"{API}/world/entities/{eid}", json={"summary": "编辑后的摘要"})

# 查询版本 → 空
requests.get(f"{API}/world/entities/{eid}/revisions")
# → {"items": [], "total": 0}

# 回滚 → 404
requests.post(f"{API}/world/entities/{eid}/rollback", json={"target_scene_index": 0})
# → 404 "No revision or archive found"
```

**根因**: `WorldEntityService.update()` 只更新 ORM 字段，不调 snapshot。对比 AI 导入流程显式调用了 `create_snapshot()`。

**修复要求**:
1. 在 `WorldEntityService.update()` 成功后调用 `EntityRevisionService.create_snapshot()`
2. 捕获 snapshot 创建失败不阻断主流程

**相关文件**: `backend/modules/world/services/entity_service.py`

---

### Bug 6: 重复导入无去重

**模块**: `modules/imports`

**问题**: 同一文件上传两次，创建 6 条 WritingDraft 行（3 唯一索引），无重复检测。`GET /writing/chapters` 因去重返回 [1,2,3] 掩盖了问题。

**复现**: 上传 sample-novel.txt（3 章）两次，检查 DB 发现 6 条行，`import_records` 两条均为 status=done。

**修复要求**:
1. 上传前检查 `import_records` 是否有同 novel_id + 同 file_name 的已完成记录
2. 检测到重复时返回 400 "文件已导入"（或提供覆盖选项）
3. 确保 race condition 下不重复入库

**相关文件**: `backend/modules/imports/services.py`

---

### Bug 7: 回滚 API 无数据时返回 404

**模块**: `modules/world`

**问题**: 当无 TextArchive 或 EntityRevision 时，`rollback_to_scene_index()` 抛 HTTP 404，前端看到"资源未找到"（暗示实体不存在）。

**修复要求**: 返回 200 + `{"restored_fields":[], "warnings":["no rollback data available"]}` （实体存在，只是无数据可恢复）

**相关文件**: `backend/modules/world/services/entity_revision_service.py`

---

## P2 级（有空修）

### Bug 8: Merge 函数死代码

**模块**: `modules/world`

**位置**: `backend/modules/world/services/dedup_service.py` 第 457-461 行 vs 第 524-525 行

**问题**: 
- 第 457-461 行：前置检查 — target 非 canonical 抛 400
- 第 524-525 行：后置处理 — target 非 canonical 自动提升
- 前置检查阻止了后置逻辑执行，524-525 是死代码

**修复要求**: 移除死代码（若保留前置检查）或移除前置检查让自动提升生效（符合 Spec）

---

### Bug 9: 并发导入后后端间歇性 500

**模块**: `modules/imports` + 全局

**问题**: 约 25% 概率并发导入后所有写入操作返回 500，`/api/health` 仍正常。数据库连接池或事务状态可能被污染。

**修复要求**: 检查导入流程中的异常处理和资源释放，确保错误不污染全局连接状态。

---

### Bug 10: 前端 Console Error

**模块**: 前端 worldView

**问题**: 视图切换时 404 资源请求错误

**修复要求**: 检查 worldView 视图切换时的资源加载路径
