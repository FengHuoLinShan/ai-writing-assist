/**
 * BR-4 流程 3 E2E（spec only；随集成阶段统一执行）：
 * 编辑台选中审读意见 → 填写处置说明 → 发起批注修订 →
 * 查看逐条受理结果、替换候选入口与改后复核结果。
 *
 * 验收对应计划 §5 BR-4：
 * - 引文已不在当前稿的意见不生成候选，逐条说明且不影响其他意见；
 * - 改后复核只给「仍在 / 可能改善 / 无法判断」；
 * - 替换候选采用门禁不变（候选在写作页审阅采用，本用例只验证入口与回执展示）。
 */
import { test, expect } from "./fixtures.js"
import { waitWritingReady } from "./helpers/workbench.js"
import { createAutosavedDraft } from "./helpers/api-client.js"

test("审读台按意见发起批注修订并跟踪候选与改后复核", async ({ page, projectFactory, openProjectWorkbench, browserErrors }, testInfo) => {
  const project = await projectFactory({ title: "审读意见修订桥接验收" })
  const draft = await createAutosavedDraft(project.id, 1, "雾港来信", "信上的地址指向旧港。")
  const locatableIssueId = crypto.randomUUID()
  const unlocatableIssueId = crypto.randomUUID()
  const candidateDraftId = crypto.randomUUID()
  const revisionTaskId = crypto.randomUUID()
  const recheckTaskId = crypto.randomUUID()

  const finding = (issueId, quote) => ({
    fingerprint: issueId, category: "structure", severity: "medium",
    judgment: "地址线索值得再核对", reader_impact: "读者可能过早确定地点",
    why_now: "", counterevidence: "", intent_relation: "", unchecked: "",
    directions: [],
    evidence: [{ chapter_index: 1, draft_id: draft.id, content_hash: quote ? draft.content_hash : "stale-hash", quote, start: 3, end: 3 + quote.length }],
    context_evidence: [], authority: "editorial_suggestion",
  })
  const issues = [
    { id: locatableIssueId, review_id: "rev-1", fingerprint: locatableIssueId, version: 0, disposition: "open", finding: finding(locatableIssueId, "地址指向旧港"), decisions: [], history: [], rechecks: [], source_may_be_stale: false },
    // 引文已不在当前稿（引文异常但 hash 一致的情形）：不应生成候选
    { id: unlocatableIssueId, review_id: "rev-1", fingerprint: unlocatableIssueId, version: 0, disposition: "open", finding: finding(unlocatableIssueId, "地址指向新港"), decisions: [], history: [], rechecks: [], source_may_be_stale: false },
  ]

  // 「去写作页审阅并采用」会按 mock 的候选 ID 拉草稿：给最小候选响应避免 404
  await page.route(`**/api/writing/drafts/${candidateDraftId}*`, async (route) => {
    if (route.request().method() !== "GET") return route.continue()
    await route.fulfill({
      json: {
        ...draft,
        id: candidateDraftId,
        status: "candidate",
        display_state: "candidate",
        provenance_json: { source: "ai_generated", review_required: false },
      },
    })
  })

  // 编辑台按选中的审稿记录过滤意见：reviews GET 需返回承载这两条意见的记录
  await page.route("**/api/assistant/editorial/reviews**", async route => {
    if (route.request().method() !== "GET") return route.continue()
    await route.fulfill({
      json: [{
        id: "rev-1", status: "partial", task_id: "task-rev-1", scope: { scope: "selection" },
        sources: [{ chapter_index: 1, draft_id: draft.id, content_hash: draft.content_hash, version_number: 1, title: "雾港来信" }],
        checked_chapters: [1], unchecked_chapters: [], missing: [],
        context_sources: [], context_omissions: [], brief_version: 0, brief_changed: false,
        report: { summary: "", coverage_complete: true, top_findings: [], all_findings: [] },
        error: null,
      }],
    })
  })

  let reviseRequests = []
  await page.route("**/api/assistant/editorial/issues**", async route => {
    const request = route.request()
    if (request.method() === "POST" && request.url().includes("/revise")) {
      const body = request.postDataJSON()
      reviseRequests.push(body)
      await route.fulfill({
        json: {
          operation_id: body.operation_id,
          items: body.items.map(item => item.issue_id === unlocatableIssueId
            ? { issue_id: item.issue_id, status: "unlocatable", chapter_index: 1, reason: "意见引文已不在当前稿中，无法定位；这条不会生成替换候选" }
            : { issue_id: item.issue_id, status: "queued", task_id: revisionTaskId, chapter_index: 1 }),
        },
      })
      return
    }
    route.fulfill({ json: issues })
  })
  await page.route("**/api/writing/drafts/*/comments**", route => route.fulfill({ json: [] }))
  await page.route(`**/api/tasks/${revisionTaskId}?*`, async route => {
    await route.fulfill({
      json: {
        task_id: revisionTaskId, task_type: "writing_comment_run", status: "done",
        result: { candidate_draft_id: candidateDraftId, comment_ids: [locatableIssueId] },
        error_message: null,
      },
    })
  })
  await page.route(`**/api/tasks/${recheckTaskId}?*`, route => route.fulfill({
    json: { task_id: recheckTaskId, task_type: "assistant_editorial_recheck", status: "done", result: { verdict: "possibly_improved" } },
  }))

  await openProjectWorkbench(project, "writing")
  // 编辑台挂在项目助手的编辑台 tab 后面：走真实入口（选章 → 交给编辑）打开
  await waitWritingReady(page, { chapter: 1 })
  await page.getByRole("button", { name: /^打开第 1 章/ }).click()
  const ready = page.getByRole("button", { name: "本章写完，交给编辑看" })
  await expect(ready).toBeEnabled()
  await ready.click()
  const desk = page.getByLabel("编辑台", { exact: true })
  await expect(desk).toBeVisible()
  await expect(desk.getByText("地址线索值得再核对").first()).toBeVisible()

  // 选中两条意见并说明处置（两条意见同文，卡片顺序稳定）
  const cards = desk.locator(".editorial-issue")
  await expect(cards).toHaveCount(2)
  for (let index = 0; index < 2; index += 1) {
    await cards.nth(index).locator("input[type='checkbox']").check()
  }
  const panel = desk.locator(".editorial-desk__revision")
  await expect(panel.getByText(/按选中的 2 条意见发起批注修订/)).toBeVisible()
  await panel.getByLabel(/处置说明/).fill("把地址线索改得更隐晦，保留悬念")
  await expect(panel.getByRole("button", { name: "发起 2 条修订" })).toBeDisabled()
  await panel.getByLabel("已核对上方重叠片段的合并范围，同意联合修订。").check()
  await panel.getByRole("button", { name: "发起 2 条修订" }).click()

  // 逐条受理结果：一条排队、一条因引文失效不生成候选。
  // mock 任务立即 done，排队是瞬态：直接等最终态（下方"替换候选已生成"），
  // 引文失效的说明在提交响应里即刻渲染。
  await expect(panel.getByText("意见引文已不在当前稿中，无法定位；这条不会生成替换候选")).toBeVisible()
  expect(reviseRequests).toHaveLength(1)
  expect(reviseRequests[0].overlap_confirmed).toBe(true)
  expect(reviseRequests[0].items.every(item => JSON.stringify(item.evidence_indices) === "[0]")).toBe(true)
  expect(reviseRequests[0].items).toHaveLength(2)
  expect(reviseRequests[0].items.every(item => item.instruction === "把地址线索改得更隐晦，保留悬念")).toBe(true)

  // 任务完成后给出替换候选入口（写作页先独立审稿、通过后才能采用）
  await expect(panel.getByText("替换候选已生成")).toBeVisible({ timeout: 20000 })
  await panel.getByRole("button", { name: "去写作页完成独立审稿并采用" }).click()
  await expect(page).toHaveURL(/writing/)

  // 改后复核（采用后由系统触发或作者手动发起）：只允许三值结论
  issues[0].rechecks = [{
    operation_id: crypto.randomUUID(), task_id: recheckTaskId, status: "completed",
    verdict: "possibly_improved", reason: "地址线索已改为更隐晦的写法", new_evidence: [], unchecked: "",
  }]
  issues[0].disposition = "prepare"
  // 用编辑台的「刷新」确定性重载意见（不依赖 8 秒轮询的时序）
  await desk.getByRole("button", { name: "刷新" }).click()
  const cardWithRecheck = desk.locator(".editorial-issue").filter({ hasText: "地址线索值得再核对" }).first()
  // 复核记录折叠在「处理与复核历史」内，先展开
  await cardWithRecheck.getByText("处理与复核历史").click()
  await expect(cardWithRecheck.getByText("改后复核：可能已改善")).toBeVisible({ timeout: 20000 })
  for (const forbidden of ["问题已解决", "已核实修复"]) {
    await expect(desk.getByText(forbidden)).toHaveCount(0)
  }
  await page.screenshot({ path: testInfo.outputPath("editorial-revision-bridge.png"), fullPage: true })
  expect(browserErrors).toEqual([])
})
