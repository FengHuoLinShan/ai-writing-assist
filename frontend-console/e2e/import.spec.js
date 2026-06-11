import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"
import path from "path"
import { fileURLToPath } from "url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))

test.describe("导入模块", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "导入测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.evaluate((id) => {
      localStorage.setItem("novel_currentProjectId", id)
      localStorage.setItem("novel_currentProject", JSON.stringify({ id, title: "导入测试项目" }))
    }, project.id)
    await page.reload()

    await expect(page.locator(SEL.viewTitle)).toHaveText("项目")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("导入文件到当前项目", async ({ page }) => {
    // 展开导入区域
    await page.locator('[data-action="toggle-import"]').click()
    await expect(page.locator("#pv-import-file")).toBeVisible()

    // 设置文件
    const filePath = path.join(__dirname, "helpers", "fixtures", "sample-novel.txt")
    await page.locator("#pv-import-file").setInputFiles(filePath)

    // 点击上传
    await page.locator('[data-action="upload-file"]').click()

    // 等待导入完成（成功或失败 toast）
    await expect(page.locator(SEL.toastContainer)).toContainText("导入", { timeout: 15000 })
  })
})
