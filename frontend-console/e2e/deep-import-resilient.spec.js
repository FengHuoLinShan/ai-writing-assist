import { test, expect } from "@playwright/test"
import { openWorkbench, reloadWorkbench } from "./helpers/workbench.js"
import {
  cleanupProject,
  createDraft,
  createProject,
  waitForBackend,
} from "./helpers/api-client.js"

function runningTask(taskId, result = {}) {
  return {
    task_id: taskId,
    id: taskId,
    status: "running",
    progress: 0.25,
    result: {
      phase: "running",
      current_step: "scene_segmentation",
      current_phase: "phase0",
      current_round: "A",
      current_chapter_range: "1-5",
      current_chapter: 3,
      current_scene_candidate_id: "cand-1",
      current_operation: "scene_prefetch",
      message: "正在预取 Scene 候选并统计质量...",
      quality_stats: {
        phase0: {
          total_batches: 6,
          completed_batches: 2,
          success: 2,
          final_422: 0,
          final_422_rate: 0,
          timeout: 0,
          schema_error: 0,
        },
      },
      ...result,
    },
  }
}

async function createProjectWithChapters(title) {
  const project = await createProject({ title, genre: "fantasy", language: "zh" })
  await createDraft(project.id, 1, "第一章", "第一章正文")
  await createDraft(project.id, 2, "第二章", "第二章正文")
  return project
}

async function submitDeepImportFromWritingView(page, start = 1, end = 2) {
  await page.evaluate(async ({ startChapter, endChapter }) => {
    await window.writingView._submitDeepImport(startChapter, endChapter)
  }, { startChapter: start, endChapter: end })
}

async function storedDeepImportTaskId(page) {
  return page.evaluate(() => {
    const legacy = localStorage.getItem("novel_deepImportTaskId")
    if (legacy) return legacy
    try {
      const workflows = JSON.parse(localStorage.getItem("novel_activeWorkflows") || "[]")
      return workflows.find((item) => item.workflowType === "deep_import")?.taskId || null
    } catch {
      return null
    }
  })
}

test.describe("深度导入韧性进度与恢复", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("显示 Phase 0 双轮预取进度和质量统计", async ({ page }) => {
    const project = await createProjectWithChapters("深度导入韧性进度")
    testProjectId = project.id
    const taskId = "resilient-phase0-task"

    await page.route("**/api/imports/deep", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ task_id: taskId, workflow_id: taskId, status: "pending" }),
      })
    })
    await page.route(`**/api/tasks/${taskId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(runningTask(taskId)),
      })
    })

    await openWorkbench(page, project, "writing")
    await submitDeepImportFromWritingView(page)

    const progress = page.locator("#writing-deep-import-bar-container")
    await expect(progress).toContainText("深度导入")
    await expect(progress).toContainText("phase0")
    await expect(progress).toContainText("Round：A")
    await expect(progress).toContainText("章节范围：1-5")
    await expect(progress).toContainText("请求数：6")
    await expect(progress).toContainText("成功：2")
    await expect(progress).toContainText("422 率：0%")

    const storedTaskId = await storedDeepImportTaskId(page)
    expect(storedTaskId).toBe(taskId)
  })

  test("Phase 0 或 Phase 1a 422 超阈值时阻断并显示官方 API 建议", async ({ page }) => {
    const project = await createProjectWithChapters("深度导入422阻断")
    testProjectId = project.id
    const taskId = "resilient-blocked-task"

    await page.route(`**/api/tasks/${taskId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: taskId,
          status: "failed",
          error_message: "Phase 0 Scene 预取 422 错误率过高",
          result: {
            phase: "failed",
            current_phase: "phase0",
            degraded: true,
            degraded_reason: "phase0_422_rate_exceeded",
            message: "Phase 0 Scene 预取 422 错误率过高，已停止深度导入。推荐使用官方api以保障稳定性与质量（强推DeepSeek-v4-flash，质量高价格低并发超快！）",
            quality_stats: {
              phase0: {
                total_batches: 10,
                completed_batches: 10,
                final_422_batches: 5,
                final_422_rate: 0.5,
              },
            },
          },
        }),
      })
    })

    await openWorkbench(page, project, "writing")
    await page.evaluate((tid) => {
      localStorage.setItem("novel_deepImportTaskId", tid)
    }, taskId)
    await reloadWorkbench(page, "writing")

    const progress = page.locator("#writing-deep-import-bar-container")
    await expect(progress).toContainText("Phase 0 Scene 预取 422 错误率过高")
    await expect(progress).toContainText("422 率：50%")
    await expect(progress).toContainText("推荐使用官方api以保障稳定性与质量")
    await expect(progress).not.toContainText("深度导入完成！")
  })

  test("Phase 1b 422 超阈值时降级继续并提示 fallback", async ({ page }) => {
    const project = await createProjectWithChapters("深度导入降级继续")
    testProjectId = project.id
    const taskId = "resilient-degraded-task"

    await page.route(`**/api/tasks/${taskId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(runningTask(taskId, {
          current_phase: "phase1b",
          current_round: null,
          current_window: "1-30",
          current_operation: "scene_fusion",
          message: "正在融合 Scene 候选并生成正式写入候选...",
          degraded: true,
          degraded_reason: "phase1b_422_rate_exceeded",
          phase1a_fallback: true,
          quality_status: "partial",
          quality_stats: {
            phase1b: {
              total_windows: 2,
              completed_windows: 2,
              final_422: 1,
              final_422_rate: 0.5,
              fallback_scene_count: 2,
              fused_scene_count: 18,
              needs_review_scene_count: 3,
            },
          },
        })),
      })
    })

    await openWorkbench(page, project, "writing")
    await page.evaluate((tid) => {
      localStorage.setItem("novel_deepImportTaskId", tid)
    }, taskId)
    await reloadWorkbench(page, "writing")

    const progress = page.locator("#writing-deep-import-bar-container")
    await expect(progress).toContainText("phase1b")
    await expect(progress).toContainText("窗口：1-30")
    await expect(progress).toContainText("422 率：50%")
    await expect(progress).toContainText("fallback Scene：2")
    await expect(progress).toContainText("自动整理失败，已使用质量补强结果继续导入")
  })

  test("刷新和路由切换后复用 localStorage task 恢复进度", async ({ page }) => {
    const project = await createProjectWithChapters("深度导入刷新恢复")
    testProjectId = project.id
    const taskId = "resilient-route-recovery-task"
    let taskFetches = 0

    await page.route(`**/api/tasks/${taskId}`, async (route) => {
      taskFetches += 1
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(runningTask(taskId, {
          current_chapter_range: "8-12",
          current_chapter: 10,
        })),
      })
    })

    await openWorkbench(page, project, "writing")
    await page.evaluate((tid) => {
      localStorage.setItem("novel_deepImportTaskId", tid)
    }, taskId)
    await reloadWorkbench(page, "writing")
    await expect(page.locator("#writing-deep-import-bar-container")).toContainText("章节范围：8-12")

    await page.evaluate(async () => {
      await window.router.navigate("project")
    })
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })
    await expect(page.locator("#view-title")).toHaveText("项目")
    await page.evaluate(async () => {
      await window.router.navigate("writing")
    })
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })
    await expect(page.locator("#writing-deep-import-bar-container")).toContainText("当前章节：10")

    await reloadWorkbench(page, "writing")
    await expect(page.locator("#writing-deep-import-bar-container")).toContainText("当前章节：10")
    expect(taskFetches).toBeGreaterThanOrEqual(2)
  })

  test("中断任务必须用户点击继续，且继续复用原 task", async ({ page }) => {
    const project = await createProjectWithChapters("深度导入手动继续")
    testProjectId = project.id
    const taskId = "resilient-interrupted-task"
    let resumeCalls = 0

    await page.route(`**/api/tasks/${taskId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(runningTask(taskId, {
          interrupted: true,
          recoverable: true,
          recovery_required: true,
          current_phase: "phase1b",
          recovery_summary: {
            current_phase: "phase1b",
            current_chapter_range: "31-60",
            committed_scenes: 12,
            committed_entities: 8,
          },
        })),
      })
    })
    await page.route("**/api/imports/deep/resume", async (route) => {
      resumeCalls += 1
      const body = route.request().postDataJSON()
      expect(body.task_id).toBe(taskId)
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: taskId,
          status: "pending",
          result: {
            phase: "running",
            current_phase: "phase1b",
            current_chapter_range: "31-60",
            message: "恢复进度中...",
          },
        }),
      })
    })

    await openWorkbench(page, project, "writing")
    await page.evaluate((tid) => {
      localStorage.setItem("novel_deepImportTaskId", tid)
    }, taskId)
    await reloadWorkbench(page, "writing")

    const progress = page.locator("#writing-deep-import-bar-container")
    await expect(progress).toContainText("深度导入需要恢复")
    await expect(progress).toContainText("已写入 Scene：12")
    expect(resumeCalls).toBe(0)

    await page.getByRole("button", { name: "继续" }).click()
    await expect(progress).toContainText("31-60")
    expect(resumeCalls).toBe(1)
    const activeTaskId = await page.evaluate(() => window.writingView._deepImportTaskId)
    expect(activeTaskId).toBe(taskId)
  })

  test("放弃恢复前二次确认，确认后显示清理结果", async ({ page }) => {
    const project = await createProjectWithChapters("深度导入放弃恢复")
    testProjectId = project.id
    const taskId = "resilient-abandon-task"
    let abandonCalls = 0

    await page.route(`**/api/tasks/${taskId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(runningTask(taskId, {
          interrupted: true,
          recoverable: true,
          recovery_required: true,
          recovery_summary: {
            committed_scenes: 9,
            committed_entities: 5,
          },
        })),
      })
    })
    await page.route("**/api/imports/deep/abandon", async (route) => {
      abandonCalls += 1
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: taskId,
          status: "cancelled",
          cleanup_summary: {
            deprecated_scenes: 9,
            deprecated_entities: 5,
          },
        }),
      })
    })

    await openWorkbench(page, project, "writing")
    await page.evaluate((tid) => {
      localStorage.setItem("novel_deepImportTaskId", tid)
    }, taskId)
    await reloadWorkbench(page, "writing")

    await page.getByRole("button", { name: "放弃恢复" }).click()
    await expect(page.locator("#modal-body")).toContainText("确认放弃深度导入恢复")
    await expect(page.locator("#modal-body")).toContainText("Scene/实体")
    expect(abandonCalls).toBe(0)

    await page.locator("#modal-footer").getByRole("button", { name: "确认放弃" }).click()
    await expect(page.locator("#toast-container")).toContainText("已放弃恢复：Scene 9 个，实体 5 个")
    expect(abandonCalls).toBe(1)
  })

  test("移动端进度提示和质量统计可读不重叠", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 760 })
    const project = await createProjectWithChapters("深度导入移动端")
    testProjectId = project.id
    const taskId = "resilient-mobile-task"

    await page.route(`**/api/tasks/${taskId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(runningTask(taskId, {
          current_scene_candidate_id: "very-long-scene-candidate-id-for-mobile-check",
          current_chapter_range: "100-105",
        })),
      })
    })

    await openWorkbench(page, project, "writing")
    await page.evaluate((tid) => {
      localStorage.setItem("novel_deepImportTaskId", tid)
    }, taskId)
    await reloadWorkbench(page, "writing")

    const progress = page.locator("#writing-deep-import-bar-container .workflow-progress")
    await expect(progress).toBeVisible()
    await expect(progress).toContainText("100-105")
    await expect(progress).toContainText("422 率")
    const box = await progress.boundingBox()
    expect(box.width).toBeLessThanOrEqual(390)
    expect(box.height).toBeGreaterThan(60)
  })
})
