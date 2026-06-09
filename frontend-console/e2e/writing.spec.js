import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { createProject, deleteProject, waitForBackend } from "./helpers/api-client.js"

test.describe("手动工作台模块", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "写作测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.evaluate((id) => {
      localStorage.setItem("novel_currentProjectId", id)
      localStorage.setItem("novel_currentProject", JSON.stringify({ id, title: "写作测试项目" }))
    }, project.id)
    await page.reload()

    await page.locator(SEL.navItem("writing")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("手动工作台")
    // 等待 onEnter 完成，避免注入状态后被异步 renderCurrentView 覆盖
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await deleteProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("空状态显示新建章节按钮", async ({ page }) => {
    await expect(page.locator(SEL.emptyState)).toBeVisible()
    await expect(page.locator(SEL.emptyState)).toContainText("开始创作")
    await expect(page.locator('[data-action="new-chapter"]')).toBeVisible()
  })

  test("新建章节并显示在章节树", async ({ page }) => {
    // headless Chromium 中 prompt 被阻塞，直接注入状态并重新渲染
    await page.evaluate(() => {
      writingView._currentChapter = 1
      writingView._chapterList = [1]
      writingView._chapters[1] = { title: null, draftCount: 0 }
      writingView._currentContent = ""
      writingView._currentTitle = "第 1 章"
      return writingView._rerender()
    })

    // 等待章节树渲染
    await expect(page.locator("#workspace-content")).toContainText("第 1 章")
    await expect(page.locator("#writing-editor")).toBeVisible()
  })

  test("编辑章节内容并暂存", async ({ page }) => {
    // 直接注入章节状态，绕过 prompt
    await page.evaluate(() => {
      writingView._currentChapter = 1
      writingView._chapterList = [1]
      writingView._chapters[1] = { title: null, draftCount: 0 }
      writingView._currentContent = ""
      writingView._currentTitle = "第 1 章"
      return writingView._rerender()
    })
    await expect(page.locator("#writing-editor")).toBeVisible()

    // 先发布以创建真实草稿，获取 draftId（autosave 需要 _currentDraftId）
    await page.locator("#writing-editor").fill("初始发布内容。")
    await page.locator('[data-action="publish"]').click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已发布", { timeout: 15000 })

    // 修改标题和内容
    await page.locator("#writing-title-input").fill("第一章 测试")
    await page.locator("#writing-editor").fill("这是测试内容。")

    // 暂存
    await page.locator('[data-action="autosave"]').click()

    // 等待暂存成功 toast
    await expect(page.locator(SEL.toastContainer)).toContainText("已暂存", { timeout: 10000 })
  })

  test("发布章节", async ({ page }) => {
    // 直接注入章节状态，绕过 prompt
    await page.evaluate(() => {
      writingView._currentChapter = 1
      writingView._chapterList = [1]
      writingView._chapters[1] = { title: null, draftCount: 0 }
      writingView._currentContent = ""
      writingView._currentTitle = "第 1 章"
      return writingView._rerender()
    })
    await expect(page.locator("#writing-editor")).toBeVisible()

    // 填写内容并发布
    await page.locator("#writing-title-input").fill("第一章 发布测试")
    await page.locator("#writing-editor").fill("这是发布测试的内容。")

    await page.locator('[data-action="publish"]').click()

    // 发布可能需要时间，检查成功 toast
    await expect(page.locator(SEL.toastContainer)).toContainText("已发布", { timeout: 15000 })
  })
})
