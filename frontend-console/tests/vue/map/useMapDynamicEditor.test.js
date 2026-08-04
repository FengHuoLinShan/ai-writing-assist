import { beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { parseDynamicHexes, useMapDynamicEditor } from "../../../vue/views/map/useMapDynamicEditor.js"

describe("useMapDynamicEditor", () => {
  let state
  let onSave
  let onFactStatus
  let toast
  let editor
  beforeEach(() => {
    resetBridgeOverrides()
    state = { currentProjectId: "p1", currentView: "map" }
    onSave = vi.fn(async () => true)
    onFactStatus = vi.fn(async () => true)
    toast = vi.fn()
    setBridgeOverrides({ state, toast })
    editor = useMapDynamicEditor({
      projectId: "p1",
      getViewport: () => ({
        timelineEntityOptions: () => [{ id: "e1", name: "沈澜", entityType: "character" }, { id: "l1", name: "北港", entityType: "location" }],
        timelinePathOptions: () => [{ id: "path1", name: "北境道" }],
      }),
      getSpatialContext: () => ({
        map: { id: "m1", name: "九州", grid_width: 20, grid_height: 12 },
        locationAnchors: [{ location_entity_id: "l1", name: "北港", q: 7, r: 4 }],
      }),
      getLocations: () => [{ id: "l1", name: "北港" }],
      onSaveObservation: onSave,
      onFactStatus,
    })
  })

  it("builds all eight schema-v1 typed payloads", () => {
    const cases = [
      ["location", { location_entity_id: "l1", path_id: "path1", movement_mode: "walk", state: "present" }],
      ["route_state", { path_id: "path1", state: "blocked", reason: "暴雨" }],
      ["status", { field_key: "alert", value: "3" }],
      ["boundary", { controller_entity_id: "e1", hexes: [] }],
      ["resource", { resource_key: "grain", controller_entity_id: "e1", amount: "2.5" }],
      ["terrain", { terrain_key: "river", state: "flooded", hexes: [] }],
      ["crisis", { crisis_key: "plague", severity: 4, hexes: [] }],
      ["semantic", { relation_type: "movement_explanation", related_entity_ids: ["e1"], summary: "密道" }],
    ]
    for (const [type, value] of cases) {
      editor.open({ id: `o-${type}`, item_kind: "observation", review_state: "candidate", updated_at: "rev", normalized_value: { schema_version: 1, type, ...value } })
      if (["boundary", "terrain", "crisis"].includes(type)) editor.state.hexText = "2,3\n1,1"
      if (type === "status") editor.state.scalarType = "number"
      const payload = editor.typedValue()
      expect(payload).toMatchObject({ schema_version: 1, type })
      if (["boundary", "terrain", "crisis"].includes(type)) expect(payload.hexes).toEqual([{ hex_q: 1, hex_r: 1 }, { hex_q: 2, hex_r: 3 }])
    }
  })

  it("preserves observation CAS and target metadata on save", async () => {
    editor.open({ id: "o1", item_id: "o1", item_kind: "observation", review_state: "candidate", updated_at: "rev-7", target_entity_id: "e1", normalized_value: { schema_version: 1, type: "route_state", path_id: "path1", state: "open" } })
    editor.state.targetName = "北境道封锁"
    editor.state.value.state = "blocked"
    await editor.save()
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ id: "o1" }), {
      expected_updated_at: "rev-7",
      review_state: "candidate",
      target_entity_id: "e1",
      target_entity_type: "character",
      target_name: "北境道封锁",
      value_json: expect.objectContaining({ schema_version: 1, type: "route_state", path_id: "path1", state: "blocked" }),
      spatial_anchor: { map_id: "m1", path_id: "path1" },
    })
  })

  it("使用地点中心生成 q/r 预览并随候选保存", async () => {
    editor.open({
      id: "o-location", item_kind: "observation", updated_at: "r2",
      normalized_value: { schema_version: 1, type: "location", location_entity_id: "l1", state: "present" },
      spatial_anchor: { location_entity_id: "l1" },
    })
    expect(editor.useLocationCenter()).toBe(true)
    expect(editor.state.anchorQ).toBe("7")
    expect(editor.state.anchorR).toBe("4")

    await editor.save()

    expect(onSave).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({
      spatial_anchor: { map_id: "m1", location_entity_id: "l1", hex_q: 7, hex_r: 4 },
    }))
  })

  it("拒绝超出当前地图网格的落点", async () => {
    editor.open({ id: "o1", item_kind: "observation", updated_at: "r1", normalized_value: { schema_version: 1, type: "location", state: "present" } })
    editor.state.anchorQ = "20"
    editor.state.anchorR = "1"
    await expect(editor.save()).resolves.toBe(false)
    expect(onSave).not.toHaveBeenCalled()
    expect(editor.state.error).toContain("超出当前 20×12 网格")
  })

  it("validates hex limits and rejects save after project switch", async () => {
    expect(() => parseDynamicHexes("2,x")).toThrow("格式不正确")
    editor.open({ id: "o1", item_kind: "observation", updated_at: "r1", normalized_value: { schema_version: 1, type: "location", state: "present" } })
    state.currentProjectId = "p2"
    await expect(editor.save()).resolves.toBe(false)
    expect(onSave).not.toHaveBeenCalled()
  })

  it("drops stale save completion after close and reopening another item", async () => {
    let resolveSave
    onSave.mockImplementationOnce(() => new Promise((resolve) => { resolveSave = resolve }))
    editor.open({ id: "old", item_kind: "observation", updated_at: "r1", normalized_value: { schema_version: 1, type: "location", state: "present" } })
    const pending = editor.save()
    expect(editor.state.saving).toBe(true)
    editor.close()
    editor.open({ id: "new", item_kind: "observation", updated_at: "r2", normalized_value: { schema_version: 1, type: "location", state: "present" } })
    resolveSave(true)
    await expect(pending).resolves.toBe(false)
    expect(editor.state.item.id).toBe("new")
    expect(editor.state.open).toBe(true)
    expect(editor.state.saving).toBe(false)
  })

  it("rejects duplicate saves while the owning request is pending", async () => {
    let resolveSave
    onSave.mockImplementationOnce(() => new Promise((resolve) => { resolveSave = resolve }))
    editor.open({ id: "one", item_kind: "observation", updated_at: "r1", normalized_value: { schema_version: 1, type: "location", state: "present" } })
    const first = editor.save()
    await expect(editor.save()).resolves.toBe(false)
    expect(onSave).toHaveBeenCalledOnce()
    resolveSave(true)
    await first
  })

  it("drops stale save errors and finalizers after close/reopen without a toast", async () => {
    let rejectSave
    onSave.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectSave = reject }))
    editor.open({ id: "old", item_kind: "observation", updated_at: "r1", normalized_value: { schema_version: 1, type: "location", state: "present" } })
    const pending = editor.save()
    editor.close()
    editor.open({ id: "new", item_kind: "observation", updated_at: "r2", normalized_value: { schema_version: 1, type: "location", state: "present" } })
    rejectSave(new Error("old request failed"))

    await expect(pending).resolves.toBe(false)
    expect(editor.state.item.id).toBe("new")
    expect(editor.state.saving).toBe(false)
    expect(editor.state.error).toBeNull()
    expect(toast).not.toHaveBeenCalled()
  })

  it("drops a pending save after project switch or unmount-equivalent close", async () => {
    let resolveSave
    onSave.mockImplementationOnce(() => new Promise((resolve) => { resolveSave = resolve }))
    editor.open({ id: "old", item_kind: "observation", updated_at: "r1", normalized_value: { schema_version: 1, type: "location", state: "present" } })
    const pending = editor.save()
    state.currentProjectId = "p2"
    editor.close()
    resolveSave(true)

    await expect(pending).resolves.toBe(false)
    expect(editor.state.open).toBe(false)
    expect(toast).not.toHaveBeenCalled()
  })

  it("keeps the fact editor open when a fact status update is cancelled", async () => {
    onFactStatus.mockResolvedValueOnce(false)
    editor.open({ id: "f1", item_kind: "fact", fact_status: "confirmed", updated_at: "r1", normalized_value: { schema_version: 1, type: "status", field_key: "weather", value: "rain" } })

    await expect(editor.save()).resolves.toBe(false)

    expect(onFactStatus).toHaveBeenCalledWith(expect.objectContaining({ id: "f1" }), "confirmed")
    expect(editor.state.open).toBe(true)
  })
})
