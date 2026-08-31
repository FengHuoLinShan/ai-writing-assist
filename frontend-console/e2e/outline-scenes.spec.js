import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { createScene, createStoryOutlineRevision, waitForBackend } from "./helpers/api-client.js"
import { expectNoPageOverflow, expectWithinViewport } from "./helpers/responsive.js"

test.describe("Outline View — 场景工作台", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ projectFactory, openProjectWorkbench }) => {
    const project = await projectFactory({
      title: "场景入口 E2E 测试",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openProjectWorkbench(project, "outline", "scenes")
  })

  test("outline/scenes 直接显示场景工作台", async ({ page }) => {
    const scenesTab = page.locator('[data-action="nav-scenes"]')
    await expect(scenesTab).toHaveClass(/active/)
    await expect(scenesTab).toHaveText("场景")

    await expect(page.locator('[aria-label="场景筛选"]')).toBeVisible()
    await expect(page.locator('.nav-item[data-view="scene"]')).toHaveCount(0)
  })

  test("场景筛选默认收起、保留未应用草稿并在应用后回到列表", async ({ page, browserErrors, projectFactory, openProjectWorkbench }) => {
    await createScene(testProjectId, {
      scene_index: 0,
      title: "潮门初启",
      goal: "让主角第一次看见退潮遗迹",
      core_conflict: "救人会错过唯一入口",
      chapter_ids: ["1"],
    })
    await page.reload()
    await page.waitForFunction(() => !state.loading)

    const filters = page.locator(".scene-workbench-filters")
    const summary = filters.locator(":scope > summary")
    await expect(filters).not.toHaveAttribute("open", "")
    await expect(summary).toContainText("搜索与筛选")
    await expect(summary).toContainText("未启用")

    await summary.focus()
    await summary.press("Enter")
    await expect(filters).toHaveAttribute("open", "")
    const search = page.locator("#scene-filter-q")
    await search.fill("潮门")
    await summary.press("Enter")
    await expect(filters).not.toHaveAttribute("open", "")
    await expect(summary).toContainText("有未应用修改")

    await page.locator('[data-action="nav-threads"]').click()
    await expect(page).toHaveURL(/\/outline\/threads/)
    await page.locator('.subnav-item[data-action="nav-scenes"]').click()
    await expect(page).toHaveURL(/\/outline\/scenes/)
    await expect(filters).not.toHaveAttribute("open", "")
    await expect(summary).toContainText("有未应用修改")
    await summary.click()
    await expect(search).toHaveValue("潮门")

    const otherProject = await projectFactory({ title: "另一部筛选作品", genre: "mystery" })
    await openProjectWorkbench(otherProject, "outline", "scenes")
    await expect(summary).toContainText("未启用")
    await summary.click()
    await expect(search).toHaveValue("")

    await openProjectWorkbench({ id: testProjectId, title: "场景入口 E2E 测试" }, "outline", "scenes")
    await expect(summary).toContainText("有未应用修改")
    await page.reload()
    await page.waitForFunction(() => !state.loading)
    await summary.click()
    await expect(search).toHaveValue("潮门")

    await page.locator('[data-action="toggle-advanced-scene-filters"]').click()
    await expect(page.locator("#scene-filter-phase")).toBeVisible()
    await expect(filters).not.toContainText("Phase 1A")
    await page.locator('[data-action="apply-scene-filters"]').click()
    await expect(filters).not.toHaveAttribute("open", "")
    await expect(summary).toBeFocused()
    await expect(summary).toContainText("已启用 1 项")
    await expect(summary).not.toContainText("未应用修改")
    await expect(page.locator(".scene-workbench-row", { hasText: "潮门初启" })).toBeVisible()

    await page.locator('.theme-dot[data-theme-value="night"]').click()
    await page.setViewportSize({ width: 375, height: 812 })
    await page.emulateMedia({ reducedMotion: "reduce" })
    await page.locator("html").evaluate((element) => { element.style.fontSize = "125%" })
    await expectNoPageOverflow(page)
    await expect(page.locator(SEL.toastItems)).toHaveCount(0, { timeout: 10000 })
    await summary.focus()
    await summary.press("Enter")
    for (const control of await filters.locator("input:not([type=checkbox]):visible, select:visible, button:visible, summary:visible, label.scene-filter-checkbox:visible").all()) {
      expect(await control.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
    }
    await expectNoPageOverflow(page)
    await page.setViewportSize({ width: 844, height: 390 })
    await expectNoPageOverflow(page)
    await page.locator('[data-action="reset-scene-filters"]').click()
    await expect(filters).not.toHaveAttribute("open", "")
    await expect(summary).toContainText("未启用")

    expect(browserErrors).toEqual([])
  })

  test("场景批量工具只在选中后出现并可明确退出", async ({ page, browserErrors, projectFactory, openProjectWorkbench }) => {
    const failedApiResponses = []
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) {
        failedApiResponses.push(`${response.status()} ${response.url()}`)
      }
    })
    const scenes = []
    for (const [index, title] of ["潮门初启", "旧港追踪", "退潮撤离"].entries()) {
      scenes.push(await createScene(testProjectId, {
        scene_index: index,
        title,
        goal: `整理${title}的创作要点`,
        core_conflict: `确认${title}的核心冲突`,
        chapter_ids: [String(index + 1)],
      }))
    }
    await page.reload()
    await page.waitForFunction(() => !state.loading)
    await expect(page.locator(".scene-workbench-row")).toHaveCount(3)

    const toolbar = page.locator(".scene-fusion-toolbar")
    const checkbox = (sceneId) => page.locator(`.scene-workbench-row[data-id="${sceneId}"] input[data-action="toggle-fusion-selection"]`)
    await expect(toolbar).toHaveCount(0)
    await expect(page.getByRole("button", { name: "全选当前列表" })).toHaveCount(0)

    await checkbox(scenes[0].id).focus()
    await checkbox(scenes[0].id).press("Space")
    await expect(toolbar).toBeVisible()
    await expect(toolbar.getByRole("status")).toHaveText(/1个场景已选/)
    await expect(toolbar.locator(".btn-primary")).toHaveCount(1)
    await expect(toolbar.getByRole("button", { name: "机械合并" })).toHaveCount(0)
    await expect(toolbar.getByRole("button", { name: "AI 融合建议" })).toHaveCount(0)

    await page.reload()
    await page.waitForFunction(() => !state.loading)
    await expect(page.locator(".scene-workbench-row")).toHaveCount(3)
    await expect(toolbar).toHaveCount(0)
    await expect(checkbox(scenes[0].id)).not.toBeChecked()

    await checkbox(scenes[0].id).check()
    await checkbox(scenes[1].id).check()
    await toolbar.getByRole("button", { name: "AI 融合建议" }).click()
    await expect(page.locator("#modal-title")).toHaveText("选择主场景")
    await page.keyboard.press("Escape")
    await expect(page.locator("#modal-overlay")).toBeHidden()
    await expect(toolbar.getByRole("status")).toHaveText(/2个场景已选/)

    await toolbar.getByRole("button", { name: "全选当前列表" }).click()
    await expect(page.locator('input[data-action="toggle-fusion-selection"]:checked')).toHaveCount(3)
    await expect(toolbar.getByRole("button", { name: "取消全选" })).toBeVisible()
    await toolbar.getByRole("button", { name: "退出选择" }).click()
    await expect(toolbar).toHaveCount(0)
    await expect(page.locator('input[data-action="toggle-fusion-selection"]:checked')).toHaveCount(0)

    await checkbox(scenes[0].id).check()
    const otherProject = await projectFactory({ title: "另一部批量作品", genre: "mystery" })
    await openProjectWorkbench(otherProject, "outline", "scenes")
    await expect(toolbar).toHaveCount(0)
    await openProjectWorkbench({ id: testProjectId, title: "场景入口 E2E 测试" }, "outline", "scenes")
    await expect(toolbar).toHaveCount(0)

    await page.locator('.theme-dot[data-theme-value="night"]').click()
    await page.setViewportSize({ width: 375, height: 812 })
    await page.emulateMedia({ reducedMotion: "reduce" })
    await page.locator("html").evaluate((element) => { element.style.fontSize = "125%" })
    await expectNoPageOverflow(page)
    await expect(page.locator(SEL.toastItems)).toHaveCount(0, { timeout: 10000 })
    await page.locator(".scene-workbench-row").first().scrollIntoViewIfNeeded()

    await checkbox(scenes[0].id).focus()
    await checkbox(scenes[0].id).press("Space")
    await expect(toolbar).toBeVisible()
    const selectionLayout = await checkbox(scenes[0].id).evaluate((element) => {
      const label = element.closest("label").getBoundingClientRect()
      const content = element.closest(".scene-workbench-row").querySelector(".scene-workbench-row__content").getBoundingClientRect()
      return { height: label.height, labelRight: label.right, contentLeft: content.left }
    })
    expect(selectionLayout.height).toBeGreaterThanOrEqual(44)
    expect(selectionLayout.labelRight).toBeLessThanOrEqual(selectionLayout.contentLeft + 1)
    for (const button of await toolbar.locator("button").all()) {
      expect(await button.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
    }
    await toolbar.scrollIntoViewIfNeeded()
    await toolbar.getByRole("button", { name: "退出选择" }).click()
    await expect(toolbar).toHaveCount(0)
    await expect(checkbox(scenes[0].id)).not.toBeChecked()
    await page.setViewportSize({ width: 844, height: 390 })
    await expectNoPageOverflow(page)

    expect(failedApiResponses).toEqual([])
    expect(browserErrors).toEqual([])
  })

  test("从大纲其他子标签返回场景工作台", async ({ page }) => {
    const sceneCurrent = page.locator('.subnav-item[data-action="nav-scenes"]')
    const threads = page.locator('.subnav-item[data-action="nav-threads"]')
    await expect(sceneCurrent).toHaveJSProperty("tagName", "BUTTON")
    await expect(sceneCurrent).toHaveAttribute("type", "button")
    await expect(sceneCurrent).toHaveAttribute("aria-current", "page")
    await expect(threads).toHaveAttribute("type", "button")
    await expect(threads).not.toHaveAttribute("aria-current", /.+/)

    await threads.focus()
    await threads.press("Enter")
    await expect(page).toHaveURL(/#workbench\/[^/]+\/outline\/threads/)
    await expect(threads).toHaveAttribute("aria-current", "page")

    const headerScenes = page.locator('.subnav-item[data-action="nav-scenes"]')
    await expect(headerScenes).toHaveAttribute("type", "button")
    await headerScenes.focus()
    await headerScenes.press(" ")

    await expect(page.locator(SEL.viewTitle)).toHaveText("故事结构")
    await expect(page).toHaveURL(/#workbench\/[^/]+\/outline\/scenes/)
    await expect(sceneCurrent).toHaveJSProperty("tagName", "BUTTON")
    await expect(sceneCurrent).toHaveAttribute("aria-current", "page")
    await expect(page.locator('[aria-label="场景筛选"]')).toBeVisible()

    await page.reload()
    await expect(sceneCurrent).toHaveAttribute("aria-current", "page")
    await page.goBack()
    await expect(page.locator('.subnav-item[data-action="nav-threads"]')).toHaveAttribute("aria-current", "page")
    await page.goForward()
    await expect(sceneCurrent).toHaveAttribute("aria-current", "page")
  })

  test("Scene AI 细纲可读编辑、刷新恢复并采用，不会串到其他作品", async ({ page, browserErrors, projectFactory, openProjectWorkbench }) => {
    const taskId = "task-scene-review-e2e"
    const contextConfirmationId = "context-scene-review-e2e"
    const failedApiResponses = []
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) failedApiResponses.push(`${response.status()} ${response.url()}`)
    })
    const draftStructure = {
      result: "proposed",
      scenes: [{
        proposal_ref: "scene-proposal-e2e",
        target_scene_ref: null,
        parent_arc_ref: "arc-first",
        title: "潮门初启",
        planned_start_chapter: 1,
        planned_end_chapter: 2,
        goal: "让主角第一次看见退潮遗迹。",
        core_conflict: "救人会错过唯一入口。",
        core_conflict_status: "present",
        emotional_beat: "惊异转为决断。",
        must_happen: "主角选择先救人。",
        must_not_happen: "不要提前揭示遗迹真相。",
        narrative_tag: "hook",
        narrative_function: "建立退潮规则并留下第一次代价。",
        pov_character_ref: "character-lead",
        related_thread_refs: ["thread-main"],
        related_character_refs: ["character-lead"],
        related_entity_refs: [],
        basis: "承接故事总览中的共同代价。",
        uncertain_fields: [],
        confidence: 0.9,
      }],
      story_outline_conflict: null,
      author_decisions: [{
        question: "这场是否应当立刻进入遗迹？",
        why_it_matters: "会改变开篇的悬念速度。",
        options: ["本场进入", "下一场进入"],
      }],
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
            target: "planned_scene",
            mode: "create",
            draft_structure: draftStructure,
            warnings: ["章节范围仍需作者确认"],
            overlap: { scenes: [{ title: "旧潮门场景" }] },
          },
        }),
      })
    })
    await page.route("**/api/outline/generate/apply", async (route) => {
      applyPayload = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ target: "planned_scene", total_threads: 0, total_arcs: 0, total_scenes: 1 }),
      })
    })
    await page.evaluate(({ projectId, sourceTaskId, confirmationId }) => {
      const now = new Date().toISOString()
      localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
        id: `${projectId}:outline_generate:${sourceTaskId}`,
        taskId: sourceTaskId,
        workflowType: "outline_generate",
        label: "场景建议",
        projectId,
        view: "outline",
        meta: { target: "planned_scene", mode: "create", label: "细纲", context_confirmation_id: confirmationId },
        createdAt: now,
        updatedAt: now,
      }]))
      return window.router.navigate("outline", "scenes", true, new URLSearchParams("review=ai"))
    }, { projectId: testProjectId, sourceTaskId: taskId, confirmationId: contextConfirmationId })

    const review = page.locator(".outline-scene-review")
    await expect(review.getByRole("heading", { name: "检查场景细纲" })).toBeVisible()
    await expect(page.locator("#outline-layer-preview-json")).toHaveCount(0)
    await expect(page.locator('[data-action="close-outline-generate-preview"]')).toHaveText("返回场景")
    await expect(review).not.toContainText("parent_arc_ref")
    await expect(review).not.toContainText("pov_character_ref")
    await expect(page.locator(SEL.toastItems)).toHaveCount(0, { timeout: 10000 })

    const title = page.locator("#outline-scene-preview-0-title")
    await title.fill("作者修订后的潮门开场")
    await page.locator("#outline-scene-preview-0-status").selectOption("not_applicable")
    await expect(page.locator("#outline-scene-preview-0-conflict")).toHaveCount(0)
    await expect(page.locator(".outline-thread-review__save-state")).toContainText("修改已暂存在本机")

    await page.goBack()
    await page.waitForFunction(() => !state.loading)
    await expect(page.locator('[aria-label="场景筛选"]')).toBeVisible()
    await page.goForward()
    await page.waitForFunction(() => !state.loading)
    await expect(title).toHaveValue("作者修订后的潮门开场")
    await page.reload()
    await page.waitForFunction(() => !state.loading)
    await expect(title).toHaveValue("作者修订后的潮门开场")

    const otherProject = await projectFactory({ title: "另一部场景作品", genre: "mystery" })
    await openProjectWorkbench(otherProject, "outline", "scenes")
    await page.evaluate(() => window.router.navigate("outline", "scenes", true, new URLSearchParams("review=ai")))
    await expect(page.getByRole("heading", { name: "这份建议暂时无法打开" })).toBeVisible()
    await expect(page.locator("body")).not.toContainText("作者修订后的潮门开场")

    await openProjectWorkbench({ id: testProjectId, title: "场景入口 E2E 测试" }, "outline", "scenes")
    await page.evaluate(() => window.router.navigate("outline", "scenes", true, new URLSearchParams("review=ai")))
    await expect(title).toHaveValue("作者修订后的潮门开场")

    await page.locator('.theme-dot[data-theme-value="night"]').click()
    await page.setViewportSize({ width: 375, height: 812 })
    await page.emulateMedia({ reducedMotion: "reduce" })
    await page.locator("html").evaluate((element) => { element.style.fontSize = "125%" })
    await expectNoPageOverflow(page)
    await expect.poll(() => page.locator('[data-action="apply-outline-generate-preview"]').evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
    await expect(page.locator(SEL.toastItems)).toHaveCount(0, { timeout: 10000 })
    await page.setViewportSize({ width: 844, height: 390 })
    await expectNoPageOverflow(page)

    await page.locator('[data-action="apply-outline-generate-preview"]').click()
    await expect(page.locator('[aria-label="场景筛选"]')).toBeVisible()
    expect(applyPayload).toEqual({
      novel_id: testProjectId,
      context_confirmation_id: contextConfirmationId,
      source_task_id: taskId,
      draft_structure: expect.objectContaining({
        result: "proposed",
        scenes: [expect.objectContaining({
          title: "作者修订后的潮门开场",
          core_conflict: null,
          core_conflict_status: "not_applicable",
          parent_arc_ref: "arc-first",
          pov_character_ref: "character-lead",
          related_thread_refs: ["thread-main"],
        })],
      }),
      confirmed: true,
    })
    const persisted = await page.evaluate(({ projectId, sourceTaskId }) => ({
      draft: localStorage.getItem(`novel_outline_scene_preview:${encodeURIComponent(projectId)}:${encodeURIComponent(sourceTaskId)}`),
      workflows: JSON.parse(localStorage.getItem("novel_active_workflows_v1") || "[]"),
    }), { projectId: testProjectId, sourceTaskId: taskId })
    expect(persisted.draft).toBeNull()
    expect(persisted.workflows).not.toEqual(expect.arrayContaining([expect.objectContaining({ taskId })]))
    expect(failedApiResponses).toEqual([])
    expect(browserErrors).toEqual([])
  })

  test("故事总览首次进入只有一个明确入口并可安全恢复", async ({ page, browserErrors, projectFactory }) => {
    const failedApiResponses = []
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) {
        failedApiResponses.push(`${response.status()} ${response.url()}`)
      }
    })

    await page.locator('[data-action="nav-story-outline"]').click()
    await expect(page).toHaveURL(/\/outline\/story-outline/)
    const workspace = page.locator(".story-outline-workspace")
    const onboarding = workspace.locator(".story-outline-onboarding")
    await expect(onboarding.getByRole("heading", { name: "先确定故事方向" })).toBeVisible()
    await expect(workspace.locator("#story-outline-history-title")).toHaveCount(0)
    await expect(workspace.locator(".empty-icon")).toHaveCount(0)

    const generate = onboarding.locator('[data-action="generate-story-outline"]')
    const manual = onboarding.locator('[data-action="edit-story-outline"]')
    await expect(generate).toHaveText("AI 生成可编辑预览")
    await expect(generate).toHaveClass(/btn-primary/)
    await expect(manual).toHaveText("手工创建")
    await expect(manual).not.toHaveClass(/btn-primary/)

    const more = onboarding.locator(".story-outline-more")
    const moreSummary = more.locator("summary")
    const reload = more.locator('[data-action="reload-story-outline"]')
    await expect(more).not.toHaveAttribute("open", "")
    await expect(reload).toBeHidden()
    await moreSummary.focus()
    await moreSummary.press("Enter")
    await expect(more).toHaveAttribute("open", "")
    await expect(reload).toBeVisible()
    await moreSummary.click()

    await generate.click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("用 AI 生成故事总览")
    const generateForm = page.locator(".story-outline-generate")
    await expect(generateForm.getByLabel("你想写一个怎样的故事？ 必填")).toBeVisible()
    await expect(generateForm.getByLabel("预计篇幅 必填")).toBeVisible()
    await expect(generateForm.getByLabel("这次先规划到哪里？ 必填")).toBeVisible()
    await expect(generateForm).not.toContainText("Top-K")
    await expect(generateForm.locator(".story-outline-generate__references")).not.toHaveAttribute("open", "")
    await page.getByRole("button", { name: "开始生成预览" }).click()
    await expect(generateForm.locator("#story-outline-generate-error-summary")).toBeFocused()
    await expect(generateForm.locator("#story-outline-author-intent-error")).toHaveText("这项需要填写。")
    await generateForm.locator("#story-outline-author-intent").fill("追查一座城市被抹去的共同记忆")
    await generateForm.locator("#story-outline-planned-scale").fill("30 万字长篇")
    await generateForm.locator("#story-outline-coverage").fill("覆盖全书，先细化第一部")
    page.once("dialog", (dialog) => dialog.accept())
    await page.keyboard.press("Escape")
    await expect(page.locator(SEL.modalOverlay)).toBeHidden()
    await expect(generate).toBeFocused()

    await page.reload()
    await expect(onboarding).toBeVisible()
    await page.locator('[data-action="nav-arcs"]').click()
    await expect(page).toHaveURL(/\/outline\/arcs/)
    await page.goBack()
    await expect(onboarding).toBeVisible()
    await page.goForward()
    await expect(page).toHaveURL(/\/outline\/arcs/)
    await page.goBack()
    await expect(onboarding).toBeVisible()

    const otherProject = await projectFactory({
      title: "故事总览切换作品",
      genre: "fantasy",
      language: "zh",
    })
    await page.locator(".sidebar-project-switcher").click()
    const otherCard = page.locator(`.project-card[data-id="${otherProject.id}"]`)
    await expect(otherCard).toBeVisible()
    await otherCard.locator('[data-action="continue-writing"]').click()
    await expect(page.locator(".sidebar-project-switcher strong")).toHaveText("故事总览切换作品")
    await page.locator('.nav-item[data-view="outline"]').click()
    await expect(page.locator('[data-action="nav-story-outline"]')).toHaveAttribute("aria-current", "page")
    await expect(onboarding).toBeVisible()
    await expect(workspace.locator("#story-outline-history-title")).toHaveCount(0)

    await page.setViewportSize({ width: 390, height: 844 })
    await page.emulateMedia({ reducedMotion: "reduce" })
    await page.locator('.theme-dot[data-theme-value="night"]').click()
    await expect(page.locator("html")).toHaveAttribute("data-theme", "night")
    await expectNoPageOverflow(page)
    await expectWithinViewport(onboarding)
    for (const control of [generate, manual, moreSummary]) {
      expect(await control.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
    }
    await generate.click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("用 AI 生成故事总览")
    await expectWithinViewport(page.locator(SEL.modalContent))
    await expect(generateForm.locator(".story-outline-generate__references")).not.toHaveAttribute("open", "")
    for (const control of await generateForm.locator("input:not([type=checkbox]):visible, textarea:visible, summary:visible").all()) {
      expect(await control.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
    }
    await page.locator("html").evaluate((element) => { element.style.fontSize = "125%" })
    await expectNoPageOverflow(page)
    await page.setViewportSize({ width: 844, height: 390 })
    await expectNoPageOverflow(page)
    await expectWithinViewport(page.locator(SEL.modalContent))
    await page.keyboard.press("Escape")
    await expect(page.locator(SEL.modalOverlay)).toBeHidden()

    expect(failedApiResponses).toEqual([])
    expect(browserErrors).toEqual([])
  })

  test("AI 故事总览预览可刷新恢复、隔离作品并处理版本冲突", async ({ page, browserErrors, projectFactory }) => {
    const taskId = "story-outline-browser-mock"
    const generatedRequests = []
    const applyRequests = []
    let applyAttempts = 0
    let latestRevision = null
    const previewContent = {
      title: "记忆档案馆",
      creative_core: {
        premise: "一名档案员追查被整座城市遗忘的历史。",
        tone_and_reader_promise: "克制的悬疑与温暖的人物关系并行。",
        story_engine: "每找回一份档案，就打开更大的谎言。",
        ending_direction: "主角让真相重新成为公共记忆。",
      },
      outline_markdown: "主角从一份错位档案出发，逐步发现城市的记忆被人为改写。",
      major_storylines: [],
      macro_movements: [],
      open_decisions: [],
    }

    await page.route("**/api/outline/story-outline?*", async (route) => {
      const requestedProjectId = new URL(route.request().url()).searchParams.get("novel_id")
      if (!latestRevision || requestedProjectId !== testProjectId) return route.fallback()
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        current_revision_id: latestRevision.id,
        revision: latestRevision,
      }) })
    })
    await page.route("**/api/outline/story-outline/generate", async (route) => {
      generatedRequests.push(route.request().postDataJSON())
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        task_id: taskId,
        task_type: "story_outline_generate",
        status: "pending",
      }) })
    })
    await page.route("**/api/tasks/story-outline-browser-mock?*", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        task_id: taskId,
        task_type: "story_outline_generate",
        status: "done",
        meta: { action: "outline.story_outline.generate", novel_id: testProjectId },
        result: {
          ...previewContent,
          managed_llm_steps: [{ provider: "browser-mock", model: "browser-mock" }],
          apply_status: null,
          applied_revision_id: null,
        },
      }) })
    })
    await page.route("**/api/outline/story-outline/generate/apply", async (route) => {
      applyAttempts += 1
      applyRequests.push(route.request().postDataJSON())
      if (applyAttempts === 1) {
        await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "revision conflict" }) })
        return
      }
      latestRevision = {
        id: "story-outline-rev-3",
        novel_id: testProjectId,
        version_number: 3,
        source: "ai_generated",
        provenance: { actor: "author" },
        base_revision_id: "story-outline-rev-2",
        restored_from_revision_id: null,
        content_hash: "b".repeat(64),
        created_at: "2026-08-23T00:00:00Z",
        is_current: true,
        ...previewContent,
        title: applyRequests.at(-1).title,
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(latestRevision) })
    })

    await page.locator('[data-action="nav-story-outline"]').click()
    await page.locator('[data-action="generate-story-outline"]').click()
    const form = page.locator(".story-outline-generate")
    await form.locator("#story-outline-author-intent").fill("追查一座城市被抹去的共同记忆")
    await form.locator("#story-outline-planned-scale").fill("30 万字长篇")
    await form.locator("#story-outline-coverage").fill("覆盖全书，先细化第一部")
    await page.getByRole("button", { name: "开始生成预览" }).click()
    await expect(page.locator(SEL.modalTitle)).toContainText("AI 参考资料")
    const start = page.getByRole("button", { name: "按这份资料开始" })
    await expect(start).toBeEnabled()
    await start.click()

    const preview = page.locator(".story-outline-preview")
    await expect(preview.getByRole("heading", { name: "检查 AI 建议" })).toBeVisible()
    expect(generatedRequests).toHaveLength(1)
    expect(generatedRequests[0]).toEqual(expect.objectContaining({
      novel_id: testProjectId,
      author_intent: "追查一座城市被抹去的共同记忆",
      planned_scale: "30 万字长篇",
      coverage: "覆盖全书，先细化第一部",
      selected_character_ids: [],
      selected_entity_ids: [],
      context_confirmation_id: expect.any(String),
      include_current_outline: false,
      operation_id: expect.any(String),
    }))

    const title = preview.locator("#story-outline-preview-title-input")
    await title.fill("作者修订的记忆档案馆")
    await expect.poll(async () => page.evaluate((projectId) => (
      JSON.parse(localStorage.getItem(`story-outline-preview-draft:${projectId}`) || "null")?.content?.title
    ), testProjectId)).toBe("作者修订的记忆档案馆")

    await page.reload()
    await expect(title).toHaveValue("作者修订的记忆档案馆")
    await expect(preview).toContainText("已恢复上次修改")
    await page.locator('[data-action="nav-arcs"]').click()
    await page.goBack()
    await expect(title).toHaveValue("作者修订的记忆档案馆")

    const otherProject = await projectFactory({ title: "AI 预览隔离作品", genre: "mystery", language: "zh" })
    await page.locator(".sidebar-project-switcher").click()
    await page.locator(`.project-card[data-id="${otherProject.id}"] [data-action="continue-writing"]`).click()
    await expect(page).toHaveURL(new RegExp(`#workbench/${otherProject.id}/writing`))
    await page.waitForFunction((projectId) => state.currentProjectId === projectId && !state.loading, otherProject.id)
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作")
    await page.locator('.nav-item[data-view="outline"]').click()
    await page.waitForFunction((projectId) => state.currentProjectId === projectId && !state.loading, otherProject.id)
    await expect(page.locator(SEL.viewTitle)).toHaveText("故事结构")
    await page.locator('[data-action="nav-story-outline"]').click()
    await expect(page).toHaveURL(/\/outline\/story-outline/)
    await page.waitForFunction((projectId) => state.currentProjectId === projectId && !state.loading, otherProject.id)
    await expect(preview).toHaveCount(0)

    await page.locator(".sidebar-project-switcher").click()
    await page.locator(`.project-card[data-id="${testProjectId}"] [data-action="continue-writing"]`).click()
    await expect(page).toHaveURL(new RegExp(`#workbench/${testProjectId}/writing`))
    await page.waitForFunction((projectId) => state.currentProjectId === projectId && !state.loading, testProjectId)
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作")
    await page.locator('.nav-item[data-view="outline"]').click()
    await page.waitForFunction((projectId) => state.currentProjectId === projectId && !state.loading, testProjectId)
    await expect(page.locator(SEL.viewTitle)).toHaveText("故事结构")
    await page.locator('[data-action="nav-story-outline"]').click()
    await expect(page).toHaveURL(/\/outline\/story-outline/)
    await page.waitForFunction((projectId) => state.currentProjectId === projectId && !state.loading, testProjectId)
    await expect(title).toHaveValue("作者修订的记忆档案馆")

    await page.setViewportSize({ width: 390, height: 844 })
    await page.emulateMedia({ reducedMotion: "reduce" })
    await expectNoPageOverflow(page)
    for (const button of await preview.locator(".story-outline-preview__actions .btn").all()) {
      expect(await button.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
    }
    expect(await page.evaluate(() => {
      const input = document.querySelector("#story-outline-preview-title-input")?.getBoundingClientRect()
      const actions = document.querySelector(".story-outline-preview__actions")?.getBoundingClientRect()
      return Boolean(input && actions && input.bottom > actions.top && input.top < actions.bottom)
    })).toBe(false)

    await preview.locator('[data-action="apply-story-outline-preview"]').click()
    await expect(preview).toContainText("当前版本被更新了")
    await expect(preview.locator('[data-action="apply-story-outline-preview"]')).toBeDisabled()
    expect(await page.evaluate((projectId) => localStorage.getItem(`story-outline-preview-draft:${projectId}`), testProjectId)).not.toBeNull()

    latestRevision = {
      id: "story-outline-rev-2",
      novel_id: testProjectId,
      version_number: 2,
      source: "manual",
      provenance: { actor: "author" },
      base_revision_id: null,
      restored_from_revision_id: null,
      content_hash: "a".repeat(64),
      created_at: "2026-08-22T00:00:00Z",
      is_current: true,
      ...previewContent,
      title: "其他会话的最新版本",
    }
    await preview.locator('[data-action="sync-story-outline-preview"]').click()
    await expect(title).toHaveValue("作者修订的记忆档案馆")
    await expect(preview.locator('[data-action="apply-story-outline-preview"]')).toBeEnabled()
    await preview.locator('[data-action="apply-story-outline-preview"]').click()
    await expect(preview).toHaveCount(0)
    await expect(page.locator(".story-outline-document")).toContainText("当前版本 · v3")
    expect(applyRequests).toHaveLength(2)
    expect(applyRequests[1]).toEqual(expect.objectContaining({
      novel_id: testProjectId,
      source_task_id: taskId,
      title: "作者修订的记忆档案馆",
      base_revision_id: "story-outline-rev-2",
      confirmed: true,
    }))
    expect(await page.evaluate((projectId) => localStorage.getItem(`story-outline-preview-draft:${projectId}`), testProjectId)).toBeNull()
    const expectedConflictErrors = browserErrors.filter((error) => error.kind === "console" && error.text.includes("409"))
    expect(expectedConflictErrors).toHaveLength(1)
    expect(browserErrors.filter((error) => !expectedConflictErrors.includes(error))).toEqual([])
  })

  test("已有故事总览可连续阅读并安全回看过往版本", async ({ page, browserErrors, projectFactory }) => {
    const failedApiResponses = []
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) {
        failedApiResponses.push(`${response.status()} ${response.url()}`)
      }
    })

    const content = {
      source: "manual",
      provenance: { actor: "author" },
      creative_core: {
        premise: "退潮后的古老航道迫使敌对群岛共同选择未来。",
        tone_and_reader_promise: "克制的海洋奇幻、政治博弈与逐层揭开的文明真相。",
        story_engine: "每次退潮都带来资源、真相与必须共同承担的新代价。",
        ending_direction: "分权航盟取代单一王座。",
      },
      outline_markdown: "主角从寻找失踪的父亲开始，逐步发现群岛秩序建立在被控制的潮汐循环之上。",
      major_storylines: [{
        name: "潮门真相",
        narrative_function: "驱动主谜题。",
        trajectory: "从失踪日志追到王室档案。",
        intersections: ["失踪父亲", "航盟成立"],
        resolution_direction: "公开机制并终结垄断。",
      }],
      macro_movements: [{
        name: "退潮开门",
        story_state_change: "失踪案升级为跨岛危机。",
        advanced_storylines: ["潮门真相"],
      }],
      open_decisions: [{
        question: "父亲是否仍然活着？",
        why_it_matters: "决定结局偏向私人救援还是公共责任。",
        options: ["仍被困在潮门", "已经牺牲"],
      }],
    }
    let previous = null
    for (const [index, title] of ["群岛共同体初稿", "潮门与航盟", "公开潮汐"].entries()) {
      previous = await createStoryOutlineRevision(testProjectId, {
        ...content,
        title,
        base_revision_id: previous?.id || null,
        idempotency_key: `story-reading-${testProjectId}-${index + 1}`,
      })
    }

    await page.locator('[data-action="nav-story-outline"]').click()
    const workspace = page.locator(".story-outline-workspace")
    const documentView = workspace.locator(".story-outline-document")
    await expect(documentView).toBeVisible()
    await expect(documentView.locator(".card")).toHaveCount(0)
    await expect(documentView.locator(".story-outline-core > div")).toHaveCount(4)
    await expect(documentView.locator(".story-outline-entry")).toHaveCount(3)
    await expect(documentView.getByRole("heading", { name: "公开潮汐" })).toBeVisible()

    const history = workspace.locator(".story-outline-history")
    const historySummary = history.locator("summary")
    await expect(history).not.toHaveAttribute("open", "")
    await expect(history.locator('[data-action="view-story-outline-revision"]').first()).toBeHidden()
    await historySummary.focus()
    await historySummary.press("Enter")
    await expect(history).toHaveAttribute("open", "")
    await expect(history.locator(".story-outline-history__item")).toHaveCount(2)
    await expect(history).not.toContainText("v3 · 公开潮汐")

    const viewButton = history.locator('[data-action="view-story-outline-revision"]').first()
    await viewButton.click()
    await expect(page.locator(SEL.modalTitle)).toContainText("故事总览历史版本 v2")
    const readOnlyModal = page.locator(SEL.modalBody).locator(".story-outline-document--modal")
    await expect(readOnlyModal.getByRole("heading", { name: "潮门与航盟" })).toBeVisible()
    await expect(readOnlyModal.locator(".card")).toHaveCount(0)
    await page.keyboard.press("Escape")
    await expect(page.locator(SEL.modalOverlay)).toBeHidden()
    await expect(viewButton).toBeFocused()

    await history.locator('[data-action="restore-story-outline-revision"]').first().click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("确认操作")
    await page.locator(SEL.modalFooter).getByRole("button", { name: "采用为新版本" }).click()
    await expect(documentView).toContainText("当前版本 · v4")
    await expect(documentView.getByRole("heading", { name: "潮门与航盟" })).toBeVisible()

    await page.reload()
    await expect(documentView).toContainText("当前版本 · v4")
    await expect(history).not.toHaveAttribute("open", "")
    await page.locator('[data-action="nav-arcs"]').click()
    await page.goBack()
    await expect(documentView).toContainText("当前版本 · v4")

    const otherProject = await projectFactory({ title: "故事总览隔离作品", genre: "mystery", language: "zh" })
    await page.locator(".sidebar-project-switcher").click()
    await page.locator(`.project-card[data-id="${otherProject.id}"] [data-action="continue-writing"]`).click()
    await page.locator('.nav-item[data-view="outline"]').click()
    await page.locator('[data-action="nav-story-outline"]').click()
    await expect(workspace.locator(".story-outline-onboarding")).toBeVisible()

    await page.locator(".sidebar-project-switcher").click()
    await page.locator(`.project-card[data-id="${testProjectId}"] [data-action="continue-writing"]`).click()
    await page.locator('.nav-item[data-view="outline"]').click()
    await page.locator('[data-action="nav-story-outline"]').click()
    await expect(documentView).toContainText("当前版本 · v4")

    await page.setViewportSize({ width: 390, height: 844 })
    await page.emulateMedia({ reducedMotion: "reduce" })
    await page.locator('.theme-dot[data-theme-value="night"]').click()
    await expectNoPageOverflow(page)
    await historySummary.click()
    await expect(history).toHaveAttribute("open", "")
    expect(await historySummary.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
    for (const button of await history.locator(".story-outline-history__actions .btn").all()) {
      expect(await button.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
    }
    await page.setViewportSize({ width: 844, height: 390 })
    await expectNoPageOverflow(page)

    expect(failedApiResponses).toEqual([])
    expect(browserErrors).toEqual([])
  })

  test("手工编辑页可刷新恢复、按作品隔离并保存新版本", async ({ page, browserErrors, projectFactory }) => {
    const failedApiResponses = []
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) {
        failedApiResponses.push(`${response.status()} ${response.url()}`)
      }
    })
    await createStoryOutlineRevision(testProjectId, {
      title: "潮门初稿",
      source: "manual",
      provenance: { actor: "author" },
      creative_core: {
        premise: "退潮后的航道迫使敌对群岛共同选择未来。",
        tone_and_reader_promise: "克制的海洋奇幻与政治博弈。",
        story_engine: "每次退潮都带来资源、真相和新代价。",
        ending_direction: "分权航盟取代单一王座。",
      },
      outline_markdown: "主角从寻找失踪的父亲开始，逐步发现潮汐循环的真相。",
      major_storylines: [{ name: "潮门真相", narrative_function: "驱动主谜题", trajectory: "从日志追到王室档案", intersections: ["失踪父亲"], resolution_direction: "公开机制" }],
      macro_movements: [{ name: "退潮开门", story_state_change: "失踪案升级为跨岛危机", advanced_storylines: ["潮门真相"] }],
      open_decisions: [{ question: "父亲是否仍然活着？", why_it_matters: "决定结局的伦理代价", options: ["仍被困", "已牺牲"] }],
      base_revision_id: null,
      idempotency_key: `story-editor-${testProjectId}-1`,
    })

    await page.locator('[data-action="nav-story-outline"]').click()
    await page.locator('[data-action="edit-story-outline"]').click()
    await expect(page).toHaveURL(/\/outline\/story-outline\?edit=1/)
    const editor = page.locator(".story-outline-editor-page")
    await expect(editor.getByRole("heading", { name: "编辑故事总览" })).toBeVisible()
    await expect(editor).not.toContainText("Markdown")
    await expect(editor).not.toContainText("JSON")
    await expect(editor.locator(".story-outline-list-item.card")).toHaveCount(0)

    const title = editor.locator("#story-outline-manual-title-input")
    await title.fill("潮门与航盟")
    await expect.poll(async () => page.evaluate((projectId) => (
      JSON.parse(localStorage.getItem(`story-outline-editor-draft:${projectId}`) || "null")?.content?.title
    ), testProjectId)).toBe("潮门与航盟")

    page.once("dialog", (dialog) => dialog.accept())
    await page.reload()
    await expect(title).toHaveValue("潮门与航盟")
    await expect(editor.locator(".story-outline-editor-notice")).toContainText("已恢复本地草稿")

    page.once("dialog", (dialog) => dialog.accept())
    await page.goBack()
    await expect(page).toHaveURL(/\/outline\/story-outline$/)
    await page.goForward()
    await expect(title).toHaveValue("潮门与航盟")

    const otherProject = await projectFactory({ title: "草稿隔离作品", genre: "mystery", language: "zh" })
    page.once("dialog", (dialog) => dialog.accept())
    await page.locator(".sidebar-project-switcher").click()
    await page.locator(`.project-card[data-id="${otherProject.id}"] [data-action="continue-writing"]`).click()
    await page.locator('.nav-item[data-view="outline"]').click()
    await page.locator('[data-action="edit-story-outline"]').click()
    await expect(editor.locator("#story-outline-manual-title-input")).toHaveValue("")

    await page.locator(".sidebar-project-switcher").click()
    await page.locator(`.project-card[data-id="${testProjectId}"] [data-action="continue-writing"]`).click()
    await page.locator('.nav-item[data-view="outline"]').click()
    await page.locator('[data-action="edit-story-outline"]').click()
    await expect(title).toHaveValue("潮门与航盟")

    await editor.locator('[data-action="save-story-outline-revision"]').click()
    const workspace = page.locator(".story-outline-workspace")
    await expect(workspace.locator(".story-outline-document")).toContainText("当前版本 · v2")
    await expect(workspace.getByRole("heading", { name: "潮门与航盟" })).toBeVisible()
    expect(await page.evaluate((projectId) => localStorage.getItem(`story-outline-editor-draft:${projectId}`), testProjectId)).toBeNull()
    await expect(page).toHaveURL(/\/outline\/story-outline$/)

    await page.setViewportSize({ width: 390, height: 844 })
    await page.emulateMedia({ reducedMotion: "reduce" })
    await page.locator('[data-action="edit-story-outline"]').click()
    await expectNoPageOverflow(page)
    for (const button of await editor.locator("button:visible").all()) {
      expect(await button.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
    }
    await page.setViewportSize({ width: 375, height: 812 })
    await page.locator("html").evaluate((element) => { element.style.fontSize = "125%" })
    const lastInput = editor.locator(".story-outline-list-editor input").last()
    await lastInput.focus()
    await lastInput.evaluate((element) => element.scrollIntoView({ block: "nearest" }))
    await expectNoPageOverflow(page)
    expect(await page.evaluate(() => {
      const focused = document.activeElement?.getBoundingClientRect()
      const footer = document.querySelector(".story-outline-editor-page__actions")?.getBoundingClientRect()
      return Boolean(focused && footer && focused.bottom > footer.top)
    })).toBe(false)
    await page.setViewportSize({ width: 844, height: 390 })
    await expectNoPageOverflow(page)

    expect(failedApiResponses).toEqual([])
    expect(browserErrors).toEqual([])
  })

  test("四层结构的 AI 任务使用同一进度区并在窄屏保留操作", async ({ page, browserErrors }) => {
    await page.locator('[data-action="nav-threads"]').click()
    await expect(page).toHaveURL(/\/outline\/threads/)
    await page.evaluate(async () => {
      const managers = await import("/vue/views/outline/ai/outlineWorkflowManagers.js")
      managers.outlineAnalysisManager.state.meta = { start_chapter: 1, end_chapter: 12 }
      managers.outlineAnalysisManager.state.progress = {
        taskId: "outline-analysis-e2e", statusLabel: "分析中", percent: 24,
        hasPercent: true, terminal: false, failed: false, done: false,
        availableActions: ["cancel"],
      }
      managers.outlineGenerateManager.state.meta = {
        label: "剧情线", mode: "create", start_chapter: 1, end_chapter: 12,
      }
      managers.outlineGenerateManager.state.progress = {
        taskId: "outline-generate-e2e", statusLabel: "生成中", percent: 48,
        hasPercent: true, terminal: false, failed: false, done: false,
        availableActions: [],
      }
      managers.plotAutoExtractManager.state.meta = {
        label: "从正文整理剧情线", start_chapter: 1, end_chapter: 12,
      }
      managers.plotAutoExtractManager.state.progress = {
        taskId: "outline-extract-e2e", statusLabel: "整理中", percent: 72,
        hasPercent: true, terminal: false, failed: false, done: false,
        availableActions: [],
      }
    })

    const taskRegion = page.locator(".outline-task-status")
    await expect(taskRegion.getByRole("heading", { name: "AI 任务" })).toBeVisible()
    await expect(taskRegion.locator(".workflow-progress")).toHaveCount(3)
    const taskGaps = await taskRegion.locator(".workflow-progress").evaluateAll((cards) => (
      cards.slice(1).map((card, index) => card.getBoundingClientRect().top - cards[index].getBoundingClientRect().bottom)
    ))
    expect(taskGaps).toEqual([8, 8])

    const analysisCard = taskRegion.locator(".workflow-progress", { hasText: "AI 大纲分析" })
    await analysisCard.locator("summary").click()
    await expect(analysisCard).toContainText("范围：第 1–12 章")
    await expect(analysisCard.locator('[data-action="cancel-outline-analysis"]')).toHaveCount(1)

    await page.locator('[data-action="nav-arcs"]').click()
    await expect(page).toHaveURL(/\/outline\/arcs/)
    await expect(taskRegion.locator(".workflow-progress")).toHaveCount(3)
    await page.goBack()
    await expect(page).toHaveURL(/\/outline\/threads/)
    await expect(taskRegion.locator(".workflow-progress")).toHaveCount(3)

    await page.locator('[data-action="nav-story-outline"]').click()
    await expect(page).toHaveURL(/\/outline\/story-outline/)
    await page.evaluate(async () => {
      const { storyOutlineTaskManager } = await import("/vue/views/outline/story/storyOutlineData.js")
      storyOutlineTaskManager.state.taskId = "story-outline-e2e"
      storyOutlineTaskManager.state.progress = {
        taskId: "story-outline-e2e", statusLabel: "生成中", percent: 32,
        hasPercent: true, terminal: false, failed: false, done: false,
        availableActions: ["cancel"], message: "正在生成故事总览预览",
      }
    })
    await expect(taskRegion.locator(".workflow-progress")).toHaveCount(1)
    expect(await taskRegion.evaluate((region) => Boolean(
      region.compareDocumentPosition(document.querySelector("[aria-labelledby='story-outline-intro-title']"))
      & Node.DOCUMENT_POSITION_FOLLOWING
    ))).toBe(true)

    await page.locator('[data-action="nav-scenes"]').click()
    await expect(page).toHaveURL(/\/outline\/scenes/)
    await page.evaluate(async () => {
      const { sceneAutoExtractManager } = await import("/vue/views/scene/sceneAutoExtractManager.js")
      sceneAutoExtractManager.state.meta = { start_chapter: 2, end_chapter: 6 }
      sceneAutoExtractManager.state.progress = {
        taskId: "scene-extract-e2e", statusLabel: "整理中", percent: 40,
        hasPercent: true, terminal: false, failed: false, done: false,
        availableActions: ["cancel"],
      }
    })
    const sceneTask = taskRegion.locator('[data-role="scene-auto-extract-progress"] .workflow-progress')
    await expect(sceneTask).toBeVisible()
    await sceneTask.locator("summary").focus()
    await sceneTask.locator("summary").press("Enter")
    await expect(sceneTask).toContainText("范围：第 2–6 章")
    const sceneCancel = sceneTask.locator('[data-action="cancel-scene-auto-extract"]')
    await expect(sceneCancel).toBeVisible()

    await page.locator('.theme-dot[data-theme-value="night"]').click()
    await expect(page.locator("html")).toHaveAttribute("data-theme", "night")
    await page.setViewportSize({ width: 375, height: 812 })
    await page.emulateMedia({ reducedMotion: "reduce" })
    await page.locator("html").evaluate((element) => { element.style.fontSize = "125%" })
    await expectNoPageOverflow(page)
    expect(await sceneCancel.evaluate((button) => button.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
    await page.setViewportSize({ width: 844, height: 390 })
    await expectNoPageOverflow(page)
    expect(browserErrors).toEqual([])
  })

  test("按名称选择 Scene 完成合并，请求仍使用 ID", async ({ page, browserErrors }) => {
    const failedApiResponses = []
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) failedApiResponses.push(`${response.status()} ${response.url()}`)
    })
    const target = await createScene(testProjectId, {
      scene_index: 0,
      title: "密道入口",
      goal: null,
      narrative_tag: "draft",
      chapter_ids: ["1"],
      scene_chunks: [],
    })
    const source = await createScene(testProjectId, {
      scene_index: 1,
      title: "潜入王宫",
      goal: "取得密信",
      narrative_tag: "draft",
      chapter_ids: ["2"],
      scene_chunks: [],
    })
    await page.reload()
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })

    const targetRow = page.locator(".scene-workbench-row", { hasText: "密道入口" })
    await targetRow.locator('[data-action="select-workbench-scene"]').click()
    const detailMore = page.locator('.scene-detail-panel .scene-detail-action-menu .action-menu-btn')
    const mergeButton = page.locator('.scene-detail-panel').getByRole("menuitem", { name: "合并场景" })
    await detailMore.click()
    await mergeButton.click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("选择要合并的场景")

    const picker = page.locator("#scene-merge-reference-picker")
    await picker.locator("[data-reference-query]").fill("潜入王宫")
    await picker.locator("[data-reference-result]", { hasText: "潜入王宫" }).click()
    await expect(picker.locator("[data-reference-selected]")).toContainText("潜入王宫")
    await page.getByRole("button", { name: "预览合并影响" }).click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("合并场景影响预览")
    const preview = page.locator(".scene-impact-preview")
    await expect(preview).toContainText("保留「密道入口」")
    await expect(preview).toContainText("潜入王宫")
    await expect(preview).toContainText("第 1 章 → 第 1 章 / 第 2 章")
    await expect(preview).toContainText("未填写→取得密信")
    await expect(preview.locator("pre")).toHaveCount(0)
    await expect(preview).not.toContainText(target.id)
    await expect(preview).not.toContainText(source.id)

    await page.keyboard.press("Escape")
    await expect(page.locator(SEL.modalOverlay)).toBeHidden()
    await expect(detailMore).toBeFocused()

    await page.locator('.theme-dot[data-theme-value="night"]').click()
    await expect(page.locator("html")).toHaveAttribute("data-theme", "night")
    await page.setViewportSize({ width: 390, height: 844 })
    await detailMore.click()
    await mergeButton.click()
    await picker.locator("[data-reference-query]").fill("潜入王宫")
    await picker.locator("[data-reference-result]", { hasText: "潜入王宫" }).click()
    await page.getByRole("button", { name: "预览合并影响" }).click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("合并场景影响预览")
    await expectNoPageOverflow(page)
    await expectWithinViewport(page.locator(SEL.modalContent))
    await expectWithinViewport(page.getByRole("button", { name: "确认合并" }))
    await page.emulateMedia({ reducedMotion: "reduce" })
    await page.locator("html").evaluate((element) => { element.style.fontSize = "125%" })
    await expectNoPageOverflow(page)
    await page.setViewportSize({ width: 844, height: 390 })
    await expectNoPageOverflow(page)
    await expectWithinViewport(page.locator(SEL.modalContent))
    await expectWithinViewport(page.getByRole("button", { name: "确认合并" }))

    const mergeRequest = page.waitForRequest((request) => {
      const url = new URL(request.url())
      return request.method() === "POST"
        && url.pathname.endsWith("/api/outline/scene-workbench/merge")
    })
    await page.getByRole("button", { name: "确认合并" }).click()
    const payload = (await mergeRequest).postDataJSON()

    expect(payload).toEqual({
      target_scene_id: target.id,
      source_scene_ids: [source.id],
      confirmed: true,
    })
    await expect(page.locator(SEL.toastContainer)).toContainText("场景已合并", { timeout: 10000 })
    expect(failedApiResponses).toEqual([])
    expect(browserErrors).toEqual([])
  })
})
