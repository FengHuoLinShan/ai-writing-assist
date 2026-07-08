# Scene 树折叠展开点击交互优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 调整写作页左侧 Scene 树的点击交互：Scene 标题点击既跳转又切换分组展开/折叠，三角按钮只切换折叠不跳转。

**Architecture:** 仅修改 `chapterTree.js` 内部的事件处理与渲染逻辑，不引入新模块或状态持久化。`_selectScene` 由「强制展开」改为「读取当前状态取反」；`_toggleSceneGroup` 改为通过父节点查找 toggle 按钮与图标，使 Scene 标题和未归类文字都能复用同一折叠逻辑。

**Tech Stack:** vanilla JavaScript, Vitest, jsdom

---

## File Structure

| File | Responsibility |
|------|---------------|
| `frontend-console/views/writing/chapterTree.js` | Scene 树渲染、折叠状态维护、点击事件处理 |
| `frontend-console/tests/writing/chapterTree.test.js` | 单元测试：验证标题点击、三角按钮、未归类分组的折叠与跳转行为 |

---

### Task 1: 修改 `_selectScene` 由强制展开改为切换

**Files:**
- Modify: `frontend-console/views/writing/chapterTree.js:497-510`

- [ ] **Step 1: 修改 `_selectScene` 实现**

在跳转回调之前，读取该 Scene 分组当前展开状态并取反。

```js
_selectScene(sceneId) {
  const scene = this._scenes.find((s) => s.id === sceneId)
  if (!scene) return

  const groupId = this._sceneGroupKey(scene)
  const currentlyExpanded = this._isSceneGroupExpanded(groupId, false)
  this._sceneGroupExpansion[groupId] = !currentlyExpanded

  const chIds = (scene.chapter_ids || []).map((id) => parseInt(id, 10)).filter((n) => !isNaN(n))
  const firstChapter = chIds.length > 0 ? Math.min(...chIds) : null

  if (firstChapter && this._chapters[firstChapter]) {
    this._currentChapter = firstChapter
    if (this._onSelect) this._onSelect(firstChapter)
  }
  if (this._onSceneSelect) this._onSceneSelect(sceneId)
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-console/views/writing/chapterTree.js
git commit -m "refactor(chapterTree): toggle scene group on title click instead of always expanding"
```

---

### Task 2: 让「未归类」文字也能触发折叠

**Files:**
- Modify: `frontend-console/views/writing/chapterTree.js:359-373`

- [ ] **Step 1: 将未归类 `<span>` 改为 `<button class="scene-tree-label">`**

```js
if (unassigned.length > 0) {
  const groupId = "unassigned"
  const isExpanded = this._isSceneGroupExpanded(
    groupId,
    unassigned.includes(this._currentChapter),
  )
  html += `
    <div class="scene-tree-node">
      <div class="scene-tree-scene" style="padding:4px 4px;">
        <button type="button" class="scene-tree-toggle" data-action="toggle-scene-group" data-group-id="${groupId}" aria-expanded="${isExpanded ? "true" : "false"}" title="${isExpanded ? "折叠" : "展开"}">
          <span class="toggle-icon">${isExpanded ? "▼" : "▶"}</span>
        </button>
        <button type="button" class="scene-tree-label" data-action="toggle-scene-group" data-group-id="${groupId}" style="color:var(--text-dim);font-size:12px;">未归类</button>
        <span style="color:var(--text-dim);font-size:10px;margin-left:4px;">(${unassigned.length}章)</span>
      </div>
      <div class="scene-tree-chapters" style="display:${isExpanded ? "block" : "none"};margin-left:12px;">
  `
  for (const idx of unassigned) {
    html += this._renderChapterRow(idx)
  }
  html += "</div></div>"
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend-console/views/writing/chapterTree.js
git commit -m "feat(chapterTree): make unassigned group label clickable for collapse"
```

---

### Task 3: 更新 `_toggleSceneGroup` 处理多种触发源并阻止冒泡

**Files:**
- Modify: `frontend-console/views/writing/chapterTree.js:520-533`
- Modify: `frontend-console/views/writing/chapterTree.js:135`

- [ ] **Step 1: 修改 `_toggleSceneGroup` 签名与实现**

触发源可能是三角按钮，也可能是 `.scene-tree-label`。统一从父节点 `.scene-tree-node` 查找 `.scene-tree-toggle` 和 `.toggle-icon`，避免依赖 `t.querySelector` 找不到图标。同时阻止事件冒泡。

```js
_toggleSceneGroup(t, event) {
  if (event) event.stopPropagation()
  const node = t.closest(".scene-tree-node")
  const chapters = node?.querySelector(".scene-tree-chapters")
  const toggleBtn = node?.querySelector(".scene-tree-toggle")
  const icon = toggleBtn?.querySelector(".toggle-icon")
  if (chapters) {
    const isHidden = chapters.style.display === "none"
    chapters.style.display = isHidden ? "block" : "none"
    const groupId = t.getAttribute("data-group-id")
    if (groupId) this._sceneGroupExpansion[groupId] = isHidden
    if (toggleBtn) {
      toggleBtn.setAttribute("aria-expanded", isHidden ? "true" : "false")
      toggleBtn.setAttribute("title", isHidden ? "折叠" : "展开")
    }
    if (icon) icon.textContent = isHidden ? "▼" : "▶"
  }
}
```

- [ ] **Step 2: 更新事件绑定，传入事件对象**

```js
"toggle-scene-group": (e, t) => this._toggleSceneGroup(t, e),
```

- [ ] **Step 3: Commit**

```bash
git add frontend-console/views/writing/chapterTree.js
git commit -m "refactor(chapterTree): unify toggle source handling and stop propagation"
```

---

### Task 4: 更新现有测试并补充新测试

**Files:**
- Modify: `frontend-console/tests/writing/chapterTree.test.js:181-219`
- Modify: `frontend-console/tests/writing/chapterTree.test.js`（新增两个 `it`）

- [ ] **Step 1: 扩展现有测试「Scene 分组三角按钮可折叠并在重渲染后保持状态」**

替换原测试，覆盖三角按钮折叠、Scene 标题展开、Scene 标题折叠三种情况。

```js
it("Scene 分组三角按钮与标题均可折叠/展开", async () => {
  state.currentProjectId = "p1"
  api.writing.listChapters.mockResolvedValue({
    chapters: [
      { chapter_index: 1, title: "开篇", word_count: 100, version_number: 1 },
      { chapter_index: 2, title: "转折", word_count: 100, version_number: 1 },
    ],
  })
  api.outline.listScenesOrdered.mockResolvedValue([
    { id: "s1", title: "Scene 1", chapter_ids: ["1", "2"] },
  ])

  const onSelect = vi.fn()
  const onSceneSelect = vi.fn()
  const tree = createTestTree({ onSelect, onSceneSelect })
  await tree.load()

  document.body.innerHTML = tree.render()
  tree.bindEvents(document.body)

  const toggle = document.querySelector('[data-action="toggle-scene-group"]')
  const chapters = document.querySelector(".scene-tree-chapters")
  expect(toggle.getAttribute("aria-expanded")).toBe("true")
  expect(chapters.style.display).toBe("block")

  // 三角按钮只折叠，不触发跳转回调
  toggle.click()
  expect(toggle.getAttribute("aria-expanded")).toBe("false")
  expect(chapters.style.display).toBe("none")
  expect(onSceneSelect).not.toHaveBeenCalled()

  document.body.innerHTML = tree.render()
  const rerenderedChapters = document.querySelector(".scene-tree-chapters")
  expect(rerenderedChapters.style.display).toBe("none")

  // Scene 标题点击：跳转并展开
  tree.bindEvents(document.body)
  document.querySelector('[data-action="select-scene"]').click()
  expect(onSelect).toHaveBeenCalledWith(1)
  expect(onSceneSelect).toHaveBeenCalledWith("s1")
  expect(document.querySelector(".scene-tree-chapters").style.display).toBe("block")

  // Scene 标题再次点击：跳转并折叠
  document.querySelector('[data-action="select-scene"]').click()
  expect(onSelect).toHaveBeenCalledTimes(2)
  expect(onSceneSelect).toHaveBeenCalledTimes(2)
  expect(document.querySelector(".scene-tree-chapters").style.display).toBe("none")
})
```

- [ ] **Step 2: 新增测试「未归类文字点击只折叠不跳转」**

```js
it("未归类分组标题点击只切换折叠不跳转", async () => {
  state.currentProjectId = "p1"
  api.writing.listChapters.mockResolvedValue({
    chapters: [
      { chapter_index: 1, title: "开篇", word_count: 100, version_number: 1 },
      { chapter_index: 2, title: "转折", word_count: 100, version_number: 1 },
    ],
  })
  api.outline.listScenesOrdered.mockResolvedValue([
    { id: "s1", title: "Scene 1", chapter_ids: ["1"] },
  ])

  const onSceneSelect = vi.fn()
  const tree = createTestTree({ onSceneSelect })
  await tree.load()

  document.body.innerHTML = tree.render()
  tree.bindEvents(document.body)

  const unassignedLabel = document.querySelector('[data-group-id="unassigned"].scene-tree-label')
  expect(unassignedLabel).not.toBeNull()
  expect(unassignedLabel.textContent).toBe("未归类")

  const unassignedChapters = document.querySelectorAll(".scene-tree-chapters")[1]
  expect(unassignedChapters.style.display).toBe("block")

  unassignedLabel.click()
  expect(unassignedChapters.style.display).toBe("none")
  expect(onSceneSelect).not.toHaveBeenCalled()
})
```

- [ ] **Step 3: 运行单元测试**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console
npm test -- tests/writing/chapterTree.test.js
```

Expected: 所有测试通过。

- [ ] **Step 4: Commit**

```bash
git add frontend-console/tests/writing/chapterTree.test.js
git commit -m "test(chapterTree): cover scene title toggle and unassigned label collapse"
```

---

## Spec Coverage Check

| Spec Requirement | Task |
|-----------------|------|
| Scene 标题点击跳转并切换展开/折叠 | Task 1 |
| 三角按钮只切换折叠不跳转 | Task 3（stopPropagation）+ Task 4 测试 |
| 未归类文字只切换折叠不跳转 | Task 2 + Task 3 + Task 4 测试 |
| 默认展开策略不变 | 未改动 `_isSceneGroupExpanded` 默认逻辑 |
| 状态不持久化 | 未引入 localStorage |

## Placeholder Scan

- 无 TBD / TODO。
- 无 "add appropriate error handling" 等模糊描述。
- 每个步骤包含具体代码或命令。

## Type Consistency

- 事件对象统一命名为 `event`。
- `data-group-id="unassigned"` 在渲染、事件处理、测试中保持一致。
- `scene-tree-label` 类名与现有 Scene 标题按钮一致。
