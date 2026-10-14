import { test, expect } from "./fixtures.js"
import { createAutosavedDraft } from "./helpers/api-client.js"
import { openWorkbench, waitWritingReady } from "./helpers/workbench.js"

const nodeId = "20000000-0000-0000-0000-000000000001"
const revisionId = "30000000-0000-0000-0000-000000000001"

function mapNotice(failed = false) {
  return {
    chapter_index: 1, receipt_id: failed ? "failed-map-receipt" : "map-receipt",
    affected: failed ? [] : [{ consumer: "map_atlas", node_id: nodeId, revision_id: revisionId, map_title: "东岸与港口地图", chapter_index: 1, reason: "canonical_map_source_changed", basis: "known" }],
    invalidated: [{ consumer: "map_atlas", label: "地图册", detail: { checked: !failed, maps: failed ? [] : [{ node_id: nodeId }] } }],
    unknown_scope: true,
    unsupported: [{ consumer: "map_atlas", reason: "世界对象、世界书页与候选未覆盖" }, { consumer: "world_canon_revision" }],
    coverage_note: failed ? "地图册未核对：来源查询暂时失败，请到地图核对来源" : "仅核对当前已保存地图的已发布正文来源；地图内容未改变",
    recompute_options: [{ kind: "reload_evidence" }, { kind: "rebuild_derived_state" }, { kind: "regenerate_prose" }],
  }
}

test("390px地图来源提示、离开恢复和核对导航", async ({ page, projectFactory }) => {
  const project = await projectFactory({ title: "合成地图来源核对" })
  await createAutosavedDraft(project.id, 1, "东岸", "东岸是港口，所有内容均为合成测试资料。")
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route("**/api/writing/invalidations?**", (route) => route.fulfill({ json: { novel_id: project.id, items: [mapNotice()] } }))
  await page.route("**/api/world/map-atlas/**", (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith("/capabilities")) return route.fulfill({ json: { structure: { available: true }, upload: { available: false }, image_generation: { available: false } } })
    if (path.endsWith("/atlas")) return route.fulfill({ json: { mode: "atlas", total_pages: 0, nodes: [{ id: nodeId, title: "东岸与港口地图", level: "region", current_revision_id: revisionId, pages: [], children: [] }] } })
    if (path.endsWith("/map")) return route.fulfill({ json: { node_id: nodeId, revision: { id: revisionId, status: "saved", document: { features: [], constraints: [], images: [] }, problems: [] }, candidates: [], image_layers: [] } })
    if (path.endsWith("/runs/latest")) return route.fulfill({ json: null })
    return route.fulfill({ json: [] })
  })
  await openWorkbench(page, project, "writing")
  await waitWritingReady(page, { chapter: 1 })
  await page.getByRole("button", { name: /^打开第 1 章/ }).click()
  await waitWritingReady(page, { editor: true })
  const notice = page.getByRole("status", { name: "本次保存的影响范围" })
  await expect(notice).toContainText("东岸与港口地图 · 第 1 章")
  await expect(notice).not.toContainText(nodeId)
  await notice.getByRole("button", { name: "查看受影响与重算选项" }).click()
  const panel = page.getByRole("region", { name: "受影响内容与重算选项" })
  await expect(panel.getByRole("radio")).toHaveCount(3)
  await panel.getByRole("button", { name: "暂不重算" }).click()
  await page.reload()
  await waitWritingReady(page, { chapter: 1 })
  await page.getByRole("button", { name: /^打开第 1 章/ }).click()
  await waitWritingReady(page, { editor: true })
  await expect(notice).toContainText("东岸与港口地图 · 第 1 章")
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: "/tmp/g8-writing-map-390.png", fullPage: true })
  await notice.getByRole("button", { name: "去地图核对" }).click()
  await expect(page).toHaveURL(new RegExp(`map.*node_id=${nodeId}`))
  await expect(page.getByRole("heading", { name: "地图", exact: true })).toBeVisible()
})

test("来源查询失败仍明确显示地图册未核对并保留正文", async ({ page, projectFactory }) => {
  const project = await projectFactory({ title: "合成地图核对失败" })
  await createAutosavedDraft(project.id, 1, "失败回执", "正文不会因地图查询失败丢失。")
  await page.route("**/api/writing/invalidations?**", (route) => route.fulfill({ json: { novel_id: project.id, items: [mapNotice(true)] } }))
  await openWorkbench(page, project, "writing")
  await waitWritingReady(page, { chapter: 1 })
  await page.getByRole("button", { name: /^打开第 1 章/ }).click()
  await waitWritingReady(page, { editor: true })
  await expect(page.getByRole("status", { name: "本次保存的影响范围" })).toContainText("地图册未核对")
  await expect(page.locator("#writing-editor")).toHaveValue("正文不会因地图查询失败丢失。")
  await page.reload()
  await waitWritingReady(page, { chapter: 1 })
  await page.getByRole("button", { name: /^打开第 1 章/ }).click()
  await waitWritingReady(page, { editor: true })
  await expect(page.getByRole("status", { name: "本次保存的影响范围" })).toContainText("地图册未核对")
})
