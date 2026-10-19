/**
 * 导演独立探索浏览器行为：真实 Vue + 合成 HTTP I/O，不证明模型质量或作者验收。
 * 仅 projectFactory 使用专用测试库；探索、助手与任务回执全部由 page.route 提供。
 */
import { test, expect } from "./fixtures.js"

const LABELS = { sandbox: "沙盘推演", event: "事件诊断", scene_line: "场景对白" }
const PAYLOADS = {
  sandbox: {
    question: "重力减半时如何搬运面粉？",
    influence_chain: [{ condition: "每天一小时重力减半", mechanism: "同一袋面粉更轻", effect: "可以选择在这一小时搬运", holds_when: "仓库开放", unknown: "具体效率未知" }],
    preconditions: ["仓库开放"], unknowns: ["具体效率未知"], warnings: [],
  },
  event: {
    mode: "diagnose", original_excerpt: "信使不知道地址却当天送达",
    gaps: [{ description: "缺少收信人行踪的来源", why_needed: "无法解释如何找到收信人" }],
    unknowns: ["信息接触路径未知"], warnings: [],
  },
  scene_line: {
    target_ref: "c_b", line: "你看起来很累，要坐一会儿吗？", rationale: "只根据可见的疲惫回应",
    knowledge_basis: ["observed:疲惫"], withheld: ["没有获知失业原因"], unknowns: [], warnings: [],
  },
}
const TEXTS = { sandbox: "可以选择在这一小时搬运", event: "缺少收信人行踪的来源", scene_line: PAYLOADS.scene_line.line }
const FINGERPRINT = "a".repeat(64)
const BUDGET_HASH = "b".repeat(64)

async function installExploration(page, scale) {
  const source = {
    type: "story_exploration_result", root_id: "synthetic-root", branch_id: "synthetic-branch",
    result_id: "synthetic-result", scale, label: "合成探索结果", output_kind: `story.exploration.${scale}`, payload: PAYLOADS[scale],
  }
  const session = { id: "synthetic-session", title: "合成探索讨论" }
  const run = {
    id: "synthetic-run", status: "completed", context: { page: "writing" },
    result: { actions: [], sources: [
      { evidence_id: "synthetic-source", title: "已完成的探索", domain_reference: source },
      { evidence_id: "synthetic-recommendation", title: "探索推荐", domain_reference: { type: "story_exploration_recommendation", scale, question: "下一步怎样继续？", focus_hint: "保留原条件", reason: "合成推荐" } },
    ] },
  }
  await page.route("**/api/assistant/capabilities?*", route => route.fulfill({ json: { enabled: true, model: { available: true }, destinations: [] } }))
  await page.route("**/api/assistant/sessions?*", route => route.fulfill({ json: { items: [session], total: 1 } }))
  await page.route(`**/api/assistant/sessions/${session.id}?*`, route => route.fulfill({ json: { session, messages: [], message_total: 0, latest_run: run } }))
  await page.route(`**/api/assistant/runs/${run.id}?*`, route => route.fulfill({ json: run }))
  await page.route("**/api/story/exploration/history?*", route => route.fulfill({ json: { items: [latest] } }))
  const calls = []
  const derived = { kind: "provisional", question: "继续核对原结果中的条件", assumptions: [{ kind: "state", text: "原条件仍未证实" }], time_basis: "assumed_now" }
  let taskStatus = "done"
  let targetScale = scale
  let latest = source
  await page.route("**/api/story/exploration/**", async route => {
    const request = route.request()
    if (request.method() !== "POST") return route.fallback()
    const path = new URL(request.url()).pathname.replace("/api/story/exploration", "")
    const body = request.postDataJSON()
    calls.push({ path, body })
    if (path.endsWith("/handoff")) {
      targetScale = body.target_scale
      return route.fulfill({ json: { derived_start: derived, requires_confirmation: true } })
    }
    if (path === "/confirmation/preview") return route.fulfill({ json: { context_fingerprint: FINGERPRINT, selected_asset_ids: [], sources: [], blockers: [] } })
    if (path === "/confirmation") return route.fulfill({ json: { confirmation_id: "synthetic-confirmation" } })
    if (path === "/preview") return route.fulfill({ json: { recommendation: { scale: body.scale }, budget: { preview_hash: BUDGET_HASH, requests_min: 3, requests_max: 5 }, possible_charge: "合成预算，实际执行可能计费" } })
    if (path === "/start" || path.endsWith("/detail")) return route.fulfill({ status: 202, json: { task_id: "synthetic-task", root_id: "synthetic-target-root", branch_id: "synthetic-target-branch", status: "pending" } })
    if (path.endsWith("/save-edit")) {
      latest = { ...source, result_id: "synthetic-author-edit", output_kind: "story.exploration.author_edit", payload: { base_output_kind: body.base_output_kind, base_result_id: source.result_id, edited_payload: body.edited_payload } }
      return route.fulfill({ json: latest })
    }
    throw new Error(`Unexpected synthetic exploration request: ${path}`)
  })
  await page.route("**/api/tasks/synthetic-task**", async route => {
    if (route.request().method() === "POST") {
      calls.push({ path: "/tasks/cancel", url: route.request().url() })
      taskStatus = "cancelled"
      return route.fulfill({ json: { task_id: "synthetic-task", status: taskStatus } })
    }
    return route.fulfill({ json: { task_id: "synthetic-task", task_type: "story_exploration_scene_task", status: taskStatus, progress: taskStatus === "done" ? 1 : 0, result: taskStatus === "done" ? { ...source, root_id: "synthetic-target-root", branch_id: "synthetic-target-branch", result_id: "synthetic-target-result", scale: targetScale, output_kind: `story.exploration.${targetScale}`, payload: PAYLOADS[targetScale] } : null, meta: {} } })
  })
  return { source, calls, derived, setTaskStatus: status => { taskStatus = status }, latest: () => latest }
}

async function openExploration(page) {
  const panel = page.locator("#project-assistant-panel")
  if (!(await panel.isVisible())) await page.getByRole("button", { name: "项目助手", exact: true }).click()
  await expect(panel).toBeVisible()
  await panel.getByRole("button", { name: "讨论", exact: true }).click()
  await panel.locator("summary").filter({ hasText: "查看依据" }).click()
  await expect(panel.locator(".exploration-result-card").first()).toBeVisible()
  return panel
}

for (const [scale, target, width] of [
  ["sandbox", "event", 1280], ["sandbox", "scene_line", 390],
  ["event", "sandbox", 390], ["event", "scene_line", 1280],
  ["scene_line", "sandbox", 1280], ["scene_line", "event", 390],
]) test(`合成 I/O：${LABELS[scale]} → ${LABELS[target]} 确认后启动并恢复 · ${width}px`, async ({ page, projectFactory, openProjectWorkbench, browserErrors }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  const project = await projectFactory({ title: "导演独立探索 · 合成浏览器验收" })
  const fixture = await installExploration(page, scale)
  await openProjectWorkbench(project, "writing")
  let panel = await openExploration(page)
  let card = panel.locator(".exploration-result-card").first()
  await expect(card).toContainText(TEXTS[scale])
  const recommendation = panel.getByLabel("探索推荐", { exact: true })
  await recommendation.getByLabel("手动覆盖尺度").selectOption(target)
  await recommendation.getByRole("button", { name: "按此设定查看预览" }).click()
  await expect(recommendation.getByRole("status")).toContainText("3–5")
  expect(fixture.calls).toEqual([{ path: "/preview", body: { novel_id: project.id, scale: target, question: "下一步怎样继续？", focus: "保留原条件" } }])

  await card.locator("summary").filter({ hasText: "基于此推演" }).click()
  await card.getByRole("button", { name: LABELS[target], exact: true }).click()
  await card.getByLabel("推演焦点（可留空）").fill("保留条件与未知")
  await card.getByRole("button", { name: "生成移交预览", exact: true }).click()
  await expect(card).toContainText(fixture.derived.question)
  expect(fixture.calls.filter(call => call.path === "/start")).toHaveLength(0)
  await card.getByRole("button", { name: "继续：确认资料范围并开始", exact: true }).click()
  await expect(card).toContainText("资料范围：选中 0 项，来源 0 条")
  expect(fixture.calls.filter(call => call.path === "/start")).toHaveLength(0)
  await card.getByRole("button", { name: "确认并开始", exact: true }).click()
  await expect(card).toContainText("移交后的探索已完成")
  await expect(card.locator(".exploration-result-card")).toContainText(TEXTS[target])
  const sequence = fixture.calls.map(call => call.path)
  expect(sequence.slice(-4)).toEqual(["/confirmation/preview", "/confirmation", "/preview", "/start"])
  const started = fixture.calls.at(-1).body
  expect(started).toEqual(expect.objectContaining({ novel_id: project.id, scale: target, start: fixture.derived, focus: "保留条件与未知", context_confirmation_id: "synthetic-confirmation", budget_preview_hash: BUDGET_HASH, operation_id: expect.any(String) }))
  expect(fixture.calls.find(call => call.path === "/confirmation").body.expected_context_fingerprint).toBe(FINGERPRINT)
  await page.reload()
  panel = await openExploration(page)
  card = panel.locator(".exploration-result-card").first()
  await expect(card).toContainText(TEXTS[scale])
  await expect(card.locator(".exploration-result-card")).toContainText(TEXTS[target])
  expect(fixture.calls.filter(call => call.path === "/start")).toHaveLength(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath(`exploration-${scale}-${target}-${width}.png`), fullPage: true })
  expect(browserErrors).toEqual([])
})

test("合成 I/O：保存失败保留草稿，刷新后保存新版本，进行中的生成可停止 · 390px", async ({ page, projectFactory, openProjectWorkbench, browserErrors }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  const project = await projectFactory({ title: "探索编辑与恢复 · 合成浏览器验收" })
  const fixture = await installExploration(page, "scene_line")
  let failSave = true
  await page.route("**/api/story/exploration/results/*/save-edit", async route => {
    if (failSave) return route.fulfill({ status: 409, json: { detail: "父版本已变化，请核对后保存" } })
    return route.fallback()
  })
  await openProjectWorkbench(project, "writing")
  let panel = await openExploration(page)
  let card = panel.locator(".exploration-result-card").first()
  await card.locator("summary").filter({ hasText: "保存编辑" }).click()
  let editor = card.getByLabel(/^编辑/)
  const text = "先坐一会儿吧，我陪着你。"
  await editor.fill(text)
  await card.getByRole("button", { name: "保存编辑", exact: true }).click()
  await expect(card.getByRole("alert")).toContainText("父版本已变化")
  await expect(card.getByRole("alert")).toContainText("草稿已在本机备份")
  await expect(card.getByText("已保存编辑", { exact: true })).toHaveCount(0)
  await expect(editor).toHaveValue(text)
  expect(browserErrors.splice(0)).toEqual([{ kind: "console", text: "Failed to load resource: the server responded with a status of 409 (Conflict)" }])
  await page.reload()
  panel = await openExploration(page)
  card = panel.locator(".exploration-result-card").first()
  await card.locator("summary").filter({ hasText: "保存编辑" }).click()
  editor = card.getByLabel(/^编辑/)
  await expect(editor).toHaveValue(text)
  failSave = false
  await card.getByRole("button", { name: "保存编辑", exact: true }).click()
  await expect(card).toContainText("已保存编辑（形成新版本")
  await expect(card).toContainText(text)
  expect(fixture.latest().result_id).not.toBe(fixture.source.result_id)
  expect(fixture.source.payload.line).toBe(TEXTS.scene_line)

  fixture.setTaskStatus("running")
  await card.getByRole("button", { name: "说详细点", exact: true }).click()
  await expect(card.getByRole("button", { name: "停止这次生成", exact: true })).toBeVisible()
  expect(fixture.calls.at(-1).path).toBe("/results/synthetic-author-edit/detail")
  await page.reload()
  panel = await openExploration(page)
  card = panel.locator(".exploration-result-card").first()
  await expect(card.getByRole("button", { name: "停止这次生成", exact: true })).toBeVisible()
  expect(fixture.calls.filter(call => call.path.endsWith("/detail"))).toHaveLength(1)
  await card.getByRole("button", { name: "停止这次生成", exact: true }).click()
  await expect(card.getByRole("button", { name: "停止这次生成", exact: true })).toHaveCount(0)
  expect(fixture.calls.filter(call => call.path === "/tasks/cancel")).toHaveLength(1)
  await expect(card).toContainText(text)
  expect(browserErrors).toEqual([])
})

test("合成 I/O：服务端与本地备份都失败时，保护编辑并阻止关闭或切讨论 · 390px", async ({ page, projectFactory, openProjectWorkbench, browserErrors }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  const project = await projectFactory({ title: "探索双保存失败 · 合成浏览器验收" })
  await installExploration(page, "scene_line")
  await page.route("**/api/story/exploration/results/*/save-edit", route => route.fulfill({ status: 409, json: { detail: "本次保存发生冲突" } }))
  let newSessions = 0
  await page.route("**/api/assistant/sessions", route => { newSessions += 1; return route.fulfill({ json: { id: "unexpected-session", title: "不应创建" } }) })
  await openProjectWorkbench(project, "writing")
  const panel = await openExploration(page)
  const card = panel.locator(".exploration-result-card").first()
  await card.locator("summary").filter({ hasText: "保存编辑" }).click()
  await page.evaluate(() => {
    const setItem = Storage.prototype.setItem
    Storage.prototype.setItem = function (key, value) {
      if (key.startsWith("novel_exploration_edit_v1")) throw new DOMException("Synthetic storage full", "QuotaExceededError")
      return setItem.call(this, key, value)
    }
  })
  const editor = card.getByLabel(/^编辑/)
  await editor.fill("这句修改仍留在本页，不能静默丢失。")
  await card.getByRole("button", { name: "保存编辑", exact: true }).click()
  await expect(card.getByRole("alert").filter({ hasText: "保存未成功" })).toContainText("本地备份也失败")
  await expect(card.getByText("已保存编辑", { exact: true })).toHaveCount(0)
  await panel.locator(".project-assistant-header").getByRole("button", { name: "关闭项目助手" }).click()
  await expect(panel).toBeVisible()
  await expect(card.getByRole("alert").filter({ hasText: "编辑尚未保存或备份" })).toBeVisible()
  await panel.getByRole("button", { name: "新讨论", exact: true }).click()
  await expect(editor).toHaveValue("这句修改仍留在本页，不能静默丢失。")
  expect(newSessions).toBe(0)
  expect(browserErrors).toEqual([{ kind: "console", text: "Failed to load resource: the server responded with a status of 409 (Conflict)" }])
})
