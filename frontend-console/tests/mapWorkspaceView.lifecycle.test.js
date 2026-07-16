import { describe, it, expect, vi, beforeEach } from "vitest"
import mapWorkspaceView from "../views/mapWorkspaceView.js"
import mapView from "../views/mapView.js"
import mapQuickCreateView from "../views/mapQuickCreateView.js"
import { autoConfirm, expectNoTechnicalIds, modalHtmlFromCall, renderHtml, resetTestEnvironment } from "./helpers.js"

beforeEach(() => {
  resetTestEnvironment({ currentProjectId: "p1" })
  mapWorkspaceView._maps = []
  mapWorkspaceView._archivedMaps = []
  mapWorkspaceView._locations = []
  mapWorkspaceView._inbox = {
    loading: false,
    items: [],
    total: 0,
    hasMore: false,
    error: null,
    page: 0,
    projectId: null,
    filters: {
      dynamicType: "",
      sceneId: "",
      source: "",
      confidence: "",
      eligibility: "",
    },
  }
  mapWorkspaceView._pendingObservationEditorId = null
  mapWorkspaceView._mode = "overview"
  mapWorkspaceView._message = null
  mapWorkspaceView._activeMapId = null
  mapWorkspaceView._activeSceneId = null
  mapWorkspaceView._focusEntityId = null
  mapWorkspaceView._focusPathId = null
  mapWorkspaceView._focusLayerNodeId = null
  mapWorkspaceView._focusedDynamicItemId = null
  mapWorkspaceView._editingState = { editing: false, dirty: false, editorLayer: "none" }
  mapWorkspaceView._showHistory = false
  mapWorkspaceView._showArchivedMaps = false
  mapWorkspaceView._rebuildMapIndexes?.()
  mapWorkspaceView._resetDynamicSummary?.()
  mapWorkspaceView._resetPlayback?.()
  mapWorkspaceView._clearPendingTimers?.()
  mapWorkspaceView._unbindBeforeUnloadGuard?.()
  mapWorkspaceView._dataLoadEpoch = 0
  mapWorkspaceView._mountEpoch = 0
  mapWorkspaceView._mountPromise = Promise.resolve()
})

describe("mapWorkspaceView map mounting", () => {
  beforeEach(() => {
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._activeSceneId = null
    mapWorkspaceView._focusEntityId = null
    mapWorkspaceView._focusedDynamicItemId = null
    mapWorkspaceView._viewMode = "dashboard"
    mapWorkspaceView._lowMotion = false
    mapWorkspaceView._layers = { terrain: true, locations: true }
  })

  it("_mountMap unmounts existing map view before mounting", async () => {
    const unmountSpy = vi.spyOn(mapView, "unmount").mockImplementation(() => {})
    const mountSpy = vi.spyOn(mapView, "mount").mockImplementation(() => {})
    const loadSpy = vi.spyOn(mapWorkspaceView, "_loadDynamicSummary").mockImplementation(() => {})

    await mapWorkspaceView._mountMap()

    expect(unmountSpy).toHaveBeenCalled()
    expect(mountSpy).toHaveBeenCalled()
    expect(unmountSpy.mock.invocationCallOrder[0]).toBeLessThan(mountSpy.mock.invocationCallOrder[0])
    unmountSpy.mockRestore()
    mountSpy.mockRestore()
    loadSpy.mockRestore()
  })

  it("pushes the map list route from the mounted map and preserves state on cancel", async () => {
    let context
    const unmountSpy = vi.spyOn(mapView, "unmount").mockImplementation(() => {})
    const mountSpy = vi.spyOn(mapView, "mount").mockImplementation((_rootId, value) => {
      context = value
    })
    const loadSpy = vi.spyOn(mapWorkspaceView, "_loadDynamicSummary").mockImplementation(() => {})
    const leaveSpy = vi.spyOn(mapView, "canLeave").mockReturnValue(false)

    await mapWorkspaceView._mountMap()
    vi.clearAllMocks()

    expect(context.onBackOverview()).toBe(false)
    expect(mapWorkspaceView._activeMapId).toBe("m1")
    expect(router.navigate).not.toHaveBeenCalled()
    expect(unmountSpy).not.toHaveBeenCalled()

    leaveSpy.mockReturnValue(true)
    expect(context.onBackOverview()).toBe(true)
    expect(mapWorkspaceView._activeMapId).toBeNull()
    expect(router.navigate).toHaveBeenCalledWith(
      "map",
      null,
      true,
      expect.any(URLSearchParams),
    )
    const query = router.navigate.mock.calls.at(-1)[3]
    expect(query.toString()).toBe("mode=overview")
    expect(unmountSpy).toHaveBeenCalledTimes(1)

    leaveSpy.mockRestore()
    unmountSpy.mockRestore()
    mountSpy.mockRestore()
    loadSpy.mockRestore()
  })

  it("keeps Scene and URL unchanged when a dirty-map Scene switch is rejected", async () => {
    let context
    mapWorkspaceView._activeSceneId = "s1"
    const unmountSpy = vi.spyOn(mapView, "unmount").mockImplementation(() => {})
    const mountSpy = vi.spyOn(mapView, "mount").mockImplementation((_rootId, value) => {
      context = value
    })
    const loadSpy = vi.spyOn(mapWorkspaceView, "_loadDynamicSummary").mockImplementation(() => {})
    const leaveSpy = vi.spyOn(mapView, "canLeave").mockReturnValue(false)

    await mapWorkspaceView._mountMap()
    vi.clearAllMocks()

    expect(context.onSceneChange("s2")).toBe(false)
    expect(mapWorkspaceView._activeSceneId).toBe("s1")
    expect(router.replace).not.toHaveBeenCalled()
    expect(unmountSpy).not.toHaveBeenCalled()

    leaveSpy.mockReturnValue(true)
    expect(context.onSceneChange("s2")).toBe(true)
    expect(mapWorkspaceView._activeSceneId).toBe("s2")
    expect(router.replace).toHaveBeenCalledWith(
      "map",
      null,
      expect.any(URLSearchParams),
    )
    expect(router.replace.mock.calls.at(-1)[2].get("scene_id")).toBe("s2")
    expect(unmountSpy).toHaveBeenCalledTimes(1)

    leaveSpy.mockRestore()
    unmountSpy.mockRestore()
    mountSpy.mockRestore()
    loadSpy.mockRestore()
  })

  it("serializes mounts and skips a superseded queued map", async () => {
    let releaseFirst
    const mountSpy = vi.spyOn(mapView, "mount").mockImplementationOnce(
      () => new Promise((resolve) => { releaseFirst = resolve }),
    ).mockResolvedValue()
    const unmountSpy = vi.spyOn(mapView, "unmount").mockImplementation(() => {})
    const loadSpy = vi.spyOn(mapWorkspaceView, "_loadDynamicSummary").mockImplementation(() => {})

    const first = mapWorkspaceView._mountMap()
    await vi.waitFor(() => expect(releaseFirst).toBeTypeOf("function"))
    mapWorkspaceView._activeMapId = "m2"
    const second = mapWorkspaceView._mountMap()
    mapWorkspaceView._activeMapId = "m3"
    const third = mapWorkspaceView._mountMap()
    releaseFirst()

    await Promise.all([first, second, third])
    expect(mountSpy).toHaveBeenCalledTimes(2)
    expect(mountSpy.mock.calls[1][1].mapId).toBe("m3")
    mountSpy.mockRestore()
    unmountSpy.mockRestore()
    loadSpy.mockRestore()
  })

  it("unmounts a completed mount when its epoch was superseded", async () => {
    let releaseMount
    const mountSpy = vi.spyOn(mapView, "mount").mockImplementation(
      () => new Promise((resolve) => { releaseMount = resolve }),
    )
    const unmountSpy = vi.spyOn(mapView, "unmount").mockImplementation(() => {})
    const loadSpy = vi.spyOn(mapWorkspaceView, "_loadDynamicSummary").mockImplementation(() => {})

    const pending = mapWorkspaceView._mountMap()
    await vi.waitFor(() => expect(releaseMount).toBeTypeOf("function"))
    mapWorkspaceView._mountEpoch += 1
    releaseMount()

    await expect(pending).resolves.toBe(false)
    expect(unmountSpy).toHaveBeenCalledTimes(2)
    expect(loadSpy).not.toHaveBeenCalled()
    mountSpy.mockRestore()
    unmountSpy.mockRestore()
    loadSpy.mockRestore()
  })
})

describe("mapWorkspaceView dynamic summary cache", () => {
  beforeEach(() => {
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._activeSceneId = null
    mapWorkspaceView._focusEntityId = null
    mapWorkspaceView._focusedDynamicItemId = null
    mapWorkspaceView._resetDynamicSummary("m1")
    vi.clearAllMocks()
  })

  it("refreshes summary when scene changes within the same map", async () => {
    api.world.getMapDashboard.mockResolvedValue({ dynamic_queue: [] })
    api.world.getMapPlayback.mockResolvedValue({ events: [], tracks: [] })

    await mapWorkspaceView._loadDynamicSummary()
    expect(api.world.getMapDashboard).toHaveBeenCalledTimes(1)

    mapWorkspaceView._activeSceneId = "s2"
    await mapWorkspaceView._loadDynamicSummary()

    expect(api.world.getMapDashboard).toHaveBeenCalledTimes(2)
  })

  it("refreshes summary when focus entity changes within the same map", async () => {
    api.world.getMapDashboard.mockResolvedValue({ dynamic_queue: [] })
    api.world.getMapPlayback.mockResolvedValue({ events: [], tracks: [] })

    await mapWorkspaceView._loadDynamicSummary()
    expect(api.world.getMapDashboard).toHaveBeenCalledTimes(1)

    mapWorkspaceView._focusEntityId = "e2"
    await mapWorkspaceView._loadDynamicSummary()

    expect(api.world.getMapDashboard).toHaveBeenCalledTimes(2)
  })

  it("refreshes summary when focused dynamic item changes within the same map", async () => {
    api.world.getMapDashboard.mockResolvedValue({ dynamic_queue: [] })
    api.world.getMapPlayback.mockResolvedValue({ events: [], tracks: [] })

    await mapWorkspaceView._loadDynamicSummary()
    expect(api.world.getMapDashboard).toHaveBeenCalledTimes(1)

    mapWorkspaceView._focusedDynamicItemId = "i2"
    await mapWorkspaceView._loadDynamicSummary()

    expect(api.world.getMapDashboard).toHaveBeenCalledTimes(2)
  })

  it("ignores a late summary response for an older context on the same map", async () => {
    let resolveOldDashboard
    let resolveOldPlayback
    mapWorkspaceView._activeSceneId = "s1"
    api.world.getMapDashboard.mockImplementation((_mapId, _projectId, sceneId) => {
      if (sceneId === "s1") {
        return new Promise((resolve) => { resolveOldDashboard = resolve })
      }
      return Promise.resolve({ marker: "new", dynamic_queue: [] })
    })
    api.world.getMapPlayback.mockImplementation((_mapId, _projectId, sceneId) => {
      if (sceneId === "s1") {
        return new Promise((resolve) => { resolveOldPlayback = resolve })
      }
      return Promise.resolve({ marker: "new", events: [], tracks: [] })
    })

    const oldLoad = mapWorkspaceView._loadDynamicSummary({ force: true })
    await vi.waitFor(() => {
      expect(resolveOldDashboard).toBeTypeOf("function")
      expect(resolveOldPlayback).toBeTypeOf("function")
    })
    mapWorkspaceView._activeSceneId = "s2"
    await mapWorkspaceView._loadDynamicSummary({ force: true })
    resolveOldDashboard({ marker: "old", dynamic_queue: [] })
    resolveOldPlayback({ marker: "old", events: [], tracks: [] })
    await oldLoad

    expect(mapWorkspaceView._dynamicSummary).toMatchObject({
      sceneId: "s2",
      dashboard: { marker: "new" },
    })
    expect(mapWorkspaceView._playback.playback).toMatchObject({ marker: "new" })
  })
})

describe("mapWorkspaceView observation review", () => {
  it("_updateObservationReview shows readable label instead of [object Object]", async () => {
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._dynamicSummary = {
      dashboard: {
        dynamic_queue: [{
          item_id: "obs1",
          item_kind: "observation",
          title: "沈砚入城",
          review_state: "candidate",
        }],
      },
      observations: [{ item_id: "obs1", title: "沈砚入城" }],
      facts: [],
    }
    api.world.updateMapObservationReview.mockResolvedValue({ id: "obs1" })
    api.world.getMapDashboard.mockResolvedValue({ dynamic_queue: [], batch_groups: [] })
    api.world.getMapPlayback.mockResolvedValue({ events: [], tracks: [] })

    mapWorkspaceView._updateObservationReview("obs1", { review_state: "ignored" })

    expect(confirmAction).toHaveBeenCalled()
    const message = confirmAction.mock.calls[0][0]
    expect(message).toContain("沈砚入城")
    expect(message).toContain("已忽略")
    expect(message).not.toContain("[object Object]")
  })
})

describe("mapWorkspaceView Scene timeline", () => {
  it("loads the latest non-contiguous Scene state and sends an explicit projection to mapView", async () => {
    mapWorkspaceView._activeMapId = "m1"
    api.world.getMapDashboard.mockResolvedValue({ dynamic_queue: [] })
    api.world.getMapPlayback.mockResolvedValue({ events: [], tracks: [] })
    api.world.getMapTimeline.mockResolvedValue({
      scenes: [{ scene_index: 2 }, { scene_index: 9 }],
      deltas: [{ delta_id: "d9", scene_index: 9, track: "journey" }],
      candidates: [],
      conflicts: [],
      continuity_issues: [],
    })
    api.world.getMapStateAt.mockResolvedValue({
      scene_index: 9,
      items: [{
        target_name: "沈砚",
        track: "journey",
        normalized_value: { schema_version: 1, type: "location", location_name: "内城" },
        spatial_anchor: { hex_q: 3, hex_r: 4 },
        source_fact_ids: ["fact-9"],
      }],
      conflicts: [],
    })
    const projection = vi.spyOn(mapView, "setTimelineProjection").mockReturnValue(true)

    await mapWorkspaceView._loadDynamicSummary({ force: true })

    expect(api.world.getMapTimeline).toHaveBeenCalledWith("m1", "p1", {
      focusEntityId: null,
      includeCandidates: undefined,
      limit: 500,
    })
    expect(api.world.getMapStateAt).toHaveBeenCalledWith("m1", "p1", 9, {
      focusEntityId: null,
      limit: 500,
    })
    expect(mapWorkspaceView._timeline.sceneIndex).toBe(9)
    expect(projection).toHaveBeenCalledWith(expect.objectContaining({
      sceneIndex: 9,
      includeCandidates: false,
      stateItems: [expect.objectContaining({ target_name: "沈砚" })],
    }))
    projection.mockRestore()
  })

  it("ignores a late state-at response after the cursor moves to a newer Scene", async () => {
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._timeline = {
      ...mapWorkspaceView._timeline,
      data: { scenes: [{ scene_index: 2 }, { scene_index: 9 }], deltas: [], candidates: [] },
      activeIndex: 0,
      sceneIndex: 2,
    }
    let resolveOld
    api.world.getMapStateAt.mockImplementation((_mapId, _novelId, sceneIndex) => {
      if (sceneIndex === 2) return new Promise((resolve) => { resolveOld = resolve })
      return Promise.resolve({ scene_index: 9, items: [{ target_name: "新状态" }], conflicts: [] })
    })
    const projection = vi.spyOn(mapView, "setTimelineProjection").mockReturnValue(true)

    const oldRequest = mapWorkspaceView._loadTimelineStateAt(2)
    await vi.waitFor(() => expect(resolveOld).toBeTypeOf("function"))
    await mapWorkspaceView._setTimelineScenePosition(1)
    resolveOld({ scene_index: 2, items: [{ target_name: "旧状态" }], conflicts: [] })
    await oldRequest

    expect(mapWorkspaceView._timeline.sceneIndex).toBe(9)
    expect(mapWorkspaceView._timeline.stateAt.items[0].target_name).toBe("新状态")
    expect(projection.mock.calls.at(-1)[0]).toEqual(expect.objectContaining({ sceneIndex: 9 }))
    projection.mockRestore()
  })

  it("steps through the returned Scene stops instead of inventing logical indexes", async () => {
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._timeline = {
      ...mapWorkspaceView._timeline,
      data: { scenes: [{ scene_index: 2 }, { scene_index: 9 }], deltas: [], candidates: [] },
      activeIndex: 0,
      sceneIndex: 2,
    }
    api.world.getMapStateAt.mockResolvedValue({ scene_index: 9, items: [], conflicts: [] })

    await mapWorkspaceView._stepTimeline(1)

    expect(mapWorkspaceView._timeline.sceneIndex).toBe(9)
    expect(api.world.getMapStateAt).toHaveBeenCalledWith("m1", "p1", 9, expect.any(Object))
  })

  it("renders canonical and candidate states separately, keeps candidates read-only, and escapes hostile text", () => {
    mapWorkspaceView._timeline = {
      ...mapWorkspaceView._timeline,
      loaded: true,
      includeCandidates: true,
      activeIndex: 0,
      sceneIndex: 4,
      data: {
        scenes: [{ scene_index: 4, delta_count: 1 }],
        deltas: [],
        candidates: [{
          id: "candidate-1",
          scene_index: 4,
          target_name: '<img src=x onerror="alert(1)">',
          dynamic_type: "status",
          normalization_state: "untyped",
          evidence_text: "<script>bad()</script>",
        }],
        conflicts: [],
        continuity_issues: [],
        undated_facts: [],
      },
      stateAt: {
        scene_index: 4,
        items: [{
          target_name: "城门",
          track: "status",
          normalization_state: "typed",
          normalized_value: { type: "status", field_key: "戒备", value: "加强" },
        }],
        conflicts: [],
      },
    }

    const container = renderHtml(mapWorkspaceView._renderTimelinePanel())

    expect(container.textContent).toContain("正式状态")
    expect(container.textContent).toContain("只读预览")
    expect(container.textContent).toContain("尚未结构化")
    expect(container.textContent).toContain('<img src=x onerror="alert(1)">')
    expect(container.querySelector("img")).toBeNull()
    expect(container.querySelector("script")).toBeNull()
    expect(container.querySelector(".is-candidate[data-action]")).toBeNull()
  })

  it("clears projection only when editing starts and preserves path focus on dirty updates", () => {
    mapWorkspaceView._timeline = {
      ...mapWorkspaceView._timeline,
      playing: true,
      sceneIndex: 3,
      data: { scenes: [{ scene_index: 3 }], deltas: [], candidates: [] },
      stateAt: { items: [], conflicts: [] },
    }
    const clear = vi.spyOn(mapView, "clearTimelineProjection").mockImplementation(() => true)
    const clearPath = vi.spyOn(mapView, "clearPathFocus").mockImplementation(() => true)
    const set = vi.spyOn(mapView, "setTimelineProjection").mockReturnValue(true)

    mapWorkspaceView._onMapEditingChange({ editing: true, dirty: false, editorLayer: "location" })
    expect(mapWorkspaceView._timeline.playing).toBe(false)
    expect(clear).toHaveBeenCalledTimes(1)
    expect(clearPath).toHaveBeenCalledTimes(1)
    expect(clearPath).toHaveBeenCalledWith({ preserveSelection: true })

    mapWorkspaceView._onMapEditingChange({ editing: true, dirty: true, editorLayer: "path" })
    expect(clear).toHaveBeenCalledTimes(1)
    expect(clearPath).toHaveBeenCalledTimes(1)

    mapWorkspaceView._onMapEditingChange({ editing: false, dirty: false, editorLayer: "none" })
    expect(set).toHaveBeenCalled()
    clear.mockRestore()
    clearPath.mockRestore()
    set.mockRestore()
  })

  it("creates a user-authored movement explanation as a candidate observation", async () => {
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._timeline = {
      ...mapWorkspaceView._timeline,
      data: {
        scenes: [{ scene_index: 7 }],
        deltas: [],
        candidates: [],
        continuity_issues: [{
          issue_key: "issue-1",
          issue_type: "blocked_route",
          message: "东桥已封锁",
          suggested_observation: {
            target_entity_id: null,
            target_entity_type: "character",
            target_name: "沈砚",
            dynamic_type: "movement_explanation",
            time_anchor: { scene_index: 7 },
            spatial_anchor: { hex_q: 2, hex_r: 3 },
            value_json: {
              schema_version: 1,
              type: "semantic",
              relation_type: "movement_explanation",
              related_entity_ids: [],
              summary: "",
            },
            review_state: "candidate",
            source_ref: { source: "map_continuity", issue_key: "issue-1" },
            evidence_text: "",
            scene_index: 7,
          },
        }],
      },
    }
    api.world.createMapObservation.mockResolvedValue({ id: "candidate-created" })
    const reload = vi.spyOn(mapWorkspaceView, "_loadDynamicSummary").mockResolvedValue()

    mapWorkspaceView._showContinuityExplanationForm("issue-1")
    const call = showModal.mock.calls.at(-1)
    document.body.innerHTML = modalHtmlFromCall(call)
    document.getElementById("map-continuity-explanation").value = "角色使用城内密道"
    document.getElementById("map-continuity-evidence").value = "第七幕正文已说明"
    await call[2][0].handler()

    expect(api.world.createMapObservation).toHaveBeenCalledWith(
      "m1",
      expect.objectContaining({
        dynamic_type: "movement_explanation",
        review_state: "candidate",
        evidence_text: "第七幕正文已说明",
        value_json: expect.objectContaining({
          schema_version: 1,
          type: "semantic",
          relation_type: "movement_explanation",
          summary: "角色使用城内密道",
        }),
      }),
      "p1",
    )
    expect(mapWorkspaceView._timeline.includeCandidates).toBe(true)
    reload.mockRestore()
  })
})

describe("mapWorkspaceView typed dynamic candidate editor", () => {
  it("keeps legacy dynamic data read-only without exposing raw JSON", () => {
    mapWorkspaceView._showDynamicEditForm({
      item_id: "obs-legacy",
      item_kind: "observation",
      title: "旧地图记录",
      dynamic_type: "state_change",
      review_state: "candidate",
      normalization_state: "untyped",
      value_json: { old: "东门", new: "内城" },
    })

    const body = modalHtmlFromCall(showModal.mock.calls.at(-1))
    const container = renderHtml(body)
    expect(container.textContent).toContain("旧版格式")
    expect(container.textContent).toContain("只读保留")
    expect(container.textContent).not.toContain("高级 JSON")
    expect(container.querySelector("#map-object-edit-value-type")).toBeNull()
    expect(container.querySelector("[id^='map-typed-']")).toBeNull()
  })

  it("builds a typed status payload from author-facing fields", () => {
    mapWorkspaceView._showDynamicEditForm({
      item_id: "obs-status",
      item_kind: "observation",
      title: "城门戒备",
      target_name: "城门",
      target_entity_type: "location",
      dynamic_type: "status",
      review_state: "candidate",
      normalization_state: "typed",
      normalized_value: {
        schema_version: 1,
        type: "status",
        field_key: "戒备等级",
        value: 2,
      },
      value_json: {
        schema_version: 1,
        type: "status",
        field_key: "戒备等级",
        value: 2,
      },
    })
    document.body.innerHTML = modalHtmlFromCall(showModal.mock.calls.at(-1))
    mapWorkspaceView._bindTypedDynamicValueEditor()
    document.getElementById("map-typed-status-key").value = "戒备等级"
    document.getElementById("map-typed-status-value-type").value = "number"
    document.getElementById("map-typed-status-value").value = "4"

    const payload = mapWorkspaceView._readObservationEditPayload("candidate")

    expect(payload).not.toHaveProperty("dynamic_type")
    expect(payload.value_json).toEqual({
      schema_version: 1,
      type: "status",
      field_key: "戒备等级",
      value: 4,
    })
  })

  it("canonicalizes typed boundary hex input and never reads the advanced JSON instead", () => {
    mapWorkspaceView._showDynamicEditForm({
      item_id: "obs-boundary",
      item_kind: "observation",
      title: "旧城区控制范围",
      target_entity_id: "123e4567-e89b-12d3-a456-426614174000",
      dynamic_type: "boundary",
      review_state: "candidate",
      normalized_value: {
        schema_version: 1,
        type: "boundary",
        controller_entity_id: "123e4567-e89b-12d3-a456-426614174000",
        hexes: [],
      },
      value_json: { schema_version: 1, type: "boundary", invalid: "must-not-win" },
    })
    document.body.innerHTML = modalHtmlFromCall(showModal.mock.calls.at(-1))
    mapWorkspaceView._bindTypedDynamicValueEditor()
    document.getElementById("map-typed-boundary-hexes").value = "3,2\n1,1\n3,2"

    const payload = mapWorkspaceView._readObservationEditPayload("candidate")

    expect(payload.value_json).toEqual({
      schema_version: 1,
      type: "boundary",
      controller_entity_id: "123e4567-e89b-12d3-a456-426614174000",
      hexes: [{ hex_q: 1, hex_r: 1 }, { hex_q: 3, hex_r: 2 }],
    })
  })

  it("renders the project inbox and assigns a proposal with its revision", async () => {
    mapWorkspaceView._maps = [{ id: "map-1", name: "九州", map_type: "world" }]
    mapWorkspaceView._inbox = {
      ...mapWorkspaceView._inbox,
      items: [{
        id: "obs-proposal",
        target_name: "沈砚",
        dynamic_type: "location",
        proposal_type: "character_location",
        proposal_value: { proposal_type: "character_location", location_name: "东门" },
        source: "deep_import",
        confidence: 0.42,
        scene_index: 3,
        source_chapter_index: 2,
        updated_at: "rev-1",
        eligibility: {
          can_confirm: false,
          missing_item_labels: ["地图", "正式地图值"],
        },
      }],
      total: 1,
    }
    api.world.assignProjectMapObservation.mockResolvedValue({ id: "obs-proposal" })

    const html = mapWorkspaceView._renderOverview()
    expect(html).toContain("地图收件箱")
    expect(html).toContain("分配并继续")
    expect(html).toContain("待补：地图、正式地图值")
    expect(html).toContain("Scene 4 · 第 2 章")
    expect(html).toContain("复制诊断信息")

    mapWorkspaceView._showInboxAssignment("obs-proposal")
    const call = showModal.mock.calls.at(-1)
    document.body.innerHTML = modalHtmlFromCall(call)
    await call[2][0].handler()

    expect(api.world.assignProjectMapObservation).toHaveBeenCalledWith(
      "obs-proposal",
      "p1",
      "map-1",
      "rev-1",
    )
    expect(mapWorkspaceView._pendingObservationEditorId).toBe("obs-proposal")
    expect(mapWorkspaceView._activeMapId).toBe("map-1")
  })

  it("keeps project inbox filters visible and offers retry after a load failure", () => {
    mapWorkspaceView._inbox = {
      ...mapWorkspaceView._inbox,
      error: "收件箱网络失败",
      items: [],
      total: 0,
      filters: {
        ...mapWorkspaceView._inbox.filters,
        dynamicType: "route_state",
        confidence: "high",
      },
    }

    const html = mapWorkspaceView._renderProjectObservationInbox()

    expect(html).toContain("收件箱网络失败")
    expect(html).toContain('data-action="map-inbox-retry"')
    expect(html).toContain('value="route_state" selected')
    expect(html).toContain('value="high" selected')
    expect(html).toContain('aria-label="按动态类型筛选"')
  })

  it("distinguishes missing confidence from an explicit zero score", () => {
    mapWorkspaceView._inbox = {
      ...mapWorkspaceView._inbox,
      items: [{
        id: "no-confidence",
        dynamic_type: "route_state",
        confidence: null,
        eligibility: { can_confirm: false, missing_item_labels: [] },
      }],
      total: 1,
    }

    expect(mapWorkspaceView._renderProjectObservationInbox()).toContain("置信度未提供")
  })

  it("keeps import diagnostics out of the author-facing inbox summary", () => {
    mapWorkspaceView._inbox = {
      ...mapWorkspaceView._inbox,
      items: [{
        id: "import-observation",
        target_name: "廷根市",
        proposal_type: "event_location",
        source: "deep_import_delta_event",
        evidence_text: "deep_import_delta_event · 克莱恩抵达廷根。",
        scene_id: "scene-raw-id",
        scene_index: 12,
        source_chapter_index: 7,
        confidence: 0.5,
        eligibility: {
          can_confirm: false,
          missing_item_labels: ["未选择地图", "缺少来源 Scene", "缺少来源章节", "动态字段尚未解析完整"],
        },
      }],
      total: 1,
    }

    const html = mapWorkspaceView._renderProjectObservationInbox()
    const wrapper = document.createElement("div")
    wrapper.innerHTML = html
    const authorText = wrapper.textContent

    expect(authorText).toContain("深度导入")
    expect(authorText).toContain("克莱恩抵达廷根。")
    expect(authorText).toContain("选择目标地图")
    expect(authorText).toContain("补全空间字段")
    expect(authorText).not.toContain("deep_import_delta_event")
    expect(authorText).not.toContain("缺少来源 Scene")
    expect(authorText).not.toContain("缺少来源章节")
    expect(html).toContain("诊断筛选")
    expect(html).toContain("Scene 原始 ID")
  })

  it("translates imported event codes in inbox cards", () => {
    mapWorkspaceView._inbox = {
      ...mapWorkspaceView._inbox,
      items: [{
        id: "relation-event",
        dynamic_type: "relation_created",
        source: "deep_import",
        confidence: 0.5,
        eligibility: { can_confirm: false, missing_item_labels: [] },
      }],
      total: 1,
    }

    const html = mapWorkspaceView._renderProjectObservationInbox()

    expect(html).toContain("关系位置建议")
    expect(html).not.toContain("relation_created")
  })

  it("sends source, confidence and eligibility filters to the paginated inbox API", async () => {
    mapWorkspaceView._inbox = {
      ...mapWorkspaceView._inbox,
      page: 1,
      filters: {
        ...mapWorkspaceView._inbox.filters,
        source: "deep_import",
        confidence: "low",
        eligibility: "missing",
      },
    }
    api.world.listMaps.mockResolvedValue({ items: [] })
    api.world.listEntities.mockResolvedValue({ items: [] })
    api.world.listProjectMapObservationInbox.mockResolvedValue({
      items: [{ id: "late-match" }],
      total: 21,
      has_more: false,
    })

    await mapWorkspaceView._loadData()

    expect(api.world.listProjectMapObservationInbox).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({
        source: "deep_import",
        confidence: "low",
        eligibility: "missing",
        skip: 20,
        limit: 20,
      }),
    )
  })

  it("resets inbox paging and filters when the active project changes", async () => {
    mapWorkspaceView._inbox = {
      ...mapWorkspaceView._inbox,
      projectId: "p1",
      page: 3,
      filters: { ...mapWorkspaceView._inbox.filters, source: "deep_import" },
    }
    state.currentProjectId = "p2"
    const load = vi.spyOn(mapWorkspaceView, "_loadData").mockResolvedValue(true)

    await mapWorkspaceView.onEnter()

    expect(mapWorkspaceView._inbox.page).toBe(0)
    expect(mapWorkspaceView._inbox.projectId).toBe("p2")
    expect(mapWorkspaceView._inbox.filters.source).toBe("")
    load.mockRestore()
  })

  it("clamps an empty stale inbox page to the last available page", async () => {
    mapWorkspaceView._inbox = { ...mapWorkspaceView._inbox, page: 1 }
    api.world.listMaps.mockResolvedValue({ items: [] })
    api.world.listEntities.mockResolvedValue({ items: [] })
    api.world.listProjectMapObservationInbox
      .mockResolvedValueOnce({ items: [], total: 1, has_more: false })
      .mockResolvedValueOnce({ items: [{ id: "only-item" }], total: 1, has_more: false })

    await mapWorkspaceView._loadData()

    expect(mapWorkspaceView._inbox.page).toBe(0)
    expect(mapWorkspaceView._inbox.items).toEqual([{ id: "only-item" }])
    expect(api.world.listProjectMapObservationInbox).toHaveBeenNthCalledWith(
      2,
      "p1",
      expect.objectContaining({ skip: 0 }),
    )
  })

  it("turns a route proposal into a canonical selector payload", () => {
    const pathOptions = vi.spyOn(mapView, "timelinePathOptions").mockReturnValue([
      { id: "path-1", name: "北境古道" },
    ])
    mapWorkspaceView._showDynamicEditForm({
      id: "obs-route",
      item_id: "obs-route",
      item_kind: "observation",
      target_name: "北境古道",
      dynamic_type: "route_state",
      review_state: "candidate",
      updated_at: "rev-route",
      proposal_type: "route_state",
      proposal_value: {
        payload_kind: "proposal",
        schema_version: 1,
        proposal_type: "route_state",
        path_name: "北境古道",
        state: "blocked",
        reason: "山洪",
      },
      eligibility: { can_confirm: false, missing_item_labels: ["正式地图值"] },
    })
    document.body.innerHTML = modalHtmlFromCall(showModal.mock.calls.at(-1))
    mapWorkspaceView._bindTypedDynamicValueEditor()

    expect(mapWorkspaceView._readObservationEditPayload("candidate", { updated_at: "rev-route" }))
      .toMatchObject({
        expected_updated_at: "rev-route",
        value_json: {
          schema_version: 1,
          type: "route_state",
          path_id: "path-1",
          state: "blocked",
          reason: "山洪",
        },
      })
    pathOptions.mockRestore()
  })

  it("keeps event locations off path-only editing and marks boundary hexes as desktop work", () => {
    mapWorkspaceView._showDynamicEditForm({
      id: "obs-event",
      item_id: "obs-event",
      item_kind: "observation",
      dynamic_type: "location",
      proposal_type: "event_location",
      proposal_value: {
        payload_kind: "proposal",
        schema_version: 1,
        proposal_type: "event_location",
        location_name: "王城广场",
      },
      review_state: "candidate",
      eligibility: { can_confirm: false, missing_item_labels: ["地点"] },
    })
    let html = modalHtmlFromCall(showModal.mock.calls.at(-1))
    expect(html).not.toContain("map-typed-location-path")

    mapWorkspaceView._showDynamicEditForm({
      id: "obs-boundary-mobile",
      item_id: "obs-boundary-mobile",
      item_kind: "observation",
      dynamic_type: "boundary",
      proposal_type: "boundary",
      normalized_value: {
        schema_version: 1,
        type: "boundary",
        controller_entity_id: "123e4567-e89b-12d3-a456-426614174000",
        hexes: [{ hex_q: 1, hex_r: 1 }],
      },
      review_state: "candidate",
      eligibility: { can_confirm: true, missing_item_labels: [] },
    })
    html = modalHtmlFromCall(showModal.mock.calls.at(-1))
    expect(html).toContain("map-boundary-spatial-field")
    expect(html).toContain("map-boundary-mobile-handoff")
    expect(html).toContain("请在桌面端继续")
  })

  it("keeps the edit modal open when the revision is stale", async () => {
    const item = {
      id: "obs-stale",
      item_id: "obs-stale",
      item_kind: "observation",
      title: "旧城门",
      dynamic_type: "status",
      review_state: "candidate",
      updated_at: "rev-old",
      normalized_value: {
        schema_version: 1,
        type: "status",
        field_key: "state",
        value: "closed",
      },
      eligibility: { can_confirm: true, missing_item_labels: [] },
    }
    mapWorkspaceView._dynamicSummary = {
      dashboard: { dynamic_queue: [item] },
      observations: [item],
      facts: [],
    }
    const conflict = Object.assign(new Error("请求冲突"), {
      status: 409,
      body: {
        context: {
          latest: { ...item, id: "obs-stale", updated_at: "rev-new" },
        },
      },
    })
    api.world.updateMapObservationReview
      .mockRejectedValueOnce(conflict)
      .mockResolvedValueOnce({ id: "obs-stale", updated_at: "rev-saved" })

    const result = await mapWorkspaceView._saveObservationEdit(item, {
      expected_updated_at: "rev-old",
      review_state: "candidate",
      target_name: "新城门",
    })

    expect(result).toBe(false)
    expect(closeModal).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("表单未关闭"), "warning")
    expect(mapWorkspaceView._dynamicObservation("obs-stale").updated_at).toBe("rev-new")

    await mapWorkspaceView._saveObservationEdit(item, {
      expected_updated_at: item.updated_at,
      review_state: "candidate",
      target_name: "新城门",
    })
    expect(api.world.updateMapObservationReview).toHaveBeenLastCalledWith(
      null,
      "obs-stale",
      "p1",
      expect.objectContaining({ expected_updated_at: "rev-new" }),
    )
  })

  it("uses the latest assignment revision when retrying the same modal", async () => {
    const item = {
      id: "obs-assign-stale",
      target_name: "沈砚",
      updated_at: "rev-old",
      eligibility: { can_confirm: false, missing_item_labels: [] },
    }
    mapWorkspaceView._maps = [{ id: "map-1", name: "九州", map_type: "world" }]
    mapWorkspaceView._inbox = {
      ...mapWorkspaceView._inbox,
      items: [item],
      total: 1,
    }
    const conflict = Object.assign(new Error("请求冲突"), {
      status: 409,
      body: { context: { latest: { ...item, updated_at: "rev-new" } } },
    })
    api.world.assignProjectMapObservation
      .mockRejectedValueOnce(conflict)
      .mockResolvedValueOnce({ id: item.id })

    mapWorkspaceView._showInboxAssignment(item.id)
    const call = showModal.mock.calls.at(-1)
    document.body.innerHTML = modalHtmlFromCall(call)
    expect(await call[2][0].handler()).toBe(false)
    expect(item.updated_at).toBe("rev-new")
    expect(await call[2][0].handler()).toBe(true)
    expect(api.world.assignProjectMapObservation).toHaveBeenLastCalledWith(
      item.id,
      "p1",
      "map-1",
      "rev-new",
    )
  })

  it("merges latest revisions for confirm, ignore, unassign and batch retries", async () => {
    const makeConflict = (item, revision) => Object.assign(new Error("请求冲突"), {
      status: 409,
      body: {
        context: {
          latest: { ...item, id: item.item_id, updated_at: revision },
        },
      },
    })
    const item = {
      id: "obs-actions",
      item_id: "obs-actions",
      item_kind: "observation",
      title: "城门",
      object_type: "status",
      review_state: "candidate",
      updated_at: "rev-1",
      eligibility: { can_confirm: true, missing_item_labels: [] },
    }
    mapWorkspaceView._activeMapId = "map-1"
    mapWorkspaceView._dynamicSummary = {
      dashboard: { dynamic_queue: [item] },
      observations: [item],
      facts: [],
    }
    mapWorkspaceView._rebuildDynamicIndexes()

    let modalHandler
    confirmAction.mockImplementation((_message, handler) => { modalHandler = handler })
    api.world.confirmMapObservation.mockRejectedValueOnce(makeConflict(item, "rev-2"))
    await mapWorkspaceView._confirmObservation(item.item_id)
    expect(await modalHandler()).toBe(false)
    expect(item.updated_at).toBe("rev-2")

    api.world.ignoreMapObservation.mockRejectedValueOnce(makeConflict(item, "rev-3"))
    await mapWorkspaceView._ignoreObservation(item.item_id)
    expect(await modalHandler()).toBe(false)
    expect(item.updated_at).toBe("rev-3")

    api.world.assignProjectMapObservation.mockRejectedValueOnce(makeConflict(item, "rev-4"))
    mapWorkspaceView._unassignObservation(item.item_id)
    expect(await modalHandler()).toBe(false)
    expect(item.updated_at).toBe("rev-4")

    api.world.runMapBatchAction.mockRejectedValueOnce(makeConflict(item, "rev-5"))
    await mapWorkspaceView._batchReviewGroup("status", "confirm")
    expect(await modalHandler()).toBe(false)
    expect(item.updated_at).toBe("rev-5")
  })
})
