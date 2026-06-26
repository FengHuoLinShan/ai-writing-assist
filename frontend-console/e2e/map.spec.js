import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { installLeafletStub } from "./helpers/leaflet-stub.js"
import { openWorkbench, reloadWorkbench } from "./helpers/workbench.js"
import {
  cleanupProject,
  createDraft,
  createEntity,
  createLocationBindings,
  createMap,
  createMapMarker,
  createProject,
  createScene,
  getMapState,
  listMaps,
  waitForBackend,
} from "./helpers/api-client.js"

test.describe("地图一级工作台", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    await installLeafletStub(page.context())
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("should create a world map from the sidebar workspace and persist its state", async ({ page }) => {
    const project = await createProject({
      title: "地图创建 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openWorkbench(page, project, "map")

    await expect(page.locator(SEL.viewTitle)).toHaveText("地图")
    await expect(page.getByRole("button", { name: "创建世界地图" })).toBeVisible()

    await page.getByRole("button", { name: "创建世界地图" }).click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("创建世界地图")

    await page.getByPlaceholder("如：九州世界").fill("九州世界 E2E")
    await page.locator(SEL.modalFooter).getByRole("button", { name: "创建" }).click()

    await expect(page.locator(SEL.toastContainer)).toContainText("世界地图已创建", {
      timeout: 10000,
    })
    await expect(page.locator("#map-leaflet")).toBeVisible({ timeout: 10000 })
    await expect(page.locator(".map-breadcrumb")).toContainText("九州世界 E2E")

    const maps = await listMaps(testProjectId)
    expect(maps.total).toBe(1)
    expect(maps.items[0]).toMatchObject({
      name: "九州世界 E2E",
      map_type: "world",
      grid_width: 30,
      grid_height: 20,
    })

    const state = await getMapState(testProjectId, maps.items[0].id)
    expect(state.map.name).toBe("九州世界 E2E")
    expect(state.tiles).toHaveLength(600)
    expect(state.scene).toBeNull()

    const recent = await page.evaluate((projectId) => {
      return JSON.parse(localStorage.getItem(`novel_map_recent:${projectId}`))
    }, testProjectId)
    expect(recent).toMatchObject({
      mapId: maps.items[0].id,
      name: "九州世界 E2E",
      mapType: "world",
    })
  })

  test("should validate the map name before creating backend records", async ({ page }) => {
    const project = await createProject({
      title: "地图校验 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openWorkbench(page, project, "map")
    await page.getByRole("button", { name: "创建世界地图" }).click()
    await page.locator(SEL.modalFooter).getByRole("button", { name: "创建" }).click()

    await expect(page.locator(SEL.toastContainer)).toContainText("请输入地图名称", {
      timeout: 10000,
    })
    await expect(page.locator(SEL.modalTitle)).toHaveText("创建世界地图")

    const maps = await listMaps(testProjectId)
    expect(maps.total).toBe(0)
  })

  test("should clear a stale recent map and show a fallback warning", async ({ page }) => {
    const project = await createProject({
      title: "最近地图回退 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openWorkbench(page, project, "map")
    await page.evaluate((projectId) => {
      localStorage.setItem(`novel_map_recent:${projectId}`, JSON.stringify({
        mapId: "00000000-0000-0000-0000-000000000000",
        name: "已删除地图",
        mapType: "world",
      }))
    }, testProjectId)

    await page.getByRole("button", { name: "打开最近地图" }).click()

    await expect(page.locator(SEL.toastContainer)).toContainText(
      "最近地图不可用，已返回地图总览",
      { timeout: 10000 },
    )
    await expect(page.locator(SEL.workspaceContent)).toContainText(
      "最近地图不可用，已返回地图总览",
    )
    await expect(page.locator(SEL.workspaceContent)).toContainText("空间总览")

    const recent = await page.evaluate((projectId) => {
      return localStorage.getItem(`novel_map_recent:${projectId}`)
    }, testProjectId)
    expect(recent).toBeNull()
  })
})

test.describe("写作页地图入口", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    await installLeafletStub(page.context())
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("should render the current scene map summary and open the map in a new tab", async ({ page }) => {
    const project = await createProject({
      title: "写作页地图入口 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await createDraft(testProjectId, 1, "第一章", "沈砚抵达洛阳外城。")
    const scene = await createScene(testProjectId, {
      scene_index: 0,
      title: "抵达洛阳",
      narrative_tag: "draft",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 10 }],
    })
    const location = await createEntity(testProjectId, {
      name: "洛阳外城",
      entity_type: "location",
      status: "canonical",
      summary: "城门与市集所在的外城。",
    })
    const character = await createEntity(testProjectId, {
      name: "沈砚",
      entity_type: "character",
      status: "canonical",
    })
    const map = await createMap(testProjectId, {
      name: "九州世界",
      map_type: "world",
      grid_width: 5,
      grid_height: 5,
      template: "blank",
    })
    await createLocationBindings(testProjectId, map.id, {
      location_entity_id: location.id,
      hexes: [{ hex_q: 0, hex_r: 0, is_center: true }],
    })
    await createMapMarker(testProjectId, map.id, {
      entity_id: character.id,
      marker_type: "character",
      hex_q: 0,
      hex_r: 0,
      label: "沈砚",
      start_scene_id: scene.id,
      start_scene_index: 0,
      visible: true,
    })

    await openWorkbench(page, project, "writing")
    await reloadWorkbench(page, "writing")
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)

    await page.locator('[data-action="select-scene"]').first().click()
    await expect(page.locator("#writing-panel-container")).toContainText("抵达洛阳")
    await expect(page.locator("#writing-panel-container")).toContainText("地图摘要", {
      timeout: 10000,
    })
    await expect(page.locator("#writing-panel-container")).toContainText("洛阳外城", {
      timeout: 10000,
    })
    await expect(page.locator("#writing-panel-container")).toContainText("沈砚")

    const popupPromise = page.waitForEvent("popup")
    await page.getByRole("button", { name: "打开地图" }).click()
    const popup = await popupPromise
    await popup.waitForLoadState("domcontentloaded")
    await popup.waitForFunction(() => !state.loading, { timeout: 10000 })

    expect(popup.url()).toContain(`#workbench/${project.id}/map?map_id=${map.id}`)
    expect(popup.url()).toContain(`scene_id=${scene.id}`)
    expect(popup.url()).toContain("mode=map")
    await expect(popup.locator(SEL.viewTitle)).toHaveText("地图")
    await expect(popup.locator("#map-leaflet")).toBeVisible({ timeout: 10000 })

    await popup.close()
  })
})
