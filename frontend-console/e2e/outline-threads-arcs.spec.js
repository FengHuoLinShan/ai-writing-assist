import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench, reloadWorkbench } from "./helpers/workbench.js"
import { createProject, createThread, cleanupProject, waitForBackend } from "./helpers/api-client.js"
import { expectNoPageOverflow, expectWithinViewportWidth } from "./helpers/responsive.js"

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
    await expect(page.locator(SEL.dataTable)).toContainText("主线")
  })

  test("剧情线与篇章只突出创作入口并渐进展开分析整理工具", async ({ page }) => {
    const threadActions = page.getByLabel("剧情线操作")
    await expect(threadActions.locator(":scope > .btn")).toHaveCount(2)
    await expect(threadActions.locator(":scope > .btn-primary")).toHaveText("新建剧情线")
    await expect(threadActions.locator('[data-action="ai-create-plot-thread"]')).toBeVisible()

    const threadTools = threadActions.locator(".outline-structure-tools")
    const threadSummary = threadTools.locator("summary")
    await expect(threadSummary).toHaveText("分析与整理")
    await expect(threadTools.locator('[data-action="analyze-outline"]')).toBeHidden()

    await threadSummary.focus()
    await page.keyboard.press("Enter")
    await expect(threadTools).toHaveAttribute("open", "")
    await expect(threadTools.locator('[data-action="plot-structure-auto-extract"]')).toHaveText("从正文提取剧情线")
    await expect(threadTools.locator('[data-action="start-smart-dedup"]')).toBeVisible()

    const analyze = threadTools.locator('[data-action="analyze-outline"]')
    await analyze.focus()
    await page.keyboard.press("Enter")
    await expect(page.locator(SEL.modalTitle)).toHaveText("AI 分析大纲")
    await page.keyboard.press("Escape")
    await expect(page.locator(SEL.modalOverlay)).toHaveClass(/hidden/)
    await expect(threadSummary).toBeFocused()

    await page.locator('[data-action="nav-arcs"]').click()
    const arcActions = page.getByLabel("篇章操作")
    await expect(arcActions.locator(":scope > .btn")).toHaveCount(2)
    await expect(arcActions.locator(":scope > .btn-primary")).toHaveText("新建篇章")
    await expect(arcActions.locator('[data-action="ai-create-outline-arc"]')).toBeVisible()
    await arcActions.locator(".outline-structure-tools > summary").click()
    await expect(arcActions.locator('[data-action="plot-structure-auto-extract"]')).toHaveText("从正文整理篇章")

    await page.goBack()
    await expect(page.locator('[data-action="nav-threads"]')).toHaveAttribute("aria-current", "page")
    await page.setViewportSize({ width: 390, height: 844 })
    await page.reload()
    await page.waitForFunction(() => !state.loading)
    await expect(page.getByLabel("剧情线操作")).toBeVisible()

    const compactActions = page.getByLabel("剧情线操作")
    const compactControls = compactActions.locator(":scope > .btn, :scope > details > summary")
    await expect(compactControls).toHaveCount(3)
    const boxes = await compactControls.evaluateAll((elements) => elements.map((element) => {
      const box = element.getBoundingClientRect()
      return { top: Math.round(box.top), height: Math.round(box.height) }
    }))
    expect(new Set(boxes.map(({ top }) => top)).size).toBe(1)
    expect(boxes.every(({ height }) => height >= 44)).toBe(true)
    await expectWithinViewportWidth(compactActions.locator(".outline-structure-tools > summary"))
    await expectNoPageOverflow(page)
  })

  test("剧情线 AI 建议可编辑、恢复并采用，不会串到其他作品", async ({ page, browserErrors, projectFactory }) => {
    const taskId = "task-thread-review-e2e"
    const contextConfirmationId = "context-thread-review-e2e"
    const draftStructure = {
      result: "proposed",
      reuse_judgments: [],
      threads: [{
        proposal_ref: "thread-proposal-e2e",
        target_thread_ref: null,
        name: "失落档案主线",
        thread_type: "main",
        summary: "档案员追查被删除的城市记忆。",
        visible_goal: "找到失踪档案",
        hidden_truth: "档案馆主动删去了历史",
        start_chapter: 1,
        planned_payoff_chapter: 12,
        current_stage: "埋下",
        related_character_refs: [],
        related_entity_refs: [],
        reader_known_state: "读者只知道档案失踪",
        author_known_state: "作者知道馆长参与删改",
        information_movements: [{
          movement_ref: "movement-e2e",
          information_subject: "被删除的城市历史",
          surface_understanding: "事故导致资料缺失",
          hidden_content: "人为抹除",
          target_ref: null,
          nodes: [{ kind: "seed", content: "发现空白目录", chapter_hint: 2, scene_ref: null, trigger: null, effect: null }],
          basis: "总览要求逐步揭露真相。",
          uncertain_fields: [],
          confidence: 0.9,
        }],
        basis: "承接故事总览的记忆主题。",
        uncertain_fields: [],
        confidence: 0.9,
      }],
      story_outline_conflict: null,
      author_decisions: [],
    }
    let applyPayload = null
    await page.route(`**/api/tasks/${taskId}*`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: taskId,
          task_type: "outline_generate",
          status: "done",
          progress: 1,
          result: {
            apply_status: "pending",
            requires_apply: true,
            source_task_id: taskId,
            context_confirmation_id: contextConfirmationId,
            target: "plot_thread",
            mode: "create",
            draft_structure: draftStructure,
            warnings: ["兑现章仍需作者确认"],
            overlap: { plot_threads: [] },
          },
        }),
      })
    })
    await page.route("**/api/outline/generate/apply", async (route) => {
      applyPayload = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ target: "plot_thread", total_threads: 1, total_arcs: 0, total_scenes: 0 }),
      })
    })
    await page.evaluate(({ projectId, sourceTaskId, confirmationId }) => {
      const now = new Date().toISOString()
      localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
        id: `${projectId}:outline_generate:${sourceTaskId}`,
        taskId: sourceTaskId,
        workflowType: "outline_generate",
        label: "剧情线建议",
        projectId,
        view: "outline",
        meta: { target: "plot_thread", mode: "create", label: "剧情线", context_confirmation_id: confirmationId },
        createdAt: now,
        updatedAt: now,
      }]))
      return window.router.navigate("outline", "threads", true, new URLSearchParams("review=ai&status=draft"))
    }, { projectId: testProjectId, sourceTaskId: taskId, confirmationId: contextConfirmationId })

    await expect(page.getByRole("heading", { name: "检查剧情线建议" })).toBeVisible()
    await expect(page.locator("#outline-layer-preview-json")).toHaveCount(0)
    const nameInput = page.locator("#outline-thread-preview-0-name")
    await nameInput.fill("作者修订后的档案主线")
    await expect(page.locator(".outline-thread-review__save-state")).toContainText("修改已暂存在本机")

    await page.goBack()
    await page.waitForFunction(() => !state.loading)
    await expect(page.locator('[data-action="create-thread"]')).toBeVisible()
    await page.goForward()
    await page.waitForFunction(() => !state.loading)
    await expect(page.locator("#outline-thread-preview-0-name")).toHaveValue("作者修订后的档案主线")
    await page.reload()
    await page.waitForFunction(() => !state.loading)
    await expect(page.locator("#outline-thread-preview-0-name")).toHaveValue("作者修订后的档案主线")

    const otherProject = await projectFactory({ title: "另一部作品", genre: "mystery" })
    await openWorkbench(page, otherProject, "outline", "threads")
    await page.evaluate(() => window.router.navigate("outline", "threads", true, new URLSearchParams("review=ai")))
    await expect(page.getByRole("heading", { name: "这份建议暂时无法打开" })).toBeVisible()
    await expect(page.locator("body")).not.toContainText("作者修订后的档案主线")

    await openWorkbench(page, { id: testProjectId, title: "剧情线篇章测试" }, "outline", "threads")
    await page.evaluate(() => window.router.navigate("outline", "threads", true, new URLSearchParams("review=ai")))
    await expect(page.locator("#outline-thread-preview-0-name")).toHaveValue("作者修订后的档案主线")

    await page.setViewportSize({ width: 375, height: 812 })
    await expectNoPageOverflow(page)
    await expect.poll(() => page.locator('[data-action="apply-outline-generate-preview"]').evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
    await page.emulateMedia({ reducedMotion: "reduce" })
    await page.evaluate(() => { document.documentElement.style.fontSize = "125%" })
    await expectNoPageOverflow(page)
    await page.evaluate(() => { document.documentElement.style.fontSize = "" })
    await page.setViewportSize({ width: 844, height: 390 })
    await expectNoPageOverflow(page)

    await page.locator('[data-action="apply-outline-generate-preview"]').click()
    await expect(page.locator('[data-action="create-thread"]')).toBeVisible()
    expect(applyPayload).toEqual({
      novel_id: testProjectId,
      context_confirmation_id: contextConfirmationId,
      source_task_id: taskId,
      draft_structure: expect.objectContaining({
        result: "proposed",
        threads: [expect.objectContaining({ name: "作者修订后的档案主线" })],
      }),
      confirmed: true,
    })
    const persisted = await page.evaluate(({ projectId, sourceTaskId }) => ({
      draft: localStorage.getItem(`novel_outline_thread_preview:${encodeURIComponent(projectId)}:${encodeURIComponent(sourceTaskId)}`),
      workflows: JSON.parse(localStorage.getItem("novel_active_workflows_v1") || "[]"),
    }), { projectId: testProjectId, sourceTaskId: taskId })
    expect(persisted.draft).toBeNull()
    expect(persisted.workflows).not.toEqual(expect.arrayContaining([expect.objectContaining({ taskId })]))
    expect(browserErrors).toEqual([])
  })

  test("篇章 AI 建议可读编辑、刷新恢复并采用，不会串到其他作品", async ({ page, browserErrors, projectFactory }) => {
    const taskId = "task-arc-review-e2e"
    const contextConfirmationId = "context-arc-review-e2e"
    const draftStructure = {
      result: "proposed",
      arcs: [{
        proposal_ref: "arc-proposal-e2e",
        target_arc_ref: null,
        title: "雾港失忆篇",
        arc_index: 1,
        start_chapter: 1,
        end_chapter: 12,
        arc_goal: "让主角发现整座城市都在遗忘同一段历史。",
        core_conflict: "保存真相会让同伴陷入危险。",
        main_opposition: "负责抹除档案的城市议会。",
        entry_hook: "一份空白档案写着主角的名字。",
        midpoint_turn: "同伴承认自己参与过第一次删改。",
        climax: "主角必须公开档案或烧毁唯一证据。",
        result_state: "城市开始质疑官方历史。",
        next_hook: "议会地下库仍藏着更早的记录。",
        related_thread_refs: [],
        related_character_refs: [],
        related_entity_refs: [],
        basis: "承接故事总览中的记忆与控制主题。",
        uncertain_fields: [],
        confidence: 0.9,
      }],
      story_outline_conflict: null,
      author_decisions: [],
    }
    let applyPayload = null
    await page.route(`**/api/tasks/${taskId}*`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: taskId,
          task_type: "outline_generate",
          status: "done",
          progress: 1,
          result: {
            apply_status: "pending",
            requires_apply: true,
            source_task_id: taskId,
            context_confirmation_id: contextConfirmationId,
            target: "outline_arc",
            mode: "create",
            draft_structure: draftStructure,
            warnings: ["结束章仍需作者确认"],
            overlap: { outline_arcs: [] },
          },
        }),
      })
    })
    await page.route("**/api/outline/generate/apply", async (route) => {
      applyPayload = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ target: "outline_arc", total_threads: 0, total_arcs: 1, total_scenes: 0 }),
      })
    })
    await page.locator('[data-action="nav-arcs"]').click()
    await page.evaluate(({ projectId, sourceTaskId, confirmationId }) => {
      const now = new Date().toISOString()
      localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
        id: `${projectId}:outline_generate:${sourceTaskId}`,
        taskId: sourceTaskId,
        workflowType: "outline_generate",
        label: "篇章建议",
        projectId,
        view: "outline",
        meta: { target: "outline_arc", mode: "create", label: "篇章", context_confirmation_id: confirmationId },
        createdAt: now,
        updatedAt: now,
      }]))
      return window.router.navigate("outline", "arcs", true, new URLSearchParams("review=ai&status=draft"))
    }, { projectId: testProjectId, sourceTaskId: taskId, confirmationId: contextConfirmationId })

    await expect(page.getByRole("heading", { name: "检查篇章建议" })).toBeVisible()
    await expect(page.locator("#outline-layer-preview-json")).toHaveCount(0)
    const titleInput = page.locator("#outline-arc-preview-0-title")
    await titleInput.fill("作者修订后的雾港篇")
    await expect(page.locator(".outline-thread-review__save-state")).toContainText("修改已暂存在本机")

    await page.goBack()
    await page.waitForFunction(() => !state.loading)
    await expect(page.locator('[data-action="create-arc"]')).toBeVisible()
    await page.goForward()
    await page.waitForFunction(() => !state.loading)
    await expect(page.locator("#outline-arc-preview-0-title")).toHaveValue("作者修订后的雾港篇")
    await page.reload()
    await page.waitForFunction(() => !state.loading)
    await expect(page.locator("#outline-arc-preview-0-title")).toHaveValue("作者修订后的雾港篇")

    const otherProject = await projectFactory({ title: "另一部篇章作品", genre: "mystery" })
    await openWorkbench(page, otherProject, "outline", "arcs")
    await page.evaluate(() => window.router.navigate("outline", "arcs", true, new URLSearchParams("review=ai")))
    await expect(page.getByRole("heading", { name: "这份建议暂时无法打开" })).toBeVisible()
    await expect(page.locator("body")).not.toContainText("作者修订后的雾港篇")

    await openWorkbench(page, { id: testProjectId, title: "剧情线篇章测试" }, "outline", "arcs")
    await page.evaluate(() => window.router.navigate("outline", "arcs", true, new URLSearchParams("review=ai")))
    await expect(page.locator("#outline-arc-preview-0-title")).toHaveValue("作者修订后的雾港篇")

    await page.setViewportSize({ width: 375, height: 812 })
    await expectNoPageOverflow(page)
    await expect.poll(() => page.locator('[data-action="apply-outline-generate-preview"]').evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
    await page.setViewportSize({ width: 844, height: 390 })
    await expectNoPageOverflow(page)

    await page.locator('[data-action="apply-outline-generate-preview"]').click()
    await expect(page.locator('[data-action="create-arc"]')).toBeVisible()
    expect(applyPayload).toEqual({
      novel_id: testProjectId,
      context_confirmation_id: contextConfirmationId,
      source_task_id: taskId,
      draft_structure: expect.objectContaining({
        result: "proposed",
        arcs: [expect.objectContaining({ title: "作者修订后的雾港篇" })],
      }),
      confirmed: true,
    })
    const persisted = await page.evaluate(({ projectId, sourceTaskId }) => ({
      draft: localStorage.getItem(`novel_outline_arc_preview:${encodeURIComponent(projectId)}:${encodeURIComponent(sourceTaskId)}`),
      workflows: JSON.parse(localStorage.getItem("novel_active_workflows_v1") || "[]"),
    }), { projectId: testProjectId, sourceTaskId: taskId })
    expect(persisted.draft).toBeNull()
    expect(persisted.workflows).not.toEqual(expect.arrayContaining([expect.objectContaining({ taskId })]))
    expect(browserErrors).toEqual([])
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
    await expect(page.locator(SEL.dataTable)).toContainText("支线")
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

  test("结构资产筛选按需展开并可定位深度导入的剧情线和篇章", async ({ page }) => {
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
    let filters = page.locator(".outline-structure-filters")
    let filterSummary = filters.locator(":scope > summary")
    await expect(filters).not.toHaveAttribute("open", "")
    await expect(filterSummary).toContainText("筛选剧情线")
    await expect(filterSummary).toContainText("未启用")
    await filterSummary.focus()
    await page.keyboard.press("Enter")
    await expect(filters).toHaveAttribute("open", "")
    await page.locator("#outline-filter-status").selectOption("deprecated")
    await page.locator("#outline-filter-source").selectOption("deep_import")
    await page.locator(".outline-structure-diagnostic-filters > summary").click()
    await page.locator("#outline-filter-workflow-id").fill("wf-structure-e2e")
    await page.locator("#outline-filter-needs-review").selectOption("true")
    await page.locator('[data-action="apply-outline-structure-filters"]').click()
    await expect(filters).not.toHaveAttribute("open", "")
    await expect(filterSummary).toContainText("已启用 4 项")
    await expect(filterSummary).toBeFocused()
    await expect(page.locator(SEL.dataTable)).toContainText("导入主线")
    await expect(page.locator(SEL.dataTable)).toContainText("深度导入")
    await expect(page.locator(SEL.dataTable)).toContainText("需要人工检查")
    await expect(page.locator(SEL.dataTable)).not.toContainText("人工支线")

    await page.reload()
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })
    await expect(page.locator(SEL.dataTable)).toContainText("导入主线")
    filters = page.locator(".outline-structure-filters")
    filterSummary = filters.locator(":scope > summary")
    await expect(filters).not.toHaveAttribute("open", "")
    await expect(filterSummary).toContainText("已启用 4 项")

    await page.locator('[data-action="nav-arcs"]').click()
    filters = page.locator(".outline-structure-filters")
    filterSummary = filters.locator(":scope > summary")
    await expect(filterSummary).toContainText("筛选篇章")
    await filterSummary.click()
    await page.locator("#outline-filter-status").selectOption("deprecated")
    await page.locator("#outline-filter-source").selectOption("deep_import")
    await page.locator(".outline-structure-diagnostic-filters > summary").click()
    await page.locator("#outline-filter-workflow-id").fill("wf-structure-e2e")
    await page.locator("#outline-filter-needs-review").selectOption("true")
    await page.locator('[data-action="apply-outline-structure-filters"]').click()
    await expect(filters).not.toHaveAttribute("open", "")
    await expect(filterSummary).toContainText("已启用 4 项")
    await expect(page.locator(SEL.dataTable)).toContainText("导入篇章")
    await expect(page.locator(SEL.dataTable)).toContainText("深度导入")
    await expect(page.locator(SEL.dataTable)).toContainText("需要人工检查")
    await expect(page.locator(SEL.dataTable)).not.toContainText("人工篇章")

    await page.goBack()
    await expect(page.locator('[data-action="nav-arcs"]')).toHaveAttribute("aria-current", "page")
    await expect(page.locator(".outline-structure-filters > summary")).toContainText("未启用")
    await page.goForward()
    await expect(page.locator(".outline-structure-filters > summary")).toContainText("已启用 4 项")

    await page.setViewportSize({ width: 390, height: 844 })
    await page.reload()
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })
    filters = page.locator(".outline-structure-filters")
    filterSummary = filters.locator(":scope > summary")
    await expect(filterSummary).toHaveCSS("min-height", "44px")
    await filterSummary.focus()
    await page.keyboard.press("Enter")
    await expect(filters).toHaveAttribute("open", "")
    for (const selector of [
      "#outline-filter-status",
      "#outline-filter-source",
      "#outline-filter-needs-review",
      "#outline-filter-workflow-id",
      '[data-action="apply-outline-structure-filters"]',
      '[data-action="reset-outline-structure-filters"]',
    ]) {
      await expect(page.locator(selector)).toHaveCSS("min-height", "44px")
    }
    await expectWithinViewportWidth(filters)
    await expectNoPageOverflow(page)
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
