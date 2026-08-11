import { test, expect, request } from "./fixtures.js"
import {
  createProject,
  cleanupProject,
  waitForBackend,
} from "./helpers/api-client.js"

const backendPort = process.env.BACKEND_PORT || "8000"
const apiBase = `http://localhost:${backendPort}/api`
const xhrHeaders = { "X-Requested-With": "XMLHttpRequest" }

test.describe("设置流程", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.reload()
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try {
        await cleanupProject(testProjectId)
      } catch {}
      testProjectId = null
    }
  })

  test("账户页可直达并同时提供模型连接与作者偏好", async ({ page }) => {
    await page.goto("/#settings")
    // hash-only goto 在 SPA 中偶发不触发重新渲染，reload 强制 initRouter 按 URL hash 渲染（确定性）
    await page.reload()
    // 限定 workspace-content，避免与顶部栏模块标题冲突
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "账户与模型连接" })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole("heading", { name: "通用创作偏好" })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole("heading", { name: "连接 AI 服务" })).toBeVisible({ timeout: 10000 })
    const providerGroup = page.getByRole("radiogroup", { name: "模型模板" })
    const providers = providerGroup.getByRole("radio")
    const selectedProvider = providerGroup.locator('[role="radio"][aria-checked="true"]')
    await selectedProvider.focus()
    await page.keyboard.press("End")
    await expect(providers.last()).toBeFocused()
    await expect(providers.last()).toHaveAttribute("aria-checked", "true")
  })

  test("项目设置页深链 + Tab 切换", async ({ page }) => {
    const proj = await createProject({ title: "E2E Settings Project", language: "zh" })
    testProjectId = proj.id
    await page.goto(`/#workbench/${testProjectId}/project-settings`)
    await page.reload()
    await expect(page.locator("#workspace-content").getByRole("heading", { name: /^项目偏好/ })).toBeVisible({ timeout: 10000 })
    const deepTab = page.getByRole("tab", { name: "高级导入" })
    const authorTab = page.getByRole("tab", { name: "创作偏好" })
    await expect(deepTab).toBeVisible()
    await expect(authorTab).toHaveAttribute("aria-selected", "true")
    await expect(deepTab).toHaveAttribute("aria-controls", "project-settings-tab-panel")
    await expect(page.locator("#project-settings-tab-panel")).toHaveAttribute(
      "aria-labelledby",
      await authorTab.getAttribute("id"),
    )
    await authorTab.focus()
    await page.keyboard.press("End")
    await expect(deepTab).toBeFocused()
    await expect(deepTab).toHaveAttribute("aria-selected", "true")
    await expect(page.locator("#project-settings-tab-panel")).toHaveAttribute(
      "aria-labelledby",
      await deepTab.getAttribute("id"),
    )
    await expect(page.getByText(/模型与密钥由“账户与模型连接”统一管理/)).toBeVisible()
    await expect(page.getByText(/Phase 0/)).toBeVisible()
    await page.keyboard.press("Home")
    await expect(authorTab).toHaveAttribute("aria-selected", "true")
    await expect(page.getByText(/日更目标/)).toBeVisible()
  })

  test("作者偏好覆盖与恢复继承", async ({ page }) => {
    const proj = await createProject({ title: "Prefs Override", language: "zh" })
    testProjectId = proj.id
    const ctx = await request.newContext()
    await ctx.put(`${apiBase}/settings/author-preferences`, {
      headers: xhrHeaders,
      data: { editor_font: "mono" },
    })
    await ctx.put(`${apiBase}/settings/projects/${testProjectId}/author-preferences`, {
      headers: xhrHeaders,
      data: { editor_font: "serif" },
    })
    await ctx.dispose()

    await page.goto(`/#workbench/${testProjectId}/project-settings`)
    await page.reload()
    await expect(page.locator("#workspace-content").getByRole("heading", { name: /^项目偏好/ })).toBeVisible({ timeout: 10000 })
    await page.getByRole("tab", { name: "创作偏好" }).click()
    await expect(page.locator("#author-editor-font")).toHaveValue("serif")

    const ctx2 = await request.newContext()
    await ctx2.delete(
      `${apiBase}/settings/projects/${testProjectId}/author-preferences/field/editor_font`,
      { headers: xhrHeaders },
    )
    await ctx2.dispose()

    await page.reload()
    // reload 后需重新等渲染完成
    await expect(page.locator("#workspace-content").getByRole("heading", { name: /^项目偏好/ })).toBeVisible({ timeout: 10000 })
    await page.getByRole("tab", { name: "创作偏好" }).click()
    await expect(page.locator("#author-editor-font")).toHaveValue("mono")
  })

  test("项目作者偏好以中文显示选项和来源值，但保留原始保存值", async ({ page }) => {
    const proj = await createProject({ title: "Localized Author Preferences", language: "zh" })
    testProjectId = proj.id
    const ctx = await request.newContext()
    const response = await ctx.put(`${apiBase}/settings/projects/${testProjectId}/author-preferences`, {
      headers: xhrHeaders,
      data: { editor_font: "system", default_focus_mode: false },
    })
    expect(response.ok()).toBe(true)
    expect(response.status()).toBe(200)
    await ctx.dispose()

    await page.goto(`/#workbench/${testProjectId}/project-settings`)
    await page.reload()
    await expect(page.locator("#workspace-content").getByRole("heading", { name: /^项目偏好/ })).toBeVisible({ timeout: 10000 })
    await page.getByRole("tab", { name: "创作偏好" }).click()
    const font = page.locator("#author-editor-font")
    await expect(font).toHaveValue("system")
    await expect(font.locator("option")).toHaveText(["跟随系统", "衬线", "无衬线", "等宽"])
    await expect(font.locator("option").first()).toHaveAttribute("value", "system")
    const fontGroup = page.locator(".author-prefs-tab .form-group").filter({ has: font })
    await expect(fontGroup.locator(".source-label")).toHaveText("已覆盖")
    await expect(fontGroup.locator(".source-value")).toHaveText("跟随系统")
    const focusGroup = page.locator(".author-prefs-tab .form-group").filter({
      has: page.locator("#author-default-focus"),
    })
    await expect(focusGroup.locator(".source-label")).toHaveText("已覆盖")
    await expect(focusGroup.locator(".source-value")).toHaveText("关闭")
  })

  test("项目设置不再提供项目级模型与 Key", async ({ page }) => {
    const proj = await createProject({ title: "Account Model Notice", language: "zh" })
    testProjectId = proj.id

    await page.goto(`/#workbench/${testProjectId}/project-settings`)
    await page.reload()
    await expect(page.locator("#workspace-content").getByRole("heading", { name: /^项目偏好/ })).toBeVisible({ timeout: 10000 })
    await expect(page.getByText(/当前模型：/)).toBeVisible()
    await expect(page.locator("#llm-api-key")).toHaveCount(0)
    await expect(page.locator("#llm-provider")).toHaveCount(0)
    await expect(page.getByRole("button", { name: "管理账户与模型连接" })).toBeVisible()
  })

  test("深度导入字段越界校验 toast", async ({ page }) => {
    const proj = await createProject({ title: "DI Validation", language: "zh" })
    testProjectId = proj.id
    await page.goto(`/#workbench/${testProjectId}/project-settings`)
    // reload 强制 initRouter 按 URL hash 同步 currentProjectId，规避空态竞态
    await page.reload()
    await expect(page.getByRole("tab", { name: "高级导入" })).toBeVisible({ timeout: 10000 })
    await page.getByRole("tab", { name: "高级导入" }).click()
    await page.fill("#deep-import-phase0-target-input-chars", "10")
    await page.getByRole("button", { name: "保存深度导入参数" }).click()
    await expect(page.getByText(/必须是/).first()).toBeVisible({ timeout: 5000 })
  })

  test("#/llm 别名：有项目时跳转到项目设置", async ({ page }) => {
    const proj = await createProject({ title: "Alias With Project", language: "zh" })
    testProjectId = proj.id
    await page.goto(`/#workbench/${testProjectId}/writing`)
    await page.waitForLoadState("networkidle")
    await page.goto(`/#workbench/${testProjectId}/llm`)
    await page.waitForURL(/project-settings/, { timeout: 5000 })
    await expect(page).toHaveURL(/project-settings/)
  })

  test("#/llm 别名：无项目时跳转全局", async ({ page }) => {
    await page.goto("/#llm")
    await page.waitForURL(/#settings/, { timeout: 5000 })
    await expect(page).toHaveURL(/#settings/)
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "账户与模型连接" })).toBeVisible({ timeout: 5000 })
  })
})
