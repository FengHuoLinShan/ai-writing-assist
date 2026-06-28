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
