import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { openProjectView } from "./helpers/workbench.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"
import { expectNoPageOverflow } from "./helpers/responsive.js"
import { copyFile, mkdir, rm } from "fs/promises"
import path from "path"
import { fileURLToPath } from "url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))

test.describe("导入异常流", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "导入异常测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openProjectView(page, project)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("上传不支持的文件格式提示错误", async ({ page }) => {
    await page.locator('[data-action="toggle-import"]').click()
    await expect(page.locator("#pv-import-file")).toBeVisible()

    const filePath = path.join(__dirname, "helpers", "fixtures", "test.pdf")
    await page.locator("#pv-import-file").setInputFiles(filePath)
    await page.locator('[data-action="upload-file"]').click()

    // 后端返回 400 "不支持的文件类型"
    await expect(page.locator(SEL.toastContainer)).toContainText("不支持", { timeout: 15000 })
  })

  test("上传超过 50MB 的文件被前端拦截", async ({ page }, testInfo) => {
    await page.locator('[data-action="toggle-import"]').click()
    await expect(page.locator("#pv-import-file")).toBeVisible()

    const temporaryFilePath = testInfo.outputPath("oversized.txt")
    await mkdir(path.dirname(temporaryFilePath), { recursive: true })
    try {
      await copyFile(path.join(__dirname, "helpers", "fixtures", "oversized.bin"), temporaryFilePath)
      await page.locator("#pv-import-file").setInputFiles(temporaryFilePath)
      await page.locator('[data-action="upload-file"]').click()

      // 前端在 _uploadFile 中检查 50MB 限制并直接 toast 错误
      await expect(page.locator(SEL.toastContainer)).toContainText("50MB", { timeout: 5000 })
    } finally {
      await rm(temporaryFilePath, { force: true })
    }
  })

  test("导入记录首次加载失败后可安全重试", async ({ page }) => {
    let importListRequests = 0
    await page.route("**/api/imports?**", async (route) => {
      importListRequests += 1
      if (importListRequests === 1) {
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ detail: "import-history-diagnostic-marker" }),
        })
        return
      }
      await route.fallback()
    })

    await page.locator(SEL.projectImportToggle).click()
    await expect(page.getByRole("alert")).toContainText("导入记录暂时无法加载，请重试。")
    await expect(page.getByRole("alert")).not.toContainText("import-history-diagnostic-marker")
    await expect(page.locator(SEL.projectImportHistory)).not.toContainText("暂无导入记录。")

    await expect(page.locator(SEL.projectImportHistoryRetry)).toHaveText("重试")
    await page.locator(SEL.projectImportHistoryRetry).click()
    await expect(page.locator(SEL.projectImportHistory)).toContainText("暂无导入记录。")
    await expect(page.locator(SEL.projectImportHistory)).not.toContainText("import-history-diagnostic-marker")
  })

  test("上传空文件标记导入失败且不创建章节", async ({ page }) => {
    await page.locator('[data-action="toggle-import"]').click()
    await expect(page.locator("#pv-import-file")).toBeVisible()

    const longFileName = `${"unbroken-import-filename-".repeat(8)}.txt`
    await page.locator("#pv-import-file").setInputFiles({
      name: longFileName,
      mimeType: "text/plain",
      buffer: Buffer.from(""),
    })
    await page.locator('[data-action="upload-file"]').click()

    await expect(page.locator(SEL.toastContainer)).toContainText("文件中未检测到有效章节", { timeout: 15000 })
    await expect(page.locator("#import-list-body")).toContainText("失败", { timeout: 15000 })
    await expect(page.locator("#import-list-body")).toContainText(longFileName)
    await expect(page.locator("#import-list-body")).toContainText("失败原因：文件中未检测到有效章节")

    await page.setViewportSize({ width: 390, height: 844 })
    await expect(page.locator("#import-list-body")).toContainText(longFileName)
    await expect(page.locator("#import-list-body")).toContainText("失败原因：文件中未检测到有效章节")
    await expectNoPageOverflow(page)
  })
})
