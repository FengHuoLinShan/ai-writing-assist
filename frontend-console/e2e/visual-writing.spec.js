/**
 * 写作页视觉基线 — 守住编辑档案风格、正文优先布局和移动速记形态。
 *
 * 确定性保障：
 * - 每个场景使用独立项目和固定章节 / Scene 数据；
 * - 页面不展示 API id，截图前等待主题切换 toast 自然退出；
 * - 桌面覆盖三主题，专注模式覆盖桌面与 390px 退出路径，移动端固定 390×844；
 * - 基线仅提交 darwin 平台，其他平台可显式生成本地快照。
 */
import { test, expect } from "./fixtures.js"
import { createDraft, createScene, waitForBackend } from "./helpers/api-client.js"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench, waitWritingReady } from "./helpers/workbench.js"

const THEMES = ["sticky", "night", "ink"]

async function applyTheme(page, theme) {
  await page.locator(SEL.themeOption(theme)).click()
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme)
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await page.waitForTimeout(300)
}

async function screenshotPage(page, name, { waitForToasts = true } = {}) {
  await page.evaluate(() => document.fonts.ready.then(() => true))
  if (waitForToasts) await expect(page.locator(SEL.toastItems)).toHaveCount(0, { timeout: 3000 })
  await expect(page).toHaveScreenshot(name, {
    fullPage: true,
    animations: "disabled",
    caret: "hide",
  })
}

async function seedWritingDesk(projectId) {
  await createDraft(
    projectId,
    1,
    "第一章 潮门初启",
    "潮声退到石阶之外，露出一道从未被记载的门。\n\n林舟把旧航海图压在灯下，朱砂标记与门上的刻痕恰好重合。",
  )
  await createDraft(
    projectId,
    2,
    "第二章 雾港来信",
    "信纸带着盐和松脂的气味，只写了一句：退潮之前，不要相信钟楼。",
  )
  await createDraft(
    projectId,
    3,
    "第三章 共同代价",
    "三座岛的代表第一次坐在同一张桌前，却没有人愿意先交出航道图。",
  )
  await createScene(projectId, {
    scene_index: 0,
    title: "退潮后的石门",
    narrative_tag: "opening",
    chapter_ids: ["1"],
    scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 48 }],
    goal: "确认石门与旧航海图的联系",
    must_happen: "林舟发现朱砂标记重合",
    must_not_happen: "石门在本章完全开启",
    core_conflict: "公开发现，还是先保护同行者",
    emotional_beat: "由谨慎观察转为承担风险",
  })
}

async function openPopulatedDesk(page, project) {
  await openWorkbench(page, project, "writing")
  await waitWritingReady(page, { chapter: 1 })
  await page.getByRole("button", { name: /^打开第 1 章/ }).click()
  await page.locator(SEL.writingSceneLabel).click()
  await expect(page.locator(SEL.writingEditor)).toHaveValue(/潮声退到石阶之外/)
  await expect(page.locator(SEL.writingSceneCockpit)).toContainText("确认石门与旧航海图的联系")
}

test.describe("writing 视觉基线", () => {
  test.skip(
    process.platform !== "darwin" && !process.env.VISUAL_BASELINE,
    "视觉基线仅提交 darwin 平台；其他平台需 VISUAL_BASELINE=1 --update-snapshots 生成本地基线",
  )

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => localStorage.clear())
  })

  test("should preserve the populated writing desk across three themes", async ({ page, projectFactory }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    const project = await projectFactory({ title: "视觉基线写作台", genre: "fantasy", language: "zh" })
    await seedWritingDesk(project.id)
    await openPopulatedDesk(page, project)

    await expect(page.locator(SEL.writingWorkspace)).toBeVisible()
    await expect(page.locator(SEL.writingTreeRail)).toBeVisible()
    await expect(page.locator(SEL.writingPanelRail)).toBeVisible()
    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotPage(page, `writing-desk-${theme}.png`)
    }
  })

  test("should preserve writing advice entry on desktop and mobile", async ({ page, projectFactory, browserErrors }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    const project = await projectFactory({ title: "视觉基线写作建议", genre: "fantasy", language: "zh" })
    await seedWritingDesk(project.id)
    await openPopulatedDesk(page, project)
    await applyTheme(page, "sticky")

    await page.locator('[data-action="open-owner-ai-drawer"]').click()
    const drawer = page.locator("[data-owner-ai-drawer]")
    await expect(drawer).toBeVisible()
    await expect(drawer.locator('[data-action="owner-writing-generation"]')).toHaveAttribute("aria-selected", "true")
    await screenshotPage(page, "owner-ai-writing-advice-desktop-sticky.png")

    await page.setViewportSize({ width: 375, height: 812 })
    await applyTheme(page, "night")
    await expect(drawer.locator('[data-action="owner-writing-continuation"]')).toBeInViewport()
    await screenshotPage(page, "owner-ai-writing-advice-mobile-night.png")
    expect(browserErrors, `浏览器错误: ${JSON.stringify(browserErrors)}`).toHaveLength(0)
  })

  test("should preserve the writing view menu on desktop and mobile", async ({ page, projectFactory, browserErrors }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    const project = await projectFactory({ title: "视觉基线写作视图菜单", genre: "fantasy", language: "zh" })
    await seedWritingDesk(project.id)
    await openPopulatedDesk(page, project)
    await applyTheme(page, "sticky")

    const menu = page.locator("details.writing-page-menu")
    await menu.locator(":scope > summary").click()
    await expect(menu.locator(".writing-page-menu__body")).toBeVisible()
    await screenshotPage(page, "writing-view-menu-desktop-sticky.png")

    await applyTheme(page, "night")
    await menu.locator(":scope > summary").click()
    await expect(menu.locator(".writing-page-menu__body")).toBeVisible()
    await screenshotPage(page, "writing-view-menu-desktop-night.png")

    await applyTheme(page, "sticky")
    await menu.locator(":scope > summary").click()
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(menu.locator(".writing-page-menu__body")).toBeInViewport()
    expect(await page.evaluate(() => Math.ceil(document.documentElement.scrollWidth - window.innerWidth))).toBeLessThanOrEqual(2)
    await screenshotPage(page, "writing-view-menu-mobile-sticky.png")

    for (const viewport of [{ width: 375, height: 667 }, { width: 760, height: 430 }]) {
      await page.setViewportSize(viewport)
      await expect(menu.locator(".writing-page-menu__body")).toBeInViewport()
      expect(await page.evaluate(() => Math.ceil(document.documentElement.scrollWidth - window.innerWidth))).toBeLessThanOrEqual(2)
      const heights = await menu.locator(".writing-page-menu__body .btn").evaluateAll((buttons) => (
        buttons.map((button) => button.getBoundingClientRect().height)
      ))
      expect(heights.every((height) => height >= 44)).toBe(true)
    }
    expect(browserErrors).toEqual([])
  })

  test("should preserve the centered paper in focus mode", async ({ page, projectFactory }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    const project = await projectFactory({ title: "视觉基线专注写作", genre: "fantasy", language: "zh" })
    await seedWritingDesk(project.id)
    await openPopulatedDesk(page, project)
    await applyTheme(page, "sticky")

    await page.locator(".writing-statusbar__focus").click()
    await expect(page.locator("body")).toHaveClass(/focus-mode-active/)
    await expect(page.locator(SEL.writingToolbar)).toHaveCount(0)
    await expect(page.locator(".writing-focus-header")).toBeVisible()
    await expect(page.locator("#topbar")).toBeHidden()
    await expect(page.locator("#sidebar")).toBeHidden()
    await expect(page.locator(SEL.writingTreeRail)).toBeHidden()
    await expect(page.locator(SEL.writingPanelRail)).toBeHidden()
    await expect(page.locator(SEL.writingEditor)).toBeVisible()
    await screenshotPage(page, "writing-focus-sticky.png")

    await page.setViewportSize({ width: 390, height: 844 })
    await expect(page.locator(SEL.mobileQuickNote)).toBeVisible()
    await expect(page.locator("#writing-focus-exit")).toBeInViewport()
    await expect(page.locator(SEL.mobileNoteEditor)).toBeFocused()
    await screenshotPage(page, "writing-focus-mobile-sticky.png")
  })

  test("should preserve version history on desktop and mobile", async ({ page, projectFactory, browserErrors }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    const project = await projectFactory({ title: "视觉基线版本历史", genre: "fantasy", language: "zh" })
    await seedWritingDesk(project.id)
    await createDraft(
      project.id,
      1,
      "第一章 潮门初启",
      "潮声退到石阶之外，露出一道从未被记载的门。\n\n林舟把旧航海图压在灯下，决定在退潮前再校对一次刻痕。",
    )
    await openPopulatedDesk(page, project)
    await applyTheme(page, "sticky")

    await page.getByRole("button", { name: "版本历史", exact: true }).click()
    const dialog = page.getByRole("dialog", { name: "版本历史" })
    await expect(dialog).toBeVisible()
    await expect(dialog.locator(".writing-version-history-item")).toHaveCount(2)
    await screenshotPage(page, "writing-version-history-desktop-sticky.png")

    await dialog.getByRole("button", { name: "关闭" }).click()
    await applyTheme(page, "night")
    await page.getByRole("button", { name: "版本历史", exact: true }).click()
    await screenshotPage(page, "writing-version-history-desktop-night.png")

    await dialog.getByRole("button", { name: "关闭" }).click()
    await applyTheme(page, "sticky")
    await page.getByRole("button", { name: "版本历史", exact: true }).click()

    await page.setViewportSize({ width: 390, height: 844 })
    await expect(dialog).toBeInViewport()
    await expect(dialog.getByRole("button", { name: "关闭" })).toBeInViewport()
    expect(await page.evaluate(() => Math.ceil(document.documentElement.scrollWidth - window.innerWidth))).toBeLessThanOrEqual(2)
    await screenshotPage(page, "writing-version-history-mobile-sticky.png")

    for (const viewport of [{ width: 375, height: 667 }, { width: 760, height: 430 }]) {
      await page.setViewportSize(viewport)
      await expect(dialog.getByRole("button", { name: "关闭" })).toBeInViewport()
      expect(await page.evaluate(() => Math.ceil(document.documentElement.scrollWidth - window.innerWidth))).toBeLessThanOrEqual(2)
    }
    await page.setViewportSize({ width: 390, height: 844 })

    const oldVersion = dialog.locator(".writing-version-history-item").last()
    const moreButton = oldVersion.getByRole("button", { name: /版本 v\d+ 的更多操作/ })
    await moreButton.click()
    await expect(oldVersion.getByRole("menuitem", { name: "移入历史" })).toBeInViewport()
    await screenshotPage(page, "writing-version-history-menu-mobile-sticky.png")
    await page.keyboard.press("Escape")
    await expect(moreButton).toBeFocused()

    await oldVersion.getByRole("button", { name: "与当前打开版本比较" }).click()
    const diff = dialog.locator(".writing-version-diff")
    await expect(diff).toBeFocused()
    await expect(diff.locator("[data-side='版本 A']").first()).toBeVisible()
    await expect(diff.locator("[data-side='版本 B']").first()).toBeVisible()
    await screenshotPage(page, "writing-version-diff-mobile-sticky.png")
    expect(browserErrors).toEqual([])
  })

  test("should preserve the 390px mobile quick note", async ({ page, projectFactory }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const project = await projectFactory({ title: "视觉基线移动速记", genre: "fantasy", language: "zh" })
    await seedWritingDesk(project.id)
    await openWorkbench(page, project, "writing")
    await waitWritingReady(page)

    const chapterRail = page.locator(SEL.writingTreeRail)
    if (await chapterRail.evaluate((element) => element.classList.contains("is-collapsed"))) {
      await page.getByLabel("展开章节").click()
    }
    await page.getByRole("button", { name: /^打开第 1 章/ }).click()
    await expect(page.locator(SEL.mobileQuickNote)).toBeVisible()
    await expect(page.locator(SEL.mobileNoteEditor)).toHaveValue(/潮声退到石阶之外/)
    await expect(page.locator(".mobile-note-actions")).toBeInViewport()
    await applyTheme(page, "sticky")
    await screenshotPage(page, "writing-mobile-390-sticky.png")
  })

  test("should preserve the 390px complete editor", async ({ page, projectFactory }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const project = await projectFactory({ title: "视觉基线移动完整编辑", genre: "fantasy", language: "zh" })
    await seedWritingDesk(project.id)
    await openWorkbench(page, project, "writing")
    await waitWritingReady(page)

    await page.getByRole("button", { name: /^打开第 1 章/ }).click()
    await page.getByRole("button", { name: "打开完整编辑器，可编辑标题、版本与检查" }).click()
    await expect(page.locator(SEL.writingEditor)).toBeVisible()
    await expect(page.locator(SEL.writingTreeRail)).toHaveClass(/is-collapsed/)
    await expect(page.getByRole("button", { name: "返回速记" })).toBeInViewport()
    const returnBox = await page.getByRole("button", { name: "返回速记" }).boundingBox()
    expect(returnBox).not.toBeNull()
    expect(returnBox.height).toBeGreaterThanOrEqual(44)
    expect(await page.evaluate(() => Math.ceil(document.documentElement.scrollWidth - window.innerWidth))).toBeLessThanOrEqual(2)
    await applyTheme(page, "sticky")
    await screenshotPage(page, "writing-mobile-complete-editor-sticky.png")
  })

  test("should keep candidate decisions ahead of read-only prose", async ({ page, projectFactory }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    const project = await projectFactory({ title: "视觉基线候选审阅", genre: "fantasy", language: "zh" })
    const baseCreated = await createDraft(
      project.id,
      1,
      "第一章 雾港来信",
      "潮声退到石阶之外，石门仍旧紧闭。\n\n林舟把旧航海图收回箱底，决定等天亮再来。",
    )
    const base = baseCreated.draft || baseCreated
    const created = await createDraft(
      project.id,
      1,
      "第一章 雾港来信",
      "潮声退到石阶之外，露出一道从未被记载的门。\n\n林舟把旧航海图压在灯下，朱砂标记与门上的刻痕恰好重合。",
    )
    const candidate = created.draft || created
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

    await openWorkbench(page, project, "writing")
    await page.evaluate(({ draftId }) => {
      const query = new URLSearchParams({ chapter_index: "1", draft_id: draftId })
      return window.router.navigate("writing", null, true, query)
    }, { draftId: candidate.id })
    await waitWritingReady(page, { chapter: 1 })
    const panel = page.locator(".writing-candidate-review-panel")
    await expect(panel).toBeFocused()
    await expect(panel).toBeInViewport()
    await expect(panel.getByRole("button", { name: "与当前工作稿比较" })).toBeVisible()
    await applyTheme(page, "sticky")
    await screenshotPage(page, "writing-candidate-review-desktop-sticky.png")

    await page.setViewportSize({ width: 390, height: 844 })
    await expect(page.locator(".writing-tree-rail")).toHaveClass(/is-collapsed/)
    await expect(page.locator(".writing-statusbar")).toBeHidden()
    await expect(panel).toBeInViewport()
    await expect(page.locator(".writing-candidate-review-actions .btn").last()).toBeInViewport()
    await screenshotPage(page, "writing-candidate-review-mobile-sticky.png")

    await panel.getByRole("button", { name: "与当前工作稿比较" }).click()
    const comparison = page.getByRole("dialog", { name: "版本历史" })
    await expect(comparison.locator(".writing-version-diff")).toBeFocused()
    await screenshotPage(page, "writing-candidate-compare-mobile-sticky.png")
  })

  test("should keep save recovery visible on desktop and mobile", async ({ page, projectFactory }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    const project = await projectFactory({ title: "视觉基线保存恢复", genre: "fantasy", language: "zh" })
    await seedWritingDesk(project.id)
    await openPopulatedDesk(page, project)
    await applyTheme(page, "sticky")
    await page.route("**/api/writing/drafts/**", async (route) => {
      if (route.request().method() !== "PUT") return route.continue()
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "网络暂时不可用" }),
      })
    })

    await page.locator(SEL.writingEditor).fill("尚未保存但仍安全保留的正文")
    await page.getByRole("button", { name: /^打开第 2 章/ }).click()
    await expect(page.locator("#writing-retry-save")).toBeVisible()
    await page.addStyleTag({ content: "#toast-container { display: none !important; }" })
    await screenshotPage(page, "writing-save-recovery-desktop-sticky.png", { waitForToasts: false })

    await page.setViewportSize({ width: 390, height: 844 })
    const mobileRecovery = page.locator(".mobile-quick-note .writing-save-recovery")
    await expect(mobileRecovery).toBeVisible()
    await expect(mobileRecovery.getByRole("button", { name: "重试保存" })).toBeInViewport()
    await screenshotPage(page, "writing-save-recovery-mobile-sticky.png", { waitForToasts: false })
  })
})
