import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import { cleanupProject, createEntity, createProject, listEntityTypes, waitForBackend } from "./helpers/api-client.js"

test.describe("世界对象入口", () => {
  let testProjectIds = []

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.afterEach(async () => {
    for (const projectId of testProjectIds) {
      try { await cleanupProject(projectId) } catch {}
    }
    testProjectIds = []
  })

  test("world objects entry stays on object management instead of forcing map", async ({ page }) => {
    const project = await createProject({
      title: "世界对象入口回归测试",
      genre: "fantasy",
      language: "zh",
    })
    testProjectIds.push(project.id)

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
    await expect(page.locator(".world-object-card-grid")).toContainText("沉钟港")

    const filterToggle = page.locator('[data-action="toggle-filter-panel"][data-filter-key="objects"]')
    await expect(filterToggle).toContainText("展开筛选")
    await expect(filterToggle).toHaveAttribute("aria-expanded", "false")
    await expect(page.locator("#filter-q")).toBeHidden()
    await filterToggle.click()
    await expect(filterToggle).toHaveAttribute("aria-expanded", "true")
    await expect(page.locator("#filter-q")).toBeVisible()

    await page.reload()
    await expect(filterToggle).toHaveAttribute("aria-expanded", "true")
    await expect(page.locator("#filter-q")).toBeVisible()

    await page.locator('.bulk-toolbar__select-all input[data-action="bulk-toggle-all"]').check()
    const selectedRows = page.locator('.world-object-card input[data-action="bulk-toggle-one"]')
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

    await page.locator(SEL.navItem("map")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("地图")
    await expect(page).toHaveURL(new RegExp(`#workbench/${project.id}/map`))
    await expect(page.getByRole("heading", { name: "AI 地图册" })).toBeVisible()

    await page.locator(SEL.navItem("world")).click()

    await expect(page).toHaveURL(new RegExp(`#workbench/${project.id}/world/objects`))
    await expect(page.locator(SEL.viewTitle)).toHaveText("人物与世界")
    await expect(page.locator(SEL.subnavItem("objects"))).toHaveClass(/active/)
    await expect(page.locator(".world-object-card-grid")).toContainText("沉钟港")
    await expect(page).not.toHaveURL(/\/map/)
  })

  test("candidate can be adopted as a custom type and filtered only in its project", async ({ page }) => {
    const project = await createProject({
      title: "世界对象自定义类型测试",
      genre: "fantasy",
      language: "zh",
    })
    const otherProject = await createProject({
      title: "世界对象类型隔离测试",
      genre: "fantasy",
      language: "zh",
    })
    testProjectIds.push(project.id, otherProject.id)
    const candidate = await createEntity(project.id, {
      name: "月廷",
      entity_type: "organization",
      status: "candidate",
      summary: "待确认的月神教团",
    })

    await openWorkbench(page, project, "world", "review-objects")
    const row = page.locator(`tr[data-id="${candidate.id}"]`)
    await expect(row).toContainText("月廷")
    await row.getByRole("button", { name: "编辑后采用" }).click()
    await page.locator("#edit-entity-type").selectOption("__custom_entity_type__")
    await page.locator("#edit-custom-entity-type").fill("宗教/神祇")
    await page.locator(SEL.modalFooter).getByRole("button", { name: "编辑后采用" }).click()

    await page.locator(SEL.subnavItem("objects")).click()
    await expect(page.locator(".world-object-card-grid")).toContainText("月廷")
    await expect(page.locator(".world-object-card-grid")).toContainText("宗教/神祇")
    const filterToggle = page.locator('[data-action="toggle-filter-panel"][data-filter-key="objects"]')
    if (await page.locator("#filter-entity-type").isHidden()) await filterToggle.click()
    await page.locator("#filter-entity-type").selectOption("宗教/神祇")
    await page.getByRole("button", { name: "应用", exact: true }).click()
    await expect(page).toHaveURL(/entity_type=%E5%AE%97%E6%95%99%2F%E7%A5%9E%E7%A5%87/)
    await expect(page.locator(".world-object-card-grid")).toContainText("月廷")

    const ownCatalog = await listEntityTypes(project.id)
    const otherCatalog = await listEntityTypes(otherProject.id)
    expect(ownCatalog.items.some((item) => item.value === "宗教/神祇")).toBe(true)
    expect(otherCatalog.items.some((item) => item.value === "宗教/神祇")).toBe(false)
  })
})
