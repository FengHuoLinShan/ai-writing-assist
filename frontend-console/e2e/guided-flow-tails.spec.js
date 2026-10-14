import { test, expect } from "./fixtures.js"
import { waitWritingReady } from "./helpers/workbench.js"

import { createAutosavedDraft, waitForBackend } from "./helpers/api-client.js"

/**
 * 集成尾部三入口 E2E（BR-4/5/6 流程侧，ADR-0032 同一运行层）。
 *
 * 只断言作者可见的入口与停点语义，所有流程 API 视图按服务端契约
 * （guided_flow 运行层 v2）用路由替身返回，不依赖真实模型：
 * - 空项目首页「新书开篇」卡：一句构想 → 方向卡选择 → 骨架采用 → 骨架可用。
 * - 审读台「走引导流程修订」：选中意见 → 候选可审阅 → 改后复核结果。
 * - 写作页续写流程卡「规划接下来几章」：采用后提窗 → 结构候选审阅。
 * 说明：本 spec 与集成分支 mock 约定对齐——capabilities 不回传上游 404、
 * attachRun 走 /flows/active 与 /flows/{id} 两个替身。
 */

const OPENING_RUN_ID = "00000000-0000-0000-0000-0000000000a1"
const EDITORIAL_RUN_ID = "00000000-0000-0000-0000-0000000000e1"
const WRITE_RUN_ID = "00000000-0000-0000-0000-0000000000f2"

function step(stepId, title, state, detail = "") {
  return { step_id: stepId, title, state, detail }
}

function json(body, status = 200) {
  return { status, contentType: "application/json", body: JSON.stringify(body) }
}

test.describe("引导流程集成尾部：三个入口", () => {
  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test("空项目首页：新书开篇卡从一句构想到方向卡选择", async ({ page, projectFactory, openProjectWorkbench }) => {
    const project = await projectFactory({ title: "空项目开篇", genre: "fantasy", language: "zh" })
    let phase = "cards"
    let started = false
    let packageVersion = 1
    const packageId = "00000000-0000-0000-0000-0000000000b1"
    let packageItems = [{ item_key: "city", kind: "core_entity", disposition: "include", payload: { operation: "create", entity: { name: "潮城", summary: "旧简介" } } }, { item_key: "risk", kind: "core_entity", disposition: "include", payload: { operation: "create", entity: { name: "待舍弃规则", summary: "无用支线" } } }]
    let lastEdits = []
    const card = {
      title: "潮汐都市",
      genre_promise: "城市奇幻",
      central_conflict: "潮钟权柄之争",
      protagonist_goal: "找回被收走的名字",
      world_tone: "潮湿、明亮、规则透明",
      reader_promise: "每章解开一层城市规则",
      main_risk: "设定密度偏高",
    }
    const openingView = (overrides = {}) => ({
      run_id: OPENING_RUN_ID,
      flow_id: "new_book_opening",
      flow_version: 1,
      title: "新书开篇",
      status: "waiting_approval",
      chapter_index: null,
      stop: null,
      steps: [
        step("direction_cards", "生成方向卡", "done"),
        step("choose_direction", "选择方向", "active"),
        step("draft_skeleton", "起草世界观骨架", "pending"),
        step("adopt_skeleton", "确认骨架", "pending"),
        step("skeleton_ready", "骨架可用", "pending"),
      ],
      candidate: null,
      panel: {
        vision: "潮汐城市",
        batch: 1,
        more_allowed: true,
        cards: phase === "cards" ? [card, { ...card, title: "守灯人" }] : [],
        chosen: null,
        package: null,
        adopted: null,
      },
      settings: {},
      ...overrides,
    })
    await page.route("**/api/assistant/capabilities*", async (route) => {
      const original = await route.fetch()
      const payload = await original.json()
      payload.guided_flows = { available: true, reason: null }
      await route.fulfill({ response: original, json: payload })
    })
    const skeletonView = () => openingView({
      status: phase === "adopted" || phase === "rolledback" ? "completed" : "waiting_approval",
      stop: { step_id: phase === "adopted" ? "skeleton_ready" : phase === "rolledback" ? "skeleton_reversed" : phase === "skeleton" ? "adopt_skeleton" : "choose_direction", kind: "author_choice", reason: phase === "cards" ? "选择一个方向" : "骨架逐条取舍", actions: [] },
      panel: { ...(openingView().panel), package: phase === "cards" ? null : { package_suggestion_id: packageId }, adopted: phase === "adopted" || phase === "rolledback" ? { package_suggestion_id: packageId } : null },
    })
    await page.route("**/api/assistant/flows/latest*", route => route.fulfill(json(started ? skeletonView() : null)))
    await page.route("**/api/assistant/flows/active*", route => route.fulfill(json(started && phase !== "adopted" ? skeletonView() : null)))
    await page.route(`**/api/assistant/flows/${OPENING_RUN_ID}?*`, route => route.fulfill(json(skeletonView())))
    await page.route("**/api/assistant/flows", async route => {
      if (route.request().method() !== "POST") return route.fallback()
      started = true
      return route.fulfill(json(openingView({ status: "running" }), 201))
    })
    await page.route("**/api/assistant/flows/*/advance", async route => {
      const choice = route.request().postDataJSON()?.choice
      if (choice?.action === "choose") phase = "skeleton"
      if (choice?.action === "adopt_skeleton") { expect(choice.expected_preview_hash).toBe("p".repeat(64)); phase = "adopted" }
      return route.fulfill(json(skeletonView()))
    })
    const artifact = () => ({ updated_at: `2026-10-12T00:00:0${packageVersion}Z`, payload_json: { items: packageItems } })
    await page.route(`**/api/world/adoption-packages/${packageId}?*`, route => route.fulfill(json(artifact())))
    await page.route(`**/api/world/adoption-packages/${packageId}/preview*`, route => route.fulfill(json({ expected_preview_hash: "p".repeat(64), canon_diff: [] })))
    await page.route(`**/api/world/adoption-packages/${packageId}/items`, route => {
      lastEdits = route.request().postDataJSON().items
      packageItems = packageItems.map(item => { const edit = lastEdits.find(edit => edit.item_key === item.item_key); return edit ? { ...item, disposition: edit.included ? "include" : "open", payload: { ...item.payload, entity: { ...item.payload.entity, ...(edit.name ? { name: edit.name } : {}), ...(edit.summary ? { summary: edit.summary } : {}) } } } : item })
      packageVersion += 1
      return route.fulfill(json({ suggestion: artifact(), item_conflicts: [] }))
    })
    await page.route(`**/api/world/adoption-packages/${packageId}/rollback`, route => { phase = "rolledback"; return route.fulfill(json({ results: [{ item_key: "city", status: "modified_after_adoption" }] })) })

    await openProjectWorkbench(project, "today")

    // 空项目首页出现新书开篇卡；作者语言，不暴露内部标识。
    const card_ = page.locator(".opening-flow")
    await expect(card_).toBeVisible()
    await expect(card_).toContainText("从一句构想开始新书")
    await expect(card_).not.toContainText("new_book_opening")

    await card_.getByLabel("一句构想").fill("潮汐城市")
    await card_.getByRole("button", { name: "开始新书开篇" }).click()

    // 方向卡停点：两张候选、可再要一批。
    await expect(card_).toContainText("潮汐都市")
    await expect(card_).toContainText("题材承诺")
    await expect(card_.getByRole("button", { name: /再要一批/ })).toBeVisible()
    await card_.getByRole("radio").first().check()
    await card_.getByRole("button", { name: "用这个方向继续" }).click()
    const review = card_.getByRole("region", { name: "骨架逐条取舍" })
    await expect(review.getByLabel("简介").first()).toHaveValue("旧简介")
    await review.getByLabel("简介").first().fill("作者保留的城市规则")
    await review.locator('input[type="checkbox"]').nth(1).uncheck()
    await expect(review.getByRole("button", { name: "采用所选条目" })).toBeDisabled()
    await review.getByRole("button", { name: "保存取舍" }).click()
    await expect(review).toContainText("取舍已保存")
    expect(lastEdits).toEqual([{ item_key: "city", included: true, summary: "作者保留的城市规则" }, { item_key: "risk", included: false }])
    await review.getByRole("button", { name: "采用所选条目" }).click()
    await expect(card_.getByRole("button", { name: "撤销这次骨架采用" })).toBeVisible()
    await page.reload()
    await expect(page.locator(".opening-flow").getByRole("button", { name: "撤销这次骨架采用" })).toBeVisible()
    await page.locator(".opening-flow").getByRole("button", { name: "撤销这次骨架采用" }).click()
    await page.locator("#modal-footer").getByRole("button", { name: /确认|撤销/ }).click()
    await expect(page.locator(".opening-flow")).toContainText("采用后已编辑，保留")

  })

  test("审读台：走引导流程修订从选中意见到改后复核结果", async ({ page, projectFactory, openProjectWorkbench }) => {
    const project = await projectFactory({ title: "修订引导", genre: "fantasy", language: "zh" })
    const draft = await createAutosavedDraft(project.id, 1, "修订章节", "需要修订的原稿。")
    const editorialView = (overrides = {}) => ({
      run_id: EDITORIAL_RUN_ID,
      flow_id: "editorial_revision",
      flow_version: 1,
      title: "按审读意见定向修订",
      description: "从审读台选中的意见开始。",
      status: "waiting_approval",
      chapter_index: null,
      stop: {
        step_id: "review_candidates",
        kind: "author_choice",
        reason: "已生成 1 个替换候选；到写作页先完成独立审稿，通过后才能采用（已采用 0 个）。 采用后自动请求改后复核。",
        actions: [
          { action: "open_candidate", label: "去写作页审阅候选" },
          { action: "proceed", label: "对已采用的发起改后复核" },
          { action: "abandon_flow", label: "结束流程" },
        ],
      },
      steps: [
        step("select_issues", "选择意见并说明处置", "done"),
        step("bridge_revision", "发起批注修订", "done"),
        step("review_candidates", "审阅替换候选", "active"),
        step("post_recheck", "请求改后复核", "pending"),
        step("review_rechecks", "查看改后复核", "pending"),
      ],
      candidate: null,
      panel: {
        items: [
          { issue_id: "issue-1", status: "queued", chapter_index: 1, reason: "", candidate_draft_id: "draft-9", kind: "ready" },
        ],
        unlocatable_count: 0,
        rechecks: [],
      },
      settings: {},
      ...overrides,
    })
    await page.route("**/api/assistant/capabilities*", async (route) => {
      const original = await route.fetch()
      const payload = await original.json()
      payload.guided_flows = { available: true, reason: null }
      payload.editorial = { available: true, reason: null }
      await route.fulfill({ response: original, json: payload })
    })
    await page.route("**/api/assistant/flows/active*", (route) => route.fulfill(json(null)))
    await page.route("**/api/assistant/flows", async (route) => {
      if (route.request().method() !== "POST") return route.fallback()
      return route.fulfill(json(editorialView({ status: "running", stop: null }), 201))
    })
    await page.route("**/api/assistant/flows/*/advance", async (route) => route.fulfill(json(editorialView())))

    await page.route("**/api/assistant/editorial/reviews*", route => route.fulfill(json([{
      id: "rev-1", status: "partial", scope: { scope: "selection" },
      sources: [{ chapter_index: 1, draft_id: draft.id, content_hash: draft.content_hash }],
      checked_chapters: [1], unchecked_chapters: [], missing: [], context_sources: [], context_omissions: [],
      report: { summary: "", coverage_complete: true, top_findings: [], all_findings: [] },
    }])))
    await page.route("**/api/assistant/editorial/issues*", route => route.fulfill(json([{
      id: "issue-1", review_id: "rev-1", version: 0, disposition: "open", decisions: [], history: [], rechecks: [],
      finding: { judgment: "这句需要修订", category: "structure", severity: "medium", suggestion: "补足动机", evidence: [{ chapter_index: 1, draft_id: draft.id, content_hash: draft.content_hash, quote: "需要修订", start: 0, end: 4 }] },
    }])))
    await openProjectWorkbench(project, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await page.getByRole("button", { name: /^打开第 1 章/ }).click()
    await page.getByRole("button", { name: "本章写完，交给编辑看" }).click()
    const desk = page.locator(".editorial-desk")
    await expect(desk).toBeVisible()

    // 选中意见 + 处置说明 → 走引导流程修订。
    await desk.locator(".editorial-issue input[type='checkbox']").first().setChecked(true)
    await desk.locator(".editorial-desk__revision textarea").fill("按上下文改写这句")
    await desk.getByRole("button", { name: "走引导流程修订" }).click()

    const strip = desk.locator(".editorial-desk__flowstrip")
    await expect(strip).toBeVisible()
    await expect(strip).toContainText("已生成 1 个替换候选")
    await expect(strip).not.toContainText("editorial_revision")
    await expect(strip.getByRole("button", { name: "去写作页审阅候选" })).toBeVisible()
  })

  test("写作页续写流程卡：采用后提「规划接下来几章」，确认后停在结构候选审阅", async ({ page, projectFactory, openProjectWorkbench }) => {
    const project = await projectFactory({ title: "滚动规划", genre: "fantasy", language: "zh" })
    const rollingOffer = {
      run_id: WRITE_RUN_ID,
      flow_id: "continue_writing",
      flow_version: 3,
      title: "继续写下一场",
      status: "waiting_approval",
      chapter_index: 1,
      candidate: { draft_id: "draft-1", chapter_index: 1, title: "第 1 章" },
      stop: {
        step_id: "rolling_offer",
        kind: "author_choice",
        reason: "第 1 章已采用。接下来的第 2 至 4 章，可以生成剧情线与篇章候选（含审查与必要返修，按实际调用计费，不生成正文）。后方已规划 0 章，不足 2 章；建议现在补足到 3 章。",
        actions: [
          { action: "plan_ahead", label: "规划接下来几章" },
          { action: "decline", label: "先不用" },
          { action: "abandon_flow", label: "结束流程" },
        ],
      },
      steps: [
        step("confirm_reference", "确认本章资料", "done"),
        step("generate_candidate", "生成正文候选", "done"),
        step("semantic_review", "独立语义审查", "done"),
        step("review_candidate", "审阅候选", "done"),
        step("rolling_offer", "规划接下来几章", "active"),
        step("rolling_threads", "提出后续剧情线候选", "pending"),
        step("rolling_arcs", "提出后续篇章候选", "pending"),
        step("rolling_review", "审阅后续章节候选", "pending"),
      ],
      panel: {
        rolling: { chapter_index: 1, window: { start: 2, end: 4 }, window_size: 3, accepted: false, planned_chapters: 0 },
      },
      settings: { semantic_review: true, rolling_planning: true, planning_window: 3 },
    }
    await page.route("**/api/assistant/capabilities*", async (route) => {
      const original = await route.fetch()
      const payload = await original.json()
      payload.guided_flows = { available: true, reason: null }
      await route.fulfill({ response: original, json: payload })
    })
    let currentRollingView = rollingOffer
    await page.route("**/api/assistant/flows/active*", (route) => route.fulfill(json(currentRollingView)))
    await page.route(`**/api/assistant/flows/${WRITE_RUN_ID}**`, async (route) => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith("/advance")) {
        const input = route.request().postDataJSON()
        const reviewing = Boolean(input.context_confirmation_id)
        currentRollingView = { ...rollingOffer, stop: { step_id: reviewing ? "review_rolling_threads" : "confirm_rolling_threads", kind: reviewing ? "author_choice" : "author_confirm", reason: reviewing ? "请取舍本层候选，采用后再确认下一层" : "请另行确认本层完整结构资料", actions: reviewing ? [{ action: "open_outline", label: "打开结构工作台" }] : [{ action: "confirm_rolling", label: "核对本层完整资料" }] }, panel: { rolling: { chapter_index: 1, window: { start: 2, end: 4 }, accepted: true } } }
        return route.fulfill(json(currentRollingView))
      }
      return route.fulfill(json(currentRollingView))
    })

    await page.route("**/api/evidence/compilation/preview", route => route.fulfill(json({ context_fingerprint: "f".repeat(64), warnings: [], blockers: [], sections: [], items: { required: [], found: [], pinned: [], excluded: [] }, budget: { total_tokens: 0, used_tokens: 0 } })))
    await page.route("**/api/evidence/compilation/confirm", route => {
      const data = route.request().postDataJSON()
      expect(data.action).toBe("outline.generate")
      expect(data.scope).toBe("full")
      expect(data.chapter_index).toBe(2)
      expect(data.planning_window_end).toBe(4)
      expect(data.budget_tokens).toBe(0)
      return route.fulfill(json({ id: "00000000-0000-0000-0000-0000000000c1", novel_id: project.id, action: data.action, context_fingerprint: "f".repeat(64), result_status: "confirmed" }, 201))
    })
    await openProjectWorkbench(project, "writing")

    const host = page.locator(".writing-flow-host")
    await expect(host).toBeVisible()
    // 补窗提示是作者语言：说明不足并建议补足到 K 章。
    await expect(host).toContainText("不足 2 章")
    await host.getByRole("button", { name: "规划接下来几章" }).click()

    // 结构候选审阅停点：去结构工作台采用或直接完成。
    await expect(host).toContainText("请另行确认本层完整结构资料")
    await host.getByRole("button", { name: "核对本层完整资料" }).click()
    await page.locator("#modal-footer").getByRole("button", { name: /按这份资料开始|确认/ }).click()
    await expect(host).toContainText("请取舍本层候选")
    await host.getByRole("button", { name: "打开结构工作台" }).click()
    await expect(page).toHaveURL(/\/outline\/story-outline(?:\?|$)/)
  })
})
