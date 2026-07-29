/**
 * 深度导入真实异步 Worker 恢复测试
 *
 * 前置条件：
 * - 专用 PostgreSQL E2E 数据库可用
 * - WORKER_E2E_LLM_API_KEY 与 LLM_SETTINGS_ENCRYPTION_KEY 已配置
 *
 * playwright.worker.config.js 会依次启动 API、前端和隔离 Worker；
 * LLM provider 不做 Mock，Worker 必须输出 readiness 日志后才开始测试。
 *
 * 运行方式：
 *   DATABASE_URL='<dedicated-postgresql-url>' \
 *   WORKER_E2E_LLM_API_KEY='<provider-key>' \
 *   LLM_SETTINGS_ENCRYPTION_KEY='<shared-encryption-key>' \
 *   npm run test:e2e:worker -- --reporter=list
 */
import { chromium, expect, test } from "@playwright/test"
import path from "node:path"
import { fileURLToPath } from "node:url"

import { SEL } from "./helpers/selectors.js"
import { openProjectView, openWorkbench, waitWritingReady } from "./helpers/workbench.js"
import {
  clearAccountLLMProvider,
  cleanupProjectStrict,
  connectAccountLLMProvider,
  createProject,
  getTask,
  waitForBackend,
} from "./helpers/api-client.js"
import { createPersistentBrowserProfile } from "./helpers/persistent-browser.js"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const TERMINAL_TASK_STATUSES = new Set(["done", "failed", "cancelled"])

function timeoutFromEnv(name, fallback, minimum = 1_000) {
  const value = Number(process.env[name] || fallback)
  if (!Number.isFinite(value) || value < minimum) {
    throw new Error(`${name} must be a finite value >= ${minimum}`)
  }
  return value
}

const TASK_TIMEOUT_MS = timeoutFromEnv("WORKER_E2E_TASK_TIMEOUT_MS", 2_400_000, 60_000)
const CLOSED_BROWSER_ADVANCE_TIMEOUT_MS = timeoutFromEnv(
  "WORKER_E2E_CLOSED_ADVANCE_TIMEOUT_MS",
  180_000,
  10_000,
)

test.skip(
  process.env.RUN_WORKER_E2E !== "1"
    || !process.env.WORKER_E2E_LLM_API_KEY
    || !process.env.LLM_SETTINGS_ENCRYPTION_KEY,
  "requires RUN_WORKER_E2E=1, WORKER_E2E_LLM_API_KEY, and LLM_SETTINGS_ENCRYPTION_KEY",
)

function taskProgressMarker(task = {}) {
  return JSON.stringify({
    status: task.status,
    progress: task.progress,
    updated_at: task.updated_at,
    heartbeat_at: task.heartbeat_at,
    current_phase: task.result?.current_phase,
    current_operation: task.result?.current_operation,
    current_item: task.result?.current_item,
  })
}

async function waitForTaskAdvance(taskId, novelId, initialTask, timeoutMs) {
  const initialMarker = taskProgressMarker(initialTask)
  const deadline = Date.now() + timeoutMs
  let lastTask = initialTask

  while (Date.now() < deadline) {
    lastTask = await getTask(taskId, novelId)
    if (
      TERMINAL_TASK_STATUSES.has(lastTask.status)
      || taskProgressMarker(lastTask) !== initialMarker
    ) {
      return lastTask
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }

  throw new Error(
    `Task ${taskId} did not advance while the browser was closed; `
      + `last status=${lastTask?.status ?? "unknown"}; `
      + `progress=${lastTask?.progress ?? "unknown"}`,
  )
}

async function waitForTaskDone(taskId, novelId, timeoutMs = TASK_TIMEOUT_MS) {
  const deadline = Date.now() + timeoutMs
  let lastTask = null

  while (Date.now() < deadline) {
    lastTask = await getTask(taskId, novelId)
    if (TERMINAL_TASK_STATUSES.has(lastTask.status)) return lastTask
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
  let accountConnectionTouched = false

  test.beforeAll(async () => {
    await waitForBackend(60_000)
  })

  test.beforeEach(async () => {
    const project = await createProject({
      title: "深度导入异步 Worker 测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id
    testProject = project

    await connectAccountLLMProvider(
      "deepseek",
      process.env.WORKER_E2E_LLM_API_KEY,
    )
    accountConnectionTouched = true
  })

  test.afterEach(async () => {
    const projectId = testProjectId
    const shouldClearConnection = accountConnectionTouched
    testProjectId = null
    testProject = null
    accountConnectionTouched = false

    try {
      if (shouldClearConnection) await clearAccountLLMProvider("deepseek")
    } finally {
      if (projectId) await cleanupProjectStrict(projectId)
    }
  })

  test("真实 UI 提交后关闭浏览器，worker 推进并在两次重开后保留终态", async () => {
    const browserProfile = await createPersistentBrowserProfile(chromium)
    let persistentContext = null

    try {
      persistentContext = await browserProfile.launch()
      const page = persistentContext.pages()[0] || await persistentContext.newPage()
      await openProjectView(page, testProject)

      await page.locator(SEL.projectImportToggle).click()
      await page.locator(SEL.projectImportFile).setInputFiles(
        path.join(__dirname, "helpers", "fixtures", "sample-novel.txt"),
      )
      await page.locator(SEL.projectImportSubmit).click()
      await expect(page.locator(SEL.toastContainer)).toContainText("导入完成", {
        timeout: 15_000,
      })

      await page.evaluate(() => window.router.navigate("writing"))
      await page.waitForFunction(() => !state.loading, { timeout: 10_000 })
      await waitWritingReady(page)
      await page.locator(SEL.writingToolsMenu).click()
      await page.getByRole("button", { name: "启动深度导入" }).click()
      const dialog = page.getByRole("dialog", { name: "自动提取" })
      await expect(dialog).toContainText("启动深度导入")
      await dialog.getByRole("button", { name: "确认并开始提取" }).click()
      await expect(page.locator(SEL.toastContainer)).toContainText("深度导入已启动", {
        timeout: 15_000,
      })

      await expect.poll(() => page.evaluate(() => {
        const workflows = JSON.parse(
          localStorage.getItem("novel_active_workflows_v1") || "[]",
        )
        return workflows.find((item) => item.workflowType === "deep_import")?.taskId || null
      })).not.toBeNull()
      const taskId = await page.evaluate(() => {
        const workflows = JSON.parse(
          localStorage.getItem("novel_active_workflows_v1") || "[]",
        )
        return workflows.find((item) => item.workflowType === "deep_import")?.taskId
      })

      const beforeClose = await getTask(taskId, testProjectId)
      expect(TERMINAL_TASK_STATUSES.has(beforeClose.status)).toBe(false)

      await browserProfile.close()
      const advancedWhileClosed = await waitForTaskAdvance(
        taskId,
        testProjectId,
        beforeClose,
        CLOSED_BROWSER_ADVANCE_TIMEOUT_MS,
      )
      expect(
        TERMINAL_TASK_STATUSES.has(advancedWhileClosed.status)
          || taskProgressMarker(advancedWhileClosed) !== taskProgressMarker(beforeClose),
      ).toBe(true)

      persistentContext = await browserProfile.launch()
      let recoveryPage = persistentContext.pages()[0] || await persistentContext.newPage()
      await openWorkbench(recoveryPage, testProject, "writing")
      let progressBar = recoveryPage.locator(SEL.deepImportProgress)
      await expect(progressBar).toBeVisible({ timeout: 15_000 })
      await expect(progressBar).toContainText(/等待执行|运行中|已完成/)

      const task = await waitForTaskDone(taskId, testProjectId)
      expect(task.status).toBe("done")
      expect(task.error_message || "").toBe("")
      expect(task.result.phase).toBe("done")
      expect(task.result.completed_steps).toEqual(expect.arrayContaining([
        "scene_segmentation",
        "entity_extraction",
        "structure_analysis",
      ]))
      await expect(recoveryPage.locator(SEL.deepImportMapNext)).toBeVisible({
        timeout: 15_000,
      })

      // 完成态在未确认关闭前必须再次跨浏览器进程恢复。
      await browserProfile.close()
      persistentContext = await browserProfile.launch()
      recoveryPage = persistentContext.pages()[0] || await persistentContext.newPage()
      await openWorkbench(recoveryPage, testProject, "writing")
      progressBar = recoveryPage.locator(SEL.deepImportProgress)
      await expect(progressBar).toContainText("已完成", { timeout: 15_000 })
      await expect(recoveryPage.locator(SEL.deepImportMapNext)).toBeVisible({
        timeout: 15_000,
      })

      await progressBar.getByRole("button", { name: "关闭" }).click()
      await expect.poll(() => recoveryPage.evaluate((expectedTaskId) => {
        const workflows = JSON.parse(
          localStorage.getItem("novel_active_workflows_v1") || "[]",
        )
        return workflows.some((item) => item.taskId === expectedTaskId)
      }, taskId)).toBe(false)
    } finally {
      await browserProfile.dispose()
    }
  })
})
