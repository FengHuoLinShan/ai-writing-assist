import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench, reloadWorkbench } from "./helpers/workbench.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"

test.describe("Outline View — 伏笔与揭示", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "伏笔揭示 E2E 测试",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openWorkbench(page, project, "outline", "foreshadowing")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("伏笔 CRUD", async ({ page }) => {
    // Given: 打开伏笔子标签，显示空态
    await expect(page.locator('[data-action="nav-foreshadowing"]')).toHaveClass(/active/)
    await expect(page.locator(SEL.emptyState)).toContainText("暂无伏笔")

    // When: 新建伏笔
    await page.locator('[data-action="create-foreshadowing"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建伏笔")

    await page.locator("#create-foreshadowing-description").fill("古剑封印松动")
    await page.locator("#create-foreshadowing-target-chapter").fill("3")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("伏笔已创建", { timeout: 10000 })

    // Then: 刷新后列表显示新伏笔
    await reloadWorkbench(page, "outline", "foreshadowing")
    await expect(page.locator(SEL.dataTable)).toContainText("古剑封印松动")
    await expect(page.locator(SEL.dataTable)).toContainText("3")

    // When: 修改状态为 triggered
    await page.locator(".foreshadowing-status-select").first().selectOption("triggered")
    await expect(page.locator(SEL.toastContainer)).toContainText("伏笔状态已更新", { timeout: 10000 })
    await expect(page.locator(SEL.dataTable)).toContainText("已触发")

    // When: 编辑伏笔
    await page.locator('[data-action="edit-foreshadowing"]').first().click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑伏笔")

    await page.locator("#edit-foreshadowing-description").fill("古剑封印即将崩溃")
    await page.locator("#edit-foreshadowing-target-chapter").fill("5")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("伏笔已保存", { timeout: 10000 })

    // Then: 刷新后列表更新
    await reloadWorkbench(page, "outline", "foreshadowing")
    await expect(page.locator(SEL.dataTable)).toContainText("古剑封印即将崩溃")
    await expect(page.locator(SEL.dataTable)).toContainText("5")

    // When: 删除伏笔并确认
    await page.locator('[data-action="delete-foreshadowing"]').first().click()
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已删除", { timeout: 10000 })

    // Then: 刷新后列表为空
    await reloadWorkbench(page, "outline", "foreshadowing")
    await expect(page.locator(SEL.emptyState)).toContainText("暂无伏笔")
  })

  test("揭示 CRUD", async ({ page }) => {
    // Given: 先创建一个伏笔，用于可选关联
    await page.locator('[data-action="create-foreshadowing"]').click()
    await page.locator("#create-foreshadowing-description").fill("神秘符文伏笔")
    await page.locator("#create-foreshadowing-target-chapter").fill("2")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("伏笔已创建", { timeout: 10000 })

    // When: 切换到揭示子标签
    await page.locator('[data-action="nav-reveals"]').click()
    await expect(page.locator('[data-action="nav-reveals"]')).toHaveClass(/active/)
    await expect(page.locator(SEL.emptyState)).toContainText("暂无揭示")

    // When: 新建揭示
    await page.locator('[data-action="create-reveal"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建揭示")

    await page.locator("#create-reveal-description").fill("符文指向失落古城")
    await page.locator("#create-reveal-chapter").fill("6")
    await expect(page.locator("#create-reveal-foreshadowing-id")).toContainText("无")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("揭示已创建", { timeout: 10000 })

    // Then: 刷新后列表显示新揭示
    await reloadWorkbench(page, "outline", "reveals")
    await expect(page.locator(SEL.dataTable)).toContainText("符文指向失落古城")
    await expect(page.locator(SEL.dataTable)).toContainText("6")

    // When: 修改状态为 revealed
    await page.locator(".reveal-status-select").first().selectOption("revealed")
    await expect(page.locator(SEL.toastContainer)).toContainText("揭示状态已更新", { timeout: 10000 })
    await expect(page.locator(SEL.dataTable)).toContainText("已揭示")

    // When: 编辑揭示
    await page.locator('[data-action="edit-reveal"]').first().click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑揭示")

    await page.locator("#edit-reveal-description").fill("符文揭示古城入口")
    await page.locator("#edit-reveal-chapter").fill("8")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("揭示已保存", { timeout: 10000 })

    // Then: 刷新后列表更新
    await reloadWorkbench(page, "outline", "reveals")
    await expect(page.locator(SEL.dataTable)).toContainText("符文揭示古城入口")
    await expect(page.locator(SEL.dataTable)).toContainText("8")

    // When: 删除揭示并确认
    await page.locator('[data-action="delete-reveal"]').first().click()
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已删除", { timeout: 10000 })

    // Then: 刷新后列表为空
    await reloadWorkbench(page, "outline", "reveals")
    await expect(page.locator(SEL.emptyState)).toContainText("暂无揭示")
  })

  test("novel_id 隔离：其他项目的伏笔列表为空", async ({ page }) => {
    // Given: 当前项目已有一条伏笔
    await page.locator('[data-action="create-foreshadowing"]').click()
    await page.locator("#create-foreshadowing-description").fill("当前项目伏笔")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("伏笔已创建", { timeout: 10000 })

    // When: 创建另一个项目并打开其伏笔标签
    const otherProject = await createProject({
      title: "隔离测试项目",
      genre: "scifi",
      language: "zh",
    })

    try {
      await openWorkbench(page, otherProject, "outline", "foreshadowing")

      // Then: 另一个项目的伏笔列表为空
      await expect(page.locator(SEL.emptyState)).toContainText("暂无伏笔")
      await expect(page.locator(SEL.dataTable)).toHaveCount(0)
    } finally {
      try { await cleanupProject(otherProject.id) } catch {}
    }
  })

  test("结构资产筛选可定位深度导入的伏笔和揭示", async ({ page }) => {
    const foreshadowingItems = [
      {
        id: "f-import",
        name: "导入伏笔",
        summary: "导入伏笔",
        planned_seed_chapter: 2,
        status: "abandoned",
        provenance_meta: { source: "deep_import", workflow_id: "wf-structure-e2e", needs_review: true, phase: "structure_analysis" },
      },
      {
        id: "f-manual",
        name: "人工伏笔",
        summary: "人工伏笔",
        planned_seed_chapter: 3,
        status: "planted",
        provenance_meta: { source: "manual", needs_review: false },
      },
    ]
    const revealItems = [
      {
        id: "r-import",
        secret_summary: "导入揭示",
        reveal_stages: [{ stage_index: 0, chapter_index: 6, reveal_content: "导入揭示" }],
        status: "abandoned",
        provenance_meta: { source: "deep_import", workflow_id: "wf-structure-e2e", needs_review: true, phase: "structure_analysis" },
      },
      {
        id: "r-manual",
        secret_summary: "人工揭示",
        reveal_stages: [{ stage_index: 0, chapter_index: 8, reveal_content: "人工揭示" }],
        status: "planned",
        provenance_meta: { source: "manual", needs_review: false },
      },
    ]
    await page.route("**/api/outline/foreshadowing**", async (route) => {
      const url = new URL(route.request().url())
      const filtered = url.searchParams.get("source") === "deep_import"
      await route.fulfill({ json: { items: filtered ? [foreshadowingItems[0]] : foreshadowingItems, total: filtered ? 1 : 2 } })
    })
    await page.route("**/api/outline/reveals**", async (route) => {
      const url = new URL(route.request().url())
      const filtered = url.searchParams.get("source") === "deep_import"
      await route.fulfill({ json: { items: filtered ? [revealItems[0]] : revealItems, total: filtered ? 1 : 2 } })
    })

    await reloadWorkbench(page, "outline", "foreshadowing")
    await page.locator("#outline-filter-status").selectOption("abandoned")
    await page.locator("#outline-filter-source").selectOption("deep_import")
    await page.locator("#outline-filter-workflow-id").fill("wf-structure-e2e")
    await page.locator("#outline-filter-needs-review").selectOption("true")
    await page.locator('[data-action="apply-outline-structure-filters"]').click()
    await expect(page.locator(SEL.dataTable)).toContainText("导入伏笔")
    await expect(page.locator(SEL.dataTable)).toContainText("深度导入")
    await expect(page.locator(SEL.dataTable)).toContainText("需复核")
    await expect(page.locator(SEL.dataTable)).not.toContainText("人工伏笔")

    await page.locator('[data-action="nav-reveals"]').click()
    await page.locator("#outline-filter-status").selectOption("abandoned")
    await page.locator("#outline-filter-source").selectOption("deep_import")
    await page.locator("#outline-filter-workflow-id").fill("wf-structure-e2e")
    await page.locator("#outline-filter-needs-review").selectOption("true")
    await page.locator('[data-action="apply-outline-structure-filters"]').click()
    await expect(page.locator(SEL.dataTable)).toContainText("导入揭示")
    await expect(page.locator(SEL.dataTable)).toContainText("深度导入")
    await expect(page.locator(SEL.dataTable)).toContainText("需复核")
    await expect(page.locator(SEL.dataTable)).not.toContainText("人工揭示")
  })
})
