import { createHash } from "node:crypto"
import { test, expect } from "./fixtures.js"
import { createDraft, createEntity, createScene } from "./helpers/api-client.js"
import { openWorkbench, waitWritingReady } from "./helpers/workbench.js"

const TEXT = "沈岚的师父柳舟住在北港。沈岚沿河寻找柳舟。"
const hash = value => createHash("sha256").update(value).digest("hex")

function evidenceResult(draftId, complete = true) {
  const source = { draft_id: draftId, chapter_index: 1, version_number: 1, content_mode: "working", start_offset: 0, end_offset: TEXT.length, source_hash: hash(TEXT), range_hash: hash(TEXT) }
  return {
    targets: [{ key: "root", name: "沈岚", depth: 0, resolution: "unresolved" }, { key: "neighbor", name: "柳舟", depth: 1, resolution: "unresolved" }],
    evidence: [{ key: "source", text: TEXT, source_ref: source, selection_ref: { kind: "source_range", source_ref: source }, target_keys: ["root", "neighbor"] }],
    coverage: { complete, scanned_chapters: 1, total_chapters: complete ? 1 : 2, matched_occurrences: 2 },
    warnings: complete ? [] : ["还有原文未查读"], has_more: !complete,
  }
}

async function mockFocused(page, draftId, partial = false) {
  const requests = []
  let resumed = false
  await page.route("**/api/evidence/compilation/focused-search**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (request.method() === "POST" && path.endsWith("/resume")) {
      resumed = true
      return route.fulfill({ status: 202, json: { task_id: "focused-2", status: "pending" } })
    }
    if (request.method() === "POST") {
      requests.push(request.postDataJSON())
      return route.fulfill({ status: 202, json: { task_id: "focused-1", status: "pending" } })
    }
    const complete = !partial || resumed
    return route.fulfill({ json: { task_id: resumed ? "focused-2" : "focused-1", status: complete ? "completed" : "recoverable", can_resume: !complete, result: evidenceResult(draftId, complete), error: null } })
  })
  return requests
}

test("副驾驶按场景查证，390px下保留出处选择及离开恢复", async ({ page, projectFactory }) => {
  const project = await projectFactory({ title: "专项查证写作验收" })
  const created = await createDraft(project.id, 1, "北港", TEXT), draft = created.draft || created
  const scene = await createScene(project.id, { scene_index: 0, title: "寻找师父", chapter_ids: ["1"], scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: TEXT.length }], goal: "找到柳舟" })
  const requests = await mockFocused(page, draft.id, true)
  await page.setViewportSize({ width: 390, height: 844 })
  await openWorkbench(page, project, "writing")
  await waitWritingReady(page, { chapter: 1 })
  await page.getByRole("button", { name: /^打开第 1 章/ }).click()
  const closeChapters = page.getByRole("button", { name: "关闭章节", exact: true })
  if (await closeChapters.isVisible()) await closeChapters.click({ force: true, timeout: 2000 }).catch(() => {})
  const railButton = page.getByRole("button", { name: "本章资料", exact: true })
  if (await railButton.getAttribute("aria-expanded") === "false") await railButton.click()
  const panel = page.locator(".focused-evidence")
  await panel.locator(":scope > summary").click()
  await panel.getByLabel("人物、地点或设定名称").fill("沈岚")
  await panel.getByRole("button", { name: "开始查证", exact: true }).click()
  await expect(panel).toContainText("当前为部分结果")
  expect(requests).toHaveLength(1)
  expect(requests[0]).toMatchObject({ consumer: "writing", scene_id: scene.id, chapter_index: 1, roots: [{ name: "沈岚" }] })
  await panel.getByRole("button", { name: "加入本次写作资料" }).click()
  await expect(panel).toContainText("已加入待确认资料")

  await page.reload()
  await waitWritingReady(page, { chapter: 1 })
  if (await closeChapters.isVisible()) await closeChapters.click()
  if (await railButton.getAttribute("aria-expanded") === "false") await railButton.click()
  await panel.locator(":scope > summary").click()
  await expect(panel).toContainText("当前为部分结果")
  await expect(panel).toContainText("已加入待确认资料")
  await panel.getByRole("button", { name: "继续未完成的查证" }).click()
  await expect(panel).toContainText("声明范围内的查读已结束")
  expect(requests).toHaveLength(1)
})

test("地图节点补查使用共用接口，证据选择不修改地图", async ({ page, projectFactory }) => {
  const project = await projectFactory({ title: "专项查证地图验收" })
  const requests = await mockFocused(page, "draft-map")
  const nodeId = "20000000-0000-0000-0000-000000000001"
  let mapWrites = 0
  await page.route("**/api/world/map-atlas/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (request.method() !== "GET") { mapWrites += 1; return route.fulfill({ status: 400, json: { detail: "unexpected write" } }) }
    if (path.endsWith("/atlas")) return route.fulfill({ json: { mode: "atlas", total_pages: 0, nodes: [{ id: nodeId, title: "北港", level: "region", pages: [], children: [] }] } })
    if (path.endsWith("/map")) return route.fulfill({ json: { node_id: nodeId, revision: null, candidates: [], image_layers: [], task: null } })
    if (path.endsWith("/runs/latest")) return route.fulfill({ json: null })
    if (path.endsWith("/pages/history")) return route.fulfill({ json: [] })
    return route.fulfill({ status: 404, json: { detail: "unexpected request" } })
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await openWorkbench(page, project, "map")
  await page.getByRole("button", { name: "补建空间示意", exact: true }).click()
  const panel = page.locator(".focused-evidence")
  await panel.locator(":scope > summary").click()
  await panel.getByRole("button", { name: "开始查证" }).click()
  await expect(panel).toContainText("第 1 章原文")
  expect(requests[0]).toMatchObject({ consumer: "map", content_mode: "canonical", roots: [{ name: "北港" }] })
  await panel.getByRole("button", { name: "加入本次地图资料" }).click()
  await expect(panel).toContainText("已加入待确认资料")
  expect(mapWrites).toBe(0)

})

test("对象详情明确授权补全，撤销需确认且发送同一任务", async ({ page, projectFactory }) => {
  const project = await projectFactory({ title: "专项补全对象验收" })
  const entity = await createEntity(project.id, { name: "北港", entity_type: "location", status: "canonical" })
  const writes = [], rollbacks = []
  let applied = false
  await page.route(`**/api/world/entities/${entity.id}?**`, route => route.fulfill({ json: { ...entity, summary: applied ? "新查证的概要" : null } }))
  await page.route("**/api/imports/targeted-completions**", async route => {
    if (new URL(route.request().url()).pathname.endsWith("/rollback")) {
      applied = false
      rollbacks.push(route.request().postDataJSON())
      return route.fulfill({ json: { status: "rolled_back", conflicts: 0 } })
    }
    writes.push(route.request().postDataJSON())
    applied = true
    return route.fulfill({ status: 202, json: { task_id: "completion-1", workflow_type: "targeted_completion" } })
  })
  await page.route("**/api/tasks/completion-1?**", route => route.fulfill({ json: { id: "completion-1", task_type: "targeted_completion", status: "done", result: { targeted_completion: { status: "done", root_count: 1, completed_roots: 1, created: 1, filled: 1, review: 1 } } } }))
  await openWorkbench(page, project, "world", "bible")
  await page.locator(".world-library-home__type-chip", { hasText: "地点" }).click()
  await page.locator(".world-library-list__row").filter({ hasText: "北港" })
    .locator("[data-action='open-world-card']")
    .click()
  const panel = page.locator(".targeted-completion")
  await panel.locator(":scope > summary").click()
  expect(writes).toHaveLength(0)
  await panel.getByRole("button", { name: "授权并开始补全" }).click()
  await expect(panel).toContainText("新增 1 · 填空 1 · 待审 1")
  await expect(page.locator(".world-entity-detail")).toContainText("新查证的概要")
  await page.locator(".world-entity-detail").getByRole("button", { name: "编辑资料", exact: true }).click()
  await expect(page.locator("#edit-entity-summary")).toHaveValue("新查证的概要")
  await page.locator("#modal-footer").getByRole("button", { name: "取消", exact: true }).click()
  expect(writes[0]).toMatchObject({ novel_id: project.id, targets: [{ entity_id: entity.id }], authorization_confirmed: true })
  page.once("dialog", dialog => dialog.dismiss())
  await panel.getByRole("button", { name: "撤销这次补全" }).click()
  expect(rollbacks).toHaveLength(0)
  page.once("dialog", dialog => dialog.accept())
  await panel.getByRole("button", { name: "撤销这次补全" }).click()
  await expect(panel).toContainText("本次补全已安全撤销")
  await expect(page.locator(".world-entity-detail")).not.toContainText("新查证的概要")
  expect(rollbacks).toEqual([{ confirmed: true }])
})
