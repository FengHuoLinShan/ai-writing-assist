/**
 * 写作首页视觉基线 — 守住继续写作优先、作者任务与待决定事项的阅读层级。
 *
 * 确定性保障：
 * - 复用 projectFactory 创建并清理唯一测试项目；
 * - workspace-summary 使用固定作者可见数据，不把动态日期、id 或任务状态写入截图；
 * - 桌面覆盖三主题，移动端固定 390x844；共四张最小快照。
 */
import { test, expect } from "./fixtures.js"
import { waitForBackend } from "./helpers/api-client.js"
import { openWorkbench } from "./helpers/workbench.js"

const THEMES = ["sticky", "night", "ink"]

async function applyTheme(page, theme) {
  await page.locator(`.theme-dot[data-theme-value="${theme}"]`).click()
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme)
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await page.waitForTimeout(300)
}

async function screenshotPage(page, name) {
  await page.evaluate(() => document.fonts.ready.then(() => true))
  await expect(page.locator("#toast-container > *")).toHaveCount(0, { timeout: 3000 })
  await expect(page).toHaveScreenshot(name, {
    fullPage: true,
    animations: "disabled",
    caret: "hide",
  })
}

function fixedSummary(projectId) {
  return {
    project_id: projectId,
    continuation: {
      chapter_index: 3,
      title: "第三章 雾港来信",
      has_unpublished_changes: true,
    },
    writing: { chapter_count: 3, word_count: 12840 },
    author_tasks: {
      today_count: 2,
      inbox_count: 1,
      later_count: 0,
      preview: [
        { id: "task-1", title: "补齐钟楼守卫的动机", source: null },
        { id: "task-2", title: "核对退潮前后的时间线", source: null },
      ],
    },
    attention: {
      actionable_total: 2,
      has_more: false,
      items: [
        {
          key: "writing-conflict-1",
          source_kind: "writing_conflict",
          title: "第三章的退潮时间与前文不一致",
          summary: "前文写明钟声后才退潮，本章目前写成了钟声前。",
          author_action: "needs_decision",
          relevance: "current_chapter",
          target: { kind: "writing_conflict", chapter_index: 3, item_id: "conflict-1" },
        },
        {
          key: "world-object-1",
          source_kind: "world_object",
          title: "林舟的旧航海图缺少来源",
          summary: "补充来历后，后续章节更容易保持人物知识边界。",
          author_action: "can_improve",
          relevance: "project_general",
          target: { kind: "world_review_objects", item_id: "entity-1" },
        },
      ],
    },
  }
}

test.describe("写作首页视觉基线", () => {
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

  test("should preserve the Today hierarchy across desktop themes and 390px", async ({ page, projectFactory, browserErrors }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    const project = await projectFactory({ title: "潮门纪事", genre: "fantasy", language: "zh" })
    await page.route(`**/api/projects/${project.id}/workspace-summary*`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(fixedSummary(project.id)),
      })
    })

    await openWorkbench(page, project, "today")
    await expect(page.locator("#today-title")).toHaveText("欢迎回到《潮门纪事》")
    await expect(page.locator(".today-resume .btn-primary")).toHaveCount(1)
    await expect(page.locator(".today-author-task-row")).toHaveCount(2)
    await expect(page.locator(".today-attention-row")).toHaveCount(2)

    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotPage(page, `today-home-${theme}.png`)
    }

    await applyTheme(page, "sticky")
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(page.locator(".today-resume__action")).toBeInViewport()
    expect(await page.evaluate(() => Math.ceil(document.documentElement.scrollWidth - window.innerWidth))).toBeLessThanOrEqual(2)
    await screenshotPage(page, "today-home-mobile-390-sticky.png")

    expect(browserErrors, `浏览器错误: ${JSON.stringify(browserErrors)}`).toHaveLength(0)
  })
})
