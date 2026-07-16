/**
 * 深度导入真实异步 Worker 受理测试
 *
 * 前置条件：
 * - 后端 API 已启动
 * - 前端静态服务器已启动
 * - 数据库可用
 * - Worker 进程正在运行（cd backend && python run_worker.py，或 make dev）
 *
 * 注意：默认 Playwright webServer 只启动后端 API + 前端，不会启动 Worker。
 * 这个用例只在真实 Worker 环境中运行，不做 Mock。
 *
 * 运行方式：
 *   RUN_WORKER_E2E=1 npx playwright test deep-import-worker.spec.js --reporter=list
 */
import { test, expect } from "./fixtures.js"
import { openProjectView, openWorkbench } from "./helpers/workbench.js"
import {
  API_BASE,
  createProject,
  cleanupProject,
  waitForBackend,
  getTask,
} from "./helpers/api-client.js"

const TERMINAL_TASK_STATUSES = new Set(["done", "failed", "cancelled"])

test.skip(
  process.env.RUN_WORKER_E2E !== "1",
  "requires RUN_WORKER_E2E=1 and a running backend worker",
)

async function waitForTaskDone(taskId, novelId, timeoutMs = 180_000) {
  const deadline = Date.now() + timeoutMs
  let lastTask = null

  while (Date.now() < deadline) {
    lastTask = await getTask(taskId, novelId)
    if (TERMINAL_TASK_STATUSES.has(lastTask.status)) {
      return lastTask
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }

  throw new Error(
    `Task ${taskId} did not finish in time; last status=${lastTask?.status ?? "unknown"}; `
      + `progress=${lastTask?.progress ?? "unknown"}; `
      + `error=${lastTask?.error_message ?? "none"}; `
      + `result=${JSON.stringify(lastTask?.result ?? {})}`,
  )
}

test.describe("深度导入异步 Worker 受理", () => {
  let testProjectId = null
  let testProject = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "深度导入异步 Worker 测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id
    testProject = project

    await openProjectView(page, project)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
      testProject = null
    }
  })

  test("提交异步深度导入后，关闭页面并等待 worker 完成", async ({ page, context }) => {
    const uploadResult = await page.evaluate(async ({ apiBase, projectId }) => {
      const fileContent = [
        "第一章 起风",
        "",
        "青石镇的清晨有些冷，林昭在薄雾里推开了门。",
        "",
        "第二章 旧信",
        "",
        "信封里没有署名，只有一行字：今晚子时到桥下见。",
        "",
        "第三章 约定",
        "",
        "他把信折好，抬头看向窗外，风已经更急了。",
      ].join("\n")

      const formData = new FormData()
      formData.append("novel_id", projectId)
      formData.append(
        "file",
        new File([fileContent], "three-chapter-novel.txt", {
          type: "text/plain",
        }),
      )

      const uploadResp = await fetch(`${apiBase}/imports/upload`, {
        method: "POST",
        body: formData,
      })
      if (!uploadResp.ok) {
        const text = await uploadResp.text()
        throw new Error(`Upload failed (${uploadResp.status}): ${text}`)
      }

      return uploadResp.json()
    }, { apiBase: API_BASE, projectId: testProjectId })

    expect(uploadResult).toBeTruthy()

    const deepImportResponse = await page.evaluate(async ({ apiBase, projectId }) => {
      const deepResp = await fetch(`${apiBase}/imports/deep`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          novel_id: projectId,
          start_chapter: 1,
          end_chapter: 3,
          adoption_policy: "user_authorized_pipeline",
          authorization_confirmed: true,
        }),
      })
      if (!deepResp.ok) {
        const text = await deepResp.text()
        throw new Error(`Deep import submission failed (${deepResp.status}): ${text}`)
      }
      return deepResp.json()
    }, { apiBase: API_BASE, projectId: testProjectId })

    const { task_id: taskId } = await deepImportResponse
    expect(taskId).toBeTruthy()

    await page.evaluate(({ projectId, activeTaskId }) => {
      localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
        id: `${projectId}:deep_import:${activeTaskId}`,
        taskId: activeTaskId,
        workflowType: "deep_import",
        label: "深度导入",
        projectId,
        view: "writing",
        meta: {},
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      }]))
    }, { projectId: testProjectId, activeTaskId: taskId })

    await page.close()

    const task = await waitForTaskDone(taskId, testProjectId)

    expect(task.status).toBe("done")
    expect(task.error_message || "").toBe("")
    expect(task.result.phase).toBe("done")
    expect(task.result.completed_steps).toEqual(
      expect.arrayContaining([
        "scene_segmentation",
        "entity_extraction",
        "structure_analysis",
      ]),
    )

    const recoveryPage = await context.newPage()
    await openWorkbench(recoveryPage, testProject, "writing")
    await expect(
      recoveryPage.locator('[data-action="deep-import-map-next"]'),
    ).toBeVisible({ timeout: 15_000 })
    await expect(recoveryPage.locator("#writing-deep-import-bar-container")).toContainText(
      /一键创建地图|先审核 \d+ 个地点|查看地图收件箱/,
    )
  })
})
