import { test, expect } from "./fixtures.js"
import { openWorkbench } from "./helpers/workbench.js"
import { cleanupProject, createProject, waitForBackend } from "./helpers/api-client.js"

test.describe("P1 lifecycle and evidence health", () => {
  let project = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.afterEach(async () => {
    if (project?.id) await cleanupProject(project.id)
    project = null
  })

  test("failed import renders only backend-provided recovery actions", async ({ page }) => {
    project = await createProject({ title: "P1 recovery action", genre: "fantasy", language: "zh" })
    const taskId = "p1-recoverable-task"
    let resumeCalls = 0
    await page.addInitScript(({ projectId, id }) => {
      localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
        id: `${projectId}:deep_import:${id}`,
        taskId: id,
        workflowType: "deep_import",
        projectId,
        view: "writing",
      }]))
    }, { projectId: project.id, id: taskId })
    await page.route(`**/api/tasks/${taskId}**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: taskId,
          task_type: "deep_import",
          status: "failed",
          result: {
            recovery_required: true,
            recovery_summary: { current_phase: "entity_extraction", committed_scenes: 4 },
          },
          lifecycle: {
            reason: "heartbeat_timeout",
            recovery_policy: "manual_resume",
            recovery_required: true,
          },
          available_actions: ["resume", "abandon"],
          attempt: 1,
          max_attempts: 1,
        }),
      })
    })
    await page.route("**/api/imports/deep/resume", async (route) => {
      resumeCalls += 1
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ task_id: taskId, status: "pending", result: {} }),
      })
    })

    await openWorkbench(page, project, "writing")

    const prompt = page.locator("#writing-deep-import-bar-container")
    await expect(prompt).toContainText("自动提取需要恢复")
    await expect(prompt.getByRole("button", { name: "继续" })).toBeVisible()
    await expect(prompt.getByRole("button", { name: "放弃恢复" })).toBeVisible()
    expect(resumeCalls).toBe(0)
    await prompt.getByRole("button", { name: "继续" }).click()
    await expect.poll(() => resumeCalls).toBe(1)
  })

  test("RAG status renders evidence health without exposing trace payload", async ({ page }) => {
    project = await createProject({ title: "P1 evidence health", genre: "fantasy", language: "zh" })
    await page.route("**/api/evidence/indexing/chunks**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ total: 2, embedding_failed_count: 0, items: [] }),
      })
    })
    await page.route("**/api/evidence/compilation/evidence-health**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          novel_id: project.id,
          content_mode: "canonical",
          window_hours: 24,
          health_state: "degraded",
          health_reasons: ["eligible_mapping_below_target"],
          scene_span_coverage: { precise_span_rate: 0.91 },
          rag_mapping_coverage: { eligible_mapping_rate: 0.82 },
          retrieval_summary: { query_count: 12, empty_count: 3 },
        }),
      })
    })

    await openWorkbench(page, project, "rag", "status")

    const card = page.locator(".rag-status-warning-card")
    await expect(card).toContainText("可以改进")
    await expect(card).toContainText("91%")
    await expect(card).toContainText("82%")
    await expect(page.locator("body")).not.toContainText("raw query")
  })
})
