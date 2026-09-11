import { test, expect } from "./fixtures.js"
import { openWorkbench } from "./helpers/workbench.js"
import { expectNoPageOverflow } from "./helpers/responsive.js"

// Provider/task responses are controlled here; real domain CAS/undo has PostgreSQL tests.
test("一次授权、成组选择、原文查看与窄屏刷新恢复", async ({ page, projectFactory }, testInfo) => {
  const project = await projectFactory({ title: "智能整理浏览器验收" })
  const submissions = [], decisions = []
  let submitted = false, accepted = false
  const summary = () => ({ counts: { organized: accepted ? 1 : 0, decision: accepted ? 1 : 2 }, fact_count: 2, processed_count: 2, question_count: 1, groups: [1, 2].map(index => ({ key: `candidate-${index}`, kind: "alias", group_key: "identity-question", outcome: accepted && index === 1 ? "organized" : "decision", question: "这两个称呼是否指向青港？", label: index === 1 ? "北港" : "港口", explanation: "请根据原文确认名称归属。", proposed_fields: { alias: index === 1 ? "北港" : "港口" }, fingerprint: String(index).repeat(64), evidence: [{ quote: "青港又称北港。船停在港口。" }] })) })
  await page.route("**/api/imports/review-summary?**", route => route.fulfill({ json: { unclassified: accepted ? 1 : 2, latest: submitted ? { task_id: "resolution-task", status: "done", result: summary() } : null } }))
  await page.route("**/api/imports/review-resolutions**", route => {
    if (route.request().url().includes("/decisions")) { decisions.push(route.request().postDataJSON()); accepted = true; return route.fulfill({ json: { status: "accepted" } }) }
    submitted = true; submissions.push(route.request().postDataJSON())
    return route.fulfill({ status: 201, json: { task_id: "resolution-task", status: "pending" } })
  })
  await page.route("**/api/tasks/resolution-task?**", route => route.fulfill({ json: { id: "resolution-task", task_type: "import_review_resolution", status: "done", result: { review_resolution: summary() } } }))
  await page.setViewportSize({ width: 390, height: 844 })
  await openWorkbench(page, project, "world", "review")
  const panel = page.getByRole("region", { name: "智能整理导入资料" })
  await panel.getByRole("button", { name: "整理这些资料", exact: true }).click()
  await panel.getByRole("button", { name: "授权并开始整理", exact: true }).click()
  await expect(panel).toContainText("1 组问题需要决定")
  await expect(panel.locator("article")).toHaveCount(1)
  await panel.getByText("原文依据", { exact: true }).first().click()
  await expect(panel.locator("blockquote").first()).toBeVisible()
  await panel.getByRole("checkbox").nth(1).uncheck()
  await panel.getByRole("button", { name: "确认采用本组选中资料" }).click()
  await expect.poll(() => decisions.length).toBe(1)
  expect(decisions[0].candidate_keys).toEqual(["candidate-1"])
  expect(submissions).toHaveLength(1)
  expect(submissions[0]).toMatchObject({ novel_id: project.id, authorization_confirmed: true, start_chapter: 1, end_chapter: 0 })
  await page.reload()
  await expect(panel).toContainText("已处理 2 / 2")
  expect(submissions).toHaveLength(1)
  await expectNoPageOverflow(page)
  await panel.screenshot({ path: testInfo.outputPath("review-resolution-narrow.png") })
})
