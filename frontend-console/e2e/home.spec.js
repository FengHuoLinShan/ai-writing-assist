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

  test("Enter lets focused controls activate while workspace keeps selection", async ({ page }) => {
    await page.goto("/")
    await enterAuthor(page)
    await expect(page.locator("#project-catalog-title")).toBeVisible()
    const installSelectHook = () => page.evaluate(() => {
      window.__shellSelectShortcutCount = 0
      document.querySelector('#workspace-content [data-action="select"]')?.remove()
      const button = document.createElement("button")
      button.hidden = true
      button.dataset.action = "select"
      button.addEventListener("click", () => { window.__shellSelectShortcutCount += 1 })
      document.querySelector("#workspace-content")?.appendChild(button)
    })
    await installSelectHook()
    const account = page.getByRole("button", { name: "账户菜单" })
    await account.focus()
    await page.keyboard.press("Enter")
    await expect(page.locator(".account-dialog")).toBeVisible()
    await expect.poll(() => page.evaluate(() => window.__shellSelectShortcutCount)).toBe(0)
    await page.locator(".account-close").click()
    await expect(page.locator(".account-dialog")).toBeHidden()
    await installSelectHook()
    await page.locator(SEL.workspace).focus()
    await expect(page.locator(SEL.workspace)).toBeFocused()
    await page.keyboard.press("Enter")
    await expect.poll(() => page.evaluate(() => window.__shellSelectShortcutCount)).toBe(1)
  })

  test("作者可从命令栏键盘浏览建议并恢复原焦点", async ({ page }) => {
    await page.goto("/")
    await enterAuthor(page)

    const trigger = page.getByRole("button", { name: /帮助/ })
    const input = page.locator(SEL.commandInput)
    await trigger.focus()
    await page.keyboard.press(":")
    await expect(input).toBeFocused()
    await page.keyboard.type("he")
    await expect(input).toHaveValue(":he")
    await expect(input).not.toHaveAttribute("aria-activedescendant")
    await page.keyboard.press("ArrowDown")
    await expect(input).toBeFocused()
    await expect(input).toHaveAttribute("aria-activedescendant", "command-suggestion-0")
    await expect(page.locator("#command-suggestion-0")).toHaveAttribute("aria-selected", "true")
    await page.keyboard.press("Enter")
    await expect(page.locator(SEL.modalTitle)).toHaveText("命令帮助")
    await page.locator(SEL.modalClose).click()

    await trigger.focus()
    await page.keyboard.press(":")
    await expect(input).toBeFocused()
    await page.keyboard.press("Escape")
    await expect(trigger).toBeFocused()
  })

  test("作者可用键盘选择主题而不在导航时切换", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("novel_theme", "minimal"))
    await page.goto("/")
    await enterAuthor(page)

    const toggle = page.locator(SEL.themeToggle)
    const minimal = page.locator(SEL.themeOption("minimal"))
    const warm = page.locator(SEL.themeOption("warm"))
    await toggle.focus()
    await page.keyboard.press("Enter")
    await expect(minimal).toBeFocused()
    await page.keyboard.press("ArrowDown")
    await expect(warm).toBeFocused()
    await expect(page.locator("html")).toHaveAttribute("data-theme", "minimal")
    await page.keyboard.press("Enter")
    await expect(page.locator("html")).toHaveAttribute("data-theme", "warm")
    await expect(toggle).toBeFocused()

    await page.keyboard.press("Space")
    await expect(warm).toBeFocused()
    await page.keyboard.press("ArrowDown")
    await expect(page.locator(SEL.themeOption("dark"))).toBeFocused()
    await page.keyboard.press("Space")
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark")
    await expect(toggle).toBeFocused()

    await page.keyboard.press("Space")
    await expect(page.locator(SEL.themeOption("dark"))).toBeFocused()
    await page.keyboard.press("Escape")
    await expect(toggle).toBeFocused()
    await expect(toggle).toHaveAttribute("aria-expanded", "false")
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark")
    await page.evaluate(() => localStorage.removeItem("novel_theme"))
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
