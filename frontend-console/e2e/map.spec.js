import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { installLeafletStub } from "./helpers/leaflet-stub.js"
import { openWorkbench, reloadWorkbench } from "./helpers/workbench.js"
import { expectNoPageOverflow, expectWithinViewport, runResponsiveMatrix } from "./helpers/responsive.js"
import {
  applyMapEditor,
  cleanupProject,
  createTerritories,
  createDraft,
  createEntity,
  createLocationBindings,
  createMap,
  createMapMarker,
  createProject,
  createScene,
  getFocusState,
  getMapLayerTree,
  getMapPaths,
  getMapState,
  listTerritories,
  listMaps,
  updateMapTerrainLayer,
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
  if (params.focusPathId) query.set("focus_path_id", params.focusPathId)
  if (params.focusLayerNodeId) query.set("focus_layer_node_id", params.focusLayerNodeId)

  await page.goto(`/#workbench/${project.id}/map?${query.toString()}`)
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  await expect(page.locator(SEL.viewTitle)).toHaveText("地图", { timeout: 10000 })
  await expect(page.locator(SEL.mapCanvas)).toBeVisible({ timeout: 10000 })
}

async function clickHex(page, q, r) {
  await page.locator(SEL.mapCanvas).click({ position: hexPosition(q, r) })
}

async function expectMapCanvasAligned(page) {
  const alignment = await page.locator(SEL.mapLeaflet).evaluate((container) => {
    const canvas = container.querySelector('canvas[data-testid="map-canvas"]')
    const overlayPane = container.querySelector(".leaflet-overlay-pane")
    return {
      canvasParentIsContainer: canvas?.parentElement === container,
      canvasInsideMovablePane: overlayPane ? overlayPane.contains(canvas) : false,
      widthMatches: canvas?.offsetWidth === Math.round(container.clientWidth),
      heightMatches: canvas?.offsetHeight === Math.round(container.clientHeight),
      backingWidthMatches: canvas?.width === Math.round(container.clientWidth),
      backingHeightMatches: canvas?.height === Math.round(container.clientHeight),
    }
  })

  expect(alignment).toMatchObject({
    canvasParentIsContainer: true,
    canvasInsideMovablePane: false,
    widthMatches: true,
    heightMatches: true,
    backingWidthMatches: true,
    backingHeightMatches: true,
  })
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

  test("should archive a complete subtree and rename its root on conflicting restore", async ({ page }) => {
    const project = await createProject({
      title: "地图归档 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id
    const root = await createMap(testProjectId, {
      name: "旧九州",
      map_type: "world",
      grid_width: 5,
      grid_height: 5,
      template: "blank",
    })
    await createMap(testProjectId, {
      name: "旧王都",
      map_type: "city",
      grid_width: 4,
      grid_height: 4,
      parent_map_id: root.id,
      template: "blank",
    })

    await openWorkbench(page, project, "map")
    const returnToOverview = page.getByRole("button", { name: "← 返回总览", exact: true })
    if (await returnToOverview.isVisible()) await returnToOverview.click()
    await page.getByRole("button", { name: "归档", exact: true }).first().click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("确认操作")
    await page.locator(SEL.modalFooter).getByRole("button", { name: "归档子树" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("地图子树已归档", {
      timeout: 10000,
    })
    expect((await listMaps(testProjectId)).total).toBe(0)
    expect((await listMaps(testProjectId, { status: "archived" })).total).toBe(2)

    await createMap(testProjectId, {
      name: "旧九州",
      map_type: "world",
      grid_width: 3,
      grid_height: 3,
      template: "blank",
    })
    await reloadWorkbench(page, "map")
    if (await returnToOverview.isVisible()) await returnToOverview.click()
    await page.getByRole("button", { name: /归档地图 2/ }).click()
    await expect(page.getByText("旧九州", { exact: true })).toBeVisible()
    await expect(page.getByText("旧王都", { exact: true })).toHaveCount(0)
    await page.getByRole("button", { name: "恢复子树" }).click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("恢复归档地图")
    await page.locator(SEL.modalFooter).getByRole("button", { name: "恢复子树" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("恢复失败", {
      timeout: 10000,
    })
    await page.locator("#map-restore-root-name").fill("复原九州")
    await page.locator(SEL.modalFooter).getByRole("button", { name: "恢复子树" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("地图子树已恢复", {
      timeout: 10000,
    })
    const activeMaps = await listMaps(testProjectId)
    expect(activeMaps.items.map((item) => item.name)).toEqual(
      expect.arrayContaining(["旧九州", "复原九州", "旧王都"]),
    )
  })

  test("should quick-create a draggable canonical location layout", async ({ page }) => {
    const project = await createProject({
      title: "地图快速创建 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id
    const location = await createEntity(testProjectId, {
      name: "云中城",
      entity_type: "location",
      status: "canonical",
    })

    await openWorkbench(page, project, "map")
    await page.getByRole("button", { name: "快速创建" }).first().click()
    await expect(page.locator("#map-quick-canvas")).toBeVisible()
    await page.locator("#map-quick-name").fill("云中世界图")
    await page.locator('[data-action="map-quick-move"][data-id="' + location.id + '"][data-dq="1"]').click()
    await page.getByRole("button", { name: "创建", exact: true }).last().click()
    await expect(page.locator(SEL.toastContainer)).toContainText("地图已快速创建", {
      timeout: 10000,
    })

    await expect.poll(async () => {
      const maps = (await listMaps(testProjectId)).items || []
      return maps.find((item) => item.name === "云中世界图") || null
    }).not.toBeNull()
    const maps = (await listMaps(testProjectId)).items || []
    const map = maps.find((item) => item.name === "云中世界图")
    const persisted = await getMapState(testProjectId, map.id)
    expect(persisted.location_layouts).toHaveLength(1)
    expect(persisted.location_bindings).toEqual(expect.arrayContaining([
      expect.objectContaining({ location_entity_id: location.id, is_center: true }),
    ]))
  })

  test("should choose among entity map presences and return to the world object", async ({ page }) => {
    const project = await createProject({
      title: "地图双向定位 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id
    const location = await createEntity(testProjectId, {
      name: "双城关隘",
      entity_type: "location",
      status: "canonical",
      summary: "同时出现在世界图和区域图。",
    })
    const worldMap = await createMap(testProjectId, {
      name: "双向世界图",
      map_type: "world",
      grid_width: 6,
      grid_height: 6,
      template: "blank",
    })
    const regionMap = await createMap(testProjectId, {
      name: "双向区域图",
      map_type: "region",
      grid_width: 6,
      grid_height: 6,
      template: "blank",
    })
    await createLocationBindings(testProjectId, worldMap.id, {
      location_entity_id: location.id,
      hexes: [{ hex_q: 1, hex_r: 1, is_center: true }],
    })
    await createLocationBindings(testProjectId, regionMap.id, {
      location_entity_id: location.id,
      hexes: [{ hex_q: 2, hex_r: 2, is_center: true }],
    })

    await openWorkbench(page, project, "world", "objects")
    const entityRow = page.locator(SEL.tableRow(location.id))
    await expect(entityRow).toContainText("双城关隘", { timeout: 10000 })
    await entityRow.locator(".action-menu-btn").click()
    await entityRow.getByRole("button", { name: "打开地图" }).click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("选择关联地图")

    const popupPromise = page.waitForEvent("popup")
    await page.locator(".world-map-presence-row", { hasText: "双向区域图" }).click()
    const popup = await popupPromise
    await popup.waitForFunction(() => typeof state !== "undefined" && !state.loading, {
      timeout: 10000,
    })
    expect(popup.url()).toContain(`map_id=${regionMap.id}`)
    expect(popup.url()).toContain(`focus_entity_id=${location.id}`)
    await expect(popup.locator(SEL.mapCanvas)).toBeVisible({ timeout: 10000 })
    await clickHex(popup, 2, 2)
    await expect(popup.locator(SEL.mapDetailPanel)).toContainText("双城关隘")
    await popup.locator(SEL.mapDetailPanel).getByRole("button", { name: "查看世界对象" }).click()
    await expect(popup.locator(SEL.tableRow(location.id))).toContainText("双城关隘", {
      timeout: 10000,
    })
    await popup.close()
  })

  test("should create and paint a terrain overlay layer", async ({ page }) => {
    const project = await createProject({
      title: "覆盖素材 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id
    const map = await createMap(testProjectId, {
      name: "覆盖素材地图",
      map_type: "world",
      grid_width: 6,
      grid_height: 6,
      template: "blank",
    })

    await openMapWorkspace(page, project, map)
    await page.getByRole("button", { name: "编辑" }).click()
    await page.getByRole("button", { name: "覆盖素材", exact: true }).click()
    await page.getByRole("button", { name: "新建" }).click()
    await page.locator("#map-overlay-new-name").fill("风暴前线")
    await page.getByRole("button", { name: "创建", exact: true }).last().click()
    await expect(page.locator("#map-overlay-new-name")).toBeHidden()
    await expect(page.locator("#map-overlay-layer")).not.toHaveValue("")
    await page.locator("#map-overlay-asset").selectOption("storm")
    await page.locator("#map-overlay-preset").selectOption("high_contrast")
    await page.locator('[data-action="map-overlay-tool"][data-tool="brush"]').click()
    await clickHex(page, 2, 2)
    await page.getByRole("button", { name: "应用当前图层", exact: true }).click()

    await expect.poll(async () => {
      const state = await getMapState(testProjectId, map.id)
      return {
        layers: state.terrain_layers?.length || 0,
        patches: state.terrain_patches?.length || 0,
        asset: state.terrain_layers?.[0]?.terrain_asset_key,
        preset: state.terrain_layers?.[0]?.meta?.preset_key,
      }
    }).toEqual({ layers: 1, patches: 1, asset: "storm", preset: "high_contrast" })
  })

  test("should draw, persist, reload, and focus a continuous path", async ({ page }) => {
    const project = await createProject({
      title: "连续线路 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id
    const map = await createMap(testProjectId, {
      name: "道路与水系地图",
      map_type: "world",
      grid_width: 8,
      grid_height: 8,
      template: "blank",
    })

    await openMapWorkspace(page, project, map)
    await page.getByRole("button", { name: "编辑" }).click()
    await page.getByRole("button", { name: "线路", exact: true }).click()
    await page.getByRole("button", { name: "+ 线路图层" }).click()
    await page.locator("#map-path-layer-name").fill("王国公路")
    await page.locator("#map-path-layer-category").selectOption("transport")
    await page.locator(SEL.modalFooter).getByRole("button", { name: "创建" }).click()
    await expect(page.locator("#map-path-layer")).not.toHaveValue("")

    const canvas = page.locator(SEL.mapCanvas)
    await canvas.scrollIntoViewIfNeeded()
    const box = await canvas.boundingBox()
    expect(box).not.toBeNull()
    const start = hexPosition(1, 1)
    const end = hexPosition(4, 2)
    await page.mouse.move(box.x + start.x, box.y + start.y)
    await page.mouse.down()
    await page.mouse.move(box.x + end.x, box.y + end.y, { steps: 16 })
    await page.mouse.up()

    await expect(page.locator(".map-path-list-row.active")).toContainText("主干道")
    await page.getByRole("button", { name: "应用当前图层", exact: true }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已原子应用 2 个编辑命令", {
      timeout: 10000,
    })

    await expect.poll(async () => {
      const state = await getMapPaths(testProjectId, map.id)
      return state.paths?.length ? state : null
    }).not.toBeNull()
    const pathState = await getMapPaths(testProjectId, map.id)
    expect(pathState.layers).toHaveLength(1)
    expect(pathState.paths[0].nodes.length).toBeGreaterThanOrEqual(2)
    const tree = await getMapLayerTree(testProjectId, map.id)
    const leaf = tree.nodes.find((node) => node.path_layer_id === pathState.layers[0].id)
    expect(leaf).toBeTruthy()

    await openMapWorkspace(page, project, map, {
      focusPathId: pathState.paths[0].id,
      focusLayerNodeId: leaf.id,
    })
    await page.getByRole("button", { name: "编辑" }).click()
    await page.getByRole("button", { name: "线路", exact: true }).click()
    await expect(page.locator(".map-path-list-row.active")).toContainText(pathState.paths[0].name)
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

  test("should keep 200x200 canvas rendering within the same-run uncropped baseline", async ({ page }, testInfo) => {
    test.setTimeout(120000)
    await page.setViewportSize({ width: 1280, height: 720 })
    const project = await createProject({
      title: "地图性能基线 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id
    const map = await createMap(testProjectId, {
      name: "200×200 性能地图",
      map_type: "world",
      grid_width: 200,
      grid_height: 200,
      template: "blank",
    })

    await openMapWorkspace(page, project, map)
    const loadMetrics = await page.evaluate(async () => {
      const { default: mapView } = await import("/views/mapView.js")
      return { ...mapView._performanceMetrics }
    })

    const sample = async (uncropped) => page.evaluate(async ({ uncropped }) => {
      const { default: mapView } = await import("/views/mapView.js")
      const originalPredicate = mapView._viewportPredicate
      if (uncropped) mapView._viewportPredicate = () => () => true
      mapView._renderSubsetCache.clear()
      mapView._performanceFrameDurations = []
      mapView._performanceMetrics.total_frames = 0
      mapView._performanceMetrics.sampled_frames = 0
      mapView._performanceMetrics.average_frame_ms = null
      mapView._performanceMetrics.p95_frame_ms = null
      try {
        for (let frame = 0; frame < 120; frame += 1) {
          await new Promise((resolve) => requestAnimationFrame(() => {
            mapView._redraw()
            resolve()
          }))
        }
        return {
          average_frame_ms: mapView._performanceMetrics.average_frame_ms,
          p95_frame_ms: mapView._performanceMetrics.p95_frame_ms,
          sampled_frames: mapView._performanceMetrics.sampled_frames,
          queued_hex_items: mapView._renderMetrics.queued_hex_items,
          total_hex_items: mapView._renderMetrics.total_hex_items,
        }
      } finally {
        mapView._viewportPredicate = originalPredicate
        mapView._renderSubsetCache.clear()
      }
    }, { uncropped })

    const uncroppedBaseline = await sample(true)
    const optimized = await sample(false)
    const report = {
      browser: "chromium",
      viewport: { width: 1280, height: 720 },
      grid: "200x200",
      warmup_frames: 20,
      sampled_frames: 100,
      load: loadMetrics,
      uncropped_baseline: uncroppedBaseline,
      optimized,
      relative_average: optimized.average_frame_ms / uncroppedBaseline.average_frame_ms,
    }
    await testInfo.attach("map-canvas-performance.json", {
      body: Buffer.from(JSON.stringify(report, null, 2)),
      contentType: "application/json",
    })

    expect(optimized.sampled_frames).toBe(100)
    expect(optimized.queued_hex_items).toBeLessThan(uncroppedBaseline.queued_hex_items)
    expect(optimized.average_frame_ms).toBeLessThanOrEqual(
      uncroppedBaseline.average_frame_ms * 1.2,
    )
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
    await expectMapCanvasAligned(page)
    await page.getByRole("button", { name: "编辑" }).click()
    await expect(page.locator(SEL.mapCanvas)).toBeVisible({ timeout: 10000 })
    await expectMapCanvasAligned(page)

    await page.getByRole("button", { name: "底图地貌" }).click()
    await page.locator(SEL.mapTerrainSelect).selectOption("water")
    await clickHex(page, 1, 1)
    await page.getByRole("button", { name: "应用当前图层", exact: true }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已原子应用 1 个编辑命令", {
      timeout: 10000,
    })
    await expect.poll(async () => {
      const state = await getMapState(testProjectId, map.id)
      return findTile(state, 1, 1)?.terrain_type
    }).toBe("water")

    await page.getByRole("button", { name: "地点", exact: true }).click()
    await page.getByRole("button", { name: "编辑范围" }).click()
    await page.locator(SEL.mapBindSelect).selectOption(location.id)
    await page.locator(SEL.mapBindCenter).check()
    await clickHex(page, 1, 1)
    await page.getByRole("button", { name: "应用当前图层", exact: true }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已原子应用 1 个编辑命令", {
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

    await page.getByRole("button", { name: "保存全部并退出" }).click()
    await expect(page.locator(SEL.mapCanvas)).toBeVisible({ timeout: 10000 })
    await clickHex(page, 1, 1)
    await expect(page.locator(SEL.mapDetailPanel)).toContainText("洛阳外城")
    await expect(page.locator(SEL.mapDetailPanel)).toContainText("城门与市集所在的外城。")
    await expect(page.locator(SEL.mapDetailPanel)).toContainText("绑定格数")
  })

  test("should preserve the second session draft on an editor revision conflict", async ({ page }) => {
    const project = await createProject({
      title: "地图并发编辑 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id
    const map = await createMap(testProjectId, {
      name: "并发地图",
      map_type: "world",
      grid_width: 6,
      grid_height: 6,
      template: "blank",
    })
    const secondPage = await page.context().newPage()
    try {
      await openMapWorkspace(page, project, map)
      await openMapWorkspace(secondPage, project, map)
      for (const currentPage of [page, secondPage]) {
        await currentPage.getByRole("button", { name: "编辑" }).click()
        await currentPage.getByRole("button", { name: "底图地貌" }).click()
      }
      await page.locator(SEL.mapTerrainSelect).selectOption("water")
      await clickHex(page, 1, 1)
      await secondPage.locator(SEL.mapTerrainSelect).selectOption("forest")
      await clickHex(secondPage, 2, 2)

      await Promise.all([
        page.getByRole("button", { name: "应用当前图层" }).click(),
        secondPage.getByRole("button", { name: "应用当前图层" }).click(),
      ])
      await expect.poll(async () => {
        const messages = await Promise.all([
          page.locator(SEL.toastContainer).innerText(),
          secondPage.locator(SEL.toastContainer).innerText(),
        ])
        return {
          success: messages.filter((message) => message.includes("已原子应用")).length,
          conflict: messages.filter((message) => message.includes("草稿已保留")).length,
        }
      }, { timeout: 10000 }).toEqual({ success: 1, conflict: 1 })

      const firstWon = (await page.locator(SEL.toastContainer).innerText())
        .includes("已原子应用")
      const losingPage = firstWon ? secondPage : page
      await expect(losingPage.locator("#map-pending-count")).toContainText("1")

      const persisted = await getMapState(testProjectId, map.id)
      expect(findTile(persisted, 1, 1)?.terrain_type === "water").toBe(firstWon)
      expect(findTile(persisted, 2, 2)?.terrain_type === "forest").toBe(!firstWon)
    } finally {
      await secondPage.close()
    }
  })

  test("should enforce a recursive group lock on legacy visual write routes", async ({ page }) => {
    const project = await createProject({
      title: "地图递归锁 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id
    const character = await createEntity(testProjectId, {
      name: "锁定角色",
      entity_type: "character",
      status: "canonical",
    })
    const organization = await createEntity(testProjectId, {
      name: "锁定组织",
      entity_type: "organization",
      status: "canonical",
    })
    const map = await createMap(testProjectId, {
      name: "递归锁地图",
      map_type: "world",
      grid_width: 6,
      grid_height: 6,
      template: "blank",
    })
    const created = await applyMapEditor(testProjectId, map.id, {
      expected_revision: 0,
      commands: [{
        type: "terrain_layer_create",
        client_id: "storm-layer",
        data: { name: "风暴", terrain_asset_key: "storm" },
      }],
    })
    const terrainLayerId = created.client_id_map["storm-layer"]
    const tree = await getMapLayerTree(testProjectId, map.id)
    const nodes = tree.nodes.map((node) => ({
      id: node.id,
      parent_id: node.parent_id,
      terrain_layer_id: node.terrain_layer_id,
      node_type: node.node_type,
      layer_key: node.layer_key,
      name: node.name,
      visible: node.visible,
      locked: node.locked,
      opacity: node.opacity,
      sort_order: node.sort_order,
      min_zoom: node.min_zoom,
      max_zoom: node.max_zoom,
      meta: node.meta || {},
    }))
    for (const [sortOrder, layerKey] of ["marker", "territory", "terrainOverlay"].entries()) {
      const node = nodes.find((item) => item.layer_key === layerKey)
      node.parent_id = null
      node.parent_client_id = "visual-group"
      node.sort_order = sortOrder
    }
    nodes.push({
      client_id: "visual-group",
      node_type: "group",
      name: "视觉锁定组",
      visible: true,
      locked: true,
      opacity: 1,
      sort_order: 2,
      meta: {},
    })
    await applyMapEditor(testProjectId, map.id, {
      expected_revision: tree.editor_revision,
      commands: [{ type: "layer_tree_replace", nodes }],
    })

    await openMapWorkspace(page, project, map)
    await page.getByRole("button", { name: "编辑" }).click()
    const lockedTree = await getMapLayerTree(testProjectId, map.id)
    for (const layerKey of ["marker", "territory", "terrainOverlay"]) {
      const node = lockedTree.nodes.find((item) => item.layer_key === layerKey)
      await expect(page.locator(`[data-layer-node-id="${node.id}"]`)).toContainText("继承锁定")
    }

    await expect(createMapMarker(testProjectId, map.id, {
      entity_id: character.id,
      marker_type: "character",
      hex_q: 1,
      hex_r: 1,
    })).rejects.toThrow(/\(409\).*map_layer_locked/)
    await expect(createTerritories(testProjectId, map.id, {
      faction_entity_id: organization.id,
      hexes: [{ hex_q: 1, hex_r: 1 }],
    })).rejects.toThrow(/\(409\).*map_layer_locked/)
    await expect(updateMapTerrainLayer(testProjectId, map.id, terrainLayerId, {
      name: "不应改名",
    })).rejects.toThrow(/\(409\).*map_(?:terrain_)?layer_locked/)
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
    await page.getByRole("button", { name: "标记", exact: true }).click()
    await page.locator(SEL.mapMarkerType).selectOption("character")
    await page.locator(SEL.mapMarkerEntity).selectOption(character.id)
    await page.locator(SEL.mapMarkerLabel).fill("沈砚在城门")
    await page.locator(SEL.mapMarkerSceneStart).selectOption(firstScene.id)
    await page.locator(SEL.mapMarkerSceneEnd).selectOption(firstScene.id)
    await clickHex(page, 2, 2)

    await expect(page.locator(SEL.toastContainer)).toContainText("标记已加入草稿", {
      timeout: 10000,
    })
    await page.getByRole("button", { name: "应用当前图层" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已原子应用 1 个编辑命令", {
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
    await page.getByRole("button", { name: "领地", exact: true }).click()
    await page.locator(SEL.mapTerritoryFaction).selectOption(organization.id)
    await page.locator('[data-action="map-territory-mode"][data-mode="paint"]').click()
    await clickHex(page, 3, 2)
    await page.getByRole("button", { name: "应用当前图层", exact: true }).click()

    await expect(page.locator(SEL.toastContainer)).toContainText("已原子应用 1 个编辑命令", {
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
    await page.locator('[data-action="switch-cockpit-tab"][data-tab="map"]').click()
    await expect(page.locator('[data-panel="map"]')).toBeVisible()
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
