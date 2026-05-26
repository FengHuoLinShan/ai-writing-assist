import { test, expect } from "@playwright/test"

test.describe("首页加载", () => {
  test("应用加载并显示项目视图", async ({ page }) => {
    await page.goto("http://localhost:8080")

    // 确认页面标题
    await expect(page.locator("#topbar-title")).toContainText("小说结构化创作控制台")
    // 确认侧边栏导航存在
    await expect(page.locator("#sidebar")).toBeVisible()
    // 确认 workspace 存在
    await expect(page.locator("#workspace")).toBeVisible()
  })

  test("侧边栏导航项可见", async ({ page }) => {
    await page.goto("http://localhost:8080")

    const navItems = ["project", "world", "character", "outline", "writing"]
    for (const item of navItems) {
      await expect(page.locator(`[data-view="${item}"]`)).toBeVisible()
    }
  })
})
