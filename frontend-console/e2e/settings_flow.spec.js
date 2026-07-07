import { test, expect, request } from "@playwright/test"
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

  test("全局页可直达且渲染作者偏好区", async ({ page }) => {
    await page.goto("/#settings")
    // hash-only goto 在 SPA 中偶发不触发重新渲染，reload 强制 initRouter 按 URL hash 渲染（确定性）
    await page.reload()
    // 限定 workspace-content，避免与 topbar 的 #view-title（同名 h2）冲突
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "全局设置" })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole("heading", { name: "作者偏好全局默认" })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole("heading", { name: "LLM 全局默认" })).toBeVisible({ timeout: 10000 })
  })

  test("项目设置页深链 + Tab 切换", async ({ page }) => {
    const proj = await createProject({ title: "E2E Settings Project", language: "zh" })
    testProjectId = proj.id
    await page.goto(`/#workbench/${testProjectId}/project-settings`)
    await page.reload()
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "项目设置" })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole("button", { name: "主配置" })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole("button", { name: "深度导入" })).toBeVisible()
    await expect(page.getByRole("button", { name: "作者偏好" })).toBeVisible()
    await page.getByRole("button", { name: "深度导入" }).click()
    await expect(page.getByText(/Phase 0/)).toBeVisible()
    await page.getByRole("button", { name: "作者偏好" }).click()
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
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "项目设置" })).toBeVisible({ timeout: 10000 })
    await page.getByRole("button", { name: "作者偏好" }).click()
    await expect(page.locator("#author-editor-font")).toHaveValue("serif")

    const ctx2 = await request.newContext()
    await ctx2.delete(
      `${apiBase}/settings/projects/${testProjectId}/author-preferences/field/editor_font`,
      { headers: xhrHeaders },
    )
    await ctx2.dispose()

    await page.reload()
    // reload 后需重新等渲染完成
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "项目设置" })).toBeVisible({ timeout: 10000 })
    await page.getByRole("button", { name: "作者偏好" }).click()
    await expect(page.locator("#author-editor-font")).toHaveValue("mono")
  })

  test("字段 source 标签：继承 → 覆盖", async ({ page }) => {
    const proj = await createProject({ title: "Source Label", language: "zh" })
    testProjectId = proj.id
    const ctx = await request.newContext()
    await ctx.put(`${apiBase}/settings/llm-defaults`, {
      headers: xhrHeaders,
      data: {
        provider_id: "openai-compatible",
        base_url: "https://api.openai.com/v1",
        model: "gpt-4o",
      },
    })
    await ctx.dispose()

    await page.goto(`/#workbench/${testProjectId}/project-settings`)
    await page.reload()
    await expect(page.locator("#workspace-content").getByRole("heading", { name: "项目设置" })).toBeVisible({ timeout: 10000 })
    await expect(page.getByText("继承全局").first()).toBeVisible({ timeout: 10000 })
    await page.fill("#llm-base-url", "https://custom.example.com/v1")
    await page.getByRole("button", { name: "保存项目 LLM 配置" }).click()
    await expect(page.getByText("已覆盖").first()).toBeVisible()
  })

  test("深度导入字段越界校验 toast", async ({ page }) => {
    const proj = await createProject({ title: "DI Validation", language: "zh" })
    testProjectId = proj.id
    await page.goto(`/#workbench/${testProjectId}/project-settings`)
    // reload 强制 initRouter 按 URL hash 同步 currentProjectId，规避空态竞态
    await page.reload()
    await expect(page.getByRole("button", { name: "主配置" })).toBeVisible({ timeout: 10000 })
    await page.getByRole("button", { name: "深度导入" }).click()
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

  test("#/llm 别名：无项目时跳转全局 + toast", async ({ page }) => {
    await page.goto("/#llm")
    await page.waitForURL(/#settings/, { timeout: 5000 })
    await expect(page).toHaveURL(/#settings/)
    await expect(page.getByText("请先选择项目").first()).toBeVisible({ timeout: 5000 })
  })
})
