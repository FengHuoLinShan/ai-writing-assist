import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench, reloadWorkbench, waitWritingReady } from "./helpers/workbench.js"
import {
  createProject,
  cleanupProject,
  waitForBackend,
  createDraft,
} from "./helpers/api-client.js"

async function openWritingToolMenu(page, selector) {
  const tool = page.locator(selector)
  const menu = page.locator("details.writing-tools-menu").filter({ has: tool })
  if (await menu.getAttribute("open") === null) {
    await menu.locator(":scope > summary").click()
  }
}

async function clickWritingTool(page, selector) {
  await openWritingToolMenu(page, selector)
  await page.locator(selector).click()
}

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
    await waitWritingReady(page)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("409 冲突 — 其他会话已发布新版本", async ({ page }) => {
    // Step 1: 通过 API 创建 v1 草稿
    const d1 = await createDraft(testProjectId, 1, "v1 标题", "v1 内容")

    const draftId = d1.draft.id
    const v1Number = d1.draft.version_number

    // Step 2: 真实导航加载第 1 章 v1
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await page.getByRole("button", { name: /打开第 1 章/ }).click()
    await expect(page.locator("#writing-editor")).toHaveValue("v1 内容", { timeout: 5000 })

    // Step 3: 模拟另一个会话发布 v2（提升章节最新版本号）
    await createDraft(testProjectId, 1, "v2 标题", "v2 内容")

    // Step 4: 在当前页面编辑并暂存（expected_version 仍为 v1）
    await page.locator("#writing-editor").fill("v3 内容 — 冲突")
    await clickWritingTool(page, "#btn-autosave")

    // Step 5: 应收到 409 冲突 toast
    await expect(page.locator(SEL.toastContainer)).toContainText("已被其他会话更新", { timeout: 10000 })
  })

  test("409 冲突 — 其他 Tab 已暂存同一草稿", async ({ browser }) => {
    // Step 1: 通过 API 创建 v1 草稿
    const d1 = await createDraft(testProjectId, 1, "v1 标题", "v1 内容")

    // Step 2: 打开两个 Tab
    const context = await browser.newContext()
    const pageA = await context.newPage()
    const pageB = await context.newPage()

    try {
      for (const page of [pageA, pageB]) {
        await openWorkbench(page, { id: testProjectId, title: "冲突测试项目" }, "writing")
        await waitWritingReady(page, { chapter: 1 })
        await page.getByRole("button", { name: /打开第 1 章/ }).click()
        await expect(page.locator("#writing-editor")).toHaveValue("v1 内容", { timeout: 5000 })
      }

      // Step 3: Tab A 编辑并暂存
      await pageA.locator("#writing-editor").fill("Tab A 内容")
      await clickWritingTool(pageA, "#btn-autosave")
      await expect(pageA.locator("#writing-save-status")).toHaveText("已保存到工作稿", { timeout: 10000 })

      // Step 4: Tab B 再暂存应收到 409
      await pageB.locator("#writing-editor").fill("Tab B 内容")
      await clickWritingTool(pageB, "#btn-autosave")
      await expect(pageB.locator(SEL.toastContainer)).toContainText("已被其他会话更新", { timeout: 10000 })
    } finally {
      await context.close()
    }
  })
})
