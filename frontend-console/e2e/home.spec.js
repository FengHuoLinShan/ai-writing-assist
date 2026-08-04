import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { waitForBackend } from "./helpers/api-client.js"
import { expectNoPageOverflow, expectWithinViewport } from "./helpers/responsive.js"

test.describe("首页与导航", () => {
  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  async function enterAuthor(page) {
    await page.getByRole("button", { name: /我是作家/ }).click()
    await expect(page.locator(SEL.sidebar)).toBeVisible()
  }

  test("应用加载并显示两个清晰的身份入口", async ({ page }) => {
    await page.goto("/")

    await expect(page.getByRole("heading", { name: "今天想怎样进入故事？" }))
      .toBeVisible()
    await expect(page.getByRole("button", { name: /我是作家/ })).toBeVisible()
    await expect(page.getByRole("button", { name: /我是 RP/ })).toBeVisible()
    await expect(page.locator(SEL.sidebar)).toHaveCount(0)
    await expect(page.locator(SEL.workspace)).toBeVisible()
  })

  test("侧边栏导航项可见", async ({ page }) => {
    await page.goto("/")
    await enterAuthor(page)

    const navItems = [
      "project",
      "world",
      "map",
      "writing",
      "rag",
      "outline",
      "generate",
      "settings",
      "project-settings",
    ]
    for (const item of navItems) {
      await expect(page.locator(SEL.navItem(item))).toBeVisible()
    }
    await expect(page.locator(SEL.navItem("scene"))).toHaveCount(0)
    await expect(page.locator(SEL.navItem("context"))).toHaveCount(0)
  })

  test("点击导航切换视图", async ({ page }) => {
    await page.goto("/")
    await enterAuthor(page)

    await page.locator(SEL.navItem("world")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("项目")
    await expect(page.locator(SEL.navItem("project"))).toHaveClass(/active/)
    await expect(page.locator(SEL.navItem("world"))).not.toHaveClass(/active/)
    await expect(page.locator(SEL.toastContainer)).toContainText("请先选择项目后再进入该页面")

    await page.locator(SEL.navItem("writing")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("项目")
    await expect(page.locator(SEL.navItem("project"))).toHaveClass(/active/)
    await expect(page.locator(SEL.navItem("writing"))).not.toHaveClass(/active/)

    await page.locator(SEL.navItem("rag")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("项目")
    await expect(page.locator(SEL.navItem("project"))).toHaveClass(/active/)
    await expect(page.locator(SEL.navItem("rag"))).not.toHaveClass(/active/)
  })

  test("后端连接状态显示", async ({ page }) => {
    await page.goto("/")
    await enterAuthor(page)

    const status = page.locator(SEL.topbarStatus)
    await expect(status).toContainText("已连接", { timeout: 10000 })
  })

  test("快捷键帮助弹窗", async ({ page }) => {
    await page.goto("/")
    await enterAuthor(page)

    await page.keyboard.press("?")
    await expect(page.locator(SEL.helpOverlay)).toBeVisible()
    await expect(page.locator(SEL.helpOverlay)).toContainText("快捷键帮助")

    await page.locator(SEL.helpClose).click()
    await expect(page.locator(SEL.helpOverlay)).toHaveClass(/hidden/)
  })

  test("命令栏聚焦与失焦", async ({ page }) => {
    await page.goto("/")
    await enterAuthor(page)

    await page.keyboard.press(":")
    const input = page.locator(SEL.commandInput)
    await expect(input).toBeFocused()

    await input.fill("help")
    await page.keyboard.press("Escape")
    await expect(input).not.toBeFocused()
  })

  test("错误日志徽标可在窄屏用键盘安全确认清空", async ({ page }) => {
    await page.route("**/debug/frontend-errors", (route) => route.fulfill({
      status: 204,
      contentType: "application/json",
      body: "{}",
    }))
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto("/")
    await page.evaluate(() => {
      for (let index = localStorage.length - 1; index >= 0; index -= 1) {
        const key = localStorage.key(index)
        if (key?.startsWith("_errorLog")) localStorage.removeItem(key)
      }
      window.errorLog.clear()
      window.appState.error = null
      window.appState.error = '<img src=x onerror="alert(1)">'
    })

    const badge = page.locator(SEL.errorLogBadge)
    await expect(badge).toHaveAttribute("aria-label", "打开错误日志，当前 1 条")
    await badge.focus()
    await page.keyboard.press("Enter")
    const panel = page.locator(SEL.errorLogPanel)
    const closeButton = panel.getByRole("button", { name: "关闭", exact: true })
    await expect(panel).toHaveAttribute("role", "dialog")
    await expect(closeButton).toBeFocused()
    await expect(panel.locator("img")).toHaveCount(0)
    await expectWithinViewport(closeButton)
    await expectNoPageOverflow(page)

    await page.keyboard.press("Escape")
    await expect(badge).toBeFocused()
    await page.keyboard.press("Space")
    await expect(closeButton).toBeFocused()

    const clearButton = panel.getByRole("button", { name: "清空", exact: true })
    await clearButton.click()
    const confirmation = panel.locator("#error-log-clear-confirmation")
    const confirmButton = confirmation.getByRole("button", { name: "确认清空", exact: true })
    await expect(confirmButton).toBeFocused()
    await expect.poll(() => page.evaluate(() => window.errorLog.getAll().length)).toBe(1)
    await page.keyboard.press("Escape")
    await expect(clearButton).toBeFocused()

    await clearButton.click()
    await confirmation.getByRole("button", { name: "确认清空", exact: true }).click()
    await expect(panel).toHaveCount(0)
    await expect(badge).toBeHidden()
    await expect(page.locator(SEL.workspace)).toBeFocused()
    await expectNoPageOverflow(page)
    await page.evaluate(() => window.errorLog.clear())
  })
})
