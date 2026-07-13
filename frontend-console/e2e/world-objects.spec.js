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
    await createEntity(project.id, {
      name: "沉钟旧港",
      entity_type: "location",
      status: "canonical",
      summary: "沉钟港的旧称",
    })

    await openWorkbench(page, project, "world", "objects")
    await expect(page.locator(SEL.dataTable)).toContainText("沉钟港")

    const filterToggle = page.locator('[data-action="toggle-filter-panel"][data-filter-key="objects"]')
    await expect(filterToggle).toContainText("收起筛选")
    await filterToggle.click()
    await expect(filterToggle).toHaveAttribute("aria-expanded", "false")
    await expect(page.locator("#filter-q")).toBeHidden()

    await page.locator('.bulk-toolbar__select-all input[data-action="bulk-toggle-all"]').check()
    const selectedRows = page.locator('tbody input[data-action="bulk-toggle-one"]')
    await expect(selectedRows).toHaveCount(2)
    await expect(selectedRows.nth(0)).toBeChecked()
    await expect(selectedRows.nth(1)).toBeChecked()
    await expect(page.locator('[data-bulk-action="fuse-entities"]')).toHaveText("融合")
    await expect(page.locator('[data-bulk-action="alias-entities"]')).toHaveText("标记为别名")
    await expect(page.locator('[data-bulk-action="review-entities"]')).toHaveCount(0)
    await expect(page.locator('[data-bulk-action="promote-entities"]')).toHaveCount(0)

    await page.locator('[data-bulk-action="alias-entities"]').click()
    await expect(page.getByText("请选择要保留的主对象：")).toBeVisible()
    await expect(page.locator('input[name="world-bulk-target"]')).toHaveCount(2)
    await page.getByRole("button", { name: "取消" }).click()

    await page.locator(SEL.subnavItem("map")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("地图")
    await expect(page).toHaveURL(new RegExp(`#workbench/${project.id}/map`))
    await expect(page.getByRole("heading", { name: "空间总览" })).toBeVisible()

    await page.locator(SEL.navItem("world")).click()

    await expect(page).toHaveURL(new RegExp(`#workbench/${project.id}/world/objects`))
    await expect(page.locator(SEL.viewTitle)).toHaveText("世界对象")
    await expect(page.locator(SEL.subnavItem("objects"))).toHaveClass(/active/)
    await expect(page.locator(SEL.dataTable)).toContainText("沉钟港")
    await expect(page).not.toHaveURL(/\/map/)
  })
})
