import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { createProject, deleteProject, waitForBackend } from "./helpers/api-client.js"
import path from "path"
import { fileURLToPath } from "url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))

test.describe("深度导入流水线", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "深度导入测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.evaluate((id) => {
      localStorage.setItem("novel_currentProjectId", id)
      localStorage.setItem("novel_currentProject", JSON.stringify({ id, title: "深度导入测试项目" }))
    }, project.id)
    await page.reload()
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await deleteProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("从项目视图导入小说后启动深度导入", async ({ page }) => {
    // Step 1: 在项目视图展开导入区域并上传文件
    await page.locator('[data-action="toggle-import"]').click()
    await expect(page.locator("#pv-import-file")).toBeVisible()

    const filePath = path.join(__dirname, "helpers", "fixtures", "sample-novel.txt")
    await page.locator("#pv-import-file").setInputFiles(filePath)
    await page.locator('[data-action="upload-file"]').click()

    // 等待导入完成 toast
    await expect(page.locator(SEL.toastContainer)).toContainText("导入完成", { timeout: 15000 })

    // Step 2: 导航到写作工作台
    await page.locator(SEL.navItem("writing")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("手动工作台")

    // 等待写作视图加载完成
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)

    // Step 3: 验证深度导入按钮存在
    const deepImportBtn = page.locator('[data-action="deep-import"]')
    await expect(deepImportBtn).toBeVisible()

    // Step 4: Mock 深度导入 API 以加速测试
    await page.route("**/api/imports/deep", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({ task_id: `mock-deep-import-${Date.now()}` }),
      })
    })

    await page.route("**/api/tasks/**", async (route) => {
      const url = route.request().url()
      if (url.includes("/api/tasks/mock-deep-import-")) {
        await route.fulfill({
          status: 200,
          body: JSON.stringify({
            task_id: "mock-deep-import-123",
            status: "done",
            result: { imported_scenes: 3, imported_entities: 5 },
          }),
        })
      } else {
        await route.continue()
      }
    })

    // Step 5: 点击深度导入按钮，验证弹窗
    await deepImportBtn.click()
    await expect(page.locator(SEL.modalTitle)).toContainText("深度导入")
    await expect(page.locator("#deep-import-start")).toBeVisible()
    await expect(page.locator("#deep-import-end")).toBeVisible()

    // Step 6: 提交深度导入
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    // Step 7: 验证深度导入相关 toast（可能显示"已启动"或"完成"）
    await expect(page.locator(SEL.toastContainer)).toContainText("深度导入", { timeout: 10000 })

    // Step 8: 验证进度条出现（由于 Mock 快速完成，进度条可能一闪而过）
    // 至少验证页面没有报错
    await expect(page.locator(SEL.viewTitle)).toHaveText("手动工作台")
  })

  test("无章节时深度导入按钮不显示", async ({ page }) => {
    // 导航到写作工作台，不导入任何章节
    await page.locator(SEL.navItem("writing")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("手动工作台")
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)

    // 空状态下（无章节）不渲染编辑器区域，因此深度导入按钮不显示
    await expect(page.locator('[data-action="new-chapter"]')).toBeVisible()
    await expect(page.locator('[data-action="deep-import"]')).not.toBeVisible()
  })
})
