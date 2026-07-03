import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"

test.describe("Outline View — 场景工作台兼容入口", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "场景入口 E2E 测试",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openWorkbench(page, project, "outline", "scenes")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("旧 outline/scenes 入口显示场景工作台跳转页", async ({ page }) => {
    const scenesTab = page.locator('[data-action="nav-scenes"]')
    await expect(scenesTab).toHaveClass(/active/)
    await expect(scenesTab).toHaveText("场景工作台")

    await expect(page.locator(SEL.emptyState)).toContainText("场景工作台已作为一级工作区")
    await expect(page.locator('[data-action="open-scene-workbench"]')).toBeVisible()
  })

  test("点击兼容入口进入一级场景工作台", async ({ page }) => {
    await page.locator('[data-action="open-scene-workbench"]').click()

    await expect(page.locator(SEL.viewTitle)).toHaveText("场景")
    await expect(page.locator('[aria-label="Scene 管理筛选"]')).toBeVisible()
  })
})
