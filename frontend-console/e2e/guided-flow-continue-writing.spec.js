import { test, expect } from "./fixtures.js"

import { waitForBackend, createDraft, getLatestDraft } from "./helpers/api-client.js"
import { reloadWorkbench, waitWritingReady } from "./helpers/workbench.js"

/**
 * 流程 2 v1「继续写下一场」作者视角 E2E（ADR-0032 / BR-3）。
 *
 * 验收口径：从首页「引导续写第 N 章」到可审阅候选，作者只做资料确认与
 * 最终采用两次决定；刷新后回到同一停点；硬性阻断时说明原因与可执行动作。
 * 生成与审查任务由路由替身返回，不依赖真实模型；流程 API 的视图载荷
 * 按服务端契约（guided_flow 运行层）构造。
 */

const CONFIRMATION_ID = "00000000-0000-0000-0000-0000000000b1"
const CANDIDATE_DRAFT_ID = "00000000-0000-0000-0000-0000000000c9"
const RUN_ID = "00000000-0000-0000-0000-0000000000f1"

function step(stepId, title, state, detail = "") {
  return { step_id: stepId, title, state, detail }
}

function flowView(overrides = {}) {
  return {
    run_id: RUN_ID,
    flow_id: "continue_writing",
    flow_version: 1,
    title: "继续写下一场",
    status: "waiting_approval",
    chapter_index: 1,
    stop: null,
    steps: [
      step("confirm_reference", "确认本章资料", "done"),
      step("generate_candidate", "生成正文候选", "active", "正在生成正文候选"),
      step("semantic_review", "独立语义审查", "pending", ""),
      step("review_candidate", "审阅候选", "pending", ""),
    ],
    candidate: null,
    settings: { semantic_review: true },
    ...overrides,
  }
}

async function mockFlowApi(page, state) {
  const json = (body, status = 200) => ({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  })

  await page.route("**/api/assistant/capabilities*", async (route) => {
    // e2e 后端助手开关默认关，真实 capabilities 会 404：能力投影本地定值，
    // 不把上游状态原样回传（404 会让前端判定不可用而隐藏入口）。
    let payload = {}
    try {
      const original = await route.fetch()
      if (original.ok()) payload = await original.json()
    } catch { /* 后端不可达时用空负载 */ }
    payload.guided_flows = { available: true, reason: null }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) })
  })
  // 刷新/换设备恢复：URL query 可能被改写，写作页回落探测活动流程；
  // 服务端契约是返回当前活动流程视图（无则 null）。
  await page.route("**/api/assistant/flows/active*", (route) => route.fulfill(json(state.active || state.current || null)))
  // 刷新/换设备恢复：attachRun 按 run_id 拉流程视图
  await page.route(`**/api/assistant/flows/${RUN_ID}*`, (route) => route.fulfill(json(state.current || state.active || flowView())))
  await page.route("**/api/assistant/flows", async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    state.started = route.request().postDataJSON()
    state.current = flowView({
      status: "waiting_approval",
      stop: {
        step_id: "confirm_reference",
        kind: "author_confirm",
        reason: "需要你确认本章资料后才能生成；可在本页就地核对或修改本章目标，再按这份资料继续。",
        actions: [{ action: "confirm_reference", label: "确认本章资料" }],
      },
      steps: [
        step("confirm_reference", "确认本章资料", "active"),
        step("generate_candidate", "生成正文候选", "pending"),
        step("semantic_review", "独立语义审查", "pending"),
        step("review_candidate", "审阅候选", "pending"),
      ],
    })
    return route.fulfill(json(state.current), 201)
  })
  await page.route("**/api/assistant/flows/*/advance", async (route) => {
    state.advances.push(route.request().postDataJSON())
    state.current = state.nextAdvance()
    return route.fulfill(json(state.current))
  })
  await page.route("**/api/assistant/flows/*/settings", async (route) => {
    const body = route.request().postDataJSON()
    return route.fulfill(json(flowView({ settings: { semantic_review: Boolean(body.semantic_review) } })))
  })
  await page.route("**/api/assistant/flows/*/abandon*", (route) => route.fulfill(json({ ok: true })))
}

test.describe("引导流程：继续写下一场", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ projectFactory }) => {
    const project = await projectFactory({ title: "引导流程测试", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    // 第 1 章已有已采用工作稿：首页续写入口的数据前提。
    await createDraft(testProjectId, 1, "第一章 雾港来信", "潮声退到石阶之外，石门仍旧紧闭。")
  })

  test("从首页到可审阅候选：作者只做资料确认与采用两次决定", async ({ page, openProjectWorkbench }) => {
    const state = { active: null, advances: [], started: null, phase: "confirmed" }
    state.nextAdvance = () => {
      if (state.phase === "confirmed") {
        state.phase = "reviewable"
        return flowView({
          status: "waiting_approval",
          candidate: { draft_id: CANDIDATE_DRAFT_ID, chapter_index: 1, title: "第一章 雾港来信" },
          stop: {
            step_id: "review_candidate",
            kind: "author_choice",
            reason: "可审阅，待作者采用",
            actions: [
              { action: "open_candidate", label: "查看候选" },
              { action: "abandon_flow", label: "结束流程" },
            ],
          },
          steps: [
            step("confirm_reference", "确认本章资料", "done"),
            step("generate_candidate", "生成正文候选", "done"),
            step("semantic_review", "独立语义审查", "done"),
            step("review_candidate", "审阅候选", "active"),
          ],
        })
      }
      return flowView({
        status: "completed",
        candidate: { draft_id: CANDIDATE_DRAFT_ID, chapter_index: 1, title: "第一章 雾港来信" },
        steps: [
          step("confirm_reference", "确认本章资料", "done"),
          step("generate_candidate", "生成正文候选", "done"),
          step("semantic_review", "独立语义审查", "done"),
          step("review_candidate", "审阅候选", "done"),
        ],
      })
    }
    await mockFlowApi(page, state)
    // 「查看候选」按流程返回的 draft_id 拉候选草稿：以真实第 1 章草稿为底，
    // 覆盖为候选态，避免真实后端 404。
    const baseDraft = await getLatestDraft(testProjectId, 1)
    await page.route(`**/api/writing/drafts/${CANDIDATE_DRAFT_ID}*`, async (route) => {
      if (route.request().method() !== "GET") return route.continue()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...baseDraft,
          id: CANDIDATE_DRAFT_ID,
          status: "candidate",
          display_state: "candidate",
          provenance_json: { source: "ai_generated", review_required: false },
        }),
      })
    })
    // 资料确认复用既有弹窗：替身确认接口，弹窗内容断言走真实组件。
    await page.route("**/api/evidence/compilation/preview", async (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        context_fingerprint: "f".repeat(64),
        warnings: [],
        blockers: [],
        sections: [],
        items: { required: [], found: [], pinned: [], excluded: [] },
        budget: { total_tokens: 4000, used_tokens: 0 },
      }),
    }))
    await page.route("**/api/evidence/compilation/confirm", async (route) => route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: CONFIRMATION_ID,
        novel_id: testProjectId,
        action: "writing.generate",
        compile_options: { requested_chapter_index: 1 },
        result_status: "confirmed",
        stale_reasons: [],
        warnings: [],
        blockers: [],
        sections: [],
        context_fingerprint: "f".repeat(64),
      }),
    }))

    await openProjectWorkbench({ id: testProjectId, title: "引导流程测试" }, "today")

    // 1) 首页入口：引导续写入口可见（能力开启 + 有可继续章节）。
    const entry = page.getByRole("button", { name: /引导续写第 1 章/ })
    await expect(entry).toBeVisible()
    await entry.click()

    // 2) 写作页流程宿主：停在资料确认，说明为什么停。
    await waitWritingReady(page)
    const host = page.locator(".writing-flow-host")
    await expect(host).toBeVisible()
    await expect(host).toContainText("需要你确认本章资料后才能生成")
    await expect(host).toContainText("确认本章资料")

    // 3) 作者决定一：按既有资料确认弹窗确认本章资料。
    await host.getByRole("button", { name: "确认本章资料", exact: true }).click()
    const confirmButton = page.locator("#modal-footer").getByRole("button", { name: /按这份资料开始|确认/ })
    await expect(confirmButton).toBeVisible({ timeout: 10000 })
    await confirmButton.click()
    await expect(host).toContainText("可审阅，待作者采用")
    expect(state.advances[0]?.context_confirmation_id).toBe(CONFIRMATION_ID)

    // 4) 作者决定二：查看候选并采用（采用走写作页既有候选面板，此处验证入口）。
    await host.getByRole("button", { name: "查看候选", exact: true }).click()
    await expect(page.locator("#writing-editor-container")).toContainText("这份建议还没有改动工作稿")

    // 5) 刷新回到同一停点（flow run id 保留在地址中）。
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page)
    await expect(page.locator(".writing-flow-host")).toBeVisible()
  })

  test("任一步硬性阻断时停下并说明原因与可执行动作", async ({ page, openProjectWorkbench }) => {
    const state = {
      active: flowView({
        status: "failed",
        stop: {
          step_id: "generate_candidate",
          kind: "blocked",
          reason: "正文候选没有生成完成；已生成内容不会丢失，可结束本流程后重新开始。",
          actions: [
            { action: "open_candidate", label: "查看候选" },
            { action: "abandon_flow", label: "结束流程" },
          ],
        },
        steps: [
          step("confirm_reference", "确认本章资料", "done"),
          step("generate_candidate", "生成正文候选", "blocked", "正文候选没有生成完成"),
          step("semantic_review", "独立语义审查", "pending"),
          step("review_candidate", "审阅候选", "pending"),
        ],
      }),
      advances: [],
      nextAdvance: () => flowView(),
    }
    await mockFlowApi(page, state)

    await openProjectWorkbench({ id: testProjectId, title: "引导流程测试" }, "writing")
    await waitWritingReady(page)
    const host = page.locator(".writing-flow-host")
    await expect(host).toBeVisible()
    await expect(host).toContainText("正文候选没有生成完成")
    await expect(host).toContainText("结束流程")
    await host.getByRole("button", { name: "结束流程", exact: true }).click()
    await page.getByRole("button", { name: "结束流程" }).last().click()
    await expect(host).toContainText("已结束")
  })
})
