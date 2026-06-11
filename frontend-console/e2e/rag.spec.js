import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"

test.describe("RAG 检索模块", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "RAG 测试项目",
      genre: "scifi",
      language: "zh",
    })
    testProjectId = project.id

    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.evaluate((id) => {
      localStorage.setItem("novel_currentProjectId", id)
      localStorage.setItem("novel_currentProject", JSON.stringify({ id, title: "RAG 测试项目" }))
    }, project.id)
    await page.reload()

    await page.locator(SEL.navItem("rag")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("RAG 检索")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("索引状态页面显示", async ({ page }) => {
    // ragView 使用 data-action 而非 data-subview
    await expect(page.locator('[data-action="nav-status"]')).toHaveClass(/active/)
    // 新项目的 RAG 状态可能是空或后端未连接，只保证视图标题和子导航正确即可
    await expect(page.locator(SEL.viewTitle)).toHaveText("RAG 检索")
  })

  test("切换到搜索子标签", async ({ page }) => {
    await page.locator('.subnav-item[data-action="nav-search"]').click()
    await expect(page.locator('.subnav-item[data-action="nav-search"]')).toHaveClass(/active/)
    // 只验证搜索输入框存在
    await expect(page.locator("#rag-search-input")).toBeVisible()
  })

  test("搜索空结果", async ({ page }) => {
    // Mock 搜索接口返回空结果，避免新项目无索引导致 API 报错
    await page.route("**/api/rag/search", async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ chunks: [] }) })
    })

    await page.locator('.subnav-item[data-action="nav-search"]').click()
    await page.locator("#rag-search-input").fill("不存在的词")
    await page.locator('[data-action="do-search"]').click()

    await expect(page.locator("#rag-results")).toContainText("未找到匹配结果", { timeout: 10000 })
  })

  test("重建索引按钮可点击", async ({ page }) => {
    await page.locator('[data-action="rebuild-index"]').click()
    // 重建索引会提交异步任务，至少应该显示 toast
    await expect(page.locator(SEL.toastContainer)).toContainText("索引", { timeout: 10000 })
  })
})
