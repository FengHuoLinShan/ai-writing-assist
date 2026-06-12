import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"

test.describe("世界对象 — 关系与别名", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "关系别名测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.evaluate((id) => {
      localStorage.setItem("novel_currentProjectId", id)
      localStorage.setItem("novel_currentProject", JSON.stringify({ id, title: "关系别名测试项目" }))
    }, project.id)
    await page.reload()

    await page.locator(SEL.navItem("world")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("世界对象")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  /*
   * 关系管理 API 已就绪：POST /api/world/relations、DELETE /api/world/relations/:id
   * 前端 worldView.js 通过"关系"子标签提供创建/删除 UI。
   */
  test("创建关系并显示在列表中", async ({ page }) => {
    // Given: 已存在两个实体
    await page.locator("#btn-new-entity").click()
    await page.locator("#create-entity-name").fill("源对象")
    await page.locator("#create-entity-type").selectOption("character_ref")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    await page.locator("#btn-new-entity").click()
    await page.locator("#create-entity-name").fill("目标对象")
    await page.locator("#create-entity-type").selectOption("location")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    // 刷新获取实体 ID
    await page.reload()
    await page.locator(SEL.navItem("world")).click()
    await expect(page.locator(SEL.dataTable)).toContainText("源对象")
    await expect(page.locator(SEL.dataTable)).toContainText("目标对象")

    const sourceId = await page.locator("tr:has-text('源对象')").getAttribute("data-id")
    const targetId = await page.locator("tr:has-text('目标对象')").getAttribute("data-id")

    // When: 切换到关系子标签，创建关系
    await page.locator(SEL.subnavItem("relations")).click()
    await expect(page.locator(SEL.subnavItem("relations"))).toHaveClass(/active/)

    await page.locator('[data-action="create-relation"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建关系")

    await page.locator("#rel-source").fill(sourceId)
    await page.locator("#rel-target").fill(targetId)
    await page.locator("#rel-type").selectOption("ally_of")
    await page.locator("#rel-desc").fill("测试关系描述")

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("关系已创建", { timeout: 10000 })

    // Then: 刷新后列表显示新关系
    await page.reload()
    await page.locator(SEL.navItem("world")).click()
    await page.locator(SEL.subnavItem("relations")).click()
    await expect(page.locator(SEL.dataTable)).toBeVisible()
    await expect(page.locator(SEL.dataTable)).toContainText("ally_of")
  })

  /*
   * 别名管理 API 已就绪：POST /api/world/aliases、DELETE /api/world/entities/:id/aliases
   * 前端 worldView.js 通过"别名"子标签提供创建/删除 UI。
   */
  test("创建别名并显示在列表中", async ({ page }) => {
    // Given: 已存在一个实体
    await page.locator("#btn-new-entity").click()
    await page.locator("#create-entity-name").fill("主角")
    await page.locator("#create-entity-type").selectOption("character_ref")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    // 刷新获取实体 ID
    await page.reload()
    await page.locator(SEL.navItem("world")).click()
    await expect(page.locator(SEL.dataTable)).toContainText("主角")
    const entityId = await page.locator("tr:has-text('主角')").getAttribute("data-id")

    // When: 切换到别名子标签，创建别名
    await page.locator(SEL.subnavItem("aliases")).click()
    await expect(page.locator(SEL.subnavItem("aliases"))).toHaveClass(/active/)

    await page.locator('[data-action="create-alias"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建别名")

    await page.locator("#alias-entity").fill(entityId)
    await page.locator("#alias-text").fill("小名")
    await page.locator("#alias-type").selectOption("nickname")

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("别名已创建", { timeout: 10000 })

    // Then: 刷新后列表显示新别名
    await page.reload()
    await page.locator(SEL.navItem("world")).click()
    await page.locator(SEL.subnavItem("aliases")).click()
    await expect(page.locator(SEL.dataTable)).toBeVisible()
    await expect(page.locator(SEL.dataTable)).toContainText("小名")
    await expect(page.locator(SEL.dataTable)).toContainText("昵称")
  })
})
