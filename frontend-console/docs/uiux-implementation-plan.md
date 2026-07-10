# NovelCraft UI/UX 详细优化实现方案

> **历史实施计划**：记录当时的 UI/UX 优化拆解，不是当前前端需求、路由或代码结构的权威来源。
> 判断当前实现以 `frontend-console/README.md`、`docs/modules/14_frontend.md`、测试和源码为准；
> 不因后续代码变化回写本计划正文。

---

## 目录

- [P0 全局：状态栏改造](#p0-全局状态栏改造)
- [P0 写作：编辑器沉浸化](#p0-写作编辑器沉浸化)
- [P0 写作：实时字数统计](#p0-写作实时字数统计)
- [P0 写作：右侧面板「写作副驾驶」](#p0-写作右侧面板写作副驾驶)
- [P1 写作：章节树简化](#p1-写作章节树简化)
- [P1 写作：AI 续写按钮前置](#p1-写作ai-续写按钮前置)
- [P1 项目：卡片字数与活跃状态](#p1-项目卡片字数与活跃状态)
- [P2 世界：卡片视图与头像](#p2-世界卡片视图与头像)
- [P2 大纲：写作页大纲浮窗](#p2-大纲写作页大纲浮窗)
- [P2 设置：参数预设包与作者偏好](#p2-设置参数预设包与作者偏好)
- [P3 全局：护眼/纸张模式](#p3-全局护眼纸张模式)
- [P3 全局：移动端快速记录](#p3-全局移动端快速记录)
- [附录：快速验证清单](#附录快速验证清单)

---

## P0 全局：状态栏改造

**目标**：将顶部状态栏从「系统管理面板」风格改为「创作仪表盘」风格，实时展示字数、保存状态、章节信息。

### 修改文件：index.html

**位置**：`#topbar`（第 17~35 行）

**当前**：
```html
<div class="topbar-center">
  <span id="topbar-project"></span>
  <span class="separator">&#183;</span>
  <span id="topbar-module">项目</span>
  <span id="topbar-submodule" class="topbar-submodule hidden"></span>
</div>
<div class="topbar-right">
  <span id="topbar-status-dot" class="status-indicator disconnected"></span>
  <span id="topbar-status" class="status-text">未连接</span>
  <div class="avatar">U</div>
</div>
```

**改为**：
```html
<div class="topbar-center">
  <span id="topbar-project"></span>
  <span class="separator">&#183;</span>
  <span id="topbar-chapter" class="topbar-chapter hidden"></span>
</div>
<div class="topbar-right">
  <!-- 后端连接状态仅在异常时显示 -->
  <span id="topbar-status-dot" class="status-indicator disconnected" title="后端连接状态"></span>
  <span id="topbar-status" class="status-text hidden">未连接</span>

  <!-- 字数仪表盘 -->
  <div id="topbar-wordcount" class="topbar-wordcount hidden">
    <span id="topbar-chapter-wc" title="本章字数">0</span>
    <span class="wc-separator">/</span>
    <span id="topbar-today-wc" title="今日字数">0</span>
    <span id="topbar-save-state" class="save-state" title="保存状态">&#9670;</span>
  </div>

  <div class="avatar">U</div>
</div>
```

### 修改文件：styles.css

**在 `#topbar` 样式后增加**（约第 240 行后）：

```css
.topbar-chapter {
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: 500;
}

.topbar-wordcount {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  background: var(--bg-active);
  padding: 2px 10px;
  border-radius: var(--radius-full);
  transition: all 0.2s ease;
}

.topbar-wordcount:hover {
  background: var(--bg-hover);
}

.wc-separator {
  color: var(--text-quaternary);
  margin: 0 2px;
}

.save-state {
  color: var(--success);
  font-size: 8px;
  margin-left: 4px;
  transition: color 0.2s ease;
}

.save-state.unsaved {
  color: var(--warning);
  animation: pulse-dot 1.5s ease-in-out infinite;
}

.save-state.saving {
  color: var(--accent);
  animation: pulse-dot 0.8s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* topbar-wordcount 只在写作视图显示，由 JS 控制 hidden 类 */
```

### 修改文件：app.js

**在 `_renderGlobalActions` 后增加**（约第 115 行后）：

```javascript
/**
 * 更新顶部状态栏字数仪表盘
 */
updateWordcountDashboard(chapterWc, todayWc, saveState) {
  const chapterEl = document.getElementById("topbar-chapter")
  const wcEl = document.getElementById("topbar-wordcount")
  const chapterWcEl = document.getElementById("topbar-chapter-wc")
  const todayWcEl = document.getElementById("topbar-today-wc")
  const saveStateEl = document.getElementById("topbar-save-state")

  if (!chapterEl || !wcEl) return

  // 只在 writing 视图且已选项目时显示
  if (state.currentView === "writing" && state.currentProjectId && this._currentChapter) {
    chapterEl.textContent = `第 ${this._currentChapter} 章`
    chapterEl.classList.remove("hidden")
    wcEl.classList.remove("hidden")
  } else {
    chapterEl.classList.add("hidden")
    wcEl.classList.add("hidden")
  }

  if (chapterWcEl) chapterWcEl.textContent = (chapterWc || 0).toLocaleString()
  if (todayWcEl) todayWcEl.textContent = (todayWc || 0).toLocaleString()
  if (saveStateEl) {
    saveStateEl.className = "save-state " + (saveState || "saved")
  }
},
```

**说明**：
- `app.js` 中暴露 `updateWordcountDashboard()` 供 `writingView.js` 调用。
- 写作视图时显示 `第 X 章 · 本章 3,847 字 / 今日 4,200 字`，hover 显示完整 tooltip（总字数、章节数）。
- `saveState` 支持 `"saved"`（绿色实心）、`"unsaved"`（橙色脉冲）、`"saving"`（蓝色脉冲）。
- 后端状态文字默认隐藏，只保留 dot，异常时 `status-text` 取消 `hidden` 并 toast 提示。

---

## P0 写作：编辑器沉浸化

**目标**：让编辑器从「代码 textarea」变成「专业写作区域」，支持专注模式。

### 修改文件：writingView.js

**1. 编辑器渲染 `_renderEditor` 中 textarea 部分**（约第 698~703 行）：

**当前**：
```javascript
<textarea id="writing-editor" style="
  width:100%;height:450px;background:var(--bg);color:var(--text);
  border:1px solid var(--border);border-radius:4px;padding:12px;
  font-family:var(--font-mono);font-size:13px;line-height:1.8;
  resize:vertical;
" placeholder="在此书写正文..." ${this._isReadonly ? 'readonly' : ''}>${this._currentContent ? esc(this._currentContent) : ''}</textarea>
```

**改为**：
```javascript
<textarea id="writing-editor" class="novel-editor ${this._focusMode ? 'novel-editor--focus' : ''}"
  style="width:100%;background:var(--bg);color:var(--text);
  border:1px solid var(--border);border-radius:8px;padding:16px 20px;
  font-family:var(--font-body);font-size:16px;line-height:1.8;
  resize:vertical;min-height:60vh;"
  placeholder="在此书写正文..." ${this._isReadonly ? 'readonly' : ''}>${this._currentContent ? esc(this._currentContent) : ''}</textarea>
```

**关键变更**：
- `font-family` 从 `var(--font-mono)` → `var(--font-body)`（思源宋体/Noto Serif SC）
- `font-size` 从 `13px` → `16px`
- `height:450px` → `min-height:60vh`（自适应，让编辑器吃满空间）
- `padding` 从 `12px` → `16px 20px`（更舒适的边距）
- 增加 `class="novel-editor"`，用于后续 CSS 和 JS 选择

**2. 在 `_renderEditor` 顶部增加专注模式按钮**（约第 670 行，在按钮区域）：

在 `writing-editor-buttons` 中增加：
```javascript
<button class="btn btn-sm" data-action="toggle-focus-mode" title="专注模式（隐藏两侧面板）">
  ${this._focusMode ? '退出专注' : '专注模式'}
</button>
```

**3. 在 `writingView` 对象中增加状态和方法**：

在 `writingView` 的私有状态区（约第 56 行）增加：
```javascript
_focusMode: false,
```

在事件绑定中增加：
```javascript
_bindEvents() {
  // ... 现有事件绑定 ...
  
  // 专注模式切换
  document.querySelector('[data-action="toggle-focus-mode"]')?.addEventListener('click', () => {
    this._toggleFocusMode()
  })
  
  // 编辑器输入时更新字数
  const editor = document.getElementById("writing-editor")
  if (editor) {
    editor.addEventListener('input', () => {
      this._updateWordcount()
      this._scheduleAutoSave()
    })
  }
}
```

**4. 增加专注模式切换方法**（在 writingView 中）：

```javascript
_toggleFocusMode() {
  this._focusMode = !this._focusMode
  const editor = document.getElementById("writing-editor")
  const tree = document.getElementById("writing-tree-container")
  const panel = document.getElementById("writing-panel-container")
  const topbar = document.getElementById("topbar")
  const sidebar = document.getElementById("sidebar")

  if (this._focusMode) {
    editor?.classList.add("novel-editor--focus")
    tree?.classList.add("focus-hidden")
    panel?.classList.add("focus-hidden")
    topbar?.classList.add("focus-hidden")
    sidebar?.classList.add("focus-hidden")
    document.body.classList.add("focus-mode-active")
  } else {
    editor?.classList.remove("novel-editor--focus")
    tree?.classList.remove("focus-hidden")
    panel?.classList.remove("focus-hidden")
    topbar?.classList.remove("focus-hidden")
    sidebar?.classList.remove("focus-hidden")
    document.body.classList.remove("focus-mode-active")
  }
  
  // 重新聚焦编辑器
  editor?.focus()
}
```

### 修改文件：styles.css

**在编辑器相关样式后增加**（约第 880 行后）：

```css
/* ===== 写作编辑器沉浸化 ===== */
.novel-editor {
  transition: all 0.3s ease;
  box-shadow: inset 0 1px 3px rgba(0,0,0,0.04);
}

.novel-editor:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-glow), inset 0 1px 3px rgba(0,0,0,0.04);
  outline: none;
}

/* 专注模式：编辑器全屏感 */
.focus-mode-active #workspace {
  margin-left: 0;
  margin-right: 0;
}

.focus-mode-active #workspace-header {
  display: none;
}

.focus-hidden {
  display: none !important;
}

.novel-editor--focus {
  min-height: 85vh !important;
  max-width: 720px;
  margin: 0 auto;
  background: var(--bg-panel) !important;
  border: 1px solid var(--border) !important;
  box-shadow: 0 4px 24px rgba(0,0,0,0.06) !important;
  font-size: 18px !important;
  line-height: 1.8 !important;
  padding: 32px 40px !important;
}

/* 专注模式时，底部字数条保留 */
.focus-mode-active .writing-wordcount-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 100;
  background: var(--bg-panel);
  border-top: 1px solid var(--border);
}

/* 段落视觉呼吸 */
.novel-editor p {
  margin-bottom: 1.2em;
}

/* 纸张模式（由 JS 切换 body class） */
[data-theme="paper"] .novel-editor,
[data-theme="paper"] .novel-editor--focus {
  background: #fdfcf8 !important;
  color: #2c2c2c !important;
  border-color: #e5e0d5 !important;
}
```

### 修改文件：styles.css（字体栈确保中文优先）

**当前 `--font-body`**（约第 44 行）：
```css
--font-body: "Noto Serif SC", "Source Han Serif SC", "Georgia", "SimSun", serif;
```

**改为**：
```css
--font-body: "Noto Serif SC", "Source Han Serif SC", "PingFang SC", "Microsoft YaHei", "Georgia", "SimSun", serif;
```

**说明**：确保 Mac（PingFang）和 Windows（Microsoft YaHei）用户都能获得良好的中文显示，宋体作为 fallback。

---

## P0 写作：实时字数统计

**目标**：在编辑器底部增加固定字数条，显示本章字数、段落数、阅读时间、今日目标进度。

### 修改文件：writingView.js

**1. 在 `_renderEditor` 返回的 html 末尾增加字数条**（约第 713 行，在 `html += '</div>'` 前）：

```javascript
// 字数统计条（在编辑器下方）
html += `
  <div class="writing-wordcount-bar" id="writing-wordcount-bar">
    <div class="wc-bar-left">
      <span id="wc-chapter">0</span> 字
      <span class="wc-divider">|</span>
      <span id="wc-paragraphs">0</span> 段落
      <span class="wc-divider">|</span>
      预计阅读 <span id="wc-readtime">0</span> 分钟
    </div>
    <div class="wc-bar-right">
      <div class="wc-daily-goal">
        <span class="wc-goal-label">今日</span>
        <div class="wc-goal-progress">
          <div class="wc-goal-fill" id="wc-goal-fill" style="width:0%"></div>
        </div>
        <span id="wc-daily">0 / 4000</span>
      </div>
    </div>
  </div>
`
```

**2. 在 `writingView` 中增加字数统计方法**：

```javascript
_updateWordcount() {
  const editor = document.getElementById("writing-editor")
  if (!editor) return

  const text = editor.value || ""
  const chars = text.length
  // 中文字数统计：按实际字符数（网文习惯）
  const paragraphs = text.split(/
{2,}/).filter(p => p.trim()).length
  const readTime = Math.max(1, Math.ceil(chars / 300)) // 300字/分钟

  // 更新底部字数条
  const chapterWcEl = document.getElementById("wc-chapter")
  const paragraphsEl = document.getElementById("wc-paragraphs")
  const readTimeEl = document.getElementById("wc-readtime")
  if (chapterWcEl) chapterWcEl.textContent = chars.toLocaleString()
  if (paragraphsEl) paragraphsEl.textContent = paragraphs
  if (readTimeEl) readTimeEl.textContent = readTime

  // 更新顶部状态栏
  const dailyWc = this._getDailyWordcount() + chars
  App.updateWordcountDashboard(chars, dailyWc, this._saveStatusText() === "未保存" ? "unsaved" : "saved")

  // 更新今日目标进度
  const dailyGoal = this._getDailyGoal()
  const dailyEl = document.getElementById("wc-daily")
  const fillEl = document.getElementById("wc-goal-fill")
  if (dailyEl) dailyEl.textContent = `${dailyWc.toLocaleString()} / ${dailyGoal.toLocaleString()}`
  if (fillEl) fillEl.style.width = Math.min(100, (dailyWc / dailyGoal) * 100) + "%"

  // 更新标题栏未保存标记
  const titleEl = document.getElementById("writing-chapter-title")
  if (titleEl && this._saveStatusText() === "未保存") {
    if (!titleEl.textContent.includes("*")) {
      titleEl.textContent = titleEl.textContent + " *"
    }
  }
},

_getDailyWordcount() {
  // 从 localStorage 读取今日已统计字数（基于版本 diff 或累计）
  try {
    const key = `novel_daily_wc_${new Date().toISOString().slice(0,10)}_${state.currentProjectId || "global"}`
    const saved = localStorage.getItem(key)
    return saved ? parseInt(saved, 10) : 0
  } catch { return 0 }
},

_getDailyGoal() {
  // 从作者偏好设置读取，默认 4000
  try {
    const goal = localStorage.getItem("novel_daily_goal")
    return goal ? parseInt(goal, 10) : 4000
  } catch { return 4000 }
},
```

**3. 在 `_saveStatusText` 中增加「未保存」标记清理**：

```javascript
_saveStatusText() {
  if (this._autoSaving) return "保存中..."
  if (this._isReadonly || this._currentChapter === null) return ""
  const editor = typeof document !== "undefined" ? document.getElementById("writing-editor") : null
  const currentContent = editor ? editor.value : this._currentContent
  if (currentContent !== undefined && currentContent !== this._lastSavedContent) {
    return "未保存"
  }
  // 保存成功，清理标题栏星号
  const titleEl = document.getElementById("writing-chapter-title")
  if (titleEl && titleEl.textContent.includes("*")) {
    titleEl.textContent = titleEl.textContent.replace(" *", "")
  }
  return this._lastSavedContent !== null ? "已保存" : ""
},
```

### 修改文件：styles.css

**增加字数条样式**（约第 1080 行后）：

```css
/* ===== 写作字数统计条 ===== */
.writing-wordcount-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  margin-top: 8px;
  border-top: 1px solid var(--border);
  font-size: 12px;
  color: var(--text-secondary);
  font-family: var(--font-mono);
  user-select: none;
}

.wc-bar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.wc-divider {
  color: var(--text-quaternary);
}

.wc-bar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.wc-daily-goal {
  display: flex;
  align-items: center;
  gap: 8px;
}

.wc-goal-label {
  color: var(--text-tertiary);
}

.wc-goal-progress {
  width: 80px;
  height: 4px;
  background: var(--bg-active);
  border-radius: 2px;
  overflow: hidden;
}

.wc-goal-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
  transition: width 0.3s ease;
}

/* 字数达到里程碑时高亮 */
.wc-milestone {
  color: var(--success);
  font-weight: 600;
}
```

---

## P0 写作：右侧面板「写作副驾驶」

**目标**：将右侧 Scene Cockpit 从折叠 details 面板改为 Tab 化的「写作参考面板」，集成人物、地点、设定、地图四个 Tab。

### 修改文件：sceneCockpitPanel.js

**目标文件**：`views/sceneCockpitPanel.js`

**当前**：`renderSceneCockpitPanel` 返回一个 `scene-cockpit` 卡片，内部用 `details/summary` 折叠模块。

**改为 Tab 结构**：

```javascript
export function renderSceneCockpitPanel({ projectId, scene, mapSummaryHtml, compact }) {
  if (!projectId) {
    return `<div class="scene-cockpit"><div class="scene-cockpit__title">请先选择项目</div></div>`
  }

  const tabs = [
    { id: "people", label: "人物", icon: "&#9786;" },
    { id: "place", label: "地点", icon: "&#127758;" },
    { id: "lore", label: "设定", icon: "&#128218;" },
    { id: "map", label: "地图", icon: "&#128506;" },
  ]

  // 提取 scene 中的人物/地点/事件（基于现有数据）
  const people = scene?.scene_characters || []
  const location = scene?.location_id || scene?.primary_location
  const events = scene?.scene_events || []
  const lore = scene?.lore_refs || []

  let html = `
    <div class="scene-cockpit">
      <div class="scene-cockpit__title">
        <span>Scene 参考</span>
        <span class="scene-cockpit-meta">${esc(scene?.title || "未关联")}</span>
      </div>
      <div class="cockpit-tabs">
        ${tabs.map(t => `
          <button class="cockpit-tab ${t.id === 'people' ? 'active' : ''}" data-tab="${t.id}">
            <span class="tab-icon">${t.icon}</span>
            <span class="tab-label">${t.label}</span>
          </button>
        `).join('')}
      </div>
      <div class="cockpit-body">
        <!-- 人物 Tab -->
        <div class="cockpit-panel ${'people' === 'people' ? '' : 'hidden'}" data-panel="people">
          ${people.length === 0 ? '<p class="cockpit-empty">暂无出场人物</p>' : `
            <div class="cockpit-people-list">
              ${people.map(p => `
                <div class="cockpit-person-card" data-person-id="${esc(p.character_id || p.id || '')}">
                  <div class="person-avatar" style="background:${_avatarColor(p.name)}">${(p.name || '?')[0]}</div>
                  <div class="person-info">
                    <div class="person-name">${esc(p.name || '未命名')}</div>
                    <div class="person-status">${esc(p.status || '无状态')}</div>
                  </div>
                  <button class="btn btn-sm btn-insert" data-action="insert-person" data-name="${esc(p.name || '')}">插入</button>
                </div>
              `).join('')}
            </div>
          `}
        </div>
        <!-- 地点 Tab -->
        <div class="cockpit-panel hidden" data-panel="place">
          ${location ? `
            <div class="cockpit-place-card">
              <div class="place-name">${esc(typeof location === 'string' ? location : location.name || '未知地点')}</div>
              <div class="place-desc">${esc(typeof location === 'object' ? (location.description || '') : '')}</div>
            </div>
          ` : '<p class="cockpit-empty">暂无地点信息</p>'}
        </div>
        <!-- 设定 Tab -->
        <div class="cockpit-panel hidden" data-panel="lore">
          ${lore.length === 0 ? '<p class="cockpit-empty">暂无关联设定</p>' : `
            <div class="cockpit-lore-list">
              ${lore.map(l => `
                <div class="cockpit-lore-item">
                  <div class="lore-title">${esc(l.title || l.name || '设定')}</div>
                  <div class="lore-desc">${esc(l.summary || l.description || '')}</div>
                </div>
              `).join('')}
            </div>
          `}
        </div>
        <!-- 地图 Tab -->
        <div class="cockpit-panel hidden" data-panel="map">
          ${mapSummaryHtml || '<p class="cockpit-empty">暂无地图摘要</p>'}
        </div>
      </div>
    </div>
  `
  return html
}

function _avatarColor(name) {
  const colors = ["#6366F1", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899"]
  let hash = 0
  for (let i = 0; i < (name || "").length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash)
  return colors[Math.abs(hash) % colors.length]
}
```

### 修改文件：writingView.js

**在 `_bindEvents` 中增加 Tab 切换和插入按钮**：

```javascript
_bindEvents() {
  // ... 现有绑定 ...
  
  // 右侧 cockpit Tab 切换
  document.querySelectorAll('.cockpit-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.tab
      document.querySelectorAll('.cockpit-tab').forEach(t => t.classList.remove('active'))
      tab.classList.add('active')
      document.querySelectorAll('.cockpit-panel').forEach(p => {
        p.classList.toggle('hidden', p.dataset.panel !== target)
      })
    })
  })
  
  // 人物「插入」按钮
  document.querySelectorAll('[data-action="insert-person"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const name = btn.dataset.name
      const editor = document.getElementById("writing-editor")
      if (editor && name) {
        const start = editor.selectionStart
        const end = editor.selectionEnd
        const text = editor.value
        editor.value = text.slice(0, start) + name + text.slice(end)
        editor.selectionStart = editor.selectionEnd = start + name.length
        editor.focus()
      }
    })
  })
}
```

### 修改文件：styles.css

**增加 Cockpit Tab 样式**（约第 1240 行后）：

```css
/* ===== Cockpit Tab 写作参考面板 ===== */
.cockpit-tabs {
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--border);
  margin: 0 -5px 8px -5px;
  padding: 0 5px;
}

.cockpit-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 6px 4px;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  font-size: 12px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
  white-space: nowrap;
}

.cockpit-tab:hover {
  color: var(--text-secondary);
  background: var(--bg-hover);
}

.cockpit-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.tab-icon {
  font-size: 14px;
  line-height: 1;
}

.tab-label {
  font-size: 11px;
}

.cockpit-panel {
  animation: fadeIn 0.15s ease;
}

.cockpit-panel.hidden {
  display: none;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(2px); }
  to { opacity: 1; transform: translateY(0); }
}

.cockpit-empty {
  color: var(--text-tertiary);
  font-size: 12px;
  text-align: center;
  padding: 16px 0;
}

/* 人物卡片 */
.cockpit-people-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cockpit-person-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--bg-hover);
  transition: background 0.15s;
}

.cockpit-person-card:hover {
  background: var(--bg-active);
}

.person-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

.person-info {
  flex: 1;
  min-width: 0;
}

.person-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-body);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.person-status {
  font-size: 11px;
  color: var(--text-tertiary);
}

.btn-insert {
  padding: 2px 8px;
  font-size: 11px;
  opacity: 0;
  transition: opacity 0.15s;
}

.cockpit-person-card:hover .btn-insert {
  opacity: 1;
}

/* 地点卡片 */
.cockpit-place-card {
  padding: 8px;
  background: var(--bg-hover);
  border-radius: 6px;
}

.place-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.place-desc {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}

/* Lore 项 */
.cockpit-lore-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cockpit-lore-item {
  padding: 6px 8px;
  border-left: 2px solid var(--accent-soft);
  background: var(--bg-hover);
  border-radius: 0 6px 6px 0;
}

.lore-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-body);
}

.lore-desc {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-top: 2px;
  line-height: 1.4;
}
```

---

## P1 写作：章节树简化

**目标**：去掉日常写作不需要的复选框和批量操作，增加字数、状态、快速切换。

### 修改文件：writingView.js

**1. `_renderSceneTree` 中去掉复选框和批量工具栏**（约第 578 行开始）：

将：
```javascript
<div style="display:flex;justify-content:space-between;align-items:center;">
  <span style="font-size:13px;font-weight:bold;">Scene 树</span>
  <button class="btn btn-sm" data-action="new-chapter" style="font-size:11px;">+ 新建章</button>
</div>
${this._renderChapterBulkToolbar()}
```

改为：
```javascript
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
  <span style="font-size:13px;font-weight:bold;">章节</span>
  <div style="display:flex;gap:4px;">
    <button class="btn btn-sm" data-action="prev-chapter" title="上一章" style="font-size:11px;">&#8592;</button>
    <button class="btn btn-sm" data-action="next-chapter" title="下一章" style="font-size:11px;">&#8594;</button>
    <button class="btn btn-sm" data-action="new-chapter" style="font-size:11px;">+ 新建</button>
  </div>
</div>
```

**2. `_renderChapterRow` 中去掉复选框和删除按钮**（约第 634 行）：

将：
```javascript
<div style="display:flex;align-items:center;padding:4px 6px;border-left:3px solid ${isActive ? 'var(--accent)' : 'transparent'};margin-bottom:1px;background:${isActive ? 'var(--hover-bg)' : 'transparent'};border-radius:0 4px 4px 0;}">
  ${renderSelectionCell(this, "writing-chapters", String(idx), `选择第 ${idx} 章`)}
  <div class="clickable" data-action="select-chapter" data-chapter="${idx}" style="flex:1;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
    第 ${idx} 章
    ${this._chapters[idx] && this._chapters[idx].title ? `<span style="color:var(--text-dim);font-size:10px;margin-left:4px;">${esc(this._chapters[idx].title)}</span>` : ''}
  </div>
  <button class="btn btn-sm" data-action="delete-chapter" data-chapter="${idx}" title="删除整章" style="font-size:10px;color:var(--danger);margin-left:2px;">✕</button>
</div>
```

改为：
```javascript
<div class="chapter-row ${isActive ? 'chapter-row--active' : ''}" data-action="select-chapter" data-chapter="${idx}">
  <div class="chapter-row__status">
    <span class="chapter-status chapter-status--${this._chapterStatus(idx)}" title="${this._chapterStatusLabel(idx)}"></span>
  </div>
  <div class="chapter-row__info">
    <div class="chapter-row__title">
      <span class="chapter-number">第 ${idx} 章</span>
      ${this._chapters[idx] && this._chapters[idx].title ? `<span class="chapter-title-text">${esc(this._chapters[idx].title)}</span>` : ''}
    </div>
    <div class="chapter-row__meta">
      <span class="chapter-wc">${this._chapterWordcount(idx)} 字</span>
    </div>
  </div>
</div>
```

**3. 在 writingView 中增加辅助方法**：

```javascript
_chapterStatus(idx) {
  if (!this._chapters[idx]) return "empty"
  // 简化为：empty / draft / published
  if (this._chapters[idx].draftCount > 0) return "draft"
  return "empty"
},

_chapterStatusLabel(idx) {
  const s = this._chapterStatus(idx)
  return { empty: "未写", draft: "草稿", published: "已发布" }[s] || s
},

_chapterWordcount(idx) {
  // 如果当前选中的章节，用编辑器实时字数
  if (idx === this._currentChapter && this._currentContent) {
    return this._currentContent.length.toLocaleString()
  }
  // 否则从 chapters 数据中取（后端可返回字数统计）
  return (this._chapters[idx]?.wordcount || 0).toLocaleString()
},
```

**4. 在 `_bindEvents` 中增加上下章切换**：

```javascript
"prev-chapter": () => this._switchChapter(-1),
"next-chapter": () => this._switchChapter(1),

_switchChapter(delta) {
  if (!this._currentChapter || this._chapterList.length === 0) return
  const currentIndex = this._chapterList.indexOf(this._currentChapter)
  const nextIndex = currentIndex + delta
  if (nextIndex >= 0 && nextIndex < this._chapterList.length) {
    const nextChapter = this._chapterList[nextIndex]
    this._selectChapter(nextChapter)
  }
},
```

### 修改文件：styles.css

**增加章节行样式**（约第 1080 行后）：

```css
/* ===== 简化章节树 ===== */
.chapter-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  margin-bottom: 2px;
  border-radius: 0 6px 6px 0;
  border-left: 3px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
}

.chapter-row:hover {
  background: var(--bg-hover);
}

.chapter-row--active {
  background: var(--accent-soft) !important;
  border-left-color: var(--accent) !important;
}

.chapter-row__status {
  flex-shrink: 0;
}

.chapter-status {
  display: block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-quaternary);
}

.chapter-status--empty { background: var(--text-quaternary); }
.chapter-status--draft { background: var(--warning); }
.chapter-status--published { background: var(--success); }

.chapter-row__info {
  flex: 1;
  min-width: 0;
}

.chapter-row__title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-body);
}

.chapter-number {
  font-weight: 500;
  white-space: nowrap;
}

.chapter-title-text {
  color: var(--text-tertiary);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chapter-row__meta {
  font-size: 10px;
  color: var(--text-quaternary);
  margin-top: 2px;
}
```

---

## P1 写作：AI 续写按钮前置

**目标**：将「AI 生成草稿」从 dropdown 中移出，变为编辑器工具栏上的显式按钮，并在点击后以「建议」形式展示。

### 修改文件：writingView.js

**1. `_renderEditor` 中按钮区域增加显式续写按钮**（约第 680 行）：

将：
```javascript
${this._renderEditorToolsMenu(hasSelection)}
```

改为：
```javascript
<button class="btn btn-sm btn-ghost" data-action="ai-continue" ${hasSelection && !this._isReadonly ? '' : 'disabled'} title="基于上下文续写">
  ✨ 续写
</button>
${this._renderEditorToolsMenu(hasSelection)}
```

**2. 在 `_bindEvents` 中增加续写处理**：

```javascript
"ai-continue": () => this._aiContinue(),

async _aiContinue() {
  if (!this._currentChapter || this._isReadonly) return
  const editor = document.getElementById("writing-editor")
  if (!editor) return
  
  const cursorPos = editor.selectionStart
  const textBefore = editor.value.slice(0, cursorPos)
  const textAfter = editor.value.slice(cursorPos)
  
  // 显示续写建议区域（在编辑器下方插入临时区域）
  this._showAiSuggestionPanel("续写中...")
  
  try {
    const result = await api.generate.continue({
      novel_id: state.currentProjectId,
      chapter_index: this._currentChapter,
      context: textBefore.slice(-500), // 取前500字作为上下文
      cursor_position: cursorPos,
    })
    
    this._showAiSuggestionPanel(result.text || "续写完成", {
      onAccept: (text) => {
        editor.value = textBefore + text + textAfter
        editor.selectionStart = editor.selectionEnd = cursorPos + text.length
        editor.focus()
        this._scheduleAutoSave()
        this._hideAiSuggestionPanel()
      },
      onReject: () => {
        this._hideAiSuggestionPanel()
      },
      onRetry: () => this._aiContinue(),
    })
  } catch (err) {
    toast(`续写失败：${err.message}`, "error")
    this._hideAiSuggestionPanel()
  }
},

_showAiSuggestionPanel(content, actions = null) {
  let panel = document.getElementById("ai-suggestion-panel")
  if (!panel) {
    panel = document.createElement("div")
    panel.id = "ai-suggestion-panel"
    panel.className = "ai-suggestion-panel"
    document.getElementById("writing-editor-container")?.appendChild(panel)
  }
  
  panel.classList.remove("hidden")
  if (!actions) {
    panel.innerHTML = `<div class="ai-suggestion-loading">${content}</div>`
    return
  }
  
  panel.innerHTML = `
    <div class="ai-suggestion-header">
      <span class="ai-suggestion-label">✨ AI 续写建议</span>
      <div class="ai-suggestion-actions">
        <button class="btn btn-sm btn-primary" data-action="accept-suggestion">接受</button>
        <button class="btn btn-sm" data-action="retry-suggestion">重新生成</button>
        <button class="btn btn-sm btn-text" data-action="reject-suggestion">忽略</button>
      </div>
    </div>
    <div class="ai-suggestion-content">${esc(content)}</div>
  `
  
  panel.querySelector('[data-action="accept-suggestion"]')?.addEventListener('click', () => actions.onAccept(content))
  panel.querySelector('[data-action="reject-suggestion"]')?.addEventListener('click', () => actions.onReject())
  panel.querySelector('[data-action="retry-suggestion"]')?.addEventListener('click', () => actions.onRetry())
},

_hideAiSuggestionPanel() {
  const panel = document.getElementById("ai-suggestion-panel")
  if (panel) panel.classList.add("hidden")
},
```

### 修改文件：styles.css

**增加续写建议面板样式**（约第 1080 行后）：

```css
/* ===== AI 续写建议面板 ===== */
.ai-suggestion-panel {
  margin-top: 8px;
  border: 1px solid var(--accent-soft);
  border-radius: 8px;
  background: var(--bg-panel);
  padding: 12px 16px;
  animation: slideIn 0.2s ease-out;
}

.ai-suggestion-panel.hidden {
  display: none;
}

.ai-suggestion-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  gap: 8px;
  flex-wrap: wrap;
}

.ai-suggestion-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
}

.ai-suggestion-actions {
  display: flex;
  gap: 6px;
}

.ai-suggestion-content {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-body);
  font-family: var(--font-body);
  background: var(--bg-hover);
  padding: 10px 12px;
  border-radius: 6px;
  border-left: 3px solid var(--accent);
}

.ai-suggestion-loading {
  color: var(--text-tertiary);
  font-size: 13px;
  text-align: center;
  padding: 12px;
}
```

---

## P1 项目：卡片字数与活跃状态

**目标**：项目卡片显示总字数、章节数、今日字数、最近活跃时间，支持「最近活跃」排序和「继续写作」按钮。

### 修改文件：projectView.js

**1. 在 `onEnter` 中加载项目统计**：

在 `onEnter` 中（约第 209 行），在 `api.projects.list()` 后增加：

```javascript
async onEnter() {
  try {
    const data = await api.projects.list()
    state.projects = data.items || data || []
    
    // 加载每个项目的字数统计（如果后端支持，否则客户端估算）
    for (const p of state.projects) {
      try {
        const stats = await api.projects.getStats(p.id)
        p._stats = stats || { total_words: 0, chapter_count: 0, last_written_at: null }
      } catch {
        p._stats = { total_words: 0, chapter_count: 0, last_written_at: null }
      }
    }
    
    // 默认按最近活跃排序（替代原来的按创建时间）
    state.projects.sort((a, b) => {
      const ta = new Date(a._stats?.last_written_at || a.updated_at || a.created_at)
      const tb = new Date(b._stats?.last_written_at || b.updated_at || b.created_at)
      return tb - ta
    })
    
    if (state.currentProjectId) { ... }
  } catch { ... }
}
```

**2. 修改卡片渲染**（约第 70~92 行）：

将卡片内信息区改为：
```javascript
<div class="project-title">${esc(p.title || p.name || "未命名项目")}</div>
<div class="project-tags">
  ${p.genre ? `<span class="pill">${esc(p.genre)}</span>` : ""}
  ${p.current_stage ? `<span class="pill">${esc(this._stageLabel(p.current_stage))}</span>` : ""}
</div>
<div class="project-desc">${esc(p.tone || p.description || "暂无描述")}</div>
<div class="project-stats">
  <div class="stat-item">
    <span class="stat-value">${(p._stats?.total_words || 0).toLocaleString()}</span>
    <span class="stat-label">字</span>
  </div>
  <div class="stat-item">
    <span class="stat-value">${p._stats?.chapter_count || 0}</span>
    <span class="stat-label">章</span>
  </div>
  <div class="stat-item">
    <span class="stat-value">${this._formatRelativeTime(p._stats?.last_written_at || p.updated_at)}</span>
    <span class="stat-label">活跃</span>
  </div>
</div>
<div class="project-actions" style="margin-top:12px;display:flex;gap:8px;">
  <button class="btn btn-primary btn-sm" data-action="continue-writing" data-id="${esc(p.id)}">继续写作</button>
  <button class="btn btn-sm btn-ghost" data-action="edit-project" data-id="${esc(p.id)}">编辑</button>
  <button class="btn btn-sm btn-danger" data-action="delete-project" data-id="${esc(p.id)}">删除</button>
</div>
```

**3. 增加辅助方法**：

```javascript
_formatRelativeTime(isoStr) {
  if (!isoStr) return "从未"
  const d = new Date(isoStr)
  const now = new Date()
  const diff = now - d
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)
  if (minutes < 1) return "刚刚"
  if (minutes < 60) return `${minutes}分钟前`
  if (hours < 24) return `${hours}小时前`
  if (days < 7) return `${days}天前`
  return d.toLocaleDateString("zh-CN")
},
```

**4. 在事件绑定中增加「继续写作」**：

```javascript
"continue-writing": (_e, _t, ctx) => {
  if (ctx.id) {
    const project = state.projects.find(p => p.id === ctx.id)
    if (project) {
      state.currentProjectId = ctx.id
      state.currentProject = project
      // 尝试恢复到最后编辑的章节
      const lastChapter = project._stats?.last_chapter_index || 1
      router.navigate("writing")
      // 写作视图加载后自动选中最后章节
      setTimeout(() => {
        writingView._selectChapter(lastChapter)
      }, 300)
    }
  }
},
```

### 修改文件：styles.css

**增加项目统计样式**（约第 2310 行后）：

```css
/* ===== 项目卡片统计 ===== */
.project-stats {
  display: flex;
  gap: 16px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--bg-active);
}

.stat-item {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.stat-value {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  font-family: var(--font-mono);
}

.stat-label {
  font-size: 11px;
  color: var(--text-tertiary);
}
```

---

## P2 世界：卡片视图与头像

**目标**：对象库增加卡片视图切换，人物显示头像色块，支持按类型分组。

### 修改文件：worldView.js

**1. 在 `worldView` 状态区增加视图模式**（约第 58 行）：

```javascript
_viewMode: "table", // "table" | "card"
```

**2. 在 `_renderEntityList` 中增加视图切换按钮**（约第 562 行）：

在新建按钮旁边增加：
```javascript
<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;justify-content:center;">
  <button class="btn btn-primary btn-sm" data-action="new" id="btn-new-entity">新建对象</button>
  <button class="btn btn-sm ${this._viewMode === 'card' ? 'btn-primary' : ''}" data-action="toggle-view-mode" title="切换视图">
    ${this._viewMode === 'card' ? '&#9776; 列表' : '&#9638; 卡片'}
  </button>
</div>
```

**3. 在渲染表格处增加视图分支**（约第 705 行）：

```javascript
if (this._viewMode === "card") {
  html += this._renderEntityCards(entities, { showNewBadge })
} else {
  html += this._renderEntityTable(entities, { showNewBadge })
}
```

**4. 增加卡片渲染方法**：

```javascript
_renderEntityCards(entities, { showNewBadge }) {
  const typeColors = {
    character: "#6366F1", location: "#10B981", faction: "#F59E0B",
    item: "#8B5CF6", event: "#EF4444", rule: "#64748B",
    power_system: "#EC4899", secret: "#1E293B", legend: "#14B8A6", resource: "#D97706"
  }
  
  const typeLabels = Object.fromEntries(this._entityTypes.map(t => [t.value, t.label]))
  
  let html = '<div class="entity-card-grid">'
  for (const e of entities) {
    const color = typeColors[e.entity_type] || "#6366F1"
    const isCharacter = e.entity_type === "character"
    html += `
      <div class="entity-card" data-id="${esc(this._entityId(e))}">
        <div class="entity-card__header">
          <div class="entity-avatar" style="background:${color}">
            ${isCharacter ? (e.name || '?')[0] : _typeIcon(e.entity_type)}
          </div>
          <div class="entity-card__meta">
            <span class="entity-type-badge" style="color:${color}">${esc(typeLabels[e.entity_type] || e.entity_type)}</span>
            <span class="entity-status-badge badge badge-${e.status || 'canonical'}">${esc({canonical:'正史',draft:'草稿',candidate:'候选',deprecated:'废弃',merged:'已合并'}[e.status] || e.status)}</span>
          </div>
        </div>
        <div class="entity-card__name">${esc(e.name)}${showNewBadge ? ' <span class="badge badge-new">新</span>' : ''}</div>
        <div class="entity-card__summary">${esc(e.summary || e.public_info || "暂无描述")}</div>
        <div class="entity-card__actions">
          <button class="btn btn-sm btn-primary" data-action="edit-entity" data-id="${esc(this._entityId(e))}">编辑</button>
          <button class="btn btn-sm" data-action="open-entity-map" data-id="${esc(this._entityId(e))}">地图</button>
        </div>
      </div>
    `
  }
  html += '</div>'
  return html
},
```

**5. 增加事件绑定**：

```javascript
"toggle-view-mode": () => {
  this._viewMode = this._viewMode === "table" ? "card" : "table"
  router.renderCurrentView()
},
```

### 修改文件：styles.css

**增加卡片视图样式**（约第 1400 行后）：

```css
/* ===== 世界对象卡片视图 ===== */
.entity-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.entity-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
  transition: all 0.2s ease;
  cursor: pointer;
}

.entity-card:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--accent);
  transform: translateY(-1px);
}

.entity-card__header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.entity-avatar {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}

.entity-card__meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.entity-type-badge {
  font-size: 11px;
  font-weight: 500;
}

.entity-status-badge {
  font-size: 10px;
  padding: 1px 6px;
}

.entity-card__name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.entity-card__summary {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: 10px;
}

.entity-card__actions {
  display: flex;
  gap: 6px;
}
```

---

## P2 大纲：写作页大纲浮窗

**目标**：在写作页按快捷键或点击按钮，从右侧滑出大纲浮窗，不离开写作页即可查看/跳转。

### 修改文件：writingView.js

**1. 在 `_renderEditor` 的按钮区域增加大纲浮窗按钮**（约第 680 行）：

```javascript
<button class="btn btn-sm btn-ghost" data-action="toggle-outline-float" title="大纲浮窗 (Ctrl+Shift+O)">
  &#128209; 大纲
</button>
```

**2. 在写作页布局中增加大纲浮窗 DOM**：

在 `writing-workspace-layout` 之后增加：

```javascript
<div id="outline-float-panel" class="outline-float-panel hidden">
  <div class="outline-float-header">
    <span>大纲</span>
    <button class="btn-icon" data-action="close-outline-float">&times;</button>
  </div>
  <div class="outline-float-body" id="outline-float-body">
    <p style="color:var(--text-tertiary);font-size:12px;">加载中...</p>
  </div>
</div>
```

**3. 增加大纲浮窗加载方法**：

```javascript
async _toggleOutlineFloat() {
  const panel = document.getElementById("outline-float-panel")
  if (!panel) return
  
  const isHidden = panel.classList.contains("hidden")
  if (isHidden) {
    panel.classList.remove("hidden")
    await this._loadOutlineFloat()
  } else {
    panel.classList.add("hidden")
  }
},

async _loadOutlineFloat() {
  const body = document.getElementById("outline-float-body")
  if (!body || !state.currentProjectId) return
  
  try {
    const threads = await api.outline.listThreads(state.currentProjectId, { limit: 50 })
    const items = threads.items || threads || []
    
    let html = '<div class="outline-float-list">'
    for (const t of items) {
      html += `
        <div class="outline-float-item" data-thread-id="${esc(t.id)}">
          <div class="outline-float-title">${esc(t.title || '未命名')}</div>
          <div class="outline-float-chapters">
            ${(t.chapter_ids || []).map(ch => `
              <span class="outline-float-chapter ${ch === String(this._currentChapter) ? 'current' : ''}">
                ${ch}
              </span>
            `).join('')}
          </div>
        </div>
      `
    }
    html += '</div>'
    body.innerHTML = html
    
    // 绑定点击跳转
    body.querySelectorAll('.outline-float-chapter').forEach(el => {
      el.addEventListener('click', () => {
        const ch = parseInt(el.textContent, 10)
        if (!isNaN(ch)) {
          this._selectChapter(ch)
        }
      })
    })
  } catch {
    body.innerHTML = '<p style="color:var(--text-tertiary);font-size:12px;">加载失败</p>'
  }
},
```

**4. 在 `_bindEvents` 和全局快捷键中增加**：

```javascript
_bindEvents() {
  // ...
  "toggle-outline-float": () => this._toggleOutlineFloat(),
  "close-outline-float": () => document.getElementById("outline-float-panel")?.classList.add("hidden"),
}
```

在 `app.js` 的全局快捷键中增加（约第 517 行）：

```javascript
case "O":
  if (e.shiftKey && (e.ctrlKey || e.metaKey)) {
    e.preventDefault()
    if (state.currentView === "writing" && typeof writingView?._toggleOutlineFloat === "function") {
      writingView._toggleOutlineFloat()
    }
  }
  break
```

### 修改文件：styles.css

**增加大纲浮窗样式**（约第 1080 行后）：

```css
/* ===== 大纲浮窗 ===== */
.outline-float-panel {
  position: fixed;
  top: var(--topbar-height);
  right: 0;
  width: 280px;
  bottom: 0;
  background: var(--bg-panel);
  border-left: 1px solid var(--border);
  box-shadow: -4px 0 24px rgba(0,0,0,0.06);
  z-index: 80;
  display: flex;
  flex-direction: column;
  animation: slideInRight 0.2s ease-out;
}

.outline-float-panel.hidden {
  display: none;
}

@keyframes slideInRight {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

.outline-float-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  font-size: 14px;
  font-weight: 600;
}

.outline-float-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
}

.outline-float-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.outline-float-item {
  padding: 8px;
  border-radius: 6px;
  background: var(--bg-hover);
}

.outline-float-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-body);
  margin-bottom: 4px;
}

.outline-float-chapters {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.outline-float-chapter {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--bg-active);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
}

.outline-float-chapter:hover {
  background: var(--accent-soft);
  color: var(--accent);
}

.outline-float-chapter.current {
  background: var(--accent);
  color: #fff;
}

/* 浮窗打开时，主工作区收缩 */
.outline-float-open #workspace {
  margin-right: 280px;
}

@media (max-width: 900px) {
  .outline-float-panel {
    width: 100%;
  }
}
```

---

## P2 设置：参数预设包与作者偏好

**目标**：将 Temperature/Top P 等技术参数打包为「创意/精确/快速」模式，增加作者偏好设置（日更目标、编辑器字体、专注模式默认开关）。

### 修改文件：llmSettingsView.js

**1. 在渲染的 settings-panel 中，在供应商模板选择后增加模式选择**：

```javascript
<div class="form-group">
  <label for="llm-mode">创作模式</label>
  <select class="form-input" id="llm-mode">
    <option value="creative">创意模式 — 适合头脑风暴、生成剧情（发散）</option>
    <option value="precise">精确模式 — 适合润色、检查一致性（收敛）</option>
    <option value="fast">快速模式 — 轻量查询、快速响应</option>
    <option value="custom">自定义 — 手动调整下方参数</option>
  </select>
  <p class="form-hint" id="llm-mode-hint">选择预设后，下方参数会自动调整。</p>
</div>
```

**2. 在底部增加作者偏好区域**：

```javascript
<div class="settings-panel" style="margin-top:16px;">
  <div class="card-title" style="font-size:16px;margin-bottom:12px;">作者偏好</div>
  <div class="form-row">
    <div class="form-group">
      <label for="author-daily-goal">日更目标字数</label>
      <input class="form-input" id="author-daily-goal" type="number" min="1000" max="20000" step="1000" value="${this._getDailyGoal()}" />
      <span class="form-hint">用于写作页字数统计和进度提醒。</span>
    </div>
    <div class="form-group">
      <label for="author-editor-font">编辑器默认字体</label>
      <select class="form-input" id="author-editor-font">
        <option value="serif">宋体（Noto Serif SC）</option>
        <option value="sans">黑体（PingFang SC / Microsoft YaHei）</option>
        <option value="mono">等宽（JetBrains Mono）</option>
      </select>
    </div>
  </div>
  <div class="form-group">
    <label class="form-checkbox">
      <input type="checkbox" id="author-focus-default" ${this._getFocusDefault() ? 'checked' : ''} />
      <span>进入写作页时自动开启专注模式</span>
    </label>
  </div>
</div>
```

**3. 在 `save()` 中保存作者偏好**：

```javascript
async save() {
  // ... 现有 LLM 保存逻辑 ...
  
  // 保存作者偏好
  try {
    const dailyGoal = document.getElementById("author-daily-goal")?.value
    const editorFont = document.getElementById("author-editor-font")?.value
    const focusDefault = document.getElementById("author-focus-default")?.checked
    if (dailyGoal) localStorage.setItem("novel_daily_goal", dailyGoal)
    if (editorFont) localStorage.setItem("novel_editor_font", editorFont)
    localStorage.setItem("novel_focus_default", focusDefault ? "1" : "0")
  } catch {}
  
  toast("配置已保存", "success")
}
```

**4. 增加模式切换逻辑**：

```javascript
applyMode(mode) {
  const presets = {
    creative: { temperature: 0.8, top_p: 0.9, max_tokens: 4096 },
    precise: { temperature: 0.2, top_p: 0.5, max_tokens: 2048 },
    fast: { temperature: 0.5, top_p: 0.7, max_tokens: 1024 },
  }
  const p = presets[mode]
  if (!p) return
  this._setInputValue("llm-temperature", p.temperature)
  this._setInputValue("llm-top-p", p.top_p)
  this._setInputValue("llm-max-tokens", p.max_tokens)
  
  const hint = document.getElementById("llm-mode-hint")
  if (hint) {
    const hints = {
      creative: "Temperature 0.8，AI 更有创意，适合生成剧情和世界观。",
      precise: "Temperature 0.2，AI 更稳定，适合润色和一致性检查。",
      fast: "轻量参数，响应更快，适合简单查询和快速提取。",
    }
    hint.textContent = hints[mode] || ""
  }
}
```

在 `bindEvents` 中增加：
```javascript
document.getElementById("llm-mode")?.addEventListener("change", (e) => {
  this.applyMode(e.target.value)
})
```

### 修改文件：styles.css

**增加表单提示文字样式**（约第 910 行后）：

```css
.form-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 4px;
  line-height: 1.4;
}

.form-checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--text-body);
  cursor: pointer;
}

.form-checkbox input {
  width: 16px;
  height: 16px;
  cursor: pointer;
}
```

---

## P3 全局：护眼/纸张模式

**目标**：增加暗色以外的护眼主题和纸张模式，减少长时间写作的视觉疲劳。

### 修改文件：app.js

**1. 在 `_initTheme` 中扩展主题支持**（约第 733 行）：

```javascript
_initTheme() {
  try {
    const saved = localStorage.getItem("novel_theme")
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches
    const theme = saved || (prefersDark ? "dark" : "light")
    document.documentElement.setAttribute("data-theme", theme)
  } catch {}
},
```

改为：

```javascript
_initTheme() {
  try {
    const saved = localStorage.getItem("novel_theme")
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches
    const theme = saved || (prefersDark ? "dark" : "light")
    document.documentElement.setAttribute("data-theme", theme)
    
    // 如果主题是 paper，同时给 body 加 class 用于编辑器背景
    if (theme === "paper") {
      document.body.classList.add("theme-paper")
    }
  } catch {}
},
```

### 修改文件：index.html

**在 `<head>` 中增加主题切换按钮**（或放在设置页）。更轻量的方式是在设置页增加，但也可以在顶部栏增加一个小图标。推荐放在设置页。

在设置页渲染中增加主题选择（已在 llmSettingsView 的「作者偏好」区域中）。

### 修改文件：styles.css

**在暗色模式 `[data-theme="dark"]` 之后增加**（约第 181 行后）：

```css
/* ===== 护眼模式（dark-soft） ===== */
[data-theme="dark-soft"] {
  --bg-base: #1a1a2e;
  --bg-panel: #252542;
  --bg-elevated: #1e1e3a;
  --bg-hover: #2a2a50;
  --bg-active: #333360;

  --text-primary: #e0e0e8;
  --text-body: #c0c0d0;
  --text-secondary: #a0a0b8;
  --text-tertiary: #808098;
  --text-quaternary: #505068;

  --accent: #7b82f0;
  --accent-soft: rgba(123, 130, 240, 0.15);
  --accent-glow: rgba(123, 130, 240, 0.25);

  --border: #3a3a60;
  --border-light: #4a4a70;
  --shadow-md: 0 4px 24px rgba(0,0,0,0.3);
  --shadow-lg: 0 8px 32px rgba(0,0,0,0.4);
}

/* ===== 纸张模式（paper） ===== */
[data-theme="paper"] {
  --bg-base: #f4f1ea;
  --bg-panel: #faf8f3;
  --bg-elevated: #fffefb;
  --bg-hover: #f0ece4;
  --bg-active: #e8e4dc;

  --text-primary: #2c2c2c;
  --text-body: #3d3d3d;
  --text-secondary: #5a5a5a;
  --text-tertiary: #7a7a7a;
  --text-quaternary: #b5b0a8;

  --accent: #8b5a2b;
  --accent-soft: rgba(139, 90, 43, 0.12);
  --accent-hover: #6d4520;
  --accent-glow: rgba(139, 90, 43, 0.15);

  --border: #dcd7ce;
  --border-light: #e5e0d7;
  --shadow-md: 0 2px 12px rgba(0,0,0,0.06);
  --shadow-lg: 0 4px 24px rgba(0,0,0,0.08);

  --font-body: "Noto Serif SC", "Source Han Serif SC", "SimSun", serif;
}

/* 纸张模式下的编辑器特殊处理 */
.theme-paper .novel-editor,
.theme-paper .novel-editor--focus {
  background: #fffefb !important;
  color: #2c2c2c !important;
  border-color: #ddd8cf !important;
}

/* 编辑器行高自定义（通过 body class 控制） */
body.line-height-15 .novel-editor { line-height: 1.5 !important; }
body.line-height-18 .novel-editor { line-height: 1.8 !important; }
body.line-height-20 .novel-editor { line-height: 2.0 !important; }
body.line-height-22 .novel-editor { line-height: 2.2 !important; }
```

**说明**：
- `dark-soft`：比当前 `dark` 更柔和，降低纯黑对比度，文字不用纯白，减少 OLED 屏幕的刺眼感。
- `paper`：米黄背景 + 深褐强调色，模拟实体书写作，适合长时间码字。
- 行高通过 `body` 的 class 控制，配合设置页的下拉选择。

---

## P3 全局：移动端快速记录

**目标**：600px 以下屏幕进入写作页时，提供一个简化的「快速记录」模式，适合通勤时记录灵感。

### 修改文件：writingView.js

**1. 在 `render` 中增加移动端检测**：

```javascript
async render() {
  if (this._loading) { ... }
  
  // 移动端快速记录模式
  if (typeof window !== "undefined" && window.innerWidth < 600 && this._currentChapter) {
    return this._renderMobileQuickNote()
  }
  
  // ... 正常渲染 ...
}
```

**2. 增加移动端渲染方法**：

```javascript
_renderMobileQuickNote() {
  const editor = document.getElementById("writing-editor")
  const currentText = editor ? editor.value : (this._currentContent || "")
  
  return `
    <div class="mobile-quick-note">
      <div class="mobile-note-header">
        <span class="mobile-note-chapter">第 ${this._currentChapter} 章</span>
        <span class="mobile-note-wc" id="mobile-note-wc">${currentText.length} 字</span>
      </div>
      <textarea id="mobile-note-editor" class="mobile-note-editor" 
        placeholder="在此记录灵感...">${esc(currentText)}</textarea>
      <div class="mobile-note-actions">
        <button class="btn btn-primary" data-action="save-mobile-note">保存为草稿</button>
        <button class="btn btn-ghost" data-action="switch-desktop-mode">完整编辑器</button>
      </div>
    </div>
  `
}
```

**3. 增加事件绑定**：

```javascript
"save-mobile-note": async () => {
  const editor = document.getElementById("mobile-note-editor")
  if (!editor || !this._currentChapter) return
  const content = editor.value
  if (this._currentDraftId) {
    await api.writing.autosave(this._currentDraftId, {
      title: this._currentTitle || ``,
      content,
      expected_version: this._currentVersionNumber,
      expected_updated_at: this._currentUpdatedAt,
    }, state.currentProjectId)
  }
  toast("已保存到草稿", "success")
  this._currentContent = content
},
"switch-desktop-mode": () => {
  // 强制使用桌面布局（用户可能横屏或想要完整功能）
  document.body.classList.add("force-desktop")
  router.refresh()
}
```

### 修改文件：styles.css

**增加移动端快速记录样式**（约第 2980 行后，在响应式区）：

```css
/* ===== 移动端快速记录 ===== */
.mobile-quick-note {
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--topbar-height));
  padding: 12px;
  gap: 8px;
}

.mobile-note-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 14px;
  color: var(--text-secondary);
}

.mobile-note-chapter {
  font-weight: 600;
}

.mobile-note-wc {
  font-family: var(--font-mono);
  font-size: 12px;
}

.mobile-note-editor {
  flex: 1;
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  font-size: 16px;
  font-family: var(--font-body);
  line-height: 1.8;
  background: var(--bg-panel);
  color: var(--text-body);
  resize: none;
  outline: none;
}

.mobile-note-editor:focus {
  border-color: var(--accent);
}

.mobile-note-actions {
  display: flex;
  gap: 8px;
}

.mobile-note-actions .btn {
  flex: 1;
}

/* 强制桌面模式（用户主动切换） */
body.force-desktop .mobile-quick-note {
  display: none;
}
```

---

## 附录：快速验证清单

### 开发完成后逐项检查

| # | 检查项 | 验证方式 |
|---|--------|---------|
| 1 | 顶部状态栏在写作视图显示字数 | 切换到写作页，看右上角是否显示 `本章 X / 今日 X` |
| 2 | 编辑器字体变为宋体/黑体 | 检查 textarea 的 `font-family` 是否为 `var(--font-body)` |
| 3 | 专注模式隐藏两侧面板 | 点击「专注模式」，确认 `#sidebar` 和 `#writing-tree-container` 隐藏 |
| 4 | 底部字数条实时更新 | 在编辑器中打字，确认 `wc-chapter` 数字变化 |
| 5 | 右侧面板显示 Tab（人物/地点/设定/地图） | 切换到写作页，看右侧 Scene 面板是否有 4 个 Tab 按钮 |
| 6 | 章节树无复选框，有状态 dot 和字数 | 检查左侧章节列表是否显示圆点状态和字数 |
| 7 | 项目卡片显示字数和最近活跃 | 项目页卡片是否显示 `X 字 · X 章 · 2小时前` |
| 8 | 世界对象卡片视图正常渲染 | 点击「卡片视图」按钮，确认网格布局正确 |
| 9 | 大纲浮窗从右侧滑出 | 在写作页按 `Ctrl+Shift+O` 或点击「大纲」按钮 |
| 10 | 设置页保存作者偏好到 localStorage | 修改日更目标，刷新页面后是否保留 |
| 11 | 纸张模式背景变为米黄色 | 切换到 paper 主题，确认编辑器背景为 `#fdfcf8` |
| 12 | 移动端显示简化编辑器 | 浏览器 DevTools 切到 375px 宽度，确认只显示 textarea + 保存按钮 |

---

## 变更文件汇总

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `index.html` | 修改 | topbar 增加字数仪表盘 DOM |
| `styles.css` | 大量新增 | 所有新增样式（字数条、专注模式、卡片视图、浮窗、纸张模式等） |
| `app.js` | 修改 | `updateWordcountDashboard`、主题初始化、快捷键 |
| `state.js` | 可选 | 如需全局状态存储作者偏好 |
| `writingView.js` | 大量修改 | 编辑器、字数统计、专注模式、章节树、AI 续写、大纲浮窗、移动端 |
| `sceneCockpitPanel.js` | 修改 | Tab 化面板、人物插入 |
| `projectView.js` | 修改 | 卡片统计、继续写作按钮、最近活跃排序 |
| `worldView.js` | 修改 | 卡片视图、视图切换 |
| `outlineView.js` | 可选 | 如需大纲页增加「去写作」按钮 |
| `llmSettingsView.js` | 修改 | 预设包、作者偏好保存 |

---

*方案结束。所有代码均基于当前 `frontend-console/` 实际代码结构，可直接按文件修改实施。*
