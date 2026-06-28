import { describe, it, expect, vi, beforeEach } from "vitest"
import mapWorkspaceView from "../views/mapWorkspaceView.js"
import { resetState, clearDocument } from "./helpers.js"

beforeEach(() => {
  resetState({ currentProjectId: "p1" })
  clearDocument()
  localStorage.clear()
  vi.useRealTimers()
  vi.clearAllMocks()
  mapWorkspaceView._maps = []
  mapWorkspaceView._locations = []
  mapWorkspaceView._mode = "overview"
  mapWorkspaceView._message = null
  mapWorkspaceView._activeMapId = null
  mapWorkspaceView._activeSceneId = null
  mapWorkspaceView._focusEntityId = null
  mapWorkspaceView._resetDynamicSummary?.()
  mapWorkspaceView._resetPlayback?.()
  mapWorkspaceView._clearPendingTimers?.()
})

describe("mapWorkspaceView overview", () => {
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
    const openSpy = vi.spyOn(mapWorkspaceView, "_openMap").mockImplementation(() => {})

    await mapWorkspaceView._openRecentMap()

    expect(openSpy).toHaveBeenCalledWith("m1", {
      sceneId: "s1",
      focusEntityId: "f1",
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

  it("toggles layer visibility", () => {
    mapWorkspaceView._setLayer("markers", false)

    expect(mapWorkspaceView._layers.markers).toBe(false)
  })

  it("keeps candidate layer off by default and renders an explicit toggle", () => {
    const html = mapWorkspaceView._renderLayerToggles()

    expect(mapWorkspaceView._layers.candidate).toBe(false)
    expect(html).toContain('data-layer="candidate"')
    expect(html).toContain("待确认")
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
    const container = document.createElement("div")
    container.innerHTML = html

    expect(html).toContain("沈砚")
    expect(html).toContain("Scene 42")
    expect(html).toContain("待确认")
    expect(html).toContain("置信度 82%")
    expect(html).toContain("洛阳外城")
    expect(html).toContain("检查器")
    expect(html).toContain("批量修改")
    expect(html).toContain("人物")
    expect(container.textContent).not.toContain("obs-technical-id")
    expect(container.textContent).not.toContain("fact-technical-id")
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

    expect(html).toContain("世界动态总控台")
    expect(html).toContain("活地图")
    expect(html).toContain("叙事透镜")
    expect(html).toContain("低动效")
    expect(html).toContain("东门密道")
    expect(container.querySelector("[data-view-mode='lens']").className).toContain("is-active")
    expect(container.querySelector("[data-action='map-low-motion-toggle']").checked).toBe(true)
    expect(container.textContent).not.toContain("secret-technical-id")
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

    expect(api.world.getMapDashboard).toHaveBeenCalledWith("m1", "p1", null, null)
    expect(api.world.getMapPlayback).toHaveBeenCalledWith("m1", "p1", null, null, true)
    expect(mapWorkspaceView._dynamicSummary.observations).toHaveLength(1)
    expect(mapWorkspaceView._dynamicSummary.facts).toHaveLength(1)
    expect(mapWorkspaceView._playback.playback.events).toHaveLength(1)
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

  it("opens dynamic object info with edit and inspector actions", () => {
    mapWorkspaceView._dynamicSummary = {
      dashboard: {
        dynamic_queue: [{
          item_id: "technical-object-id",
          title: "沈砚入城",
          time_label: "Scene 1",
          status_label: "待确认",
          source_summary: "deep_import · 沈砚进入内城。",
        }],
      },
    }

    mapWorkspaceView._showDynamicObjectInfo("technical-object-id")

    expect(showModal).toHaveBeenCalled()
    const [title, body, actions] = showModal.mock.calls.at(-1)
    expect(title).toContain("沈砚入城")
    expect(body).toContain("Scene 1")
    expect(body).toContain("待确认")
    expect(body).not.toContain("technical-object-id")
    expect(actions.map((action) => action.text)).toEqual(["修改", "打开检查器"])
  })

  it("confirms a map observation and refreshes summary", async () => {
    mapWorkspaceView._activeMapId = "m1"
    mapWorkspaceView._dynamicSummary.observations = [{ item_id: "obs1", title: "沈砚" }]
    api.world.confirmMapObservation.mockResolvedValue({ id: "fact1" })
    api.world.getMapDashboard.mockResolvedValue({
      dynamic_queue: [{ item_id: "fact1", item_kind: "fact", title: "沈砚" }],
    })
    api.world.getMapPlayback.mockResolvedValue({ events: [], tracks: [] })
    confirmAction.mockImplementation((_message, onConfirm) => onConfirm())

    await mapWorkspaceView._confirmObservation("obs1")

    expect(api.world.confirmMapObservation).toHaveBeenCalledWith("m1", "obs1", "p1")
    expect(toast).toHaveBeenCalledWith("地图事实已确认", "success")
  })

  it("opens a searched location on its detail map", () => {
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

    expect(openSpy).toHaveBeenCalledWith("m2", { focusEntityId: "loc1" })
    openSpy.mockRestore()
  })

  it("clears pending render timers on leave", async () => {
    vi.useFakeTimers()
    const clearSpy = vi.spyOn(globalThis, "clearTimeout")
    mapWorkspaceView._mode = "map"
    mapWorkspaceView._activeMapId = "m1"

    await mapWorkspaceView.render()
    mapWorkspaceView.onLeave()

    expect(clearSpy).toHaveBeenCalled()
    vi.useRealTimers()
  })
})
