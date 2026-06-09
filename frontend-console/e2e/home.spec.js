import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { waitForBackend } from "./helpers/api-client.js"

test.describe("首页与导航", () => {
  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test("应用加载并显示项目视图", async ({ page }) => {
    await page.goto("/")

    await expect(page.locator(SEL.topbarTitle)).toContainText("小说结构化创作控制台")
    await expect(page.locator(SEL.sidebar)).toBeVisible()
    await expect(page.locator(SEL.workspace)).toBeVisible()
    await expect(page.locator(SEL.viewTitle)).toHaveText("项目")
  })

  test("侧边栏导航项可见", async ({ page }) => {
    await page.goto("/")

    const navItems = ["project", "world", "writing", "rag", "context", "generate"]
    for (const item of navItems) {
      await expect(page.locator(SEL.navItem(item))).toBeVisible()
    }
  })

  test("点击导航切换视图", async ({ page }) => {
    await page.goto("/")

    await page.locator(SEL.navItem("world")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("世界对象")
    await expect(page.locator(SEL.navItem("world"))).toHaveClass(/active/)

    await page.locator(SEL.navItem("writing")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("手动工作台")
    await expect(page.locator(SEL.navItem("writing"))).toHaveClass(/active/)

    await page.locator(SEL.navItem("rag")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("RAG 检索")
  })

  test("后端连接状态显示", async ({ page }) => {
    await page.goto("/")
    await page.waitForTimeout(2000)

    const status = page.locator(SEL.topbarStatus)
    await expect(status).toContainText("已连接")
  })

  test("快捷键帮助弹窗", async ({ page }) => {
    await page.goto("/")

    await page.keyboard.press("?")
    await expect(page.locator(SEL.helpOverlay)).toBeVisible()
    await expect(page.locator(SEL.helpOverlay)).toContainText("快捷键帮助")

    await page.locator(SEL.helpClose).click()
    await expect(page.locator(SEL.helpOverlay)).toHaveClass(/hidden/)
  })

  test("命令栏聚焦与失焦", async ({ page }) => {
    await page.goto("/")

    await page.keyboard.press(":")
    const input = page.locator(SEL.commandInput)
    await expect(input).toBeFocused()

    await input.fill("help")
    await page.keyboard.press("Escape")
    await expect(input).not.toBeFocused()
  })
})
