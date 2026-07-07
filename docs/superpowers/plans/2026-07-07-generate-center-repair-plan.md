# 生成中心前端组件修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务逐步实施。步骤使用 `- [ ]` 语法以便跟踪。

**Goal:** 修复生成中心页面在任务/上下文预览/角色视角交互中的 E2E 失败与状态持久化缺陷，消除 AbortController 泄漏与重复提交风险，确保前后端相关测试与 lint 全绿。

**Architecture:** 变更集中在前端 `frontend-console/views/generateView.js`（任务表单状态、按钮忙状态、请求控制器生命周期）与 `frontend-console/e2e/generate.spec.js`（补充预设选择步骤）。后端 `object-draft-chatbox` 与提示词模板服务已通过现有测试覆盖，本计划不修改后端代码，仅作为验证目标。

**Tech Stack:** 前端 vanilla JS / Vitest / Playwright；后端 FastAPI / pytest / ruff。

---

## 文件变更清单

| 文件 | 动作 | 说明 |
|------|------|------|
| `frontend-console/e2e/generate.spec.js` | 修改 | 上下文预览 E2E 先选择“生成剧情线”预设 |
| `frontend-console/views/generateView.js` | 修改 | 持久化 `viewpoint_character_id`；移除相关人物到视角人物的回退；切到非角色预设时清空视角人物；任务按钮忙状态；finally 释放 AbortController |
| `frontend-console/tests/generateView.test.js` | 修改 | 新增视角人物持久化、预设切换清空视角人物、忙状态等单元测试 |

---

## Task 1：修复 E2E “上下文预览标签展示最近一次编译结果”

**Files:**
- Modify: `frontend-console/e2e/generate.spec.js:195-205`
- Test: `frontend-console/e2e/generate.spec.js`

当前测试只填写任务描述就点击“执行任务”，`_taskPreset` 保持 `"custom"`，导致上下文预览显示“来自：任务：自定义任务”。需要按真实交互先选择“生成剧情线”预设卡片。

- [ ] **Step 1：修改测试，先点击 `data-preset="plot"` 卡片**

```javascript
// frontend-console/e2e/generate.spec.js
// 旧代码
  test("上下文预览标签展示最近一次编译结果", async ({ page }) => {
    await page.getByRole("button", { name: "任务" }).click()
    await page.locator("#gen-task").fill("生成剧情线")
    await page.getByRole("button", { name: "执行任务" }).click()
    await expect(page.locator("#gen-task-output")).toContainText("已加载 2 段上下文", { timeout: 15000 })

    await page.getByRole("button", { name: "上下文预览" }).click()

    await expect(page.locator("#workspace-content")).toContainText("上下文预览")
    await expect(page.locator("#workspace-content")).toContainText("任务：生成剧情线")
  })
```

```javascript
// 新代码
  test("上下文预览标签展示最近一次编译结果", async ({ page }) => {
    await page.getByRole("button", { name: "任务" }).click()
    await page.locator('[data-preset="plot"]').click()
    await page.getByRole("button", { name: "执行任务" }).click()
    await expect(page.locator("#gen-task-output")).toContainText("已加载 2 段上下文", { timeout: 15000 })

    await page.getByRole("button", { name: "上下文预览" }).click()

    await expect(page.locator("#workspace-content")).toContainText("上下文预览")
    await expect(page.locator("#workspace-content")).toContainText("任务：生成剧情线")
  })
```

- [ ] **Step 2：运行该 E2E 用例验证通过**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console
npm run test:e2e -- e2e/generate.spec.js --grep "上下文预览标签展示最近一次编译结果"
```

Expected: `1 passed`

- [ ] **Step 3：提交**

```bash
git add frontend-console/e2e/generate.spec.js
git commit -m "test(generate): 上下文预览 E2E 先选择生成剧情线预设"
```

---

## Task 2：任务表单持久化视角人物 ID

**Files:**
- Modify: `frontend-console/views/generateView.js:1297-1306`
- Test: `frontend-console/tests/generateView.test.js`

`_compileTaskContext` 把 `_taskForm` 写回状态时漏掉了 `viewpoint_character_id`，导致角色视角模式编译后回到任务标签时视角人物输入框为空。

- [ ] **Step 1：写失败测试**

在 `frontend-console/tests/generateView.test.js` 的 `describe("generateView task tab", () => { ... })` 内新增：

```javascript
  it("执行任务后保留视角人物 ID", async () => {
    generateView._generateSubTab = "task"
    generateView._taskForm = {
      task: "写角色视角场景",
      scope: "chapter",
      reveal_mode: "character",
      budget_tokens: 4000,
      viewpoint_character_id: "char-1",
    }
    document.body.innerHTML = await generateView.render()
    document.getElementById("gen-reveal").value = "character"
    document.getElementById("gen-viewpoint-character").value = "char-1"

    await generateView._runTask()

    expect(api.context.compile).toHaveBeenCalledWith(
      expect.objectContaining({
        task: "写角色视角场景",
        reveal_mode: "character",
        viewpoint_character_id: "char-1",
        character_ids: ["char-1"],
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(generateView._taskForm.viewpoint_character_id).toBe("char-1")
  })
```

Run:

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console
npm test -- --run tests/generateView.test.js -t "执行任务后保留视角人物 ID"
```

Expected: FAIL（`_taskForm.viewpoint_character_id` 为 `undefined`）

- [ ] **Step 2：修改 `_compileTaskContext` 持久化视角人物 ID**

```javascript
// frontend-console/views/generateView.js
// 旧代码
    this._taskForm = {
      task: params.task,
      scope: params.scope,
      reveal_mode: params.reveal_mode,
      budget_tokens: params.budget_tokens,
      entity_ids: params.entity_ids,
      character_ids: params.character_ids,
      chapter_index: params.chapter_index,
      scene_id: params.scene_id,
    }
```

```javascript
// 新代码
    this._taskForm = {
      task: params.task,
      scope: params.scope,
      reveal_mode: params.reveal_mode,
      budget_tokens: params.budget_tokens,
      entity_ids: params.entity_ids,
      character_ids: params.character_ids,
      viewpoint_character_id: params.viewpoint_character_id,
      chapter_index: params.chapter_index,
      scene_id: params.scene_id,
    }
```

- [ ] **Step 3：运行单元测试**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console
npm test -- --run tests/generateView.test.js -t "执行任务后保留视角人物 ID"
```

Expected: PASS

- [ ] **Step 4：提交**

```bash
git add frontend-console/views/generateView.js frontend-console/tests/generateView.test.js
git commit -m "fix(generate): 任务编译后持久化 viewpoint_character_id"
```

---

## Task 3：移除“相关人物”到视角人物的自动回退

**Files:**
- Modify: `frontend-console/views/generateView.js:1260`
- Test: `frontend-console/tests/generateView.test.js`

当前 `_readTaskForm` 在角色视角模式下，如果视角人物输入为空，会自动把“相关人物”的第一个 ID 当作视角人物，这与 UI 提示“角色视角模式仅使用此 ID 作为视角人物，与相关人物相互独立”矛盾。

- [ ] **Step 1：写失败测试**

在 `describe("generateView task tab", () => { ... })` 内新增：

```javascript
  it("角色视角模式不自动把相关人物当作视角人物", async () => {
    generateView._generateSubTab = "task"
    generateView._taskForm = {
      task: "写角色视角场景",
      scope: "chapter",
      reveal_mode: "character",
      budget_tokens: 4000,
      character_ids: ["char-1"],
    }
    document.body.innerHTML = await generateView.render()
    document.getElementById("gen-reveal").value = "character"
    document.getElementById("gen-characters").value = "char-1"
    document.getElementById("gen-viewpoint-character").value = ""

    await generateView._runTask()

    expect(api.context.compile).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("角色视角模式必须选择或输入视角人物 ID", "warning")
  })
```

Run:

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console
npm test -- --run tests/generateView.test.js -t "角色视角模式不自动把相关人物当作视角人物"
```

Expected: FAIL（当前会回退到 `char-1` 并提交编译）

- [ ] **Step 2：修改 `_readTaskForm`**

```javascript
// frontend-console/views/generateView.js
// 旧代码
    const viewpointCharacterId = reveal === "character" ? (viewpointCharacterInput.trim() || characterIds?.[0]) : undefined
```

```javascript
// 新代码
    const viewpointCharacterId = reveal === "character" ? (viewpointCharacterInput.trim() || undefined) : undefined
```

- [ ] **Step 3：运行单元测试**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console
npm test -- --run tests/generateView.test.js -t "角色视角模式不自动把相关人物当作视角人物"
```

Expected: PASS

- [ ] **Step 4：提交**

```bash
git add frontend-console/views/generateView.js frontend-console/tests/generateView.test.js
git commit -m "fix(generate): 角色视角人物不再回退到相关人物"
```

---

## Task 4：切到非角色视角预设时清空视角人物 ID

**Files:**
- Modify: `frontend-console/views/generateView.js:1011-1020`
- Test: `frontend-console/tests/generateView.test.js`

如果用户先设置了角色视角人物，再点击“生成剧情线”/“润色正文”等预设，`_taskForm.viewpoint_character_id` 会残留，再次切回角色视角时可能显示旧值。

- [ ] **Step 1：写失败测试**

在 `describe("generateView task tab", () => { ... })` 内新增：

```javascript
  it("切换到非角色视角预设时清空视角人物 ID", async () => {
    generateView._generateSubTab = "task"
    generateView._taskForm = {
      ...generateView._taskForm,
      viewpoint_character_id: "char-1",
    }
    document.body.innerHTML = await generateView.render()

    await generateView._selectTaskPreset("plot")

    expect(generateView._taskForm.reveal_mode).toBe("author_full")
    expect(generateView._taskForm.viewpoint_character_id).toBeUndefined()
  })
```

Run:

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console
npm test -- --run tests/generateView.test.js -t "切换到非角色视角预设时清空视角人物 ID"
```

Expected: FAIL（`viewpoint_character_id` 仍为 `"char-1"`）

- [ ] **Step 2：修改 `_applyTaskPresetValues`**

```javascript
// frontend-console/views/generateView.js
// 旧代码
  _applyTaskPresetValues(presetKey) {
    const preset = TASK_PRESETS[presetKey]
    if (!preset) return
    this._taskForm = {
      ...this._taskForm,
      task: preset.task,
      scope: preset.scope,
      reveal_mode: preset.reveal_mode,
    }
  }
```

```javascript
// 新代码
  _applyTaskPresetValues(presetKey) {
    const preset = TASK_PRESETS[presetKey]
    if (!preset) return
    this._taskForm = {
      ...this._taskForm,
      task: preset.task,
      scope: preset.scope,
      reveal_mode: preset.reveal_mode,
      viewpoint_character_id: preset.reveal_mode === "character" ? this._taskForm.viewpoint_character_id : undefined,
    }
  }
```

- [ ] **Step 3：运行单元测试**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console
npm test -- --run tests/generateView.test.js -t "切换到非角色视角预设时清空视角人物 ID"
```

Expected: PASS

- [ ] **Step 4：提交**

```bash
git add frontend-console/views/generateView.js frontend-console/tests/generateView.test.js
git commit -m "fix(generate): 非角色视角预设清空 viewpoint_character_id"
```

---

## Task 5：编译/渲染期间禁用任务按钮并修复 AbortController 泄漏

**Files:**
- Modify: `frontend-console/views/generateView.js:887-892`, `1294-1331`, `1399-1435`
- Test: `frontend-console/tests/generateView.test.js`

当前 `_setBusy` 不控制任务操作按钮，用户可能重复点击“执行任务”或“预览上下文”。另外 `_compileTaskContext` 与 `_viewGenerationContext` 只在成功路径释放 `AbortController`，异常时会泄漏。

- [ ] **Step 1：写失败测试**

在 `describe("generateView task tab", () => { ... })` 内新增：

```javascript
  it("上下文编译期间禁用任务操作按钮", async () => {
    generateView._generateSubTab = "task"
    generateView._taskForm = {
      task: "测试任务",
      scope: "arc",
      reveal_mode: "author_safe",
      budget_tokens: 4000,
    }
    document.body.innerHTML = await generateView.render()
    let resolveCompile
    api.context.compile.mockImplementation(() => new Promise((resolve) => { resolveCompile = resolve }))

    generateView._runTask()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(document.querySelector('[data-action="run-task"]')?.disabled).toBe(true)
    expect(document.querySelector('[data-action="preview-task-context"]')?.disabled).toBe(true)
    expect(document.querySelector('[data-action="render-task-md"]')?.disabled).toBe(true)

    resolveCompile({
      sections: [],
      total_tokens: 0,
      budget_tokens: 4000,
      scope: "arc",
      reveal_mode: "author_safe",
    })
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(document.querySelector('[data-action="run-task"]')?.disabled).toBe(false)
  })
```

Run:

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console
npm test -- --run tests/generateView.test.js -t "上下文编译期间禁用任务操作按钮"
```

Expected: FAIL（按钮未被禁用）

- [ ] **Step 2：扩展 `_setBusy` 选择器**

```javascript
// frontend-console/views/generateView.js
// 旧代码
  _setBusy(busy) {
    this._busy = busy
    document.querySelectorAll('[data-action="send-chat-message"], [data-action="generate-object-draft"], [data-action="generate-pov-prose"]').forEach((btn) => {
      btn.disabled = busy
    })
  }
```

```javascript
// 新代码
  _setBusy(busy) {
    this._busy = busy
    document.querySelectorAll(
      '[data-action="send-chat-message"], [data-action="generate-object-draft"], [data-action="generate-pov-prose"], [data-action="run-task"], [data-action="preview-task-context"], [data-action="render-task-md"]'
    ).forEach((btn) => {
      btn.disabled = busy
    })
  }
```

- [ ] **Step 3：在 `_compileTaskContext` 的 finally 中释放控制器**

```javascript
// 旧代码
  async _compileTaskContext({ silent = false } = {}) {
    const params = this._readTaskForm()
    if (!this._validateTaskForm(params)) return
    this._taskForm = { /* ... */ }
    this._lastContextSource = "task"
    this._lastContextRequestParams = params
    const output = document.getElementById("gen-task-output")
    if (output) output.innerHTML = '<div class="loading">编译中...</div>'
    try {
      this._setBusy(true)
      const controller = this._trackRequestController()
      const data = await api.context.compile(params, { signal: controller.signal })
      this._lastContextBundle = data
      this._releaseRequestController(controller)
      this._generateSubTab = "preview"
      this._persistState()
      await this._refreshView()
    } catch (err) {
      /* ... */
    } finally {
      this._setBusy(false)
    }
  }
```

```javascript
// 新代码
  async _compileTaskContext({ silent = false } = {}) {
    const params = this._readTaskForm()
    if (!this._validateTaskForm(params)) return
    this._taskForm = {
      task: params.task,
      scope: params.scope,
      reveal_mode: params.reveal_mode,
      budget_tokens: params.budget_tokens,
      entity_ids: params.entity_ids,
      character_ids: params.character_ids,
      viewpoint_character_id: params.viewpoint_character_id,
      chapter_index: params.chapter_index,
      scene_id: params.scene_id,
    }
    this._lastContextSource = "task"
    this._lastContextRequestParams = params
    const output = document.getElementById("gen-task-output")
    if (output) output.innerHTML = '<div class="loading">编译中...</div>'
    let controller = null
    try {
      this._setBusy(true)
      controller = this._trackRequestController()
      const data = await api.context.compile(params, { signal: controller.signal })
      this._lastContextBundle = data
      this._generateSubTab = "preview"
      this._persistState()
      await this._refreshView()
    } catch (err) {
      const message = `编译失败：${esc(err.message || "未知错误")}`
      if (output) {
        output.innerHTML = `<p style="color:var(--danger);font-size:13px;">${message}</p>`
      }
      if (!silent) {
        toast(message, "error")
      }
    } finally {
      this._releaseRequestController(controller)
      this._setBusy(false)
    }
  }
```

- [ ] **Step 4：在 `_viewGenerationContext` 的 finally 中释放控制器**

```javascript
// 旧代码
    try {
      this._setBusy(true)
      const controller = this._trackRequestController()
      const data = await api.context.compile(params, { signal: controller.signal })
      this._releaseRequestController(controller)
      this._lastContextBundle = data
      this._lastContextSource = "chat"
      this._lastContextRequestParams = params
      this._generateSubTab = "preview"
      this._persistState()
      await this._refreshView()
    } catch (err) {
      toast(`编译失败：${err.message || "未知错误"}`, "error")
    } finally {
      this._setBusy(false)
    }
```

```javascript
// 新代码
    let controller = null
    try {
      this._setBusy(true)
      controller = this._trackRequestController()
      const data = await api.context.compile(params, { signal: controller.signal })
      this._lastContextBundle = data
      this._lastContextSource = "chat"
      this._lastContextRequestParams = params
      this._generateSubTab = "preview"
      this._persistState()
      await this._refreshView()
    } catch (err) {
      toast(`编译失败：${err.message || "未知错误"}`, "error")
    } finally {
      this._releaseRequestController(controller)
      this._setBusy(false)
    }
```

- [ ] **Step 5：运行单元测试**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console
npm test -- --run tests/generateView.test.js
```

Expected: `37 passed`（加上新增测试后数量相应增加，全部通过）

- [ ] **Step 6：提交**

```bash
git add frontend-console/views/generateView.js frontend-console/tests/generateView.test.js
git commit -m "fix(generate): 任务按钮忙状态与 AbortController 泄漏"
```

---

## Task 6：最终验证

- [ ] **Step 1：前端单元测试**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console
npm test -- --run tests/generateView.test.js
```

Expected: 全部通过

- [ ] **Step 2：生成中心 E2E**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console
npm run test:e2e -- e2e/generate.spec.js
```

Expected: `9 passed`

- [ ] **Step 3：后端相关测试**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/backend
python -m pytest modules/world/tests/test_object_draft_chatbox_api.py modules/world/tests/test_generation_prompt_templates.py -q
```

Expected: `16 passed`

- [ ] **Step 4：Lint**

```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist
make lint
```

Expected: `All checks passed!`

- [ ] **Step 5：提交验证结果（可选）**

如果 CI/本地验证全部通过，可打 tag 或备注；本任务无需新增代码提交。

---

## Self-Review

**1. Spec coverage（用户需求覆盖）**

- 检查生成中心前端组件：已覆盖 `generateView.js` 任务/上下文预览/角色视角状态、事件、请求生命周期；已检查 `api.js`、`tests/setup.js` 等周边文件，无需改动。
- 检查对应后端服务：已确认 `object_draft_generation_service.py`、路由 `api.py`、schema 与测试工作正常，本计划仅验证不修改。
- 完整详细修复计划：每项变更均给出文件、行号、旧代码、新代码、测试命令与预期结果。

**2. Placeholder scan**

- 无 `TBD` / `TODO` / `implement later` / `fill in details`。
- 无“适当处理异常”这类模糊描述；每个代码块均给出可直接应用的代码。
- 无未定义的函数或类型引用。

**3. Type consistency**

- `viewpoint_character_id` 在 `_taskForm`、`_readTaskForm`、`_compileTaskContext`、`_applyTaskPresetValues`、单元测试与 E2E 中保持一致，均为 `string | undefined`。
- `_setBusy` 新增的 `[data-action="run-task"]` 等选择器与 HTML 中 `data-action` 属性一致。
- `_releaseRequestController` 已兼容 `null` 入参。

---

## Execution Handoff

**计划已保存到 `docs/superpowers/plans/2026-07-07-generate-center-repair-plan.md`。两种执行方式：**

**1. Subagent-Driven（推荐）** — 每个 Task 派一个子 Agent 执行，我负责逐步 Review，迭代快、风险低。

**2. Inline Execution** — 在当前会话按 Task 顺序一次性执行，适合改动量小、上下文连续的情况。

请选择执行方式。