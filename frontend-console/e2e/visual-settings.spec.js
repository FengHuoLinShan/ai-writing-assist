/**
 * settings 两页视觉基线 — Vue 迁移前后的像素对比锚点。
 *
 * 基线 PNG 提交在 e2e/visual-settings.spec.js-snapshots/（Playwright 默认目录约定）。
 * 首次生成用 `--update-snapshots`；此后普通运行即做像素对比。
 *
 * 确定性保障：
 * - beforeAll 显式重置后端全局 LLM 默认与作者偏好（其他 E2E 会修改这些持久化值），
 *   截图内容不依赖执行顺序或复用数据库状态。
 * - 动态内容：截图前等待 toast 容器清空（历史上还 mask 过"引用此默认的项目"列表，
 *   该列表已随设置页重构移除）。
 * - 基线仅提交 darwin 平台；其他平台默认跳过，需 `VISUAL_BASELINE=1` 配合
 *   `--update-snapshots` 生成并提交本平台基线后再作为门禁运行。
 */
import { test, expect, request } from "./fixtures.js"
import { API_BASE, waitForBackend } from "./helpers/api-client.js"

const THEMES = ["sticky", "night", "ink"]

const xhrHeaders = { "X-Requested-With": "XMLHttpRequest" }

async function applyTheme(page, theme) {
  await page.locator(`.theme-dot[data-theme-value="${theme}"]`).click()
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme)
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
}

async function screenshotSettingsPage(page, name) {
  await page.evaluate(() => document.fonts.ready.then(() => true))
  await page.evaluate(() => {
    window.scrollTo(0, 0)
    document.querySelector("#workspace-content")?.scrollTo(0, 0)
  })
  await expect(page.locator("#toast-container > *")).toHaveCount(0, { timeout: 3000 })
  await expect(page).toHaveScreenshot(name, {
    fullPage: true,
    animations: "disabled",
    caret: "hide",
  })
}

test.describe("settings 视觉基线", () => {
  test.skip(
    process.platform !== "darwin" && !process.env.VISUAL_BASELINE,
    "视觉基线仅提交 darwin 平台；其他平台需 VISUAL_BASELINE=1 --update-snapshots 生成本地基线",
  )

  test.use({ viewport: { width: 1440, height: 900 } })

  test.beforeAll(async () => {
    await waitForBackend(60000)
    // 固定后端全局设置为"未配置"（继承系统默认），屏蔽其他 E2E 的持久化修改
    const ctx = await request.newContext()
    const llmResp = await ctx.put(`${API_BASE}/account/settings/llm-defaults`, {
      headers: xhrHeaders,
      data: {
        timeout: null,
        max_tokens: null,
        temperature: null,
        top_p: null,
        extra: {},
      },
    })
    const prefsResp = await ctx.put(`${API_BASE}/account/settings/author-preferences`, {
      headers: xhrHeaders,
      data: { daily_goal: null, editor_font: null, default_focus_mode: null },
    })
    await ctx.dispose()
    expect(llmResp.ok(), "重置全局 LLM 默认失败").toBeTruthy()
    expect(prefsResp.ok(), "重置全局作者偏好失败").toBeTruthy()
  })

  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => localStorage.clear())
    await page.goto("/")
  })

  test("账户设置页 × 三主题", async ({ page }) => {
    await page.goto("/#settings")
    // hash-only goto 在 SPA 中偶发不触发重新渲染，reload 强制 initRouter 按 URL hash 渲染（确定性）
    await page.reload()
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "账户设置" })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole("button", { name: "保存创作偏好" })).toBeVisible()
    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotSettingsPage(page, `settings-global-${theme}.png`)
    }
  })

  test("项目设置页 × 三主题 + 两个 Tab", async ({ page, projectFactory }) => {
    const proj = await projectFactory({ title: "视觉基线项目", language: "zh" })
    await page.goto(`/#workbench/${proj.id}/project-settings`)
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "当前作品设置" })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole("tab", { name: "创作偏好" })).toHaveAttribute("aria-selected", "true")
    for (const theme of THEMES) {
      await applyTheme(page, theme)
      await screenshotSettingsPage(page, `settings-project-${theme}.png`)
    }

    await applyTheme(page, "sticky")
    await page.getByRole("tab", { name: "高级导入" }).click()
    await page.getByRole("button", { name: "查看专家参数" }).click()
    await expect(page.locator("#deep-import-phase0-target-input-chars")).toHaveValue("72000")
    await expect(page.getByRole("button", { name: /怎样切分场景/ })).toBeVisible()
    await screenshotSettingsPage(page, "settings-project-tab-deep-import.png")

    await page.getByRole("tab", { name: "创作偏好" }).click()
    await expect(page.getByText(/日更目标/)).toBeVisible()
    await screenshotSettingsPage(page, "settings-project-tab-author.png")
  })

  test.describe("390px", () => {
    test.use({ viewport: { width: 390, height: 844 } })

    test("账户与项目设置保持单栏且无横向溢出", async ({ page, projectFactory }) => {
      await page.goto("/#settings")
      await page.reload()
      await expect(page.getByRole("heading", { name: "账户设置" })).toBeVisible({ timeout: 10000 })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      await screenshotSettingsPage(page, "settings-global-mobile-sticky.png")

      const proj = await projectFactory({ title: "窄屏设置项目", language: "zh" })
      await page.goto(`/#workbench/${proj.id}/project-settings`)
      await expect(page.getByRole("heading", { name: "当前作品设置" })).toBeVisible({ timeout: 10000 })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      await expect(page.locator("#topbar-project")).toHaveText(proj.title)
      await expect(page.locator("#topbar-project")).toBeVisible()
      await expect(page.locator("#topbar-module")).toBeHidden()
      const topbarBoxes = await page.locator("#topbar").evaluate((topbar) => {
        const box = (selector) => {
          const rect = topbar.querySelector(selector)?.getBoundingClientRect()
          return rect ? { left: rect.left, right: rect.right } : null
        }
        return { left: box(".topbar-left"), center: box(".topbar-center"), right: box(".topbar-right") }
      })
      expect(topbarBoxes.left.right).toBeLessThanOrEqual(topbarBoxes.center.left + 1)
      expect(topbarBoxes.center.right).toBeLessThanOrEqual(topbarBoxes.right.left + 1)
      for (const button of await page.locator(".settings-shell button:visible").all()) {
        expect((await button.boundingBox())?.height || 0).toBeGreaterThanOrEqual(42)
      }
      await screenshotSettingsPage(page, "settings-project-mobile-sticky.png")

      await page.getByRole("tab", { name: "高级导入" }).click()
      const expert = page.getByRole("button", { name: "查看专家参数" })
      await expect(expert).toBeVisible()
      await expect(page.getByRole("button", { name: /怎样切分场景/ })).toBeHidden()
      expect((await expert.boundingBox())?.height || 0).toBeGreaterThanOrEqual(42)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      await screenshotSettingsPage(page, "settings-project-deep-mobile-sticky.png")
    })
  })
})
