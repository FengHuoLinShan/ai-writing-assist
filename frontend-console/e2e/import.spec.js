import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openProjectView } from "./helpers/workbench.js"
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

    await openProjectView(page, project)
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

    // 等待导入完成 toast 显示解析/成功章节数
    await expect(page.locator(SEL.toastContainer)).toContainText("共解析", { timeout: 15000 })
    await expect(page.locator(SEL.toastContainer)).toContainText("成功", { timeout: 15000 })

    // 导入成功后自动跳转到写作视图，章节树应出现导入的章节
    await expect(page.locator("#writing-tree-container")).toContainText("第 1 章", { timeout: 10000 })
    await expect(page.locator("#writing-tree-container")).toContainText("第 2 章", { timeout: 10000 })
    await expect(page.locator("#writing-tree-container")).toContainText("第 3 章", { timeout: 10000 })
  })
})
