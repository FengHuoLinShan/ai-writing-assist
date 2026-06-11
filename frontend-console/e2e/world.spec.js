import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"

test.describe("世界对象模块", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "世界对象测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.evaluate((id) => {
      localStorage.setItem("novel_currentProjectId", id)
      localStorage.setItem("novel_currentProject", JSON.stringify({ id, title: "世界对象测试项目" }))
    }, project.id)
    await page.reload()

    // 导航到世界视图
    await page.locator(SEL.navItem("world")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("世界对象")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("对象库空态显示新建按钮", async ({ page }) => {
    await expect(page.locator(SEL.emptyState)).toBeVisible()
    await expect(page.locator("#btn-new-entity")).toBeVisible()
  })

  test("创建世界对象并显示在列表中", async ({ page }) => {
    // Given: 用户在对象库空态页面
    await expect(page.locator("#btn-new-entity")).toBeVisible()

    // When: 点击新建按钮，填写表单并提交
    await page.locator("#btn-new-entity").click()
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建世界对象")

    await page.locator("#create-entity-name").fill("测试城堡")
    await page.locator("#create-entity-type").selectOption("location")
    await page.locator("#create-entity-summary").fill("一座古老的城堡")

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    // Then: 显示创建成功 toast
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    // 刷新页面验证列表
    await page.reload()
    await page.locator(SEL.navItem("world")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("世界对象")

    await expect(page.locator(SEL.dataTable)).toBeVisible()
    await expect(page.locator(SEL.dataTable)).toContainText("测试城堡")
    await expect(page.locator(SEL.dataTable)).toContainText("location")
  })

  test("编辑世界对象", async ({ page }) => {
    // Given: 已存在一个世界对象
    await page.locator("#btn-new-entity").click()
    await page.locator("#create-entity-name").fill("编辑前名称")
    await page.locator("#create-entity-type").selectOption("item")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    // 刷新以显示列表
    await page.reload()
    await page.locator(SEL.navItem("world")).click()
    await expect(page.locator(SEL.dataTable)).toContainText("编辑前名称")

    // When: 点击编辑按钮，修改字段并保存
    await page.locator('[data-action="edit-entity"]').first().click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑世界对象")

    await page.locator("#edit-entity-name").fill("编辑后名称")
    await page.locator("#edit-entity-type").selectOption("faction")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    // Then: 保存成功，刷新后列表更新
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存", { timeout: 10000 })

    await page.reload()
    await page.locator(SEL.navItem("world")).click()
    await expect(page.locator(SEL.dataTable)).toContainText("编辑后名称")
    await expect(page.locator(SEL.dataTable)).toContainText("faction")
  })

  test("删除世界对象", async ({ page }) => {
    // Given: 已存在一个世界对象
    await page.locator("#btn-new-entity").click()
    await page.locator("#create-entity-name").fill("待删除对象")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    // 刷新以显示列表
    await page.reload()
    await page.locator(SEL.navItem("world")).click()
    await expect(page.locator(SEL.dataTable)).toContainText("待删除对象")

    // When: 点击删除按钮，确认删除
    await page.locator('[data-action="delete-entity"]').first().click()

    // confirmAction 使用自定义模态框，点击确认
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()

    // Then: 删除成功，刷新后列表为空
    await expect(page.locator(SEL.toastContainer)).toContainText("已删除", { timeout: 10000 })

    await page.reload()
    await page.locator(SEL.navItem("world")).click()
    await expect(page.locator(SEL.emptyState)).toBeVisible()
  })

  test("关系子标签显示", async ({ page }) => {
    await page.locator(SEL.subnavItem("relations")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("世界对象")
    await expect(page.locator(SEL.subnavItem("relations"))).toHaveClass(/active/)
    await expect(page.locator(SEL.emptyState)).toBeVisible()
  })

  test("别名子标签显示", async ({ page }) => {
    await page.locator(SEL.subnavItem("aliases")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("世界对象")
    await expect(page.locator(SEL.subnavItem("aliases"))).toHaveClass(/active/)
    await expect(page.locator(SEL.emptyState)).toBeVisible()
  })
})
