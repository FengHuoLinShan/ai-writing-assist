import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import { cleanupProject, createEntity, createProject, waitForBackend } from "./helpers/api-client.js"

test.describe("世界对象入口", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("world objects entry stays on object management instead of forcing map", async ({ page }) => {
    const project = await createProject({
      title: "世界对象入口回归测试",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await createEntity(project.id, {
      name: "沉钟港",
      entity_type: "location",
      status: "canonical",
      summary: "北境航线的旧港口",
    })

    await openWorkbench(page, project, "world", "objects")
    await expect(page.locator(SEL.dataTable)).toContainText("沉钟港")

    await page.locator(SEL.subnavItem("map")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("地图")
    await expect(page).toHaveURL(new RegExp(`#workbench/${project.id}/map`))

    await page.locator(SEL.navItem("world")).click()

    await expect(page).toHaveURL(new RegExp(`#workbench/${project.id}/world/objects`))
    await expect(page.locator(SEL.viewTitle)).toHaveText("世界对象")
    await expect(page.locator(SEL.subnavItem("objects"))).toHaveClass(/active/)
    await expect(page.locator(SEL.dataTable)).toContainText("沉钟港")
    await expect(page).not.toHaveURL(/\/map/)
  })
})
