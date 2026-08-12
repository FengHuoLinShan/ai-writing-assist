/**
 * project / rag 页视觉基线 — Phase 2 Vue 迁移的像素对比锚点。
 *
 * 机制与 visual-settings.spec.js 一致：darwin 基线按平台提交、动态内容 mask、
 * 三主题对比。确定性保障：
 * - 项目页：两个项目创建间隔 >1s（稳定排序），统计数字与创建日期 mask；
 * - rag 检索页：page.route 拦截证据接口返回固定 58 条（复用 rag.spec.js 手法）；
 * - rag 状态页：新项目全零计数，天然确定。
 */
import { test, expect } from "./fixtures.js"
import { waitForBackend } from "./helpers/api-client.js"
import { openWorkbench } from "./helpers/workbench.js"

const THEMES = ["sticky", "night", "ink"]

async function applyTheme(page, theme) {
  await page.locator(`.theme-dot[data-theme-value="${theme}"]`).click()
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

test.describe("project / rag 视觉基线", () => {
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

  test("项目页 × 三主题", async ({ page, projectFactory }) => {
    await projectFactory({ title: "视觉基线项目·甲", genre: "scifi", language: "zh" })
    await page.waitForTimeout(1100) // 稳定 created_at 排序
    await projectFactory({ title: "视觉基线项目·乙", genre: "fantasy", language: "zh" })

    await page.goto("/")
    await page.getByRole("button", { name: /我是作家/ }).click()
    await expect(page.locator("#project-catalog-title")).toBeVisible({ timeout: 10000 })
    // 复用库中可能残留其他测试项目：搜索过滤到本测试的两个项目，保证内容确定
    await page.locator("#project-search-input").fill("视觉基线项目")
    await expect(page.locator(".project-card[data-id]")).toHaveCount(2)
    const mask = [
      page.locator("dl.project-stats"),
      page.locator(".project-meta"),
      page.locator('[data-role="project-total-count"]'),
      page.locator('[data-role="project-filter-count"]'),
      page.locator(".project-archive-hero__folio strong"),
    ]
    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotPage(page, `project-catalog-${theme}.png`, mask)
    }
  })

  test("rag 状态页 × 三主题", async ({ page, projectFactory }) => {
    const proj = await projectFactory({ title: "视觉基线检索", genre: "scifi", language: "zh" })
    await openWorkbench(page, proj, "rag", "status")
    await expect(page.getByRole("heading", { name: "查找资料尚未准备好" })).toBeVisible({ timeout: 10000 })
    await expect(page.locator('[data-action="rebuild-index"]')).toBeVisible({ timeout: 10000 })
    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotPage(page, `rag-status-${theme}.png`)
    }
  })

  test("rag 检索结果页 × 三主题", async ({ page, projectFactory }) => {
    const proj = await projectFactory({ title: "视觉基线检索", genre: "scifi", language: "zh" })
    await page.route("**/api/context/evidence/search", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          total: 58,
          hits: Array.from({ length: 58 }, (_, index) => ({
            kind: "manuscript",
            title: `旧塔结果 ${index + 1}`,
            snippet: `旧塔的固定证据 ${index + 1}`,
            chapter_index: index + 1,
            source_ref: {
              content_mode: "canonical",
              chapter_index: index + 1,
              version_number: 1,
              source_content_hash: `hash-${index + 1}`,
            },
          })),
          warnings: [],
          degraded: false,
        }),
      })
    })

    await openWorkbench(page, proj, "rag", "search")
    await expect(page.locator("#rag-search-input")).toBeVisible({ timeout: 10000 })
    await page.getByLabel("检索关键词").fill("旧塔")
    await page.locator('[data-action="do-search"]').click()
    await expect(page.locator(".rag-result-card")).toHaveCount(20)
    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotPage(page, `rag-search-${theme}.png`)
    }
  })
})
