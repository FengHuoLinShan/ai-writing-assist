import { beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { parseDynamicHexes, useMapDynamicEditor } from "../../../vue/views/map/useMapDynamicEditor.js"

describe("useMapDynamicEditor", () => {
  let state
  let onSave
  let editor
  beforeEach(() => {
    resetBridgeOverrides()
    state = { currentProjectId: "p1", currentView: "map" }
    onSave = vi.fn(async () => true)
    setBridgeOverrides({ state, toast: vi.fn() })
    editor = useMapDynamicEditor({
      projectId: "p1",
      getViewport: () => ({
        timelineEntityOptions: () => [{ id: "e1", name: "沈澜", entityType: "character" }, { id: "l1", name: "北港", entityType: "location" }],
        timelinePathOptions: () => [{ id: "path1", name: "北境道" }],
      }),
      getLocations: () => [{ id: "l1", name: "北港" }],
      onSaveObservation: onSave,
      onFactStatus: vi.fn(async () => true),
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
    })
  })

  it("validates hex limits and rejects save after project switch", async () => {
    expect(() => parseDynamicHexes("2,x")).toThrow("格式不正确")
    editor.open({ id: "o1", item_kind: "observation", updated_at: "r1", normalized_value: { schema_version: 1, type: "location", state: "present" } })
    state.currentProjectId = "p2"
    await expect(editor.save()).resolves.toBe(false)
    expect(onSave).not.toHaveBeenCalled()
  })
})
