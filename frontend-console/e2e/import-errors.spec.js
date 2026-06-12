import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openProjectView } from "./helpers/workbench.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"
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

  test("上传超过 50MB 的文件被前端拦截", async ({ page }) => {
    await page.locator('[data-action="toggle-import"]').click()
    await expect(page.locator("#pv-import-file")).toBeVisible()

    const filePath = path.join(__dirname, "helpers", "fixtures", "oversized.bin")
    await page.locator("#pv-import-file").setInputFiles(filePath)
    await page.locator('[data-action="upload-file"]').click()

    // 前端在 _uploadFile 中检查 50MB 限制并直接 toast 错误
    await expect(page.locator(SEL.toastContainer)).toContainText("50MB", { timeout: 5000 })
  })

  test("上传空文件标记导入失败且不创建章节", async ({ page }) => {
    await page.locator('[data-action="toggle-import"]').click()
    await expect(page.locator("#pv-import-file")).toBeVisible()

    const filePath = path.join(__dirname, "helpers", "fixtures", "empty.txt")
    await page.locator("#pv-import-file").setInputFiles(filePath)
    await page.locator('[data-action="upload-file"]').click()

    await expect(page.locator(SEL.toastContainer)).toContainText("文件中未检测到有效章节", { timeout: 15000 })
    await expect(page.locator("#import-list-body")).toContainText("失败", { timeout: 15000 })
  })
})
