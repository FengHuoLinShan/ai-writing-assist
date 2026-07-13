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

    // Step 3: 上传完成后由用户从受支持入口显式启动场景自动提取
    await page.locator("details.writing-tools-menu > summary").click()
    const sceneExtractionBtn = page.locator(
      '[data-action="auto-extract-stage"][data-stage="scenes"]',
    )
    await expect(sceneExtractionBtn).toBeVisible()
    await sceneExtractionBtn.click()
    await expect(page.locator(SEL.modalTitle)).toContainText("场景（scene）自动提取")

    // Step 4: Mock 深度导入 API 以加速测试
    await page.route("**/api/imports/stages/scenes", async (route) => {
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

    // Step 5: 在当前表单中确认授权并提交
    await page.locator("#modal-footer").getByRole("button", { name: "确认并开始提取" }).click()

    // Step 6: 验证当前任务入口成功启动
    await expect(page.locator(SEL.toastContainer)).toContainText("自动提取已启动", { timeout: 10000 })

    // Step 7: 验证进度条出现（由于 Mock 快速完成，进度条可能一闪而过）
    // 至少验证页面没有报错
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作台")
  })

  test("场景自动提取进度在路由切换后恢复", async ({ page }) => {
    const mockTaskId = `mock-recovery-task-${Date.now()}`

    // 使用 context.route 确保路由在整个浏览器上下文中有效
    await page.context().route(`**/api/tasks/${mockTaskId}**`, async (route) => {
      expect(new URL(route.request().url()).searchParams.get("novel_id")).toBe(
        testProjectId,
      )
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: mockTaskId,
          task_type: "scene_auto_extraction",
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

    // 通过当前 active workflow contract 恢复 task
    await page.evaluate(({ tid, projectId }) => {
      localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
        id: `${projectId}:scene_auto_extraction:${tid}`,
        taskId: tid,
        workflowType: "scene_auto_extraction",
        projectId,
        view: "writing",
      }]))
    }, { tid: mockTaskId, projectId: testProjectId })

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

    // 验证当前 stage task 通过 active workflow contract 恢复显示
    await expect(page.locator("#writing-deep-import-bar-container")).toContainText(
      "Phase: entity_extraction",
      { timeout: 10000 },
    )
  })

  test("刷新恢复遇到 503 会保留记录并退避重试", async ({ page }) => {
    const mockTaskId = `mock-transient-task-${Date.now()}`
    let queryCount = 0
    await page.context().route(`**/api/tasks/${mockTaskId}**`, async (route) => {
      expect(new URL(route.request().url()).searchParams.get("novel_id")).toBe(
        testProjectId,
      )
      queryCount += 1
      if (queryCount === 1) {
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ detail: "temporary unavailable" }),
        })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: mockTaskId,
          task_type: "scene_auto_extraction",
          status: "running",
          progress: 0.2,
          result: { phase: "running", current_step: "entity_extraction" },
        }),
      })
    })
    await page.evaluate(({ tid, projectId }) => {
      localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
        id: `${projectId}:scene_auto_extraction:${tid}`,
        taskId: tid,
        workflowType: "scene_auto_extraction",
        projectId,
        view: "writing",
      }]))
    }, { tid: mockTaskId, projectId: testProjectId })

    await page.evaluate(() => window.router.navigate("project"))
    await page.waitForFunction(() => !state.loading)
    await page.evaluate(() => window.router.navigate("writing"))
    await page.waitForFunction(() => !state.loading)

    await expect(page.locator("#writing-deep-import-bar-container")).toContainText(
      "任务状态查询暂时不可用",
    )
    await expect(page.locator("#writing-deep-import-bar-container")).toContainText(
      "Phase: entity_extraction",
      { timeout: 10000 },
    )
    const retained = await page.evaluate(() => (
      JSON.parse(localStorage.getItem("novel_active_workflows_v1") || "[]")
    ))
    expect(retained).toHaveLength(1)
  })

  test("运行中任务经二次确认后取消", async ({ page }) => {
    const mockTaskId = `mock-cancel-task-${Date.now()}`
    let cancelRequestSeen = false
    await page.context().route(`**/api/tasks/${mockTaskId}**`, async (route) => {
      const request = route.request()
      expect(new URL(request.url()).searchParams.get("novel_id")).toBe(testProjectId)
      if (request.method() === "POST" && request.url().includes("/cancel")) {
        cancelRequestSeen = true
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            task_id: mockTaskId,
            status: "cancelled",
            cancelled: true,
          }),
        })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: mockTaskId,
          task_type: "scene_auto_extraction",
          status: "running",
          progress: 0.2,
          result: { phase: "running", current_step: "entity_extraction" },
        }),
      })
    })
    await page.evaluate(({ tid, projectId }) => {
      localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
        id: `${projectId}:scene_auto_extraction:${tid}`,
        taskId: tid,
        workflowType: "scene_auto_extraction",
        projectId,
        view: "writing",
      }]))
    }, { tid: mockTaskId, projectId: testProjectId })

    await page.evaluate(() => window.router.navigate("project"))
    await page.waitForFunction(() => !state.loading)
    await page.evaluate(() => window.router.navigate("writing"))
    await page.waitForFunction(() => !state.loading)

    const bar = page.locator("#writing-deep-import-bar-container")
    const progressSummary = bar.locator(".workflow-progress__compact")
    await expect(progressSummary).toBeVisible()
    await progressSummary.click()
    await expect(bar.locator('[data-action="cancel-deep-import"]')).toBeVisible()
    await bar.locator('[data-action="cancel-deep-import"]').click()
    await expect(page.locator(SEL.modalTitle)).toContainText("确认")
    await page.locator("#modal-footer").getByRole("button", { name: "确认取消" }).click()

    await expect(bar).toContainText("已取消")
    expect(cancelRequestSeen).toBe(true)
    expect(await page.evaluate(() => (
      JSON.parse(localStorage.getItem("novel_active_workflows_v1") || "[]").length
    ))).toBe(1)
  })

  test("失败任务刷新后保留，直到用户关闭", async ({ page }) => {
    const mockTaskId = `mock-failed-task-${Date.now()}`
    await page.context().route(`**/api/tasks/${mockTaskId}**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: mockTaskId,
          task_type: "scene_auto_extraction",
          status: "failed",
          progress: 0.3,
          error_message: "Project LLM API key is not configured",
          result: { phase: "failed", message: "场景自动提取失败" },
        }),
      })
    })
    await page.evaluate(({ tid, projectId }) => {
      localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
        id: `${projectId}:scene_auto_extraction:${tid}`,
        taskId: tid,
        workflowType: "scene_auto_extraction",
        projectId,
        view: "writing",
      }]))
    }, { tid: mockTaskId, projectId: testProjectId })

    await page.evaluate(() => window.router.navigate("project"))
    await page.waitForFunction(() => !state.loading)
    await page.evaluate(() => window.router.navigate("writing"))
    await page.waitForFunction(() => !state.loading)

    const bar = page.locator("#writing-deep-import-bar-container")
    await expect(bar).toContainText("失败")
    await expect(bar).toContainText("30%")
    expect(await page.evaluate(() => (
      JSON.parse(localStorage.getItem("novel_active_workflows_v1") || "[]").length
    ))).toBe(1)

    await bar.locator('[data-action="dismiss-deep-import"]').click()
    expect(await page.evaluate(() => (
      JSON.parse(localStorage.getItem("novel_active_workflows_v1") || "[]").length
    ))).toBe(0)
  })

  test("无章节时场景自动提取入口不显示", async ({ page }) => {
    // 导航到写作工作台，不导入任何章节
    await page.evaluate(() => {
      const pid = localStorage.getItem("novel_currentProjectId")
      if (pid) state.currentProjectId = pid
      window.router.navigate("writing")
    })
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })

    // 空状态下（无章节）不渲染编辑器区域，因此深度导入按钮不显示
    await expect(page.locator('[data-action="new-chapter"]')).toBeVisible()
    await expect(
      page.locator('[data-action="auto-extract-stage"][data-stage="scenes"]'),
    ).not.toBeVisible()
  })
})
