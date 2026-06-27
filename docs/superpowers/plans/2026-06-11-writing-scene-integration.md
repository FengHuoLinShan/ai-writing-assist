# Writing View Scene 集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development

**Goal:** 将 writingView 从平面章节列表升级为 Scene→Chapter 二级树 + 当前 Scene 卡面板，对齐 Spec 场景 4。

**Architecture:** 纯前端变更。后端 Scene API 完整，api.js 已有 Scene 方法（Round 2）。writingView.js 加载 scenes 数据，重构左侧面板为 Scene 树，右侧面板替换为当前 Scene 卡。

**Tech Stack:** Vanilla JS, 现有 KeepAlive/viewState/modal 基础设施

**Spec 依据:** `docs/核心业务场景与预期行为.md` 场景 4 — 进入工作台 + 切换 Scene 导航

---

## 文件变更

```
修改:
  frontend-console/views/writingView.js   — 主要变更
  frontend-console/api.js                 — 添加 scenes/ordered 端点（如需要）
```

---

### Task 1: 添加 scenes/ordered API 方法到 api.js

**Files:**
- Modify: `frontend-console/api.js`

- [ ] **Step 1: 在 outline 对象中添加 scenesOrdered 方法**

```javascript
    async listScenesOrdered(novelId) {
      return request("/outline/scenes/ordered?novel_id=" + encodeURIComponent(novelId))
    },
    async listScenesByChapter(novelId, chapterIndex) {
      return request(`/outline/scenes/by-chapter?novel_id=${encodeURIComponent(novelId)}&chapter_index=${chapterIndex}`)
    },
```

- [ ] **Step 2: 提交**

```bash
git add frontend-console/api.js
git commit -m "feat: add scenes/ordered and scenes/by-chapter API methods"
```

---

### Task 2: 重构左侧面板为 Scene 树

**Files:**
- Modify: `frontend-console/views/writingView.js`

**当前行为**: `_renderChapterTree()` 渲染平面章节列表。

**目标行为**: Scene 树（一级节点 Scene）+ 折叠 Chapter（二级节点）。

- [ ] **Step 1: 添加 _scenes 数据属性**

在对象定义中添加：
```javascript
  _scenes: [],
  _currentSceneId: null,
```

- [ ] **Step 2: 在 onEnter() 中加载 Scene 数据**

在 `onEnter()` 的 `_chapterList` 加载之后添加：

```javascript
    // 加载 Scene 数据
    try {
      this._scenes = await api.outline.listScenesOrdered(state.currentProjectId) || []
    } catch {
      this._scenes = []
    }
```

- [ ] **Step 3: 替换 _renderChapterTree() 为 _renderSceneTree()**

新方法：

```javascript
  _renderSceneTree() {
    // 构建 Scene→Chapter 映射
    // 未关联 Scene 的章节归入 "未归类"
    const assignedChapters = new Set()
    const sceneChapterMap = this._scenes.map((s) => {
      const chIds = (s.chapter_ids || []).map((id) => {
        const num = parseInt(id, 10)
        if (!isNaN(num) && this._chapters[num]) {
          assignedChapters.add(num)
          return num
        }
        return null
      }).filter(Boolean)
      return { scene: s, chapters: chIds }
    })

    // 未关联 Scene 的章节
    const unassigned = this._chapterList.filter((idx) => !assignedChapters.has(idx))

    let html = `
      <div class="card" style="max-height:600px;overflow-y:auto;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="font-size:13px;font-weight:bold;">Scene 树</span>
          <button class="btn btn-sm" data-action="new-chapter" style="font-size:11px;">+ 新建章</button>
        </div>
        <div style="margin-top:6px;">
    `

    // 先渲染未归类章节（如果存在）
    if (unassigned.length > 0) {
      const isExpanded = unassigned.includes(this._currentChapter)
      html += `
        <div class="scene-tree-node">
          <div class="scene-tree-scene" data-action="toggle-scene-group" data-scene-id="unassigned" style="cursor:pointer;">
            <span class="toggle-icon">${isExpanded ? '▼' : '▶'}</span>
            <span style="color:var(--text-dim);font-size:12px;">未归类</span>
            <span style="color:var(--text-dim);font-size:10px;margin-left:4px;">(${unassigned.length}章)</span>
          </div>
          <div class="scene-tree-chapters" style="display:${isExpanded ? 'block' : 'none'};margin-left:16px;">
      `
      for (const idx of unassigned) {
        html += this._renderChapterRow(idx)
      }
      html += '</div></div>'
    }

    // 渲染 Scene 节点
    for (const { scene, chapters } of sceneChapterMap) {
      const isCurrentScene = scene.id === this._currentSceneId
      const isExpanded = isCurrentScene || chapters.includes(this._currentChapter)

      html += `
        <div class="scene-tree-node">
          <div class="scene-tree-scene clickable" data-action="select-scene" data-scene-id="${esc(scene.id)}"
               style="padding:4px 6px;border-radius:4px;${isCurrentScene ? 'background:var(--hover-bg);' : ''}">
            <span class="toggle-icon">${isExpanded ? '▼' : '▶'}</span>
            <span style="font-size:13px;font-weight:${isCurrentScene ? 'bold' : 'normal'};">${esc(scene.title || '未命名')}</span>
            <span style="color:var(--text-dim);font-size:10px;margin-left:4px;">(${chapters.length}章)</span>
          </div>
          <div class="scene-tree-chapters" style="display:${isExpanded ? 'block' : 'none'};margin-left:16px;">
      `

      for (const idx of chapters) {
        html += this._renderChapterRow(idx)
      }

      html += '</div></div>'
    }

    html += '</div></div>'
    return html
  },

  _renderChapterRow(idx) {
    const isActive = idx === this._currentChapter
    return `
      <div style="display:flex;align-items:center;padding:4px 6px;border-left:3px solid ${isActive ? 'var(--accent)' : 'transparent'};margin-bottom:1px;background:${isActive ? 'var(--hover-bg)' : 'transparent'};border-radius:0 4px 4px 0;}">
        <div class="clickable" data-action="select-chapter" data-chapter="${idx}" style="flex:1;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
          第 ${idx} 章
          ${this._chapters[idx].title ? `<span style="color:var(--text-dim);font-size:10px;margin-left:4px;">${esc(this._chapters[idx].title)}</span>` : ''}
        </div>
        <button class="btn btn-sm" data-action="delete-chapter" data-chapter="${idx}" title="删除整章" style="font-size:10px;color:var(--danger);margin-left:2px;">✕</button>
      </div>
    `
  },
```

- [ ] **Step 4: 更新 render() 中调用名**

将 `render()` 方法中的 `${this._renderChapterTree()}` 改为 `${this._renderSceneTree()}`。

- [ ] **Step 5: 提交**

```bash
git add frontend-console/views/writingView.js
git commit -m "feat: replace flat chapter tree with Scene→Chapter hierarchy in writingView"
```

---

### Task 3: 替换右侧面板为 Scene 卡

**Files:**
- Modify: `frontend-console/views/writingView.js`

- [ ] **Step 1: 添加 _findCurrentScene() 方法**

```javascript
  _findCurrentScene() {
    if (!this._currentChapter || !this._scenes.length) return null
    // 精确匹配 chapter_ids
    const chStr = String(this._currentChapter)
    const exact = this._scenes.find((s) =>
      (s.chapter_ids || []).includes(chStr)
    )
    if (exact) return exact
    // scene_chunks 反查
    const byChunk = this._scenes.find((s) =>
      (s.scene_chunks || []).some((c) => String(c.chapter_index) === chStr)
    )
    return byChunk || null
  },
```

- [ ] **Step 2: 替换 _renderOutlinePanel() 为 _renderScenePanel()**

```javascript
  _renderScenePanel() {
    const currentScene = this._findCurrentScene()

    let html = `
      <div class="card" style="max-height:600px;overflow-y:auto;font-size:12px;">
        <div style="font-size:13px;font-weight:bold;margin-bottom:8px;">当前 Scene</div>
    `

    if (currentScene) {
      const s = currentScene
      const tagLabel = {
        inciting_incident: "激励事件", rising_action: "冲突升级",
        climax: "阶段高潮", valley: "低谷", transition: "过渡",
        hook: "钩子", payoff: "爽点", draft: "草稿",
      }[s.narrative_tag] || s.narrative_tag || "草稿"
      const tagClass = `narrative-tag-${s.narrative_tag || "draft"}`

      html += `
        <div style="margin-bottom:10px;">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">
            <span style="font-family:var(--font-mono);font-size:14px;font-weight:600;">#${s.scene_index}</span>
            <span class="narrative-tag ${tagClass}">${tagLabel}</span>
          </div>
          <div style="font-size:14px;font-weight:500;margin-bottom:8px;">${esc(s.title || "未命名 Scene")}</div>
          ${s.goal ? `
            <div style="margin-bottom:6px;">
              <div style="color:var(--text-dim);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;">目标</div>
              <div style="color:var(--text);">${esc(s.goal)}</div>
            </div>
          ` : ''}
          ${s.core_conflict ? `
            <div style="margin-bottom:6px;">
              <div style="color:var(--text-dim);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;">冲突</div>
              <div style="color:var(--text);">${esc(s.core_conflict)}</div>
            </div>
          ` : ''}
          ${s.emotional_beat ? `
            <div style="margin-bottom:6px;">
              <div style="color:var(--text-dim);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;">情感</div>
              <div style="color:var(--text);">${esc(s.emotional_beat)}</div>
            </div>
          ` : ''}
          ${s.must_happen ? `
            <div style="margin-bottom:6px;">
              <div style="color:var(--text-dim);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;">必须发生</div>
              <div style="color:var(--text);">${esc(s.must_happen)}</div>
            </div>
          ` : ''}
          ${s.must_not_happen ? `
            <div style="margin-bottom:6px;">
              <div style="color:var(--text-dim);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;">禁止发生</div>
              <div style="color:var(--text);">${esc(s.must_not_happen)}</div>
            </div>
          ` : ''}
        </div>
      `
    } else {
      html += `
        <div style="color:var(--text-dim);font-size:11px;margin-bottom:8px;">
          当前章节未关联 Scene。${this._scenes.length > 0 ? '请选择左侧 Scene 节点。' : '请先在大纲视图中创建 Scene 卡。'}
        </div>
      `
    }

    // 保留大纲快速入口
    html += `
      <hr style="border:none;border-top:1px solid var(--border);margin:8px 0;">
      <button class="btn btn-sm" data-action="open-outline" style="font-size:11px;width:100%;">管理大纲</button>
    `

    html += '</div>'
    return html
  },
```

- [ ] **Step 3: 更新 render() 中调用名**

将 `render()` 方法中的 `${this._renderOutlinePanel()}` 改为 `${this._renderScenePanel()}`。

- [ ] **Step 4: 更新 _loadOutlineData() 同步加载 Scene**

在 `_selectChapter()` 中调用 `_loadSceneData()` 查找当前 Scene：

```javascript
  _updateCurrentScene() {
    this._currentSceneId = null
    const scene = this._findCurrentScene()
    if (scene) {
      this._currentSceneId = scene.id
    }
  },
```

并在 `_selectChapter()` 末尾（在 `await this._rerender()` 之前）添加：
```javascript
    this._updateCurrentScene()
```

- [ ] **Step 5: 提交**

```bash
git add frontend-console/views/writingView.js
git commit -m "feat: replace outline panel with Scene card panel in writingView"
```

---

### Task 4: Scene 级导航 + 展开/折叠

**Files:**
- Modify: `frontend-console/views/writingView.js`

- [ ] **Step 1: 添加 _selectScene() 方法**

```javascript
  _selectScene(sceneId) {
    this._currentSceneId = sceneId
    // 找到该 Scene 的第一个 Chapter
    const scene = this._scenes.find((s) => s.id === sceneId)
    if (!scene) return

    const chIds = (scene.chapter_ids || []).map((id) => parseInt(id, 10)).filter((n) => !isNaN(n))
    const firstChapter = chIds.length > 0 ? Math.min(...chIds) : null

    if (firstChapter && this._chapters[firstChapter]) {
      this._selectChapter(firstChapter)
    } else {
      // Scene 无关联章节，只更新高亮
      this._currentChapter = null
      this._rerender()
    }
  },
```

- [ ] **Step 2: 在 _bindEvents() 中添加新事件**

```javascript
      "select-scene": (_e, t) => this._selectScene(t.getAttribute("data-scene-id")),
      "toggle-scene-group": (_e, t) => {
        const chapters = t.parentElement.querySelector(".scene-tree-chapters")
        const icon = t.querySelector(".toggle-icon")
        if (chapters) {
          const isHidden = chapters.style.display === "none"
          chapters.style.display = isHidden ? "block" : "none"
          if (icon) icon.textContent = isHidden ? "▼" : "▶"
        }
      },
```

- [ ] **Step 3: 提交**

```bash
git add frontend-console/views/writingView.js
git commit -m "feat: add Scene-level navigation and expand/collapse in writingView"
```

---

### Task 5: 验证

**Files:** 无新建

- [ ] **Step 1: 运行前端单元测试**

```bash
cd frontend-console && npx vitest run
```

确认无新增失败（预存的 writingView.test.js `saveDraft` 测试失败不计入）。

- [ ] **Step 2: 提交（如有 lint 修复）**

---

## 自审

1. **Spec coverage:**
   - 左侧 Scene 树 ✅ Task 2
   - Chapter 折叠二级节点 ✅ Task 2
   - 右侧 Scene 卡面板 ✅ Task 3
   - Scene 切换导航 ✅ Task 4
   - Scene 卡数据来源 outline ✅ Task 3（只读展示）
   - 自动推断 Scene 归属 ✅ Task 3（_findCurrentScene 通过 chapter_ids + scene_chunks）
   - 右键断章 → ⚠️ 延后（需编辑器选区+右键菜单，独立功能）
   - 右键创建新 Scene → ⚠️ 延后（同上）
   - 角色/实体搜索浮窗 → ⚠️ 延后（独立 UI 组件）

2. **延后项及原因：**
   - 右键断章/创建 Scene：需要实现编辑器右键菜单、选区位置计算、scene_chunks 更新等独立子系统
   - 角色/实体搜索浮窗：需独立搜索结果组件，依赖 world 模块后端 API
   - Ctrl+S 快捷键修复：app.js 独立变更

3. **未归类章节处理：** Task 2 在树顶部显示"未归类"分组，避免已导入但未执行深度导入的章节不可见。
