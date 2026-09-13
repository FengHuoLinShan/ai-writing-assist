import { readFileSync } from "node:fs"
import { test, expect } from "./fixtures.js"
import { API_BASE, createArc } from "./helpers/api-client.js"
import { openWorkbench, openWorkspaceTools } from "./helpers/workbench.js"

const sample = JSON.parse(readFileSync(new URL("./fixtures/unified-map.json", import.meta.url), "utf8"))
const headers = { "X-Requested-With": "XMLHttpRequest" }

test("故事工具按选择切换，缺少总览时引导规划，切模块清理旧工具", async ({ page, projectFactory }) => {
  const project = await projectFactory({ title: "工具栏故事流程" })
  await createArc(project.id, { title: "第一卷 潮起", arc_index: 1, start_chapter: 1, end_chapter: 10 })
  await openWorkbench(page, project, "outline", "arcs")
  const card = page.locator("#sidebar-context-slot .workspace-tools")
  await expect(card).toHaveAttribute("aria-label", "故事工具")
  await expect(card.locator(".workspace-tools__action.btn-primary")).toHaveText("新建篇章")
  await page.locator('[data-action="bulk-toggle-one"]').check()
  await expect(card.locator(".workspace-tools__action.btn-primary")).toContainText("AI 修订所选")
  await card.locator('[data-action="ai-create-outline-arc"]').click()
  await expect(page).toHaveURL(/outline\/story-outline/)
  await expect(card).toContainText("故事总览")
  await expect(card.locator('[data-action="edit-story-outline"]')).toHaveText("手工创建")
  await card.locator('[data-action="edit-story-outline"]').click()
  await page.locator("#story-outline-manual-title-input").fill("未完成的全书方向")
  await expect(card).toContainText("继续编辑并保存")
  await page.reload()
  await expect(page.locator("#story-outline-manual-title-input")).toHaveValue("未完成的全书方向")
  await expect(page.locator("#sidebar-context-slot .workspace-tools")).toHaveCount(1)
  page.once("dialog", dialog => dialog.accept())
  await page.locator('[data-action="close-story-outline-editor"]').click()
  await expect(card).toContainText("继续上次编辑")
  await page.locator('.nav-item[data-view="world"]').click()
  await expect(card).toHaveCount(1)
  await expect(card).toHaveAttribute("aria-label", "资料工具")
})

test("移动故事工具先关闭抽屉，再进入正文整理表单", async ({ page, projectFactory }) => {
  const project = await projectFactory({ title: "工具栏手机整理" })
  await page.setViewportSize({ width: 390, height: 844 })
  await openWorkbench(page, project, "outline", "scenes")
  await expect(page.locator("#sidebar-context-slot .workspace-tools")).toHaveCount(0)
  await openWorkspaceTools(page)
  const drawer = page.getByRole("dialog", { name: "故事工具", exact: true })
  await expect(drawer).toBeVisible()
  await expect(drawer.getByRole("button", { name: "关闭故事工具" })).toBeVisible()
  await drawer.locator('[data-action="scene-auto-extract"]').click()
  await expect(drawer).toHaveCount(0)
  await expect(page.locator("#modal-overlay")).not.toHaveClass(/hidden/)
  await expect(page.locator("#modal-content")).toContainText("章节")
  await expect(page.locator("#workspace [inert]")).toHaveCount(0)
  await page.keyboard.press("Escape")

})

test("地图工具打开原编辑区，保存后可阅读预览，菜单与手机抽屉可用", async ({ page, request, projectFactory }, testInfo) => {
  const project = await projectFactory({ title: "工具栏地图流程" })
  const created = await request.post(API_BASE + "/world/map-atlas/" + project.id + "/nodes", { headers, data: { title: "河谷地图", level: "region" } })
  expect(created.ok()).toBeTruthy()
  const node = await created.json()
  const saved = await request.post(API_BASE + "/world/map-atlas/" + project.id + "/nodes/" + node.id + "/revisions", { headers, data: { base_revision_id: node.current_revision_id, document: sample } })
  expect(saved.ok()).toBeTruthy()
  await openWorkbench(page, project, "map")
  const card = page.locator(".workspace-tools")
  await page.getByRole("button", { name: "临江城", exact: true }).press("Enter")
  await expect(card).toContainText("查证地点依据")
  await card.getByRole("button", { name: "地图工具：更多工具", exact: true }).click()
  await page.getByRole("menuitem", { name: "添加地点与绘制", exact: true }).click()
  await expect(page.locator(".map-edit-grid details").first()).toHaveAttribute("open", "")
  await page.getByRole("button", { name: "临江城", exact: true }).press("Enter")
  await expect(card).toContainText("查证地点依据")
  await page.getByLabel("显示名称", { exact: true }).fill("已核对的河谷地点")
  await expect(card.getByRole("button", { name: "继续编辑并保存", exact: true })).toBeVisible()
  await card.locator('[data-action="map-tool-save-area"]').click()
  await expect(page.getByRole("region", { name: "空间地图编辑器" }).locator(":focus")).toHaveCount(1)
  await page.getByRole("button", { name: "保存地图", exact: true }).click()
  await expect(page.locator(".map-save-status")).toHaveText("已保存到服务端")

  await page.setViewportSize({ width: 1440, height: 650 })
  await card.locator(".action-menu-btn").click()
  const menu = page.getByRole("menu")
  await expect(menu).toBeVisible()

  await page.getByRole("menuitem", { name: "阅读预览", exact: true }).click()
  await page.getByRole("button", { name: "预览读者所见" }).click()
  await expect(card).toContainText("阅读预览")
  await expect(card.getByRole("button", { name: "整理空间关系", exact: true })).toHaveCount(0)
  await expect(card).not.toContainText("查证地点依据")
  await card.locator('[data-action="map-tool-exit-reader"]').click()

  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await openWorkspaceTools(page)
    await expect(page.locator(".workspace-tools")).toHaveCount(1)

    await page.screenshot({ path: testInfo.outputPath("map-tools-" + width + ".png") })
    if (width <= 760) {
      await page.keyboard.press("Escape")
      await expect(page.locator(".workspace-tools-trigger")).toBeFocused()
    }
  }
})
