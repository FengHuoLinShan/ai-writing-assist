import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench, reloadWorkbench } from "./helpers/workbench.js"
import { createProject, createThread, cleanupProject, waitForBackend } from "./helpers/api-client.js"

test.describe("Outline View — 剧情线与篇章", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "剧情线篇章测试",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openWorkbench(page, project, "outline", "threads")
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
    await reloadWorkbench(page, "outline", "scenes")
    await page.locator('[data-action="nav-threads"]').click()
    await expect(page.locator(SEL.dataTable)).toBeVisible()
    await expect(page.locator(SEL.dataTable)).toContainText("主线剧情")
    await expect(page.locator(SEL.dataTable)).toContainText("main")
  })

  test("行菜单用键盘隔离快捷键、恢复焦点并同步关闭另一行", async ({ page }) => {
    const first = await createThread(testProjectId, { name: "晨雾主线", thread_type: "main", summary: "城市苏醒" })
    const second = await createThread(testProjectId, { name: "港口支线", thread_type: "sub", summary: "旧港秘密" })
    await reloadWorkbench(page, "outline", "threads")

    await page.evaluate(() => {
      window.__actionMenuGenerateCount = 0
      const button = document.createElement("button")
      button.hidden = true
      button.dataset.action = "generate"
      button.addEventListener("click", () => { window.__actionMenuGenerateCount += 1 })
      document.querySelector("#workspace-content")?.appendChild(button)
    })
    const firstTrigger = page.getByRole("button", { name: "晨雾主线的更多操作" })
    const secondTrigger = page.getByRole("button", { name: "港口支线的更多操作" })
    const firstMenu = page.locator(`.action-menu[data-menu-id="thread-actions-${first.id}"]`)
    const secondMenu = page.locator(`.action-menu[data-menu-id="thread-actions-${second.id}"]`)

    await firstTrigger.focus()
    await page.keyboard.press("ArrowDown")
    const firstDelete = firstMenu.getByRole("menuitem", { name: "删除" })
    await expect(firstDelete).toBeFocused()
    await page.keyboard.press("Tab")
    await expect(firstMenu).not.toHaveClass(/open/)
    await expect(firstTrigger).toHaveAttribute("aria-expanded", "false")
    await expect.poll(() => page.evaluate(() => document.activeElement?.classList.contains("action-menu-item"))).toBe(false)

    await firstTrigger.focus()
    await page.keyboard.press("ArrowDown")
    await expect(firstDelete).toBeFocused()
    await page.keyboard.press("g")
    await expect.poll(() => page.evaluate(() => window.__actionMenuGenerateCount)).toBe(0)
    await page.keyboard.press("Escape")
    await expect(firstTrigger).toBeFocused()

    await firstTrigger.click()
    await expect(firstMenu).toHaveClass(/open/)
    await secondTrigger.focus()
    await page.keyboard.press("Enter")
    await expect(firstMenu).not.toHaveClass(/open/)
    await expect(firstTrigger).toHaveAttribute("aria-expanded", "false")
    await expect(secondMenu).toHaveClass(/open/)
    await expect(secondTrigger).toHaveAttribute("aria-expanded", "true")
  })

  test("编辑剧情线", async ({ page }) => {
    // Given: 已存在一个剧情线
    await page.locator('[data-action="nav-threads"]').click()
    await page.locator('[data-action="create-thread"]').click()
    await page.locator("#create-thread-name").fill("原始剧情线")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("剧情线已创建", { timeout: 10000 })

    // 刷新以显示列表
    await reloadWorkbench(page, "outline", "scenes")
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
    await reloadWorkbench(page, "outline", "scenes")
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
    await reloadWorkbench(page, "outline", "scenes")
    await page.locator('[data-action="nav-threads"]').click()
    await expect(page.locator(SEL.dataTable)).toContainText("待删除剧情线")

    // When: 打开该行操作菜单，点击删除并确认
    const threadRow = page.locator("tr").filter({ hasText: "待删除剧情线" })
    await threadRow.locator(".action-menu-btn").click()
    await threadRow.locator('[data-action="delete-thread"]').click()
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已删除", { timeout: 10000 })

    // Then: 刷新后列表为空
    await reloadWorkbench(page, "outline", "scenes")
    await page.locator('[data-action="nav-threads"]').click()
    await expect(page.locator(SEL.emptyState)).toContainText("暂无剧情线")
  })

  test("创建篇章并显示在列表中", async ({ page }) => {
    // Given: 用户在篇章子标签
    await page.locator('[data-action="nav-arcs"]').click()
    await expect(page.locator('[data-action="nav-arcs"]')).toHaveClass(/active/)
    await expect(page.locator(SEL.emptyState)).toContainText("暂无篇章")

    // When: 点击新建篇章，填写表单并提交
    await page.locator('[data-action="create-arc"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建篇章")

    await page.locator("#create-arc-name").fill("第一卷")
    await page.locator("#create-arc-start").fill("1")
    await page.locator("#create-arc-end").fill("10")
    await page.locator("#create-arc-desc").fill("主角初入江湖")

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("篇章已创建", { timeout: 10000 })

    // Then: 刷新后列表显示新篇章
    await reloadWorkbench(page, "outline", "scenes")
    await page.locator('[data-action="nav-arcs"]').click()
    await expect(page.locator(SEL.dataTable)).toBeVisible()
    await expect(page.locator(SEL.dataTable)).toContainText("第一卷")
    await expect(page.locator(SEL.dataTable)).toContainText("1")
    await expect(page.locator(SEL.dataTable)).toContainText("10")
  })

  test("结构资产筛选可定位深度导入的剧情线和篇章", async ({ page }) => {
    const threadItems = [
      {
        id: "t-import",
        name: "导入主线",
        thread_type: "main",
        status: "deprecated",
        provenance_meta: { source: "deep_import", workflow_id: "wf-structure-e2e", needs_review: true, phase: "structure_analysis" },
      },
      {
        id: "t-manual",
        name: "人工支线",
        thread_type: "sub",
        status: "canonical",
        provenance_meta: { source: "manual", needs_review: false },
      },
    ]
    const arcItems = [
      {
        id: "a-import",
        title: "导入篇章",
        start_chapter: 1,
        end_chapter: 5,
        status: "deprecated",
        provenance_meta: { source: "deep_import", workflow_id: "wf-structure-e2e", needs_review: true, phase: "structure_analysis" },
      },
      {
        id: "a-manual",
        title: "人工篇章",
        start_chapter: 6,
        end_chapter: 8,
        status: "canonical",
        provenance_meta: { source: "manual", needs_review: false },
      },
    ]
    await page.route("**/api/outline/threads**", async (route) => {
      const url = new URL(route.request().url())
      const filtered = url.searchParams.get("source") === "deep_import"
      await route.fulfill({ json: { items: filtered ? [threadItems[0]] : threadItems, total: filtered ? 1 : 2 } })
    })
    await page.route("**/api/outline/arcs**", async (route) => {
      const url = new URL(route.request().url())
      const filtered = url.searchParams.get("source") === "deep_import"
      await route.fulfill({ json: { items: filtered ? [arcItems[0]] : arcItems, total: filtered ? 1 : 2 } })
    })

    await reloadWorkbench(page, "outline", "threads")
    await page.locator("#outline-filter-status").selectOption("deprecated")
    await page.locator("#outline-filter-source").selectOption("deep_import")
    await page.locator(".outline-structure-diagnostic-filters > summary").click()
    await page.locator("#outline-filter-workflow-id").fill("wf-structure-e2e")
    await page.locator("#outline-filter-needs-review").selectOption("true")
    await page.locator('[data-action="apply-outline-structure-filters"]').click()
    await expect(page.locator(SEL.dataTable)).toContainText("导入主线")
    await expect(page.locator(SEL.dataTable)).toContainText("深度导入")
    await expect(page.locator(SEL.dataTable)).toContainText("需要人工检查")
    await expect(page.locator(SEL.dataTable)).not.toContainText("人工支线")

    await page.locator('[data-action="nav-arcs"]').click()
    await page.locator("#outline-filter-status").selectOption("deprecated")
    await page.locator("#outline-filter-source").selectOption("deep_import")
    await page.locator(".outline-structure-diagnostic-filters > summary").click()
    await page.locator("#outline-filter-workflow-id").fill("wf-structure-e2e")
    await page.locator("#outline-filter-needs-review").selectOption("true")
    await page.locator('[data-action="apply-outline-structure-filters"]').click()
    await expect(page.locator(SEL.dataTable)).toContainText("导入篇章")
    await expect(page.locator(SEL.dataTable)).toContainText("深度导入")
    await expect(page.locator(SEL.dataTable)).toContainText("需要人工检查")
    await expect(page.locator(SEL.dataTable)).not.toContainText("人工篇章")
  })

  test("编辑篇章", async ({ page }) => {
    // Given: 已存在一个篇章
    await page.locator('[data-action="nav-arcs"]').click()
    await page.locator('[data-action="create-arc"]').click()
    await page.locator("#create-arc-name").fill("原始篇章")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("篇章已创建", { timeout: 10000 })

    // 刷新以显示列表
    await reloadWorkbench(page, "outline", "scenes")
    await page.locator('[data-action="nav-arcs"]').click()
    await expect(page.locator(SEL.dataTable)).toContainText("原始篇章")

    // When: 点击编辑按钮，修改字段并保存
    await page.locator('[data-action="edit-arc"]').first().click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑篇章")

    await page.locator("#edit-arc-name").fill("修改后的篇章")
    await page.locator("#edit-arc-end").fill("20")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存", { timeout: 10000 })

    // Then: 刷新后列表更新
    await reloadWorkbench(page, "outline", "scenes")
    await page.locator('[data-action="nav-arcs"]').click()
    await expect(page.locator(SEL.dataTable)).toContainText("修改后的篇章")
    await expect(page.locator(SEL.dataTable)).toContainText("20")
  })

  test("删除篇章", async ({ page }) => {
    // Given: 已存在一个篇章
    await page.locator('[data-action="nav-arcs"]').click()
    await page.locator('[data-action="create-arc"]').click()
    await page.locator("#create-arc-name").fill("待删除篇章")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("篇章已创建", { timeout: 10000 })

    // 刷新以显示列表
    await reloadWorkbench(page, "outline", "scenes")
    await page.locator('[data-action="nav-arcs"]').click()
    await expect(page.locator(SEL.dataTable)).toContainText("待删除篇章")

    // When: 打开该行操作菜单，点击删除并确认
    const arcRow = page.locator("tr").filter({ hasText: "待删除篇章" })
    await arcRow.locator(".action-menu-btn").click()
    await arcRow.locator('[data-action="delete-arc"]').click()
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已删除", { timeout: 10000 })

    // Then: 刷新后列表为空
    await reloadWorkbench(page, "outline", "scenes")
    await page.locator('[data-action="nav-arcs"]').click()
    await expect(page.locator(SEL.emptyState)).toContainText("暂无篇章")
  })
})
