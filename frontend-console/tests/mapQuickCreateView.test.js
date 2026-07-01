import { beforeEach, describe, expect, it, vi } from "vitest"
import mapQuickCreateView from "../views/mapQuickCreateView.js"
import { clearDocument, resetState } from "./helpers.js"

beforeEach(() => {
  resetState({ currentProjectId: "p1" })
  clearDocument()
  vi.clearAllMocks()
  mapQuickCreateView._context = null
  mapQuickCreateView._preview = null
  mapQuickCreateView._activeLayouts = []
  mapQuickCreateView._layoutHistory = []
  mapQuickCreateView._includeCandidates = false
  mapQuickCreateView._target = "world"
  mapQuickCreateView._onCreated = null
})

function mockQuickCreateApis() {
  api.world.getMapQuickCreateContext.mockResolvedValue({
    locations: [{ id: "loc1", name: "洛阳", status: "canonical" }],
    candidate_locations: [{ id: "loc2", name: "候选城", status: "candidate" }],
    existing_maps: [],
    warnings: [],
  })
  api.world.previewQuickCreateMap.mockResolvedValue({
    map: { name: "快速创建世界地图", grid_width: 40, grid_height: 30 },
    location_layouts: [{
      location_entity_id: "loc1",
      center_hex_q: 10,
      center_hex_r: 8,
      occupy_radius: 1,
      locked: false,
    }],
    warnings: [],
  })
}

describe("mapQuickCreateView", () => {
  it("opens preview without confirming", async () => {
    mockQuickCreateApis()

    await mapQuickCreateView.open()

    expect(api.world.getMapQuickCreateContext).toHaveBeenCalledWith("p1", false)
    expect(api.world.previewQuickCreateMap).toHaveBeenCalledWith(expect.objectContaining({
      include_candidates: false,
    }), "p1")
    expect(api.world.confirmQuickCreateMap).not.toHaveBeenCalled()
    expect(showModal).toHaveBeenCalledWith("快速创建地图", expect.stringContaining("洛阳"), expect.any(Array))
    expect(showModal).toHaveBeenCalledWith(
      "快速创建地图",
      expect.not.stringContaining("生成人物等结构化标记"),
      expect.any(Array),
    )
  })

  it("candidate toggle refreshes context and preview", async () => {
    mockQuickCreateApis()

    await mapQuickCreateView.setIncludeCandidates(true)

    expect(api.world.getMapQuickCreateContext).toHaveBeenCalledWith("p1", true)
    expect(api.world.previewQuickCreateMap).toHaveBeenCalledWith(expect.objectContaining({
      include_candidates: true,
    }), "p1")
  })

  it("confirm creates one map and invokes callback", async () => {
    mockQuickCreateApis()
    const onCreated = vi.fn()
    mapQuickCreateView._onCreated = onCreated
    mapQuickCreateView._preview = {
      location_layouts: [{ location_entity_id: "loc1", center_hex_q: 1, center_hex_r: 1 }],
    }
    mapQuickCreateView._activeLayouts = [
      { location_entity_id: "loc1", center_hex_q: 2, center_hex_r: 3, occupy_radius: 2 },
    ]
    api.world.confirmQuickCreateMap.mockResolvedValue({
      map: { id: "m1", name: "快速创建世界地图" },
    })

    await mapQuickCreateView._confirm()

    expect(api.world.confirmQuickCreateMap).toHaveBeenCalledWith(expect.objectContaining({
      include_markers: false,
      layouts: mapQuickCreateView._activeLayouts,
    }), "p1")
    expect(closeModal).toHaveBeenCalled()
    expect(onCreated).toHaveBeenCalledWith({ id: "m1", name: "快速创建世界地图" })
  })

  it("updates active preview layout before confirm", async () => {
    mockQuickCreateApis()
    await mapQuickCreateView.open()

    mapQuickCreateView._moveLocation("loc1", 1, 0)
    mapQuickCreateView._resizeLocation("loc1", "increase")

    expect(mapQuickCreateView._activeLayouts[0]).toMatchObject({
      center_hex_q: 11,
      center_hex_r: 8,
      occupy_radius: 2,
    })

    mapQuickCreateView._undoLayout()
    expect(mapQuickCreateView._activeLayouts[0]).toMatchObject({
      center_hex_q: 11,
      occupy_radius: 1,
    })
  })
})
