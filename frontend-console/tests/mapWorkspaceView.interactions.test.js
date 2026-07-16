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
describe("mapWorkspaceView dirty guard", () => {
  it("exposes route leave confirmation without tearing down the map", () => {
    const guard = vi.spyOn(mapView, "canLeave").mockReturnValue(false)
    const unmount = vi.spyOn(mapView, "unmount")

    expect(mapWorkspaceView.canLeave()).toBe(false)
    expect(unmount).not.toHaveBeenCalled()
    guard.mockRestore()
    unmount.mockRestore()
  })

  it("marks browser unload when map edits are dirty", () => {
    mapWorkspaceView._editingState = { editing: true, dirty: true, editorLayer: "location" }
    mapWorkspaceView._bindBeforeUnloadGuard()
    const event = new Event("beforeunload", { cancelable: true })

    window.dispatchEvent(event)

    expect(event.defaultPrevented).toBe(true)
  })

  it("blocks switching to another map while edits are dirty", () => {
    mapWorkspaceView._mode = "map"
    mapWorkspaceView._activeMapId = "m1"
    const guard = vi.spyOn(mapView, "canLeave").mockReturnValue(false)
    const refresh = vi.spyOn(router, "refresh")

    expect(mapWorkspaceView._openMap("m2")).toBe(false)

    expect(mapWorkspaceView._activeMapId).toBe("m1")
    expect(refresh).not.toHaveBeenCalled()
    guard.mockRestore()
    refresh.mockRestore()
  })

  it("clears the workspace dirty state after a confirmed map switch", () => {
    mapWorkspaceView._mode = "map"
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._editingState = { editing: true, dirty: true, editorLayer: "marker" }
    const guard = vi.spyOn(mapView, "canLeave").mockReturnValue(true)
    const refresh = vi.spyOn(router, "refresh").mockImplementation(() => {})

    expect(mapWorkspaceView._openMap("m2")).toBe(true)

    expect(mapWorkspaceView._editingState).toEqual({
      editing: false,
      dirty: false,
      editorLayer: "none",
    })
    guard.mockRestore()
    refresh.mockRestore()
  })
})

describe("mapWorkspaceView overview", () => {
  it("pushes cross-map navigation and replaces same-map context changes", () => {
    mapWorkspaceView._maps = [
      { id: "m1", name: "九州", map_type: "world", parent_map_id: null },
      { id: "m2", name: "洛阳", map_type: "city", parent_map_id: "m1" },
    ]
    mapWorkspaceView._rebuildMapIndexes()
    const leave = vi.spyOn(mapView, "canLeave").mockReturnValue(true)

    expect(mapWorkspaceView._openMap("m1")).toBe(true)
    expect(router.navigate).toHaveBeenLastCalledWith(
      "map",
      null,
      true,
      expect.any(URLSearchParams),
    )

    vi.clearAllMocks()
    expect(mapWorkspaceView._openMap("m1", { sceneId: "s1" })).toBe(true)
    expect(router.replace).toHaveBeenLastCalledWith(
      "map",
      null,
      expect.any(URLSearchParams),
    )

    vi.clearAllMocks()
    expect(mapWorkspaceView._openMap("m2")).toBe(true)
    expect(router.navigate).toHaveBeenLastCalledWith(
      "map",
      null,
      true,
      expect.any(URLSearchParams),
    )
    leave.mockRestore()
  })

  it("replaces history for view mode changes inside one map", () => {
    mapWorkspaceView._mode = "map"
    mapWorkspaceView._activeMapId = "m1"
    const leave = vi.spyOn(mapView, "canLeave").mockReturnValue(true)
    const unmount = vi.spyOn(mapView, "unmount").mockImplementation(() => {})

    expect(mapWorkspaceView._setViewMode("lens")).toBe(true)

    expect(router.replace).toHaveBeenCalledWith(
      "map",
      null,
      expect.any(URLSearchParams),
    )
    const query = router.replace.mock.calls.at(-1)[2]
    expect(query.get("map_id")).toBe("m1")
    expect(query.get("mode")).toBe("lens")
    expect(unmount).toHaveBeenCalledTimes(1)
    leave.mockRestore()
    unmount.mockRestore()
  })

  it("keeps the current mode and URL when leaving a dirty map is rejected", () => {
    mapWorkspaceView._mode = "map"
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._viewMode = "dashboard"
    const leave = vi.spyOn(mapView, "canLeave").mockReturnValue(false)

    expect(mapWorkspaceView._setViewMode("lens")).toBe(false)

    expect(mapWorkspaceView._viewMode).toBe("dashboard")
    expect(router.replace).not.toHaveBeenCalled()
    leave.mockRestore()
  })

  it("renders overview with recent map entry and map tree", () => {
    mapWorkspaceView._maps = [
      { id: "m1", name: "九州世界", map_type: "world", parent_map_id: null },
      { id: "m2", name: "洛阳", map_type: "city", parent_map_id: "m1" },
    ]
    mapWorkspaceView._saveRecentMap({
      id: "m1",
      name: "九州世界",
      map_type: "world",
    })

    const html = mapWorkspaceView._renderOverview()

    expect(html).toContain("打开最近地图")
    expect(html).toContain("九州世界")
    expect(html).toContain("洛阳")
  })

  it("renders only archived subtree roots and restores from a named root", async () => {
    mapWorkspaceView._showArchivedMaps = true
    mapWorkspaceView._archivedMaps = [
      { id: "root", name: "旧世界", map_type: "world", parent_map_id: null },
      { id: "child", name: "旧都", map_type: "city", parent_map_id: "root" },
    ]

    const html = mapWorkspaceView._renderOverview()

    expect(html).toContain("旧世界")
    expect(html).not.toContain("旧都")
    mapWorkspaceView._showRestoreMapForm("root")
    const buttons = showModalHtml.mock.calls.at(-1)[2]
    document.body.innerHTML = '<input id="map-restore-root-name" value="复原世界" />'
    api.world.restoreMap.mockResolvedValue({})
    api.world.listMaps
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({ items: [] })
    api.world.listEntities.mockResolvedValue({ items: [] })

    await buttons[0].handler()

    expect(api.world.restoreMap).toHaveBeenCalledWith(
      "root",
      { root_name: "复原世界" },
      "p1",
    )
  })

  it("opens the archived list without resetting its local view state", async () => {
    mapWorkspaceView._archivedMaps = [
      { id: "root", name: "旧世界", map_type: "world", parent_map_id: null },
    ]
    document.body.innerHTML = `<main id="workspace-content">${mapWorkspaceView._renderOverview()}</main>`
    mapWorkspaceView._bindEvents()

    document.querySelector("[data-action='map-toggle-archived']").click()
    await vi.waitFor(() => expect(router.renderCurrentView).toHaveBeenCalled())

    expect(mapWorkspaceView._showArchivedMaps).toBe(true)
    expect(router.refresh).not.toHaveBeenCalled()
  })

  it("keeps the restore form open after a name conflict", async () => {
    mapWorkspaceView._archivedMaps = [
      { id: "root", name: "旧世界", map_type: "world", parent_map_id: null },
    ]
    mapWorkspaceView._showRestoreMapForm("root")
    const buttons = showModalHtml.mock.calls.at(-1)[2]
    document.body.innerHTML = '<input id="map-restore-root-name" value="旧世界" />'
    api.world.restoreMap.mockRejectedValue(new Error("同层同名冲突"))

    const result = await buttons[0].handler()

    expect(result).toBe(false)
    expect(closeModal).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("恢复失败：同层同名冲突", "error")
  })

  it("loads archive impact before confirming subtree archive", async () => {
    mapWorkspaceView._maps = [{ id: "m1", name: "九州", parent_map_id: null }]
    mapWorkspaceView._rebuildMapIndexes()
    api.world.getMapArchiveImpact.mockResolvedValue({
      map_count: 2,
      asset_counts: { tiles: 16, markers: 2 },
    })
    api.world.archiveMap.mockResolvedValue({ status: "archived" })
    api.world.listMaps
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({ items: [] })
    api.world.listEntities.mockResolvedValue({ items: [] })
    autoConfirm()

    await mapWorkspaceView._archiveMap("m1")
    await Promise.resolve()

    expect(confirmAction).toHaveBeenCalledWith(
      expect.stringContaining("18 个关联资产"),
      expect.any(Function),
      "归档子树",
    )
    expect(api.world.archiveMap).toHaveBeenCalledWith("m1", "p1")
  })

  it("uses map indexes for tree rendering and opening maps", () => {
    const maps = [
      { id: "m1", name: "九州世界", map_type: "world", parent_map_id: null },
      { id: "m2", name: "洛阳", map_type: "city", parent_map_id: "m1", parent_entity_id: "loc1" },
    ]
    maps.find = () => { throw new Error("map lookup should use indexes") }
    maps.filter = () => { throw new Error("map tree should use parent index") }
    mapWorkspaceView._maps = maps
    mapWorkspaceView._rebuildMapIndexes()
    const refresh = vi.spyOn(router, "refresh").mockImplementation(() => {})

    const tree = mapWorkspaceView._renderMapTree()
    mapWorkspaceView._openMap("m1")
    mapWorkspaceView._openLocation("loc1")

    expect(tree).toContain("九州世界")
    expect(tree).toContain("洛阳")
    expect(mapWorkspaceView._activeMapId).toBe("m2")
    refresh.mockRestore()
  })

  it("clears stale recent map and shows the required fallback message", async () => {
    mapWorkspaceView._saveRecentMap({
      id: "missing",
      name: "旧地图",
      map_type: "world",
    })
    api.world.getMap.mockRejectedValue(new Error("404"))

    await mapWorkspaceView._openRecentMap()

    expect(localStorage.getItem("novel_map_recent:p1")).toBeNull()
    expect(mapWorkspaceView._mode).toBe("overview")
    expect(toast).toHaveBeenCalledWith("最近地图不可用，已返回地图总览", "warning")
  })

  it("opens recent map with route scene context", async () => {
    mapWorkspaceView._activeSceneId = "s1"
    mapWorkspaceView._focusEntityId = "f1"
    mapWorkspaceView._saveRecentMap({
      id: "m1",
      name: "九州世界",
      map_type: "world",
    })
    api.world.getMap.mockResolvedValue({ id: "m1", name: "九州世界", map_type: "world" })
    const openSpy = vi.spyOn(mapWorkspaceView, "_openMap")

    await mapWorkspaceView._openRecentMap()

    expect(openSpy).toHaveBeenCalledWith("m1", {
      sceneId: "s1",
      focusEntityId: "f1",
      history: "replace",
    })
    openSpy.mockRestore()
  })

  it("opens recent route context in live view when requested", async () => {
    mapWorkspaceView._activeSceneId = "s1"
    mapWorkspaceView._focusEntityId = "f1"
    mapWorkspaceView._saveRecentMap({
      id: "m1",
      name: "九州世界",
      map_type: "world",
    })
    api.world.getMap.mockResolvedValue({ id: "m1", name: "九州世界", map_type: "world" })
    const openSpy = vi.spyOn(mapWorkspaceView, "_openMap")

    await mapWorkspaceView._openRecentMap({ viewMode: "live" })

    expect(openSpy).toHaveBeenCalledWith("m1", {
      sceneId: "s1",
      focusEntityId: "f1",
      viewMode: "live",
      history: "replace",
    })
    openSpy.mockRestore()
  })

  it("does not reopen recent route after it has resolved to an active map", async () => {
    window.location.hash = "#workbench/p1/map?focus_entity_id=f1&mode=recent"
    mapWorkspaceView._mode = "map"
    mapWorkspaceView._activeMapId = "m1"
    const recentSpy = vi.spyOn(mapWorkspaceView, "_openRecentMap").mockResolvedValue()
    const mountSpy = vi.spyOn(mapWorkspaceView, "_mountMap").mockImplementation(() => {})

    const html = await mapWorkspaceView.render()

    expect(html).toContain("map-workspace-active")
    expect(mapWorkspaceView._focusEntityId).toBe("f1")
    expect(recentSpy).not.toHaveBeenCalled()
    recentSpy.mockRestore()
    mountSpy.mockRestore()
  })

  it("mounts the active map from onRendered after the route DOM is committed", async () => {
    window.location.hash = "#workbench/p1/map?map_id=m1"
    mapWorkspaceView._mode = "map"
    mapWorkspaceView._activeMapId = "m1"
    const mountSpy = vi.spyOn(mapWorkspaceView, "_mountMap").mockImplementation(() => {})

    const html = await mapWorkspaceView.render()
    expect(mountSpy).not.toHaveBeenCalled()
    document.body.innerHTML = `<main id="workspace-content">${html}</main>`

    await mapWorkspaceView.onRendered()

    expect(document.getElementById("map-root")).not.toBeNull()
    expect(mountSpy).toHaveBeenCalledTimes(1)
    mountSpy.mockRestore()
  })

  it("falls back to backend open target when recent route has no recent map", async () => {
    mapWorkspaceView._activeSceneId = "s1"
    mapWorkspaceView._focusEntityId = "f1"
    api.world.getMapOpenTarget.mockResolvedValue({
      map_id: "m2",
      scene_id: "s1",
      focus_entity_id: "f1",
      mode: "dashboard",
    })
    const openSpy = vi.spyOn(mapWorkspaceView, "_openMap")

    await mapWorkspaceView._openRecentMap({ viewMode: "live" })

    expect(api.world.getMapOpenTarget).toHaveBeenCalledWith("p1", {
      sceneId: "s1",
      focusEntityId: "f1",
    })
    expect(openSpy).toHaveBeenCalledWith("m2", {
      sceneId: "s1",
      focusEntityId: "f1",
      viewMode: "live",
      history: "replace",
    })
    expect(toast).not.toHaveBeenCalledWith("最近地图不可用，已返回地图总览", "warning")
    openSpy.mockRestore()
  })

  it("falls back to backend open target when stale recent map has route context", async () => {
    mapWorkspaceView._activeSceneId = "s1"
    mapWorkspaceView._saveRecentMap({
      id: "missing",
      name: "旧地图",
      map_type: "world",
    })
    api.world.getMap.mockRejectedValue(new Error("404"))
    api.world.getMapOpenTarget.mockResolvedValue({
      map_id: "m2",
      scene_id: "s1",
      mode: "live",
    })
    const openSpy = vi.spyOn(mapWorkspaceView, "_openMap")

    await mapWorkspaceView._openRecentMap({ viewMode: "live" })

    expect(localStorage.getItem("novel_map_recent:p1")).toBeNull()
    expect(api.world.getMapOpenTarget).toHaveBeenCalledWith("p1", {
      sceneId: "s1",
      focusEntityId: null,
    })
    expect(openSpy).toHaveBeenCalledWith("m2", {
      sceneId: "s1",
      focusEntityId: null,
      viewMode: "live",
      history: "replace",
    })
    openSpy.mockRestore()
  })

  it("filters maps and locations by search text", () => {
    mapWorkspaceView._maps = [{ id: "m1", name: "九州世界", map_type: "world" }]
    mapWorkspaceView._locations = [
      { id: "loc1", name: "洛阳外城", entity_type: "location" },
    ]

    const results = mapWorkspaceView._search("洛阳")

    expect(results).toEqual([
      { type: "location", id: "loc1", name: "洛阳外城", entity: mapWorkspaceView._locations[0] },
    ])
  })

  it("loads locations without exceeding backend page size", async () => {
    api.world.listMaps.mockResolvedValue({ items: [] })
    api.world.listEntities.mockImplementation(async (params) => {
      if (params.limit > 50) {
        throw new Error("422")
      }
      return {
        items: params.skip === 0
          ? Array.from({ length: 50 }, (_, index) => ({ id: `loc${index}`, name: `地点${index}` }))
          : [{ id: "loc50", name: "地点50" }],
      }
    })

    await mapWorkspaceView._loadData()

    expect(mapWorkspaceView._locations).toHaveLength(51)
    expect(api.world.listEntities).toHaveBeenNthCalledWith(1, expect.objectContaining({
      novel_id: "p1",
      entity_type: "location",
      skip: 0,
      limit: 50,
    }))
    expect(api.world.listEntities).toHaveBeenNthCalledWith(2, expect.objectContaining({
      skip: 50,
      limit: 50,
    }))
  })

  it("propagates load failures without replacing known data with empty lists", async () => {
    mapWorkspaceView._maps = [{ id: "known-map" }]
    mapWorkspaceView._archivedMaps = [{ id: "known-archive" }]
    mapWorkspaceView._locations = [{ id: "known-location" }]
    api.world.listMaps.mockRejectedValue(new Error("network down"))
    api.world.listEntities.mockResolvedValue({ items: [] })

    await expect(mapWorkspaceView._loadData()).rejects.toThrow("network down")

    expect(mapWorkspaceView._maps).toEqual([{ id: "known-map" }])
    expect(mapWorkspaceView._archivedMaps).toEqual([{ id: "known-archive" }])
    expect(mapWorkspaceView._locations).toEqual([{ id: "known-location" }])
  })

  it("does not let an older project data load overwrite the current project", async () => {
    let resolveOldActive
    let resolveOldArchived
    let resolveOldLocations
    const listMaps = vi.spyOn(mapWorkspaceView, "_listAllMaps")
      .mockImplementation((status, projectId) => {
        if (projectId === "p1") {
          return new Promise((resolve) => {
            if (status === "active") resolveOldActive = resolve
            else resolveOldArchived = resolve
          })
        }
        return Promise.resolve([{ id: `${status}-${projectId}` }])
      })
    const listLocations = vi.spyOn(mapWorkspaceView, "_listAllLocations")
      .mockImplementation((projectId) => {
        if (projectId === "p1") {
          return new Promise((resolve) => { resolveOldLocations = resolve })
        }
        return Promise.resolve([{ id: `location-${projectId}` }])
      })

    const oldLoad = mapWorkspaceView._loadData()
    await vi.waitFor(() => {
      expect(resolveOldActive).toBeTypeOf("function")
      expect(resolveOldArchived).toBeTypeOf("function")
      expect(resolveOldLocations).toBeTypeOf("function")
    })
    state.currentProjectId = "p2"
    await expect(mapWorkspaceView._loadData()).resolves.toBe(true)

    resolveOldActive([{ id: "active-p1" }])
    resolveOldArchived([{ id: "archived-p1" }])
    resolveOldLocations([{ id: "location-p1" }])
    await expect(oldLoad).resolves.toBe(false)

    expect(mapWorkspaceView._maps).toEqual([{ id: "active-p2" }])
    expect(mapWorkspaceView._archivedMaps).toEqual([{ id: "archived-p2" }])
    expect(mapWorkspaceView._locations).toEqual([{ id: "location-p2" }])
    listMaps.mockRestore()
    listLocations.mockRestore()
  })

  it("clears active and archived data when there is no current project", async () => {
    state.currentProjectId = null
    mapWorkspaceView._maps = [{ id: "active-old" }]
    mapWorkspaceView._archivedMaps = [{ id: "archived-old" }]
    mapWorkspaceView._locations = [{ id: "location-old" }]

    await expect(mapWorkspaceView._loadData()).resolves.toBe(true)

    expect(mapWorkspaceView._maps).toEqual([])
    expect(mapWorkspaceView._archivedMaps).toEqual([])
    expect(mapWorkspaceView._locations).toEqual([])
  })

  it("toggles layer visibility", () => {
    mapWorkspaceView._setLayer("markers", false)

    expect(mapWorkspaceView._layers.markers).toBe(false)
  })

  it("keeps candidate layer off by default and renders an explicit toggle", () => {
    const html = mapWorkspaceView._renderLayerToggles()

    expect(mapWorkspaceView._layers.candidate).toBe(false)
    expect(html).toContain('data-layer="candidate"')
    expect(html).toContain("待处理")
    expect(html).not.toMatch(/data-layer="candidate"[\s\S]*?checked/)
  })

  it("can enable the candidate layer from the workspace context", () => {
    mapWorkspaceView._setLayer("candidate", true)

    expect(mapWorkspaceView._layers.candidate).toBe(true)
  })

  it("renders dynamic fact summary with author-facing labels", () => {
    mapWorkspaceView._dynamicSummary = {
      mapId: "m1",
      loading: false,
      loaded: true,
      dashboard: {
        title: "世界动态总控台",
        first_visual_layer: {
          main_crisis: "洛阳外城",
          main_characters: ["沈砚"],
          top_risks: ["洛阳外城：待确认"],
        },
        dynamic_queue: [
          {
            item_id: "obs-technical-id",
            item_kind: "observation",
            title: "沈砚",
            time_label: "Scene 42",
            status_label: "待确认",
            source_summary: "deep_import_delta_event · 沈砚穿过东门。",
            confidence: 0.82,
            review_state: "candidate",
            risk_level: "warning",
          },
          {
            item_id: "fact-technical-id",
            item_kind: "fact",
            title: "洛阳外城",
            time_label: "第 12 章",
            status_label: "已确认",
            source_summary: "manual_edit",
            fact_status: "confirmed",
            risk_level: "info",
          },
        ],
        inspector: {
          title: "沈砚",
          status_label: "待确认",
          summary: "右侧检查器汇总候选映射、正式事实、冲突风险和来源证据。",
          ai_candidates: [{ title: "沈砚" }],
          map_facts: [{ title: "洛阳外城" }],
          conflicts: [],
          source_evidence: ["deep_import_delta_event · 沈砚穿过东门。"],
        },
        batch_groups: [{
          group_key: "character",
          group_label: "人物",
          count: 2,
          candidate_count: 1,
          confirmed_count: 1,
          first_joined_label: "Scene 42",
        }],
      },
      observations: [],
      facts: [],
      error: null,
    }

    const html = mapWorkspaceView._renderDynamicSummary()
    const container = renderHtml(html)

    expect(container.textContent).toContain("沈砚")
    expect(container.textContent).toContain("Scene 42")
    expect(container.textContent).toContain("洛阳外城：待处理")
    expect(container.textContent).not.toContain("待确认")
    expect(container.textContent).toContain("置信度 82%")
    expect(container.textContent).toContain("洛阳外城")
    expect(container.textContent).toContain("检查器")
    expect(container.textContent).toContain("批量修改")
    expect(container.textContent).toContain("人物")
    expectNoTechnicalIds(container, ["obs-technical-id", "fact-technical-id"])
  })

  it("hides UUID debug refs from dashboard and object info default text", () => {
    const observationId = "123e4567-e89b-12d3-a456-426614174000"
    const entityId = "123e4567-e89b-12d3-a456-426614174001"
    mapWorkspaceView._dynamicSummary = {
      mapId: "m1",
      loading: false,
      loaded: true,
      dashboard: {
        title: "世界动态总控台",
        first_visual_layer: {
          main_crisis: "洛阳封锁",
          main_characters: ["沈砚"],
          top_risks: ["洛阳封锁：有冲突"],
        },
        dynamic_queue: [{
          item_id: observationId,
          item_kind: "observation",
          target_entity_id: entityId,
          title: "洛阳封锁",
          type_label: "地点动态",
          location_label: "洛阳外城",
          spatial_anchor_label: "坐标 2,2",
          time_label: "Scene 3",
          status_label: "冲突",
          source_summary: "第 1 章 · 城门忽然封闭。",
          confidence: 0.66,
          review_state: "conflicted",
          risk_level: "danger",
          debug_ref: {
            id: observationId,
            scene_id: "123e4567-e89b-12d3-a456-426614174002",
          },
        }],
        inspector: {
          title: "洛阳封锁",
          status_label: "冲突",
          type_label: "地点动态",
          location_label: "洛阳外城",
          spatial_anchor_label: "坐标 2,2",
          summary: "右侧检查器显示作者可读摘要。",
          ai_candidates: [{ title: "洛阳封锁" }],
          map_facts: [],
          conflicts: [{ title: "洛阳封锁" }],
          source_evidence: ["第 1 章 · 城门忽然封闭。"],
          debug_ref: { id: observationId },
        },
        batch_groups: [],
      },
      observations: [],
      facts: [],
      error: null,
    }

    const html = mapWorkspaceView._renderDynamicSummary()
    const container = renderHtml(html)
    expect(container.textContent).toContain("洛阳封锁")
    expect(container.textContent).toContain("洛阳外城")
    expect(container.textContent).not.toContain(observationId)
    expect(container.textContent).not.toContain(entityId)
    expect(container.textContent).not.toContain("scene_id")

    mapWorkspaceView._showDynamicObjectInfo(observationId)
    const body = modalHtmlFromCall(showModal.mock.calls.at(-1))
    expect(body).toContain("洛阳外城")
    expect(body).toContain("坐标 2,2")
    expect(body).not.toContain(observationId)
    expect(body).not.toContain(entityId)
  })

  it("renders three map modes, low motion toggle, and semantic bubble band", () => {
    mapWorkspaceView._mode = "map"
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._viewMode = "lens"
    mapWorkspaceView._lowMotion = true
    mapWorkspaceView._dynamicSummary = {
      mapId: "m1",
      loading: false,
      loaded: true,
      dashboard: {
        title: "世界动态总控台",
        dynamic_queue: [
          {
            item_id: "secret-technical-id",
            item_kind: "observation",
            title: "东门密道",
            object_type: "location",
            dynamic_type: "secret",
            time_label: "Scene 42",
            status_label: "待确认",
            source_summary: "沈砚发现墙后暗门。",
            priority: 90,
            risk_level: "warning",
            review_state: "candidate",
          },
        ],
        inspector: {
          title: "东门密道",
          status_label: "待确认",
          summary: "语义气泡进入上方空白带。",
        },
      },
      observations: [],
      facts: [],
      error: null,
    }

    const html = mapWorkspaceView._renderMapWorkspace()
    const container = document.createElement("div")
    container.innerHTML = html

    expect(container.textContent).toContain("世界动态总控台")
    expect(container.textContent).toContain("活地图")
    expect(container.textContent).toContain("叙事透镜")
    expect(container.textContent).toContain("低动效")
    expect(container.textContent).toContain("东门密道")
    expect(container.querySelector("[data-view-mode='lens']").className).toContain("is-active")
    expect(container.querySelector("[data-action='map-low-motion-toggle']").checked).toBe(true)
    expectNoTechnicalIds(container, ["secret-technical-id"])
  })

  it("loads dynamic summary for the active map", async () => {
    mapWorkspaceView._activeMapId = "m1"
    api.world.getMapDashboard.mockResolvedValue({
      dynamic_queue: [
        { item_id: "obs1", item_kind: "observation", title: "沈砚" },
        { item_id: "fact1", item_kind: "fact", title: "洛阳" },
      ],
    })
    api.world.getMapPlayback.mockResolvedValue({
      events: [{ event_id: "play1", title: "沈砚入城", track: "journey" }],
      tracks: [{ track: "journey", label: "人物旅程", count: 1 }],
    })

    await mapWorkspaceView._loadDynamicSummary({ force: true })

    expect(api.world.getMapDashboard).toHaveBeenCalledWith("m1", "p1", null, null, null)
    expect(api.world.getMapPlayback).toHaveBeenCalledWith("m1", "p1", null, null, true)
    expect(mapWorkspaceView._dynamicSummary.observations).toHaveLength(1)
    expect(mapWorkspaceView._dynamicSummary.facts).toHaveLength(1)
    expect(mapWorkspaceView._playback.playback.events).toHaveLength(1)
  })

  it("retries dynamic summary after a cached load error", async () => {
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._dynamicSummary = {
      mapId: "m1",
      loading: false,
      loaded: true,
      dashboard: null,
      observations: [],
      facts: [],
      error: "地图动态事实暂不可用",
    }
    mapWorkspaceView._playback = {
      loading: false,
      loaded: true,
      playback: null,
      error: "世界动态播放暂不可用",
      playing: false,
      activeIndex: 0,
    }
    api.world.getMapDashboard.mockResolvedValue({
      dynamic_queue: [{ item_id: "obs1", item_kind: "observation", title: "沈砚" }],
    })
    api.world.getMapPlayback.mockResolvedValue({
      events: [{ event_id: "play1", title: "沈砚入城", track: "journey" }],
      tracks: [{ track: "journey", label: "人物旅程", count: 1 }],
    })

    await mapWorkspaceView._loadDynamicSummary()

    expect(api.world.getMapDashboard).toHaveBeenCalledWith("m1", "p1", null, null, null)
    expect(api.world.getMapPlayback).toHaveBeenCalledWith("m1", "p1", null, null, true)
    expect(mapWorkspaceView._dynamicSummary.error).toBeNull()
    expect(mapWorkspaceView._playback.error).toBeNull()
  })

  it("renders and starts cinematic playback without exposing event ids", () => {
    mapWorkspaceView._playback = {
      loading: false,
      loaded: true,
      error: null,
      playing: false,
      activeIndex: 0,
      playback: {
        title: "世界动态播放",
        tracks: [{ track: "journey", label: "人物旅程", count: 1 }],
        events: [{
          event_id: "technical-playback-id",
          title: "沈砚入城",
          time_label: "Scene 1",
          status_label: "已确认",
          change_summary: "位置：东门 → 内城",
          risk_level: "info",
        }],
      },
    }

    const html = mapWorkspaceView._renderPlaybackPanel()
    const container = document.createElement("div")
    container.innerHTML = html

    expect(html).toContain("电影化播放")
    expect(html).toContain("人物旅程 1")
    expect(html).toContain("沈砚入城")
    expect(html).toContain("位置：东门 → 内城")
    expect(container.textContent).not.toContain("technical-playback-id")

    mapWorkspaceView._startPlayback()

    expect(mapWorkspaceView._playback.playing).toBe(true)
    mapWorkspaceView._stopPlayback()
    expect(mapWorkspaceView._playback.playing).toBe(false)
  })

  it("播放带 path anchor 的事件时激活线路和楼层分支", () => {
    const focus = vi.spyOn(mapView, "focusPath").mockReturnValue(true)
    mapWorkspaceView._playback = {
      playing: false,
      activeIndex: 0,
      playback: { events: [{
        event_id: "event-1",
        spatial_anchor: { path_id: "path-1", layer_node_id: "floor-1" },
      }] },
    }

    mapWorkspaceView._startPlayback()

    expect(focus).toHaveBeenCalledWith("path-1", "floor-1")
    mapWorkspaceView._stopPlayback()
    focus.mockRestore()
  })

  it("播放切到非 path 事件、停止或结束时清理旧线路高亮", () => {
    const clear = vi.spyOn(mapView, "clearPathFocus").mockImplementation(() => {})
    mapWorkspaceView._playback = {
      playing: true,
      activeIndex: 0,
      playback: { events: [{ event_id: "event-plain", spatial_anchor: { q: 1, r: 1 } }] },
    }

    expect(mapWorkspaceView._syncPlaybackPathFocus()).toBe(false)
    expect(clear).toHaveBeenCalledTimes(1)

    mapWorkspaceView._stopPlayback()
    expect(clear).toHaveBeenCalledTimes(2)
    clear.mockRestore()
  })

  it("回放线路更新提示使用已加载 path revision 比较", () => {
    const mismatch = vi.spyOn(mapView, "pathRevisionMismatch").mockReturnValue(true)
    mapWorkspaceView._playback = {
      loading: false,
      error: null,
      activeIndex: 0,
      playback: { events: [{
        event_id: "event-1",
        title: "穿过旧桥",
        spatial_anchor: { path_id: "path-1", path_revision: 2 },
      }] },
    }

    expect(mapWorkspaceView._renderPlaybackPanel()).toContain("线路已更新")
    expect(mismatch).toHaveBeenCalledWith({ path_id: "path-1", path_revision: 2 })
    mismatch.mockRestore()
  })

  it("opens dynamic object info with edit and inspector actions", () => {
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._dynamicSummary = {
      dashboard: {
        dynamic_queue: [{
          item_id: "technical-object-id",
          item_kind: "observation",
          title: "沈砚入城",
          target_entity_id: "char-1",
          time_label: "Scene 1",
          status_label: "待确认",
          type_label: "人物动态",
          location_label: "洛阳内城",
          spatial_anchor_label: "东门",
          review_state: "candidate",
          source_summary: "deep_import · 沈砚进入内城。",
        }],
      },
    }

    mapWorkspaceView._showDynamicObjectInfo("technical-object-id")

    expect(showModal).toHaveBeenCalled()
    const call = showModal.mock.calls.at(-1)
    const [title, , actions] = call
    const body = modalHtmlFromCall(call)
    expect(title).toContain("沈砚入城")
    expect(body).toContain("Scene 1")
    expect(body).toContain("待处理")
    expect(body).toContain("人物动态")
    expect(body).toContain("洛阳内城")
    expect(body).toContain("东门")
    expect(body).not.toContain("technical-object-id")
    expect(actions.map((action) => action.text)).toEqual([
      "修改",
      "采用",
      "忽略",
      "标记冲突",
      "更换地图",
      "取消分配",
      "复制诊断信息",
      "打开检查器",
    ])
  })

  it("updates observation review and fact status from object info actions", async () => {
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._dynamicSummary = {
      dashboard: {
        dynamic_queue: [
          {
            item_id: "obs1",
            item_kind: "observation",
            title: "沈砚入城",
            review_state: "candidate",
            status_label: "待确认",
          },
          {
            item_id: "fact1",
            item_kind: "fact",
            title: "林照据守",
            fact_status: "confirmed",
            status_label: "已确认",
          },
        ],
      },
      observations: [{ item_id: "obs1", title: "沈砚入城", updated_at: "rev-1" }],
      facts: [{ item_id: "fact1", title: "林照据守" }],
    }
    api.world.updateMapObservationReview.mockResolvedValue({ id: "obs1" })
    api.world.updateMapFactStatus.mockResolvedValue({ id: "fact1" })
    api.world.getMapDashboard.mockResolvedValue({
      dynamic_queue: [{
        item_id: "obs1",
        item_kind: "observation",
        title: "沈砚",
        target_entity_id: "char-1",
        object_type: "character",
        review_state: "candidate",
        updated_at: "rev-1",
      }],
      batch_groups: [{
        group_key: "character",
        group_label: "人物",
        count: 1,
        candidate_count: 1,
        confirmed_count: 0,
        time_groups: [{
          time_key: "scene-1",
          time_label: "Scene 1",
          count: 1,
          candidate_count: 1,
          confirmed_count: 0,
        }],
      }],
    })
    api.world.getMapPlayback.mockResolvedValue({ events: [], tracks: [] })
    confirmAction.mockImplementation((_message, onConfirm) => onConfirm())

    await mapWorkspaceView._markObservationConflict("obs1")
    await mapWorkspaceView._updateFactStatus("fact1", "rolled_back")

    expect(api.world.updateMapObservationReview).toHaveBeenCalledWith(
      "m1",
      "obs1",
      "p1",
      { expected_updated_at: "rev-1", review_state: "conflicted" },
    )
    expect(api.world.updateMapFactStatus).toHaveBeenCalledWith(
      "m1",
      "fact1",
      "p1",
      "rolled_back",
    )
  })

  it("edits only author-owned observation fields before confirmation", async () => {
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._dynamicSummary = {
      dashboard: { dynamic_queue: [] },
      observations: [{
        item_id: "obs1",
        item_kind: "observation",
        title: "沈砚入城",
        target_name: "沈砚",
        target_entity_type: "character",
        dynamic_type: "position_change",
        review_state: "candidate",
        time_anchor: { chapter: 1 },
        spatial_anchor: { q: 1, r: 1 },
        value_json: { field: "location", old: "东门", new: "内城" },
        source_ref: { source: "deep_import" },
        evidence_text: "原始证据",
        confidence: 0.4,
        updated_at: "rev-1",
      }],
      facts: [],
    }
    api.world.updateMapObservationReview.mockResolvedValue({ id: "obs1" })
    api.world.getMapDashboard.mockResolvedValue({ dynamic_queue: [], batch_groups: [] })
    api.world.getMapPlayback.mockResolvedValue({ events: [], tracks: [] })
    confirmAction.mockImplementation((_message, onConfirm) => onConfirm())

    mapWorkspaceView._showDynamicEditForm(mapWorkspaceView._dynamicSummary.observations[0])
    const call = showModal.mock.calls.at(-1)
    const [, , buttons] = call
    const body = modalHtmlFromCall(call)
    document.body.innerHTML = body
    document.getElementById("map-object-edit-target-name").value = "沈砚修订"
    expect(body).not.toMatch(/时间锚点 JSON|空间锚点 JSON|来源引用 JSON|高级 JSON/)
    expect(document.getElementById("map-object-edit-confidence")).toBeNull()
    expect(document.getElementById("map-object-edit-evidence")).toBeNull()

    await buttons[0].handler()

    expect(api.world.updateMapObservationReview).toHaveBeenCalledWith(
      "m1",
      "obs1",
      "p1",
      {
        expected_updated_at: "rev-1",
        review_state: "candidate",
        target_entity_id: null,
        target_entity_type: null,
        target_name: "沈砚修订",
      },
    )
  })

  it("opens focused inspector and batch reviews candidate groups", async () => {
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._dynamicSummary = {
      dashboard: {
        dynamic_queue: [{
          item_id: "obs1",
          item_kind: "observation",
          title: "沈砚",
          target_entity_id: "char-1",
          object_type: "character",
          review_state: "candidate",
        }],
        batch_groups: [{
          group_key: "character",
          group_label: "人物",
          count: 1,
          candidate_count: 1,
          confirmed_count: 0,
        }],
      },
      observations: [{ item_id: "obs1", title: "沈砚", updated_at: "rev-1" }],
      facts: [],
    }
    api.world.getMapDashboard.mockResolvedValue({
      dynamic_queue: [{
        item_id: "obs1",
        item_kind: "observation",
        title: "沈砚",
        target_entity_id: "char-1",
        object_type: "character",
        review_state: "candidate",
        updated_at: "rev-1",
      }],
      batch_groups: [{
        group_key: "character",
        group_label: "人物",
        count: 1,
        candidate_count: 1,
        confirmed_count: 0,
        time_groups: [{
          time_key: "scene-1",
          time_label: "Scene 1",
          count: 1,
          candidate_count: 1,
          confirmed_count: 0,
        }],
      }],
    })
    api.world.getMapPlayback.mockResolvedValue({ events: [], tracks: [] })
    api.world.runMapBatchAction.mockResolvedValue({ updated_count: 1 })
    confirmAction.mockImplementation((_message, onConfirm) => onConfirm())

    await mapWorkspaceView._openFocusedInspector("char-1")
    await mapWorkspaceView._batchReviewGroup("character", "confirm")

    expect(api.world.getMapDashboard)
      .toHaveBeenCalledWith("m1", "p1", null, "char-1", null)
    expect(api.world.runMapBatchAction).toHaveBeenCalledWith(
      "m1",
      "p1",
      {
        action: "confirm_observations",
        observation_items: [{
          observation_id: "obs1",
          expected_updated_at: "rev-1",
        }],
      },
    )
  })

  it("processes oversized map groups one service-sized batch at a time", async () => {
    const observations = Array.from({ length: 101 }, (_, index) => ({
      item_id: `obs-${index + 1}`,
      item_kind: "observation",
      object_type: "large-group",
      review_state: "candidate",
      updated_at: `rev-${index + 1}`,
    }))
    mapWorkspaceView._dynamicSummary = {
      dashboard: { dynamic_queue: observations },
      observations,
      facts: [],
    }
    mapWorkspaceView._rebuildDynamicIndexes()
    confirmAction.mockImplementation((_message, onConfirm) => onConfirm())
    api.world.runMapBatchAction.mockResolvedValue({ updated_count: 100 })

    await mapWorkspaceView._batchReviewGroup("large-group", "confirm")

    expect(confirmAction.mock.calls[0][0]).toContain("本次先采用 100 条")
    expect(api.world.runMapBatchAction).toHaveBeenCalledWith(
      mapWorkspaceView._activeMapId,
      "p1",
      {
        action: "confirm_observations",
        observation_items: Array.from({ length: 100 }, (_, index) => ({
          observation_id: `obs-${index + 1}`,
          expected_updated_at: `rev-${index + 1}`,
        })),
      },
    )
  })

  it("uses cached dynamic indexes instead of repeated linear item lookup", async () => {
    const observation = {
      item_id: "obs1",
      item_kind: "observation",
      title: "沈砚",
      target_entity_id: "char-1",
      object_type: "character",
      review_state: "candidate",
      updated_at: "rev-1",
    }
    const event = {
      event_id: "evt1",
      title: "沈砚移动",
    }
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._dynamicSummary = {
      dashboard: { dynamic_queue: [observation] },
      observations: [observation],
      facts: [],
    }
    mapWorkspaceView._playback = {
      playback: { events: [event], tracks: [] },
    }
    mapWorkspaceView._rebuildDynamicIndexes()
    mapWorkspaceView._dynamicSummary.dashboard.dynamic_queue.find = () => {
      throw new Error("dynamic_queue.find should not be used for id lookup")
    }
    mapWorkspaceView._dynamicSummary.observations.find = () => {
      throw new Error("observations.find should not be used for id lookup")
    }
    mapWorkspaceView._playback.playback.events.find = () => {
      throw new Error("playback.events.find should not be used for id lookup")
    }
    confirmAction.mockImplementation((_message, onConfirm) => onConfirm())
    api.world.confirmMapObservation.mockResolvedValue({ id: "obs1" })
    api.world.getMapDashboard.mockResolvedValue({ dynamic_queue: [], batch_groups: [] })
    api.world.getMapPlayback.mockResolvedValue({ events: [], tracks: [] })

    expect(mapWorkspaceView._findDynamicItem("obs1")).toBe(observation)
    expect(mapWorkspaceView._findDynamicItem("evt1")).toBe(event)
    await mapWorkspaceView._confirmObservation("obs1")

    expect(api.world.confirmMapObservation).toHaveBeenCalledWith("m1", "obs1", "p1", "rev-1")
  })

  it("renders batch groups with object type and map time hierarchy", () => {
    const html = mapWorkspaceView._renderBatchGroups([{
      group_key: "character",
      group_label: "人物",
      count: 3,
      candidate_count: 2,
      confirmed_count: 1,
      first_joined_label: "Scene 1",
      time_groups: [
        { time_key: "scene-1", time_label: "Scene 1", count: 2, candidate_count: 1, confirmed_count: 1 },
        { time_key: "scene-2", time_label: "Scene 2", count: 1, candidate_count: 1, confirmed_count: 0 },
      ],
    }])

    expect(html).toContain("人物")
    expect(html).toContain("Scene 1")
    expect(html).toContain("Scene 2")
    expect(html).toContain("2 待处理")
  })

  it("counts conflicted observations as pending attention and hides history by default", () => {
    mapWorkspaceView._dynamicSummary = {
      dashboard: {
        title: "世界动态总控台",
        dynamic_queue: [
          {
            item_id: "candidate-1",
            item_kind: "observation",
            object_type: "character",
            title: "候选位置",
            review_state: "candidate",
          },
          {
            item_id: "conflicted-1",
            item_kind: "observation",
            object_type: "character",
            title: "冲突位置",
            review_state: "conflicted",
          },
          {
            item_id: "fact-1",
            item_kind: "fact",
            object_type: "character",
            title: "已采用位置",
            fact_status: "confirmed",
          },
          {
            item_id: "ignored-1",
            item_kind: "observation",
            object_type: "character",
            title: "历史位置",
            review_state: "ignored",
          },
        ],
        batch_groups: [],
      },
      observations: [],
      facts: [],
    }

    mapWorkspaceView._rebuildDynamicIndexes()
    const html = mapWorkspaceView._renderDynamicSummary()

    expect(html).toContain("2 待处理 · 1 已采用")
    expect(html).toContain("存在冲突")
    expect(html).toContain("查看历史 1")
    expect(html).not.toContain("历史位置")
    expect(mapWorkspaceView._dynamicIndexes.candidateIdsByGroup.get("character"))
      .toEqual(["candidate-1", "conflicted-1"])

    mapWorkspaceView._showHistory = true
    expect(mapWorkspaceView._renderDynamicSummary()).toContain("历史位置")
  })

  it("只在作者打开历史时加载 ignored 观察及 rolled-back/deprecated 事实", async () => {
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._dynamicSummary = {
      dashboard: { title: "世界动态总控台", dynamic_queue: [], batch_groups: [] },
      observations: [],
      facts: [],
      historyItems: [],
      historyLoaded: false,
      historyLoading: false,
    }
    api.world.listMapObservations.mockResolvedValue({
      items: [{ id: "obs-old", review_state: "ignored", target_name: "已忽略密道" }],
    })
    api.world.listMapFacts.mockImplementation((_mapId, _novelId, factStatus) => ({
      items: factStatus === "deprecated"
        ? [{ id: "fact-deprecated", fact_status: "deprecated", target_name: "已废弃旧路" }]
        : [{ id: "fact-old", fact_status: "rolled_back", target_name: "已回滚驻地" }],
    }))

    expect(mapWorkspaceView._renderDynamicSummary()).toContain("查看历史")
    expect(api.world.listMapObservations).not.toHaveBeenCalled()

    await mapWorkspaceView._toggleHistory()

    expect(api.world.listMapObservations).toHaveBeenCalledWith("m1", "p1", "ignored")
    expect(api.world.listMapFacts).toHaveBeenCalledWith("m1", "p1", "rolled_back")
    expect(api.world.listMapFacts).toHaveBeenCalledWith("m1", "p1", "deprecated")
    expect(mapWorkspaceView._renderDynamicSummary()).toContain("已忽略密道")
    expect(mapWorkspaceView._renderDynamicSummary()).toContain("已回滚驻地")
    expect(mapWorkspaceView._renderDynamicSummary()).toContain("已废弃旧路")

    await mapWorkspaceView._toggleHistory()
    await mapWorkspaceView._toggleHistory()
    expect(api.world.listMapObservations).toHaveBeenCalledTimes(1)
    expect(api.world.listMapFacts).toHaveBeenCalledTimes(2)
  })

  it("requests focused dashboard for dynamic items without entity ids", async () => {
    mapWorkspaceView._activeMapId = "m1"
    const selectInspectorObject = vi.spyOn(mapView, "selectInspectorObject")
    api.world.getMapDashboard.mockResolvedValue({
      dynamic_queue: [{ item_id: "obs1", item_kind: "observation", title: "东门密道" }],
      inspector: {
        title: "东门密道",
        status_label: "待确认",
        debug_ref: { id: "obs1" },
      },
    })
    api.world.getMapPlayback.mockResolvedValue({ events: [], tracks: [] })

    await mapWorkspaceView._openFocusedInspector(null, "obs1")

    expect(api.world.getMapDashboard).toHaveBeenCalledWith(
      "m1",
      "p1",
      null,
      null,
      "obs1",
    )
    expect(mapWorkspaceView._dynamicSummary.dashboard.inspector.title).toBe("东门密道")
    expect(selectInspectorObject).toHaveBeenCalledWith(
      "observation",
      expect.objectContaining({ item_id: "obs1" }),
    )
    selectInspectorObject.mockRestore()
  })

  it("locally focuses inspector for dynamic items without entity ids", () => {
    mapWorkspaceView._focusedDynamicItemId = "obs1"
    mapWorkspaceView._dynamicSummary = {
      dashboard: {
        dynamic_queue: [
          {
            item_id: "obs1",
            item_kind: "observation",
            title: "东门密道",
            object_type: "location",
            dynamic_type: "secret",
            review_state: "candidate",
            status_label: "待确认",
            source_summary: "沈砚发现墙后暗门。",
          },
          {
            item_id: "fact1",
            item_kind: "fact",
            title: "东门密道",
            object_type: "location",
            dynamic_type: "secret",
            fact_status: "confirmed",
            status_label: "已确认",
            source_summary: "地图上存在旧暗门。",
          },
          {
            item_id: "other1",
            item_kind: "observation",
            title: "西市码头",
            object_type: "location",
            dynamic_type: "location_state",
            review_state: "candidate",
            status_label: "待确认",
          },
        ],
        inspector: {
          title: "总控台",
          status_label: "全局",
          ai_candidates: [],
          map_facts: [],
          conflicts: [],
          source_evidence: [],
        },
      },
      observations: [],
      facts: [],
    }

    const html = mapWorkspaceView._renderDynamicSummary()
    const container = document.createElement("div")
    container.innerHTML = html
    const inspector = container.querySelector(".map-inspector")

    expect(inspector.textContent).toContain("东门密道")
    expect(inspector.textContent).toContain("待处理 1")
    expect(inspector.textContent).toContain("已采用 1")
    expect(inspector.textContent).not.toContain("西市码头")
    expect(inspector.textContent).not.toContain("obs1")
  })

  it("confirms a map observation and refreshes summary", async () => {
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._dynamicSummary.observations = [{
      item_id: "obs1",
      title: "沈砚",
      updated_at: "rev-1",
    }]
    api.world.confirmMapObservation.mockResolvedValue({ id: "fact1" })
    api.world.getMapDashboard.mockResolvedValue({
      dynamic_queue: [{ item_id: "fact1", item_kind: "fact", title: "沈砚" }],
    })
    api.world.getMapPlayback.mockResolvedValue({ events: [], tracks: [] })
    confirmAction.mockImplementation((_message, onConfirm) => onConfirm())

    await mapWorkspaceView._confirmObservation("obs1")

    expect(api.world.confirmMapObservation).toHaveBeenCalledWith("m1", "obs1", "p1", "rev-1")
    expect(toast).toHaveBeenCalledWith("地图事实已采用", "success")
  })

  it("opens a searched location on its detail map", async () => {
    const root = document.createElement("div")
    root.id = "workspace-content"
    root.innerHTML = `<button data-action="map-search-location" data-id="loc1">洛阳</button>`
    document.body.append(root)
    mapWorkspaceView._maps = [
      { id: "m1", name: "九州世界", map_type: "world", parent_map_id: null },
      {
        id: "m2",
        name: "洛阳详图",
        map_type: "city",
        parent_map_id: "m1",
        parent_entity_id: "loc1",
      },
    ]
    const openSpy = vi.spyOn(mapWorkspaceView, "_openMap").mockImplementation(() => {})

    mapWorkspaceView._bindEvents()
    root.querySelector("[data-action='map-search-location']").click()
    await Promise.resolve()

    expect(openSpy).toHaveBeenCalledWith("m2", { focusEntityId: "loc1" })
    openSpy.mockRestore()
  })

  it("reloads data and opens the map returned by quick-create", async () => {
    const quickCreateSpy = vi.spyOn(mapQuickCreateView, "open").mockImplementation(
      async ({ onCreated } = {}) => {
        await onCreated?.({ id: "quick-map", name: "快速创建世界地图", map_type: "world" })
      },
    )
    const loadSpy = vi.spyOn(mapWorkspaceView, "_loadData").mockResolvedValue()
    const openSpy = vi.spyOn(mapWorkspaceView, "_openMap").mockImplementation(() => {})

    await mapWorkspaceView._openQuickCreate()

    expect(loadSpy).toHaveBeenCalled()
    expect(openSpy).toHaveBeenCalledWith("quick-map", { viewMode: "live" })
    quickCreateSpy.mockRestore()
    loadSpy.mockRestore()
    openSpy.mockRestore()
  })

  it("shows a visible error when quick-create cannot open", async () => {
    const quickCreateSpy = vi.spyOn(mapQuickCreateView, "open").mockRejectedValue(
      new Error("后端服务器错误"),
    )

    const result = await mapWorkspaceView._openQuickCreate()

    expect(result).toBeNull()
    expect(toast).toHaveBeenCalledWith("快速创建地图失败：后端服务器错误", "error")
    quickCreateSpy.mockRestore()
  })

  it("warns before quick-create when no project is selected", async () => {
    state.currentProjectId = null
    const quickCreateSpy = vi.spyOn(mapQuickCreateView, "open")

    const result = await mapWorkspaceView._openQuickCreate()

    expect(result).toBeNull()
    expect(quickCreateSpy).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("请先选择项目", "warning")
    quickCreateSpy.mockRestore()
  })

  it("shows feedback when delegated async action rejects", async () => {
    document.body.innerHTML = `
      <main id="workspace-content">
        <button data-action="map-search-location" data-id="loc1">打开地点</button>
      </main>
    `
    const openLocationSpy = vi.spyOn(mapWorkspaceView, "_openLocation")
      .mockRejectedValue(new Error("location failed"))

    mapWorkspaceView._bindEvents()
    document.querySelector("[data-action='map-search-location']").click()

    await vi.waitFor(() => {
      expect(toast).toHaveBeenCalledWith("操作失败：location failed", "error")
    })
    openLocationSpy.mockRestore()
  })

  it("does not schedule a timer to mount an already selected map", async () => {
    vi.useFakeTimers()
    const timerSpy = vi.spyOn(globalThis, "setTimeout")
    mapWorkspaceView._mode = "map"
    mapWorkspaceView._activeMapId = "m1"

    await mapWorkspaceView.render()

    expect(timerSpy).not.toHaveBeenCalled()
    vi.useRealTimers()
  })

  it("keeps an explicit overview route on the map list", async () => {
    vi.useFakeTimers()
    const timerSpy = vi.spyOn(globalThis, "setTimeout")
    window.location.hash = "#workbench/p1/map?mode=overview"
    mapWorkspaceView._mode = "overview"
    mapWorkspaceView._activeMapId = null

    const html = await mapWorkspaceView.render()

    expect(html).toContain("空间总览")
    expect(timerSpy).not.toHaveBeenCalled()
    vi.useRealTimers()
  })
})
