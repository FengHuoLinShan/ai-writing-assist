# 前端异步交互失败路径审查

## 背景

用户触发异步流程（如"地图 → 快速创建"）时，入口或业务方法未接住 Promise rejection，失败只进入全局 `errorLogger` / 右下角错误计数，不进入用户可见业务反馈，表现为"按钮无反应"。

根因链条：`UI event → async handler (fire-and-forget) → rejection → window.unhandledrejection → errorLogger 计数 +1`，用户无感知。

## 结论摘要

- **严重 (CRITICAL)**：2 个系统性模式，影响所有 modal 和 click 委托
- **高 (HIGH)**：4 个具体代码位置，handler 内无 try/catch，rejection 完全无声
- **中 (MEDIUM)**：5 个位置，fire-and-forget 但依赖内部 catch，如内部 catch 遗漏则无声失败
- **低 (LOW)**：6 个位置，有 catch 但 toast 可能因 modal 提前关闭而不可见

## 2026-07-08 实施状态

本轮修复保持前端内聚，只修改前端 handler、modal/helper、测试和本审计文档；未修改后端 API、schema 或 wire contract。

### 已修复

- C1 `ui/modal.js`：modal 按钮现在 `await` handler。普通按钮成功 resolve 后自动关闭；handler reject 时 toast `操作失败：...` 且 modal 保持打开；handler 返回 `false` 时保持打开，用于业务方法已本地 toast 的失败或校验不通过路径。取消/关闭按钮仍直接关闭。
- C2 `shared/viewHelper.js`：`bindDelegation` 现在捕获同步 throw 和 async reject，并 toast `操作失败：...`。`mapWorkspaceView._bindEvents()` 因未走共享 helper，单独补了统一 async 兜底。
- H1 `sceneWorkbenchView.js`：Scene merge/split 确认 API reject 时显示业务 toast，handler 返回 `false`，modal 不关闭。
- H2 `outlineView.js`：AI 生成剧情结构 modal 移除脱钩 `setTimeout`，直接 `await _generateStructure(start, end)`；`_generateStructure` 仍保留“catch 后 toast 并 rethrow”契约，modal handler 捕获后返回 `false`，避免重复 toast 和 unhandled rejection。
- H3 `mapQuickCreateView.js`：candidate toggle / target change 预览刷新失败时 toast `快速创建预览刷新失败：...`，恢复旧预览状态，不产生 unhandled rejection。快速创建确认失败或校验失败返回 `false`。
- H4 `projectView.js`：回收站批量恢复、批量永久删除、单个永久删除确认后的失败路径均有可见反馈；永久删除仍必须通过 `confirmAction` 二次确认。
- M1 `app.js`：导航点击、命令回车和命令建议点击的 reject 进入可见 toast。
- M2 `router.js`：`popstate` 路由处理失败进入 `console.warn` 和可见 toast。
- M3 `projectView.js`：由 C1 的 `confirmAction` async handler 契约兜住，不再丢弃 Promise。
- M4 `worldView.js`：对象、关系、别名单项复核标记失败时显示业务 toast 并返回 `false`。

### 部分已修 / 保留诊断

- `errorLogger` 保留为诊断辅助，但不再作为这些用户交互失败路径的唯一反馈面。
- `runBulkAction` 仍保留“单项失败聚合为 `failed` 结果”的既有契约；回收站永久删除只要存在失败就返回 `false`，避免确认 modal 成功关闭语义误导用户。

### 仍非本轮目标

- `writing/tools.js` 等更远端 setTimeout 或内部已有 catch 的低风险项未展开重构。本轮只修复已审计划覆盖的系统性失败路径和列名业务入口。
- 没有改变危险操作确认入口：永久删除、废弃、合并等仍保留既有二次确认语义。

---

## 系统性模式（CRITICAL）

### C1. `modal.js` — 异步 handler 未 await，modal 提前关闭

**文件**：`frontend-console/ui/modal.js:41-46`

```js
el.addEventListener("click", () => {
  btn.handler()          // 若 handler 是 async，Promise 被丢弃
  if (btn.text !== "取消" && btn.text !== "关闭") {
    closeModal()         // modal 立即关闭，不等 async 完成
  }
})
```

**问题**：
- `handler()` 返回值未被 `await`
- `closeModal()` 在 handler 返回后立即调用（对 async handler，promise pending 时 modal 已关）
- 即使 handler 内部有 try/catch + toast，toast 虽能显示，但 modal 已消失，用户可能错过上下文

**影响范围**：项目中所有 `showModal` / `showModalHtml` / `confirmAction` 调用 — 共 44+ 处 `handler: async () =>`。

**最小修复方向**：`btn.handler()` 改为 `await btn.handler()`（需要把外层 `addEventListener` 的 callback 标记为 async，并加 `.catch` 兜底）。同时移除或推迟自动 `closeModal()` 到 handler 完成后。

---

### C2. `viewHelper.js` / `mapWorkspaceView.js` — `root.onclick` 事件委托未 await

**文件**：`frontend-console/shared/viewHelper.js:20-30`（`bindDelegation`）
**文件**：`frontend-console/views/mapWorkspaceView.js:1433-1457`（`root.onclick`）

`bindDelegation` 中：
```js
element[key] = (e) => {
  const handler = handlerMap[a]
  if (handler) handler.call(view, e, t, ctx)  // 未 await
}
```

`mapWorkspaceView._bindEvents` 中：
```js
root.onclick = (e) => {
  if (action === "map-quick-create") this._openQuickCreate()   // async，fire-and-forget
  if (action === "map-open") this._openMap(...)                 // sync，OK
  if (action === "map-search-location") this._openLocation(...) // async，fire-and-forget
  if (action === "map-confirm-observation") this._confirmObservation(...) // async，fire-and-forget
  ...
}
```

**问题**：所有通过 `data-action` 分发的 handler 都是 fire-and-forget。虽然 `_openQuickCreate` 等内部有 try/catch，但任何同步 throw（如调用 `method()` 前 guard 遗漏）会直接丢失。

**最小修复方向**：在 `bindDelegation` 中将 handler 调用包装为 `try { await handler.call(...) } catch (e) { toast(...) }`，并使委托函数 async。

---

## 高优先级（HIGH）

### H1. `sceneWorkbenchView.js` — merge/split handler 无 try/catch

**文件**：`frontend-console/views/sceneWorkbenchView.js:849-857`
**触发入口**：Scene 合并确认按钮
```js
handler: async () => {
  await api.outline.mergeScenes(state.currentProjectId, { ... })
  toast("Scene 已合并", "success")
  closeModal()
  await router.refresh()
}
```

**文件**：`frontend-console/views/sceneWorkbenchView.js:1126-1135`
**触发入口**：Scene 拆分确认按钮
```js
handler: async () => {
  await api.outline.splitScene(state.currentProjectId, { ... })
  toast("Scene 已拆分", "success")
  closeModal()
  await router.refresh()
}
```

**失败路径**：API 返回 422/500 → Promise reject → 无 try/catch 拦截 → `unhandledrejection` → errorLogger 计数 +1

**用户可见表现**：modal 关闭（C1 导致），页面无变化，右下角错误计数增加

**最小修复方向**：加 `try/catch` 包裹，catch 中 `toast(err.message, "error")` 且不 `closeModal()`

---

### H2. `outlineView.js` — _generateStructure 的 setTimeout 绕过 catch

**文件**：`frontend-console/views/outlineView.js:1447-1449`
**触发入口**：AI 生成剧情结构确认按钮
```js
handler: async () => {
  try {
    closeModal()
    setTimeout(() => this._generateStructure(start, end), 0)  // try/catch 到此结束
  } catch (err) { toast(err.message || "生成失败", "error") }
}
```

**失败路径**：`_generateStructure` 是 async，在 setTimeout 中执行。try/catch 只覆盖了 `closeModal()` 和 `setTimeout()`（都同步）。`_generateStructure` 内的 rejection 完全无拦截。

**用户可见表现**：modal 关闭（C1），用户以为已提交，实际后台静默失败，errorLogger 计数 +1

**最小修复方向**：移除 setTimeout，直接在 handler 内 `await this._generateStructure(start, end)`，并确保 `_generateStructure` 有内部 try/catch 或 handler 包裹它。

---

### H3. `mapQuickCreateView.js` — onchange async 无 catch

**文件**：`frontend-console/views/mapQuickCreateView.js:182-186`
**触发入口**：快速创建 modal 中 checkbox/select 切换
```js
candidate.onchange = () => this.setIncludeCandidates(candidate.checked)  // async，fire-and-forget
target.onchange = () => this.setTarget(target.value)                      // async，fire-and-forget
```

`setIncludeCandidates`/`setTarget` 内部调用 `api.world.getMapQuickCreateContext` 和 `api.world.previewQuickCreateMap`，均未包 try/catch。

**失败路径**：API 失败 → `setIncludeCandidates` 内 `await` reject → unhandled

**用户可见表现**：checkbox 切换了，但预览未更新，无任何提示

**最小修复方向**：在两个方法内加 try/catch + toast

---

### H4. `projectView.js` — 批量恢复无 try/catch

**文件**：`frontend-console/views/projectView.js:473-479`
**触发入口**：回收站"批量恢复"按钮
```js
document.getElementById("recycle-bulk-restore")?.addEventListener("click", async () => {
  const result = await runBulkAction(selected, async (project) => api.projects.restore(project.id))
  toast(...)
  router.refresh()
  this.showRecycleBin()
})
```

**失败路径**：`runBulkAction` reject → 无 catch → unhandledrejection

**用户可见表现**：无反应，errorLogger 计数 +1

**最小修复方向**：加 try/catch，catch 中 toast error

---

## 中优先级（MEDIUM）

### M1. `app.js` — 导航 click 和 command keydown 无 catch

**文件**：`frontend-console/app.js:77-83`
```js
el.addEventListener("click", async () => {
  await router.navigate(viewName, lastSub || ...)
})
```

**文件**：`frontend-console/app.js:168-177`
```js
input.addEventListener("keydown", async (e) => {
  if (e.key === "Enter") {
    await commands.execute(value)
  }
})
```

**问题**：`router.navigate` 和 `commands.execute` 均可能 reject，无 catch。

**最小修复方向**：加 `.catch()` 或 try/catch + toast

---

### M2. `router.js` — popstate 无 catch

**文件**：`frontend-console/router.js:453-463`
```js
window.addEventListener("popstate", async (e) => {
  await _applyRoute(routeState)
  await renderCurrentView()
})
```

**问题**：浏览器前进/后退时若路由处理 reject，无声失败。

**最小修复方向**：加 try/catch + console.warn

---

### M3. `projectView.js` — uploadFile 的 confirmAction 回调调用 async 未处理 rejection

**文件**：`frontend-console/views/projectView.js:620-623`
```js
confirmAction("深度导入已启动", async () => {
  await writingView._submitDeepImport(1, result.imported_chapters)
}, "启动深度导入第一阶段（scene）")
```

**问题**：`confirmAction` 的回调通过 `modal.js:41` 的 `handler()` 调用，未被 await。`_submitDeepImport` 内部有 try/catch，但若其在 catch 之前 throw（如 guard 遗漏），则无声失败。

**最小修复方向**：确保 `_submitDeepImport` 内部完全 try/catch 覆盖，或改造 confirmAction 支持 async。

---

### M4. `worldView.js` — `_markEntityReviewed/Unreviewed` 无调用方 catch

**文件**：`frontend-console/views/worldView.js:1798-1870`

这些方法通过 `data-action` 分发调用（见 viewHelper.js 的 `bindWorkspaceClick`），dispatch 层未 await。方法内部虽有 try/catch 部分（仅 getEntity），但 `updateEntity` 调用无 try/catch 包裹。

**失败路径**：`updateEntity` reject → 方法 reject → dispatch 层未 await → unhandled

**最小修复方向**：将 `updateEntity` 等关键调用包入 try/catch + toast

---

### M5. `writing/tools.js` — 断章确认后 setTimeout 绕过 catch

**文件**：`frontend-console/views/writing/tools.js:138-139`
```js
handler: async () => {
  modalApi.closeModal()
  await splitScene(splitPos, currentChapter, currentScene)  // splitScene 内有 try/catch，安全
}
```

此处 `splitScene` 已有 try/catch，标记为 MEDIUM 仅因 modal 提前关闭（C1），用户可能看不到后续 toast。风险较低。

---

## 低优先级（LOW）

### L1-L6. modal handler 有 try/catch 但 modal 提前关闭

以下文件中的 `handler: async () => { try { ... } catch { toast(...) } }` 模式在 catch 后能显示 toast（toast 同步），但由于 C1，modal 在 handler 返回时（promise pending）立即关闭。用户可能来不及关联 toast 和 modal 上下文。

- `frontend-console/views/worldView.js:1310,1642,1897,2400,2506,2641,2691,2750`
- `frontend-console/views/outlineView.js:728,773,831,891,981,1020,1098,1138,1218,1284,1380,1432`
- `frontend-console/views/mapView.js:1000,1584,1628,1685`
- `frontend-console/views/mapWorkspaceView.js:1196,1522`
- `frontend-console/views/projectView.js:360,565`
- `frontend-console/views/worldBibleView.js:287`
- `frontend-console/views/writing/autoExtraction.js:79,156`

**最小修复方向**：修复 C1 后，这些位置自动受益。

---

## 覆盖缺口

以下路径缺少"API reject → toast/inline feedback"测试覆盖：

| 路径 | 缺少的测试 |
|------|-----------|
| modal handler reject → toast 显示 | 模拟 `showModal` + async handler reject，验证 toast 被调用 |
| `_openQuickCreate` 内 `_loadContext` API reject | 模拟 API fail，验证 toast("快速创建...") 被调用 |
| `setIncludeCandidates` API reject | 无测试覆盖此路径 |
| `mergeScenes` handler reject | 无测试（当前 handler 无 catch，测试会失败） |
| `_generateStructure` setTimeout reject | 无测试 |
| `bindDelegation` handler 同步 throw | 无测试 |
| 批量恢复 `runBulkAction` reject | 无测试 |
| `root.onclick` fire-and-forget 异常传播 | 无测试 |

---

## 搜索方法

本次审查使用的 `rg` 命令：

```bash
# 系统性模式
rg "handler:\s*async" frontend-console/ --include "*.js" -n
rg "addEventListener.*async" frontend-console/ --include "*.js" -n
rg "onclick\s*=\s*async" frontend-console/ --include "*.js" -n
rg "onchange\s*=\s*async" frontend-console/ --include "*.js" -n
rg "\.catch\(" frontend-console/views/ --include "*.js" -n
rg "data-action" frontend-console/ --include "*.js" -n | head -50

# 交互入口模式
rg "_bindEvents|_bindModalEvents|_show.*Form|_confirm|_submit|_save" frontend-console/ --include "*.js" -n
rg "root\.onclick\s*=" frontend-console/views/ --include "*.js" -n

# modal 系统分析
rg "showModal|showModalHtml|confirmAction" frontend-console/ --include "*.js" -n
```

---

## 非目标

- 本次未修改业务代码
- 本次未新增测试
- 本次未调整 API/schema/wire contract
