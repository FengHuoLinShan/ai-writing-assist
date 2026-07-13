import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openProjectList, reloadProjectList } from "./helpers/workbench.js"
import {
  API_BASE,
  createProject,
  cleanupProject,
  deleteProject,
  waitForBackend,
} from "./helpers/api-client.js"

test.describe("项目回收站", () => {
  let testProjectId = null
  let testProjectIds = []

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    await openProjectList(page)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
    for (const projectId of testProjectIds) {
      try { await cleanupProject(projectId) } catch {}
    }
    testProjectIds = []
  })

  test("软删除后项目进入回收站并可恢复", async ({ page }) => {
    const project = await createProject({
      title: "回收站恢复测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await reloadProjectList(page)
    const card = page.locator(SEL.projectCard(project.id))
    await expect(card).toBeVisible()

    // hover 显示操作按钮并删除
    await card.hover()
    await card.locator('[data-action="delete-project"]').click()

    // 确认删除
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()

    // 等待软删除 toast
    await expect(page.locator(SEL.toastContainer)).toContainText("已移至回收站", { timeout: 15000 })

    // 项目从列表消失
    await reloadProjectList(page)
    await expect(page.locator(SEL.projectCard(project.id))).toHaveCount(0)

    // 打开回收站
    await page.locator('[data-action="recycle-bin"]').click()
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.locator(SEL.modalTitle)).toHaveText("回收站")
    await expect(page.locator(SEL.modalBody)).toContainText("回收站恢复测试项目")

    // 恢复项目
    await page.locator(`.restore-project-btn[data-id="${project.id}"]`).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已恢复", { timeout: 10000 })

    // 刷新后项目回到列表
    await reloadProjectList(page)
    await expect(page.locator(SEL.projectCard(project.id))).toContainText("回收站恢复测试项目")
  })

  test("永久删除项目后不可恢复", async ({ page }) => {
    const project = await createProject({
      title: "永久删除测试项目",
      genre: "scifi",
      language: "zh",
    })
    testProjectId = project.id

    await reloadProjectList(page)
    const card = page.locator(SEL.projectCard(project.id))
    await expect(card).toBeVisible()

    // hover 显示操作按钮并删除
    await card.hover()
    await card.locator('[data-action="delete-project"]').click()

    // 确认删除
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()

    await expect(page.locator(SEL.toastContainer)).toContainText("已移至回收站", { timeout: 15000 })

    // 打开回收站
    await reloadProjectList(page)
    await page.locator('[data-action="recycle-bin"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("回收站")
    await expect(page.locator(SEL.modalBody)).toContainText("永久删除测试项目")

    // 永久删除
    await page.locator(`.perm-delete-project-btn[data-id="${project.id}"]`).click()
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.locator(SEL.modalBody)).toContainText("不可恢复")
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()

    await expect(page.locator(SEL.toastContainer)).toContainText("已永久删除", { timeout: 10000 })

    // 回收站中不再显示
    await expect(page.locator(SEL.modalBody)).not.toContainText("永久删除测试项目", { timeout: 10000 })

    // 验证项目确实已不存在（通过API）
    const resp = await fetch(`${API_BASE}/projects/${project.id}`)
    expect(resp.status).toBe(404)
  })

  test("批量永久删除回收站项目", async ({ page }) => {
    const projects = await Promise.all([
      createProject({ title: "批量永久删除测试 A", language: "zh" }),
      createProject({ title: "批量永久删除测试 B", language: "zh" }),
    ])
    testProjectIds = projects.map((project) => project.id)
    await Promise.all(testProjectIds.map((projectId) => deleteProject(projectId)))

    await reloadProjectList(page)
    await page.locator('[data-action="recycle-bin"]').click()
    for (const project of projects) {
      await page.locator(`.recycle-project-checkbox[data-id="${project.id}"]`).check()
    }

    await page.locator("#recycle-bulk-delete").click()
    await expect(page.locator(SEL.modalBody)).toContainText("不可恢复")
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()

    await expect(page.locator(SEL.toastContainer)).toContainText("已永久删除 2 个项目")
    for (const project of projects) {
      await expect(page.locator(SEL.modalBody)).not.toContainText(project.title)
      const response = await fetch(`${API_BASE}/projects/${project.id}`)
      expect(response.status).toBe(404)
    }
  })
})
