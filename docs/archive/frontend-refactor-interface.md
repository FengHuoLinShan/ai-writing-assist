# 前端写作台重构接口设计文档

> 本文档为 `views/writingView.js` 拆分与 `app.js` Smart Dedup 下沉的临时设计契约。重构完成后可归档到 `docs/archive/`。

## 1. 设计原则

1. **子模块不互相 import**：所有子模块通过 factory 接收依赖，所有协调通过 `writingView` orchestrator 完成。
2. **小接口、深实现**：每个子模块暴露 4-8 个公共方法，内部可自由组织。
3. **状态归属清晰**：
   - 跨子模块状态（如 `currentChapter`）由 orchestrator 持有并注入。
   - 子模块私有状态由子模块自己持有。
4. **事件显式回调**：子模块通过构造函数传入的 `onXxx` 回调与 orchestrator 通信，不直接操作全局状态。
5. **DOM 操作局部化**：每个子模块负责自己生成 HTML 和绑定自己生成 DOM 内的事件。
6. **全局变量最小化**：保留 `window.writingView`，子模块不暴露到 `window`。
7. **不允许全局回退**：子模块通过构造函数接收依赖（`state`、`api`、`modal`、`esc` 等），禁止 `|| globalThis.*` 形式的全局回退。

## 2. 目录与文件命名

```
frontend-console/
├── shared/
│   ├── smartDedup.js          # 新增：Smart Dedup 业务管理器
│   ├── confirmAsync.js        # 新增：异步二次确认封装
│   ├── writingToolsResult.js  # 新增：工具结果应用到 orchestrator
│   ├── sceneLocator.js        # 新增：光标/章节定位当前 Scene
│   └── prompt.js              # 新增：通用确认/输入弹窗（可选）
├── views/
│   ├── writingView.js         # 重写：orchestrator
│   └── writing/
│       ├── chapterTree.js
│       ├── editor.js
│       ├── versions.js
│       ├── publish.js
│       ├── deepImportRecovery.js
│       ├── autoExtraction.js
│       ├── conflictCheck.js
│       ├── scenePanel.js      # 场景驾驶舱 + 地图摘要
│       ├── outlineFloat.js
│       ├── focusMode.js
│       ├── tools.js           # 工具栏、导出、断章、AI 生成草稿
│       └── mobileQuickNote.js # 移动端速记（可合并到 tools.js）
└── tests/
    ├── shared/smartDedup.test.js
    └── writing/
        ├── chapterTree.test.js
        ├── editor.test.js
        ├── versions.test.js
        ├── publish.test.js
        ├── deepImportRecovery.test.js
        ├── autoExtraction.test.js
        ├── conflictCheck.test.js
        └── scenePanel.test.js
```

## 3. writingView Orchestrator 持有状态

以下状态仍由 `writingView` 持有，作为各子模块的共享上下文：

```javascript
const writingView = {
  _currentChapter: null,
  _chapterList: [],
  _chapters: {},
  _scenes: [],
  _loading: true,
  _chapterListLoadError: null,
  _focusMode: false,
  _forceDesktopMode: false,
  _bulkSelections: {},
  _showBulkActions: false,
  // 子模块实例
  _chapterTree: null,
  _editor: null,
  _versions: null,
  _publish: null,
  _deepImportRecovery: null,
  _autoExtraction: null,
  _conflictCheck: null,
  _scenePanel: null,
  _outlineFloat: null,
  _focusModeManager: null,
  _tools: null,
  _mobileQuickNote: null,
}
```

## 4. 子模块接口契约

### 4.1 `shared/smartDedup.js`

```javascript
export function createSmartDedupManager({ api, router, toast, modal, esc, onRenderActions, getCurrentProjectId })

// 返回对象：
{
  recoverWorkflow(projectId),           // 恢复项目下的 smart_dedup_scan 工作流
  startScan(),                          // 启动扫描（当前 projectId 由 getCurrentProjectId 提供）
  showProgress(),                       // 显示进度/建议弹窗
  handleAction(action),                 // 处理 "start-smart-dedup" / "show-smart-dedup-progress"
  renderActionButton(progressState),    // 返回顶部操作按钮 HTML
  dispose(),                            // 清理轮询
}
```

**说明**：

- `onRenderActions()` 回调在状态变化时触发，由 `app.js` 重新渲染顶部按钮。
- `progressState` 由调用方从 manager 内部读取，或通过 `getState()` 获取。
- 为了测试方便，可额外暴露 `getState()` 返回内部状态快照。

### 4.2 `views/writing/chapterTree.js`

```javascript
export function createChapterTree({ state, api, onSelect, onSceneSelect, onBulkChange, esc })

{
  async load(),                         // 加载章节列表和场景列表
  render(),                             // 返回左侧章节树 HTML
  bindEvents(container),                // 绑定章节树内事件
  clearSelection(),                     // 清空批量选择
  async newChapter(),                   // 创建新章节
  async deleteChapter(chapterIndex),    // 删除章节
  async runBulkAction(action),          // 执行批量操作
  dispose(),
  // orchestrator 专用状态同步方法
  _getChapterList(),
  _getLoadError(),
  _getChapterMap(),
  _getScenes(),
  _setCurrentChapter(index),
  _setCurrentSceneId(sceneId),
  _setChapters(map),
  _setScenes(scenes),
  _setChapterList(list),
  _setBulkSelections(selections),
  _setShowBulkActions(show),
}
```

**说明**：

- `load()` 内部调用 `api.writing.listChapters` 和 `api.outline.listScenesOrdered`。
- `onSelect(chapterIndex)` 当用户点击章节时调用。
- `onSceneSelect(sceneId)` 当用户点击 Scene 时调用（可能触发章节跳转）。
- `onBulkChange(scope)` 当批量选择变化时调用，由 orchestrator 决定是否显示批量工具条。
- 以 `_` 开头的方法仅供 orchestrator 同步状态，不属于对外公共 API。
- `deleteChapter` 使用 `shared/confirmAsync` 进行二次确认。

### 4.3 `views/writing/editor.js`

```javascript
export function createEditor({ state, api, toast, onWordcountUpdate, onSaveStatusChange, onSceneChange })

{
  async loadChapter(chapterIndex, options = {}), // options: { draftId, versionNumber, isReadonly, restoreSourceVersion }
  render(),                                      // 返回编辑器 HTML
  bindEvents(container),
  autosave(),                                    // 手动触发保存
  getContent(),                                  // 返回当前编辑器内容
  getTitle(),                                    // 返回当前标题
  getCurrentSceneId(),
  getCursorOffset(),
  getDraftId(),
  getVersionNumber(),
  getUpdatedAt(),
  getRestoreSourceVersion(),
  getDraftStatus(),
  isReadonly(),
  insertTextAtCursor(text),
  saveBackup(content, title),
  setReadonly(readonly),
  setPublishStatus(status),
  setState(patch),
  updateWordcount(),
  updateMeta(focusMode),
  saveStatusText(),
  aiContinue(),
  dispose(),
}
```

**说明**：

- 编辑器因 orchestrator 需要高频读取内部状态（内容、标题、版本、光标 Scene 等），实际公共方法多于 4-8 个。
- 这些 getter/setter/action 均围绕编辑器自身状态，不操作全局状态；未来如需进一步收紧，可考虑统一为 `getState()` / `setState()` / `dispatch(action)`。

- 编辑器内部管理 `_currentContent`、`_currentTitle`、`_currentDraftId`、`_currentVersionNumber`、`_lastSavedContent`、自动保存定时器等。
- `onWordcountUpdate(stats)` 回调统计信息 `{ chapterWords, todayWords, saveState }`。
- `onSaveStatusChange(text)` 回调保存状态文本变化。
- `onSceneChange(sceneId)` 当光标移动导致当前 Scene 变化时回调。

### 4.4 `views/writing/versions.js`

```javascript
export function createVersionManager({ state, api, toast, modal, esc, onSwitch })

{
  async load(chapterIndex),
  render(),                             // 返回版本选择器 HTML
  bindEvents(container),
  async switchVersion(draftId, versionNumber, isLatest),
  async restoreFromVersion(),
  async deleteVersion(),
  dispose(),
}
```

**说明**：

- `onSwitch({ draftId, versionNumber, isReadonly, restoreSourceVersion })` 当版本切换/恢复后回调，orchestrator 同步通知 editor。

### 4.5 `views/writing/publish.js`

```javascript
export function createPublishManager({ state, api, toast, modal, esc, onStatusChange, onPublished })

{
  async publish(content, title, chapterIndex, currentDraftId, currentScene),
  async retry(),
  renderBar(),                          // 返回发布进度条 HTML
  updateBar(container),
  dismissError(),
  dispose(),
}
```

**说明**：

- 发布前二次确认由 `writingView._confirmBeforePublish` 负责；`publishManager` 只负责提交和轮询。
- `publishManager` 不再暴露 `confirmBeforePublish`。

### 4.6 `views/writing/deepImportRecovery.js`

```javascript
export function createDeepImportRecovery({ state, api, toast, modal, esc, onPrompt, onStatusChange, onDone })

{
  async recover(),                      // 恢复并轮询项目下的 deep_import / auto_extraction 任务
  renderBar(),
  updateBar(container),
  renderRecoveryPrompt(),
  async resume(),
  async abandon(),
  async showAuditDetails(),
  dispose(),
}
```

**说明**：

- 同时处理 `deep_import` 和三种 `auto_extraction` 工作流的恢复与轮询。
- `onPrompt(progress)` 当需要显示恢复提示时回调，orchestrator 负责渲染到合适位置或弹窗。
- `onStatusChange(status)` 当进度更新时回调。

### 4.7 `views/writing/autoExtraction.js`

```javascript
export function createAutoExtraction({ state, api, toast, modal, esc, onTaskStarted })

{
  showForm(stage = "scenes"),           // 显示提取表单弹窗
  showDeepImportForm(),                 // 显示深度导入表单弹窗
  extractChapterCards(),                // 显示章节卡提取表单弹窗
  dispose(),
}
```

**说明**：

- `onTaskStarted({ taskId, workflowType, stage, label })` 任务提交成功后回调，orchestrator 将其交给 `deepImportRecovery` 接管轮询。

### 4.8 `views/writing/conflictCheck.js`

```javascript
export function createConflictCheck({ state, api, toast, modal, esc, onInsertText, onLocate, onOpenSource })

{
  async run(chapterIndex, getContentCallback), // getContentCallback 返回当前正文
  async refresh(chapterIndex),                 // 刷新检查条，显示该章节最新检查记录
  renderStrip(),
  updateStrip(container),
  bindEvents(container),
  dispose(),
}
```

**说明**：

- `getContentCallback` 由 orchestrator 提供，用于在检查前保存草稿。
- `refresh(chapterIndex)` 用于章节切换时快速刷新检查条，不触发新的后台检查；显式检查仍调用 `run()`。
- `onInsertText(text)` 当用户选择插入 AI 建议时回调，orchestrator 调用 editor.insertTextAtCursor。
- `onLocate(check, itemId)` / `onOpenSource(check, itemId)` 由 orchestrator 路由到编辑器、地图或大纲。

### 4.9 `views/writing/scenePanel.js`

```javascript
export function createScenePanel({ state, api, toast, esc, onOpenMap, onSwitchTab })

{
  async update(currentSceneId, currentChapter),
  render(),
  bindEvents(container),
  bindCockpitDrag(container),
  dispose(),
}
```

**说明**：

- 包含 Scene 驾驶舱渲染、当前 Scene 检测、地图摘要加载、Cockpit 拖拽排序。
- `onOpenMap(sceneId)` 当用户点击打开地图时回调。

### 4.10 `views/writing/outlineFloat.js`

```javascript
export function createOutlineFloat({ state, api, esc })

{
  async toggle(),
  close(),
  dispose(),
}
```

### 4.11 `views/writing/focusMode.js`

```javascript
export function createFocusModeManager({ state, onChange })

{
  renderToggle(),
  toggle(),
  switchDesktopMode(),
  isFocusMode(),
  dispose(),
}
```

**说明**：

- 加载作者偏好（每日目标、章节目标、默认专注模式）可在此模块或 `shared/authorPreferences.js` 中实现。
- 建议新增 `shared/authorPreferences.js` 提供 `loadAuthorPreferences(projectId)` 和 `saveAuthorPreferences(...)`，供 `focusMode.js` 和 `editor.js` 使用。

### 4.12 `views/writing/tools.js`

```javascript
export function createWritingTools({ state, api, toast, modal, esc, editor, onInsertText, onRefresh })

{
  renderToolsMenu(hasSelection),
  bindEvents(container),
  exportChapter(),
  async splitScene(splitPos, currentChapter, currentScene),
  async generateDraft(),
  dispose(),
}
```

### 4.13 `views/writing/mobileQuickNote.js`

```javascript
export function createMobileQuickNote({ state, api, toast, esc, onSaved })

{
  shouldRender(),
  render(),
  bindEvents(container),
  dispose(),
}
```

## 5. 事件/回调命名规范

子模块通过回调与 orchestrator 通信，回调名统一为 `on + 动词 + 名词`：

| 回调 | 触发场景 |
|------|----------|
| `onSelect(chapterIndex)` | 章节树选择章节 |
| `onSceneSelect(sceneId)` | 章节树选择 Scene |
| `onBulkChange(scope)` | 批量选择变化 |
| `onWordcountUpdate(stats)` | 编辑器字数统计更新 |
| `onSaveStatusChange(text)` | 保存状态文本变化 |
| `onSceneChange(sceneId)` | 光标所在 Scene 变化 |
| `onSwitch(versionInfo)` | 版本切换 |
| `onPublished()` | 发布完成 |
| `onStatusChange(status)` | 发布/深度导入状态变化 |
| `onPrompt(progress)` | 需要显示恢复提示 |
| `onTaskStarted(taskInfo)` | 自动提取任务提交 |
| `onInsertText(text)` | 冲突检查建议插入 |
| `onLocate(...)` | 定位冲突来源 |
| `onOpenMap(sceneId)` | 打开当前 Scene 地图 |
| `onChange(focusMode)` | 专注模式变化 |

## 6. writingView Orchestrator 伪代码

```javascript
const writingView = {
  async onEnter() {
    this._loading = true
    this._initSubModules()
    await this._chapterTree.load()
    this._chapterList = this._chapterTree.getChapterList()
    this._chapters = this._chapterTree.getChapterMap()
    this._scenes = this._chapterTree.getScenes()
    // 恢复上次编辑章节
    const saved = state.viewStates.writing?.projectId === state.currentProjectId ? state.viewStates.writing : null
    if (saved?.currentChapter) {
      await this._selectChapter(saved.currentChapter, saved)
    }
    await this._deepImportRecovery.recover()
    this._loading = false
  },

  async render() {
    if (this._loading) return LOADING_HTML
    if (this._chapterListLoadError) return ERROR_HTML
    if (this._chapterList.length === 0) return EMPTY_HTML
    return `
      <div class="writing-layout">
        <aside>${this._chapterTree.render()}</aside>
        <main>
          ${this._editor.render()}
          ${this._tools.renderToolsMenu()}
          ${this._publish.renderBar()}
          ${this._deepImportRecovery.renderBar()}
          ${this._conflictCheck.renderStrip()}
        </main>
        <aside>${this._scenePanel.render()}</aside>
      </div>
      ${this._outlineFloat.render()}
    `
  },

  _bindEvents() {
    this._chapterTree.bindEvents(container)
    this._editor.bindEvents(container)
    this._versions.bindEvents(container)
    this._tools.bindEvents(container)
    this._conflictCheck.bindEvents(container)
    this._scenePanel.bindEvents(container)
    this._scenePanel.bindCockpitDrag(container)
  },

  async _selectChapter(chapterIndex, options = {}) {
    await this._editor.loadChapter(chapterIndex, options)
    await this._versions.load(chapterIndex)
    await this._conflictCheck.refresh(chapterIndex)
    this._scenePanel.update(this._editor.getCurrentSceneId(), chapterIndex)
    this._currentChapter = chapterIndex
  },

  onLeave() {
    this._editor.dispose()
    this._publish.dispose()
    this._deepImportRecovery.dispose()
    this._conflictCheck.dispose()
    this._scenePanel.dispose()
    // ... 其他 dispose
  }
}
```

## 7. app.js 修改要点

1. 删除 `SMART_DEDUP_PAGE_SIZE` 常量和所有 `_smartDedup*` 字段/方法。
2. 在 `init()` 中创建 `this._smartDedup = createSmartDedupManager({ api, router, toast, modal, esc, onRenderActions: () => this._renderGlobalActions() })`。
3. 在 `init()` 中调用 `this._smartDedup.recoverWorkflow(state.currentProjectId)`。
4. `_renderGlobalActions()` 中调用 `this._smartDedup.renderActionButton()` 生成按钮。
5. `_bindGlobalActions()` 中调用 `this._smartDedup.handleAction(action)`。

## 8. worldView 地图子视图修改要点

1. 删除 `_renderMap()` 方法及其内部的 `setTimeout(() => router.navigate("map", null), 0)`。
2. 在 subnav 渲染中，将"地图"子视图改为直接链接到 `#workbench/:pid/map`：
   ```html
   <span class="subnav-item" data-action="nav-map">地图</span>
   ```
3. 在 `_bindEvents` / 事件处理中，点击"地图"时调用 `router.navigate("map", null)`。

## 9. 测试策略

1. **保持外部行为测试不变**：`tests/writingView.test.js` 中验证 orchestrator 行为的集成测试保留。
2. **拆分子模块测试**：从原测试中提取与各子模块相关的用例，放到 `tests/writing/*.test.js`。
3. **新增 Smart Dedup 测试**：覆盖建议归一化、高风险判断、主对象选择、应用 payload 构建。
4. **每个子模块提取后单独跑测试**：确保迁移过程中问题定位快速。

## 10. 并行执行顺序

1. **Phase 0（已完成）**：输出本接口文档。
2. **Phase 1（并行）**：
   - Agent A: `shared/smartDedup.js` + `app.js`
   - Agent B: `views/writing/chapterTree.js`
   - Agent C: `views/writing/editor.js`
   - Agent D: `views/writing/versions.js` + `views/writing/publish.js`
   - Agent E: `views/writing/deepImportRecovery.js` + `views/writing/autoExtraction.js`
   - Agent F: `views/writing/conflictCheck.js` + `views/writing/scenePanel.js` + `views/writing/outlineFloat.js` + `views/writing/focusMode.js` + `views/writing/tools.js` + `views/writing/mobileQuickNote.js`
   - Agent G: `views/worldView.js` 地图 hack 移除
3. **Phase 2（串行）**：Agent H 重写 `views/writingView.js` 为 orchestrator。
4. **Phase 3（并行）**：Agent I 拆分测试。
5. **Phase 4（父代理）**：全量验证。
