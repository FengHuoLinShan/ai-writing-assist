import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { installLeafletStub } from "./helpers/leaflet-stub.js"
import { openWorkbench } from "./helpers/workbench.js"
import { expectNoPageOverflow, expectWithinViewport } from "./helpers/responsive.js"
import {
  cleanupProject,
  createEntity,
  createLocationBindings,
  createMap,
  createMapObservation,
  createProject,
  createTerritories,
  getMapState,
  listMaps,
  listTerritories,
  waitForBackend,
} from "./helpers/api-client.js"

const MOBILE_VIEWPORT = { width: 390, height: 844 }

async function openMapWorkspace(page, project, map) {
  await openWorkbench(page, project, "map")
  await page.goto(`/#workbench/${project.id}/map?map_id=${map.id}&mode=live`)
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  await expect(page.locator(SEL.viewTitle)).toHaveText("地图", { timeout: 10000 })
  await expect(page.locator(SEL.mapCanvas)).toBeVisible({ timeout: 10000 })
}

async function expectMobileWorkspaceFits(page) {
  expect(await page.evaluate(() => ({ width: innerWidth, height: innerHeight })))
    .toEqual(MOBILE_VIEWPORT)
  await expectNoPageOverflow(page)
}

test.use({ viewport: MOBILE_VIEWPORT, hasTouch: true })

test.describe("390px 地图浏览与桌面端编辑转交", () => {
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

  test("保留触控浏览和只读摘要，不在窄屏暴露复杂编辑", async ({ page }) => {
    const project = await createProject({
      title: "移动端地图转交 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id
    const map = await createMap(testProjectId, {
      name: "移动端浏览图",
      map_type: "world",
      grid_width: 8,
      grid_height: 8,
      template: "blank",
    })
    const location = await createEntity(testProjectId, {
      name: "触控港口",
      entity_type: "location",
      status: "canonical",
    })
    const faction = await createEntity(testProjectId, {
      name: "海风盟",
      entity_type: "organization",
      status: "canonical",
    })
    await createLocationBindings(testProjectId, map.id, {
      location_entity_id: location.id,
      hexes: [{ hex_q: 1, hex_r: 1, is_center: true }],
    })
    await createTerritories(testProjectId, map.id, {
      faction_entity_id: faction.id,
      hexes: [{ hex_q: 2, hex_r: 2 }],
    })

    const before = await getMapState(testProjectId, map.id)
    const territoriesBefore = await listTerritories(testProjectId, map.id)
    await openMapWorkspace(page, project, map)
    await expectMobileWorkspaceFits(page)

    const handoff = page.getByRole("note")
    await expect(handoff).toContainText("移动端为浏览模式")
    await expect(handoff).toContainText("1 个势力格")
    await expect(handoff).toContainText("线路节点精修")
    await expect(page.getByRole("button", { name: "请在桌面端编辑" })).toBeVisible()
    await expect(page.getByRole("button", { name: "编辑", exact: true })).toHaveCount(0)
    await expect(page.locator(".map-edit-panel")).toHaveCount(0)

    const label = page.locator(
      `.map-center-label[data-id="${location.id}"]`,
    )
    await expect(label).toBeVisible()
    const labelBox = await label.boundingBox()
    expect(labelBox).not.toBeNull()
    await page.touchscreen.tap(
      labelBox.x + labelBox.width / 2,
      labelBox.y + labelBox.height / 2,
    )
    await expect(page.locator(SEL.mapDetailPanel)).toContainText("触控港口")

    const canvas = page.locator(SEL.mapCanvas)
    await canvas.scrollIntoViewIfNeeded()
    await expectWithinViewport(canvas)
    const canvasBox = await canvas.boundingBox()
    expect(canvasBox).not.toBeNull()
    const cdp = await page.context().newCDPSession(page)
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchStart",
      touchPoints: [{ x: canvasBox.x + 40, y: canvasBox.y + 80 }],
    })
    for (let step = 1; step <= 8; step += 1) {
      await cdp.send("Input.dispatchTouchEvent", {
        type: "touchMove",
        touchPoints: [{
          x: canvasBox.x + 40 + (70 * step) / 8,
          y: canvasBox.y + 80 + (40 * step) / 8,
        }],
      })
    }
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] })
    await expect(canvas).toBeVisible()
    await expectMobileWorkspaceFits(page)

    await page.getByRole("button", { name: "请在桌面端编辑" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText(
      "复杂地图编辑请在桌面端继续",
    )

    const after = await getMapState(testProjectId, map.id)
    const territoriesAfter = await listTerritories(testProjectId, map.id)
    expect(after.map.editor_revision).toBe(before.map.editor_revision)
    expect(after.tiles).toHaveLength(before.tiles.length)
    expect(after.location_bindings).toEqual(before.location_bindings)
    expect(territoriesAfter).toEqual(territoriesBefore)
  })

  test("390px 下 quick-create 可调整预览并确认创建", async ({ page }) => {
    const project = await createProject({
      title: "移动端快速创建 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id
    const location = await createEntity(testProjectId, {
      name: "移动云港",
      entity_type: "location",
      status: "canonical",
    })

    await openWorkbench(page, project, "map")
    await page.getByRole("button", { name: "快速创建" }).first().click()
    const quickDialog = page.getByRole("dialog", { name: "快速创建地图" })
    const preview = quickDialog.getByLabel("地点布局画布")
    await preview.scrollIntoViewIfNeeded()
    await expect(preview).toBeVisible()
    await expectWithinViewport(preview)
    await quickDialog.locator("#map-quick-name").fill("移动云港世界图")
    const locationRow = quickDialog.getByRole("row").filter({ hasText: location.name })
    const initialCoordinates = (await locationRow.locator("td").nth(2).textContent())
      .split(",")
      .map((value) => Number(value.trim()))
    expect(initialCoordinates).toHaveLength(2)
    expect(initialCoordinates.every(Number.isFinite)).toBe(true)
    const moveButton = locationRow.getByRole("button", { name: "向右移动地点 移动云港", exact: true })
    const radiusButton = locationRow.getByRole("button", { name: "扩大地点 移动云港 的半径", exact: true })
    const lockButton = locationRow.getByRole("button", { name: "锁定地点 移动云港", exact: true })
    for (const control of [moveButton, radiusButton, lockButton]) {
      const box = await control.boundingBox()
      expect(box).not.toBeNull()
      expect(box.width).toBeGreaterThanOrEqual(40)
      expect(box.height).toBeGreaterThanOrEqual(40)
    }
    await moveButton.tap()
    const createButton = quickDialog.getByRole("button", { name: "创建", exact: true })
    await createButton.scrollIntoViewIfNeeded()
    const createBox = await createButton.boundingBox()
    expect(createBox).not.toBeNull()
    expect(createBox.height).toBeGreaterThanOrEqual(44)
    await expectMobileWorkspaceFits(page)
    await createButton.click()
    await expect(page.locator(SEL.toastContainer)).toContainText("地图已快速创建", {
      timeout: 10000,
    })

    await expect.poll(async () => {
      const maps = (await listMaps(testProjectId)).items || []
      return maps.find((item) => item.name === "移动云港世界图") || null
    }).not.toBeNull()
    const maps = (await listMaps(testProjectId)).items || []
    const map = maps.find((item) => item.name === "移动云港世界图")
    const persisted = await getMapState(testProjectId, map.id)
    expect(persisted.location_layouts).toHaveLength(1)
    expect(persisted.location_layouts[0]).toEqual(expect.objectContaining({
      location_entity_id: location.id,
      center_hex_q: initialCoordinates[0] + 1,
      center_hex_r: initialCoordinates[1],
    }))
    expect(persisted.location_bindings).toEqual(expect.arrayContaining([
      expect.objectContaining({ location_entity_id: location.id, is_center: true }),
    ]))
  })

  test("势力待处理项在 390px 只显示桌面端空间编辑转交", async ({ page }) => {
    const project = await createProject({
      title: "移动端势力审核 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id
    const map = await createMap(testProjectId, {
      name: "移动端势力图",
      map_type: "world",
      grid_width: 8,
      grid_height: 8,
      template: "blank",
    })
    const faction = await createEntity(testProjectId, {
      name: "海风盟",
      entity_type: "organization",
      status: "canonical",
    })
    await createMapObservation(testProjectId, map.id, {
      target_entity_id: faction.id,
      target_entity_type: "organization",
      target_name: faction.name,
      dynamic_type: "boundary",
      time_anchor: { kind: "initial_state" },
      value_json: {
        payload_kind: "proposal",
        schema_version: 1,
        proposal_type: "boundary",
        controller_name: faction.name,
        area_description: "东部港口",
      },
      source_ref: { source: "e2e_fixture" },
      evidence_text: "海风盟控制东部港口。",
      confidence: 0.8,
    })

    await openMapWorkspace(page, project, map)
    const viewModeGroup = page.getByRole("group", { name: "地图视图" })
    const dashboardButton = viewModeGroup.getByRole("button", {
      name: "世界动态总控台",
      exact: true,
    })
    const liveButton = viewModeGroup.getByRole("button", { name: "活地图", exact: true })
    await expect(liveButton).toHaveAttribute("aria-pressed", "true")
    await expect(dashboardButton).toHaveAttribute("aria-pressed", "false")
    await dashboardButton.click()
    await expect(dashboardButton).toHaveClass(/is-active/)
    await expect(dashboardButton).toHaveAttribute("aria-pressed", "true")
    await expect(liveButton).toHaveAttribute("aria-pressed", "false")
    await page.locator('summary[aria-label="展开动态摘要"]').click()
    const dynamicQueue = page.locator(".map-dynamic-section").filter({
      has: page.getByRole("heading", { name: "动态队列", exact: true }),
    })
    const candidate = dynamicQueue.locator(".map-dynamic-item").filter({ hasText: faction.name })
    await expect(candidate).toBeVisible({ timeout: 10000 })
    const candidateTitle = candidate.getByRole("button", { name: faction.name, exact: true })
    await candidateTitle.focus()
    await expectWithinViewport(candidateTitle)
    await page.keyboard.press("Space")
    const detailDialog = page.getByRole("dialog", { name: faction.name })
    await expect(detailDialog).toBeVisible()
    await expectMobileWorkspaceFits(page)
    await detailDialog.getByRole("button", { name: "修改", exact: true }).click()

    const editDialog = page.getByRole("dialog", { name: "修改地图对象" })
    await expect(editDialog).toBeVisible()
    await expect(editDialog.locator(".map-boundary-spatial-field")).toBeHidden()
    await expect(editDialog.locator(".map-boundary-mobile-handoff")).toBeVisible()
    await expect(editDialog.locator(".map-boundary-mobile-handoff")).toContainText("请在桌面端继续")
    const saveButton = editDialog.getByRole("button", { name: "保存", exact: true })
    const saveBox = await saveButton.boundingBox()
    expect(saveBox).not.toBeNull()
    expect(saveBox.height).toBeGreaterThanOrEqual(44)
    await expectMobileWorkspaceFits(page)
  })
})
