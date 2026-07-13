# worldView 对象库过滤/分页/合并 E2E 失败记录

> 创建时间：2026-07-13
> 关联改动：项目页 / 世界页 / 大纲页 / 生成页 排版紧凑化
> 状态：已确认与本次排版改动无关，属既有缺陷，待后续修复

## 背景

在对世界页、大纲页、生成页进行顶部工具栏统一与布局紧凑化后，运行 Playwright E2E 时发现 `e2e/world.spec.js` 部分用例失败。为排除本次改动影响，已将 `frontend-console/views/worldView.js` 临时回退到 `HEAD` 重新执行，确认这些失败在原始代码上同样存在。

## 失败清单

运行命令：

```bash
cd frontend-console
npx playwright test e2e/world.spec.js --reporter=line
```

失败用例：

1. **合并实体到目标实体**
2. **回滚实体到指定场景索引**
3. **按类型过滤对象**
4. **按名称搜索对象**
5. **对象库分页**

## 症状与日志

### 1. 合并实体到目标实体

- **错误**：`.data-table` 中未找到「候选实体」，只显示「目标实体」。
- **可能原因**：候选实体（`status: "draft"`）默认被过滤在列表外，或列表加载逻辑未按测试预期展示候选实体。

### 2. 回滚实体到指定场景索引

- **错误**：

  ```
  API /world/_test/entities/{id}/text-archive failed (404): {"detail":"Not found"}
  ```

- **位置**：`e2e/helpers/api-client.js:29`，由 `e2e/world.spec.js:218` 调用 `seedEntityArchive` 触发。
- **可能原因**：后端测试用归档写入端点未注册或已被移除，导致测试前置数据无法写入。

### 3. 按类型过滤对象 / 按名称搜索对象 / 对象库分页

- **错误**：点击「应用」或「下一页」后，表格数据没有变化，仍显示旧数据。
- **示例**：选择 `entity_type=location` 后，表格仍包含 `faction` 类型的「测试组织」；翻到第 2 页后仍显示第 1 页的 20 条数据。

## 根因分析

### 过滤/分页未刷新数据

问题出在 `worldView.js` 的状态同步逻辑：

- `_applyFilters()` 先更新 `this._filters`，再调用 `router.navigate()` 变更 URL query。
- `renderCurrentView()` 判定为 `isSameRender`（同一视图、同一子标签、同一项目），因此跳过 `onEnter()`。
- `worldView.render()` 调用 `_syncRouteQueryState(subView, { loadOnChange: true })`。
- `_syncRouteQueryState()` 重新从 URL query 解析出 `nextFilters`，但此时 `this._filters` 已经被 `_applyFilters()` 设置为相同值，导致 `filtersChanged === false`，不会调用 `_loadEntities()`。

结果：DOM 被重新渲染，但 `this._entities` 仍是旧数据，界面看起来没有过滤/翻页。

相关代码：

- `frontend-console/views/worldView.js:2410-2429` `_applyFilters()`
- `frontend-console/views/worldView.js:249-271` `_syncRouteQueryState()`
- `frontend-console/views/worldView.js:345-349` `renderCurrentView()` 中的 `isSameRender` 判断
- `frontend-console/views/worldView.js:365-367` 仅在 `!isSameRender` 时才执行 `onEnter()`

### 合并实体测试数据问题

测试创建：

- `目标实体`：`status: "canonical"`
- `候选实体`：`status: "draft"`

对象库默认 `display_state=active`，后端可能把 `canonical` 视为 active，而 `draft` 不在 active 列表中，因此「候选实体」不会出现在对象库表格里。测试假设两者都会显示，可能需要调整测试数据或在测试前切换到「待处理」子标签。

### 回滚实体测试端点缺失

`seedEntityArchive` 依赖 `/world/_test/entities/{id}/text-archive`，该端点返回 404。需要确认：

- 该端点是否仅在特定测试配置下启用；
- 是否应改用正式 API 写入归档；
- 或测试辅助函数需要更新。

## 修复建议

### 方案 A：让 `_applyFilters()` 后强制刷新数据

在 `_applyFilters()`、`_resetFilters()`、`_changePage()` 中，构建完 query 后调用 `router.refresh()` 而非 `router.navigate()`，利用 `refresh()` 的 `_forceRefresh = true` 强制重新执行 `onEnter()` 并拉取数据。

风险：会丢失 `isSameRender` 优化，但这些操作本身就需要刷新，影响很小。

### 方案 B：在 `_syncRouteQueryState()` 中检测 query 与当前状态的差异

将「是否加载数据」的判断从「`this._filters` 是否变化」改为「URL query 是否与上一次加载时的 query 不同」。例如：

- 在 `worldView` 中保存 `_lastLoadedQuery`；
- `_syncRouteQueryState()` 中比较当前 query 与 `_lastLoadedQuery`；
- 如果不同，则调用 `_loadEntities()` 并更新 `_lastLoadedQuery`。

这样即使 `this._filters` 已被提前更新，也能正确触发加载。

### 方案 C：合并实体测试调整

将「候选实体」的 `status` 改为 `candidate` 或在「待处理」子标签中执行合并；或者调整测试断言，确认对象库默认只显示 active/canonical 实体。

### 方案 D：回滚实体测试修复

- 确认 `/world/_test/entities/{id}/text-archive` 是否应存在；
- 若已废弃，更新 `e2e/helpers/api-client.js` 中的 `seedEntityArchive` 使用新的归档写入方式；
- 或在后端补充该测试端点。

## 相关文件

- `frontend-console/views/worldView.js`
- `frontend-console/router.js`（`isSameRender` / `refresh()` 逻辑）
- `frontend-console/e2e/world.spec.js`
- `frontend-console/e2e/helpers/api-client.js`

## 验证记录

已执行以下验证：

```bash
# 当前代码：失败
cd frontend-console
npx playwright test e2e/world.spec.js --reporter=line

# 临时回退 worldView.js 到 HEAD 后：同样失败
git checkout HEAD -- frontend-console/views/worldView.js
npx playwright test e2e/world.spec.js --reporter=line
```

结论：这些失败是 worldView 既有逻辑/测试数据/后端测试端点问题，与本次排版改动无关。
