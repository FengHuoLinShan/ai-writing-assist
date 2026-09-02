import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { openProjectView } from "./helpers/workbench.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"
import { expectNoPageOverflow } from "./helpers/responsive.js"
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

    // 等待导入完成 toast 显示解析/保存章节数（实际文案不含"成功"）
    await expect(page.locator(SEL.toastContainer)).toContainText("共解析", { timeout: 15000 })
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存", { timeout: 15000 })

    // 导入成功后自动跳转到写作视图，章节树应出现导入的章节
    await expect(page.locator("#writing-tree-container")).toContainText("第 1 章", { timeout: 10000 })
    await expect(page.locator("#writing-tree-container")).toContainText("第 2 章", { timeout: 10000 })
    await expect(page.locator("#writing-tree-container")).toContainText("第 3 章", { timeout: 10000 })
  })

  test("抽屉复用已选择文件导入为新项目，取消后保留选择", async ({ page }) => {
    await page.locator(SEL.projectImportToggle).click()
    const filePath = path.join(__dirname, "helpers", "fixtures", "sample-novel.txt")
    await page.locator(SEL.projectImportFile).setInputFiles(filePath)
    await expect(page.getByLabel(/支持 txt、epub、html、htm，最大 50MB/)).toHaveAttribute(
      "accept",
      ".txt,.epub,.html,.htm",
    )

    let chooserCount = 0
    page.on("filechooser", () => { chooserCount += 1 })
    await page.locator(SEL.projectImportNewProject).click()

    await expect(page.locator(SEL.modalBody)).toContainText("sample-novel.txt")
    expect(chooserCount).toBe(0)
    await page.getByRole("button", { name: "取消" }).click()
    await expect(page.locator(SEL.modalOverlay)).toHaveClass(/hidden/)
    await expect.poll(() => page.locator(SEL.projectImportFile).evaluate((input) => input.files?.[0]?.name)).toBe("sample-novel.txt")

    await page.setViewportSize({ width: 390, height: 844 })
    await expectNoPageOverflow(page)
  })
})
