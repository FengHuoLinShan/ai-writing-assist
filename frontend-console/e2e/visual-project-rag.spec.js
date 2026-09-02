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
import { openWorkbench, openWritingAiDrawer } from "./helpers/workbench.js"

const THEMES = ["sticky", "night", "ink"]

async function applyTheme(page, theme) {
  await page.locator(`.theme-dot[data-theme-value="${theme}"]`).click()
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme)
  const announcement = page.locator("#toast-container .toast")
  await expect(announcement).toBeVisible()
  await expect(announcement).toHaveCount(0, { timeout: 3000 })
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
    await page.addInitScript(() => {
      if (sessionStorage.getItem("visual-storage-ready")) return
      localStorage.clear()
      sessionStorage.setItem("visual-storage-ready", "1")
    })
    await page.goto("/")
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
    ]
    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotPage(page, `project-catalog-${theme}.png`, mask)
    }
  })

  test("rag 状态页 × 三主题", async ({ page, projectFactory, browserErrors }) => {
    const proj = await projectFactory({ title: "视觉基线检索", genre: "scifi", language: "zh" })
    await openWorkbench(page, proj, "rag", "status")
    await expect(page.getByRole("heading", { name: "查找资料尚未准备好" })).toBeVisible({ timeout: 10000 })
    await expect(page.locator('[data-action="rebuild-index"]')).toBeVisible({ timeout: 10000 })
    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotPage(page, `rag-status-${theme}.png`)
    }
    await page.setViewportSize({ width: 390, height: 844 })
    await page.evaluate(() => localStorage.setItem("nc-theme", "night"))
    await page.reload()
    await expect(page.locator("html")).toHaveAttribute("data-theme", "night")
    await expect(page.getByRole("heading", { name: "查找资料尚未准备好" })).toBeVisible({ timeout: 10000 })
    await page.evaluate(() => window.scrollTo(0, 0))
    await expect(page).toHaveScreenshot("rag-status-mobile-night.png", {
      animations: "disabled",
      caret: "hide",
    })
    expect(browserErrors, `浏览器错误: ${JSON.stringify(browserErrors)}`).toHaveLength(0)
  })

  test("rag 检索结果页 × 三主题", async ({ page, projectFactory, browserErrors }) => {
    const proj = await projectFactory({ title: "视觉基线检索", genre: "scifi", language: "zh" })
    await page.route("**/api/evidence/compilation/evidence/search", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          total: 58,
          hits: Array.from({ length: 58 }, (_, index) => ({
            kind: "manuscript",
            title: `旧塔结果 ${index + 1}`,
            snippet: `旧塔的铜铃在夜里响起，守卫沿着潮湿石阶赶往塔顶。这是第 ${index + 1} 条固定证据。`,
            score: 0.92 - (index % 5) * 0.05,
            match_count: index === 0 ? 3 : 1,
            chapter_index: index + 1,
            parent_scene_contexts: index === 0 ? [{
              target_type: "outline_scene",
              target_id: "scene-1",
              scene_index: 1,
              scene_title: "夜探旧塔",
              context_summary: "目标：找到密道入口；阻碍：铜铃声会惊动守卫。",
            }] : [],
            writing_relevance: index === 0 ? {
              kind: "previous_scene",
              label: "前序场景：可用于核对当前场景的剧情承接。",
            } : {},
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
    await page.route("**/api/evidence/compilation/evidence/read", async (route) => {
      const payload = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          title: "第一章 · 旧塔",
          text: "旧塔的铜铃在夜里响起，守卫沿着潮湿石阶赶往塔顶。",
          highlight_start: 0,
          highlight_end: 6,
          source_ref: payload.source_ref,
          scene_refs: [],
          object_refs: [],
          warnings: [],
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

    await applyTheme(page, "sticky")
    await page.locator('[data-action="open-hit"]').first().click()
    await expect(page.locator("#rag-evidence-drawer")).toContainText("旧塔的铜铃")
    await expect(page.locator("#toast-container > *")).toHaveCount(0, { timeout: 3000 })
    await expect(page).toHaveScreenshot("rag-evidence-drawer-desktop.png", {
      animations: "disabled",
      caret: "hide",
    })
    await page.locator('[data-action="close-drawer"]').click()

    await page.setViewportSize({ width: 390, height: 844 })
    await applyTheme(page, "night")
    await expect(page).toHaveScreenshot("rag-search-mobile-night.png", {
      animations: "disabled",
      caret: "hide",
    })
    await page.locator('[data-role="rag-advanced-filters"] summary').click()
    await expect(page.getByText("从哪里查", { exact: true })).toBeVisible()
    await page.setViewportSize({ width: 390, height: 1400 })
    await expect(page).toHaveScreenshot("rag-search-filters-mobile-night.png", {
      animations: "disabled",
      caret: "hide",
    })
    await page.locator('[data-role="rag-advanced-filters"] summary').click()
    await page.setViewportSize({ width: 390, height: 844 })
    await page.locator('[data-action="open-hit"]').first().click()
    await expect(page.locator("#rag-evidence-drawer")).toContainText("旧塔的铜铃")
    await expect(page.locator("#toast-container > *")).toHaveCount(0, { timeout: 3000 })
    await expect(page).toHaveScreenshot("rag-evidence-drawer-mobile.png", {
      animations: "disabled",
      caret: "hide",
    })
    expect(browserErrors, `浏览器错误: ${JSON.stringify(browserErrors)}`).toHaveLength(0)
  })

  test("AI 工具查找资料首屏 × 桌面与手机", async ({ page, projectFactory, browserErrors }) => {
    const proj = await projectFactory({ title: "视觉基线抽屉查找", genre: "scifi", language: "zh" })
    await openWorkbench(page, proj, "writing")
    await openWritingAiDrawer(page)
    await page.getByRole("tab", { name: "查找资料", exact: true }).click()
    await expect(page.locator("#owner-ai-panel-evidence #rag-search-input")).toBeVisible({ timeout: 10000 })

    await applyTheme(page, "sticky")
    await expect(page).toHaveScreenshot("owner-ai-search-desktop-sticky.png", {
      animations: "disabled",
      caret: "hide",
    })

    await page.setViewportSize({ width: 390, height: 844 })
    await applyTheme(page, "night")
    await expect(page).toHaveScreenshot("owner-ai-search-mobile-night.png", {
      animations: "disabled",
      caret: "hide",
    })
    expect(browserErrors, `浏览器错误: ${JSON.stringify(browserErrors)}`).toHaveLength(0)
  })
})
