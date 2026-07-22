/**
 * world 页视觉基线 — Phase 3a Vue 迁移的像素对比锚点。
 *
 * 机制与 visual-settings.spec.js / visual-project-rag.spec.js 一致：
 * darwin 基线按平台提交、动态内容 mask、三主题对比。确定性保障：
 * - 每个测试用独立新项目 + API 种子数据（实体/候选/世界书页面），内容完全确定；
 * - world 页面不渲染日期；hot 概览计数由种子数据推导，新项目全零章节上下文；
 * - 基线仅提交 darwin 平台；其他平台需 VISUAL_BASELINE=1 --update-snapshots 生成本地基线。
 */
import { test, expect } from "./fixtures.js"
import { createEntity, createWorldBiblePage, waitForBackend } from "./helpers/api-client.js"
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

test.describe("world 视觉基线", () => {
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

  test("world 对象库 × 三主题", async ({ page, projectFactory }) => {
    const proj = await projectFactory({ title: "视觉基线世界", genre: "fantasy", language: "zh" })
    await createEntity(proj.id, { name: "沉钟港", entity_type: "location", status: "canonical", summary: "北境航线的旧港口" })
    await createEntity(proj.id, { name: "雾岭", entity_type: "location", status: "canonical", summary: "终年多雾的山岭" })
    await createEntity(proj.id, { name: "林澈", entity_type: "character", status: "canonical", summary: "巡港人" })
    await createEntity(proj.id, { name: "月廷", entity_type: "organization", status: "canonical", summary: "月神教团" })

    await openWorkbench(page, proj, "world", "objects")
    await expect(page.locator(".world-hot-overview")).toBeVisible({ timeout: 10000 })
    await expect(page.locator(".data-table tbody tr[data-id]")).toHaveCount(4)
    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotPage(page, `world-objects-${theme}.png`)
    }
  })

  test("world 待处理（对象队列）× 三主题", async ({ page, projectFactory }) => {
    const proj = await projectFactory({ title: "视觉基线待处理", genre: "fantasy", language: "zh" })
    await createEntity(proj.id, { name: "潮声会", entity_type: "organization", status: "candidate", summary: "码头工人的行会" })
    await createEntity(proj.id, { name: "旧灯塔", entity_type: "location", status: "candidate", summary: "废弃的导航灯塔" })
    await createEntity(proj.id, { name: "阿荞", entity_type: "character", status: "candidate", summary: "灯塔看守的孙女" })

    await openWorkbench(page, proj, "world", "review-objects")
    await expect(page.locator(".world-review-workspace, .data-table").first()).toBeVisible({ timeout: 10000 })
    await expect(page.locator("tr[data-id]")).toHaveCount(3)
    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotPage(page, `world-review-objects-${theme}.png`)
    }
  })

  test("world 世界书 × 三主题", async ({ page, projectFactory }) => {
    const proj = await projectFactory({ title: "视觉基线世界书", genre: "fantasy", language: "zh" })
    await createWorldBiblePage(proj.id, { title: "世界基本背景", page_type: "background" })
    await createWorldBiblePage(proj.id, { title: "北境诸港", page_type: "geography" })

    await openWorkbench(page, proj, "world", "bible")
    await expect(page.locator(".world-bible-workspace")).toBeVisible({ timeout: 10000 })
    await expect(page.locator(".world-bible-workspace")).toContainText("世界基本背景")
    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotPage(page, `world-bible-${theme}.png`)
    }
  })
})
