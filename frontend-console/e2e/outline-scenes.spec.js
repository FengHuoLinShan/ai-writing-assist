import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"

test.describe("Outline View — 场景工作台", () => {
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

  test("outline/scenes 直接显示场景工作台", async ({ page }) => {
    const scenesTab = page.locator('[data-action="nav-scenes"]')
    await expect(scenesTab).toHaveClass(/active/)
    await expect(scenesTab).toHaveText("场景工作台")

    await expect(page.locator('[aria-label="Scene 管理筛选"]')).toBeVisible()
    await expect(page.locator('.nav-item[data-view="scene"]')).toHaveCount(0)
  })

  test("从大纲其他子标签返回场景工作台", async ({ page }) => {
    await page.locator('[data-action="nav-threads"]').click()
    await page.locator('[data-action="nav-scenes"]').click()

    await expect(page.locator(SEL.viewTitle)).toHaveText("大纲")
    await expect(page.locator('[aria-label="Scene 管理筛选"]')).toBeVisible()
  })
})
