# 全子系统 Bug 审查与修复计划

## 审查范围

前端 10 个视图 + 路由/状态/命令系统，按「页面跳转逻辑」「数据显示问题」「数据填充问题」「错误处理问题」「XSS 安全」5 个维度逐个审查。

---

## 一、路由系统（router.js）— 2 个 Bug

### Bug R1：`_prevRenderedView` 导致子标签切换不刷新 onEnter

**位置**：router.js L108-L117
**现象**：上一轮优化引入 `_prevRenderedView`，同视图内切子标签时跳过 `onEnter`。但 `onEnter` 不仅加载数据，还负责重置状态。例如 `characterView.onEnter` 会重置 `selectedItem`，跳过后状态残留。
**修复**：改为比较 `_prevRenderedView === viewName && _prevSubView === subView`，只有视图+子标签都相同时才跳过。新增 `_prevSubView` 变量。

### Bug R2：`popstate` 中重复调用 `onLeave`

**位置**：router.js L212-L216
**现象**：`popstate` 处理器手动调用旧视图的 `onLeave`，然后又调用 `renderCurrentView`，后者也会调用 `onLeave`（当 `_prevView !== targetView` 时），导致 `onLeave` 被调用两次。
**修复**：移除 `popstate` 中的手动 `onLeave` 调用，统一由 `renderCurrentView` 处理。

---

## 二、worldView — 4 个 Bug

### Bug W1：对象列表未转义 `name`/`entity_type`/`summary`

**位置**：worldView.js L214-L219
**现象**：`_renderEntityList` 中 `<td>${e.name}</td>` 等未通过 `esc()` 转义，存在 XSS 风险。
**修复**：所有用户数据字段加 `esc()`。

### Bug W2：候选列表未转义 `name`/`entity_type`

**位置**：worldView.js L281-L285
**现象**：`_renderCandidatesList` 中 `<td>${c.name}</td>` 等未转义。
**修复**：加 `esc()`。

### Bug W3：编辑表单未转义 `entity.name`/`entity.summary`

**位置**：worldView.js L515-L529
**现象**：`editEntity` 中 `value="${entity.name}"` 和 `<textarea>...${entity.summary}` 未转义，如果名称包含 `"` 会破坏 HTML 属性。
**修复**：`value="${esc(entity.name)}"` 和 `${esc(entity.summary || "")}`。

### Bug W4：`onEnter` 不重置 `_candidates` 列表

**位置**：worldView.js L17-L53
**现象**：`onEnter` 中 `_candidates` 只在 API 成功时赋值，但 API 失败时不清空旧数据，导致切换项目后可能显示上一个项目的候选。
**修复**：在 `onEnter` 开头清空 `_entities = []` 和 `_candidates = []`。

---

## 三、geoView — 3 个 Bug

### Bug G1：`_renderEdges` 未转义 `srcName`/`tgtName`/`difficulty`

**位置**：geoView.js L326-L332
**现象**：`<td>${srcName}</td>` 等未转义，如果来源名包含 HTML 标签会导致 XSS。
**修复**：加 `esc()`。

### Bug G2：`_renderEras` 未转义 `era.name`/`era.summary`

**位置**：geoView.js L374-L376
**现象**：`<td><strong>${era.name}</strong></td>` 未转义。
**修复**：加 `esc()`。

### Bug G3：`_onLocationClick` 右侧面板未转义 `node.name`/`node.level`

**位置**：geoView.js L266-L267
**现象**：`<h4>${node.name}</h4>` 和 `<p>层级：${node.level || "未知"}</p>` 未转义。
**修复**：加 `esc()`。

---

## 四、timelineView — 3 个 Bug

### Bug T1：`deleteEvent` 使用 `updateEvent` 而非 `deleteEvent` API

**位置**：timelineView.js L194
**现象**：`deleteEvent` 调用 `api.timeline.updateEvent(..., { status: "deprecated" })`，但 API 层可能没有 `updateEvent` 方法（需要确认）。正确做法是调用 `api.timeline.deleteEvent`。
**修复**：确认 API 层方法名，使用正确的删除 API。

### Bug T2：`showEditForm` 未转义 `ev.title`/`ev.summary`/`ev.order_index`

**位置**：timelineView.js L158-L167
**现象**：`value="${esc(ev.title)}"` 已转义标题，但 `ev.summary` 在 textarea 中已转义，`ev.order_index` 在 value 中未转义（数字类型风险低但应一致）。
**修复**：统一转义。

### Bug T3：`_loadEvents` 静默吞掉错误

**位置**：timelineView.js L87
**现象**：`catch { this._events = [] }` 不给用户任何提示，用户看到空列表不知道是没数据还是加载失败。
**修复**：添加 `toast` 提示。

---

## 五、outlineView — 3 个 Bug

### Bug O1：`_submitChapterCardExtraction` 使用 `prompt()` 而非模态框

**位置**：outlineView.js L442-L445
**现象**：使用 `prompt("起始章节：", "1")` 弹出浏览器原生对话框，与项目其他地方使用 `showModal` 的风格不一致，且 `prompt` 在部分浏览器中可能被阻止。
**修复**：改为 `showModal` 形式，与 writingView 中的章节卡提取确认弹窗保持一致。

### Bug O2：CRUD 操作后 `router.navigate` 不刷新数据

**位置**：outlineView.js L124, L130, L299, L305, L358, L382, L425, L434 等
**现象**：创建/删除/更新后调用 `router.navigate("outline", "threads")` 等，但由于 `_prevRenderedView` 优化，`onEnter` 被跳过，旧数据仍显示。需要强制刷新数据。
**修复**：在 CRUD 操作的 handler 中，先调用对应的 `_loadXxx()` 方法刷新数据，再调用 `router.navigate`。或者在 `navigate` 中增加 `forceRefresh` 参数。

### Bug O3：`_renderChapters` 中 `confirm-chapter` 的 `data-title` 可能包含特殊字符

**位置**：outlineView.js L331
**现象**：`data-title="${esc(c.title || "")}"` 已转义，但 `confirmChapter` 中用 `t.getAttribute("data-title")` 获取，HTML 实体解码后是正确的，无实际 Bug。确认无需修改。

---

## 六、memoryView — 2 个 Bug

### Bug M1：`confirmProposal`/`rejectProposal` 后不刷新列表

**位置**：memoryView.js L130-L146
**现象**：确认/拒绝提案后调用 `router.navigate("memory", "proposals")`，但由于 `_prevRenderedView` 优化，`onEnter` 被跳过，提案列表不刷新，已处理的提案仍显示。
**修复**：在操作成功后手动调用 `this._loadProposals()` 刷新数据，然后 `router.navigate`。

### Bug M2：`onEnter` 缺少项目检查提示

**位置**：memoryView.js L11-L14
**现象**：无项目时 `onEnter` 不提示，用户看到空列表不知道原因。
**修复**：无项目时 toast 提示。

---

## 七、writingView — 3 个 Bug

### Bug Wr1：`_cardCollapsible` 中 `JSON.stringify` 结果未转义

**位置**：writingView.js L355
**现象**：`esc(s.summary || s.description || s.scene_summary || JSON.stringify(s))` — `JSON.stringify` 的结果会经过 `esc()`，这部分没问题。但 L479 中 `typeof v === "object" ? JSON.stringify(v) : v` 的结果在 `_cardCollapsible` 中经过 `esc(display)` 处理，也 OK。确认无需修改。

### Bug Wr2：`_renderSidePanel` 中 `ending_hook` 重复渲染

**位置**：writingView.js L364 和 L371
**现象**：`_cardCollapsible("尾钩", card.ending_hook)` 出现两次，第一次在折叠字段区域，第二次也在折叠字段区域。
**修复**：删除重复的 L371 行。

### Bug Wr3：`_loadChapterCard` 加载成功但不刷新右侧面板

**位置**：writingView.js L549-L563
**现象**：`_loadChapterCard` 成功后只更新了 `this._currentCard`，注释说"本版本简单全量重绘右侧"但实际没有重绘。`_selectChapter` 的第二次 `render` 会刷新，但如果 `_loadChapterCard` 在 `_selectChapter` 的 `Promise.all` 之后才完成（竞态），可能不刷新。
**修复**：确认 `_selectChapter` 中 `Promise.all` 后的 `render` 能正确刷新。当前逻辑是先渲染骨架，再 `Promise.all`，再渲染完整页面，应该 OK。但需确认 `_loadChapterCard` 的结果在第二次 render 时已生效。

---

## 八、contextView — 2 个 Bug

### Bug C1：`_escapeHtml` 使用 DOM 方法而非 `esc()`

**位置**：contextView.js L247-L251
**现象**：`_escapeHtml` 创建 DOM 元素转义，与全局 `esc()` 函数功能重复且性能更差。
**修复**：删除 `_escapeHtml`，改用全局 `esc()`。

### Bug C2：`compile` 方法未校验 `novel_id`

**位置**：contextView.js L129
**现象**：`api.context.compile({ novel_id: _state.currentProjectId, ... })` 传入 `undefined` 的 `novel_id` 时，后端会返回 422 错误，但前端没有提前校验。
**修复**：在 `compile` 开头加 `if (!_state.currentProjectId) { toast("请先选择项目", "warning"); return }`。

---

## 九、ragView — 1 个 Bug

### Bug R1：`_doSearch` 中 `chunk.chapter_index` 未转义

**位置**：ragView.js L138
**现象**：`第 ${chunk.chapter_index} 章` 中 `chapter_index` 是数字，风险低，但为一致性应转义。
**修复**：加 `esc()`。

---

## 十、projectView — 2 个 Bug

### Bug P1：`editProject` 保存后不更新项目列表缓存

**位置**：projectView.js（需确认具体行号）
**现象**：编辑项目名称/描述后，侧边栏的项目列表仍显示旧名称。
**修复**：保存成功后刷新项目列表。

### Bug P2：`importFile` 错误处理不详细

**位置**：projectView.js（需确认具体行号）
**现象**：导入文件失败时只显示通用错误，不显示具体原因（如文件格式不支持、超过大小限制等）。
**修复**：从 API 错误响应中提取 `detail` 字段显示。

---

## 修复优先级排序

### P0 — 必须立即修复（XSS/数据安全）
1. Bug W1/W2/W3：worldView XSS 未转义
2. Bug G1/G2/G3：geoView XSS 未转义

### P1 — 高优先级（功能缺陷）
3. Bug R1：`_prevRenderedView` 导致子标签切换不刷新
4. Bug O2：CRUD 后数据不刷新
5. Bug M1：提案确认/拒绝后列表不刷新
6. Bug R2：popstate 重复 onLeave

### P2 — 中优先级（体验问题）
7. Bug W4：worldView onEnter 不清空旧数据
8. Bug O1：outlineView 使用 prompt()
9. Bug T1：timelineView 删除用错 API
10. Bug T3：timelineView 静默吞错误
11. Bug Wr2：writingView ending_hook 重复
12. Bug C1/C2：contextView 优化
13. Bug P1/P2：projectView 问题

### P3 — 低优先级（一致性/防御性）
14. Bug T2：timelineView 转义一致性
15. Bug R1：ragView 转义一致性
16. Bug M2：memoryView 无项目提示

---

## 实施步骤

### Step 1：修复路由系统（Bug R1, R2）
- router.js：引入 `_prevSubView`，修改 `renderCurrentView` 的 `onEnter` 跳过逻辑
- router.js：移除 `popstate` 中重复的 `onLeave` 调用

### Step 2：修复 XSS 问题（Bug W1-W3, G1-G3）
- worldView.js：所有用户数据字段加 `esc()`
- geoView.js：所有用户数据字段加 `esc()`

### Step 3：修复数据刷新问题（Bug O2, M1, W4）
- outlineView.js：CRUD 操作后先 `_loadXxx()` 再 `navigate`
- memoryView.js：确认/拒绝后先 `_loadProposals()` 再 `navigate`
- worldView.js：`onEnter` 开头清空列表

### Step 4：修复其他功能 Bug（Bug T1, T3, O1, Wr2, C1-C2, P1-P2）
- timelineView.js：修复删除 API、添加错误提示
- outlineView.js：prompt 改 showModal
- writingView.js：删除重复 ending_hook
- contextView.js：用 esc() 替换 _escapeHtml、添加 novel_id 校验
- projectView.js：保存后刷新列表、改进错误提示

### Step 5：运行测试验证
- 前端测试：`cd frontend-console && npm test`
- 后端测试：`cd backend && python -m pytest -x -q --ignore=tests/test_api.py`
