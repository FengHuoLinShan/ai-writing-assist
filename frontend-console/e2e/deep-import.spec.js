import { test, expect } from "./fixtures.js"
import { chromium } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench, waitWritingReady } from "./helpers/workbench.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"
import { createPersistentBrowserProfile } from "./helpers/persistent-browser.js"
import path from "path"
import { fileURLToPath } from "url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))

test.describe("深度导入流水线", () => {
  let testProjectId = null
  let testProject = null

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
    testProject = project

    await openWorkbench(page, project, "writing")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
      testProject = null
    }
  })

  test("从真实入口提交后关闭并重启浏览器，可恢复运行进度", async () => {
    const browserProfile = await createPersistentBrowserProfile(chromium)
    let persistentContext = null
    try {
      persistentContext = await browserProfile.launch()
      const page = persistentContext.pages()[0] || await persistentContext.newPage()
      await openWorkbench(page, testProject, "writing")

    // Navigate to project view for file upload
    await page.evaluate(() => window.router.navigate("project"))
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })
    // Step 1: 在项目视图展开导入区域并上传文件
    await page.locator(SEL.projectImportToggle).click()
    await expect(page.locator(SEL.projectImportFile)).toBeVisible()

    const filePath = path.join(__dirname, "helpers", "fixtures", "sample-novel.txt")
    await page.locator(SEL.projectImportFile).setInputFiles(filePath)
    await page.locator(SEL.projectImportSubmit).click()

    // 等待导入完成 toast
    await expect(page.locator(SEL.toastContainer)).toContainText("导入完成", { timeout: 15000 })

    // Step 2: 上传流程会自动进入写作页；等待真实章节数据完成渲染。
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作", { timeout: 10000 })
    await waitWritingReady(page, { chapter: 1 })
    await expect(page.locator(SEL.writingChapterCount)).toHaveText("章节 · 共 3 章")
    await expect(
      page.locator(SEL.writingToolsMenu),
      "上传成功后应立即看到已提交章节和 AI 工具入口",
    ).toBeVisible()

    // Step 3: 上传完成后由用户在写作现场显式开始整理导入内容
    await page.locator(SEL.writingAiMenu).click()
    const deepImportButton = page.getByRole("button", { name: "完整整理" })
    await expect(deepImportButton).toBeVisible()
    await deepImportButton.click()
    const extractionDialog = page.getByRole("dialog", { name: "自动提取" })
    await expect(extractionDialog).toContainText("完整整理导入内容")

    // Step 4: Mock 后端执行，但保留真实 UI 提交和本地恢复凭据写入。
    const taskId = `mock-deep-import-${Date.now()}`
    await persistentContext.route("**/api/imports/deep", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ task_id: taskId }),
      })
    })

    const installTaskRoute = (context) => context.route(`**/api/tasks/${taskId}**`, async (route) => {
      expect(new URL(route.request().url()).searchParams.get("novel_id")).toBe(
        testProjectId,
      )
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: taskId,
          task_type: "deep_import",
          status: "running",
          progress: 0.35,
          result: {
            phase: "running",
            current_phase: "phase1b_enrichment",
            current_item: { completed: 2, total: 6 },
            message: "正在补全 Scene 字段",
          },
        }),
      })
    })
    await installTaskRoute(persistentContext)

    // Step 5: 在当前表单中确认授权并提交
    await extractionDialog.getByRole("button", { name: "确认并开始提取" }).click()

    // Step 6: 验证当前任务入口成功启动
    await expect(page.locator(SEL.toastContainer)).toContainText("整理导入内容已启动", { timeout: 10000 })
    await expect(page.locator(SEL.deepImportProgress)).toContainText("正在补全场景字段")
    await expect.poll(() => page.evaluate((expectedTaskId) => {
      const items = JSON.parse(localStorage.getItem("novel_active_workflows_v1") || "[]")
      return items.some((item) => item.taskId === expectedTaskId)
    }, taskId)).toBe(true)

    // Step 7: 关闭持久浏览器进程，再使用同一用户 profile 重启。
    await browserProfile.close()
    persistentContext = await browserProfile.launch()
    await installTaskRoute(persistentContext)
    const recoveryPage = persistentContext.pages()[0] || await persistentContext.newPage()
    await openWorkbench(recoveryPage, testProject, "writing")
    await expect(recoveryPage.locator(SEL.deepImportProgress)).toContainText(
      "正在补全场景字段",
      { timeout: 10000 },
    )
    await expect(recoveryPage.locator(SEL.deepImportProgress)).toContainText("35%")
    } finally {
      await browserProfile.dispose()
    }
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
    await expect(page.locator(SEL.viewTitle)).toHaveText("作品档案", { timeout: 10000 })

    // 导航回写作视图
    await page.evaluate(async () => {
      await window.router.navigate("writing")
    })
    await page.waitForFunction(() => !state.loading, { timeout: 15000 })
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作", { timeout: 10000 })

    // 验证当前 stage task 通过 active workflow contract 恢复显示
    await expect(page.locator("#writing-deep-import-bar-container")).toContainText(
      "第 2/3 步：实体提取",
      { timeout: 10000 },
    )
    await expect(page.locator(SEL.deepImportProgress)).toContainText("世界对象与关系提取")
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
          available_actions: ["cancel"],
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
      "任务状态暂不可用",
    )
    await expect(page.locator("#writing-deep-import-bar-container")).toContainText(
      "世界对象与关系提取",
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
          available_actions: ["cancel"],
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
    const compactSummary = bar.locator("summary.workflow-progress__compact")
    await expect(compactSummary).toBeVisible()
    await compactSummary.click()
    const cancelButton = bar.getByRole("button", { name: "取消任务" })
    await expect(cancelButton).toBeVisible()
    await cancelButton.click()
    const confirmDialog = page.getByRole("dialog", { name: "确认操作" })
    await expect(confirmDialog).toContainText("确认取消当前任务")
    await confirmDialog.getByRole("button", { name: "确认取消" }).click()

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

    await bar.getByRole("button", { name: "关闭" }).click()
    expect(await page.evaluate(() => (
      JSON.parse(localStorage.getItem("novel_active_workflows_v1") || "[]").length
    ))).toBe(0)
  })

  test("降级完成任务刷新后主动展开作者提示", async ({ page }) => {
    const mockTaskId = `mock-degraded-task-${Date.now()}`
    await page.context().route(`**/api/tasks/${mockTaskId}**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: mockTaskId,
          task_type: "scene_auto_extraction",
          status: "done",
          progress: 1,
          result: {
            phase: "done",
            message: "Scene 提取已完成",
            quality_status: "partial",
            degraded: true,
            degraded_reason: "phase1b_422_rate_exceeded",
            phase1a_fallback: true,
            phase_errors: [{
              phase: "phase1b_enrichment",
              error_kind: "schema_failure",
              message: "部分 Scene 已使用可复核结果继续导入",
            }],
          },
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

    const bar = page.locator(SEL.deepImportProgress)
    await expect(bar.locator("details.workflow-progress")).toHaveAttribute("open", "")
    await expect(bar).toContainText("部分降级完成")
    await expect(bar).toContainText("部分步骤已降级完成，请检查需要人工处理的结果")
    await expect(bar).toContainText("自动整理失败，已使用质量补强结果继续导入")
    await expect(bar).not.toContainText("phase1b_422_rate_exceeded")
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
    await expect(page.getByRole("button", { name: "新建章节", exact: true })).toBeVisible()
    await expect(page.getByRole("button", { name: "从正文整理场景" })).not.toBeVisible()
  })
})
