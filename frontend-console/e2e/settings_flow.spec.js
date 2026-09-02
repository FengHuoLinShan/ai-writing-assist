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
  let extraProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => localStorage.clear())
    await page.goto("/")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try {
        await cleanupProject(testProjectId)
      } catch {}
      testProjectId = null
    }
    if (extraProjectId) {
      try {
        await cleanupProject(extraProjectId)
      } catch {}
      extraProjectId = null
    }
  })

  test("账户页可直达并同时提供模型连接与作者偏好", async ({ page }) => {
    const browserErrors = []
    const failedResponses = []
    page.on("console", (message) => {
      if (message.type() === "error") browserErrors.push(message.text())
    })
    page.on("response", (response) => {
      if (response.status() >= 500) failedResponses.push(`${response.status()} ${response.url()}`)
    })
    await page.goto("/#settings")
    // hash-only goto 在 SPA 中偶发不触发重新渲染，reload 强制 initRouter 按 URL hash 渲染（确定性）
    await page.reload()
    // 限定 workspace-content，避免与顶部栏模块标题冲突
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "账户设置" })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole("heading", { name: "通用创作偏好" })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole("heading", { name: "AI 文本服务" })).toBeVisible({ timeout: 10000 })
    const providerGroup = page.getByRole("radiogroup", { name: "AI 文本服务" })
    const providers = providerGroup.getByRole("radio")
    const selectedProvider = providerGroup.locator('[role="radio"][aria-checked="true"]')
    await selectedProvider.focus()
    await page.keyboard.press("End")
    await expect(providers.last()).toBeFocused()
    await expect(providers.last()).toHaveAttribute("aria-checked", "true")
    await expect(page.locator(".settings-advanced-section")).not.toHaveAttribute("open", "")
    expect(browserErrors).toEqual([])
    expect(failedResponses).toEqual([])
  })

  test("账户连接加载失败后可在原位重试", async ({ page }) => {
    let shouldFail = true
    await page.route("**/api/account/settings/llm-connections", async (route) => {
      if (shouldFail) {
        shouldFail = false
        await route.abort("failed")
        return
      }
      await route.continue()
    })

    await page.goto("/#settings")
    await page.reload()
    const error = page.locator(".account-connection-section .settings-load-error")
    await expect(error).toContainText("模型连接暂时无法加载", { timeout: 10000 })
    await expect(error).toHaveAttribute("role", "alert")
    await error.getByRole("button", { name: "重新加载" }).click()
    await expect(page.getByRole("radiogroup", { name: "AI 文本服务" })).toBeVisible()
    await expect(error).toHaveCount(0)
  })

  test("项目设置页深链 + Tab 切换", async ({ page }) => {
    const proj = await createProject({ title: "E2E Settings Project", language: "zh" })
    testProjectId = proj.id
    const browserErrors = []
    const failedResponses = []
    page.on("console", (message) => {
      if (message.type() === "error") browserErrors.push(message.text())
    })
    page.on("response", (response) => {
      if (response.status() >= 500) failedResponses.push(`${response.status()} ${response.url()}`)
    })
    await page.goto(`/#workbench/${testProjectId}/project-settings`)
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "当前作品设置" })).toBeVisible({ timeout: 10000 })
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
    await expect(page.getByText(/模型与密钥仍由账户设置统一管理/)).toBeVisible()
    await expect(page.getByRole("button", { name: /怎样切分场景/ })).toBeVisible()
    await page.keyboard.press("Home")
    await expect(authorTab).toHaveAttribute("aria-selected", "true")
    await expect(page.getByText(/日更目标/)).toBeVisible()

    await page.locator("#author-daily-goal").fill("1350")
    await expect(page.locator(".author-prefs-tab .settings-save-state")).toHaveText("有未保存修改")
    await page.getByRole("button", { name: "保存创作偏好" }).click()
    await expect(page.locator(".author-prefs-tab .settings-save-state")).toContainText("已保存")
    await page.reload()
    await expect(page.locator("#author-daily-goal")).toHaveValue("1350")

    await page.locator('[data-action="settings-scope-account"]').click()
    await expect(page.getByRole("heading", { name: "账户设置" })).toBeVisible()
    await page.goBack()
    await expect(page.getByRole("heading", { name: "当前作品设置" })).toBeVisible()
    expect(browserErrors).toEqual([])
    expect(failedResponses).toEqual([])
    await expect(page.locator("#author-daily-goal")).toHaveValue("1350")
    await page.goForward()
    await expect(page.getByRole("heading", { name: "账户设置" })).toBeVisible()
    await page.goBack()
    await expect(page.getByRole("heading", { name: "当前作品设置" })).toBeVisible()
  })

  test("项目偏好加载失败可重试，切换作品前保护未保存输入", async ({ page }) => {
    const proj = await createProject({ title: "Settings Guard A", language: "zh" })
    testProjectId = proj.id
    const other = await createProject({ title: "Settings Guard B", language: "zh" })
    extraProjectId = other.id
    let shouldFail = true
    await page.route(`**/api/projects/${testProjectId}/effective-author-preferences`, async (route) => {
      if (shouldFail) {
        shouldFail = false
        await route.abort("failed")
        return
      }
      await route.continue()
    })

    await page.goto(`/#workbench/${testProjectId}/project-settings`)
    const error = page.locator("#project-settings-tab-panel .settings-load-error")
    await expect(error).toContainText("当前作品的设置暂时无法加载", { timeout: 10000 })
    await error.getByRole("button", { name: "重新加载" }).click()
    await expect(page.locator("#author-daily-goal")).toBeVisible()

    await page.locator("#author-daily-goal").fill("2468")
    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("未保存修改")
      await dialog.dismiss()
    })
    await page.locator(".sidebar-project-switcher").click()
    await expect(page.getByRole("heading", { name: "当前作品设置" })).toBeVisible()
    await expect(page.locator("#author-daily-goal")).toHaveValue("2468")

    page.once("dialog", async (dialog) => dialog.accept())
    await page.locator(".sidebar-project-switcher").click()
    const extraProject = page.locator(`.project-card[data-id="${extraProjectId}"]`)
    await expect(extraProject).toBeVisible()
    await extraProject.click()
    await expect(page.locator("#topbar-project")).toHaveText("Settings Guard B")
    await page.evaluate(() => window.router.navigate("project-settings"))
    await expect(page.getByRole("heading", { name: "当前作品设置" })).toBeVisible()
    await expect(page.locator("#author-daily-goal")).not.toHaveValue("2468")
  })

  test("作者偏好覆盖与恢复继承", async ({ page }) => {
    const proj = await createProject({ title: "Prefs Override", language: "zh" })
    testProjectId = proj.id
    const ctx = await request.newContext()
    await ctx.put(`${apiBase}/account/settings/author-preferences`, {
      headers: xhrHeaders,
      data: { editor_font: "mono" },
    })
    await ctx.put(`${apiBase}/projects/${testProjectId}/author-preferences`, {
      headers: xhrHeaders,
      data: { editor_font: "serif" },
    })
    await ctx.dispose()

    await page.goto(`/#workbench/${testProjectId}/project-settings`)
    await page.reload()
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "当前作品设置" })).toBeVisible({ timeout: 10000 })
    await page.getByRole("tab", { name: "创作偏好" }).click()
    await expect(page.locator("#author-editor-font")).toHaveValue("serif")

    const ctx2 = await request.newContext()
    await ctx2.delete(
      `${apiBase}/projects/${testProjectId}/author-preferences/field/editor_font`,
      { headers: xhrHeaders },
    )
    await ctx2.dispose()

    await page.reload()
    // reload 后需重新等渲染完成
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "当前作品设置" })).toBeVisible({ timeout: 10000 })
    await page.getByRole("tab", { name: "创作偏好" }).click()
    await expect(page.locator("#author-editor-font")).toHaveValue("mono")
  })

  test("项目作者偏好以中文显示选项和来源值，但保留原始保存值", async ({ page }) => {
    const proj = await createProject({ title: "Localized Author Preferences", language: "zh" })
    testProjectId = proj.id
    const ctx = await request.newContext()
    const response = await ctx.put(`${apiBase}/projects/${testProjectId}/author-preferences`, {
      headers: xhrHeaders,
      data: { editor_font: "system", default_focus_mode: false },
    })
    expect(response.ok()).toBe(true)
    expect(response.status()).toBe(200)
    await ctx.dispose()

    await page.goto(`/#workbench/${testProjectId}/project-settings`)
    await page.reload()
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "当前作品设置" })).toBeVisible({ timeout: 10000 })
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
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "当前作品设置" })).toBeVisible({ timeout: 10000 })
    await expect(page.getByText(/AI 文本服务：/)).toBeVisible()
    await expect(page.locator("#llm-api-key")).toHaveCount(0)
    await expect(page.locator("#llm-provider")).toHaveCount(0)
    await expect(page.getByRole("button", { name: "管理连接" })).toBeVisible()
  })

  test("深度导入字段越界校验 toast", async ({ page }) => {
    const proj = await createProject({ title: "DI Validation", language: "zh" })
    testProjectId = proj.id
    await page.goto(`/#workbench/${testProjectId}/project-settings`)
    // reload 强制 initRouter 按 URL hash 同步 currentProjectId，规避空态竞态
    await page.reload()
    await expect(page.getByRole("tab", { name: "高级导入" })).toBeVisible({ timeout: 10000 })
    await page.getByRole("tab", { name: "高级导入" }).click()
    await page.getByRole("button", { name: "查看专家参数" }).click()
    await page.getByRole("button", { name: /怎样切分场景/ }).click()
    await page.fill("#deep-import-phase0-target-input-chars", "10")
    await page.getByRole("button", { name: "保存深度导入参数" }).click()
    await expect(page.getByText(/必须是/).first()).toBeVisible({ timeout: 5000 })
    await expect(page.locator("#deep-import-phase0-target-input-chars")).toBeFocused()
    await expect(page.locator("#deep-import-phase0-target-input-chars")).toHaveAttribute("aria-invalid", "true")
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
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "账户设置" })).toBeVisible({ timeout: 5000 })
  })
})
