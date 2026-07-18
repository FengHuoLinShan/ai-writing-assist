/**
 * settings 两页视觉基线 — Vue 迁移前后的像素对比锚点。
 *
 * 基线 PNG 提交在 e2e/visual-settings.spec.js-snapshots/（Playwright 默认目录约定）。
 * 首次生成用 `--update-snapshots`；此后普通运行即做像素对比。
 *
 * 动态内容处理：项目 ID 为随机 UUID，"引用此默认的项目"列表逐次不同，整体 mask；
 * toast 容器同样 mask，避免异步通知干扰。
 */
import { test, expect } from "./fixtures.js"
import { waitForBackend } from "./helpers/api-client.js"

const THEMES = ["minimal", "warm", "dark"]

async function applyTheme(page, theme) {
  await page.locator("#theme-toggle").click()
  await page.locator(`#theme-menu [data-theme-value="${theme}"]`).click()
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme)
}

async function screenshotSettingsPage(page, name) {
  await page.evaluate(() => document.fonts.ready.then(() => true))
  await expect(page).toHaveScreenshot(name, {
    fullPage: true,
    animations: "disabled",
    caret: "hide",
    mask: [
      page.locator(".projects-using-list"),
      page.locator("#toast-container"),
    ],
    maxDiffPixelRatio: 0.02,
  })
}

test.describe("settings 视觉基线", () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.reload()
  })

  test("全局设置页 × 三主题", async ({ page }) => {
    await page.goto("/#settings")
    // hash-only goto 在 SPA 中偶发不触发重新渲染，reload 强制 initRouter 按 URL hash 渲染（确定性）
    await page.reload()
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "全局设置" })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole("button", { name: "保存作者偏好" })).toBeVisible()
    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotSettingsPage(page, `settings-global-${theme}.png`)
    }
  })

  test("项目设置页 × 三主题 + 三个 Tab", async ({ page, projectFactory }) => {
    const proj = await projectFactory({ title: "视觉基线项目", language: "zh" })
    await page.goto(`/#workbench/${proj.id}/project-settings`)
    await page.reload()
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "项目设置" })).toBeVisible({ timeout: 10000 })
    await expect(page.locator("#llm-max-tokens")).toHaveValue("12000")
    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotSettingsPage(page, `settings-project-${theme}.png`)
    }

    await applyTheme(page, "minimal")
    await page.getByRole("button", { name: "深度导入" }).click()
    await expect(page.getByText(/Phase 0/)).toBeVisible()
    await screenshotSettingsPage(page, "settings-project-tab-deep-import.png")

    await page.getByRole("button", { name: "作者偏好" }).click()
    await expect(page.getByText(/日更目标/)).toBeVisible()
    await screenshotSettingsPage(page, "settings-project-tab-author.png")
  })
})
