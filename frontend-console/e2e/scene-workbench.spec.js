import { test, expect } from "./fixtures.js"
import { openWorkbench } from "./helpers/workbench.js"
import { expectNoPageOverflow, expectWithinViewport, expectWithinViewportWidth } from "./helpers/responsive.js"
import { SEL } from "./helpers/selectors.js"
import {
  cleanupProject,
  createDraft,
  createEntity,
  createProject,
  createScene,
  listScenes,
  listScenesOrdered,
  waitForBackend,
} from "./helpers/api-client.js"

test.describe("Scene 工作台", () => {
  let testProjectId = null

  test.beforeEach(async ({ page }) => {
    const fusionResults = new Map()
    await page.route("**/api/outline/scene-workbench/fusion/preview-task?*", async (route) => {
      const body = route.request().postDataJSON()
      const { operation_id: operationId, ...previewBody } = body
      const response = await route.fetch({
        url: route.request().url().replace("/preview-task", "/preview"),
        data: previewBody,
      })
      fusionResults.set(operationId, await response.json())
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({ task_id: operationId, status: "pending" }),
      })
    })
    await page.route("**/api/tasks/**", async (route) => {
      const taskId = new URL(route.request().url()).pathname.split("/").at(-1)
      const result = fusionResults.get(taskId)
      if (!result || route.request().method() !== "GET") return route.fallback()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ task_id: taskId, task_type: "scene_fusion_preview", status: "done", progress: 1, result }),
      })
    })
  })

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("从写作页整理按钮进入场景工作台并定位当前 Scene", async ({ page }) => {
    const project = await createProject({ title: "Scene 工作台跳转", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "写作联动 Scene",
      goal: "进入宫门",
      core_conflict: "守卫阻拦",
      must_happen: "交出令牌",
      must_not_happen: "身份暴露",
      chapter_ids: ["1"],
    })
    await createDraft(project.id, 1, "第一章", "正文")

    await openWorkbench(page, project, "writing")
    await page.getByRole("button", { name: /打开第 1 章/ }).click()
    await page.getByRole("button", { name: "写作联动 Scene", exact: true }).click()
    await page.getByRole("button", { name: "整理" }).click()

    await expect(page.locator("#topbar-module")).toHaveText("故事结构")
    await expect(page).toHaveURL(new RegExp(`scene_id=${scene.id}`))
    await expect(page.locator(`.scene-workbench-row[data-id="${scene.id}"]`)).toHaveClass(/is-selected/)
  })

  test("场景导航与主次操作分层且不重复", async ({ page, browserErrors }) => {
    const failedApiResponses = []
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) failedApiResponses.push(`${response.status()} ${response.url()}`)
    })
    const project = await createProject({ title: "Scene 顶部操作布局", genre: "fantasy", language: "zh" })
    testProjectId = project.id

    await openWorkbench(page, project, "outline", "scenes")

    const emptyState = page.locator(".scene-workbench-empty")
    await expect(emptyState.getByRole("heading", { name: "还没有场景" })).toBeVisible()
    await expect(emptyState).toContainText("可以从已有正文整理情节")
    const emptyExtract = emptyState.locator('[data-action="empty-scene-auto-extract"]')
    await emptyExtract.click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("从正文整理场景")
    await page.keyboard.press("Escape")
    await expect(page.locator(SEL.modalOverlay)).not.toBeVisible()
    await expect(emptyExtract).toBeFocused()

    await expect(page.locator('[data-action="set-scene-view-mode"][data-mode="hot"]')).toHaveAttribute("aria-pressed", "true")
    await page.locator('[data-action="set-scene-view-mode"][data-mode="normal"]').click()
    await expect(page).toHaveURL(/outline\/scenes\?mode=normal$/)
    await expect(page.locator('[data-action="set-scene-view-mode"][data-mode="normal"]')).toHaveAttribute("aria-pressed", "true")
    await expect.poll(() => page.evaluate(
      (projectId) => localStorage.getItem(`novel_view_mode:${projectId}:scene-workbench`),
      project.id,
    )).toBe("normal")
    await expect(page.locator('[data-action="scene-auto-extract"]')).toHaveCount(1)
    await expect(page.locator('[data-action="start-smart-dedup"], [data-action="show-smart-dedup-progress"]')).toHaveCount(1)
    await expect(page.locator("#workspace-header")).toHaveCount(0)
    await expect(page.locator(".outline-scene-layout .subnav")).toHaveCount(1)
    await expect(page.locator(".outline-scene-layout .subnav .scene-workbench-actions")).toHaveCount(0)
    await expect(page.locator(".outline-scene-layout .view-header__tail .scene-workbench-actions")).toHaveCount(1)
    await expect(page.locator(".outline-scene-layout .view-header__title")).toContainText("场景 共 0 个")
    await expect(page.locator(".outline-scene-layout .view-header__actions > .btn-primary")).toHaveCount(1)

    const tools = page.locator(".scene-workbench-tools")
    const toolsSummary = tools.locator("summary")
    await toolsSummary.focus()
    await toolsSummary.press("Enter")
    await expect(tools).toHaveAttribute("open", "")
    const autoExtract = tools.locator('[data-action="scene-auto-extract"]')
    await autoExtract.click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("从正文整理场景")
    await page.keyboard.press("Escape")
    await expect(page.locator(SEL.modalOverlay)).not.toBeVisible()
    await expect(autoExtract).toBeFocused()
    await toolsSummary.click()
    await expect(tools).not.toHaveAttribute("open", "")

    await page.setViewportSize({ width: 390, height: 844 })
    await expectNoPageOverflow(page)
    for (const tab of await page.locator(".outline-scene-layout .subnav-item").all()) await expectWithinViewport(tab)

    for (const theme of ["night", "ink", "sticky"]) {
      await page.locator(`.theme-dot[data-theme-value="${theme}"]`).click()
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme)
      await expectNoPageOverflow(page)
    }
    await page.emulateMedia({ reducedMotion: "reduce" })
    await page.setViewportSize({ width: 375, height: 812 })
    await page.locator("html").evaluate((element) => { element.style.fontSize = "125%" })
    await expectNoPageOverflow(page)
    await expect(page.locator('[data-action="ai-create-planned-scene"]')).toBeVisible()
    await page.setViewportSize({ width: 844, height: 390 })
    await expectNoPageOverflow(page)
    expect(browserErrors).toEqual([])
    expect(failedApiResponses).toEqual([])
  })

  test("场景筛选更新失败时保留旧内容并可恢复", async ({ page, browserErrors }) => {
    const project = await createProject({ title: "Scene 列表恢复", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const failedApiResponses = []
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) failedApiResponses.push(`${response.status()} ${response.url()}`)
    })
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "密道入口",
      goal: "找到进入王城的路",
      core_conflict: "入口已被封锁",
      chapter_ids: ["1"],
    })
    const workbenchPattern = "**/api/outline/scene-workbench?*"
    let requestMode = "fail"

    await openWorkbench(page, project, "outline", "scenes")
    const row = page.locator(`.scene-workbench-row[data-id="${scene.id}"]`)
    await expect(row).toBeVisible()

    await page.route(workbenchPattern, async (route) => {
      if (requestMode === "fail") {
        await route.fulfill({
          status: 429,
          contentType: "application/json",
          body: JSON.stringify({ detail: "暂时无法更新" }),
        })
        return
      }
      await route.continue()
    })
    await page.locator(".scene-workbench-filters > summary").click()
    await page.locator("#scene-filter-q").fill("不存在的场景")
    await page.locator('[data-action="apply-scene-filters"]').click()
    const refreshError = page.locator('.scene-workbench-refresh[role="alert"]')
    await expect(refreshError).toContainText("场景列表未能更新")
    await expect(refreshError).toContainText("当前内容仍保留")
    await expect(row).toBeVisible()

    requestMode = "pass"
    await refreshError.locator('[data-action="retry-scene-refresh"]').click()
    const filteredEmpty = page.locator(".scene-workbench-empty")
    await expect(page.locator(".scene-workbench__organize")).toHaveAttribute("aria-busy", "false")
    await expect(refreshError).toHaveCount(0)
    await expect(filteredEmpty.getByRole("heading", { name: "没有找到符合条件的场景" })).toBeVisible()

    await page.locator('.theme-dot[data-theme-value="night"]').click()
    await page.emulateMedia({ reducedMotion: "reduce" })
    await page.locator("html").evaluate((element) => { element.style.fontSize = "125%" })
    await page.setViewportSize({ width: 390, height: 844 })
    await expectNoPageOverflow(page)
    const clearFilters = filteredEmpty.locator('[data-action="clear-scene-empty-filters"]')
    expect(await clearFilters.evaluate((button) => button.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
    await page.unroute(workbenchPattern)
    expect(failedApiResponses).toHaveLength(1)
    expect(failedApiResponses[0]).toContain("429")
    expect(browserErrors.filter((error) => {
      return !(error.kind === "console" && error.text?.includes("429 (Too Many Requests)"))
    })).toEqual([])
  })

  test("单个结构待整理项可标记无需整理并从更多菜单恢复", async ({ page }) => {
    const project = await createProject({ title: "Scene 整理裁决", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "无需调整的场景",
      status: "canonical",
      goal: "保留当前结构",
      core_conflict: "系统提示与作者判断不同",
      must_happen: "记录作者裁决",
      must_not_happen: "改动正文",
      chapter_ids: ["1"],
      structure_meta: { needs_organize: true, reviewed_at: "2026-08-13T00:00:00Z" },
    })
    await page.setViewportSize({ width: 390, height: 844 })
    await openWorkbench(page, project, "outline", "scenes")

    await page.locator('.scene-workbench-overview > summary').click()
    await page.locator('[data-action="filter-health"][data-id="needs_organize"]').click()
    const row = page.locator(`.scene-workbench-row[data-id="${scene.id}"]`)
    await row.locator('input[data-action="toggle-fusion-selection"]').check()
    await expect(page.locator('[data-action="handle-selected-context-actions"]')).toHaveText("整理映射")
    await page.locator('[data-action="handle-selected-context-actions"]').click()
    await expect(page.locator("#modal-title")).toHaveText("整理场景正文范围")
    await page.getByRole("button", { name: "标记为无需整理" }).click()

    await expect(row).toHaveCount(0)
    await page.locator('[data-action="filter-health"][data-id="needs_organize"]').click()
    await expect(row).toBeVisible()
    await row.locator(".action-menu-btn").click()
    await row.locator('[data-action="restore-scene-organize"]').click()

    await expect(row).toContainText("待整理")
    await expectNoPageOverflow(page)
  })

  test("热点进度分段清楚并在导航与作品切换后恢复", async ({ page, browserErrors }) => {
    const project = await createProject({ title: "Scene 热点定位", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const otherProject = await createProject({ title: "Scene 热点隔离", genre: "fantasy", language: "zh" })
    const past = await createScene(project.id, {
      scene_index: 0,
      title: "已经写过",
      chapter_ids: ["1"],
    })
    const current = await createScene(project.id, {
      scene_index: 1,
      title: "正在发生",
      chapter_ids: ["2", "4"],
    })
    const upcoming = await createScene(project.id, {
      scene_index: 2,
      title: "未来事件",
      chapter_ids: ["5"],
    })
    await createDraft(project.id, 1, "第一章", "已完成正文")
    await createDraft(project.id, 3, "第三章", "当前正文")
    await createDraft(project.id, 99, "占位章", " \n\t　")
    const failedApiResponses = []
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) failedApiResponses.push(`${response.status()} ${response.url()}`)
    })

    try {
      await openWorkbench(page, project, "outline", "scenes")

      const overview = page.locator(".scene-workbench-overview")
      const overviewSummary = overview.locator(":scope > summary")
      const progressPanel = page.locator(".scene-progress-panel")
      const progressFilters = progressPanel.locator('[data-action="filter-progress-segment"]')
      await expect(overview).toHaveAttribute("open", "")
      await expect(progressPanel).toContainText("截至第 3 章")
      await expect(progressFilters).toHaveCount(4)
      for (const segment of ["current", "upcoming", "past", "unassigned"]) {
        await expect(progressPanel.locator(`[data-action="filter-progress-segment"][data-segment="${segment}"]`)).toHaveClass(new RegExp(`scene-progress-filter--${segment}`))
      }
      await expect(page.locator(`.scene-workbench-row[data-id="${past.id}"] .scene-progress-chip`)).toHaveClass(/scene-progress-chip--past/)
      await expect(page.locator(`.scene-workbench-row[data-id="${current.id}"] .scene-progress-chip`)).toHaveClass(/scene-progress-chip--current/)
      await expect(page.locator(`.scene-workbench-row[data-id="${upcoming.id}"] .scene-progress-chip`)).toHaveClass(/scene-progress-chip--upcoming/)
      const currentMeta = page.locator(`.scene-workbench-row[data-id="${current.id}"] .scene-workbench-row__meta`)
      expect(await currentMeta.locator(":scope > span:not(:last-child)").evaluateAll((spans) => spans.map((span) => getComputedStyle(span, "::after").content))).toEqual(["\"·\"", "\"·\"", "\"·\"", "\"·\""])

      const currentFilter = page.locator('[data-action="filter-progress-segment"][data-segment="current"]')
      await currentFilter.click()
      await expect(currentFilter).toHaveClass(/active/)
      await expect(currentFilter).toHaveAttribute("aria-pressed", "true")
      await expect(page.locator(`.scene-workbench-row[data-id="${current.id}"]`)).toBeVisible()
      await expect(page.locator(`.scene-workbench-row[data-id="${past.id}"]`)).toHaveCount(0)
      await expect(page.locator(`.scene-workbench-row[data-id="${upcoming.id}"]`)).toHaveCount(0)

      await page.reload()
      await expect(currentFilter).toHaveAttribute("aria-pressed", "true")
      await expect(page.locator(`.scene-workbench-row[data-id="${current.id}"]`)).toBeVisible()
      await page.evaluate(() => window.router.navigate("outline", "story-outline"))
      await expect(page).toHaveURL(/outline\/story-outline/)
      await page.goBack()
      await expect(currentFilter).toHaveAttribute("aria-pressed", "true")
      await page.goForward()
      await expect(page).toHaveURL(/outline\/story-outline/)
      await page.goBack()
      await expect(currentFilter).toHaveAttribute("aria-pressed", "true")

      await page.locator('.theme-dot[data-theme-value="night"]').click()
      await page.emulateMedia({ reducedMotion: "reduce" })
      await page.locator("html").evaluate((element) => { element.style.fontSize = "125%" })
      await page.setViewportSize({ width: 390, height: 844 })
      await expect(overview).not.toHaveAttribute("open", "")
      await expect(overviewSummary).toContainText("当前 1")
      await expect(overviewSummary).toContainText("缺设定 3")
      await overview.scrollIntoViewIfNeeded()
      await expectNoPageOverflow(page)
      expect(await overviewSummary.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)

      await overviewSummary.focus()
      await overviewSummary.press("Enter")
      await expect(overview).toHaveAttribute("open", "")
      await expect(progressPanel).toBeVisible()
      expect(await progressFilters.evaluateAll((buttons) => buttons.every((button) => button.getBoundingClientRect().height >= 44))).toBe(true)
      const healthFilters = overview.locator('[data-action="filter-health"]')
      expect(await healthFilters.evaluateAll((buttons) => buttons.every((button) => button.getBoundingClientRect().height >= 44))).toBe(true)
      await overview.locator('[data-action="filter-health"][data-id="missing_setup"]').click()
      await expect(overview).toHaveAttribute("open", "")
      await expect(overviewSummary).toContainText("缺设定 3")
      await page.locator("html").evaluate((element) => { element.style.fontSize = "" })
      await page.setViewportSize({ width: 1440, height: 900 })
      await expect(overview).toHaveAttribute("open", "")

      await page.locator(".sidebar-project-switcher").click()
      await page.locator(SEL.projectCard(otherProject.id)).click()
      await expect(page.locator(SEL.topbarProject)).toHaveText("Scene 热点隔离")
      await expect(page.locator('[data-action="filter-progress-segment"][aria-pressed="true"]')).toHaveCount(0)

      await page.locator(".sidebar-project-switcher").click()
      await page.locator(SEL.projectCard(project.id)).click()
      await expect(page.locator(SEL.topbarProject)).toHaveText("Scene 热点定位")
      await page.waitForFunction(() => !state.loading)
      await page.evaluate(() => window.router.navigate("outline", "scenes"))
      await page.waitForFunction(() => !state.loading)
      await expect(currentFilter).toHaveAttribute("aria-pressed", "true")
      await expect(page.locator(`.scene-workbench-row[data-id="${current.id}"]`)).toBeVisible()
      expect(browserErrors).toEqual([])
      expect(failedApiResponses).toEqual([])
    } finally {
      await cleanupProject(otherProject.id)
    }
  })

  test("选择 Scene 按需打开详情栏，浏览历史与刷新可恢复", async ({ page, browserErrors }) => {
    const project = await createProject({ title: "Scene 历史恢复", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const failedApiResponses = []
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) failedApiResponses.push(`${response.status()} ${response.url()}`)
    })
    const first = await createScene(project.id, {
      scene_index: 0,
      title: "默认 Scene",
      goal: "建立起点",
      core_conflict: "起点受阻",
      chapter_ids: ["1"],
    })
    const second = await createScene(project.id, {
      scene_index: 1,
      title: "后续 Scene",
      goal: "推进情节",
      core_conflict: "阻力升级",
      chapter_ids: ["2"],
    })

    await openWorkbench(page, project, "outline", "scenes")
    const workbench = page.locator(".scene-workbench")
    const detailRail = page.locator(".scene-detail-rail")
    const organizeRatio = () => workbench.evaluate((element) => {
      const content = element.querySelector(".scene-workbench__organize")
      return content.getBoundingClientRect().width / element.getBoundingClientRect().width
    })
    await expect(detailRail).toHaveCount(0)
    expect(await organizeRatio()).toBeGreaterThan(0.97)
    const opener = page.locator(`.scene-workbench-row[data-id="${second.id}"] [data-action="select-workbench-scene"]`)
    await opener.click()

    await expect(page).toHaveURL(new RegExp(`outline/scenes\\?mode=hot&scene_id=${second.id}$`))
    await expect(page.locator(`.scene-workbench-row[data-id="${second.id}"]`)).toHaveClass(/is-selected/)
    await expect(detailRail).toBeVisible()
    await expect(detailRail.locator(".scene-detail-panel h3")).toHaveText("后续 Scene")
    await expect(detailRail.locator("fieldset > legend")).toHaveText(["基本信息", "创作要点"])
    await expect(detailRail.locator(".scene-detail-summary h4")).toHaveText("章节与来源")
    const save = detailRail.locator('[data-action="save-scene-detail"]')
    const detailActions = detailRail.locator(".scene-detail-actions")
    const detailMore = detailActions.locator(".scene-detail-action-menu .action-menu-btn")
    const detailContextAction = detailActions.locator(":scope > button:not([data-action='save-scene-detail'])")
    await expect(save).toBeDisabled()
    await expect(save).toHaveText("已保存")
    await expect(detailActions.locator(":scope > [data-action='start-merge-scene'], :scope > [data-action='start-split-scene']")).toHaveCount(0)
    await expect(detailContextAction).toBeEnabled()
    await expect(detailMore).toHaveText("更多")
    expect(await organizeRatio()).toBeLessThan(0.75)
    await detailMore.focus()
    await detailMore.press("ArrowDown")
    const mergeScene = detailActions.getByRole("menuitem", { name: "合并场景" })
    const splitScene = detailActions.getByRole("menuitem", { name: "拆分场景" })
    await expect(mergeScene).toBeFocused()
    await mergeScene.press("ArrowDown")
    await expect(splitScene).toBeFocused()
    await splitScene.press("Escape")
    await expect(detailMore).toBeFocused()
    await page.locator('.theme-dot[data-theme-value="night"]').click()
    await expect(page.locator("html")).toHaveAttribute("data-theme", "night")
    await expect(page.locator("#toast-container > *")).toHaveCount(0, { timeout: 3000 })
    await detailMore.press("ArrowDown")
    await expect(mergeScene).toBeFocused()
    await mergeScene.press("Escape")
    await page.locator('.theme-dot[data-theme-value="ink"]').click()

    const title = detailRail.locator("#scene-detail-title")
    await title.fill("尚未保存的标题")
    await expect(save).toBeEnabled()
    await expect(save).toHaveText("保存修改")
    await expect(detailContextAction).toBeDisabled()
    await expect(detailMore).toBeDisabled()
    await expect(detailMore).toHaveAttribute("aria-label", /请先保存或放弃当前修改/)
    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("当前场景有未保存修改")
      await dialog.dismiss()
    })
    const returnToList = detailRail.getByRole("button", { name: "返回列表" })
    await returnToList.click()
    await expect(detailRail).toBeVisible()
    await expect(title).toHaveValue("尚未保存的标题")

    await title.fill("后续 Scene")
    await expect(save).toBeDisabled()
    await expect(detailContextAction).toBeEnabled()
    await expect(detailMore).toBeEnabled()
    await returnToList.click()
    await expect(detailRail).toHaveCount(0)
    await expect(opener).toBeFocused()
    expect(await organizeRatio()).toBeGreaterThan(0.97)

    await opener.click()
    await expect(detailRail).toBeVisible()
    await page.goBack()

    await expect(page).toHaveURL(/outline\/scenes\?mode=hot$/)
    await expect(page.locator(".scene-workbench-row.is-selected")).toHaveCount(0)
    await expect(detailRail).toHaveCount(0)
    expect(await organizeRatio()).toBeGreaterThan(0.97)
    await expect(page.locator(`.scene-workbench-row[data-id="${first.id}"]`)).not.toHaveClass(/is-selected/)

    await page.goForward()
    await expect(page).toHaveURL(new RegExp(`scene_id=${second.id}`))
    await expect(detailRail).toBeVisible()
    await expect(detailRail.locator(".scene-detail-panel h3")).toHaveText("后续 Scene")
    await page.reload()
    await expect(detailRail).toBeVisible()
    await expect(page.locator(`.scene-workbench-row[data-id="${second.id}"]`)).toHaveClass(/is-selected/)
    expect(browserErrors).toEqual([])
    expect(failedApiResponses).toEqual([])
  })

  test("旧 Scene 深链接自动打开目标所在分页", async ({ page }) => {
    const project = await createProject({ title: "Scene 深链接分页", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scenes = await Promise.all(Array.from({ length: 21 }, (_, index) => createScene(project.id, {
      scene_index: index,
      title: `深链接 Scene ${index + 1}`,
      goal: `目标 ${index + 1}`,
      core_conflict: `冲突 ${index + 1}`,
      chapter_ids: [String(index + 1)],
    })))
    const target = scenes.at(-1)

    await openWorkbench(page, project, "scene", target.id)

    await expect(page).toHaveURL(new RegExp(`outline/scenes\\?scene_id=${target.id}$`))
    await expect(page.locator(`.scene-workbench-row[data-id="${target.id}"]`)).toHaveClass(/is-selected/)
    await expect(page.locator(".scene-workbench-pagination")).toContainText("第 2 / 2 页")

    await page.locator('[data-action="prev-scene-page"]').click()

    await expect(page).toHaveURL(/outline\/scenes$/)
    await expect(page.locator(".scene-workbench-pagination")).toContainText("第 1 / 2 页")
  })

  test("未归类章节可以分配到 Scene", async ({ page }) => {
    const project = await createProject({ title: "Scene 分配", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "目标 Scene",
      goal: "整理章节",
      core_conflict: "结构混乱",
      must_happen: "章节归位",
      must_not_happen: "误删正文",
      chapter_ids: ["1"],
    })
    await createDraft(project.id, 1, "第一章", "正文")
    await createDraft(project.id, 3, "第三章", "未归类正文")

    await openWorkbench(page, project, "scene")
    await expect(page.locator(".scene-workbench-row--unassigned")).toContainText("第 3 章")
    await page.locator('[data-action="assign-unassigned-chapter"]').click()
    await expect(page.locator("#modal-title")).toHaveText("分配第 3 章")
    await expect(page.locator(`input[name="assign-target-scene"][value="${scene.id}"]`)).toBeChecked()
    await page.getByRole("button", { name: "确认分配" }).click()

    await expect(page.locator(".scene-workbench-row--unassigned")).toHaveCount(0, { timeout: 10000 })
    const scenes = await listScenesOrdered(project.id)
    expect(scenes[0].chapter_ids).toEqual(["1", "3"])
  })

  test("拆分必须先展示影响预览，确认后才执行", async ({ page }) => {
    const project = await createProject({ title: "Scene 拆分", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "长 Scene",
      goal: "潜入",
      core_conflict: "守卫阻拦",
      must_happen: "拿到文书",
      must_not_happen: "身份暴露",
      chapter_ids: ["1", "2"],
    })

    await openWorkbench(page, project, "scene", scene.id)
    const detailActions = page.locator(".scene-workbench__detail .scene-detail-actions")
    await detailActions.locator(".scene-detail-action-menu .action-menu-btn").click()
    await detailActions.locator('[data-action="start-split-scene"]').click()
    await expect(page.locator("#modal-title")).toHaveText("拆分场景")
    await expect(page.locator("#scene-split-partition")).toContainText("进入新场景：第 2 章")
    await page.getByRole("button", { name: "生成拆分预览" }).click()

    await expect(page.locator("#modal-title")).toHaveText("场景拆分预览")
    await expect(page.locator(".scene-draft-review-grid")).toBeVisible()
    await expect(page.locator(".scene-split-impact-summary")).toContainText("影响摘要")
    await expect(page.locator(".scene-split-impact-summary")).toContainText("保留原场景")
    await expect(page.locator(".scene-split-impact-summary")).toContainText("第 1 章")
    await expect(page.locator(".scene-split-impact-summary")).toContainText("创建新场景")
    await expect(page.locator(".scene-split-impact-summary")).toContainText("第 2 章")
    await expect(page.locator(".scene-split-impact-summary")).not.toContainText(scene.id)
    await expect(page.locator("#modal-body pre")).toHaveCount(0)
    await expect(page.locator("#modal-content")).toHaveAttribute("data-modal-size", "large")
    await page.setViewportSize({ width: 390, height: 844 })
    await expectNoPageOverflow(page)
    await expectWithinViewport(page.locator("#modal-content"))
    await expectWithinViewport(page.getByRole("button", { name: "确认拆分" }))
    let scenes = await listScenesOrdered(project.id)
    expect(scenes).toHaveLength(1)

    await page.getByRole("button", { name: "确认拆分" }).click()
    await expect(page.locator("#toast-container")).toContainText("场景已拆分", { timeout: 10000 })
    scenes = await listScenesOrdered(project.id)
    expect(scenes).toHaveLength(2)
    expect(scenes[0].chapter_ids).toEqual(["1"])
    expect(scenes[1].chapter_ids).toEqual(["2"])
  })

  test("编辑 Scene 字段后写作页驾驶舱刷新", async ({ page }) => {
    const project = await createProject({ title: "Scene 编辑联动", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "旧标题",
      goal: "旧目标",
      core_conflict: "冲突",
      must_happen: "必须",
      must_not_happen: "禁止",
      chapter_ids: ["1"],
    })
    await createDraft(project.id, 1, "第一章", "正文")

    await openWorkbench(page, project, "scene", scene.id)
    await page.locator("#scene-detail-title").fill("新标题")
    await page.locator("#scene-detail-goal").fill("新目标")
    await page.locator('[data-action="save-scene-detail"]').click()
    await expect(page.locator("#toast-container")).toContainText("场景已保存", { timeout: 10000 })
    const selectedRow = page.locator(".scene-workbench-row.is-selected")
    await expect(selectedRow.locator(".scene-workbench-row__title")).toHaveText("新标题")
    await selectedRow.locator(".action-menu-btn").click()
    const openWriting = selectedRow.locator('[data-action="open-writing-scene"]')
    await expect(openWriting).toBeVisible()
    await openWriting.click()

    await expect(page.locator("#topbar-module")).toHaveText("写作")
    await expect(page.locator("#writing-panel-container")).toContainText("新标题")
    await expect(page.locator("#writing-panel-container")).toContainText("新目标")
  })

  test("场景详情按姓名选择视角人物", async ({ page, browserErrors }) => {
    const project = await createProject({ title: "Scene 视角人物", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const otherProject = await createProject({ title: "Scene 视角隔离", genre: "fantasy", language: "zh" })
    const originalCharacter = await createEntity(project.id, {
      name: "沈岚",
      entity_type: "character",
      status: "canonical",
      summary: "王城密探",
    })
    const nextCharacter = await createEntity(project.id, {
      name: "顾澈",
      entity_type: "character",
      status: "canonical",
      summary: "熟悉王宫密道",
    })
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "夜探王城",
      goal: "取得密信",
      core_conflict: "巡逻守卫",
      pov_character_id: originalCharacter.id,
      chapter_ids: ["1"],
    })
    let expectedSearchFailure = true
    const unexpectedFailedApiResponses = []
    page.on("response", (response) => {
      if (!response.url().includes("/api/") || response.status() < 400) return
      if (response.status() === 503 && response.url().includes("/api/world/entities?")) return
      unexpectedFailedApiResponses.push(`${response.status()} ${response.url()}`)
    })
    await page.route("**/api/world/entities?*", async (route) => {
      const query = new URL(route.request().url()).searchParams.get("q")
      if (route.request().method() === "GET" && expectedSearchFailure && query === "暂时失败") {
        expectedSearchFailure = false
        await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "temporary" }) })
        return
      }
      await route.fallback()
    })

    try {
      await openWorkbench(page, project, "scene", scene.id)
      const picker = page.locator("#scene-detail-pov-character")
      await expect(picker.locator("[data-reference-selected]")).toContainText("沈岚")
      await expect(picker.locator("[data-reference-selected]")).toContainText("王城密探")
      await expect(page.locator("#scene-detail-pov_character_id")).toHaveCount(0)
      await expect(page.locator(".scene-detail-panel")).not.toContainText(originalCharacter.id)

      await picker.locator("[data-reference-remove]").click()
      const query = picker.locator("[data-reference-query]")
      await query.fill("暂时失败")
      await expect(picker.locator("[data-reference-status]")).toContainText("人物加载失败，请重试")
      await query.fill("完全不存在的人名")
      await expect(picker.locator("[data-reference-results]")).toContainText("没有匹配的人物，可换个姓名或别名再试")
      await query.fill("顾澈")
      await expect(picker.locator("[data-reference-result]", { hasText: "顾澈" })).toBeVisible()
      await query.press("ArrowDown")
      await query.press("Enter")
      await expect(picker.locator("[data-reference-selected]")).toContainText("顾澈")
      await expect(picker.locator("[data-reference-selected]")).toContainText("熟悉王宫密道")
      await expect(page.locator(".scene-detail-panel")).not.toContainText(nextCharacter.id)

      page.once("dialog", async (dialog) => {
        expect(dialog.message()).toContain("当前场景有未保存修改")
        await dialog.dismiss()
      })
      await page.locator(".sidebar-project-switcher").click()
      await expect(page.locator(SEL.topbarProject)).toHaveText("Scene 视角人物")
      await expect(picker.locator("[data-reference-selected]")).toContainText("顾澈")

      const saveRequest = page.waitForRequest((request) => request.method() === "PATCH" && new URL(request.url()).pathname.endsWith(`/api/outline/scenes/${scene.id}`))
      await page.locator('[data-action="save-scene-detail"]').click()
      expect((await saveRequest).postDataJSON()).toEqual(expect.objectContaining({ pov_character_id: nextCharacter.id }))
      await expect(page.locator(SEL.toastContainer)).toContainText("场景已保存", { timeout: 10000 })
      await expect(picker.locator("[data-reference-selected]")).toContainText("顾澈")

      await page.reload()
      await expect(picker.locator("[data-reference-selected]")).toContainText("顾澈", { timeout: 10000 })
      await page.goBack()
      await expect(page.locator("#scene-detail-pov-character")).toHaveCount(0)
      await page.goForward()
      await expect(picker.locator("[data-reference-selected]")).toContainText("顾澈")

      await page.locator('.theme-dot[data-theme-value="night"]').click()
      await expect(page.locator("html")).toHaveAttribute("data-theme", "night")
      await page.emulateMedia({ reducedMotion: "reduce" })
      await page.locator("html").evaluate((element) => { element.style.fontSize = "125%" })
      await page.setViewportSize({ width: 390, height: 844 })
      const dialog = page.getByRole("dialog", { name: "编辑场景：夜探王城" })
      await expect(dialog).toBeVisible()
      await expectNoPageOverflow(page)
      await expectWithinViewport(dialog)
      await picker.scrollIntoViewIfNeeded()
      await expectWithinViewport(picker)
      await page.setViewportSize({ width: 844, height: 390 })
      await expectNoPageOverflow(page)
      await picker.scrollIntoViewIfNeeded()
      await expectWithinViewportWidth(picker)
      await expectWithinViewport(picker.locator("[data-reference-selected]"))

      await page.locator("html").evaluate((element) => { element.style.fontSize = "" })
      await page.setViewportSize({ width: 1440, height: 900 })
      await page.locator(".sidebar-project-switcher").click()
      await page.locator(SEL.projectCard(otherProject.id)).click()
      await expect(page.locator(SEL.topbarProject)).toHaveText("Scene 视角隔离")
      await expect(page.locator("#scene-detail-pov-character")).toHaveCount(0)

      await page.locator(".sidebar-project-switcher").click()
      await page.locator(SEL.projectCard(project.id)).click()
      await expect(page.locator(SEL.topbarProject)).toHaveText("Scene 视角人物")
      await page.waitForFunction(() => !state.loading)
      await page.evaluate(() => window.router.navigate("outline", "scenes"))
      await page.waitForFunction(() => !state.loading)
      await page.locator(`.scene-workbench-row[data-id="${scene.id}"] [data-action="select-workbench-scene"]`).click()
      await expect(page.locator("#scene-detail-pov-character [data-reference-selected]")).toContainText("顾澈")

      expect(expectedSearchFailure).toBe(false)
      expect(unexpectedFailedApiResponses).toEqual([])
      expect(browserErrors.filter((error) => {
        const expectedResponse = error.kind === "response" && error.status === 503 && error.url?.includes("/api/world/entities?")
        const expectedConsole = error.kind === "console" && error.text?.includes("503 (Service Unavailable)")
        return !expectedResponse && !expectedConsole
      })).toEqual([])
    } finally {
      await cleanupProject(otherProject.id)
    }
  })

  test("已采用 Scene 可移入历史并通过历史筛选查看", async ({ page }) => {
    const project = await createProject({ title: "Scene 移入历史", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "旧版潜入计划",
      goal: "潜入王宫",
      core_conflict: "守卫巡查",
      chapter_ids: ["1"],
      status: "canonical",
    })

    await openWorkbench(page, project, "outline", "scenes")
    const row = page.locator(`.scene-workbench-row[data-id="${scene.id}"]`)
    await row.locator(".action-menu-btn").click()
    await row.locator('[data-action="move-scene-to-history"]').click()

    await expect(page.locator("#modal-title")).toHaveText("确认操作")
    await expect(page.locator("#modal-body")).toContainText("正文和追踪信息会保留")
    await page.getByRole("button", { name: "确认移入历史" }).click()

    await expect(page.locator("#toast-container")).toContainText("场景已移入历史", { timeout: 10000 })
    await expect(page.locator(`.scene-workbench-row[data-id="${scene.id}"]`)).toHaveCount(0)
    await expect(page).toHaveURL(/outline\/scenes$/)

    await page.locator(".scene-workbench-filters > summary").click()
    await page.locator("#scene-filter-status").selectOption("deprecated")
    await page.locator('[data-action="apply-scene-filters"]').click()

    const historyRow = page.locator(`.scene-workbench-row[data-id="${scene.id}"]`)
    await expect(historyRow).toBeVisible()
    await expect(historyRow).toContainText("历史")
    await historyRow.locator(".action-menu-btn").click()
    await expect(historyRow.locator('[data-action="move-scene-to-history"]')).toHaveCount(0)
  })

  test("手动融合可保存新 Scene 并废弃原 Scene", async ({ page }) => {
    const project = await createProject({ title: "Scene 手动融合", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const first = await createScene(project.id, {
      scene_index: 0,
      title: "调查旧港",
      goal: "找到线索",
      core_conflict: "守卫阻拦",
      must_happen: "发现暗号",
      must_not_happen: "暴露身份",
      chapter_ids: ["1"],
    })
    const second = await createScene(project.id, {
      scene_index: 1,
      title: "潜入仓库",
      goal: "确认走私路线",
      core_conflict: "巡逻靠近",
      must_happen: "拿到账册",
      must_not_happen: "惊动敌人",
      chapter_ids: ["2"],
    })

    await openWorkbench(page, project, "scene")
    await page.locator(`.scene-workbench-row[data-id="${first.id}"] input[data-action="toggle-fusion-selection"]`).check()
    await page.locator(`.scene-workbench-row[data-id="${second.id}"] input[data-action="toggle-fusion-selection"]`).check()
    await page.locator('[data-action="start-ai-fusion-draft"]').click()
    await expect(page.locator("#modal-title")).toHaveText("选择主场景")
    await page.evaluate(() => {
      const button = Array.from(document.querySelectorAll("#modal-footer button"))
        .find((item) => item.textContent?.includes("生成 AI 融合建议"))
      button?.click()
    })
    await page.locator('[data-role="scene-fusion-preview-progress"] summary').click()
    await page.getByRole("button", { name: "查看预览" }).click()
    await expect(page.locator("#modal-title")).toHaveText("场景 AI 建议预览")
    await expect(page.locator("#modal-body")).toContainText("找到线索")
    await expect(page.locator("#modal-body")).toContainText("确认走私路线")
    const footerLayout = await page.evaluate(() => {
      const footer = document.querySelector("#modal-footer")
      const content = document.querySelector("#modal-content")
      const contentRect = content?.getBoundingClientRect()
      const buttons = Array.from(document.querySelectorAll("#modal-footer button"))
        .map((button) => {
          const rect = button.getBoundingClientRect()
          return {
            text: button.textContent || "",
            left: rect.left,
            right: rect.right,
          }
        })
      return {
        footerWrap: footer ? getComputedStyle(footer).flexWrap : "",
        modalSize: content?.dataset.modalSize || "",
        tableDisplay: getComputedStyle(document.querySelector(".scene-draft-review-grid")).display,
        bodyHasHorizontalOverflow: (() => {
          const body = document.querySelector("#modal-body")
          return body ? body.scrollWidth > body.clientWidth + 1 : true
        })(),
        buttonsWithinContent: Boolean(contentRect) && buttons.every((button) => (
          button.left >= contentRect.left - 1 && button.right <= contentRect.right + 1
        )),
      }
    })
    expect(footerLayout.footerWrap).toBe("wrap")
    expect(footerLayout.modalSize).toBe("large")
    expect(footerLayout.tableDisplay).toBe("table")
    expect(footerLayout.bodyHasHorizontalOverflow).toBe(false)
    expect(footerLayout.buttonsWithinContent).toBe(true)
    await page.locator("#scene-fusion-title").fill("旧港与仓库调查")
    await page.evaluate(() => {
      const button = Array.from(document.querySelectorAll("#modal-footer button"))
        .find((item) => item.textContent?.includes("将 2 个原场景移入历史并保存"))
      button?.click()
    })
    await expect(page.locator('[data-role="fusion-deprecation-confirm"]')).toBeVisible()
    const scenesBeforeConfirm = await listScenesOrdered(project.id)
    expect(scenesBeforeConfirm.filter((scene) => scene.id === first.id || scene.id === second.id)
      .every((scene) => scene.status === "draft")).toBe(true)
    await page.locator('[data-action="confirm-fusion-deprecation"]').click()
    await expect(page.locator("#toast-container")).toContainText("融合场景已保存", { timeout: 10000 })

    const deprecatedScenes = await listScenes(project.id, { status: "deprecated" })
    const deprecatedIds = new Set((deprecatedScenes.items || deprecatedScenes).map((scene) => scene.id))
    expect(deprecatedIds.has(first.id)).toBe(true)
    expect(deprecatedIds.has(second.id)).toBe(true)

    const scenes = await listScenesOrdered(project.id)
    const fused = scenes.find((scene) => scene.id !== first.id && scene.id !== second.id)
    expect(fused?.source).toBe("manual_fusion")
  })

  test("Scene AI 建议表在中窄屏纵向重排且不横向溢出", async ({ page }) => {
    const project = await createProject({ title: "Scene 预览响应式", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const first = await createScene(project.id, {
      scene_index: 0,
      title: "长文本来源一",
      goal: "第一条需要比较的长目标。".repeat(12),
      chapter_ids: ["1"],
    })
    const second = await createScene(project.id, {
      scene_index: 1,
      title: "长文本来源二",
      goal: "第二条需要比较的长目标。".repeat(12),
      chapter_ids: ["2"],
    })

    await page.setViewportSize({ width: 1280, height: 800 })
    await openWorkbench(page, project, "scene")
    await page.locator(`.scene-workbench-row[data-id="${first.id}"] input[data-action="toggle-fusion-selection"]`).check()
    await page.locator(`.scene-workbench-row[data-id="${second.id}"] input[data-action="toggle-fusion-selection"]`).check()
    await page.locator('[data-action="start-ai-fusion-draft"]').click()
    await page.getByRole("button", { name: "生成 AI 融合建议" }).click()
    await page.locator('[data-role="scene-fusion-preview-progress"] summary').click()
    await page.getByRole("button", { name: "查看预览" }).click()
    await expect(page.locator("#modal-title")).toHaveText("场景 AI 建议预览")

    for (const width of [820, 390]) {
      await page.setViewportSize({ width, height: 800 })
      const layout = await page.evaluate(() => {
        const body = document.querySelector("#modal-body")
        const table = document.querySelector(".scene-draft-review-grid")
        const firstCell = table?.querySelector("td")
        const content = document.querySelector("#modal-content")
        const contentRect = content?.getBoundingClientRect()
        const footerButtons = Array.from(document.querySelectorAll("#modal-footer button"))
          .map((button) => button.getBoundingClientRect())
        return {
          tableDisplay: table ? getComputedStyle(table).display : "",
          cellDisplay: firstCell ? getComputedStyle(firstCell).display : "",
          bodyHasHorizontalOverflow: body ? body.scrollWidth > body.clientWidth + 1 : true,
          buttonsWithinContent: Boolean(contentRect) && footerButtons.every((rect) => (
            rect.left >= contentRect.left - 1 && rect.right <= contentRect.right + 1
          )),
        }
      })
      expect(layout.tableDisplay).toBe("block")
      expect(layout.cellDisplay).toBe("block")
      expect(layout.bodyHasHorizontalOverflow).toBe(false)
      expect(layout.buttonsWithinContent).toBe(true)
    }
  })

  test("手动融合可放弃后继续编辑结果再保存", async ({ page }) => {
    const project = await createProject({ title: "Scene 融合编辑保存", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const first = await createScene(project.id, {
      scene_index: 0,
      title: "追踪线索",
      goal: "锁定嫌疑人",
      core_conflict: "线索被销毁",
      chapter_ids: ["1"],
    })
    const second = await createScene(project.id, {
      scene_index: 1,
      title: "夜审证人",
      goal: "获得证词",
      core_conflict: "证人恐惧",
      chapter_ids: ["2"],
    })

    const selectScenes = async () => {
      await page.locator(`.scene-workbench-row[data-id="${first.id}"] input[data-action="toggle-fusion-selection"]`).check()
      await page.locator(`.scene-workbench-row[data-id="${second.id}"] input[data-action="toggle-fusion-selection"]`).check()
      await page.locator('[data-action="start-ai-fusion-draft"]').click()
      await expect(page.locator("#modal-title")).toHaveText("选择主场景")
      await page.evaluate(() => {
        const button = Array.from(document.querySelectorAll("#modal-footer button"))
          .find((item) => item.textContent?.includes("生成 AI 融合建议"))
        button?.click()
      })
      await page.locator('[data-role="scene-fusion-preview-progress"] summary').click()
      await page.getByRole("button", { name: "查看预览" }).click()
      await expect(page.locator("#modal-title")).toHaveText("场景 AI 建议预览")
    }
    const clickFusionButton = async (text) => {
      await page.evaluate((label) => {
        const button = Array.from(document.querySelectorAll("#modal-footer button"))
          .find((item) => item.textContent?.includes(label))
        button?.click()
      }, text)
    }

    await openWorkbench(page, project, "scene")
    await selectScenes()
    await clickFusionButton("放弃融合结果")
    await expect(page.locator("#toast-container")).toContainText("融合结果已放弃", { timeout: 10000 })
    let scenes = await listScenesOrdered(project.id)
    expect(scenes).toHaveLength(2)

    await openWorkbench(page, project, "scene")
    await selectScenes()
    await page.locator("#scene-fusion-title").fill("线索与证词合流")
    await page.locator("#scene-fusion-goal").fill("锁定真正嫌疑人")
    await clickFusionButton("继续编辑融合结果后再保存")
    await expect(page.locator("#toast-container")).toContainText("融合场景已保存", { timeout: 10000 })

    scenes = await listScenesOrdered(project.id)
    expect(scenes.some((scene) => scene.title === "线索与证词合流" && scene.goal === "锁定真正嫌疑人")).toBe(true)
    const sourceScenes = scenes.filter((scene) => scene.id === first.id || scene.id === second.id)
    expect(sourceScenes.every((scene) => scene.status === "draft")).toBe(true)
  })

  test("多选 Scene 不会重绘页面或把列表滚回顶部", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 620 })
    const project = await createProject({ title: "Scene 多选滚动保持", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scenes = await Promise.all(Array.from({ length: 18 }, (_, index) => createScene(project.id, {
      scene_index: index,
      title: `滚动 Scene ${index}`,
      goal: `目标 ${index}`,
      core_conflict: `冲突 ${index}`,
      chapter_ids: [String(index + 1)],
    })))

    await openWorkbench(page, project, "scene")
    const organize = page.locator(".scene-workbench__organize")
    await organize.evaluate((el) => { el.scrollTop = el.scrollHeight })
    const before = await organize.evaluate((el) => el.scrollTop)
    expect(before).toBeGreaterThan(50)

    await page.locator(`.scene-workbench-row[data-id="${scenes.at(-1).id}"] input[data-action="toggle-fusion-selection"]`).check()

    const after = await organize.evaluate((el) => el.scrollTop)
    expect(after).toBeGreaterThan(50)
    await expect(page.locator(".scene-fusion-toolbar")).toContainText("1")
  })

  test("Scene 进度轮询只更新进度卡并保持列表滚动位置", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 620 })
    const project = await createProject({ title: "Scene 进度局部刷新", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    await Promise.all(Array.from({ length: 18 }, (_, index) => createScene(project.id, {
      scene_index: index,
      title: `进度浏览 Scene ${index}`,
      goal: `目标 ${index}`,
      core_conflict: `冲突 ${index}`,
      chapter_ids: [String(index + 1)],
    })))

    const taskId = "11111111-1111-4111-8111-111111111111"
    let phase = "phase1a"
    await page.route(`**/api/tasks/${taskId}?*`, async (route) => {
      const phase1a = phase === "phase1a"
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: taskId,
          task_type: "scene_auto_extraction",
          status: "running",
          progress: phase1a ? 0.295 : 0.79,
          result: {
            current_phase: phase1a ? "phase1a_scene_slicing" : "phase1b_enrichment",
            current_item: phase1a
              ? { kind: "window", completed: 2, total: 4 }
              : { kind: "scene_candidate", completed: 41, total: 82 },
            phase_timeline: phase1a
              ? [
                  { phase: "phase0_plan", status: "completed" },
                  { phase: "phase1a_scene_slicing", status: "running" },
                ]
              : [
                  { phase: "phase0_plan", status: "completed" },
                  { phase: "phase1a_scene_slicing", status: "completed" },
                  { phase: "phase1b_enrichment", status: "running" },
                ],
          },
        }),
      })
    })

    await openWorkbench(page, project, "scene")
    await page.evaluate(({ taskId: id, projectId }) => {
      localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
        id: `${projectId}:scene_auto_extraction:${id}`,
        taskId: id,
        workflowType: "scene_auto_extraction",
        projectId,
        view: "scene",
        meta: { start_chapter: 1, end_chapter: 60 },
      }]))
    }, { taskId, projectId: project.id })
    await page.reload()
    await expect(page.locator('[data-role="scene-auto-extract-progress"]')).toContainText(
      "阶段 2 · 划分场景边界｜窗口 2/4",
    )

    const organize = page.locator(".scene-workbench__organize")
    await organize.evaluate((el) => { el.scrollTop = el.scrollHeight })
    const before = await organize.evaluate((el) => el.scrollTop)
    expect(before).toBeGreaterThan(50)
    await page.locator("#scene-filter-q").evaluate((input) => {
      input.value = "正在浏览"
    })

    phase = "phase1b"
    await expect(page.locator('[data-role="scene-auto-extract-progress"]')).toContainText(
      "阶段 3 · 补充场景资料｜场景 41/82",
      { timeout: 5000 },
    )

    expect(await organize.evaluate((el) => el.scrollTop)).toBe(before)
    await expect(page.locator("#scene-filter-q")).toHaveValue("正在浏览")
  })

  test("Scene 翻页按钮在列表内容底部且不覆盖场景卡片", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 620 })
    const project = await createProject({ title: "Scene 分页底部悬浮", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    await Promise.all(Array.from({ length: 22 }, (_, index) => createScene(project.id, {
      scene_index: index,
      title: `分页 Scene ${index}`,
      goal: `目标 ${index}`,
      core_conflict: `冲突 ${index}`,
      chapter_ids: [String(index + 1)],
    })))

    await openWorkbench(page, project, "scene")
    await page.locator(".scene-workbench__organize").evaluate((el) => {
      el.scrollTop = el.scrollHeight
    })
    const pagination = page.locator(".scene-workbench-pagination")
    await expect(pagination).toBeVisible()
    await expect(pagination).toContainText("第 1 / 2 页")

    const paginationState = await page.evaluate(() => {
      const list = document.querySelector(".scene-workbench__organize")
      const pager = document.querySelector(".scene-workbench-pagination")
      const listRect = list?.getBoundingClientRect()
      const pagerRect = pager?.getBoundingClientRect()
      const geometryTolerance = 1
      const style = pager ? getComputedStyle(pager) : null
      const rows = Array.from(document.querySelectorAll(".scene-workbench-row"))
      const overlaps = rows.filter((row) => {
        const rect = row.getBoundingClientRect()
        return Boolean(pagerRect)
          && rect.left < pagerRect.right
          && rect.right > pagerRect.left
          && rect.top < pagerRect.bottom
          && rect.bottom > pagerRect.top
      })
      return {
        workspaceHasOuterScroll: (() => {
          const workspace = document.querySelector("#workspace-content")
          return workspace ? workspace.scrollHeight > workspace.clientHeight + 2 : true
        })(),
        position: style?.position || "",
        afterRows: Boolean(pagerRect && rows.length) && pagerRect.top >= rows.at(-1).getBoundingClientRect().bottom,
        insideList: Boolean(listRect && pagerRect)
          && pagerRect.left >= listRect.left
          && pagerRect.right <= listRect.right
          && pagerRect.top >= listRect.top
          // scrollTop/clientHeight use integer CSS pixels while DOMRect may be fractional.
          && pagerRect.bottom <= listRect.bottom + geometryTolerance,
        overlappingRows: overlaps.length,
        nextHitTarget: (() => {
          const nextButton = document.querySelector('[data-action="next-scene-page"]')
          if (!nextButton) return null
          const rect = nextButton.getBoundingClientRect()
          const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
          return hit?.getAttribute("data-action") || null
        })(),
      }
    })
    expect(paginationState).toEqual({
      workspaceHasOuterScroll: false,
      position: "static",
      afterRows: true,
      insideList: true,
      overlappingRows: 0,
      nextHitTarget: "next-scene-page",
    })
  })

  test("窄屏场景详情可补全、保存、返回并恢复", async ({ page, browserErrors }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const project = await createProject({ title: "Scene 移动端", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const otherProject = await createProject({ title: "Scene 切换作品", genre: "fantasy", language: "zh" })
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "移动端 Scene",
      goal: "目标",
      core_conflict: null,
      must_happen: "必须",
      must_not_happen: "禁止",
      chapter_ids: ["1"],
    })
    try {
      await openWorkbench(page, project, "scene")

      await expect(page.locator(".scene-workbench__organize")).toBeVisible()
      await expect(page.locator(".scene-workbench-row .scene-context-action")).toBeVisible()
      await expect(page.locator(".scene-workbench-row .scene-secondary-action")).toBeHidden()
      await expect(page.locator(".scene-workbench-row .action-menu-btn")).toBeVisible()
      await expect(page.locator(".scene-workbench-row.is-selected")).toHaveCount(0)
      await expect(page.locator(".scene-workbench-drawer")).toHaveCount(0)
      await expectNoPageOverflow(page)

      const opener = page.locator(`.scene-workbench-row[data-id="${scene.id}"] [data-action="select-workbench-scene"]`)
      await opener.click()
      await expect(page).toHaveURL(new RegExp(`scene_id=${scene.id}`))
      const dialog = page.getByRole("dialog", { name: "编辑场景：移动端 Scene" })
      await expectWithinViewport(dialog)
      await expect(page.locator("#sidebar")).toBeHidden()
      await expect(dialog.locator("fieldset > legend")).toHaveText(["基本信息", "创作要点"])
      await expect(dialog.locator(".scene-detail-summary h4")).toHaveText("章节与来源")
      const mobileSave = dialog.locator('[data-action="save-scene-detail"]')
      const mobileMore = dialog.locator(".scene-detail-action-menu .action-menu-btn")
      await expect(mobileSave).toHaveText("已保存")
      await expect(mobileMore).toHaveText("更多")
      expect(await mobileMore.evaluate((button) => button.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
      await expectWithinViewport(dialog.locator(".scene-detail-actions"))
      await expect.poll(() => mobileSave.evaluate((button) => {
        const rect = button.getBoundingClientRect()
        const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
        return hit === button || button.contains(hit)
      })).toBe(true)
      const closeButton = dialog.getByRole("button", { name: "返回列表" })
      await expectWithinViewport(closeButton)
      await expect(closeButton).toBeFocused()
      await mobileMore.focus()
      await mobileMore.press("ArrowDown")
      const mobileMenu = dialog.locator(".scene-detail-action-menu .action-menu-list")
      await expectWithinViewport(mobileMenu)
      const mobileMerge = dialog.getByRole("menuitem", { name: "合并场景" })
      await expect(mobileMerge).toBeFocused()
      expect(await mobileMerge.evaluate((button) => button.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
      await page.keyboard.press("Escape")
      await expect(dialog).toBeVisible()
      await expect(mobileMore).toBeFocused()
      await page.emulateMedia({ reducedMotion: "reduce" })
      await page.locator("html").evaluate((element) => { element.style.fontSize = "125%" })
      await page.setViewportSize({ width: 760, height: 390 })
      await expectNoPageOverflow(page)
      await expectWithinViewport(dialog.locator(".scene-detail-actions"))
      await mobileMore.press("ArrowDown")
      await expectWithinViewport(mobileMenu)
      await page.keyboard.press("Escape")
      await expect(dialog).toBeVisible()
      await page.locator("html").evaluate((element) => { element.style.fontSize = "" })
      await page.setViewportSize({ width: 375, height: 812 })
      await expectNoPageOverflow(page)
      await expectWithinViewport(dialog.locator(".scene-detail-actions"))
      await mobileMore.press("ArrowDown")
      await expectWithinViewport(mobileMenu)
      await page.keyboard.press("Escape")
      await page.setViewportSize({ width: 390, height: 844 })
      await closeButton.focus()
      await page.keyboard.press("Escape")
      await expect(dialog).toHaveCount(0)
      await expect(page.locator("#sidebar")).toBeVisible()
      await expect(page).not.toHaveURL(/scene_id=/)
      await expect(opener).toBeFocused()

      await page.locator(`.scene-workbench-row[data-id="${scene.id}"] [data-action="handle-scene-health"][data-health="missing_setup"]`).click()
      await expect(page.locator("#scene-detail-core_conflict")).toBeFocused()
      await page.locator("#scene-detail-core_conflict").fill("必须避开巡逻守卫")
      await expect(mobileMore).toBeDisabled()
      await page.keyboard.press("Escape")
      const confirmation = page.locator(SEL.modalOverlay)
      await expect(confirmation).toBeVisible()
      await confirmation.getByRole("button", { name: "取消" }).click()
      await expect(dialog).toBeVisible()
      await expect(page.locator("#scene-detail-core_conflict")).toHaveValue("必须避开巡逻守卫")

      await page.setViewportSize({ width: 1440, height: 900 })
      page.once("dialog", async (nativeDialog) => {
        expect(nativeDialog.message()).toContain("当前场景有未保存修改")
        await nativeDialog.dismiss()
      })
      await page.locator(".sidebar-project-switcher").click()
      await expect(page.locator(SEL.topbarProject)).toHaveText("Scene 移动端")
      await expect(page.locator("#scene-detail-core_conflict")).toHaveValue("必须避开巡逻守卫")
      await page.setViewportSize({ width: 390, height: 844 })
      await expect(dialog).toBeVisible()

      let rejectNextSave = true
      await page.route(`**/api/outline/scenes/${scene.id}?*`, async (route) => {
        if (route.request().method() === "PATCH" && rejectNextSave) {
          rejectNextSave = false
          await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "保存冲突，请重试" }) })
          return
        }
        await route.fallback()
      })
      await mobileSave.click()
      await expect(dialog.getByRole("alert")).toContainText("保存失败")
      await expect(page.locator("#scene-detail-core_conflict")).toHaveValue("必须避开巡逻守卫")

      const saveResponse = page.waitForResponse((response) => response.request().method() === "PATCH" && response.url().includes(`/api/outline/scenes/${scene.id}`) && response.ok())
      await mobileSave.click()
      await saveResponse
      await expect(dialog.getByRole("alert")).toHaveCount(0)
      await expect(mobileMore).toBeEnabled()

      await page.reload()
      await expect(dialog).toBeVisible({ timeout: 10000 })
      await expect(page.locator("#scene-detail-core_conflict")).toHaveValue("必须避开巡逻守卫")
      await page.goBack()
      await expect(dialog).toHaveCount(0)
      await expect(page).not.toHaveURL(/scene_id=/)
      await page.goForward()
      await expect(dialog).toBeVisible()

      await page.setViewportSize({ width: 1440, height: 900 })
      await page.locator(".sidebar-project-switcher").click()
      await page.locator(SEL.projectCard(otherProject.id)).click()
      await expect(page.locator(SEL.topbarProject)).toHaveText("Scene 切换作品")
      await expect(dialog).toHaveCount(0)
      await page.waitForFunction(() => !state.loading)
      await page.evaluate(() => window.router.navigate("outline", "scenes"))
      await page.waitForFunction(() => !state.loading)
      await expect(page.locator(".scene-workbench-row")).toHaveCount(0)

      await page.locator(".sidebar-project-switcher").click()
      await page.locator(SEL.projectCard(project.id)).click()
      await expect(page.locator(SEL.topbarProject)).toHaveText("Scene 移动端")
      await page.waitForFunction(() => !state.loading)
      await page.evaluate(() => window.router.navigate("outline", "scenes"))
      await page.waitForFunction(() => !state.loading)
      await page.locator(`.scene-workbench-row[data-id="${scene.id}"] [data-action="select-workbench-scene"]`).click()
      await expect(page.locator("#scene-detail-core_conflict")).toHaveValue("必须避开巡逻守卫")
      expect(browserErrors.filter((error) => !error.text?.includes("409 (Conflict)"))).toEqual([])
    } finally {
      await cleanupProject(otherProject.id)
    }
  })

  test("390px 窄屏长列表可以滚动到分页并翻页", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const project = await createProject({ title: "Scene 窄屏长列表", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    await Promise.all(Array.from({ length: 21 }, (_, index) => createScene(project.id, {
      scene_index: index,
      title: `窄屏 Scene ${index + 1}`,
      goal: `目标 ${index + 1}`,
      core_conflict: `冲突 ${index + 1}`,
      chapter_ids: [String(index + 1)],
    })))

    await openWorkbench(page, project, "outline", "scenes")

    const scroller = page.locator(".scene-workbench")
    const geometry = await scroller.evaluate((element) => ({
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
      overflowY: getComputedStyle(element).overflowY,
    }))
    expect(geometry.scrollHeight).toBeGreaterThan(geometry.clientHeight)
    expect(geometry.overflowY).toBe("auto")

    await scroller.evaluate((element) => { element.scrollTop = element.scrollHeight })
    await expectWithinViewport(page.locator(".scene-workbench-pagination"))
    await page.locator('[data-action="next-scene-page"]').click()
    await expect(page.locator(".scene-workbench-pagination")).toContainText("第 2 / 2 页")
    await expectNoPageOverflow(page)
  })

  test("右侧 Scene 详情栏内容溢出时可滚动", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 620 })
    const project = await createProject({ title: "Scene 详情栏滚动", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const longText = "需要滚动才能查看的示例内容。".repeat(80)
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "长内容 Scene",
      goal: longText,
      core_conflict: longText,
      must_happen: longText,
      must_not_happen: longText,
      chapter_ids: ["1"],
    })

    await openWorkbench(page, project, "scene", scene.id)

    const body = page.locator(".scene-detail-rail > .workspace-rail__body")
    await expect(body).toBeVisible()
    const canScroll = await body.evaluate((el) => el.scrollHeight > el.clientHeight + 2)
    expect(canScroll).toBe(true)

    const saveButton = page.locator('.scene-detail-rail [data-action="save-scene-detail"]')
    await body.evaluate((el) => { el.scrollTop = el.scrollHeight })
    await expect(saveButton).toBeInViewport()

    const scrollState = await body.evaluate((el) => ({
      scrollTop: el.scrollTop,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    }))
    expect(scrollState.scrollTop).toBeGreaterThan(50)
    expect(scrollState.scrollTop + scrollState.clientHeight).toBeGreaterThan(scrollState.scrollHeight - 10)
  })
})
