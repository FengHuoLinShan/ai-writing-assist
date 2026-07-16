import { expect, test } from "@playwright/test"

import {
  cleanupProject,
  confirmMapObservation,
  createEntity,
  createMap,
  createMapObservation,
  createProject,
  createScene,
  waitForBackend,
} from "./helpers/api-client.js"
import { installLeafletStub } from "./helpers/leaflet-stub.js"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"

async function openMapWorkspace(page, project, map) {
  await openWorkbench(page, project, "map")
  await page.goto(`/#workbench/${project.id}/map?map_id=${map.id}&mode=map`)
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  await expect(page.locator(SEL.viewTitle)).toHaveText("地图", { timeout: 10000 })
  await expect(page.locator(SEL.mapCanvas)).toBeVisible({ timeout: 10000 })
}

async function createConfirmedLocationFact({
  novelId,
  mapId,
  character,
  location,
  scene,
  q,
  r,
}) {
  const observation = await createMapObservation(novelId, mapId, {
    target_entity_id: character.id,
    target_entity_type: "character",
    target_name: character.name,
    dynamic_type: "location",
    time_anchor: { kind: "initial_state", scene_index: scene.scene_index },
    spatial_anchor: {
      location_entity_id: location.id,
      hex_q: q,
      hex_r: r,
    },
    value_json: {
      schema_version: 1,
      type: "location",
      location_entity_id: location.id,
      movement_mode: "walk",
    },
    confidence: 1,
    review_state: "candidate",
    source_ref: { source: "map_dynamic_timeline_e2e" },
    scene_id: scene.id,
    scene_index: scene.scene_index,
  })
  return confirmMapObservation(novelId, mapId, observation)
}

test.describe("地图 Scene 动态时间轴", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    await installLeafletStub(page.context())
  })

  test.afterEach(async () => {
    if (!testProjectId) return
    try { await cleanupProject(testProjectId) } catch {}
    testProjectId = null
  })

  test("keeps candidates read-only while stepping non-contiguous Scene state", async ({ page }) => {
    const project = await createProject({
      title: "地图动态时间轴 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id
    const map = await createMap(project.id, {
      name: "Scene 动态图",
      map_type: "world",
      grid_width: 12,
      grid_height: 12,
      template: "blank",
    })
    const character = await createEntity(project.id, {
      name: "巡夜人",
      entity_type: "character",
      status: "canonical",
    })
    const eastGate = await createEntity(project.id, {
      name: "东门",
      entity_type: "location",
      status: "canonical",
    })
    const westGate = await createEntity(project.id, {
      name: "西门",
      entity_type: "location",
      status: "canonical",
    })
    const scene2 = await createScene(project.id, {
      scene_index: 2,
      title: "东门巡查",
      narrative_tag: "draft",
      chapter_ids: [],
      scene_chunks: [],
    })
    const scene9 = await createScene(project.id, {
      scene_index: 9,
      title: "西门告警",
      narrative_tag: "draft",
      chapter_ids: [],
      scene_chunks: [],
    })

    await createConfirmedLocationFact({
      novelId: project.id,
      mapId: map.id,
      character,
      location: eastGate,
      scene: scene2,
      q: 1,
      r: 1,
    })
    await createConfirmedLocationFact({
      novelId: project.id,
      mapId: map.id,
      character,
      location: westGate,
      scene: scene9,
      q: 6,
      r: 2,
    })
    await createMapObservation(project.id, map.id, {
      target_name: "未经确认的警戒",
      dynamic_type: "status",
      time_anchor: { scene_index: 9 },
      spatial_anchor: { hex_q: 6, hex_r: 2 },
      value_json: {
        schema_version: 1,
        type: "status",
        field_key: "警戒",
        value: "临时封锁",
      },
      confidence: 0.7,
      review_state: "candidate",
      source_ref: { source: "map_dynamic_timeline_e2e" },
      scene_id: scene9.id,
      scene_index: 9,
    })

    await openMapWorkspace(page, project, map)

    const timeline = page.locator(".map-timeline-panel")
    await expect(timeline).toBeVisible({ timeout: 10000 })
    const sceneSelect = timeline.getByLabel("选择 Scene")
    await expect(sceneSelect).toHaveValue("1")
    await expect(sceneSelect.locator("option:checked")).toHaveText("Scene 9")
    await expect(timeline.locator(".map-timeline-state")).toContainText("巡夜人")
    await expect(timeline).toContainText("待处理内容默认隐藏")
    await expect(timeline).not.toContainText("未经确认的警戒")

    await timeline.getByLabel("待处理预览").check()
    await expect(timeline.locator(".map-timeline-candidates")).toContainText(
      "未经确认的警戒",
      { timeout: 10000 },
    )
    await expect(timeline.locator(".map-timeline-candidates")).toContainText("只读预览")
    await expect(timeline.locator(".map-timeline-state")).toContainText("巡夜人")

    await timeline.getByRole("button", { name: "上一个 Scene" }).click()
    await expect(sceneSelect).toHaveValue("0")
    await expect(sceneSelect.locator("option:checked")).toHaveText("Scene 2")
    await expect(timeline.locator(".map-timeline-state")).toContainText("巡夜人")
    await expect(page.locator(".map-continuity-panel")).toContainText("空间连续性")
    await expect(page.locator(".map-continuity-panel")).toContainText("没有完整接入当前线路图")
  })
})
