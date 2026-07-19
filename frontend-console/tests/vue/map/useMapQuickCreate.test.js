import { beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { useMapQuickCreate } from "../../../vue/views/map/useMapQuickCreate.js"

function apiFixture() {
  return {
    getMapQuickCreateContext: vi.fn(async (_projectId, includeCandidates) => ({
      locations: [{ id: "loc1", name: "洛阳", status: "canonical" }, { id: "loc2", name: "长安", status: "canonical" }],
      candidate_locations: includeCandidates ? [{ id: "loc3", name: "候选城", status: "candidate" }] : [],
      existing_maps: [{ id: "detail", name: "洛阳详图", parent_entity_id: "loc1", map_type: "region", grid_width: 20, grid_height: 10 }],
    })),
    previewQuickCreateMap: vi.fn(async (payload) => ({
      map: { name: "快速创建世界地图", grid_width: payload.grid_width || 40, grid_height: payload.grid_height || 30, map_type: payload.map_type || "world" },
      location_layouts: [
        { location_entity_id: "loc1", center_hex_q: 10, center_hex_r: 8, occupy_radius: 1, locked: false },
        { location_entity_id: "loc2", center_hex_q: 14, center_hex_r: 8, occupy_radius: 1, locked: false },
        ...(payload.include_candidates ? [{ location_entity_id: "loc3", center_hex_q: 18, center_hex_r: 8, occupy_radius: 1, meta: { entity_status: "candidate" } }] : []),
      ], warnings: [],
    })),
    confirmQuickCreateMap: vi.fn(async () => ({ map: { id: "m1", name: "新地图" } })),
  }
}

describe("useMapQuickCreate", () => {
  let api
  let state
  let onCreated
  beforeEach(() => {
    resetBridgeOverrides()
    api = apiFixture()
    state = { currentProjectId: "p1", currentView: "map" }
    onCreated = vi.fn(async () => true)
    setBridgeOverrides({ api: { world: api }, state, toast: vi.fn(), confirm: () => true })
  })

  it("restores selection, move, resize, lock and undo/redo before submitting only selected layouts", async () => {
    const quick = useMapQuickCreate({ projectId: "p1", onCreated })
    await quick.open()
    quick.toggleSelection("loc1", false)
    quick.moveLocation("loc2", 1, 0)
    quick.resizeLocation("loc2", "increase")
    expect(quick.state.activeLayouts.find((item) => item.location_entity_id === "loc2")).toMatchObject({ center_hex_q: 15, occupy_radius: 2 })
    quick.undo()
    expect(quick.state.activeLayouts.find((item) => item.location_entity_id === "loc2").occupy_radius).toBe(1)
    quick.redo()
    quick.toggleLock("loc2")

    await quick.submit()

    expect(api.confirmQuickCreateMap).toHaveBeenCalledWith(expect.objectContaining({
      include_markers: false,
      layouts: [expect.objectContaining({ location_entity_id: "loc2", center_hex_q: 15, occupy_radius: 2, locked: true })],
    }), "p1")
    expect(onCreated).toHaveBeenCalledWith({ id: "m1", name: "新地图" })
  })

  it("keeps candidate layouts read-only and rolls back failed preview changes", async () => {
    const quick = useMapQuickCreate({ projectId: "p1", onCreated })
    await quick.open()
    quick.toggleSelection("loc1", false)
    await quick.setIncludeCandidates(true)
    expect(quick.state.selectedIds.has("loc1")).toBe(false)
    expect(quick.state.selectedIds.has("loc2")).toBe(true)
    expect(quick.state.selectedIds.has("loc3")).toBe(false)
    quick.toggleSelection("loc3", true)
    expect(quick.state.selectedIds.has("loc3")).toBe(false)

    api.previewQuickCreateMap.mockRejectedValueOnce(new Error("preview failed"))
    const previous = quick.state.preview
    await expect(quick.setTarget("detail")).resolves.toBe(false)
    expect(quick.state.target).toBe("world")
    expect(quick.state.preview).toBe(previous)
  })

  it("rejects submission and late completion after project ownership changes", async () => {
    const quick = useMapQuickCreate({ projectId: "p1", onCreated })
    await quick.open()
    state.currentProjectId = "p2"
    await expect(quick.submit()).resolves.toBe(false)
    expect(api.confirmQuickCreateMap).not.toHaveBeenCalled()

    state.currentProjectId = "p1"
    await quick.open()
    let resolveConfirm
    api.confirmQuickCreateMap.mockImplementationOnce(() => new Promise((resolve) => { resolveConfirm = resolve }))
    const pending = quick.submit()
    state.currentProjectId = "p2"
    resolveConfirm({ map: { id: "m2" } })
    await expect(pending).resolves.toBe(false)
    expect(onCreated).not.toHaveBeenCalled()
  })
})
