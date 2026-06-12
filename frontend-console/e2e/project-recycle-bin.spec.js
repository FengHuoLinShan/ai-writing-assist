import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"

test.describe("项目回收站", () => {
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
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("软删除后项目进入回收站并可恢复", async ({ page }) => {
    const project = await createProject({
      title: "回收站恢复测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await page.reload()
    await expect(page.locator(SEL.projectGrid)).toBeVisible({ timeout: 10000 })
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
    await page.reload()
    await expect(page.locator(SEL.projectGrid)).toBeVisible({ timeout: 10000 })
    await expect(page.locator(SEL.projectCard(project.id))).toHaveCount(0)

    // 打开回收站
    await page.locator('[data-action="recycle-bin"]').click()
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.locator(SEL.modalTitle)).toHaveText("回收站")
    await expect(page.locator(SEL.modalBody)).toContainText("回收站恢复测试项目")

    // 恢复项目
    await page.locator('.restore-project-btn').click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已恢复", { timeout: 10000 })

    // 刷新后项目回到列表
    await page.reload()
    await expect(page.locator(SEL.projectGrid)).toBeVisible({ timeout: 10000 })
    await expect(page.locator(SEL.projectCard(project.id))).toContainText("回收站恢复测试项目")
  })

  test("永久删除项目后不可恢复", async ({ page }) => {
    const project = await createProject({
      title: "永久删除测试项目",
      genre: "scifi",
      language: "zh",
    })
    testProjectId = project.id

    await page.reload()
    await expect(page.locator(SEL.projectGrid)).toBeVisible({ timeout: 10000 })
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
    await page.reload()
    await page.locator('[data-action="recycle-bin"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("回收站")
    await expect(page.locator(SEL.modalBody)).toContainText("永久删除测试项目")

    // 永久删除
    await page.locator('.perm-delete-project-btn').click()
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.locator(SEL.modalBody)).toContainText("不可恢复")
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()

    await expect(page.locator(SEL.toastContainer)).toContainText("已永久删除", { timeout: 10000 })

    // 回收站中不再显示
    await expect(page.locator(SEL.modalBody)).not.toContainText("永久删除测试项目", { timeout: 10000 })

    // 验证项目确实已不存在（通过API）
    const API_BASE = "http://localhost:8000/api"
    const resp = await fetch(`${API_BASE}/projects/${project.id}`)
    expect(resp.status).toBe(404)
  })
})
