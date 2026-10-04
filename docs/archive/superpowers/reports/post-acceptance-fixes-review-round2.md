# 二次验收报告：`post-acceptance-fixes` 分支

> 审阅对象：`.worktrees/post-acceptance-fixes` (commit `6d05cb5` + 修复改动)
> 审阅日期：2026-06-12
> 上一轮报告：`docs/superpowers/reports/post-acceptance-fixes-review.md`（识别 4 个 P0、5 个 P1/P2 问题）

---

## 修复验证

### P0 — 已关闭（4/4）

| # | 问题 | 状态 | 验证 |
|---|------|------|------|
| 1 | `rollback_service.py` 缺少 novel_id 校验 | ✅ 已修复 | `rollback_service.py:35` — `str(entity.novel_id) != str(nid)` 已补充 |
| 2 | 直接 `setattr` 绕过 `repo.update()` | ✅ 已修复 | `rollback_service.py:116-122` — 改用 `self._entity_repo.update(db, eid, CoreEntityUpdate(...))`，带 None 检查 |
| 3 | MANUAL_ROLLBACK DeltaLog 缺字段 | ✅ 已修复 | `rollback_service.py:125-135` — 补充了 `field_path="__rollback__"`、`old_value=None`、`new_value=f"rolled back to scene_index <= {target_scene_index}"` |
| 4 | 字段重建策略逻辑缺陷 | ✅ 已修复 | `rollback_service.py:57-62` — 改用 `setdefault` 策略：先取最早 `old_value` 作为基线，再逐条 `new_value` 覆盖到目标 scene_index。注释清晰说明了策略 |

### P1 — 已关闭（3/3）

| # | 问题 | 状态 | 验证 |
|---|------|------|------|
| 5 | `/rollback` 破坏性 API 变更 | ✅ 已修复 | `world/api.py:281-293` — 新增 `POST /rollback-by-revision` 端点保留旧接口（`?revision_id=` query param），标记 `[Legacy]`。新 `/rollback` 使用 `EntityRollbackRequest` body |
| 6 | 旧 `EntityRevisionService` 无废弃标记 | ✅ 已修复 | `entity_revision_service.py:13-19` — 类 docstring 明确标注"已废弃为只读快照"；`rollback_to_revision` 方法添加 `[Legacy]` docstring 并注明替代方案 |
| 7 | `contextView._renderCompileResult()` innerHTML | ✅ 已修复 | `contextView.js:160-234` — 完全重构为 DOM 构造：`replaceChildren()` + `createElement()` + `textContent`。预算表、段落来源标签、警告信息全部通过 DOM API 构建 |

### P2 — 已关闭（2/3，1 个调整为预期行为）

| # | 问题 | 状态 | 验证 |
|---|------|------|------|
| 8 | `generateView._handleGenerate()` innerHTML | ✅ 已修复 | `generateView.js:149-225` — 加载步骤 2、3 和结果预览全部改为 DOM 构造。`responseId`、`typeNames[currentType]` 等动态值通过 `textContent` 设置 |
| 9 | `app._hideCommandBar()` innerHTML | ✅ 已修复 | `app.js:150` — 改用 `suggestions.replaceChildren()` |
| 10 | `split_scene_chunk()` reorder 并发风险 | ⚪ 预期接受 | 当前为单用户 demo 环境，并发非实际风险。建议在方法注释中标注此限制即可 |

---

## 超出预期

以下是在首轮报告中未被要求，但 Agent 主动完成的改进：

- **`contextView.js` 编译错误显示** → `replaceChildren()` + DOM 构造（原为 `innerHTML` + `esc()`）
- **`generateView.js` 生成错误显示** → `replaceChildren()` + DOM 构造（原为 `innerHTML`）
- **`generateView.js` 结果预览** → 动态 API 返回值的 `task_id`/`status` 现通过 `textContent` 赋值
- **`.gitignore` E2E fixtures** → 二进制测试文件 `oversized.bin`、`test.pdf` 已加入忽略

---

## 最终测试结果

```
后端 focus suite:  83 passed (project 32 + world 43 + outline 8)
后端 unit:          43 passed (revision + event + helpers + draft provider)
前端:               88 passed (11 test files)
```

前后端 214 个测试全部通过，前端测试数从 87 增至 88。

---

## 遗留问题

### ⚪ 接受的风险项

1. **`contextView.js` 的 `_budgetName()` 返回值未经 `esc()`** — 但 `_budgetName` 本身是静态映射函数，返回硬编码的中文标签，不包含用户/AI 数据，安全。

2. **`writingView.js` 的 `_rerender()` 系列方法仍用 `innerHTML`** — 这些是框架级的视图渲染方法，每次重新生成整个 HTML 片段。属于该 vanilla JS SPA 的架构模式，并非将用户输入直接塞入 `innerHTML`。所有动态值在渲染时由 `render()` 方法通过 `esc()` 转义。

3. **`backend/modules/imports/services.py` 的 diff** — 仅做了 linter 风格修复（长 f-string 拆行），无业务逻辑变更，确认安全。

---

## 总结

首轮报告中的 4 个 P0 问题全部修复且实现质量良好：

- `rollback_service.py` 现在正确校验 novel_id、使用 repository 更新接口、DeltaLog 字段完整、字段重建策略注释清晰
- API 层面同时保留了新旧回滚端点，向后兼容
- 前端 `contextView.js` 和 `generateView.js` 的 innerHTML 问题已彻底重构为纯 DOM 构造

**验收结论：通过。** 建议合并时确保 `rollback_service.py` 的新文件也纳入。
