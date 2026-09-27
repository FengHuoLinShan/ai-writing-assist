import { test, expect } from "./fixtures.js"
import { createAutosavedDraft } from "./helpers/api-client.js"

test("编辑台在桌面与 390px 下保留作者约定、完成标记和范围反馈", async ({ page, projectFactory, openProjectWorkbench, browserErrors }, testInfo) => {
  const project = await projectFactory({ title: "编辑台浏览器验收" })
  const draft = await createAutosavedDraft(project.id, 1, "雾港来信", "信上的地址指向旧港。")
  let reviews = []
  let issues = []
  let submitted = null
  await page.route("**/api/assistant/editorial/reviews**", async route => {
    const request = route.request()
    if (request.method() === "POST") {
      submitted = request.postDataJSON()
      const finding = {
        fingerprint: "synthetic-editorial-issue", category: "structure", severity: "medium",
        judgment: "地址线索值得再核对", reader_impact: "读者可能过早确定地点",
        why_now: "下一章即将沿此线索展开", counterevidence: "也可能是刻意误导",
        intent_relation: "保留迟疑的叙述声音", unchecked: "第二章缺稿",
        directions: [{ approach: "延后确认地址", affected_chapters: [1], tradeoff: "悬念持续更久" }],
        evidence: [{ chapter_index: 1, draft_id: draft.id, content_hash: draft.content_hash, quote: "地址指向旧港", start: 3, end: 9 }],
        context_evidence: [], authority: "editorial_suggestion",
      }
      const review = {
        id: crypto.randomUUID(), status: "partial", task_id: crypto.randomUUID(), scope: submitted,
        sources: [{ chapter_index: 1, draft_id: draft.id, content_hash: draft.content_hash, version_number: 1, title: "雾港来信" }],
        checked_chapters: [1], unchecked_chapters: [], missing: [{ chapter_index: 2, reason: "missing" }],
        context_sources: [], context_omissions: [], brief_version: submitted.expected_brief_version,
        brief_changed: false, report: { summary: "本次只完成了所列范围", coverage_complete: false, top_findings: [finding], all_findings: [finding] }, error: null,
      }
      reviews = [review]
      issues = [{ id: crypto.randomUUID(), review_id: review.id, fingerprint: finding.fingerprint, version: 0, disposition: "open", finding, decisions: [], history: [], rechecks: [], source_may_be_stale: false }]
      await route.fulfill({ json: review })
    } else await route.fulfill({ json: reviews })
  })
  await page.route("**/api/assistant/editorial/issues**", route => route.fulfill({ json: issues }))
  await openProjectWorkbench(project, "writing")
  await page.getByRole("button", { name: /^打开第 1 章/ }).click()
  const ready = page.getByRole("button", { name: "本章写完，交给编辑看" })
  await expect(ready).toBeEnabled()
  await ready.click()
  const desk = page.getByLabel("编辑台", { exact: true })
  await expect(desk).toBeVisible()
  await expect(page.getByRole("button", { name: "本版已交编辑" })).toBeVisible()
  await desk.getByLabel("希望保留的叙述声音").fill("保留迟疑的第一人称")
  await desk.getByRole("button", { name: "保存编辑约定" }).click()
  await expect(desk.getByText("编辑约定已保存。旧报告仍保留原依据。")).toBeVisible()
  await desk.getByRole("button", { name: "开始审读已保存正文" }).click()
  await expect(desk.getByText("缺失或排除：2章（缺稿）。")).toBeVisible()
  await expect(desk.getByText("地址线索值得再核对")).toBeVisible()
  await desk.locator("summary").filter({ hasText: "依据、反证和处理方向" }).click()
  await expect(desk.getByText("代价：悬念持续更久")).toBeVisible()
  expect(submitted.scope).toBe("chapter")
  expect(submitted.start_chapter).toBe(1)
  expect(submitted.expected_brief_version).toBe(1)
  await page.screenshot({ path: testInfo.outputPath("editorial-desktop.png"), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator("#project-assistant-panel")).toHaveAttribute("role", "dialog")
  await expect(desk.getByText("本次只完成了所列范围", { exact: true })).toBeVisible()
  await desk.locator("summary").filter({ hasText: "主动跟进" }).click()
  await desk.getByLabel("允许这部作品主动检查").check()
  await desk.getByRole("button", { name: "保存主动跟进设置" }).click()
  await expect(desk.locator("summary").filter({ hasText: "主动跟进" })).toContainText("已开启")
  await page.screenshot({ path: testInfo.outputPath("editorial-390px.png"), fullPage: true })
  expect(browserErrors).toEqual([])
})
