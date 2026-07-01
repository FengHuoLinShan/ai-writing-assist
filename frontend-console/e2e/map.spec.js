import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { installLeafletStub } from "./helpers/leaflet-stub.js"
import { openWorkbench, reloadWorkbench } from "./helpers/workbench.js"
import { expectNoPageOverflow, expectWithinViewport, runResponsiveMatrix } from "./helpers/responsive.js"
import {
  cleanupProject,
  createDraft,
  createEntity,
  createLocationBindings,
  createMap,
  createMapMarker,
  createProject,
  createScene,
  getFocusState,
  getMapState,
  listTerritories,
  listMaps,
  waitForBackend,
} from "./helpers/api-client.js"

const LEAFLET_ORIGIN = 60

function hexPosition(q, r, size = 30) {
  return {
    x: LEAFLET_ORIGIN + size * 1.5 * q,
    y: LEAFLET_ORIGIN + size * Math.sqrt(3) * (r + q / 2),
  }
}

function findTile(mapState, q, r) {
  return (mapState.tiles || []).find((tile) => tile.hex_q === q && tile.hex_r === r)
}

async function openMapWorkspace(page, project, map, params = {}) {
  await openWorkbench(page, project, "map")
  const query = new URLSearchParams({
    map_id: map.id,
    mode: "map",
  })
  if (params.sceneId) query.set("scene_id", params.sceneId)
  if (params.focusEntityId) query.set("focus_entity_id", params.focusEntityId)

  await page.goto(`/#workbench/${project.id}/map?${query.toString()}`)
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  await expect(page.locator(SEL.viewTitle)).toHaveText("地图", { timeout: 10000 })
  await expect(page.locator(SEL.mapCanvas)).toBeVisible({ timeout: 10000 })
}

async function clickHex(page, q, r) {
  await page.locator(SEL.mapCanvas).click({ position: hexPosition(q, r) })
}

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
    await expect(page.locator(SEL.mapLeaflet)).toBeVisible({ timeout: 10000 })
    await expect(page.locator(SEL.mapBreadcrumb)).toContainText("九州世界 E2E")

    await runResponsiveMatrix(page, async () => {
      await expectNoPageOverflow(page)
      await expectWithinViewport(page.locator(".map-toolbar").last())
      await expect(page.locator(SEL.mapLeaflet)).toBeVisible()
    })

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

  test("should persist terrain edits and center location bindings from the editor", async ({ page }) => {
    const project = await createProject({
      title: "地图编辑落库 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    const location = await createEntity(testProjectId, {
      name: "洛阳外城",
      entity_type: "location",
      status: "canonical",
      summary: "城门与市集所在的外城。",
    })
    const map = await createMap(testProjectId, {
      name: "九州世界编辑图",
      map_type: "world",
      grid_width: 6,
      grid_height: 6,
      template: "blank",
    })

    await openMapWorkspace(page, project, map)
    await page.getByRole("button", { name: "编辑" }).click()
    await expect(page.locator(SEL.mapCanvas)).toBeVisible({ timeout: 10000 })

    await page.locator(SEL.mapTerrainSelect).selectOption("water")
    await clickHex(page, 1, 1)
    await page.getByRole("button", { name: "应用" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已应用 1 个变更", {
      timeout: 10000,
    })
    await expect.poll(async () => {
      const state = await getMapState(testProjectId, map.id)
      return findTile(state, 1, 1)?.terrain_type
    }).toBe("water")

    await page.getByRole("button", { name: "地点绑定" }).click()
    await page.locator(SEL.mapBindSelect).selectOption(location.id)
    await page.locator(SEL.mapBindCenter).check()
    await clickHex(page, 1, 1)
    await page.getByRole("button", { name: "应用" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已应用 1 个变更", {
      timeout: 10000,
    })
    await expect.poll(async () => {
      const state = await getMapState(testProjectId, map.id)
      return state.location_bindings.some((binding) =>
        binding.location_entity_id === location.id &&
        binding.hex_q === 1 &&
        binding.hex_r === 1 &&
        binding.is_center === true
      )
    }).toBe(true)

    await page.getByRole("button", { name: "保存并退出编辑" }).click()
    await expect(page.locator(SEL.mapCanvas)).toBeVisible({ timeout: 10000 })
    await clickHex(page, 1, 1)
    await expect(page.locator(SEL.mapDetailPanel)).toContainText("洛阳外城")
    await expect(page.locator(SEL.mapDetailPanel)).toContainText("城门与市集所在的外城。")
    await expect(page.locator(SEL.mapDetailPanel)).toContainText("绑定格数")
  })

  test("should create a generated detail map from a bound location", async ({ page }) => {
    const project = await createProject({
      title: "地图详图 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    const location = await createEntity(testProjectId, {
      name: "洛阳外城",
      entity_type: "location",
      status: "canonical",
      summary: "城门与市集所在的外城。",
    })
    const map = await createMap(testProjectId, {
      name: "九州世界详图入口",
      map_type: "world",
      grid_width: 5,
      grid_height: 5,
      template: "blank",
    })
    await createLocationBindings(testProjectId, map.id, {
      location_entity_id: location.id,
      hexes: [{ hex_q: 0, hex_r: 0, is_center: true }],
    })

    await openMapWorkspace(page, project, map)
    await clickHex(page, 0, 0)
    await expect(page.locator(SEL.mapDetailPanel)).toContainText("洛阳外城")
    await page.locator(SEL.mapDetailPanel).getByRole("button", { name: "创建详图" }).click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("确认操作")
    await page.locator(SEL.modalFooter).getByRole("button", { name: "创建详图" }).click()

    await expect(page.locator(SEL.modalTitle)).toHaveText("创建地点详图")
    await page.locator(SEL.mapDetailName).fill("洛阳外城详图")
    await page.locator(SEL.mapDetailAutogen).selectOption("1")
    await page.locator(SEL.modalFooter).getByRole("button", { name: "创建" }).click()

    await expect(page.locator(SEL.toastContainer)).toContainText("详图已创建", {
      timeout: 10000,
    })
    await expect(page.locator(SEL.mapBreadcrumb)).toContainText("洛阳外城详图", {
      timeout: 10000,
    })

    const maps = await listMaps(testProjectId)
    const detail = maps.items.find((item) => item.name === "洛阳外城详图")
    expect(detail).toMatchObject({
      map_type: "city",
      parent_map_id: map.id,
      parent_entity_id: location.id,
    })

    await expect.poll(async () => {
      const state = await getMapState(testProjectId, detail.id)
      return [...new Set(state.tiles.map((tile) => tile.terrain_type))]
    }).toContain("city")
  })

  test("should attach scene-scoped markers and switch the scene timeline", async ({ page }) => {
    const project = await createProject({
      title: "地图 Scene 标记 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    const firstScene = await createScene(testProjectId, {
      scene_index: 0,
      title: "抵达洛阳",
      narrative_tag: "draft",
      chapter_ids: [],
      scene_chunks: [],
    })
    const secondScene = await createScene(testProjectId, {
      scene_index: 1,
      title: "夜探城门",
      narrative_tag: "draft",
      chapter_ids: [],
      scene_chunks: [],
    })
    const character = await createEntity(testProjectId, {
      name: "沈砚",
      entity_type: "character",
      status: "canonical",
    })
    const map = await createMap(testProjectId, {
      name: "九州 Scene 图",
      map_type: "world",
      grid_width: 6,
      grid_height: 6,
      template: "blank",
    })

    await openMapWorkspace(page, project, map, { sceneId: firstScene.id })
    await expect(page.locator(SEL.mapSceneLabel)).toContainText("Scene 0: 抵达洛阳")

    await page.getByRole("button", { name: "编辑" }).click()
    await page.getByRole("button", { name: "标记" }).click()
    await page.locator(SEL.mapMarkerType).selectOption("character")
    await page.locator(SEL.mapMarkerEntity).selectOption(character.id)
    await page.locator(SEL.mapMarkerLabel).fill("沈砚在城门")
    await page.locator(SEL.mapMarkerSceneStart).selectOption(firstScene.id)
    await page.locator(SEL.mapMarkerSceneEnd).selectOption(firstScene.id)
    await clickHex(page, 2, 2)

    await expect(page.locator(SEL.toastContainer)).toContainText("标记已添加", {
      timeout: 10000,
    })
    await expect.poll(async () => {
      const state = await getMapState(testProjectId, map.id, firstScene.id)
      return state.markers.some((marker) =>
        marker.entity_id === character.id &&
        marker.label === "沈砚在城门" &&
        marker.hex_q === 2 &&
        marker.hex_r === 2 &&
        marker.start_scene_id === firstScene.id &&
        marker.end_scene_id === firstScene.id
      )
    }).toBe(true)
    await expect.poll(async () => {
      const state = await getMapState(testProjectId, map.id, secondScene.id)
      return state.markers.some((marker) => marker.label === "沈砚在城门")
    }).toBe(false)

    await page.locator(SEL.mapSceneBar).getByRole("button", { name: "→" }).click()
    await expect(page.locator(SEL.mapSceneLabel)).toContainText("Scene 1: 夜探城门", {
      timeout: 10000,
    })
    await page.locator(SEL.mapSceneBar).getByRole("button", { name: "清除" }).click()
    await expect(page.locator(SEL.mapSceneLabel)).toHaveText("选择 Scene", {
      timeout: 10000,
    })
  })

  test("should paint organization territory and expose focus state", async ({ page }) => {
    const project = await createProject({
      title: "地图势力聚焦 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    const organization = await createEntity(testProjectId, {
      name: "北府",
      entity_type: "organization",
      status: "canonical",
    })
    const otherOrganization = await createEntity(testProjectId, {
      name: "南衙",
      entity_type: "organization",
      status: "canonical",
    })
    const map = await createMap(testProjectId, {
      name: "九州势力图",
      map_type: "world",
      grid_width: 6,
      grid_height: 6,
      template: "blank",
    })

    await openMapWorkspace(page, project, map)
    await page.getByRole("button", { name: "编辑" }).click()
    await page.locator(SEL.mapTerritoryFaction).selectOption(organization.id)
    await page.getByRole("button", { name: "绘制" }).click()
    await clickHex(page, 3, 2)

    await expect(page.locator(SEL.toastContainer)).toContainText("势力范围已更新", {
      timeout: 10000,
    })
    await expect.poll(async () => {
      const territories = await listTerritories(testProjectId, map.id)
      return territories.some((territory) =>
        territory.faction_entity_id === organization.id &&
        territory.hex_q === 3 &&
        territory.hex_r === 2
      )
    }).toBe(true)

    const focused = await getFocusState(testProjectId, map.id, organization.id)
    expect(focused.territories).toHaveLength(1)
    expect(focused.territories[0]).toMatchObject({
      faction_entity_id: organization.id,
      hex_q: 3,
      hex_r: 2,
    })

    const otherFocused = await getFocusState(testProjectId, map.id, otherOrganization.id)
    expect(otherFocused.territories).toHaveLength(0)

    await page.locator(SEL.mapFactionBar).getByText("北府").click()
    await expect(page.locator(SEL.mapFactionBar)).toContainText("清除聚焦", {
      timeout: 10000,
    })
    await page.locator(SEL.mapFactionBar).getByRole("button", { name: "清除聚焦" }).click()
    await expect(page.locator(SEL.mapFactionBar)).not.toContainText("清除聚焦", {
      timeout: 10000,
    })
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
    await expect(popup.locator(SEL.mapLeaflet)).toBeVisible({ timeout: 10000 })

    await popup.close()
  })
})
