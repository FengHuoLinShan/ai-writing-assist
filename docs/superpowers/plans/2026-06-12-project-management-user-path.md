# 项目创建与管理用户路径实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成后端 project 模块已具备的能力与前端 projectView / 工作台面包屑的打通，确保作者可在首页完成项目创建、列表选择、工作台内编辑、软删除、回收站恢复与永久删除，并通过单测与 E2E 验收。

**Architecture:** 复用现有三层模块结构（models/schemas/repositories/services/api）与 vanilla JS 前端路由；后端仅做必要补充，前端补齐字段展示、编辑表单与面包屑同步。

**Tech Stack:** Python 3.13 + FastAPI + SQLAlchemy async + SQLite/PostgreSQL；前端 vanilla JS + Playwright E2E + Vitest 单测。

---

## 前置上下文

- 后端 `backend/modules/project/` 已实现 CRUD、软删除、恢复、永久删除、默认 `language=zh` / `default_reveal_policy=author_safe`、404/422 错误处理，38 个单测全部通过。
- 前端 `frontend-console/views/projectView.js` 已实现创建、列表、编辑、软删除、回收站 UI，但缺少“创建时间”展示、编辑字段不齐（缺 `tone`/`target_length`）、空标题提示文案与需求不符。
- 面包屑（`#topbar-project`）由 `state.js` 在 `currentProject` 变更时自动刷新，因此编辑后只需正确赋值 `state.currentProject`。
- E2E 测试 `e2e/project.spec.js` 与 `e2e/project-recycle-bin.spec.js` 已覆盖核心路径，但需要随 UI 调整同步更新断言。

---

## Task 1: 后端 API 层补测试（HTTP 级 422 / 404）

**Files:**
- Create: `backend/modules/project/tests/test_project_api.py`
- Modify: `backend/modules/project/api.py`（如需要，当前已满足需求）

- [ ] **Step 1: 编写 HTTP 级测试**

```python
"""
Project API 层测试

通过 async_client 验证 HTTP 契约：创建、列表、编辑、软删除、
恢复、永久删除、空标题 422、404。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from modules.project.schemas import ProjectCreate


@pytest.fixture
async def sample_project(async_client: AsyncClient):
    resp = await async_client.post("/api/projects", json={"title": "API 测试小说"})
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_create_project(async_client: AsyncClient) -> None:
    resp = await async_client.post("/api/projects", json={"title": "HTTP 创建测试"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "HTTP 创建测试"
    assert data["language"] == "zh"
    assert data["default_reveal_policy"] == "author_safe"


@pytest.mark.asyncio
async def test_create_project_empty_title_returns_422(async_client: AsyncClient) -> None:
    resp = await async_client.post("/api/projects", json={"title": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_projects_paginated(async_client: AsyncClient, sample_project: dict) -> None:
    resp = await async_client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert len(data["items"]) >= 1


@pytest.mark.asyncio
async def test_get_project_not_found(async_client: AsyncClient) -> None:
    fake_id = str(uuid.uuid4())
    resp = await async_client.get(f"/api/projects/{fake_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_project(async_client: AsyncClient, sample_project: dict) -> None:
    pid = sample_project["id"]
    resp = await async_client.put(
        f"/api/projects/{pid}",
        json={"tone": "黑暗", "target_length": "novel"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tone"] == "黑暗"
    assert data["target_length"] == "novel"


@pytest.mark.asyncio
async def test_soft_delete_and_restore(async_client: AsyncClient, sample_project: dict) -> None:
    pid = sample_project["id"]

    resp = await async_client.delete(f"/api/projects/{pid}")
    assert resp.status_code == 204

    resp = await async_client.get(f"/api/projects/{pid}")
    assert resp.status_code == 404

    resp = await async_client.get("/api/projects/recycle-bin")
    assert resp.status_code == 200
    assert any(p["id"] == pid for p in resp.json()["items"])

    resp = await async_client.post(f"/api/projects/{pid}/restore")
    assert resp.status_code == 200
    assert resp.json()["deleted_at"] is None


@pytest.mark.asyncio
async def test_permanent_delete_only_after_soft_delete(async_client: AsyncClient, sample_project: dict) -> None:
    pid = sample_project["id"]

    # 未软删不能直接永久删除
    resp = await async_client.delete(f"/api/projects/{pid}/permanent")
    assert resp.status_code == 404

    await async_client.delete(f"/api/projects/{pid}")
    resp = await async_client.delete(f"/api/projects/{pid}/permanent")
    assert resp.status_code == 204

    resp = await async_client.get(f"/api/projects/{pid}")
    assert resp.status_code == 404

    resp = await async_client.get("/api/projects/recycle-bin")
    assert resp.status_code == 200
    assert not any(p["id"] == pid for p in resp.json()["items"])
```

- [ ] **Step 2: 运行新增 API 测试**

Run: `cd backend && python -m pytest modules/project/tests/test_project_api.py -v`
Expected: 7 passed

- [ ] **Step 3: 运行全部 project 模块测试**

Run: `cd backend && python -m pytest modules/project/tests/ -v`
Expected: 45 passed

---

## Task 2: 前端 projectView.js 补齐需求

**Files:**
- Modify: `frontend-console/views/projectView.js`

### 2.1 创建项目空标题提示

- [ ] **Step 1: 修改 showCreateForm 校验提示**

将第 369 行：
```js
            toast("请输入项目名称", "warning")
```
替换为：
```js
            toast("请输入项目标题", "warning")
```

### 2.2 项目列表展示创建时间

- [ ] **Step 2: 修改 render 中项目卡片时间展示**

将第 51-52 行：
```js
        const status = p.status || "active"
        const isCanonical = status === "active" || status === "canonical"
        const updated = p.updated_at ? new Date(p.updated_at).toLocaleDateString("zh-CN") : ""
```
替换为：
```js
        const status = p.status || "active"
        const isCanonical = status === "active" || status === "canonical"
        const created = p.created_at ? new Date(p.created_at).toLocaleDateString("zh-CN") : ""
```

将第 65-67 行：
```js
            <div class="project-meta">
              ${updated ? `更新于 ${updated}` : "刚刚创建"}
            </div>
```
替换为：
```js
            <div class="project-meta">
              ${created ? `创建于 ${created}` : "刚刚创建"}
            </div>
```

### 2.3 编辑表单增加风格基调与目标规模

- [ ] **Step 3: 扩展 editProject 表单字段与保存逻辑**

将第 188-206 行的 `editProject` 表单 HTML 与保存逻辑整体替换为：

```js
  editProject(id) {
    const project = state.projects.find((p) => p.id === id)
    if (!project) return

    const formHtml = `
      <div class="form-group">
        <label>项目标题</label>
        <input class="form-input" id="edit-title" value="${esc(project.title || project.name || "")}" />
      </div>
      <div class="form-group">
        <label>题材</label>
        <input class="form-input" id="edit-genre" value="${esc(project.genre || "")}" />
      </div>
      <div class="form-group">
        <label>风格基调</label>
        <input class="form-input" id="edit-tone" value="${esc(project.tone || "")}" placeholder="如：黑暗、幽默、写实" />
      </div>
      <div class="form-group">
        <label>目标规模</label>
        <select class="form-select" id="edit-target-length">
          <option value="">未设置</option>
          <option value="short" ${project.target_length === "short" ? "selected" : ""}>短篇</option>
          <option value="medium" ${project.target_length === "medium" ? "selected" : ""}>中篇</option>
          <option value="novel" ${project.target_length === "novel" ? "selected" : ""}>长篇</option>
          <option value="epic" ${project.target_length === "epic" ? "selected" : ""}>史诗</option>
        </select>
      </div>
    `

    showModal("编辑项目", formHtml, [
      {
        text: "保存",
        class: "btn-primary",
        handler: async () => {
          const title = document.getElementById("edit-title")?.value
          const genre = document.getElementById("edit-genre")?.value
          const tone = document.getElementById("edit-tone")?.value
          const targetLength = document.getElementById("edit-target-length")?.value

          if (!title) {
            toast("请输入项目标题", "warning")
            return
          }

          const payload = {
            title,
            genre: genre || null,
            tone: tone || null,
            target_length: targetLength || null,
          }

          try {
            const updated = await api.projects.update(id, payload)
            const idx = state.projects.findIndex((p) => p.id === id)
            if (idx >= 0) {
              state.projects[idx] = { ...state.projects[idx], ...updated }
            }
            if (state.currentProjectId === id) {
              state.currentProject = { ...state.currentProject, ...updated }
            }
            toast("项目已更新", "success")
            closeModal()
          } catch (err) {
            toast(`保存失败：${err.message}`, "error")
          }
        },
      },
    ])
  },
```

### 2.4 确保面包屑同步

- [ ] **Step 4: 验证 state.currentProject 更新逻辑**

上述 `editProject` 保存成功后已将 `state.currentProject` 替换为 `{ ...state.currentProject, ...updated }`。`state.js` 中 `currentProject` 的 setter 会触发 `updateUIForState("currentProject", value)`，从而刷新 `#topbar-project` 文本。

---

## Task 3: 前端单测更新

**Files:**
- Modify: `frontend-console/tests/projectView.test.js`

- [ ] **Step 1: 更新创建空标题提示断言**

将现有 showCreateForm 相关断言中若检查提示文案的部分（如有）改为 `"请输入项目标题"`；当前测试未直接断言文案，可新增：

```js
    it("空标题提交时提示请输入项目标题", async () => {
      api.projects.create.mockResolvedValue({ id: "p-new", title: "新项目" })
      projectView.showCreateForm()

      const showModalMock = vi.mocked(globalThis.showModal)
      const buttons = showModalMock.mock.calls[0][2]
      const titleInput = document.createElement("input")
      titleInput.id = "create-title"
      titleInput.value = ""
      document.body.appendChild(titleInput)

      await buttons[0].handler()

      expect(api.projects.create).not.toHaveBeenCalled()
      expect(globalThis.toast).toHaveBeenCalledWith("请输入项目标题", "warning")

      titleInput.remove()
    })
```

- [ ] **Step 2: 更新编辑测试覆盖新字段与面包屑同步**

将现有 `editProject` 描述块替换为：

```js
  describe("editProject", () => {
    it("项目存在时调用 showModal", () => {
      state.projects = [{ id: "p1", title: "项目A", genre: "fantasy", tone: "黑暗", target_length: "novel", current_stage: "writing" }]

      projectView.editProject("p1")

      expect(globalThis.showModal).toHaveBeenCalledOnce()
      const showModalMock = vi.mocked(globalThis.showModal)
      const html = showModalMock.mock.calls[0][1]
      expect(html).toContain("项目A")
      expect(html).toContain("edit-tone")
      expect(html).toContain("edit-target-length")
    })

    it("项目不存在时不操作", () => {
      projectView.editProject("nonexistent")
      expect(globalThis.showModal).not.toHaveBeenCalled()
    })

    it("保存成功后同步项目列表与面包屑状态", async () => {
      state.projects = [{ id: "p1", title: "项目A", genre: "fantasy", tone: "黑暗", target_length: "novel" }]
      state.currentProjectId = "p1"
      state.currentProject = { ...state.projects[0] }

      const updated = { id: "p1", title: "项目A-改", genre: "武侠", tone: "热血", target_length: "epic" }
      api.projects.update.mockResolvedValue(updated)

      projectView.editProject("p1")
      const showModalMock = vi.mocked(globalThis.showModal)
      const buttons = showModalMock.mock.calls[0][2]

      const titleInput = document.createElement("input")
      titleInput.id = "edit-title"
      titleInput.value = "项目A-改"
      document.body.appendChild(titleInput)

      const genreInput = document.createElement("input")
      genreInput.id = "edit-genre"
      genreInput.value = "武侠"
      document.body.appendChild(genreInput)

      const toneInput = document.createElement("input")
      toneInput.id = "edit-tone"
      toneInput.value = "热血"
      document.body.appendChild(toneInput)

      const targetSelect = document.createElement("select")
      targetSelect.id = "edit-target-length"
      targetSelect.innerHTML = `<option value="">未设置</option><option value="epic" selected>史诗</option>`
      document.body.appendChild(targetSelect)

      await buttons[0].handler()

      expect(api.projects.update).toHaveBeenCalledWith("p1", {
        title: "项目A-改",
        genre: "武侠",
        tone: "热血",
        target_length: "epic",
      })
      expect(state.projects[0]).toEqual(updated)
      expect(state.currentProject).toEqual(updated)

      titleInput.remove()
      genreInput.remove()
      toneInput.remove()
      targetSelect.remove()
    })
  })
```

- [ ] **Step 3: 运行 projectView 单测**

Run: `cd frontend-console && npm test -- --run projectView.test.js`
Expected: 全部通过

---

## Task 4: E2E 测试更新

**Files:**
- Modify: `frontend-console/e2e/project.spec.js`
- Modify: `frontend-console/e2e/project-recycle-bin.spec.js`

### 4.1 project.spec.js 编辑与面包屑断言

- [ ] **Step 1: 更新 "编辑项目信息" 用例**

将第 77-111 行替换为：

```js
  test("编辑项目信息并同步面包屑", async ({ page }) => {
    const project = await createProject({
      title: "编辑前标题",
      genre: "mystery",
      language: "zh",
    })
    testProjectId = project.id

    await page.reload()
    await expect(page.locator(SEL.projectGrid)).toBeVisible({ timeout: 10000 })
    const card = page.locator(SEL.projectCard(project.id))
    await expect(card).toBeVisible()

    await card.hover()
    const editBtn = card.locator('[data-action="edit-project"]')
    await editBtn.click()

    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑项目")

    await page.locator("#edit-title").fill("编辑后标题")
    await page.locator("#edit-genre").fill("武侠")
    await page.locator("#edit-tone").fill("热血")
    await page.locator("#edit-target-length").selectOption("epic")

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    await expect(page.locator(SEL.modalOverlay)).toHaveClass(/hidden/)
    await expect(page.locator(SEL.toastContainer)).toContainText("项目已更新", { timeout: 10000 })

    // 进入工作台验证面包屑同步刷新
    await card.click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作台", { timeout: 10000 })
    await expect(page.locator(SEL.topbarProject)).toHaveText("编辑后标题", { timeout: 10000 })
  })
```

- [ ] **Step 2: 保持其他用例不变**

`创建项目并自动切换到写作视图`、`创建的项目出现在列表中`、`删除项目`、`点击项目行切换到项目并显示在写作视图` 用例逻辑已覆盖需求，保留原样。

### 4.2 project-recycle-bin.spec.js 保持现状

- [ ] **Step 3: 确认回收站 E2E 无需修改**

当前 `project-recycle-bin.spec.js` 已覆盖：软删除进入回收站、恢复、永久删除不可恢复。仅确认选择器在新 UI 下仍可用（`[data-action="delete-project"]`、`[data-action="recycle-bin"]`、`.restore-project-btn`、`.perm-delete-project-btn` 均未改变）。

---

## Task 5: 验证

- [ ] **Step 1: 后端 project 模块测试**

Run: `cd backend && python -m pytest modules/project/tests/ -v`
Expected: 全部通过

- [ ] **Step 2: 前端 projectView 单测**

Run: `cd frontend-console && npm test -- --run projectView.test.js`
Expected: 全部通过

- [ ] **Step 3: 聚焦 lint（本次修改文件）**

Run:
```bash
cd backend && ruff check modules/project/tests/test_project_api.py modules/project/api.py modules/project/services.py modules/project/repositories.py modules/project/schemas.py
cd frontend-console && npx eslint views/projectView.js tests/projectView.test.js e2e/project.spec.js e2e/project-recycle-bin.spec.js || true
```

若后端无 eslint，仅执行 ruff；前端如无 eslint 配置，跳过或运行 `npm test` 已覆盖的 vitest。

- [ ] **Step 4: 运行 E2E（可选，需服务启动）**

Run:
```bash
cd frontend-console && npm run test:e2e -- project.spec.js project-recycle-bin.spec.js
```

Expected: 全部通过（需确保 `make dev` 已启动）。

---

## Self-Review

1. **Spec coverage:**
   - 空标题 422 + 前端提示 → Task 2.1 + Task 3.1
   - 创建默认 language/zh、default_reveal_policy/author_safe + 跳转 writing → Task 5 验证现有逻辑
   - 首页列表标题/题材/创建时间 + 分页 20 → Task 2.2 + Task 5
   - 工作台编辑标题/题材/风格基调/目标规模 + 面包屑刷新 → Task 2.3
   - 软删除/恢复/永久删除（二次确认） → Task 4 验证现有 E2E
   - 404 不可打开/编辑 → Task 1 HTTP 测试

2. **Placeholder scan:** 无 TBD/TODO，所有代码块完整。

3. **Type consistency:** 后端字段名使用 `target_length`；前端 ID 使用 `edit-target-length`，提交键使用 `target_length`，与 API schema 一致。
