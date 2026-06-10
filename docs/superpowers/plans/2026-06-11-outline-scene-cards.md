# Outline View Scene 卡子标签 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development

**Goal:** 将 outlineView 的 Scene 卡子标签从存根「场景卡列表（开发中）」实现为完整的 Scene 卡片列表，支持查看/创建/编辑/删除。

**Architecture:** 纯前端变更。后端 Scene CRUD API 已完整实现（7 个 endpoints）。前端需要在 api.js 添加 Scene API 方法，在 outlineView.js 实现卡片式渲染和 CRUD 模态框。

**Tech Stack:** Vanilla JS (zero framework), 现有 modal/toast/router 基础设施

**Spec 依据:** `docs/核心业务场景与预期行为.md` 场景 6 — 正常流：浏览剧情结构 + 手动创建/编辑 Scene 卡

---

### Task 1: 在 api.js 添加 Scene API 方法

**Files:**
- Modify: `frontend-console/api.js:480`（在 outline 对象内追加）

- [ ] **Step 1: 在 api.js 的 outline 对象内追加 Scene 方法**

在 `frontend-console/api.js` 的 `outline:` 对象内（约 line 482），`listArcs` 方法之前，追加：

```javascript
    // ---- Scene 卡 ----
    async listScenes(novelId, skip = 0, limit = 50) {
      return request("/outline/scenes" + buildQueryString({ novel_id: novelId, skip, limit }))
    },
    async getScene(sceneId, novelId) {
      return request(`/outline/scenes/${sceneId}?novel_id=${encodeURIComponent(novelId)}`)
    },
    async createScene(novelId, data) {
      return request(`/outline/scenes?novel_id=${encodeURIComponent(novelId)}`, {
        method: "POST",
        body: JSON.stringify(data),
      })
    },
    async updateScene(sceneId, novelId, data) {
      return request(`/outline/scenes/${sceneId}?novel_id=${encodeURIComponent(novelId)}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      })
    },
    async deleteScene(sceneId, novelId) {
      return request(`/outline/scenes/${sceneId}?novel_id=${encodeURIComponent(novelId)}`, {
        method: "DELETE",
      })
    },
```

- [ ] **Step 2: 提交**

```bash
git add frontend-console/api.js
git commit -m "feat: add Scene CRUD API methods to frontend api module"
```

---

### Task 2: 实现 _renderScenes() 卡片列表

**Files:**
- Modify: `frontend-console/views/outlineView.js`

- [ ] **Step 1: 添加 _scenes 数据和 Scene 加载**

在 `onEnter()` 方法中，在 fetchThreads/fetchArcs 部分追加 Scene 加载：

在 `const subView = state.currentSubView || "scenes"` 之后，promises 构建区追加：

```javascript
    if (subView === "scenes") {
      promises.push(
        api.outline.listScenes(state.currentProjectId)
          .then((data) => { this._scenes = data.items || data || [] })
          .catch(() => { this._scenes = [] })
      )
    }
```

同时在对象定义处添加 `_scenes: [],`（在 `_threads: [], _arcs: [],` 之后）。

- [ ] **Step 2: 替换 _renderScenes() 存根**

用以下代码替换当前的 `_renderScenes()` 方法：

```javascript
  _renderScenes() {
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先选择项目。</p></div>'
    }

    let html = `
      <div style="margin-bottom:8px;">
        <button class="btn btn-primary" data-action="create-scene">新建 Scene</button>
      </div>
    `

    if (!this._scenes || this._scenes.length === 0) {
      return html + `
        <div class="empty-state">
          <div class="empty-icon">&#128209;</div>
          <p>暂无 Scene 卡。</p>
          <p style="color:var(--text-dim);font-size:12px;">Scene 是叙事结构的最小单元。通过深度导入自动生成，或手动创建。</p>
        </div>
      `
    }

    // 先按 scene_index 排序
    const sorted = [...this._scenes].sort((a, b) => (a.scene_index || 0) - (b.scene_index || 0))

    html += '<div class="scene-card-list">'
    for (const s of sorted) {
      const tagLabel = this._narrativeTagLabel(s.narrative_tag)
      const tagClass = `narrative-tag-${s.narrative_tag || "draft"}`
      const sourceLabel = s.source === "deep_import" ? "AI导入" : s.source === "ai_generated" ? "AI生成" : "手动"
      const statusMap = { canonical: "正史", draft: "草稿", candidate: "候选", deprecated: "废弃" }
      const statusClass = `badge-${s.status || "draft"}`

      html += `
        <div class="scene-card" data-id="${esc(s.id)}">
          <div class="scene-card-header">
            <span class="scene-index">#${s.scene_index}</span>
            <span class="narrative-tag ${tagClass}">${tagLabel}</span>
            <span class="badge ${statusClass}">${statusMap[s.status] || esc(s.status)}</span>
            <span class="scene-source">${sourceLabel}</span>
          </div>
          <div class="scene-card-title">${esc(s.title || "未命名 Scene")}</div>
          ${s.goal ? `<div class="scene-card-field"><span class="field-label">目标</span>${esc(s.goal)}</div>` : ""}
          ${s.core_conflict ? `<div class="scene-card-field"><span class="field-label">冲突</span>${esc(s.core_conflict)}</div>` : ""}
          ${s.emotional_beat ? `<div class="scene-card-field"><span class="field-label">情感</span>${esc(s.emotional_beat)}</div>` : ""}
          <div class="scene-card-actions">
            <button class="btn btn-sm" data-action="edit-scene" data-id="${esc(s.id)}">编辑</button>
            <button class="btn btn-sm btn-danger" data-action="delete-scene" data-id="${esc(s.id)}">删除</button>
          </div>
        </div>
      `
    }
    html += '</div>'
    return html
  },

  _narrativeTagLabel(tag) {
    const map = {
      inciting_incident: "激励事件",
      rising_action: "冲突升级",
      climax: "阶段高潮",
      valley: "低谷",
      transition: "过渡",
      hook: "钩子",
      payoff: "爽点",
      draft: "草稿",
    }
    return map[tag] || tag || "草稿"
  },
```

- [ ] **Step 3: 提交**

```bash
git add frontend-console/views/outlineView.js
git commit -m "feat: implement Scene card list in outlineView replacing stub"
```

---

### Task 3: 实现 Scene 创建/编辑/删除模态框

**Files:**
- Modify: `frontend-console/views/outlineView.js`

- [ ] **Step 1: 添加 _showCreateSceneForm() 方法**

在 `_showCreateArcForm()` 方法之后追加：

```javascript
  _showCreateSceneForm() {
    const tagOptions = [
      { value: "draft", label: "草稿（默认）" },
      { value: "hook", label: "钩子" },
      { value: "inciting_incident", label: "激励事件" },
      { value: "rising_action", label: "冲突升级" },
      { value: "climax", label: "阶段高潮" },
      { value: "valley", label: "低谷" },
      { value: "transition", label: "过渡" },
      { value: "payoff", label: "爽点" },
    ]
    const tagSelectHtml = tagOptions.map(
      (o) => `<option value="${o.value}">${o.label}</option>`
    ).join("")

    // 获取当前最大 scene_index
    const maxIdx = this._scenes && this._scenes.length > 0
      ? Math.max(...this._scenes.map((s) => s.scene_index || 0))
      : -1
    const nextIdx = maxIdx + 1

    const formHtml = `
      <div class="form-group">
        <label>序号</label>
        <input class="form-input" id="create-scene-index" type="number" value="${nextIdx}" min="0" />
      </div>
      <div class="form-group">
        <label>标题</label>
        <input class="form-input" id="create-scene-title" placeholder="Scene 标题" />
      </div>
      <div class="form-group">
        <label>叙事标签</label>
        <select class="form-select" id="create-scene-tag">${tagSelectHtml}</select>
      </div>
      <div class="form-group">
        <label>目标</label>
        <textarea class="form-textarea" id="create-scene-goal" rows="2" placeholder="此 Scene 要完成的叙事目标"></textarea>
      </div>
      <div class="form-group">
        <label>核心冲突</label>
        <textarea class="form-textarea" id="create-scene-conflict" rows="2" placeholder="核心冲突描述"></textarea>
      </div>
      <div class="form-group">
        <label>情感节奏</label>
        <input class="form-input" id="create-scene-emotion" placeholder="读者的情感走向" />
      </div>
      <div class="form-group">
        <label>必须发生</label>
        <textarea class="form-textarea" id="create-scene-must-happen" rows="2" placeholder="必须发生的事件"></textarea>
      </div>
      <div class="form-group">
        <label>禁止发生</label>
        <textarea class="form-textarea" id="create-scene-must-not" rows="2" placeholder="禁止发生的事件"></textarea>
      </div>
    `
    showModal("新建 Scene 卡", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const title = document.getElementById("create-scene-title")?.value?.trim()
        try {
          await api.outline.createScene(state.currentProjectId, {
            scene_index: parseInt(document.getElementById("create-scene-index")?.value || "0", 10),
            title: title || null,
            narrative_tag: document.getElementById("create-scene-tag")?.value || "draft",
            goal: document.getElementById("create-scene-goal")?.value?.trim() || null,
            core_conflict: document.getElementById("create-scene-conflict")?.value?.trim() || null,
            emotional_beat: document.getElementById("create-scene-emotion")?.value?.trim() || null,
            must_happen: document.getElementById("create-scene-must-happen")?.value?.trim() || null,
            must_not_happen: document.getElementById("create-scene-must-not")?.value?.trim() || null,
            source: "manual",
            status: "draft",
          })
          toast("Scene 卡已创建", "success")
          router.navigate("outline", "scenes")
        } catch (err) { toast(err.message || "创建失败", "error") }
      },
    }])
  },
```

- [ ] **Step 2: 添加 _editScene() 方法**

```javascript
  _editScene(id) {
    const scene = (this._scenes || []).find((s) => s.id === id)
    if (!scene) return

    const tags = ["draft", "hook", "inciting_incident", "rising_action", "climax", "valley", "transition", "payoff"]
    const tagLabels = { draft: "草稿", hook: "钩子", inciting_incident: "激励事件", rising_action: "冲突升级", climax: "阶段高潮", valley: "低谷", transition: "过渡", payoff: "爽点" }
    const tagSelectHtml = tags.map(
      (t) => `<option value="${t}" ${(scene.narrative_tag || "draft") === t ? "selected" : ""}>${tagLabels[t]}</option>`
    ).join("")

    const formHtml = `
      <div class="form-group">
        <label>序号</label>
        <input class="form-input" id="edit-scene-index" type="number" value="${scene.scene_index || 0}" min="0" />
      </div>
      <div class="form-group">
        <label>标题</label>
        <input class="form-input" id="edit-scene-title" value="${esc(scene.title || "")}" />
      </div>
      <div class="form-group">
        <label>叙事标签</label>
        <select class="form-select" id="edit-scene-tag">${tagSelectHtml}</select>
      </div>
      <div class="form-group">
        <label>目标</label>
        <textarea class="form-textarea" id="edit-scene-goal" rows="2">${esc(scene.goal || "")}</textarea>
      </div>
      <div class="form-group">
        <label>核心冲突</label>
        <textarea class="form-textarea" id="edit-scene-conflict" rows="2">${esc(scene.core_conflict || "")}</textarea>
      </div>
      <div class="form-group">
        <label>情感节奏</label>
        <input class="form-input" id="edit-scene-emotion" value="${esc(scene.emotional_beat || "")}" />
      </div>
      <div class="form-group">
        <label>必须发生</label>
        <textarea class="form-textarea" id="edit-scene-must-happen" rows="2">${esc(scene.must_happen || "")}</textarea>
      </div>
      <div class="form-group">
        <label>禁止发生</label>
        <textarea class="form-textarea" id="edit-scene-must-not" rows="2">${esc(scene.must_not_happen || "")}</textarea>
      </div>
    `
    showModal("编辑 Scene 卡", formHtml, [{
      text: "保存", class: "btn-primary", handler: async () => {
        try {
          await api.outline.updateScene(id, state.currentProjectId, {
            scene_index: parseInt(document.getElementById("edit-scene-index")?.value || "0", 10),
            title: document.getElementById("edit-scene-title")?.value?.trim() || null,
            narrative_tag: document.getElementById("edit-scene-tag")?.value || "draft",
            goal: document.getElementById("edit-scene-goal")?.value?.trim() || null,
            core_conflict: document.getElementById("edit-scene-conflict")?.value?.trim() || null,
            emotional_beat: document.getElementById("edit-scene-emotion")?.value?.trim() || null,
            must_happen: document.getElementById("edit-scene-must-happen")?.value?.trim() || null,
            must_not_happen: document.getElementById("edit-scene-must-not")?.value?.trim() || null,
          })
          toast("已保存", "success")
          router.navigate("outline", "scenes")
        } catch (err) { toast(err.message || "保存失败", "error") }
      },
    }])
  },
```

- [ ] **Step 3: 添加 _deleteScene() 方法**

```javascript
  _deleteScene(id) {
    confirmAction("确定删除此 Scene 卡？删除后标记为 deprecated，正文保留。", async () => {
      try {
        await api.outline.deleteScene(id, state.currentProjectId)
        toast("已删除", "success")
        router.navigate("outline", "scenes")
      } catch (err) { toast(err.message || "删除失败", "error") }
    }, "确认删除")
  },
```

- [ ] **Step 4: 在 _bindEvents() 中添加事件绑定**

```javascript
      "create-scene": () => this._showCreateSceneForm(),
      "edit-scene": (_e, _t, ctx) => ctx.id && this._editScene(ctx.id),
      "delete-scene": (_e, _t, ctx) => ctx.id && this._deleteScene(ctx.id),
```

- [ ] **Step 5: 提交**

```bash
git add frontend-console/views/outlineView.js
git commit -m "feat: add Scene create/edit/delete modals to outlineView"
```

---

### Task 4: 添加 narrative_tag 颜色样式

**Files:**
- Modify: `frontend-console/styles.css`

- [ ] **Step 1: 在 styles.css 末尾追加 Scene 卡片样式**

```css
/* ===== Scene 卡片列表 ===== */
.scene-card-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.scene-card {
  border: 1px solid var(--border-dim);
  border-radius: 8px;
  padding: 12px;
  background: var(--bg-surface);
  transition: box-shadow 0.15s;
}

.scene-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.scene-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.scene-index {
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.scene-source {
  font-size: 11px;
  color: var(--text-dim);
  margin-left: auto;
}

.scene-card-title {
  font-size: 15px;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.scene-card-field {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 4px;
  line-height: 1.5;
}

.scene-card-field .field-label {
  color: var(--text-dim);
  font-size: 11px;
  margin-right: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.scene-card-actions {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border-dim);
  display: flex;
  gap: 6px;
}

/* ===== 叙事标签颜色 ===== */
.narrative-tag {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 500;
}

.narrative-tag-inciting_incident { background: var(--error-soft); color: var(--error); }
.narrative-tag-rising_action { background: var(--warning-soft); color: var(--warning); }
.narrative-tag-climax { background: #ffe0e0; color: #c62828; }
.narrative-tag-valley { background: var(--bg-active); color: var(--text-dim); }
.narrative-tag-transition { background: var(--bg-active); color: var(--text-tertiary); }
.narrative-tag-hook { background: var(--info-soft); color: var(--info); }
.narrative-tag-payoff { background: var(--success-soft); color: var(--success); }
.narrative-tag-draft { background: var(--bg-active); color: var(--text-secondary); }
```

- [ ] **Step 2: 提交**

```bash
git add frontend-console/styles.css
git commit -m "style: add Scene card and narrative tag styles"
```

---

### Task 5: 添加 outlineView Scene 卡 E2E 测试

**Files:**
- Create: `frontend-console/e2e/outline-scenes.spec.js`

- [ ] **Step 1: 创建 E2E 测试文件**

```javascript
const { test, expect } = require("@playwright/test")

test.describe("Outline View — Scene 卡", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/")
  })

  test("默认显示 Scene 卡子标签", async ({ page }) => {
    // 创建项目 → 进入大纲
    await page.click('[data-action="create-project"]')
    await page.fill('[data-testid="project-title"]', "Scene 测试项目")
    await page.click('[data-testid="project-submit"]')
    await page.waitForTimeout(500)

    // 导航到大纲
    await page.click('[data-action="nav-outline"]')
    await page.waitForTimeout(300)

    // 默认显示 scenes 子标签
    const scenesTab = page.locator(".subnav-item.active")
    await expect(scenesTab).toHaveText("场景卡")

    // 初始状态显示空态提示
    const emptyState = page.locator(".empty-state")
    await expect(emptyState).toContainText("暂无 Scene 卡")
  })

  test("创建 Scene 卡", async ({ page }) => {
    await page.click('[data-action="create-project"]')
    await page.fill('[data-testid="project-title"]', "Scene 创建测试")
    await page.click('[data-testid="project-submit"]')
    await page.waitForTimeout(500)
    await page.click('[data-action="nav-outline"]')
    await page.waitForTimeout(300)

    // 点击新建 Scene
    await page.click('[data-action="create-scene"]')
    await page.waitForTimeout(200)

    // 填写表单
    await page.fill("#create-scene-title", "测试 Scene")
    await page.selectOption("#create-scene-tag", "inciting_incident")
    await page.fill("#create-scene-goal", "完成首次探索")
    await page.fill("#create-scene-conflict", "主角遭遇未知生物")
    await page.fill("#create-scene-emotion", "紧张到兴奋")

    // 提交
    await page.click("button.btn-primary")

    // 等待列表刷新
    await page.waitForTimeout(500)

    // 验证卡片出现
    const card = page.locator(".scene-card").first()
    await expect(card).toContainText("测试 Scene")
    await expect(card).toContainText("激励事件")
    await expect(card).toContainText("完成首次探索")
  })
})
```

- [ ] **Step 2: 提交**

```bash
git add frontend-console/e2e/outline-scenes.spec.js
git commit -m "test: add E2E tests for outlineView Scene card CRUD"
```

---

### Task 6: 验证 + Lint

**Files:** 无新建

- [ ] **Step 1: 运行前端单元测试确认无回归**

```bash
cd frontend-console && npx vitest run
```

- [ ] **Step 2: 运行 E2E 测试**

```bash
cd frontend-console && npx playwright test e2e/outline-scenes.spec.js --reporter=list
```

- [ ] **Step 3: 如有失败修复后提交；否则标记完成**

---

## 自审

1. **Spec coverage** — 逐条对照：
   - Scene 标签时间线式排列 ✅ Task 2（卡片列表按 scene_index 排序）
   - 显示 scene_index / title / narrative_tag 标签 / goal 摘要 ✅ Task 2
   - 手动创建 Scene，可编辑 7 个字段 ✅ Task 3
   - narrative_tag 选项全部 8 个 ✅ Task 3
   - 手动创建默认 narrative_tag = "draft" ✅ Task 3
   - 删除 Scene 标记 deprecated ✅ Task 3（调用后端 soft delete API）
   - 拖拽排序 → ⚠️ 本轮延后（需要后端 reorder API）

2. **Placeholder scan** — 无 TBD/TODO，所有代码完整

3. **延后项：**
   - 拖拽排序（需要后端 `PUT /api/outline/scenes/reorder` API）
   - 所属 Arc 显示（需要查询 outline_arcs 关联数据）
   - 伏笔/揭示标签（独立功能，需先实现后端 API）
