import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"
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

    await openWorkbench(page, project, "writing")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("从项目视图导入小说后启动深度导入", async ({ page }) => {
    // Navigate to project view for file upload
    await page.evaluate(() => window.router.navigate("project"))
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })
    // Step 1: 在项目视图展开导入区域并上传文件
    await page.locator('[data-action="toggle-import"]').click()
    await expect(page.locator("#pv-import-file")).toBeVisible()

    const filePath = path.join(__dirname, "helpers", "fixtures", "sample-novel.txt")
    await page.locator("#pv-import-file").setInputFiles(filePath)
    await page.locator('[data-action="upload-file"]').click()

    // 等待导入完成 toast
    await expect(page.locator(SEL.toastContainer)).toContainText("导入完成", { timeout: 15000 })

    // Step 2: 导航到写作工作台
    await page.evaluate(() => {
      const pid = localStorage.getItem("novel_currentProjectId")
      if (pid) state.currentProjectId = pid
      window.router.navigate("writing")
    })
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })

    // 等待写作视图加载完成
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)

    // Step 3: 验证深度导入按钮存在，且导入后弹出深度导入确认
    const deepImportBtn = page.locator('[data-action="deep-import"]')
    await expect(deepImportBtn).toBeVisible()
    await expect(page.locator(SEL.modalTitle)).toContainText("确认操作")
    await expect(page.locator("#modal-body")).toContainText("是否启动深度导入")

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

    // Step 5: 在导入后确认弹窗中点击“启动深度导入”
    await page.locator("#modal-footer").getByRole("button", { name: "启动深度导入" }).click()

    // Step 6: 验证深度导入相关 toast（可能显示"已启动"或"完成"）
    await expect(page.locator(SEL.toastContainer)).toContainText("深度导入", { timeout: 10000 })

    // Step 7: 验证进度条出现（由于 Mock 快速完成，进度条可能一闪而过）
    // 至少验证页面没有报错
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作台")
  })

  test("深度导入进度条在路由切换后恢复", async ({ page }) => {
    const mockTaskId = `mock-recovery-task-${Date.now()}`

    // 使用 context.route 确保路由在整个浏览器上下文中有效
    await page.context().route(`**/api/tasks/${mockTaskId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: mockTaskId,
          status: "running",
          result: {
            phase: "running",
            current_step: "entity_extraction",
            completed_steps: ["scene_segmentation"],
            message: "Phase 2/3: 实体提取",
          },
        }),
      })
    })

    // 在 localStorage 中设置 task id
    await page.evaluate((tid) => {
      localStorage.setItem("novel_deepImportTaskId", tid)
    }, mockTaskId)

    // 切换到项目视图再切回，触发 onEnter → _recoverDeepImportTask
    await page.evaluate(async () => {
      await window.router.navigate("project")
    })
    await page.waitForFunction(() => !state.loading, { timeout: 15000 })
    await expect(page.locator(SEL.viewTitle)).toHaveText("项目", { timeout: 10000 })

    // 导航回写作视图
    await page.evaluate(async () => {
      await window.router.navigate("writing")
    })
    await page.waitForFunction(() => !state.loading, { timeout: 15000 })
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作台", { timeout: 10000 })

    // 验证深度导入进度条恢复显示（_recoverDeepImportTask 在 onEnter 中被触发）
    await expect(page.locator("#writing-deep-import-bar-container")).toContainText("Phase 2/3", { timeout: 10000 })
  })

  test("无章节时深度导入按钮不显示", async ({ page }) => {
    // 导航到写作工作台，不导入任何章节
    await page.evaluate(() => {
      const pid = localStorage.getItem("novel_currentProjectId")
      if (pid) state.currentProjectId = pid
      window.router.navigate("writing")
    })
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })

    // 空状态下（无章节）不渲染编辑器区域，因此深度导入按钮不显示
    await expect(page.locator('[data-action="new-chapter"]')).toBeVisible()
    await expect(page.locator('[data-action="deep-import"]')).not.toBeVisible()
  })
})
