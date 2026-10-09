import { test, expect } from "./fixtures.js"
import { clickWritingTool, openWorkbench, waitWritingReady } from "./helpers/workbench.js"
import { createDraft, createScene, waitForBackend } from "./helpers/api-client.js"

const GEN_TASK_ID = "00000000-0000-0000-0000-00000000e2e1"
const CANDIDATE_ID = "00000000-0000-0000-0000-00000000e2e2"

test.describe("写作生成跨设备恢复（BR-1a）", () => {
  let testProject = null
  let sceneId = null
  // 共享的模拟生成任务状态：两个浏览器上下文都从这份状态读写在途/终态。
  const generation = { submitted: false, status: "pending" }

  function taskPayload(projectId) {
    const done = generation.status === "done"
    return {
      task_id: GEN_TASK_ID,
      task_type: "writing_generate",
      status: generation.status,
      meta: { novel_id: projectId, chapter_index: 1, scene_id: sceneId },
      result: done ? { draft_id: CANDIDATE_ID } : { current_phase: "drafting" },
      error_message: null,
      created_at: "2026-10-09T08:00:00Z",
      started_at: "2026-10-09T08:00:01Z",
      finished_at: done ? "2026-10-09T08:05:00Z" : null,
      heartbeat_at: "2026-10-09T08:04:00Z",
      attempt: 1,
      max_attempts: 1,
      stale: false,
      operation: {
        version: 1,
        submission_mode: "exact_operation",
        stage: done ? "done" : "drafting",
        error_code: null,
        retryable: false,
        possible_charge: true,
        partial_result: false,
        available_actions: done ? ["dismiss"] : ["cancel"],
      },
      lifecycle: { reason: null, recovery_policy: "restart_origin", recovery_required: false, stale_detected_at: null },
      available_actions: done ? ["dismiss"] : ["cancel"],
    }
  }

  async function installGenerationRoutes(page, projectId) {
    await page.route("**/api/evidence/compilation/confirm", async (route) => {
      const body = route.request().postDataJSON()
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "00000000-0000-0000-0000-00000000e2e3",
          novel_id: body.novel_id,
          action: body.action,
          task: body.task,
          scope: body.scope,
          selected_asset_ids: {},
          sections: [],
          warnings: [],
        }),
      })
    })
    await page.route("**/api/writing/generate", async (route) => {
      generation.submitted = true
      generation.status = "running"
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ task_id: GEN_TASK_ID, status: "running" }),
      })
    })
    await page.route(/\/api\/tasks(\?|\/)/, async (route) => {
      const url = new URL(route.request().url())
      const isList = url.pathname.endsWith("/api/tasks")
      if (!generation.submitted) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [], active_count: 0 }) })
        return
      }
      const payload = taskPayload(projectId)
      if (isList) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ items: [payload], active_count: generation.status === "done" ? 0 : 1 }),
        })
      } else {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) })
      }
    })
    await page.route(`**/api/writing/drafts/${CANDIDATE_ID}/comments?**`, async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) })
    })
    await page.route(`**/api/writing/drafts/${CANDIDATE_ID}?**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: CANDIDATE_ID,
          novel_id: projectId,
          chapter_index: 1,
          title: "第一章 雾港来信",
          content: "潮声退到石阶之外，石门仍旧紧闭。守港人举起灯，示意林舟不要回头。",
          version_number: 2,
          status: "candidate",
          provenance_json: { source: "writing_generate", review_required: false },
          updated_at: "2026-10-09T08:05:00Z",
        }),
      })
    })
  }

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ projectFactory }) => {
    generation.submitted = false
    generation.status = "pending"
    testProject = await projectFactory({ title: "跨设备生成恢复", genre: "fantasy", language: "zh" })
    await createDraft(testProject.id, 1, "第一章 雾港来信", "潮声退到石阶之外，石门仍旧紧闭。")
    const scene = await createScene(testProject.id, {
      scene_index: 0,
      title: "退潮后的石门",
      narrative_tag: "opening",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 18 }],
      goal: "判断是否公开石门",
      core_conflict: "保护同行者，还是抢先留下证据",
    })
    sceneId = scene.id
  })

  test("A 设备发起生成，B 设备首页与写作页可见并可回到候选", async ({ page, browser }) => {
    test.setTimeout(120000)
    const projectId = testProject.id

    // 设备 A 与设备 B 先后打开写作页（此时都还没有在途生成）。
    await installGenerationRoutes(page, projectId)
    await openWorkbench(page, testProject, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await page.getByRole("button", { name: /打开第 1 章/ }).click()

    const contextB = await browser.newContext()
    const pageB = await contextB.newPage()
    try {
      await installGenerationRoutes(pageB, projectId)
      await openWorkbench(pageB, testProject, "writing")
      await waitWritingReady(pageB, { chapter: 1 })
      await pageB.getByRole("button", { name: /打开第 1 章/ }).click()

      // A 发起生成，任务保持“运行中”。
      await clickWritingTool(page, '[data-action="writing-ai-menu"]')
      await page.getByRole("button", { name: "AI 正文建议" }).click()
      await expect(page.locator("#modal-overlay")).toContainText("AI 参考资料")
      await page.locator("#modal-footer").getByRole("button", { name: "按这份资料开始" }).click()
      await expect(page.locator("#writing-generation-bar-container")).toContainText("正在生成正文", { timeout: 15000 })

      // B 的页面先于任务启动加载：点击生成时先提示已有在途生成，取消则跟随原任务。
      await clickWritingTool(pageB, '[data-action="writing-ai-menu"]')
      await pageB.getByRole("button", { name: "AI 正文建议" }).click()
      await expect(pageB.locator("#modal-overlay")).toContainText("已有一份正文正在生成", { timeout: 15000 })
      await pageB.locator("#modal-footer").getByRole("button", { name: "取消" }).click()
      await expect(pageB.locator("#writing-generation-bar-container")).toContainText("正在生成正文", { timeout: 15000 })

      // B 首页（写作首页）经服务端任务总览展示同一在途任务。
      await pageB.evaluate(async () => {
        await window.router.navigate("writing", null, true, new URLSearchParams({ home: "1" }))
      })
      await expect(pageB.getByRole("heading", { name: "正在进行的整理" })).toBeVisible({ timeout: 15000 })
      await expect(pageB.locator(".today-workflow-card")).toContainText("正在生成正文建议")

      // 回到写作页，进度条继续跟随同一任务。
      await pageB.evaluate(async () => {
        await window.router.navigate("writing", null, true)
      })
      await expect(pageB.locator("#writing-generation-bar-container")).toContainText("正在生成正文", { timeout: 15000 })

      // 任务完成后，B 能回到其候选。
      generation.status = "done"
      await expect(pageB.locator("#writing-generation-bar-container")).toContainText("查看并审阅建议", { timeout: 20000 })
      await pageB.locator("#writing-generation-bar-container").getByRole("button", { name: "查看并审阅建议" }).click()
      await expect(pageB.locator(".writing-candidate-review-panel")).toBeVisible({ timeout: 15000 })
      await expect(pageB.locator(".writing-candidate-review-panel")).toContainText("这份建议还没有改动工作稿")
    } finally {
      await contextB.close()
    }
  })
})
