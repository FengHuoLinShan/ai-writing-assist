import { test, expect } from "./fixtures.js"
import { createDraft } from "./helpers/api-client.js"

test("深度审稿原位启动、离开恢复、部分覆盖与窄屏导航", async ({ page, projectFactory, openProjectWorkbench, browserErrors }, testInfo) => {
  const project = await projectFactory({ title: "协作验收 · 铜门" })
  const created = await createDraft(project.id, 1, "铜门", "门从里面打开。阿澄站在门外等候。")
  const draft = created.draft
  let run = null, submitted = null, polls = 0
  const reportId = "38c6829e-d40c-4ec1-9c4e-00f39aa344fe"
  const collaboration = { blueprint: "deep_review", label: "深度审稿", experimental: true, phase: "investigating", completion: "partial", freshness: "fresh", completed_count: 1, total_count: 3,
    work_items: [{ key: "facts", label: "事实与规则", status: "succeeded", attempt: 1 }, { key: "characters", label: "人物知识", status: "running", attempt: 1 }, { key: "narrative", label: "叙事结构", status: "pending", attempt: 0 }],
    coverage: [{ label: "事实与规则", checked_dimensions: ["开门条件"], omissions: ["未检查角色知识边界"] }], remaining_work: ["人物知识"], domain_results: [{ type: "writing_review", id: reportId, task_id: reportId, target: { type: "writing_draft", id: draft.id, chapter_index: 1 } }] }
  await page.route("**/api/assistant/capabilities?**", route => route.fulfill({ json: { enabled: true, model: { available: true }, web_search: { available: false }, destinations: [], collaboration: [{ id: "deep_review", label: "深度审稿", available: true, experimental: true }] } }))
  await page.route("**/api/assistant/sessions/*/team-runs", async route => {
    submitted = route.request().postDataJSON()
    expect(submitted.context.draft_id).toBe(draft.id)
    expect(submitted.allow_web).toBe(false)
    const sessionId = new URL(route.request().url()).pathname.split("/").at(-2)
    run = { id: submitted.operation_id, task_id: submitted.operation_id, session_id: sessionId, status: "running", result: { collaboration }, usage: { requests: 3 }, can_resume: false }
    await route.fulfill({ status: 202, json: run })
  })
  await page.route("**/api/tasks/*?**", async route => {
    if (!run || !route.request().url().includes(run.task_id)) return route.fallback()
    polls += 1
    if (polls >= 3 && run.result.collaboration) run = { ...run, status: "completed", result: { answer: "审稿结束，请结合未检查范围。", actions: [], collaboration: { ...collaboration, phase: "completed", completed_count: 2, work_items: collaboration.work_items.map(item => ({ ...item, status: item.key === "characters" ? "failed" : "succeeded" })) } } }
    await route.fulfill({ json: { id: run.task_id, task_type: "assistant_turn", status: run.status === "completed" ? "done" : "running", progress: 0.4, result: { run_id: run.id }, meta: { novel_id: project.id } } })
  })
  await page.route("**/api/assistant/runs/*?**", route => run ? route.fulfill({ json: run }) : route.fallback())
  await page.route("**/api/assistant/sessions/*?**", async route => {
    if (!run || !route.request().url().includes(run.session_id)) return route.fallback()
    const response = await route.fetch()
    const detail = await response.json()
    const messages = [...detail.messages, ...(run.result.answer ? [{ id: run.id, role: "assistant", content: run.result.answer, assistant_run_id: run.id, created_at: new Date().toISOString() }] : [])]
    await route.fulfill({ json: { ...detail, messages, message_total: messages.length, latest_run: run, last_context: submitted.context } })
  })
  await page.route(`**/api/writing/semantic-reviews/${reportId}?**`, route => route.fulfill({ json: { status: "completed", findings: [], not_checked: ["未检查角色知识边界"] } }))
  await openProjectWorkbench(project, "writing")
  await page.getByRole("button", { name: "打开第 1 章：铜门，16 字" }).click()
  await expect(page.locator("#writing-editor")).toHaveValue("门从里面打开。阿澄站在门外等候。")
  await page.locator("summary").filter({ hasText: "检查与导出" }).click()
  await page.getByRole("button", { name: "深度审稿", exact: true }).click()
  const panel = page.locator("#project-assistant-panel")
  await expect(panel).toBeVisible()
  await expect(panel.locator("#assistant-input")).toHaveValue(/深度审稿这一章/)
  await panel.getByRole("button", { name: "发送", exact: true }).click()
  await expect(panel.getByLabel("深度审稿进度")).toBeVisible()
  await page.evaluate(() => window.router.navigate("world", "bible"))
  await expect(panel.getByLabel("深度审稿进度")).toBeVisible()
  await expect(panel.getByText("本次仅完成部分检查，请结合未覆盖范围阅读。")).toBeVisible({ timeout: 30000 })
  await page.reload()
  await page.getByRole("button", { name: "项目助手", exact: true }).click()
  await expect(panel.getByText("本次仅完成部分检查，请结合未覆盖范围阅读。")).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(panel).toHaveAttribute("role", "dialog")
  await page.screenshot({ path: testInfo.outputPath("team-review-mobile.png"), fullPage: true })
  await panel.getByRole("button", { name: "在原工作区查看与处理" }).click()
  await panel.getByRole("button", { name: "关闭项目助手", exact: true }).click()
  await expect(page.getByLabel("深度审稿报告")).toBeVisible()
  await expect(page.locator("#writing-editor")).toHaveValue("门从里面打开。阿澄站在门外等候。")
  let followup = null
  await page.route("**/api/assistant/sessions/*/turns", async route => {
    followup = route.request().postDataJSON()
    run = { ...run, id: followup.operation_id, task_id: followup.operation_id, status: "completed", result: { answer: "仅解释原结论。", actions: [] } }
    await route.fulfill({ status: 202, json: run })
  })
  await page.getByRole("button", { name: "项目助手", exact: true }).click()
  await panel.locator("#assistant-input").fill("解释一下刚才的结论")
  await panel.getByRole("button", { name: "发送", exact: true }).click()
  await expect.poll(() => followup).not.toBeNull()
  expect(followup).not.toHaveProperty("blueprint")
  await expect(panel.getByText("仅解释原结论。")).toBeVisible()
  expect(browserErrors).toEqual([])
})
