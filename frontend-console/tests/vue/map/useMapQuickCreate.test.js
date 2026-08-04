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
  let toast
  beforeEach(() => {
    resetBridgeOverrides()
    api = apiFixture()
    state = { currentProjectId: "p1", currentView: "map" }
    onCreated = vi.fn(async () => true)
    toast = vi.fn()
    setBridgeOverrides({ api: { world: api }, state, toast, confirm: () => true })
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
    expect(quick.state.preview).toEqual(previous)
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

  it("allows only the latest overlapping preview request to commit or roll back", async () => {
    const quick = useMapQuickCreate({ projectId: "p1", onCreated })
    await quick.open()
    const originalPreview = quick.state.preview
    const pending = []
    api.previewQuickCreateMap.mockImplementation((payload) => new Promise((resolve, reject) => pending.push({ payload, resolve, reject })))

    const first = quick.changeSetting("gridWidth", 60)
    await vi.waitFor(() => expect(pending).toHaveLength(1))
    const second = quick.changeSetting("gridHeight", 44)
    await vi.waitFor(() => expect(pending).toHaveLength(2))
    pending[1].resolve({
      map: { name: "最新预览", grid_width: 60, grid_height: 44, map_type: "world" },
      location_layouts: [], warnings: [],
    })
    await expect(second).resolves.toBe(true)
    pending[0].reject(new Error("stale preview failed"))
    await expect(first).resolves.toBe(false)

    expect(quick.state.preview.map.name).toBe("最新预览")
    expect(quick.state.gridWidth).toBe(60)
    expect(quick.state.gridHeight).toBe(44)
    expect(toast).not.toHaveBeenCalled()
    expect(quick.state.preview).not.toBe(originalPreview)
  })

  it("rolls back only the newest failed preview and ignores an older late success", async () => {
    const quick = useMapQuickCreate({ projectId: "p1", onCreated })
    await quick.open()
    const originalPreview = quick.state.preview
    const pending = []
    api.previewQuickCreateMap.mockImplementation(() => new Promise((resolve, reject) => pending.push({ resolve, reject })))

    const first = quick.changeSetting("gridWidth", 60)
    await vi.waitFor(() => expect(pending).toHaveLength(1))
    const second = quick.changeSetting("gridHeight", 44)
    await vi.waitFor(() => expect(pending).toHaveLength(2))
    pending[1].reject(new Error("latest preview failed"))
    await expect(second).resolves.toBe(false)
    pending[0].resolve({
      map: { name: "stale success", grid_width: 60, grid_height: 30, map_type: "world" },
      location_layouts: [], warnings: [],
    })
    await expect(first).resolves.toBe(false)

    expect(quick.state.gridWidth).toBe(40)
    expect(quick.state.gridHeight).toBe(30)
    expect(quick.state.preview).toEqual(originalPreview)
    expect(toast).toHaveBeenCalledWith("快速创建预览刷新失败：latest preview failed", "error")
  })

  it("does not let a stale preview finally clear the newer request's loading state", async () => {
    const quick = useMapQuickCreate({ projectId: "p1", onCreated })
    await quick.open()
    const pending = []
    api.previewQuickCreateMap.mockImplementation(() => new Promise((resolve, reject) => pending.push({ resolve, reject })))

    const first = quick.changeSetting("gridWidth", 60)
    await vi.waitFor(() => expect(pending).toHaveLength(1))
    const second = quick.changeSetting("gridHeight", 44)
    await vi.waitFor(() => expect(pending).toHaveLength(2))
    pending[0].reject(new Error("stale preview failed"))
    await expect(first).resolves.toBe(false)
    expect(quick.state.loading).toBe(true)
    pending[1].resolve({ map: { name: "latest", grid_width: 60, grid_height: 44, map_type: "world" }, location_layouts: [], warnings: [] })
    await expect(second).resolves.toBe(true)
    expect(quick.state.loading).toBe(false)
  })

  it("rejects duplicate submit and closes a committed form when its callback fails", async () => {
    let resolveConfirm
    onCreated.mockRejectedValueOnce(new Error("workspace unavailable"))
    api.confirmQuickCreateMap.mockImplementationOnce(() => new Promise((resolve) => { resolveConfirm = resolve }))
    const quick = useMapQuickCreate({ projectId: "p1", onCreated })
    await quick.open()

    const first = quick.submit()
    await expect(quick.submit()).resolves.toBe(false)
    expect(api.confirmQuickCreateMap).toHaveBeenCalledTimes(1)
    resolveConfirm({ map: { id: "m2", name: "已提交地图" } })
    await expect(first).resolves.toBe(false)

    expect(quick.state.open).toBe(false)
    expect(quick.state.saving).toBe(false)
    expect(toast).toHaveBeenCalledWith("地图已创建，但工作区刷新或打开失败。请从地图列表继续。", "warning")
    expect(toast).not.toHaveBeenCalledWith(expect.stringMatching(/^快速创建地图失败/), "error")
  })

  it("treats an active callback false result as a committed-but-unavailable workspace", async () => {
    onCreated.mockResolvedValueOnce(false)
    const quick = useMapQuickCreate({ projectId: "p1", onCreated })
    await quick.open()

    await expect(quick.submit()).resolves.toBe(false)

    expect(quick.state.open).toBe(false)
    expect(api.confirmQuickCreateMap).toHaveBeenCalledTimes(1)
    expect(toast).toHaveBeenCalledWith("地图已创建，但工作区刷新或打开失败。请从地图列表继续。", "warning")
    expect(toast).not.toHaveBeenCalledWith("地图已快速创建", "success")
  })

  it("restores the coherent committed baseline after a mixed context/settings overlap fails", async () => {
    const quick = useMapQuickCreate({ projectId: "p1", onCreated })
    await quick.open()
    const baselinePreview = JSON.parse(JSON.stringify(quick.state.preview))
    const contexts = []
    const previews = []
    api.getMapQuickCreateContext.mockImplementation((_projectId, includeCandidates) => new Promise((resolve) => contexts.push({ includeCandidates, resolve })))
    api.previewQuickCreateMap.mockImplementation((payload) => new Promise((resolve, reject) => previews.push({ payload, resolve, reject })))

    const includeCandidates = quick.setIncludeCandidates(true)
    const setting = quick.changeSetting("gridWidth", 60)
    await vi.waitFor(() => expect(contexts).toHaveLength(2))
    expect(contexts.map((request) => request.includeCandidates)).toEqual([true, true])
    contexts[1].resolve({
      locations: [{ id: "loc1", name: "洛阳" }, { id: "loc2", name: "长安" }],
      candidate_locations: [{ id: "loc3", name: "候选城", status: "candidate" }],
      existing_maps: [],
    })
    await vi.waitFor(() => expect(previews).toHaveLength(1))
    expect(previews[0].payload).toMatchObject({ include_candidates: true, grid_width: 60 })
    quick.state.mapName = "作者仍在输入的名称"
    quick.state.mapNameTouched = true
    previews[0].reject(new Error("latest mixed request failed"))
    await expect(setting).resolves.toBe(false)
    contexts[0].resolve({ locations: [], candidate_locations: [{ id: "stale" }], existing_maps: [] })
    await expect(includeCandidates).resolves.toBe(false)

    expect(quick.state.includeCandidates).toBe(false)
    expect(quick.state.gridWidth).toBe(40)
    expect(quick.state.context.candidate_locations).toEqual([])
    expect(quick.state.preview).toEqual(baselinePreview)
    expect(quick.state.activeLayouts.map((layout) => layout.location_entity_id)).toEqual(["loc1", "loc2"])
    expect(quick.previewPayload()).toMatchObject({ include_candidates: false, grid_width: 40 })
    expect(quick.state.mapName).toBe("作者仍在输入的名称")
  })

  it("does not let a pre-commit completion or callback continuation alter a successor dialog", async () => {
    const quick = useMapQuickCreate({ projectId: "p1", onCreated })
    await quick.open()
    let resolveConfirm
    let resolveCallback
    api.confirmQuickCreateMap.mockImplementationOnce(() => new Promise((resolve) => { resolveConfirm = resolve }))
    onCreated.mockImplementationOnce(() => new Promise((resolve) => { resolveCallback = resolve }))

    const pending = quick.submit()
    resolveConfirm({ map: { id: "m2", name: "已提交地图" } })
    await Promise.resolve()
    expect(onCreated).toHaveBeenCalledWith({ id: "m2", name: "已提交地图" })
    quick.close()
    await quick.open()
    resolveCallback(true)
    await expect(pending).resolves.toBe(false)

    expect(quick.state.open).toBe(true)
    expect(quick.state.saving).toBe(false)
    expect(toast).not.toHaveBeenCalledWith("地图已快速创建", "success")
  })

  it("reports exactly one success after an explicit same-project route handoff disposes the origin", async () => {
    let resolveCallback
    onCreated.mockImplementationOnce(() => new Promise((resolve) => { resolveCallback = resolve }))
    const quick = useMapQuickCreate({ projectId: "p1", onCreated })
    await quick.open()

    const pending = quick.submit()
    await Promise.resolve()
    quick.close()
    resolveCallback({ kind: "map-quick-create-route-handoff", projectId: "p1" })

    await expect(pending).resolves.toBe(true)
    expect(quick.state.open).toBe(false)
    expect(toast).toHaveBeenCalledTimes(1)
    expect(toast).toHaveBeenCalledWith("地图已快速创建", "success")
  })

  it("invalidates a pre-commit submit when the dialog is closed for teardown", async () => {
    const quick = useMapQuickCreate({ projectId: "p1", onCreated })
    await quick.open()
    let resolveConfirm
    api.confirmQuickCreateMap.mockImplementationOnce(() => new Promise((resolve) => { resolveConfirm = resolve }))
    const pending = quick.submit()

    quick.close()
    resolveConfirm({ map: { id: "m2", name: "已提交地图" } })
    await expect(pending).resolves.toBe(false)

    expect(onCreated).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalledWith("地图已快速创建", "success")
    expect(toast).not.toHaveBeenCalledWith(expect.stringMatching(/^快速创建地图失败/), "error")
  })

  it("keeps a committed result quiet after a project switch or teardown", async () => {
    const quick = useMapQuickCreate({ projectId: "p1", onCreated })
    await quick.open()
    let resolveCallback
    onCreated.mockImplementationOnce(() => new Promise((resolve) => { resolveCallback = resolve }))
    const pending = quick.submit()
    await Promise.resolve()
    state.currentProjectId = "p2"
    quick.close()
    resolveCallback(true)
    await expect(pending).resolves.toBe(false)

    expect(quick.state.open).toBe(false)
    expect(toast).not.toHaveBeenCalledWith("地图已快速创建", "success")
    expect(toast).not.toHaveBeenCalledWith(expect.stringMatching(/^快速创建地图失败/), "error")
  })
})
