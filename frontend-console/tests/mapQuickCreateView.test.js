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
  mapQuickCreateView._selectedLocationIds = new Set()
  mapQuickCreateView._previousLayoutIds = new Set()
  mapQuickCreateView._includeCandidates = false
  mapQuickCreateView._target = "world"
  mapQuickCreateView._replaceMapId = null
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
    expect(showModal).toHaveBeenCalledWith(
      "快速创建地图",
      expect.objectContaining({ html: expect.stringContaining("洛阳") }),
      expect.any(Array),
    )
    expect(showModal).toHaveBeenCalledWith(
      "快速创建地图",
      expect.objectContaining({ html: expect.stringContaining("已选 1 / 共 1") }),
      expect.any(Array),
    )
    expect(showModal).toHaveBeenCalledWith(
      "快速创建地图",
      expect.objectContaining({ html: expect.stringContaining("map-quick-select-all") }),
      expect.any(Array),
    )
    expect(showModal).toHaveBeenCalledWith(
      "快速创建地图",
      expect.objectContaining({ html: expect.stringContaining("map-quick-extra-search") }),
      expect.any(Array),
    )
    expect(showModal).toHaveBeenCalledWith(
      "快速创建地图",
      expect.objectContaining({ html: expect.not.stringContaining("生成人物等结构化标记") }),
      expect.any(Array),
    )
  })

  it("shows placeable locations when only default spacing is available", async () => {
    api.world.getMapQuickCreateContext.mockResolvedValue({
      locations: [{ id: "loc1", name: "琉璃湾", status: "draft" }],
      candidate_locations: [],
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
        meta: { entity_status: "draft" },
      }],
      warnings: ["缺少地点方向/距离关系，已生成等间距草稿"],
    })

    await mapQuickCreateView.open()

    const modalHtml = showModal.mock.calls.at(-1)[1].html
    expect(modalHtml).toContain("琉璃湾")
    expect(modalHtml).toContain("缺少地点方向/距离关系，已生成等间距草稿")
    expect(modalHtml).not.toContain("暂无可放置地点")
  })

  it("candidate toggle refreshes context and preview", async () => {
    mockQuickCreateApis()

    await mapQuickCreateView.setIncludeCandidates(true)

    expect(api.world.getMapQuickCreateContext).toHaveBeenCalledWith("p1", true)
    expect(api.world.previewQuickCreateMap).toHaveBeenCalledWith(expect.objectContaining({
      include_candidates: true,
    }), "p1")
  })

  it("infers the fixed target level when replacing an existing map", () => {
    expect(mapQuickCreateView._targetForExistingMap({ id: "world" })).toBe("world")
    expect(mapQuickCreateView._targetForExistingMap({
      id: "detail",
      parent_entity_id: "loc1",
    })).toBe("detail")
    expect(mapQuickCreateView._targetForExistingMap({
      id: "drilldown",
      parent_entity_id: "loc2",
      parent_map_id: "detail",
    })).toBe("drilldown")
  })

  it("candidate toggle failure keeps the previous preview and shows feedback", async () => {
    mockQuickCreateApis()
    await mapQuickCreateView.open()
    const previousPreview = mapQuickCreateView._preview
    const previousLayouts = mapQuickCreateView._activeLayouts
    api.world.getMapQuickCreateContext.mockRejectedValueOnce(new Error("context failed"))

    const result = await mapQuickCreateView.setIncludeCandidates(true)

    expect(result).toBe(false)
    expect(mapQuickCreateView._includeCandidates).toBe(false)
    expect(mapQuickCreateView._preview).toBe(previousPreview)
    expect(mapQuickCreateView._activeLayouts).toEqual(previousLayouts)
    expect(toast).toHaveBeenCalledWith("快速创建预览刷新失败：context failed", "error")
  })

  it("target change failure keeps the previous preview and shows feedback", async () => {
    mockQuickCreateApis()
    await mapQuickCreateView.open()
    const previousPreview = mapQuickCreateView._preview
    api.world.previewQuickCreateMap.mockRejectedValueOnce(new Error("preview failed"))

    const result = await mapQuickCreateView.setTarget("detail")

    expect(result).toBe(false)
    expect(mapQuickCreateView._target).toBe("world")
    expect(mapQuickCreateView._preview).toBe(previousPreview)
    expect(toast).toHaveBeenCalledWith("快速创建预览刷新失败：preview failed", "error")
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
    mapQuickCreateView._selectedLocationIds = new Set(["loc1"])
    api.world.confirmQuickCreateMap.mockResolvedValue({
      map: { id: "m1", name: "快速创建世界地图" },
    })

    await mapQuickCreateView._confirm()

    expect(api.world.confirmQuickCreateMap).toHaveBeenCalledWith(expect.objectContaining({
      include_markers: false,
      layouts: mapQuickCreateView._activeLayouts,
    }), "p1")
    expect(onCreated).toHaveBeenCalledWith({ id: "m1", name: "快速创建世界地图" })
  })

  it("shows a visible error when confirm fails", async () => {
    mockQuickCreateApis()
    mapQuickCreateView._preview = {
      location_layouts: [{ location_entity_id: "loc1", center_hex_q: 1, center_hex_r: 1 }],
    }
    mapQuickCreateView._activeLayouts = [
      { location_entity_id: "loc1", center_hex_q: 2, center_hex_r: 3, occupy_radius: 2 },
    ]
    mapQuickCreateView._selectedLocationIds = new Set(["loc1"])
    api.world.confirmQuickCreateMap.mockRejectedValue(new Error("后端服务器错误"))

    const result = await mapQuickCreateView._confirm()

    expect(result).toBe(false)
    expect(closeModal).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("快速创建地图失败：后端服务器错误", "error")
  })

  it("submits only selected layouts", async () => {
    api.world.getMapQuickCreateContext.mockResolvedValue({
      locations: [
        { id: "loc1", name: "洛阳", status: "canonical" },
        { id: "loc2", name: "长安", status: "canonical" },
      ],
      candidate_locations: [],
      existing_maps: [],
      warnings: [],
    })
    api.world.previewQuickCreateMap.mockResolvedValue({
      map: { name: "快速创建世界地图", grid_width: 40, grid_height: 30 },
      location_layouts: [
        { location_entity_id: "loc1", center_hex_q: 10, center_hex_r: 8, occupy_radius: 1 },
        { location_entity_id: "loc2", center_hex_q: 14, center_hex_r: 8, occupy_radius: 1 },
      ],
      warnings: [],
    })
    api.world.confirmQuickCreateMap.mockResolvedValue({
      map: { id: "m1", name: "快速创建世界地图" },
    })

    await mapQuickCreateView.open()
    mapQuickCreateView._toggleSelection("loc1", false)
    await mapQuickCreateView._confirm()

    expect(api.world.confirmQuickCreateMap).toHaveBeenCalledWith(expect.objectContaining({
      layouts: [
        { location_entity_id: "loc2", center_hex_q: 14, center_hex_r: 8, occupy_radius: 1 },
      ],
    }), "p1")
  })

  it("does not confirm when no layouts are selected", async () => {
    mockQuickCreateApis()

    await mapQuickCreateView.open()
    mapQuickCreateView._setAllSelected(false)
    const result = await mapQuickCreateView._confirm()

    expect(result).toBe(false)
    expect(api.world.confirmQuickCreateMap).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("请至少选择一个地点", "warning")
  })

  it("preserves existing selections and keeps newly loaded candidates read-only", async () => {
    api.world.getMapQuickCreateContext.mockResolvedValue({
      locations: [
        { id: "loc1", name: "洛阳", status: "canonical" },
        { id: "loc2", name: "长安", status: "canonical" },
        { id: "loc3", name: "候选城", status: "candidate" },
      ],
      candidate_locations: [{ id: "loc3", name: "候选城", status: "candidate" }],
      existing_maps: [],
      warnings: [],
    })
    api.world.previewQuickCreateMap
      .mockResolvedValueOnce({
        map: { name: "快速创建世界地图", grid_width: 40, grid_height: 30 },
        location_layouts: [
          { location_entity_id: "loc1", center_hex_q: 10, center_hex_r: 8, occupy_radius: 1 },
          { location_entity_id: "loc2", center_hex_q: 14, center_hex_r: 8, occupy_radius: 1 },
        ],
        warnings: [],
      })
      .mockResolvedValueOnce({
        map: { name: "快速创建世界地图", grid_width: 40, grid_height: 30 },
        location_layouts: [
          { location_entity_id: "loc1", center_hex_q: 10, center_hex_r: 8, occupy_radius: 1 },
          { location_entity_id: "loc2", center_hex_q: 14, center_hex_r: 8, occupy_radius: 1 },
          { location_entity_id: "loc3", center_hex_q: 18, center_hex_r: 8, occupy_radius: 1 },
        ],
        warnings: [],
      })

    await mapQuickCreateView.open()
    mapQuickCreateView._toggleSelection("loc1", false)
    await mapQuickCreateView.setIncludeCandidates(true)

    expect(mapQuickCreateView._selectedLocationIds.has("loc1")).toBe(false)
    expect(mapQuickCreateView._selectedLocationIds.has("loc2")).toBe(true)
    expect(mapQuickCreateView._selectedLocationIds.has("loc3")).toBe(false)
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
