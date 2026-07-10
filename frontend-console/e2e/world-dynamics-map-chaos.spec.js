import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { installLeafletStub } from "./helpers/leaflet-stub.js"
import { openWorkbench, reloadWorkbench } from "./helpers/workbench.js"
import {
  cleanupProject,
  confirmMapObservation,
  createDraft,
  createEntity,
  createLocationBindings,
  createMap,
  createMapMarker,
  createMapObservation,
  createProject,
  createScene,
  createTerritories,
  getMapDashboard,
  getMapPlayback,
  runMapBatchAction,
  waitForBackend,
} from "./helpers/api-client.js"

const uuidPattern = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i

async function openMapWorkspace(page, project, map, params = {}) {
  const query = new URLSearchParams({
    map_id: map.id,
    mode: params.mode || "dashboard",
  })
  if (params.sceneId) query.set("scene_id", params.sceneId)
  if (params.focusEntityId) query.set("focus_entity_id", params.focusEntityId)
  await page.goto(`/#workbench/${project.id}/map?${query.toString()}`)
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  await expect(page.locator(SEL.viewTitle)).toHaveText("地图", { timeout: 10000 })
  await expect(page.locator("#map-dynamic-summary")).toContainText("世界动态总控台", {
    timeout: 10000,
  })
}

async function createObservation(novelId, mapId, data) {
  return createMapObservation(novelId, mapId, {
    target_entity_id: data.targetEntityId,
    target_entity_type: data.targetEntityType,
    target_name: data.targetName,
    dynamic_type: data.dynamicType,
    time_anchor: {
      scene_id: data.sceneId,
      scene_index: data.sceneIndex,
      chapter_index: 1,
    },
    spatial_anchor: {
      hex_q: data.hexQ ?? 1,
      hex_r: data.hexR ?? 1,
      location_name: data.locationName || "洛阳外城",
    },
    value_json: { state: data.dynamicType, label: data.targetName },
    confidence: data.confidence ?? 0.8,
    source_ref: {
      source: "chaos_e2e",
      chapter_index: 1,
      scene_id: data.sceneId,
    },
    evidence_text: data.evidence || `${data.targetName} 出现在地图上下文。`,
    scene_id: data.sceneId,
    scene_index: data.sceneIndex,
    review_state: data.reviewState,
  })
}

async function seedChaosWorld() {
  const project = await createProject({
    title: "世界动态地图混乱测试",
    genre: "fantasy",
    language: "zh",
  })
  const novelId = project.id
  await createDraft(novelId, 1, "第一章", "沈砚抵达洛阳外城，暗门传闻浮现。")
  const sceneA = await createScene(novelId, {
    scene_index: 1,
    title: "抵达洛阳",
    narrative_tag: "draft",
    chapter_ids: ["1"],
    scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 12 }],
  })
  const sceneB = await createScene(novelId, {
    scene_index: 2,
    title: "夜探东门",
    narrative_tag: "draft",
    chapter_ids: ["1"],
    scene_chunks: [{ chapter_index: 1, start_pos: 12, end_pos: 24 }],
  })
  const sceneC = await createScene(novelId, {
    scene_index: 3,
    title: "洛阳封锁",
    narrative_tag: "draft",
    chapter_ids: ["1"],
    scene_chunks: [{ chapter_index: 1, start_pos: 24, end_pos: 36 }],
  })

  const shen = await createEntity(novelId, {
    name: "沈砚",
    entity_type: "character",
    status: "canonical",
    summary: "主要人物，正在追查东门密道。",
  })
  await createEntity(novelId, { name: "陆青", entity_type: "character", status: "canonical" })
  await createEntity(novelId, { name: "林照", entity_type: "character", status: "canonical" })
  const luoyang = await createEntity(novelId, {
    name: "洛阳外城",
    entity_type: "location",
    status: "canonical",
    summary: "当前 Scene 主地点。",
  })
  await createEntity(novelId, { name: "九州", entity_type: "location", status: "canonical" })
  await createEntity(novelId, { name: "东门", entity_type: "location", status: "canonical" })
  await createEntity(novelId, { name: "城下密室", entity_type: "location", status: "canonical" })
  const beifu = await createEntity(novelId, { name: "北府", entity_type: "organization", status: "canonical" })
  await createEntity(novelId, { name: "天机阁", entity_type: "organization", status: "canonical" })
  await createEntity(novelId, { name: "粮草", entity_type: "resource", status: "canonical" })
  await createEntity(novelId, { name: "灵脉", entity_type: "resource", status: "canonical" })
  await createEntity(novelId, { name: "东门封锁", entity_type: "event", status: "canonical" })

  const map = await createMap(novelId, {
    name: "九州世界动态图",
    map_type: "world",
    grid_width: 12,
    grid_height: 8,
    template: "blank",
  })
  await createLocationBindings(novelId, map.id, {
    location_entity_id: luoyang.id,
    hexes: [{ hex_q: 2, hex_r: 2, is_center: true }],
  })
  await createMapMarker(novelId, map.id, {
    entity_id: shen.id,
    marker_type: "character",
    hex_q: 2,
    hex_r: 2,
    label: "沈砚",
    start_scene_id: sceneA.id,
    start_scene_index: 1,
    visible: true,
  })
  await createTerritories(novelId, map.id, {
    faction_entity_id: beifu.id,
    hexes: [{ hex_q: 3, hex_r: 2 }],
  })

  const high = await createObservation(novelId, map.id, {
    targetEntityId: shen.id,
    targetEntityType: "character",
    targetName: "沈砚",
    dynamicType: "position_change",
    sceneId: sceneA.id,
    sceneIndex: 1,
    confidence: 0.92,
    hexQ: 2,
    hexR: 2,
    locationName: "洛阳外城",
    evidence: "沈砚抵达洛阳外城。",
  })
  const low = await createObservation(novelId, map.id, {
    targetEntityType: "secret",
    targetName: "暗门传闻",
    dynamicType: "secret",
    sceneId: sceneB.id,
    sceneIndex: 2,
    confidence: 0.22,
    hexQ: 2,
    hexR: 3,
    locationName: "东门",
    evidence: "有人提到墙后可能有暗门。",
  })
  const crisis = await createObservation(novelId, map.id, {
    targetEntityType: "location",
    targetName: "洛阳封锁",
    dynamicType: "crisis",
    sceneId: sceneC.id,
    sceneIndex: 3,
    confidence: 0.67,
    hexQ: 2,
    hexR: 2,
    locationName: "洛阳外城",
    evidence: "洛阳外城突然封锁。",
  })
  const conflict = await createObservation(novelId, map.id, {
    targetEntityId: shen.id,
    targetEntityType: "character",
    targetName: "沈砚",
    dynamicType: "position_change",
    sceneId: sceneB.id,
    sceneIndex: 2,
    confidence: 0.71,
    reviewState: "conflicted",
    hexQ: 10,
    hexR: 6,
    locationName: "远山谷",
    evidence: "同一时间出现了远山谷记录。",
  })

  return {
    project,
    map,
    scenes: { sceneA, sceneB, sceneC },
    entities: { shen, luoyang, beifu },
    observations: { high, low, crisis, conflict },
  }
}

async function expectNoOverlaps(locator) {
  const boxes = (await locator.evaluateAll((nodes) =>
    nodes
      .map((node) => {
        const box = node.getBoundingClientRect()
        return {
          text: node.textContent,
          x: box.x,
          y: box.y,
          width: box.width,
          height: box.height,
        }
      })
      .filter((box) => box.width > 0 && box.height > 0)
  ))
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i]
      const b = boxes[j]
      const overlap = a.x < b.x + b.width
        && a.x + a.width > b.x
        && a.y < b.y + b.height
        && a.y + a.height > b.y
      expect(overlap, `${a.text} overlaps ${b.text}`).toBe(false)
    }
  }
}

test.describe("世界动态地图混乱路径", () => {
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

  test("author can traverse dashboard, writing, world object, candidate flow, and view modes", async ({ page }) => {
    const fixture = await seedChaosWorld()
    testProjectId = fixture.project.id

    await openMapWorkspace(page, fixture.project, fixture.map, {
      sceneId: fixture.scenes.sceneB.id,
    })
    const summary = page.locator("#map-dynamic-summary")
    await expect(summary).toContainText("世界动态总控台")
    await expect(summary).toContainText("暗门传闻")
    await expect(summary).toContainText("沈砚")
    await expect(summary).toContainText("待处理")
    await expect(summary).not.toContainText("待确认")
    await expect(summary).toContainText("批量修改")
    await expect(summary).not.toContainText(uuidPattern)

    await summary.locator(".map-dynamic-item", { hasText: "暗门传闻" }).first().click()
    await expect(page.locator(SEL.modalTitle)).toContainText("暗门传闻")
    await expect(page.locator(SEL.modalBody)).toContainText("东门")
    await expect(page.locator(SEL.modalFooter)).toContainText("修改")
    await expect(page.locator(SEL.modalFooter)).toContainText("打开检查器")
    await page.locator(SEL.modalFooter).getByRole("button", { name: "打开检查器" }).click()
    await expect(summary.locator(".map-inspector")).toContainText("暗门传闻", {
      timeout: 10000,
    })

    await summary.locator(".map-dynamic-item", { hasText: "暗门传闻" }).getByRole("button", { name: "忽略" }).click()
    await page.locator(SEL.modalFooter).getByRole("button", { name: "确认" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("地图映射已忽略", {
      timeout: 10000,
    })
    const dashboardAfterIgnore = await getMapDashboard(
      fixture.project.id,
      fixture.map.id,
      { sceneId: fixture.scenes.sceneB.id },
    )
    expect(dashboardAfterIgnore.dynamic_queue.map((item) => item.title)).not.toContain("暗门传闻")

    await confirmMapObservation(fixture.project.id, fixture.map.id, fixture.observations.high.id)
    let playback = await getMapPlayback(fixture.project.id, fixture.map.id, {
      includeCandidates: false,
    })
    expect(playback.events.some((event) => event.title.includes("沈砚"))).toBe(true)
    await runMapBatchAction(fixture.project.id, fixture.map.id, {
      action: "update_fact_status",
      fact_ids: playback.events.map((event) => event.event_id),
      patch: { fact_status: "rolled_back" },
    })
    playback = await getMapPlayback(fixture.project.id, fixture.map.id, {
      includeCandidates: false,
    })
    expect(playback.events.some((event) => event.title.includes("沈砚"))).toBe(false)

    await openWorkbench(page, fixture.project, "writing")
    await reloadWorkbench(page, "writing")
    await page.locator('[data-action="select-scene"]').first().click()
    await expect(page.locator("#writing-panel-container")).toContainText("地图摘要", {
      timeout: 10000,
    })
    await expect(page.locator("#writing-panel-container")).toContainText("洛阳外城")

    await openWorkbench(page, fixture.project, "world", "objects")
    await expect(page.locator(SEL.dataTable)).toContainText("沈砚", { timeout: 10000 })
    const entityRow = page.locator(SEL.tableRow(fixture.entities.shen.id))
    await entityRow.locator(".action-menu-btn").click()
    const popupPromise = page.waitForEvent("popup")
    await entityRow.getByRole("button", { name: "打开地图" }).click()
    const popup = await popupPromise
    await popup.waitForFunction(
      () => typeof state !== "undefined" && !state.loading,
      { timeout: 10000 },
    )
    expect(popup.url()).toContain(`focus_entity_id=${fixture.entities.shen.id}`)
    await expect(popup.locator("#map-dynamic-summary")).toContainText("世界动态总控台", {
      timeout: 10000,
    })
    await popup.close()

    await openMapWorkspace(page, fixture.project, fixture.map)
    await page.waitForFunction(() => Boolean(document.querySelector("[data-view-mode='live']")?.onclick))
    for (const mode of [
      ["live", "活地图"],
      ["lens", "叙事透镜"],
      ["dashboard", "世界动态总控台"],
    ]) {
      const modeButton = page.locator(`[data-view-mode="${mode[0]}"]`)
      await modeButton.click()
      await expect.poll(() => page.evaluate(() => window.mapWorkspaceView?._viewMode)).toBe(mode[0])
      await expect(modeButton).toContainText(mode[1])
      await expect(page.locator("#map-dynamic-summary")).toContainText("洛阳封锁")
    }

    await page.locator('[data-action="map-low-motion-toggle"]').check()
    await expect(page.locator('[data-action="map-low-motion-toggle"]')).toBeChecked()
    await page.getByRole("button", { name: "播放" }).click()
    await expect(page.locator("#map-dynamic-summary")).toContainText("电影化播放")
  })

  test("high-density chaos layout remains readable on desktop and 390px viewport", async ({ page }) => {
    const fixture = await seedChaosWorld()
    testProjectId = fixture.project.id
    for (let index = 0; index < 28; index += 1) {
      await createObservation(fixture.project.id, fixture.map.id, {
        targetEntityType: index % 2 === 0 ? "event" : "resource",
        targetName: `密集对象 ${index}`,
        dynamicType: index % 5 === 0 ? "secret" : "location",
        sceneId: fixture.scenes.sceneC.id,
        sceneIndex: 3,
        confidence: 0.4 + (index % 5) / 10,
        hexQ: 2 + (index % 3),
        hexR: 2 + (index % 3),
        locationName: "洛阳外城",
      })
    }

    for (const viewport of [
      { width: 1280, height: 800 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport)
      await openMapWorkspace(page, fixture.project, fixture.map, {
        sceneId: fixture.scenes.sceneC.id,
      })
      await expect(page.locator("#map-dynamic-summary")).toContainText("密集对象", {
        timeout: 10000,
      })
      await expectNoOverlaps(page.locator(".map-semantic-bubble"))
      await expectNoOverlaps(page.locator(".map-dynamic-item:visible"))
      await expect(page.locator("#map-dynamic-summary")).not.toContainText(uuidPattern)
    }
  })
})
