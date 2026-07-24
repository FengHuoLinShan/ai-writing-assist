/**
 * 写作页视觉基线 — 守住编辑档案风格、正文优先布局和移动速记形态。
 *
 * 确定性保障：
 * - 每个场景使用独立项目和固定章节 / Scene 数据；
 * - 页面不展示 API id，截图前等待主题切换 toast 自然退出；
 * - 桌面覆盖三主题，专注模式覆盖正文居中，移动端固定 390×844；
 * - 基线仅提交 darwin 平台，其他平台可显式生成本地快照。
 */
import { test, expect } from "./fixtures.js"
import { createDraft, createScene, waitForBackend } from "./helpers/api-client.js"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench, waitWritingReady } from "./helpers/workbench.js"

const THEMES = ["minimal", "warm", "dark"]

async function applyTheme(page, theme) {
  await page.locator(SEL.themeToggle).click()
  await page.locator(SEL.themeOption(theme)).click()
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme)
}

async function screenshotPage(page, name) {
  await page.evaluate(() => document.fonts.ready.then(() => true))
  await expect(page.locator(SEL.toastItems)).toHaveCount(0, { timeout: 3000 })
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
    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.reload()
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

  test("should preserve the centered paper in focus mode", async ({ page, projectFactory }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    const project = await projectFactory({ title: "视觉基线专注写作", genre: "fantasy", language: "zh" })
    await seedWritingDesk(project.id)
    await openPopulatedDesk(page, project)
    await applyTheme(page, "minimal")

    await page.locator(SEL.writingToolbar).getByRole("button", { name: "聚焦模式" }).click()
    await expect(page.locator("body")).toHaveClass(/focus-mode-active/)
    await expect(page.locator(SEL.writingTreeRail)).toBeHidden()
    await expect(page.locator(SEL.writingPanelRail)).toBeHidden()
    await screenshotPage(page, "writing-focus-minimal.png")
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
    await applyTheme(page, "minimal")
    await screenshotPage(page, "writing-mobile-390-minimal.png")
  })
})
