# 交叉验收报告：`post-acceptance-fixes` 分支

> 审阅对象：`.worktrees/post-acceptance-fixes` (commit `6d05cb5` + 未提交改动)
> 审阅日期：2026-06-12
> 审阅范围：`docs/superpowers/plans/2026-06-11-post-agent-acceptance-fixes.md` 全 8 个任务

---

## 总览

| 任务 | 状态 | 测试通过 |
|------|------|----------|
| Task 1 项目软删除 | ✅ 完整（超计划） | 83/83 |
| Task 2 深度导入启动 | ✅ 正确 | 87/87 |
| Task 3 Scene 偏移断章 | ✅ 正确 | 83/83 |
| Task 4 实体回滚 | 🔴 存在多个问题 | 83/83 |
| Task 5 实体重复确认 | ✅ 前后端完整 | 83/83 |
| Task 6 XSS 加固 | 🟡 部分完成 | 87/87 |
| Task 7 E2E 测试 | ✅ 新建 3 个 spec | — |
| Task 8 最终验证 | ✅ 全绿 | — |

---

## 🔴 P0 — 必须修复

### 1. `EntityRollbackService` 缺少 novel_id 访问控制校验

**文件:** `backend/modules/world/services/rollback_service.py:32-35`

```python
eid = parse_uuid(entity_id, "entity_id")
nid = parse_uuid(novel_id, "novel_id")

entity = await self._entity_repo.get(db, eid)
if entity is None or str(entity.novel_id) != str(nid):
```

`nid` 解析后从未用于权限校验。`entity.novel_id` 应和 `nid` 比较以防止跨 novel 访问。当前仅校验了 entity 存在性，未校验归属。攻击者可通过任意 `novel_id` 参数回滚其他项目的实体。

**修复:** 在校验行补充 `str(entity.novel_id) != str(nid)`。

---

### 2. `EntityRollbackService` 直接设属性绕过 `CoreEntityRepository.update()`

**文件:** `backend/modules/world/services/rollback_service.py:110-117`

```python
if update_values:
    stmt = select(CoreEntity).where(CoreEntity.id == eid)
    result = await db.execute(stmt)
    row = result.scalar_one()
    for k, v in update_values.items():
        setattr(row, k, v)
    db.add(row)
    await db.flush()
```

直接 `setattr` + `db.add` 绕过了 `CoreEntityRepository.update()` 方法。后果：
- `updated_at` 时间戳不会更新
- 不经过 repository 层的数据校验和业务规则
- 与其他所有 entity 更新路径不一致，增加维护风险

**修复:** 使用 `self._entity_repo.update(db, eid, CoreEntityUpdate(**update_values))` 或至少手动更新 `updated_at`。

---

### 3. MANUAL_ROLLBACK DeltaLog 缺少必要字段

**文件:** `backend/modules/world/services/rollback_service.py:119-127`

```python
rollback_delta = DeltaLog(
    novel_id=nid,
    entity_id=eid,
    category="MANUAL_ROLLBACK",
    source="manual_rollback",
    scene_index=target_scene_index,
    meta={"target_scene_index": target_scene_index},
)
db.add(rollback_delta)
```

只设置了 `category`、`source`、`meta`。未设置:
- `field_path`: DeltaLog 的核心字段，用于区分变更了哪个属性。回滚是整体操作，但字段不应为空。
- `new_value` / `old_value`: 未记录回滚前后的值。
- `created_at`: 依赖 ORM 默认值，不确定 DeltaLog 模型是否有 `default=now()`。

**修复:** 至少设置 `field_path="__rollback__"` 和 `new_value=f"rolled back to scene_index <= {target_scene_index}"`。

---

### 4. 回滚字段重建策略有逻辑缺陷

**文件:** `backend/modules/world/services/rollback_service.py:53-57`

```python
reconstructed: dict[str, object] = {}
for d in deltas:
    if d.field_path and d.new_value is not None:
        reconstructed[d.field_path] = d.new_value
```

此策略取"最后一条有 new_value 的 DeltaLog"的值。但如果变更序列是 `importance: 0.5 → 0.7 → 0.3`，且 `target_scene_index` 落在第一个变更之后、第二个变更之前，正确结果应为 `0.7`（回退到此时间点的最新状态），但上述逻辑会取 `0.3`（全局最后一条记录）。

**修复:** 按 `scene_index <= target_scene_index` 过滤后再取 last new_value；或按时间线逐条应用变更只到目标 scene_index。

---

## 🟡 P1 — 建议修复

### 5. `POST /entities/{entity_id}/rollback` 破坏性 API 变更

**文件:** `backend/modules/world/api.py:265-278`

```python
# 原来:
revision_id: str = Query(..., description="目标版本 ID")

# 改为:
data: EntityRollbackRequest  # { target_scene_index: int }
```

原端点接受 `?revision_id=xxx` query parameter，改为接受 `{target_scene_index: int}` request body。这会破坏所有现有前端或其他服务的调用。

**建议:** 保留旧端点作为 legacy，新增 `/rollback-by-scene` 端点，并在旧端点上标注废弃注释。

---

### 6. 旧 `EntityRevisionService` 无废弃标记

**文件:** `backend/modules/world/services/entity_revision_service.py`（全文）

`rollback_to_revision()` 方法仍然存在且看起来可用，但实际回滚已迁移到 `EntityRollbackService`。开发者阅读代码时无法区分新旧回滚路径，可能误用。

**建议:** 在旧的 `rollback_to_revision` 方法添加 `[Legacy]` 标记，或删除该方法。

---

### 7. `contextView._renderCompileResult()` 仍使用 `innerHTML`

**文件:** `frontend-console/views/contextView.js:149-184`

`_renderCompileResult` 从头到尾用字符串拼接 HTML，然后一次性 `output.innerHTML = html`。虽然所有动态值都用了 `esc()`，但按照计划要求"remove risky innerHTML rendering for user/AI content"，应改为 DOM 构造 API。

**建议:** 使用 `document.createElement()` + `textContent` 重构渲染逻辑，或在方法注释中明确说明 `esc()` 的使用已经足以防御 XSS。

---

### 8. `generateView._handleGenerate()` 多处 `innerHTML` 残留

**文件:** `frontend-console/views/generateView.js:149, 163, 191`

```javascript
// line 149 - 静态加载提示，风险较低但仍应避免
resultEl.innerHTML = '<div class="loading">步骤 2/6：正在编译上下文...</div>'

// line 163 - 同上
resultEl.innerHTML = `<div class="loading">步骤 3/6：正在生成${typeNames[this._currentType]}...</div>`

// line 191 - 含 dynamism 的预览内容
resultEl.innerHTML = previewHtml
```

第 191 行的 `previewHtml` 包含了从 API 响应拼装的字符串（`responseId`、`resp.status` 等）。虽然这些是后端返回值而非直接用户输入，但按照纵深防御原则应使用 DOM 构造。

**建议:** 对于静态加载提示（149、163），可保留但加注释标记为安全（纯静态字符串）。第 191 行应改为 `replaceChildren()` + DOM 构造。

---

### 9. `app._hideCommandBar()` 仍有 `innerHTML` 残留

**文件:** `frontend-console/app.js:150`

```javascript
if (suggestions) suggestions.innerHTML = ""
```

此处在清空元素，`innerHTML = ""` 是安全的（不插入内容）。应改为 `suggestions.replaceChildren()` 以与计划要求一致。

---

## 🟢 P2 — 可后续优化

### 10. `split_scene_chunk()` 的 reorder 可能产生索引冲突

**文件:** `backend/modules/outline/services.py:267-273`

```python
later_scenes = await self.repo.get_by_novel_ordered(db, nid)
for s in later_scenes:
    if s.id == source.id:
        continue
    if s.scene_index >= new_scene.scene_index:
        s.scene_index += 1
        db.add(s)
```

这段逻辑加载了全部 scenes 进行重排，在并发场景下可能产生 race condition（两个 split 同时执行导致 scene_index 重复）。当前单用户场景下可接受，但应增加注释说明此限制。

### 11. `generateView` 静态 HTML 字符串使用 `innerHTML`

**文件:** `frontend-console/views/generateView.js` 多处

视图中使用 `innerHTML` 渲染静态 HTML 字符串（不含用户/AI 数据）。虽然安全，但按计划要求应逐步改为 DOM 构造。

### 12. E2E fixtures 包含大文件

**文件:**
- `frontend-console/e2e/helpers/fixtures/oversized.bin`
- `frontend-console/e2e/helpers/fixtures/test.pdf`

应确认这些文件已加入 `.gitignore` 且不会进入版本库。`oversized.bin` 如果确实是用于测试的大文件，建议用脚本生成而非提交二进制。

---

## 亮点

- **Task 1 回收站**: 实现了从前端到后端的完整回收站闭环（list_deleted / restore / permanent_delete），超出计划要求。
- **Task 5 前后端完整**: 不仅实现了后端 409 去重检查，还完成了前端的 confirmAction + force_create 重试流程。
- **Task 4 架构设计**: 独立 `EntityRollbackService` 类结构清晰，分离了新旧回滚关注点。
- **测试质量**: 后端 83 测试 + 前端 87 测试全部通过，涉及的测试覆盖了计划的全部关键路径。
