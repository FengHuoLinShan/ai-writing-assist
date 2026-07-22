/**
 * outline 页视觉基线 — Phase 3c Vue 迁移的像素对比锚点。
 *
 * 机制与 visual-world.spec.js 一致：darwin 基线按平台提交、动态内容 mask、
 * 三主题对比。确定性保障：
 * - 每个测试用独立新项目 + API 种子数据（总纲 revision/篇章纲/剧情线），内容完全确定；
 * - outline 页面不渲染日期；计数由种子数据推导；
 * - scenes 子视图归 sceneWorkbenchView（Phase 4），不在本基线范围；
 * - 基线仅提交 darwin 平台；其他平台需 VISUAL_BASELINE=1 --update-snapshots 生成本地基线。
 */
import { test, expect } from "./fixtures.js"
import {
  createArc,
  createStoryOutlineRevision,
  createThread,
  waitForBackend,
} from "./helpers/api-client.js"
import { openWorkbench } from "./helpers/workbench.js"

const THEMES = ["minimal", "warm", "dark"]

async function applyTheme(page, theme) {
  await page.locator("#theme-toggle").click()
  await page.locator(`#theme-menu [data-theme-value="${theme}"]`).click()
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme)
}

async function screenshotPage(page, name, mask = []) {
  await page.evaluate(() => document.fonts.ready.then(() => true))
  await expect(page.locator("#toast-container > *")).toHaveCount(0, { timeout: 3000 })
  await expect(page).toHaveScreenshot(name, {
    fullPage: true,
    animations: "disabled",
    caret: "hide",
    mask,
  })
}

test.describe("outline 视觉基线", () => {
  test.skip(
    process.platform !== "darwin" && !process.env.VISUAL_BASELINE,
    "视觉基线仅提交 darwin 平台；其他平台需 VISUAL_BASELINE=1 --update-snapshots 生成本地基线",
  )

  test.use({ viewport: { width: 1440, height: 900 } })

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.reload()
  })

  test("outline 小说总纲 × 三主题", async ({ page, projectFactory }) => {
    const proj = await projectFactory({ title: "视觉基线总纲", genre: "fantasy", language: "zh" })
    await createStoryOutlineRevision(proj.id, {
      base_revision_id: null,
      idempotency_key: `visual-baseline-${proj.id}`,
      source: "manual",
      provenance: { actor: "author" },
      title: "群岛共同体",
      creative_core: {
        premise: "孤立群岛必须共同面对退潮遗迹。",
        tone_and_reader_promise: "克制的海洋奇幻与渐进真相。",
        story_engine: "每次退潮都带来资源、真相与新的共同代价。",
        ending_direction: "分权联盟取代单一王座。",
      },
      outline_markdown: "# 总体方向\n\n故事围绕共同承担秩序推进。",
      major_storylines: [],
      macro_movements: [],
      open_decisions: [],
    })

    await openWorkbench(page, proj, "outline", "story-outline")
    await expect(page.locator(".story-outline-workspace")).toBeVisible({ timeout: 10000 })
    await expect(page.locator(".story-outline-workspace")).toContainText("群岛共同体")
    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotPage(page, `outline-story-outline-${theme}.png`)
    }
  })

  test("outline 篇章纲 × 三主题", async ({ page, projectFactory }) => {
    const proj = await projectFactory({ title: "视觉基线篇章纲", genre: "fantasy", language: "zh" })
    await createArc(proj.id, { title: "第一卷 潮起", start_chapter: 1, end_chapter: 10, arc_goal: "主角初入江湖，建立航盟。" })
    await createArc(proj.id, { title: "第二卷 暗涌", start_chapter: 11, end_chapter: 22, arc_goal: "旧势力反扑，航盟分裂危机。" })

    await openWorkbench(page, proj, "outline", "arcs")
    await expect(page.locator('[data-action="nav-arcs"]')).toHaveClass(/active/)
    await expect(page.locator("#workspace-content")).toContainText("第一卷 潮起")
    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotPage(page, `outline-arcs-${theme}.png`)
    }
  })

  test("outline 剧情线 × 三主题", async ({ page, projectFactory }) => {
    const proj = await projectFactory({ title: "视觉基线剧情线", genre: "fantasy", language: "zh" })
    await createThread(proj.id, { name: "潮门调查", thread_type: "main", summary: "主角追查潮门背后的筛选机制。" })
    await createThread(proj.id, { name: "旧港暗线", thread_type: "sub", summary: "旧港渔夫守护的世代秘密。" })

    await openWorkbench(page, proj, "outline", "threads")
    await expect(page.locator('[data-action="nav-threads"]')).toHaveClass(/active/)
    await expect(page.locator("#workspace-content")).toContainText("潮门调查")
    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotPage(page, `outline-threads-${theme}.png`)
    }
  })
})
