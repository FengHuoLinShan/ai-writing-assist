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
    // 如果数据库中已有项目，则检查表格；否则检查空态
    const emptyState = page.locator(SEL.emptyState)
    const table = page.locator(SEL.dataTable)
    if (await emptyState.isVisible().catch(() => false)) {
      await expect(page.locator("#btn-create-project")).toBeVisible()
    } else {
      await expect(table).toBeVisible()
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
    await expect(page.locator(SEL.dataTable)).toBeVisible()
    await expect(page.locator(SEL.dataTable)).toContainText("列表测试项目")
    // 前端直接显示 genre 原始值，不做中文映射
    await expect(page.locator(SEL.dataTable)).toContainText("scifi")
  })

  test("编辑项目信息", async ({ page }) => {
    const project = await createProject({
      title: "编辑前标题",
      genre: "mystery",
      language: "zh",
    })
    testProjectId = project.id

    await page.reload()
    await expect(page.locator(SEL.dataTable)).toBeVisible()

    // 点击编辑按钮
    const editBtn = page.locator('[data-action="edit-project"]')
    await editBtn.first().click()

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
    await expect(page.locator(SEL.dataTable)).toBeVisible()
    await expect(page.locator(SEL.dataTable)).toContainText("编辑后标题")
  })

  test("删除项目", async ({ page }) => {
    const project = await createProject({
      title: "待删除项目",
      genre: "romance",
      language: "zh",
    })
    testProjectId = project.id

    await page.reload()
    await expect(page.locator(SEL.dataTable)).toContainText("待删除项目")

    // 点击删除按钮
    const deleteBtn = page.locator('[data-action="delete-project"]')
    await deleteBtn.first().click()

    // 确认删除弹窗
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.locator(SEL.modalBody)).toContainText("确定要删除")

    // 确认弹窗的确定按钮是 btn-danger（来自 confirmAction）
    const confirmBtn = page.locator(SEL.modalFooter).locator(SEL.btnDanger)
    await confirmBtn.click()

    // 等待删除成功 toast
    await expect(page.locator(SEL.toastContainer)).toContainText("已删除", { timeout: 15000 })

    // 刷新页面验证项目已消失
    await page.reload()
    await expect(page.locator(SEL.dataTable)).not.toContainText("待删除项目", { timeout: 15000 })
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
    await expect(page.locator(SEL.dataTable)).toBeVisible()

    // 点击项目行
    await page.locator(SEL.clickableRow).first().click()

    // 应切换到世界视图的对象库
    await expect(page.locator(SEL.viewTitle)).toHaveText("世界对象", { timeout: 10000 })
    await expect(page.locator(SEL.topbarProject)).toContainText("点击切换项目")
  })
})
