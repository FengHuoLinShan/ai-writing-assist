import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { createProject, deleteProject, waitForBackend } from "./helpers/api-client.js"

test.describe("项目模块", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.reload()
    await expect(page.locator(SEL.viewTitle)).toHaveText("项目")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try {
        await deleteProject(testProjectId)
      } catch {}
      testProjectId = null
    }
  })

  test("空项目状态显示新建按钮", async ({ page }) => {
    const emptyState = page.locator(SEL.emptyState)
    const grid = page.locator(SEL.projectGrid)
    if (await emptyState.isVisible().catch(() => false)) {
      await expect(page.locator("#btn-create-project")).toBeVisible()
    } else {
      await expect(grid).toBeVisible()
      await expect(page.locator("#btn-create-project")).toBeVisible()
    }
  })

  test("创建项目并自动切换到世界视图", async ({ page }) => {
    await page.locator("#btn-create-project").click()
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建项目")

    await page.locator("#create-title").fill("E2E 测试小说")
    await page.locator("#create-genre").selectOption("fantasy")
    await page.locator("#create-tone").fill("黑暗史诗")

    const modalFooter = page.locator(SEL.modalFooter)
    await modalFooter.locator(SEL.btnPrimary).click()

    // 创建成功后应切换到世界视图
    await expect(page.locator(SEL.viewTitle)).toHaveText("世界对象", { timeout: 10000 })
    await expect(page.locator(SEL.topbarProject)).toContainText("E2E 测试小说")

    // 记录项目ID用于清理
    const projectId = await page.evaluate(() => localStorage.getItem("novel_currentProjectId"))
    testProjectId = projectId
    expect(projectId).toBeTruthy()
  })

  test("创建的项目出现在列表中", async ({ page }) => {
    const project = await createProject({
      title: "列表测试项目",
      genre: "scifi",
      tone: "赛博朋克",
      language: "zh",
    })
    testProjectId = project.id

    await page.reload()
    await expect(page.locator(SEL.projectGrid)).toBeVisible()
    await expect(page.locator(SEL.projectCard(project.id))).toContainText("列表测试项目")
    await expect(page.locator(SEL.projectCard(project.id))).toContainText("scifi")
  })

  test("编辑项目信息", async ({ page }) => {
    const project = await createProject({
      title: "编辑前标题",
      genre: "mystery",
      language: "zh",
    })
    testProjectId = project.id

    await page.reload()
    await expect(page.locator(SEL.projectGrid)).toBeVisible({ timeout: 10000 })
    const card = page.locator(SEL.projectCard(project.id))
    await expect(card).toBeVisible()

    // hover 显示操作按钮
    await card.hover()
    const editBtn = card.locator('[data-action="edit-project"]')
    await editBtn.click()

    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑项目")

    await page.locator("#edit-title").fill("编辑后标题")
    await page.locator("#edit-genre").fill("武侠")
    await page.locator("#edit-stage").selectOption("writing")

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    // 等待模态框关闭
    await expect(page.locator(SEL.modalOverlay)).toHaveClass(/hidden/)

    // 前端编辑后不会自动刷新列表，需要手动刷新页面验证
    await page.reload()
    await expect(page.locator(SEL.projectGrid)).toBeVisible({ timeout: 10000 })
    await expect(page.locator(SEL.projectCard(project.id))).toContainText("编辑后标题")
  })

  test("删除项目", async ({ page }) => {
    const project = await createProject({
      title: "待删除项目",
      genre: "romance",
      language: "zh",
    })
    testProjectId = project.id

    await page.reload()
    await expect(page.locator(SEL.projectGrid)).toBeVisible({ timeout: 10000 })
    const card = page.locator(SEL.projectCard(project.id))
    await expect(card).toBeVisible()

    // hover 显示操作按钮
    await card.hover()
    const deleteBtn = card.locator('[data-action="delete-project"]')
    await deleteBtn.click()

    // 确认删除弹窗
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.locator(SEL.modalBody)).toContainText("确定要删除")

    // 确认弹窗的确定按钮是 btn-danger（来自 confirmAction）
    const confirmBtn = page.locator(SEL.modalFooter).locator(SEL.btnDanger)
    await confirmBtn.click()

    // 等待删除成功 toast（软删除 → 回收站）
    await expect(page.locator(SEL.toastContainer)).toContainText("已移至回收站", { timeout: 15000 })

    // 刷新页面验证项目已消失
    await page.reload()
    await expect(page.locator(SEL.projectCard(project.id))).toHaveCount(0, { timeout: 15000 })
    testProjectId = null
  })

  test("点击项目行切换到项目并显示在世界视图", async ({ page }) => {
    const project = await createProject({
      title: "点击切换项目",
      genre: "wuxia",
      language: "zh",
    })
    testProjectId = project.id

    await page.reload()
    await expect(page.locator(SEL.projectGrid)).toBeVisible({ timeout: 10000 })
    const card = page.locator(SEL.projectCard(project.id))
    await expect(card).toBeVisible()

    // 点击项目卡片
    await card.click()

    // 应切换到世界视图的对象库
    await expect(page.locator(SEL.viewTitle)).toHaveText("世界对象", { timeout: 10000 })
    await expect(page.locator(SEL.topbarProject)).toContainText("点击切换项目")
  })
})
