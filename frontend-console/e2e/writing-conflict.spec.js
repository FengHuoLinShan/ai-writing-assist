import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import {
  createProject, cleanupProject, waitForBackend,
} from "./helpers/api-client.js"

test.describe("写作工作台 — 版本冲突", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "冲突测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openWorkbench(page, project, "writing")
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("409 冲突 — 其他会话已更新草稿版本", async ({ page }) => {
    // Step 1: 通过 API 创建 v1 草稿
    const API_BASE = "http://localhost:8000/api"
    const d1 = await (await fetch(`${API_BASE}/writing/drafts?novel_id=${encodeURIComponent(testProjectId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        novel_id: testProjectId,
        chapter_index: 1,
        title: "v1 标题",
        content: "v1 内容",
      }),
    })).json()

    const draftId = d1.draft.id
    const v1Number = d1.draft.version_number

    // Step 2: 在页面中注入 v1 状态
    await page.evaluate((args) => {
      writingView._currentChapter = 1
      writingView._currentDraftId = args.draftId
      writingView._currentVersionNumber = args.v1Number
      writingView._chapterList = [1]
      writingView._chapters[1] = { title: "v1 标题", draftCount: 1 }
      writingView._currentContent = "v1 内容"
      writingView._currentTitle = "v1 标题"
      writingView._isReadonly = false
      writingView._lastSavedContent = "v1 内容"
      return writingView._rerender()
    }, { draftId, v1Number })

    await expect(page.locator("#writing-editor")).toHaveValue("v1 内容", { timeout: 5000 })

    // Step 3: 模拟另一个会话更新同一草稿（提升版本号）
    await fetch(`${API_BASE}/writing/drafts/${draftId}?novel_id=${encodeURIComponent(testProjectId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: "v2 标题",
        content: "v2 内容",
        expected_version: v1Number,
      }),
    })

    // Step 4: 在当前页面编辑并暂存（expected_version 仍为 v1）
    await page.locator("#writing-editor").fill("v3 内容 — 冲突")
    await page.locator('[data-action="autosave"]').click()

    // Step 5: 应收到 409 冲突 toast
    await expect(page.locator(SEL.toastContainer)).toContainText("已被其他会话更新", { timeout: 10000 })
  })
})
