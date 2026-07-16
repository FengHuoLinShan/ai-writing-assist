import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { installLeafletStub } from "./helpers/leaflet-stub.js"
import { openWorkbench, reloadWorkbench } from "./helpers/workbench.js"
import {
  createProject,
  cleanupProject,
  waitForBackend,
  createDraft,
  createScene,
  createEntity,
  createMap,
  createLocationBindings,
  createMapMarker,
  createMapObservation,
  getLatestDraft,
  listConflictChecks,
} from "./helpers/api-client.js"

test.describe("写作工作台 — 版本冲突", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    await installLeafletStub(page.context())

    const project = await createProject({
      title: "冲突测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openWorkbench(page, project, "writing")
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("409 冲突 — 其他会话已发布新版本", async ({ page }) => {
    // Step 1: 通过 API 创建 v1 草稿
    const d1 = await createDraft(testProjectId, 1, "v1 标题", "v1 内容")

    const draftId = d1.draft.id
    const v1Number = d1.draft.version_number

    // Step 2: 真实导航加载第 1 章 v1
    await reloadWorkbench(page, "writing")
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
    await page.locator('[data-action="select-chapter"][data-chapter="1"]').click()
    await expect(page.locator("#writing-editor")).toHaveValue("v1 内容", { timeout: 5000 })

    // Step 3: 模拟另一个会话发布 v2（提升章节最新版本号）
    await createDraft(testProjectId, 1, "v2 标题", "v2 内容")

    // Step 4: 在当前页面编辑并暂存（expected_version 仍为 v1）
    await page.locator("#writing-editor").fill("v3 内容 — 冲突")
    await page.locator('[data-action="autosave"]').click()

    // Step 5: 应收到 409 冲突 toast
    await expect(page.locator(SEL.toastContainer)).toContainText("已被其他会话更新", { timeout: 10000 })
  })

  test("待处理地图风险 — 用户勾选待处理内容后保留跨模块证据并可打开来源", async ({ page }) => {
    const draft = await createDraft(
      testProjectId,
      1,
      "第一章 旧约门",
      "旧稿：守门人还在等待主角解释。",
    )
    const character = await createEntity(testProjectId, {
      name: "沈砚",
      entity_type: "character",
      status: "canonical",
    })
    const location = await createEntity(testProjectId, {
      name: "旧约门",
      entity_type: "location",
      status: "canonical",
      summary: "禁区入口与粮仓相邻。",
    })
    const scene = await createScene(testProjectId, {
      scene_index: 1,
      title: "旧约门交涉",
      narrative_tag: "draft",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 1000 }],
      goal: "取得银色通行符并安全进入禁区。",
      core_conflict: "守门人怀疑主角背弃旧盟友。",
      must_happen: "守门人交出银色通行符",
      must_not_happen: "主角杀死守门人",
      pov_character_id: character.id,
    })
    const map = await createMap(testProjectId, {
      name: "九州风险图",
      map_type: "world",
      grid_width: 5,
      grid_height: 5,
      template: "blank",
    })
    await createLocationBindings(testProjectId, map.id, {
      location_entity_id: location.id,
      hexes: [{ hex_q: 1, hex_r: 1, is_center: true }],
    })
    await createMapMarker(testProjectId, map.id, {
      entity_id: character.id,
      marker_type: "character",
      hex_q: 1,
      hex_r: 1,
      label: "沈砚在旧约门",
      start_scene_id: scene.id,
      start_scene_index: 1,
      visible: true,
    })
    const observation = await createMapObservation(testProjectId, map.id, {
      target_entity_id: location.id,
      target_entity_type: "location",
      target_name: "旧约门粮仓火势",
      dynamic_type: "risk",
      time_anchor: {
        chapter_index: 1,
        scene_id: scene.id,
        scene_index: 1,
      },
      spatial_anchor: {
        hex_q: 1,
        hex_r: 1,
        location_name: "旧约门",
      },
      value_json: { risk: "粮仓火势正在扩大" },
      confidence: 0.82,
      review_state: "candidate",
      source_ref: {
        source: "writing_conflict_e2e",
        chapter_index: 1,
        scene_id: scene.id,
      },
      evidence_text: "候选地图证据：旧约门粮仓火势正在扩大，需要作者确认。",
      scene_id: scene.id,
      scene_index: 1,
      source_chapter_index: 1,
    })

    await reloadWorkbench(page, "writing")
    await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
    await page.locator('[data-action="select-scene"]').first().click()
    await expect(page.locator("#writing-editor")).toBeVisible({ timeout: 10000 })
    await expect(page.locator("#writing-panel-container")).toContainText("旧约门交涉")
    await expect(page.locator("#writing-panel-container")).toContainText("地图摘要", {
      timeout: 10000,
    })

    await page.locator("#writing-title-input").fill("第一章 旧约门")
    await page.locator("#writing-editor").fill(
      "守门人交出银色通行符，主角说明自己违背誓约的原因后，准备从旧约门进入禁区。",
    )
    await page.locator('[data-action="run-conflict-check"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("剧情设定冲突检查")
    await page.locator("#writing-conflict-include-candidates").check()
    await page.locator(SEL.modalFooter).getByRole("button", { name: "开始检查" }).click()

    await expect(page.locator(SEL.modalOverlay)).toContainText("地图/世界状态风险", {
      timeout: 15000,
    })
    await expect(page.locator(SEL.modalOverlay)).toContainText("旧约门粮仓火势")
    await expect(page.locator(SEL.modalOverlay)).toContainText("候选地图证据")
    await expect(page.locator(SEL.modalOverlay)).toContainText("本次检查包含待处理内容")

    const mapRiskItem = page.locator(".writing-conflict-item", {
      hasText: "地图/世界状态风险",
    }).first()
    await expect(mapRiskItem).toContainText("world")
    await expect(mapRiskItem).toContainText("需要人工检查")
    await mapRiskItem.locator(".writing-conflict-evidence-drawer summary").click()
    await expect(mapRiskItem.locator(".writing-conflict-evidence-drawer")).toContainText("world")
    await expect(mapRiskItem.locator(".writing-conflict-evidence-drawer")).toContainText("地图摘要")
    await expect(mapRiskItem.locator(".writing-conflict-evidence-drawer")).toContainText("地图风险")
    await expect(mapRiskItem.locator(".writing-conflict-evidence-drawer")).toContainText("map_object")
    await expect(mapRiskItem.locator(".writing-conflict-evidence-drawer")).toContainText("依赖待处理地图观察")

    const popupPromise = page.waitForEvent("popup")
    await mapRiskItem.getByRole("button", { name: "来源" }).click()
    const popup = await popupPromise
    await popup.waitForLoadState("domcontentloaded")
    await popup.waitForFunction(() => !state.loading, { timeout: 10000 })
    expect(popup.url()).toContain(`#workbench/${testProjectId}/map`)
    expect(popup.url()).toContain(`map_id=${map.id}`)
    expect(popup.url()).toContain(`scene_id=${scene.id}`)
    await expect(popup.locator(SEL.viewTitle)).toHaveText("地图")
    await expect(popup.locator(SEL.mapLeaflet)).toBeVisible({ timeout: 10000 })
    await popup.close()

    const history = await listConflictChecks(testProjectId, {
      chapter_index: 1,
      scene_id: scene.id,
      limit: 1,
    })
    const latest = history.items[0]
    expect(latest.include_candidates).toBe(true)
    const persistedMapRisk = latest.items.find((item) => item.kind === "map_risk")
    expect(persistedMapRisk).toBeTruthy()
    expect(persistedMapRisk.source_module).toBe("world")
    expect(persistedMapRisk.needs_review).toBe(true)
    expect(persistedMapRisk.location_json.source.module).toBe("world")
    expect(persistedMapRisk.location_json.open_target).toMatchObject({
      kind: "map_object",
      map_id: map.id,
      scene_id: scene.id,
      observation_id: observation.id,
    })

    await page.locator(SEL.modalFooter).getByRole("button", { name: "关闭" }).click()
    await page.locator('[data-action="publish"]').click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已发布", { timeout: 30000 })

    const latestDraft = await getLatestDraft(testProjectId, 1)
    expect(latestDraft.id).not.toBe(draft.draft.id)
    const snapshot = latestDraft.conflict_check_snapshot_json
    const snapshotMapRisk = snapshot.items.find((item) => item.kind === "map_risk")
    expect(snapshotMapRisk).toBeTruthy()
    expect(snapshotMapRisk.source_module).toBe("world")
    expect(snapshotMapRisk.needs_review).toBe(true)
    expect(snapshotMapRisk.location_json.source.module).toBe("world")
    expect(snapshotMapRisk.location_json.source.type).toBe("map.scene_summary")
    expect(snapshotMapRisk.location_json.open_target).toMatchObject({
      kind: "map_object",
      map_id: map.id,
      scene_id: scene.id,
      observation_id: observation.id,
    })
  })

  test("409 冲突 — 其他 Tab 已暂存同一草稿", async ({ browser }) => {
    // Step 1: 通过 API 创建 v1 草稿
    const d1 = await createDraft(testProjectId, 1, "v1 标题", "v1 内容")

    // Step 2: 打开两个 Tab
    const context = await browser.newContext()
    const pageA = await context.newPage()
    const pageB = await context.newPage()

    try {
      for (const page of [pageA, pageB]) {
        await openWorkbench(page, { id: testProjectId, title: "冲突测试项目" }, "writing")
        await page.waitForFunction(() => typeof writingView !== "undefined" && writingView._loading === false)
        await page.locator('[data-action="select-chapter"][data-chapter="1"]').click()
        await expect(page.locator("#writing-editor")).toHaveValue("v1 内容", { timeout: 5000 })
      }

      // Step 3: Tab A 编辑并暂存
      await pageA.locator("#writing-editor").fill("Tab A 内容")
      await pageA.locator('[data-action="autosave"]').click()
      await expect(pageA.locator(SEL.toastContainer)).toContainText("已暂存", { timeout: 10000 })

      // Step 4: Tab B 再暂存应收到 409
      await pageB.locator("#writing-editor").fill("Tab B 内容")
      await pageB.locator('[data-action="autosave"]').click()
      await expect(pageB.locator(SEL.toastContainer)).toContainText("已被其他会话更新", { timeout: 10000 })
    } finally {
      await context.close()
    }
  })
})
