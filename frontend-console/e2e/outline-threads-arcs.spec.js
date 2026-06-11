import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"

test.describe("Outline View — 剧情线与篇章纲", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "剧情线篇章纲测试",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.evaluate((id) => {
      localStorage.setItem("novel_currentProjectId", id)
      localStorage.setItem("novel_currentProject", JSON.stringify({ id, title: "剧情线篇章纲测试" }))
    }, project.id)
    await page.reload()

    await page.locator(SEL.navItem("outline")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("大纲")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("创建剧情线并显示在列表中", async ({ page }) => {
    // Given: 用户在剧情线子标签
    await page.locator('[data-action="nav-threads"]').click()
    await expect(page.locator('[data-action="nav-threads"]')).toHaveClass(/active/)
    await expect(page.locator(SEL.emptyState)).toContainText("暂无剧情线")

    // When: 点击新建剧情线，填写表单并提交
    await page.locator('[data-action="create-thread"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建剧情线")

    await page.locator("#create-thread-name").fill("主线剧情")
    await page.locator("#create-thread-type").selectOption("main")
    await page.locator("#create-thread-desc").fill("主角成长的主线故事")

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("剧情线已创建", { timeout: 10000 })

    // Then: 刷新后列表显示新剧情线
    await page.reload()
    await page.locator(SEL.navItem("outline")).click()
    await page.locator('[data-action="nav-threads"]').click()
    await expect(page.locator(SEL.dataTable)).toBeVisible()
    await expect(page.locator(SEL.dataTable)).toContainText("主线剧情")
    await expect(page.locator(SEL.dataTable)).toContainText("main")
  })

  test("编辑剧情线", async ({ page }) => {
    // Given: 已存在一个剧情线
    await page.locator('[data-action="nav-threads"]').click()
    await page.locator('[data-action="create-thread"]').click()
    await page.locator("#create-thread-name").fill("原始剧情线")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("剧情线已创建", { timeout: 10000 })

    // 刷新以显示列表
    await page.reload()
    await page.locator(SEL.navItem("outline")).click()
    await page.locator('[data-action="nav-threads"]').click()
    await expect(page.locator(SEL.dataTable)).toContainText("原始剧情线")

    // When: 点击编辑按钮，修改字段并保存
    await page.locator('[data-action="edit-thread"]').first().click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑剧情线")

    await page.locator("#edit-thread-name").fill("修改后的剧情线")
    await page.locator("#edit-thread-type").selectOption("sub")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存", { timeout: 10000 })

    // Then: 刷新后列表更新
    await page.reload()
    await page.locator(SEL.navItem("outline")).click()
    await page.locator('[data-action="nav-threads"]').click()
    await expect(page.locator(SEL.dataTable)).toContainText("修改后的剧情线")
    await expect(page.locator(SEL.dataTable)).toContainText("sub")
  })

  test("删除剧情线", async ({ page }) => {
    // Given: 已存在一个剧情线
    await page.locator('[data-action="nav-threads"]').click()
    await page.locator('[data-action="create-thread"]').click()
    await page.locator("#create-thread-name").fill("待删除剧情线")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("剧情线已创建", { timeout: 10000 })

    // 刷新以显示列表
    await page.reload()
    await page.locator(SEL.navItem("outline")).click()
    await page.locator('[data-action="nav-threads"]').click()
    await expect(page.locator(SEL.dataTable)).toContainText("待删除剧情线")

    // When: 点击删除按钮，确认删除
    await page.locator('[data-action="delete-thread"]').first().click()
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已删除", { timeout: 10000 })

    // Then: 刷新后列表为空
    await page.reload()
    await page.locator(SEL.navItem("outline")).click()
    await page.locator('[data-action="nav-threads"]').click()
    await expect(page.locator(SEL.emptyState)).toContainText("暂无剧情线")
  })

  test("创建篇章纲并显示在列表中", async ({ page }) => {
    // Given: 用户在篇章纲子标签
    await page.locator('[data-action="nav-arcs"]').click()
    await expect(page.locator('[data-action="nav-arcs"]')).toHaveClass(/active/)
    await expect(page.locator(SEL.emptyState)).toContainText("暂无篇章纲")

    // When: 点击新建篇章纲，填写表单并提交
    await page.locator('[data-action="create-arc"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建篇章纲")

    await page.locator("#create-arc-name").fill("第一卷")
    await page.locator("#create-arc-start").fill("1")
    await page.locator("#create-arc-end").fill("10")
    await page.locator("#create-arc-desc").fill("主角初入江湖")

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("篇章纲已创建", { timeout: 10000 })

    // Then: 刷新后列表显示新篇章纲
    await page.reload()
    await page.locator(SEL.navItem("outline")).click()
    await page.locator('[data-action="nav-arcs"]').click()
    await expect(page.locator(SEL.dataTable)).toBeVisible()
    await expect(page.locator(SEL.dataTable)).toContainText("第一卷")
    await expect(page.locator(SEL.dataTable)).toContainText("1")
    await expect(page.locator(SEL.dataTable)).toContainText("10")
  })

  test("编辑篇章纲", async ({ page }) => {
    // Given: 已存在一个篇章纲
    await page.locator('[data-action="nav-arcs"]').click()
    await page.locator('[data-action="create-arc"]').click()
    await page.locator("#create-arc-name").fill("原始篇章")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("篇章纲已创建", { timeout: 10000 })

    // 刷新以显示列表
    await page.reload()
    await page.locator(SEL.navItem("outline")).click()
    await page.locator('[data-action="nav-arcs"]').click()
    await expect(page.locator(SEL.dataTable)).toContainText("原始篇章")

    // When: 点击编辑按钮，修改字段并保存
    await page.locator('[data-action="edit-arc"]').first().click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑篇章纲")

    await page.locator("#edit-arc-name").fill("修改后的篇章")
    await page.locator("#edit-arc-end").fill("20")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存", { timeout: 10000 })

    // Then: 刷新后列表更新
    await page.reload()
    await page.locator(SEL.navItem("outline")).click()
    await page.locator('[data-action="nav-arcs"]').click()
    await expect(page.locator(SEL.dataTable)).toContainText("修改后的篇章")
    await expect(page.locator(SEL.dataTable)).toContainText("20")
  })

  test("删除篇章纲", async ({ page }) => {
    // Given: 已存在一个篇章纲
    await page.locator('[data-action="nav-arcs"]').click()
    await page.locator('[data-action="create-arc"]').click()
    await page.locator("#create-arc-name").fill("待删除篇章")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("篇章纲已创建", { timeout: 10000 })

    // 刷新以显示列表
    await page.reload()
    await page.locator(SEL.navItem("outline")).click()
    await page.locator('[data-action="nav-arcs"]').click()
    await expect(page.locator(SEL.dataTable)).toContainText("待删除篇章")

    // When: 点击删除按钮，确认删除
    await page.locator('[data-action="delete-arc"]').first().click()
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已删除", { timeout: 10000 })

    // Then: 刷新后列表为空
    await page.reload()
    await page.locator(SEL.navItem("outline")).click()
    await page.locator('[data-action="nav-arcs"]').click()
    await expect(page.locator(SEL.emptyState)).toContainText("暂无篇章纲")
  })
})
