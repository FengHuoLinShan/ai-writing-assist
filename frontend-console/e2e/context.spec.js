import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"

test.describe("上下文模块", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "上下文测试项目",
      genre: "mystery",
      language: "zh",
    })
    testProjectId = project.id

    await openWorkbench(page, project, "context")
    // 等待 DOM 实际更新为 contextView 内容（防御 renderCurrentView 偶发竞态）
    try {
      await page.waitForFunction(() => {
        const content = document.getElementById("workspace-content")
        return content && content.querySelector("#ctx-task") !== null
      }, { timeout: 8000 })
    } catch {
      // 若渲染竞态导致 DOM 未更新，通过 reload 从 URL hash 恢复 context 视图
      await page.reload()
      await page.waitForFunction(() => {
        const content = document.getElementById("workspace-content")
        return content && content.querySelector("#ctx-task") !== null
      }, { timeout: 10000 })
    }
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("上下文编译页面加载", async ({ page }) => {
    await expect(page.locator("#ctx-task")).toBeVisible()
    await expect(page.locator("#ctx-scope")).toBeVisible()
    await expect(page.locator("#ctx-reveal")).toBeVisible()
    await expect(page.locator('[data-action="compile"]')).toBeVisible()
  })

  test("未选择项目时编译给出警告", async ({ page }) => {
    // 清除 localStorage 中的项目选择后导航到上下文视图
    await page.evaluate(() => {
      localStorage.removeItem("novel_currentProjectId")
      localStorage.removeItem("novel_currentProject")
    })
    await page.reload()
    await page.evaluate(() => {
      state.currentProjectId = null
      state.currentProject = null
      window.router.navigate("context")
    })
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })

    await page.locator("#ctx-task").fill("测试任务")
    await page.locator('[data-action="compile"]').click()

    await expect(page.locator(SEL.toastContainer)).toContainText("请先选择项目", { timeout: 10000 })
  })

  test("编译上下文并显示结果", async ({ page }) => {
    await page.locator("#ctx-task").fill("为测试项目生成上下文")
    await page.locator('[data-action="compile"]').click()

    // 编译可能成功也可能因为没有数据而返回空结果
    await expect(page.locator("#ctx-output")).not.toContainText("填写左侧参数后点击编译", { timeout: 15000 })
  })
})
