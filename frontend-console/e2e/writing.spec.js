import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { expectNoPageOverflow, expectWithinViewport } from "./helpers/responsive.js"
import { reloadWorkbench, waitWritingReady } from "./helpers/workbench.js"
import {
  API_BASE,
  waitForBackend,
  createAutosavedDraft, createDraft, createScene, deleteDraft, getLatestDraft,
} from "./helpers/api-client.js"

async function confirmPublishIfPrompted(page) {
  const continueButton = page.locator("#modal-footer").getByRole("button", { name: "继续设为正式正文" })
  try {
    await expect(continueButton).toBeVisible({ timeout: 3000 })
    await continueButton.click()
  } catch {}
}

async function waitForPublishFeedback(page) {
  const feedback = page.locator("#writing-publish-bar-container")
  await expect(feedback).toBeVisible({ timeout: 15000 })
  await expect(feedback).toContainText(/(正在整理相关资料|已设为正式正文|正式正文已就绪|正文无实质变化)/)
  await expect(page.locator(SEL.toastContainer)).not.toContainText("已设为正式正文")
  return feedback
}

function writingChapter(page, chapter) {
  return page.getByRole("button", { name: new RegExp(`^打开第 ${Number(chapter)} 章`) })
}

async function selectWritingChapter(page, chapter) {
  const rail = page.locator(".writing-tree-rail")
  if (await rail.count() && await rail.evaluate((element) => element.classList.contains("is-collapsed"))) {
    await page.getByLabel("展开章节").click()
  }
  await writingChapter(page, chapter).click()
}

async function createFirstChapter(page) {
  await page.getByRole("button", { name: "新建章节", exact: true }).click()
  await waitWritingReady(page, { editor: true })
}

async function openWritingToolMenu(page, selector) {
  const tool = page.locator(selector)
  const menu = page.locator("details.writing-tools-menu").filter({ has: tool })
  if (await menu.getAttribute("open") === null) {
    await menu.locator(":scope > summary").click()
  }
}

async function clickWritingTool(page, selector) {
  await openWritingToolMenu(page, selector)
  await page.locator(selector).click()
}

test.describe("写作台模块", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page, projectFactory, openProjectWorkbench }) => {
    const project = await projectFactory({
      title: "写作测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openProjectWorkbench(project, "writing")
    await waitWritingReady(page)
  })

  // ============================================================
  // 基础功能
  // ============================================================

  test("空状态显示新建章节按钮", async ({ page }) => {
    const emptyTree = page.locator("#writing-tree-container .empty-state")
    await expect(emptyTree).toBeVisible()
    await expect(emptyTree).toContainText("尚无章节")
    await expect(page.getByRole("button", { name: "新建章节" })).toHaveCount(1)
  })

  test("新建章节并显示在章节树", async ({ page }) => {
    await createFirstChapter(page)

    await expect(page.locator("#workspace-content")).toContainText("第 1 章")
    await expect(page.locator("#writing-editor")).toBeVisible()
  })

  test("编辑章节内容并暂存", async ({ page }) => {
    await createFirstChapter(page)

    await page.locator("#writing-editor").fill("初始发布内容。")
    await page.locator("#btn-publish").click()
    await confirmPublishIfPrompted(page)
    await waitForPublishFeedback(page)

    await page.locator("#writing-title-input").fill("第一章 测试")
    await page.locator("#writing-editor").fill("这是测试内容。")

    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#writing-save-status")).toHaveText("已保存到工作稿", { timeout: 10000 })
  })

  test("AI 写作建议按当前正文给出主操作，任务可收起并回到审阅", async ({ page, browserErrors, projectFactory, openProjectWorkbench }) => {
    const failedApiResponses = []
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) {
        failedApiResponses.push(`${response.status()} ${response.request().method()} ${response.url()}`)
      }
    })
    const baseCreated = await createDraft(testProjectId, 1, "第一章 雾港来信", "潮声退到石阶之外，石门仍旧紧闭。")
    const base = baseCreated.draft || baseCreated
    await createScene(testProjectId, {
      scene_index: 0,
      title: "退潮后的石门",
      narrative_tag: "opening",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 18 }],
      goal: "判断是否公开石门",
      core_conflict: "保护同行者，还是抢先留下证据",
    })
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    const originalProject = await page.evaluate(() => ({ ...state.currentProject }))

    let finishGeneration
    let generationPayload = null
    await page.route("**/api/context/confirm", async (route) => {
      const body = route.request().postDataJSON()
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "00000000-0000-0000-0000-0000000000b1",
          novel_id: body.novel_id,
          action: body.action,
          task: body.task,
          scope: body.scope,
          reveal_mode: body.reveal_mode,
          context_mode: body.context_mode,
          selected_asset_ids: {},
          sections: [],
          warnings: [],
        }),
      })
    })
    await page.route("**/api/writing/generate", async (route) => {
      generationPayload = route.request().postDataJSON()
      await new Promise((resolve) => { finishGeneration = resolve })
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ draft_id: "candidate-owner-ai" }),
      })
    })
    await page.route("**/api/writing/drafts/candidate-owner-ai?**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "candidate-owner-ai",
          novel_id: testProjectId,
          chapter_index: 1,
          title: "第一章 雾港来信",
          content: "潮声退到石阶之外，石门仍旧紧闭。守港人举起灯，示意林舟不要回头。",
          version_number: 2,
          status: "candidate",
          provenance_json: { source: "writing_generate", review_required: false },
          updated_at: "2026-08-23T12:00:00Z",
        }),
      })
    })

    const openAi = page.locator('[data-action="open-owner-ai-drawer"]')
    await openAi.click()
    const drawer = page.locator("[data-owner-ai-drawer]")
    await expect(drawer.locator(".owner-ai-writing__context")).toContainText("第 1 章 · 第一章 雾港来信")
    await expect(drawer.locator('[data-action="owner-writing-continuation"]')).toHaveClass(/btn-primary/)
    await expect(drawer.locator(".owner-ai-writing__more")).not.toHaveAttribute("open", "")
    await drawer.locator(".owner-ai-writing__more > summary").click()
    await expect(drawer.locator('[data-action="owner-writing-pov"]')).toBeDisabled()
    await expect(drawer.locator(".owner-ai-writing__more")).toContainText("当前场景还没有设置视角人物")

    await page.reload({ waitUntil: "domcontentloaded" })
    await page.waitForFunction(() => !state.loading)
    await expect(drawer).toBeVisible()
    await expect(drawer.locator('[data-action="owner-writing-continuation"]')).toBeVisible()
    await page.evaluate(() => window.router.navigate("outline"))
    await expect(page.locator("#topbar-module")).toContainText("故事结构")
    await page.goBack()
    await expect(drawer).toBeVisible()
    await expect(drawer.locator(".owner-ai-writing__context")).toContainText("第一章 雾港来信")

    const otherProject = await projectFactory({ title: "写作建议隔离对照作品", genre: "mystery", language: "zh" })
    await openProjectWorkbench(otherProject, "writing")
    await waitWritingReady(page)
    await page.locator('[data-action="open-owner-ai-drawer"]').click()
    await expect(page.locator(".owner-ai-writing__context")).toContainText("还没有选择章节")
    await expect(page.locator('[data-action="owner-writing-draft"]')).toBeDisabled()
    await page.locator('[data-action="close-owner-ai-drawer"]').click()

    await openProjectWorkbench(originalProject, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    await page.locator('[data-action="open-owner-ai-drawer"]').click()
    await page.setViewportSize({ width: 375, height: 812 })
    await expectWithinViewport(page.locator('[data-action="owner-writing-continuation"]'))
    await expectNoPageOverflow(page)
    await page.setViewportSize({ width: 812, height: 375 })
    await expectWithinViewport(page.locator('[data-action="owner-writing-continuation"]'))
    await expectNoPageOverflow(page)
    await page.setViewportSize({ width: 375, height: 812 })

    await page.locator('[data-action="owner-writing-continuation"]').click()
    await expect(page.locator("#modal-overlay")).toContainText("AI 参考资料")
    await page.keyboard.press("Escape")
    await expect(page.locator("#modal-overlay")).toBeHidden()
    await expect(drawer).toBeVisible()
    await expect(page.locator('[data-action="owner-writing-continuation"]')).toBeEnabled()

    await page.locator('[data-action="owner-writing-continuation"]').click()
    await expect(page.locator("#modal-overlay")).toContainText("AI 参考资料")
    await page.locator("#modal-footer").getByRole("button", { name: "确认使用" }).click()
    await expect(page.locator(".owner-ai-writing__progress")).toContainText("可以收起 AI 工具继续写作")
    await page.locator('[data-action="owner-writing-show-progress"]').click()
    await expect(drawer).toHaveCount(0)
    await expect(page.locator("#writing-generation-bar-container")).toBeVisible()
    await expect.poll(() => typeof finishGeneration).toBe("function")
    finishGeneration()

    const review = page.locator(".writing-candidate-review-panel")
    await expect(review).toBeVisible({ timeout: 10000 })
    await expect(review).toBeFocused()
    await expect(review).toContainText("这份建议还没有改动工作稿")
    await expect(page).not.toHaveURL(/(?:\?|&)owner_ai=1/)
    expect(generationPayload).toMatchObject({
      novel_id: testProjectId,
      chapter_index: 1,
      generation_mode: "continue",
      base_draft_id: base.id,
    })
    expect(browserErrors).toEqual([])
    expect(failedApiResponses, `失败 API: ${JSON.stringify(failedApiResponses)}`).toEqual([])
  })

  test("发布章节", async ({ page }) => {
    await page.setViewportSize({ width: 1224, height: 768 })
    await createFirstChapter(page)
    const frozenAt = new Date("2026-08-13T08:00:00Z")
    await page.clock.install({ time: frozenAt })
    await page.clock.pauseAt(frozenAt)
    await page.route("**/api/writing/drafts", async (route) => {
      if (route.request().method() !== "POST") return route.fallback()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ new_version: true }),
      })
    })

    await page.locator("#writing-title-input").fill("第一章 发布测试")
    await page.locator("#writing-editor").fill("这是发布测试的内容。")
    await expect(page.locator(".writing-statusbar")).toHaveCSS("position", "sticky")
    await page.locator("#btn-publish").click()
    await confirmPublishIfPrompted(page)
    const publishFeedback = await waitForPublishFeedback(page)

    for (const width of [1224, 1100, 900, 761]) {
      await page.setViewportSize({ width, height: 768 })
      const geometry = await page.evaluate(() => {
        const publishBar = document.querySelector("#writing-publish-bar-container")
        const statusbar = document.querySelector(".writing-statusbar")
        const topbar = document.querySelector("#topbar")
        const workspace = document.querySelector("#workspace")
        if (!publishBar || !statusbar || !topbar || !workspace) return null
        return {
          position: getComputedStyle(publishBar.closest(".writing-workflow-notices")).position,
          publishTop: publishBar.getBoundingClientRect().top,
          topbarBottom: topbar.getBoundingClientRect().bottom,
          publishCenter: publishBar.getBoundingClientRect().left + publishBar.getBoundingClientRect().width / 2,
          workspaceCenter: workspace.getBoundingClientRect().left + workspace.getBoundingClientRect().width / 2,
          statusPosition: getComputedStyle(statusbar).position,
          overflows: document.documentElement.scrollWidth > innerWidth,
        }
      })
      expect(geometry).not.toBeNull()
      expect(geometry.position).toBe("fixed")
      expect(geometry.publishTop).toBeGreaterThanOrEqual(geometry.topbarBottom)
      expect(Math.abs(geometry.publishCenter - geometry.workspaceCenter)).toBeLessThan(2)
      expect(geometry.statusPosition).toBe("sticky")
      expect(geometry.overflows).toBe(false)
    }
    await page.clock.runFor(2999)
    await expect(publishFeedback).toBeVisible()
    await page.clock.runFor(1)
    await expect(publishFeedback).toBeHidden()
  })

  // ============================================================
  // Scene 切换不丢失内容
  // ============================================================

  test("Scene 切换不丢失内容", async ({ page }) => {
    // 创建后端草稿
    const d1 = await createDraft(testProjectId, 1, "第一章", "第一章的正文内容ABC")
    const d2 = await createDraft(testProjectId, 2, "第二章", "第二章的正文内容XYZ")

    const d1Content = d1.draft.content
    const d2Content = d2.draft.content
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)

    await expect(page.locator("#writing-editor")).toHaveValue(d1Content, { timeout: 5000 })

    // 切换到第 2 章
    await selectWritingChapter(page, 2)
    await expect(page.locator("#writing-editor")).toHaveValue(d2Content, { timeout: 5000 })

    // 编辑第 2 章后切换回第 1 章
    await page.locator("#writing-editor").fill("修改后的第二章内容")
    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#writing-save-status")).toHaveText("已保存到工作稿", { timeout: 10000 })

    // 恢复第 1 章内容
    await selectWritingChapter(page, 1)
    await expect(page.locator("#writing-editor")).toHaveValue(d1Content, { timeout: 5000 })
  })

  test("保存与切章失败时保留正文并可在桌面和手机重试", async ({ page, browserErrors }) => {
    const expectExpectedFailure = () => {
      expect(browserErrors.filter((item) => item.kind === "pageerror")).toEqual([])
      const responses = browserErrors.filter((item) => item.kind === "response" && item.status === 503)
      const consoleErrors = browserErrors.filter((item) => item.kind === "console")
      expect(responses.length).toBeGreaterThan(0)
      expect(consoleErrors).toHaveLength(responses.length)
      expect(consoleErrors.every((item) => item.text.includes("503"))).toBe(true)
      expect(browserErrors).toHaveLength(responses.length + consoleErrors.length)
      browserErrors.length = 0
    }
    const d1 = await createDraft(testProjectId, 1, "第一章", "第一章原文")
    const d2 = await createDraft(testProjectId, 2, "第二章", "第二章原文")
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    await expect(page.locator("#writing-editor")).toHaveValue("第一章原文")

    let failSave = true
    await page.route(`**/api/writing/drafts/${d1.draft.id}*`, async (route) => {
      if (route.request().method() !== "PUT" || !failSave) return route.continue()
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "暂时无法保存" }) })
    })
    await page.locator("#writing-editor").fill("第一章未保存正文")
    await selectWritingChapter(page, 2)

    await expect(page.locator("#writing-retry-save")).toBeVisible()
    await expect(page.locator("#writing-editor")).toHaveValue("第一章未保存正文")
    await expect(page.locator("#writing-save-status")).toHaveClass(/writing-save-badge--error/)
    expectExpectedFailure()

    failSave = false
    await page.locator("#writing-retry-save").click()
    await expect(page.locator("#writing-retry-save")).toBeHidden()
    await expect(page.locator("#writing-save-status")).toHaveText("已保存到工作稿")

    let failLoad = true
    await page.route(`**/api/writing/drafts/${d2.draft.id}*`, async (route) => {
      if (route.request().method() !== "GET" || !failLoad) return route.continue()
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "章节暂时无法加载" }) })
    })
    await selectWritingChapter(page, 2)
    await expect(page.locator("#writing-retry-load")).toBeVisible()
    await expect(page.locator("#writing-editor")).toHaveCount(0)
    await expect(page.locator("#writing-editor-container")).toContainText("上一章的内容仍安全保留")
    expectExpectedFailure()

    failLoad = false
    await page.locator("#writing-retry-load").click()
    await expect(page.locator("#writing-editor")).toHaveValue("第二章原文")

    await page.setViewportSize({ width: 390, height: 844 })
    await expect(page.locator("#mobile-note-editor")).toHaveValue("第二章原文")
    let failMobileSave = true
    await page.route(`**/api/writing/drafts/${d2.draft.id}*`, async (route) => {
      if (route.request().method() !== "PUT" || !failMobileSave) return route.continue()
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "移动网络不可用" }) })
    })
    await page.locator("#mobile-note-editor").fill("手机端未保存正文")
    await page.getByRole("button", { name: "保存工作稿", exact: true }).click()
    const mobileRecovery = page.locator(".mobile-quick-note .writing-save-recovery")
    await expect(mobileRecovery).toBeVisible()
    await expect(mobileRecovery.getByRole("button", { name: "重试保存" })).toBeInViewport()
    expectExpectedFailure()

    failMobileSave = false
    await mobileRecovery.getByRole("button", { name: "重试保存" }).click()
    await expect(mobileRecovery).toBeHidden()
    await expect(page.locator(".mobile-note-status")).toHaveText("已保存到工作稿")
    expect(browserErrors).toEqual([])
  })

  test("AI 建议在刷新和返回后仍先决策，采用前可取消确认", async ({ page, browserErrors, projectFactory }) => {
    const baseCreated = await createDraft(testProjectId, 1, "第一章 雾港来信", "潮声退到石阶之外，石门仍旧紧闭。")
    const base = baseCreated.draft || baseCreated
    const created = await createDraft(testProjectId, 1, "第一章 雾港来信", "潮声退到石阶之外，露出一道从未被记载的门。")
    const candidate = created.draft || created
    const otherProject = await projectFactory({ title: "候选隔离对照作品", genre: "mystery", language: "zh" })
    const adopted = {
      ...candidate,
      id: "adopted-candidate",
      status: "draft",
      version_number: Number(candidate.version_number || 1) + 1,
      provenance_json: { source: "ai_generated", adopted_from_candidate_id: candidate.id },
    }
    await page.route(`**/api/writing/drafts/${candidate.id}/adopt*`, async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(adopted) })
    })
    await page.route(`**/api/writing/drafts/${candidate.id}*`, async (route) => {
      if (route.request().method() !== "GET") return route.continue()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...candidate,
          status: "candidate",
          provenance_json: { source: "writing_generate", review_required: false },
        }),
      })
    })
    await page.route("**/api/writing/chapters/1/versions*", async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      await route.fulfill({
        response,
        json: {
          ...body,
          versions: (body.versions || []).map((version) => version.id === candidate.id
            ? { ...version, status: "candidate", display_state: "candidate" }
            : version.id === base.id ? { ...version, display_state: "active" } : version),
        },
      })
    })
    await page.route("**/api/writing/drafts/adopted-candidate*", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(adopted) })
    })

    await reloadWorkbench(page, "writing")
    await page.evaluate(({ draftId }) => {
      const query = new URLSearchParams({ chapter_index: "1", draft_id: draftId })
      return window.router.navigate("writing", null, true, query)
    }, { draftId: candidate.id })
    await waitWritingReady(page, { chapter: 1 })
    const panel = page.locator(".writing-candidate-review-panel")
    const adoptButton = panel.getByRole("button", { name: "采用到工作稿" })
    await expect(panel).toBeVisible()
    await expect(panel).toBeInViewport()
    await expect(panel).toBeFocused()
    await expect(page.locator(".writing-candidate-review-actions .btn-primary")).toHaveCount(1)
    await expect(page.locator("#btn-publish")).toHaveCount(0)
    await expect(page.locator("#writing-editor")).toHaveAttribute("readonly", "")

    const compareButton = panel.getByRole("button", { name: "与当前工作稿比较" })
    await compareButton.click()
    const comparison = page.getByRole("dialog", { name: "版本历史" })
    await expect(comparison.locator(".writing-version-diff")).toBeFocused()
    await expect(comparison).toContainText("石门仍旧紧闭")
    await expect(comparison).toContainText("从未被记载的门")
    await page.keyboard.press("Escape")
    await expect(comparison).toBeHidden()
    await expect(compareButton).toBeFocused()

    await page.reload()
    await expect(panel).toBeVisible({ timeout: 10000 })
    await expect(panel).toBeFocused()
    await page.evaluate(() => window.router.navigate("project-settings"))
    await expect(page).toHaveURL(/project-settings/)
    await page.goBack()
    await expect(panel).toBeVisible({ timeout: 10000 })
    await expect(panel).toBeFocused()
    await page.goForward()
    await expect(page).toHaveURL(/project-settings/)
    await page.goBack()
    await expect(panel).toBeVisible({ timeout: 10000 })
    await expect(panel).toBeFocused()

    await page.locator(".sidebar-project-switcher").click()
    await page.locator(SEL.projectCard(otherProject.id)).click()
    await expect(page.locator(SEL.topbarProject)).toHaveText("候选隔离对照作品")
    await expect(panel).toHaveCount(0)
    await page.locator(".sidebar-project-switcher").click()
    await page.locator(SEL.projectCard(testProjectId)).click()
    await page.evaluate(() => window.router.navigate("writing"))
    await expect(panel).toBeVisible({ timeout: 10000 })
    await expect(panel).toBeFocused()

    await adoptButton.click()
    const confirmation = page.locator("#modal-overlay")
    const confirmButton = page.locator("#modal-footer").getByRole("button", { name: "采用到工作稿" })
    await expect(confirmation).toBeVisible()
    await expect(confirmButton).toBeFocused()
    await page.keyboard.press("Escape")
    await expect(confirmation).toBeHidden()
    await expect(adoptButton).toBeFocused()
    await expect(panel).toBeVisible()

    await adoptButton.click()
    await confirmButton.click()
    await expect(panel).toHaveCount(0)
    await expect(page.locator("#writing-editor")).not.toHaveAttribute("readonly", "")
    await expect(page.locator("#writing-editor")).toBeFocused()
    await expect(page.locator("#btn-publish")).toBeVisible()
    expect(browserErrors).toEqual([])
  })

  // ============================================================
  // 版本历史查看与恢复
  // ============================================================

  test("版本历史查看与恢复", async ({ page, browserErrors, projectFactory }) => {
    const failedApiResponses = []
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) {
        failedApiResponses.push(`${response.status()} ${response.request().method()} ${response.url()}`)
      }
    })
    // 创建 v1 和 v2
    await createDraft(testProjectId, 1, "第一版", "版本一的正文内容")
    const v2 = await createDraft(testProjectId, 1, "第二版", "版本二的正文内容")

    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    await expect(page.locator("#writing-editor")).toHaveValue(v2.draft.content)

    // 打开版本历史弹窗
    await page.getByRole("button", { name: "版本历史", exact: true }).click()
    const versionDialog = page.getByRole("dialog", { name: "版本历史" })
    await expect(versionDialog).toBeVisible({ timeout: 5000 })
    await expect(versionDialog).toContainText("v2")
    await expect(versionDialog).toContainText("v1")
    await expect(versionDialog.locator(".writing-version-history-item", { hasText: "v2" }).getByRole("button", { name: "移入历史" })).toHaveCount(0)
    const writingOverlay = versionDialog.locator("xpath=..")
    const initialV1Row = versionDialog.locator(".writing-version-history-item", { hasText: "v1" })

    // 旧版本可一步与当前打开版本比较，不必先理解 A/B 选择器。
    await initialV1Row.getByRole("button", { name: "与当前打开版本比较" }).click()
    await expect(versionDialog.locator(".writing-version-diff")).toBeFocused()
    await expect(versionDialog.locator(".writing-version-diff")).toContainText("版本一的正文内容")
    await expect(versionDialog.locator(".writing-version-diff")).toContainText("版本二的正文内容")

    // 单独预览保留在低频操作菜单中。
    await initialV1Row.getByRole("button", { name: "版本 v1 的更多操作" }).click()
    await initialV1Row.getByRole("menuitem", { name: "单独预览" }).click()
    await expect(page.locator("#writing-editor")).toHaveValue("版本一的正文内容", { timeout: 5000 })
    await expect(versionDialog).toBeHidden()
    await expect(page.locator("#writing-editor")).toBeFocused()
    // v1 非最新版本 → 只读预览后可明确选择“从此版本继续写”
    await page.getByRole("button", { name: "版本历史", exact: true }).click()
    const reopenedVersionDialog = page.getByRole("dialog", { name: "版本历史" })
    const v1Row = reopenedVersionDialog.locator(".writing-version-history-item", { hasText: "v1" })
    await expect(v1Row.getByRole("button", { name: "从此版本继续写" })).toBeVisible()

    // 点击“从此版本继续写”
    await v1Row.getByRole("button", { name: "从此版本继续写" }).click()
    const globalConfirmation = page.locator("#modal-overlay")
    await expect(globalConfirmation).toBeVisible()
    await expect(writingOverlay).toHaveAttribute("inert", "")
    await expect(globalConfirmation).not.toHaveAttribute("inert")
    await expect(page.locator("#modal-content")).toContainText("恢复至 v1")
    await expect(page.locator("#modal-footer").getByRole("button", { name: "确认恢复" })).toBeFocused()
    await page.locator("#modal-footer").getByRole("button", { name: "取消" }).click()
    await expect(globalConfirmation).toBeHidden()
    await expect(versionDialog).toBeVisible()
    await expect(v1Row.getByRole("button", { name: "从此版本继续写" })).toBeFocused()

    await v1Row.getByRole("button", { name: "从此版本继续写" }).click()
    await page.locator("#modal-footer").getByRole("button", { name: "确认恢复" }).click()
    await expect(page.locator("#btn-autosave")).toHaveText("保存为新工作稿")

    // 编辑后保存 — 由于 restore 模式，autosave 走发布流程
    await page.locator("#writing-editor").fill("基于 v1 的新内容")
    await clickWritingTool(page, "#btn-autosave")
    await confirmPublishIfPrompted(page)
    await waitForPublishFeedback(page)

    // 旧版本只移入历史，不删除正文记录。
    await page.getByRole("button", { name: "版本历史", exact: true }).click()
    const oldVersionRow = page.getByRole("dialog", { name: "版本历史" })
      .locator(".writing-version-history-item", { hasText: "v1" })
    await oldVersionRow.getByRole("button", { name: "版本 v1 的更多操作" }).click()
    await oldVersionRow.getByRole("menuitem", { name: "移入历史" }).click()
    await expect(page.locator("#modal-content")).toContainText("正文不会丢失")
    await page.locator("#modal-footer").getByRole("button", { name: "移入历史" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("v1 已移入历史")
    await expect(oldVersionRow).toContainText("历史")
    await oldVersionRow.getByRole("button", { name: "版本 v1 的更多操作" }).click()
    await expect(oldVersionRow.getByRole("menuitem", { name: "移入历史" })).toHaveCount(0)
    await expect(globalConfirmation).toBeHidden()
    await expect(versionDialog.locator(":focus")).toHaveCount(1)

    await page.keyboard.press("Escape")
    await expect(oldVersionRow.getByRole("button", { name: "版本 v1 的更多操作" })).toBeFocused()
    await page.keyboard.press("Escape")
    await expect(page.getByRole("dialog", { name: "版本历史" })).toBeHidden()
    await expect(page.getByRole("button", { name: "版本历史", exact: true })).toBeFocused()
    await page.getByRole("button", { name: "版本历史", exact: true }).click()
    await page.reload()
    await waitWritingReady(page, { chapter: 1 })
    await expect(page.getByRole("dialog", { name: "版本历史" })).toHaveCount(0)
    await page.evaluate(() => window.router.navigate("project-settings"))
    await page.goBack()
    await expect(page.getByRole("button", { name: "版本历史", exact: true })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole("dialog", { name: "版本历史" })).toHaveCount(0)

    const otherProject = await projectFactory({ title: "版本历史隔离作品", genre: "mystery", language: "zh" })
    await createDraft(otherProject.id, 1, "另一部作品", "独立的版本正文")
    await page.locator(".sidebar-project-switcher").click()
    await page.locator(SEL.projectCard(otherProject.id)).click()
    await page.evaluate(() => window.router.navigate("writing"))
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    await expect(page.locator("#writing-editor")).toHaveValue("独立的版本正文")
    await expect(page.getByRole("dialog", { name: "版本历史" })).toHaveCount(0)
    expect(browserErrors).toEqual([])
    expect(failedApiResponses).toEqual([])
  })

  test("实质变化留版、强制 checkpoint 和发布前撤销", async ({ page }) => {
    const v1 = await createDraft(testProjectId, 1, "第一章", "甲\n乙")
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    await expect(page.locator("#writing-editor")).toHaveValue("甲\n乙")

    // 纯空白修改只留本地，用户可显式强制留版。
    await page.locator("#writing-editor").fill(" 　甲\t\n\n乙 ")
    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#writing-save-status")).toHaveText("排版修改已保留在本地")
    await clickWritingTool(page, "#btn-checkpoint-version")
    await expect(page.locator("#modal-overlay")).toContainText("正文没有实质变化")
    await page.locator("#modal-footer").getByRole("button", { name: "保存新版本" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存为新版本")
    await expect(page.locator("#version-selector")).toContainText("v2")

    // 手动版本需显式确认放弃，回到 v1。
    await openWritingToolMenu(page, "#btn-autosave")
    await page.getByRole("button", { name: "放弃未设为正式正文的更改" }).click()
    await page.locator("#modal-footer").getByRole("button", { name: "放弃更改" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已回到上一版")
    await expect(page.locator("#writing-editor")).toHaveValue(v1.draft.content)

    // 实质修改自动创建工作版，撤销回基线时自动回到 v1。
    await page.locator("#writing-editor").fill("甲乙丙")
    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#writing-save-status")).toHaveText("已保存到工作稿")
    await page.locator("#writing-editor").fill("甲\n乙")
    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#version-selector option").first()).toContainText("v1")

    // 再次修改后发布，当前工作版原位提升，不多加一版。
    await page.locator("#writing-editor").fill("甲乙丁")
    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#version-selector option").first()).not.toContainText("v1")
    const workingVersion = await page.locator("#version-selector option").first().getAttribute("data-version")
    await page.locator("#btn-publish").click()
    await confirmPublishIfPrompted(page)
    await waitForPublishFeedback(page)

    const history = await page.evaluate(async ({ apiBase, projectId }) => {
      const response = await fetch(`${apiBase}/writing/chapters/1/versions?novel_id=${projectId}`)
      return response.json()
    }, { apiBase: API_BASE, projectId: testProjectId })
    expect(String(history.versions[0].version_number)).toBe(workingVersion)
    expect(history.versions[0].status).toBe("published")
  })

  test("自动保存响应不会覆盖请求期间的新输入", async ({ page }) => {
    await createDraft(testProjectId, 1, "第一章", "原文")
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)

    let autosaveRequests = 0
    let releaseFirstAutosave
    const firstAutosaveGate = new Promise((resolve) => { releaseFirstAutosave = resolve })
    await page.route("**/api/writing/drafts/**", async (route) => {
      if (route.request().method() !== "PUT") {
        await route.continue()
        return
      }
      autosaveRequests += 1
      if (autosaveRequests === 1) {
        await firstAutosaveGate
      }
      await route.continue()
    })

    await page.locator("#writing-editor").fill("第一次修改")
    await clickWritingTool(page, "#btn-autosave")
    await expect.poll(() => autosaveRequests).toBe(1)
    await page.locator("#writing-editor").fill("第二次修改")
    releaseFirstAutosave()
    await expect(page.locator("#btn-autosave")).toBeEnabled({ timeout: 15000 })
    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#writing-save-status")).toHaveText("已保存到工作稿", { timeout: 15000 })

    await expect(page.locator("#writing-editor")).toHaveValue("第二次修改")
    await expect.poll(async () => {
      const historyResponse = await page.request.get(
        `${API_BASE}/writing/chapters/1/versions?novel_id=${testProjectId}`,
      )
      const history = await historyResponse.json()
      const latestId = history.versions?.[0]?.id
      if (!latestId) return null
      const draftResponse = await page.request.get(
        `${API_BASE}/writing/drafts/${latestId}?novel_id=${testProjectId}`,
      )
      return (await draftResponse.json()).content
    }).toBe("第二次修改")
    await page.unrouteAll({ behavior: "wait" })
  })

  test("auto 回退到手动基线时原位发布手动版本", async ({ page }) => {
    await createDraft(testProjectId, 1, "第一章", "v1")
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    await page.locator("#writing-editor").fill("v2")
    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#version-selector option").first()).toContainText("v2")
    await expect(page.locator("#writing-save-status")).toHaveText("已保存到工作稿")
    await clickWritingTool(page, "#btn-checkpoint-version")
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存为新版本")
    const manualVersion = await page.locator("#version-selector option").first().getAttribute("data-version")

    await page.locator("#writing-editor").fill("v3")
    await clickWritingTool(page, "#btn-autosave")
    await expect(page.locator("#version-selector option").first()).toContainText(
      `v${Number(manualVersion) + 1}`,
    )
    await expect(page.locator("#writing-save-status")).toHaveText("已保存到工作稿")
    await page.locator("#writing-editor").fill("v2")
    await page.locator("#btn-publish").click()
    await confirmPublishIfPrompted(page)
    await waitForPublishFeedback(page)

    const history = await page.evaluate(async ({ apiBase, projectId }) => {
      const response = await fetch(`${apiBase}/writing/chapters/1/versions?novel_id=${projectId}`)
      return response.json()
    }, { apiBase: API_BASE, projectId: testProjectId })
    const latestActive = history.versions.find((item) => item.display_state === "active")
    expect(String(latestActive.version_number)).toBe(manualVersion)
    expect(latestActive.status).toBe("published")
    const discardedAuto = history.versions.find(
      (item) => item.version_number === Number(manualVersion) + 1,
    )
    expect(discardedAuto).toMatchObject({
      display_state: "archived",
      status: "deprecated",
    })
  })

  test("历史恢复在最新版本变化后返回并发冲突", async ({ page }) => {
    await createDraft(testProjectId, 1, "第一章", "v1")
    await createDraft(testProjectId, 1, "第一章", "v2")
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    await page.getByRole("button", { name: "版本历史", exact: true }).click()
    await page.locator(".writing-version-history-item", { hasText: "v1" })
      .getByRole("button", { name: "从此版本继续写" }).click()
    await page.locator("#modal-footer").getByRole("button", { name: "确认恢复" }).click()
    await expect(page.locator("#writing-editor")).toHaveValue("v1")

    const newest = await createDraft(testProjectId, 1, "第一章", "v3")
    await page.locator("#writing-editor").fill("基于 v1 恢复")
    await page.locator("#btn-publish").click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator(SEL.toastContainer)).toContainText("其他会话更新")

    const history = await page.evaluate(async ({ apiBase, projectId }) => {
      const response = await fetch(`${apiBase}/writing/chapters/1/versions?novel_id=${projectId}`)
      return response.json()
    }, { apiBase: API_BASE, projectId: testProjectId })
    expect(history.versions[0].id).toBe(newest.draft.id)
  })

  // ============================================================
  // 手选 Scene 驱动右侧副驾驶
  // ============================================================

  test("手选 Scene 切换右侧上下文，光标移动不会改选择", async ({ page }) => {
    // 创建一个 10 字符的章节，并用 scene_chunks 分成两个 Scene
    await createDraft(testProjectId, 1, "ch1", "ABCDEFGHIJ")
    await createScene(testProjectId, {
      scene_index: 0,
      title: "Scene A",
      narrative_tag: "draft",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 5 }],
    })
    await createScene(testProjectId, {
      scene_index: 1,
      title: "Scene B",
      narrative_tag: "draft",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 5, end_pos: 10 }],
    })

    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)

    await page.getByRole("button", { name: /^打开第 1 章/ }).click()
    await expect(page.locator("#writing-editor")).toHaveValue("ABCDEFGHIJ", { timeout: 5000 })

    await page.locator(".scene-cockpit-switcher__item", { hasText: "Scene B" }).click()
    await expect(page.locator(".scene-cockpit-switcher__item.active")).toContainText("Scene B")
    await expect(page.locator("#writing-panel-container")).toContainText("Scene B")

    await page.evaluate(() => {
      const editor = document.getElementById("writing-editor")
      editor.setSelectionRange(2, 2)
      document.dispatchEvent(new Event("selectionchange"))
    })
    await expect(page.locator(".scene-cockpit-switcher__item.active")).toContainText("Scene B")
    await expect(page.locator("#writing-panel-container")).toContainText("Scene B")
  })

  test("写作副驾驶默认展示 Scene 执行信息且不被工作区裁切", async ({ page }) => {
    await createDraft(testProjectId, 1, "第一章 东门交锋", "东门交锋正文")
    await createScene(testProjectId, {
      scene_index: 0,
      title: "东门交锋",
      narrative_tag: "draft",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 8 }],
      goal: "拿到令牌后安全离开",
      must_happen: "主角与守卫正面对质",
      must_not_happen: "主角身份提前暴露",
      core_conflict: "通行时限与身份隐藏之间的冲突",
      emotional_beat: "从紧张试探到果断突围",
    })

    await page.setViewportSize({ width: 1280, height: 768 })
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    await page.getByRole("button", { name: /^打开第 1 章/ }).click()

    await expect(page.getByRole("tab", { name: "本场" })).toHaveClass(/active/)
    await expect(page.locator('.cockpit-panel[data-panel="lore"]')).toContainText("拿到令牌后安全离开")

    const geometry = await page.evaluate(() => {
      const cockpit = document.querySelector(".scene-cockpit")
      const workspace = document.querySelector("#workspace-content")
      if (!cockpit || !workspace) return null
      const cockpitBox = cockpit.getBoundingClientRect()
      const workspaceBox = workspace.getBoundingClientRect()
      return {
        cockpitBottom: cockpitBox.bottom,
        workspaceBottom: workspaceBox.bottom,
      }
    })
    expect(geometry).not.toBeNull()
    expect(geometry.cockpitBottom).toBeLessThanOrEqual(geometry.workspaceBottom + 2)

    await page.getByRole("tab", { name: "地点" }).click()
    await expect(page.getByRole("tab", { name: "地点" })).toHaveClass(/active/)
  })

  test("专注模式可恢复、可退出，并在桌面与手机保持正文状态", async ({ page, projectFactory, browserErrors }) => {
    await createDraft(testProjectId, 1, "第一章 专注写作", "用于验证专注模式宽度的正文。")
    const otherProject = await projectFactory({ title: "专注隔离对照作品", genre: "mystery", language: "zh" })
    await createDraft(otherProject.id, 1, "第一章 对照", "另一部作品的正文。")
    await page.setViewportSize({ width: 1280, height: 800 })
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    await selectWritingChapter(page, 1)
    const viewMenu = page.locator("details.writing-page-menu")
    const focusEntry = viewMenu.locator(":scope > summary")
    await expect(focusEntry).toHaveAccessibleName("写作视图")
    await expect(focusEntry).toHaveAttribute("aria-expanded", "false")
    await focusEntry.click()
    await expect(focusEntry).toHaveAttribute("aria-expanded", "true")
    await page.locator("#writing-editor").click()
    await expect(focusEntry).toHaveAttribute("aria-expanded", "false")

    await focusEntry.focus()
    await page.keyboard.press("Enter")
    await page.keyboard.press("Tab")
    await expect(viewMenu.getByRole("button", { name: "进入专注" })).toBeFocused()
    await page.keyboard.press("Escape")
    await expect(focusEntry).toHaveAttribute("aria-expanded", "false")
    await expect(focusEntry).toBeFocused()

    await focusEntry.click()
    await viewMenu.getByRole("button", { name: "进入专注" }).click()

    await expect(page.locator("body")).toHaveClass(/focus-mode-active/)
    await expect(page.locator("#writing-tree-container")).toBeHidden()
    await expect(page.locator("#writing-panel-container")).toBeHidden()
    await expect(page.locator("#topbar")).toBeHidden()
    await expect(page.locator("#sidebar")).toBeHidden()
    await expect(page.locator(".writing-toolbar")).toHaveCount(0)
    await expect(page.locator(".writing-editor-header")).toBeHidden()
    await expect(page.locator(".writing-focus-header")).toContainText("第一章 专注写作")
    await expect(page.locator("#writing-editor")).toBeVisible()
    await expect(page.locator("#writing-editor")).toBeFocused()
    const exitBox = await page.locator("#writing-focus-exit").boundingBox()
    expect(exitBox).not.toBeNull()
    expect(exitBox.height).toBeGreaterThanOrEqual(44)

    const geometry = await page.evaluate(() => {
      const workspace = document.querySelector("#workspace-content")
      const layout = document.querySelector(".writing-workspace-layout")
      const editorContainer = document.querySelector("#writing-editor-container")
      const editor = document.querySelector("#writing-editor")
      if (!workspace || !layout || !editorContainer || !editor) return null
      const workspaceBox = workspace.getBoundingClientRect()
      const layoutBox = layout.getBoundingClientRect()
      const containerBox = editorContainer.getBoundingClientRect()
      const editorBox = editor.getBoundingClientRect()
      return {
        workspaceWidth: workspaceBox.width,
        layoutWidth: layoutBox.width,
        containerWidth: containerBox.width,
        editorWidth: editorBox.width,
        editorCenterOffset: Math.abs(
          (editorBox.left + editorBox.width / 2) -
          (workspaceBox.left + workspaceBox.width / 2),
        ),
      }
    })

    expect(geometry).not.toBeNull()
    expect(geometry.containerWidth).toBeGreaterThan(geometry.workspaceWidth * 0.8)
    expect(geometry.editorWidth).toBeGreaterThanOrEqual(700)
    expect(geometry.editorCenterOffset).toBeLessThanOrEqual(2)

    await page.keyboard.press("Escape")
    await expect(page.locator("body")).not.toHaveClass(/focus-mode-active/)
    await expect(page.locator("#writing-editor")).toHaveValue("用于验证专注模式宽度的正文。")
    await expect(focusEntry).toBeFocused()

    await page.locator(".writing-statusbar__focus").click()
    await page.reload()
    await expect(page.locator(".writing-focus-header")).toBeVisible({ timeout: 10000 })
    await expect(page.locator("#writing-editor")).toHaveValue("用于验证专注模式宽度的正文。")
    await expect(page.locator("#writing-editor")).toBeFocused()

    await page.evaluate(() => window.router.navigate("project-settings"))
    await expect(page).toHaveURL(/project-settings/)
    await expect(page.locator("body")).not.toHaveClass(/focus-mode-active/)
    await page.goBack()
    await expect(page.locator(".writing-focus-header")).toBeVisible({ timeout: 10000 })
    await page.goForward()
    await expect(page).toHaveURL(/project-settings/)
    await page.goBack()
    await expect(page.locator(".writing-focus-header")).toBeVisible({ timeout: 10000 })

    await page.locator("#writing-focus-exit").click()
    await page.locator(".sidebar-project-switcher").click()
    await page.locator(SEL.projectCard(otherProject.id)).click()
    await page.evaluate(() => window.router.navigate("writing"))
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    await expect(page.locator("body")).not.toHaveClass(/focus-mode-active/)
    await expect(page.locator("#writing-editor")).toHaveValue("另一部作品的正文。")

    await page.locator(".sidebar-project-switcher").click()
    await page.locator(SEL.projectCard(testProjectId)).click()
    await page.setViewportSize({ width: 390, height: 844 })
    await page.evaluate(() => window.router.navigate("writing"))
    await waitWritingReady(page)
    await expect(page.locator(SEL.mobileNoteEditor)).toHaveValue("用于验证专注模式宽度的正文。")
    await page.locator("details.writing-page-menu > summary").click()
    const mobileMenu = page.locator("details.writing-page-menu")
    const mobileMenuBody = mobileMenu.locator(".writing-page-menu__body")
    await expect(mobileMenuBody).toBeInViewport()
    for (const button of await mobileMenuBody.getByRole("button").all()) {
      expect((await button.boundingBox())?.height).toBeGreaterThanOrEqual(44)
    }
    await mobileMenu.getByRole("button", { name: "进入专注" }).click()
    await expect(page.locator(".writing-focus-header")).toBeVisible()
    await expect(page.locator(SEL.mobileNoteEditor)).toBeFocused()
    const mobileExitBox = await page.locator("#writing-focus-exit").boundingBox()
    expect(mobileExitBox).not.toBeNull()
    expect(mobileExitBox.height).toBeGreaterThanOrEqual(44)
    expect(await page.evaluate(() => Math.ceil(document.documentElement.scrollWidth - window.innerWidth))).toBeLessThanOrEqual(2)
    await page.keyboard.press("Escape")
    await expect(page.locator(SEL.mobileNoteEditor)).toHaveValue("用于验证专注模式宽度的正文。")
    await expect(page.locator("body")).not.toHaveClass(/focus-mode-active/)
    expect(browserErrors).toEqual([])
  })

  test("桌面内容优先布局让正文占主要宽度且辅助栏可独立收起", async ({ page }) => {
    await createDraft(testProjectId, 1, "第一章 内容优先", "用于验证工作台分栏比例的正文。")
    await page.setViewportSize({ width: 1280, height: 800 })
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await writingChapter(page, 1).click()

    const before = await page.evaluate(() => {
      const layout = document.querySelector(".writing-workspace-layout")
      const editor = document.querySelector("#writing-editor-container")
      const left = document.querySelector(".writing-tree-rail")
      const right = document.querySelector(".writing-panel-rail")
      if (!layout || !editor || !left || !right) return null
      const contentWidth = editor.getBoundingClientRect().width
        + left.getBoundingClientRect().width
        + right.getBoundingClientRect().width
      return {
        editorWidth: editor.getBoundingClientRect().width,
        leftWidth: left.getBoundingClientRect().width,
        rightWidth: right.getBoundingClientRect().width,
        contentWidth,
      }
    })

    expect(before).not.toBeNull()
    // 三主题规范骨架：章节树固定 238px、写作副驾驶固定 257px，正文吃掉剩余弹性宽
    expect(before.leftWidth).toBe(238)
    expect(before.rightWidth).toBe(257)
    // 1280 视口下固定双 rail 后正文仍占最大份额（1440 基准下约 0.57）
    expect(before.editorWidth / before.contentWidth).toBeGreaterThanOrEqual(0.45)

    await page.getByLabel("收起写作副驾驶").click()
    await expect(page.locator(".writing-panel-rail")).toHaveClass(/is-collapsed/)
    const collapsedWidth = await page.locator("#writing-editor-container").evaluate((node) => node.getBoundingClientRect().width)
    expect(collapsedWidth).toBeGreaterThan(before.editorWidth)
  })

  test("剧情设定冲突检查流程、状态更新和发布快照归档", async ({ page }) => {
    await createAutosavedDraft(testProjectId, 1, "第一章", "旧稿")
    await createScene(testProjectId, {
      scene_index: 0,
      title: "宫门对峙",
      narrative_tag: "draft",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 12 }],
      must_happen: "王后签字",
      must_not_happen: "主角死亡",
    })

    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    await page.getByRole("button", { name: /^打开第 1 章/ }).click()
    await expect(page.locator("#writing-editor")).toBeVisible({ timeout: 5000 })

    await page.locator("#writing-title-input").fill("第一章 冲突检查")
    await page.locator("#writing-editor").fill("主角死亡。城门仍未开启。")
    await clickWritingTool(page, "#btn-conflict-check")

    const conflictOptions = page.getByRole("dialog", { name: "剧情设定冲突检查选项" })
    await expect(conflictOptions).toContainText("剧情设定冲突检查", { timeout: 10000 })
    await conflictOptions.getByRole("button", { name: "开始检查" }).click()
    const conflictDialog = page.getByRole("dialog", { name: "剧情设定冲突检查", exact: true })
    await expect(page.locator(".writing-conflict-item", { hasText: "疑似出现禁止项" })).toBeVisible()
    await expect(page.locator(".writing-conflict-item", { hasText: "必须发生项未逐字出现" })).toBeVisible()
    const forbiddenPresent = conflictDialog.locator(".writing-conflict-item", { hasText: "疑似出现禁止项" })
    await expect(forbiddenPresent.getByRole("button", { name: "定位正文" })).toBeEnabled()
    await expect(forbiddenPresent.getByRole("button", { name: "打开来源" })).toBeEnabled()
    const requiredMissing = conflictDialog.locator(".writing-conflict-item", { hasText: "必须发生项未逐字出现" })
    await expect(requiredMissing.getByRole("button", { name: "无正文定位" })).toBeDisabled()
    await expect(requiredMissing.getByRole("button", { name: "打开来源" })).toBeEnabled()

    let aiReviewDone = false
    const mockedAiCheck = {
      id: "mock-check-ai",
      novel_id: testProjectId,
      chapter_index: 1,
      scene_id: null,
      draft_id: null,
      version_number: 1,
      scope: {},
      include_candidates: false,
      status: "completed",
      summary_json: {
        total: 3,
        open_high_count: 1,
        ai_review: { status: "done", item_count: 1, discarded_count: 0 },
      },
      ai_review_enabled: true,
      ai_review_status: "done",
      ai_review_confirmation_id: "00000000-0000-0000-0000-0000000000a1",
      ai_review_model: "mock",
      ai_review_error: null,
      items: [
        {
          id: "mock-high",
          check_id: "mock-check-ai",
          novel_id: testProjectId,
          kind: "forbidden_present",
          severity: "high",
          source_module: "outline",
          evidence_summary: "正文出现 Scene 禁止发生项：主角死亡",
          is_ai_judgment: false,
          needs_review: false,
          status: "open",
          suggestion_status: "not_requested",
        },
        {
          id: "mock-required",
          check_id: "mock-check-ai",
          novel_id: testProjectId,
          kind: "required_missing",
          severity: "medium",
          source_module: "outline",
          evidence_summary: "正文尚未覆盖 Scene 必须发生项：王后签字",
          is_ai_judgment: false,
          needs_review: false,
          status: "open",
          suggestion_status: "not_requested",
        },
        {
          id: "mock-ai-item",
          check_id: "mock-check-ai",
          novel_id: testProjectId,
          kind: "motivation_gap",
          severity: "medium",
          source_module: "ai",
          evidence_summary: "主角突然接受守卫条件",
          is_ai_judgment: true,
          needs_review: false,
          status: "open",
          confidence: 0.72,
          llm_rationale: "前文没有建立信任动机",
          suggestion_status: "not_requested",
        },
      ],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    await page.route("**/api/context/confirm", async (route) => {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "00000000-0000-0000-0000-0000000000a1",
          novel_id: testProjectId,
          action: "writing.conflict_check.ai_review",
          selected_asset_ids: {},
          warnings: [],
        }),
      })
    })
    await page.route("**/api/writing/conflict-checks/*/ai-review", async (route) => {
      aiReviewDone = true
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockedAiCheck),
      })
    })
    await page.route("**/api/writing/conflict-checks/*/ai-review-task", async (route) => {
      aiReviewDone = true
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: "mock-ai-review-task",
          status: "pending",
          check: {
            ...mockedAiCheck,
            ai_review_status: "running",
            items: mockedAiCheck.items.slice(0, 2),
          },
        }),
      })
    })
    const suggestionTaskResults = new Map()
    await page.route("**/api/tasks/**", async (route) => {
      const url = new URL(route.request().url())
      const taskId = url.pathname.split("/").at(-1)
      const suggestionResult = suggestionTaskResults.get(taskId)
      if (!url.pathname.endsWith("/api/tasks/mock-ai-review-task") && !suggestionResult) {
        await route.continue()
        return
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: taskId,
          task_type: suggestionResult ? "writing_conflict_item_ai_suggestion" : "writing_conflict_ai_review",
          status: "done",
          progress: 1,
          result: suggestionResult || { check_id: mockedAiCheck.id, ai_review_status: "done" },
        }),
      })
    })
    await page.route("**/api/writing/conflict-checks/mock-check-ai?**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockedAiCheck),
      })
    })
    await page.route("**/api/writing/conflict-checks?**", async (route) => {
      if (!aiReviewDone) {
        await route.continue()
        return
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [mockedAiCheck], total: 1 }),
      })
    })
    await page.route("**/api/writing/conflict-check-items/*/ai-suggestion-task", async (route) => {
      const body = route.request().postDataJSON()
      const updatedAiItem = {
        ...mockedAiCheck.items[2],
        suggestion_status: "done",
        ai_suggestion: JSON.stringify({
          strategy: "补动机过渡",
          suggested_text: "他想起旧约，才勉强点头。",
          rationale: "让接受条件有心理来源。",
          constraints: ["不能提前揭示守卫真相"],
          risk_notes: ["保持守卫仍不可信"],
        }),
      }
      mockedAiCheck.items = mockedAiCheck.items.map((item) => (
        item.id === updatedAiItem.id ? updatedAiItem : item
      ))
      suggestionTaskResults.set(body.operation_id, updatedAiItem)
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({ task_id: body.operation_id, status: "pending" }),
      })
    })
    await page.route("**/api/writing/conflict-check-items/mock-required?**", async (route) => {
      const updatedRequiredItem = {
        ...mockedAiCheck.items[1],
        status: "later",
      }
      mockedAiCheck.items = mockedAiCheck.items.map((item) => (
        item.id === updatedRequiredItem.id ? updatedRequiredItem : item
      ))
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(updatedRequiredItem),
      })
    })

    await page.getByRole("button", { name: "手动补充 AI 语义复核" }).click()
    await expect(page.locator("#modal-overlay")).toContainText("AI 参考资料", { timeout: 10000 })
    const conflictOverlay = conflictDialog.locator("xpath=..")
    await expect(conflictOverlay).toHaveAttribute("inert", "")
    await page.keyboard.press("Escape")
    await expect(page.locator("#modal-overlay")).toBeHidden()
    await expect(conflictOverlay).not.toHaveAttribute("inert")
    await expect(page.getByRole("button", { name: "手动补充 AI 语义复核" })).toBeEnabled()
    await expect(conflictDialog.locator(":focus")).toHaveCount(1)
    await expect(page.locator(SEL.toastContainer)).not.toContainText("已取消 AI 参考资料确认")

    await page.getByRole("button", { name: "手动补充 AI 语义复核" }).click()
    await expect(page.locator("#modal-overlay")).toContainText("AI 参考资料", { timeout: 10000 })
    await page.locator("#modal-footer").getByRole("button", { name: "确认使用" }).click()
    await expect(conflictDialog).toContainText("AI 判断", { timeout: 10000 })
    await expect(conflictDialog).toContainText("主角突然接受守卫条件")

    const unavailableAi = conflictDialog.locator(".writing-conflict-item", { hasText: "主角突然接受守卫条件" })
    await expect(unavailableAi.getByRole("button", { name: "无正文定位" })).toBeDisabled()
    await expect(unavailableAi.getByRole("button", { name: "无可打开来源" })).toBeDisabled()

    await page
      .locator(".writing-conflict-item", { hasText: "主角突然接受守卫条件" })
      .getByRole("button", { name: "生成 AI 修复建议" })
      .click()
    await expect(page.locator("#modal-overlay")).toContainText("AI 参考资料", { timeout: 10000 })
    await page.locator("#modal-footer").getByRole("button", { name: "确认使用" }).click()
    await expect(conflictDialog).toContainText("补动机过渡", { timeout: 10000 })

    await page
      .locator(".writing-conflict-item", { hasText: "必须发生项未逐字出现" })
      .getByRole("button", { name: "稍后" })
      .click()
    await expect(page.locator(SEL.toastContainer)).toContainText("状态已更新", { timeout: 10000 })
    await conflictDialog.locator(".modal-footer").getByRole("button", { name: "关闭" }).click()

    await page.locator("#btn-publish").click()
    await expect(page.locator("#modal-overlay")).toContainText("未处理的重要问题", { timeout: 10000 })
    await page.locator("#modal-footer").getByRole("button", { name: "继续设为正式正文" }).click()
    await waitForPublishFeedback(page)

    const latestDraft = await getLatestDraft(testProjectId, 1)
    expect(latestDraft.novel_id).toBe(testProjectId)
    expect(latestDraft.status).toBe("published")
    expect(latestDraft.title).toBe("第一章 冲突检查")
    expect(latestDraft.content).toBe("主角死亡。城门仍未开启。")
    expect(latestDraft.conflict_check_snapshot_json?.items?.length).toBeGreaterThanOrEqual(2)
    expect(latestDraft.conflict_check_snapshot_json.items.some((item) => item.kind === "forbidden_present")).toBe(true)
  })

  test("纯章节目录的章节行有尺寸并可直接点击", async ({ page }) => {
    await createDraft(testProjectId, 1, "第一章", "第一章正文")
    await createDraft(testProjectId, 3, "第三章 归潮尽头", "第三章正文")
    await createScene(testProjectId, {
      scene_index: 0,
      title: "回声仓",
      narrative_tag: "draft",
      chapter_ids: ["1", "3"],
      scene_chunks: [
        { chapter_index: 1, start_pos: 0, end_pos: 5 },
        { chapter_index: 3, start_pos: 0, end_pos: 5 },
      ],
    })

    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    await expect(page.locator("#writing-tree-container")).not.toContainText("回声仓")
    await selectWritingChapter(page, 1)
    await expect(page.locator("#writing-panel-container")).toContainText("回声仓")

    const row = page.getByRole("button", { name: /打开第 3 章/ })
    await expect(row).toBeVisible({ timeout: 5000 })
    const box = await row.boundingBox()
    expect(box?.width).toBeGreaterThan(0)
    expect(box?.height).toBeGreaterThan(0)

    await row.click()
    await expect(page.locator("#writing-title-input")).toHaveValue("第三章 归潮尽头", { timeout: 5000 })
    await expect(page.locator("#writing-editor")).toHaveValue("第三章正文", { timeout: 5000 })
    await expect(page.locator("#btn-autosave")).toBeEnabled()
    await expect(page.locator("#btn-publish")).toBeEnabled()
    await expect(page.locator("#btn-conflict-check")).toBeEnabled()

    await page.getByRole("button", { name: /打开第 1 章/ }).click()
    await expect(page.locator("#writing-title-input")).toHaveValue("第一章", { timeout: 5000 })
    await expect(page.locator("#writing-editor")).toHaveValue("第一章正文", { timeout: 5000 })
    await row.click()
    await expect(page.locator("#writing-title-input")).toHaveValue("第三章 归潮尽头", { timeout: 5000 })
    await expect(page.locator("#writing-editor")).toHaveValue("第三章正文", { timeout: 5000 })
  })

  test("重复发布无实质变化的正文不制造版本或任务", async ({ page }) => {
    const initial = await createDraft(testProjectId, 3, "第三章 归潮尽头", "第三章正文")
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 3 })
    await selectWritingChapter(page, 3)
    await expect(page.locator("#writing-title-input")).toHaveValue("第三章 归潮尽头", { timeout: 5000 })

    const polledTaskUrls = []
    await page.route("**/api/tasks/**", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback()
        return
      }
      const url = new URL(route.request().url())
      polledTaskUrls.push(url.toString())
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: url.pathname.split("/").at(-1),
          task_type: "publish_chapter",
          status: "done",
          progress: null,
          meta: { novel_id: testProjectId, chapter_index: 3 },
          result: { message: "发布完成" },
          error_message: null,
          created_at: null,
          started_at: null,
          finished_at: null,
        }),
      })
    })

    await page.locator("#btn-publish").click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator("#writing-publish-bar-container")).toContainText("无实质变化")
    expect(polledTaskUrls).toEqual([])

    const afterFirstPublish = await getLatestDraft(testProjectId, 3)
    expect(afterFirstPublish.version_number).toBe(initial.draft.version_number)
    expect(afterFirstPublish.status).toBe("published")

    await page.locator("#btn-publish").click()
    await confirmPublishIfPrompted(page)
    await expect(page.locator("#writing-publish-bar-container")).toContainText("无实质变化")

    const afterSecondPublish = await getLatestDraft(testProjectId, 3)
    expect(afterSecondPublish.version_number).toBe(afterFirstPublish.version_number)
    expect(afterSecondPublish.id).toBe(afterFirstPublish.id)
  })

  test("写作台响应式宽度不出现页面级横向溢出", async ({ page }) => {
    await createDraft(testProjectId, 1, "响应式章节", "响应式正文")
    await createScene(testProjectId, {
      scene_index: 0,
      title: "响应式本场",
      narrative_tag: "draft",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 6 }],
      goal: "验证本场摘要不重复且不溢出",
    })

    for (const width of [1280, 900, 760, 600, 390]) {
      await page.setViewportSize({ width, height: 900 })
      await reloadWorkbench(page, "writing")
      await waitWritingReady(page)
      if (width <= 760) {
        await expect(page.locator("#mobile-note-editor")).toBeVisible({ timeout: 5000 })
        await expect(page.locator(".mobile-quick-note")).toContainText("更多编辑")
      } else {
        await selectWritingChapter(page, 1)
        await expect(page.locator("#writing-editor")).toBeVisible({ timeout: 5000 })
        await openWritingToolMenu(page, "#btn-conflict-check")
        await expect(page.locator("#btn-conflict-check")).toBeVisible()
        const expandReference = page.getByLabel("展开写作副驾驶")
        if (await expandReference.isVisible()) await expandReference.click()
      }

      await expect(page.locator(".scene-lens")).toHaveCount(1)
      if (width === 390) {
        const lens = page.locator("details.scene-lens--mobile")
        await lens.locator(":scope > summary").click()
        for (const target of [lens.locator(":scope > summary"), lens.locator(".scene-lens__load .btn")]) {
          const box = await target.boundingBox()
          expect(box).not.toBeNull()
          expect(box.height).toBeGreaterThanOrEqual(44)
        }
      }
      if (width === 900 || width === 1280) {
        const lensOverflow = await page.locator(".scene-lens").evaluate((element) => (
          Math.ceil(element.scrollWidth - element.clientWidth)
        ))
        expect(lensOverflow).toBeLessThanOrEqual(1)
      }

      const overflow = await page.evaluate(() => {
        const doc = document.documentElement
        return Math.ceil(doc.scrollWidth - window.innerWidth)
      })
      expect(overflow).toBeLessThanOrEqual(2)
    }
  })

  test("390px 下短文本可保存为工作稿并在刷新后恢复", async ({ page }) => {
    await createDraft(testProjectId, 1, "移动速记", "原始移动正文")
    await page.setViewportSize({ width: 390, height: 844 })
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    await selectWritingChapter(page, 1)

    const editor = page.getByLabel("移动端速记正文")
    await expect(editor).toBeVisible()
    await expect(editor).toHaveValue("原始移动正文")
    await editor.fill("390px 下保存的短文本。")
    const saveButton = page.getByRole("button", { name: "保存工作稿", exact: true })
    const saveBox = await saveButton.boundingBox()
    expect(saveBox).not.toBeNull()
    expect(saveBox.height).toBeGreaterThanOrEqual(44)
    const actionsBox = await page.locator(".mobile-note-actions").boundingBox()
    const navigationBox = await page.locator("#sidebar").boundingBox()
    expect(actionsBox).not.toBeNull()
    expect(navigationBox).not.toBeNull()
    expect(actionsBox.y + actionsBox.height).toBeLessThanOrEqual(navigationBox.y)
    await saveButton.click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存到工作稿", {
      timeout: 10000,
    })
    await expect.poll(async () => (
      (await getLatestDraft(testProjectId, 1)).content
    )).toBe("390px 下保存的短文本。")

    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    await expect(page.getByLabel("移动端速记正文")).toHaveValue("390px 下保存的短文本。")
    const overflow = await page.evaluate(() => (
      Math.ceil(document.documentElement.scrollWidth - window.innerWidth)
    ))
    expect(overflow).toBeLessThanOrEqual(2)
  })

  test("390px 可逆切换完整编辑器并在刷新后恢复模式", async ({ page, projectFactory }) => {
    const browserErrors = []
    const failedApiRequests = []
    page.on("pageerror", (error) => browserErrors.push(error.message))
    page.on("console", (message) => {
      if (message.type() === "error") browserErrors.push(message.text())
    })
    page.on("requestfailed", (request) => {
      if (request.url().includes("/api/")) failedApiRequests.push(`${request.method()} ${request.url()}`)
    })
    const otherProject = await projectFactory({ title: "移动模式隔离作品", genre: "fantasy", language: "zh" })
    await createDraft(otherProject.id, 1, "另一个作品", "独立的移动正文")
    await createDraft(testProjectId, 1, "移动切换", "切换前正文")
    await page.setViewportSize({ width: 390, height: 844 })
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    await selectWritingChapter(page, 1)
    const editor = page.getByLabel("移动端速记正文")
    await expect(editor).toHaveValue("切换前正文")
    await editor.fill("尚未保存但必须保留的正文")

    await page.getByRole("button", { name: "打开完整编辑器，可编辑标题、版本与检查" }).click()

    await expect(page.locator("#writing-editor")).toBeVisible()
    await expect(page.locator("#writing-editor")).toHaveValue("尚未保存但必须保留的正文")
    await expect(page.getByRole("button", { name: "返回速记" })).toBeFocused()
    await page.getByRole("button", { name: "返回速记" }).click()
    await expect(editor).toHaveValue("尚未保存但必须保留的正文")
    await expect(editor).toBeFocused()

    await page.getByRole("button", { name: "打开完整编辑器，可编辑标题、版本与检查" }).click()
    const saveSummary = page.locator("#writing-editor-buttons").getByText("保存", { exact: true })
    await saveSummary.click()
    await page.keyboard.press("Escape")
    await expect(page.locator("#writing-save-tools")).toBeHidden()
    await expect(saveSummary).toBeFocused()
    await saveSummary.click()
    await page.getByRole("button", { name: "保存工作稿", exact: true }).click()
    await expect(page.locator("#writing-save-tools")).toBeHidden()
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存到工作稿", { timeout: 10000 })
    await page.reload()
    await waitWritingReady(page)
    await expect(page.locator("#writing-editor")).toBeVisible()
    await expect(page.getByRole("button", { name: "返回速记" })).toBeVisible()

    await page.evaluate(() => window.router.navigate("project-settings"))
    await expect(page).toHaveURL(/project-settings/)
    await page.goBack()
    await expect(page.locator("#writing-editor")).toBeVisible({ timeout: 10000 })
    await page.goForward()
    await expect(page).toHaveURL(/project-settings/)
    await page.goBack()
    await expect(page.getByRole("button", { name: "返回速记" })).toBeVisible({ timeout: 10000 })

    await page.setViewportSize({ width: 900, height: 844 })
    await page.locator(".sidebar-project-switcher").click()
    await page.locator(SEL.projectCard(otherProject.id)).click()
    await expect(page.locator(SEL.topbarProject)).toHaveText("移动模式隔离作品")
    await page.setViewportSize({ width: 390, height: 844 })
    await page.evaluate(() => window.router.navigate("writing"))
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    await expect(page.getByLabel("移动端速记正文")).toHaveValue("独立的移动正文")

    await page.setViewportSize({ width: 900, height: 844 })
    await page.locator(".sidebar-project-switcher").click()
    await page.locator(SEL.projectCard(testProjectId)).click()
    await page.setViewportSize({ width: 390, height: 844 })
    await page.evaluate(() => window.router.navigate("writing"))
    await waitWritingReady(page)
    await expect(page.getByRole("button", { name: "返回速记" })).toBeVisible({ timeout: 10000 })
    expect(browserErrors).toEqual([])
    expect(failedApiRequests).toEqual([])
  })

  // ============================================================
  // 场景自动整理
  // ============================================================

  test("场景自动整理保留唯一 imports 入口", async ({ page }) => {
    await createDraft(testProjectId, 1, "ch1", "测试正文")
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })

    await page.locator('[data-action="writing-ai-menu"]').click()
    const sceneExtraction = page.getByRole("button", { name: "先整理场景骨架（推荐）" })
    await expect(sceneExtraction).toBeVisible()
    await expect(sceneExtraction).toHaveCount(1)

    await sceneExtraction.click()
    const extractionDialog = page.getByRole("dialog", { name: "自动提取" })
    await expect(extractionDialog).toBeVisible()
    await expect(extractionDialog).toContainText("从正文整理场景")
    await expect(extractionDialog).toContainText("起始章节")
    await expect(extractionDialog).toContainText("结束章节")

    await extractionDialog.getByRole("button", { name: "关闭" }).click()
    await expect(extractionDialog).not.toBeVisible()
  })

  // ============================================================
  // 多 Tab 冲突检测
  // ============================================================

  test("多 Tab 冲突检测 — 草稿被其他会话删除", async ({ page }) => {
    // 先加载 v1，再由另一会话创建 v2 并删除当前编辑的 v1。
    const d1 = await createDraft(testProjectId, 1, "v1", "原始内容")
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    await expect(page.locator("#writing-editor")).toHaveValue("原始内容", { timeout: 5000 })

    // 模拟另一个会话删除（软废弃）了当前编辑的 v1 版本
    await createDraft(testProjectId, 1, "v2", "另一个版本")
    await deleteDraft(testProjectId, d1.draft.id)

    // 尝试暂存 — v1 已不是最新工作版本，应返回 409 并给出可操作的冲突文案
    await page.locator("#writing-editor").fill("冲突内容")
    await clickWritingTool(page, "#btn-autosave")

    await expect(page.locator(SEL.toastContainer)).toContainText(
      "该章节已被其他会话更新，请刷新后重新编辑",
      { timeout: 10000 },
    )
  })
})
