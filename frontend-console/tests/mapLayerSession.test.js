import { beforeEach, describe, expect, it } from "vitest"
import {
  activeSelectionReason,
  layerSessionStorageKey,
  resolveLayerSelections,
  sessionLayerVisible,
  setLayerSelection,
} from "../views/mapLayerSession.js"

const nodes = [
  { id: "world", node_type: "group", selection_mode: "normal", visible: true, sort_order: 0 },
  { id: "floor", parent_id: "world", node_type: "group", selection_mode: "floor", visible: true, sort_order: 0 },
  { id: "f0", parent_id: "floor", node_type: "group", selection_mode: "exclusive", floor_level: 0, visible: true, sort_order: 1 },
  { id: "f1", parent_id: "floor", node_type: "group", selection_mode: "normal", floor_level: 1, visible: true, sort_order: 0 },
  { id: "a", parent_id: "f0", node_type: "leaf", selection_mode: "normal", visible: true, sort_order: 0 },
  { id: "b", parent_id: "f0", node_type: "leaf", selection_mode: "normal", visible: true, sort_order: 1 },
  { id: "c", parent_id: "f1", node_type: "leaf", selection_mode: "normal", visible: true, sort_order: 0 },
]

describe("mapLayerSession", () => {
  beforeEach(() => localStorage.clear())

  it("楼层默认选 level 0，exclusive 选第一个子层", () => {
    const selections = resolveLayerSelections({ nodes, novelId: "n1", mapId: "m1" })
    expect(selections).toEqual({ floor: "f0", f0: "a" })
    expect(JSON.parse(localStorage.getItem(layerSessionStorageKey("n1", "m1")))).toEqual(selections)
    expect(sessionLayerVisible(nodes[4], nodes, selections)).toBe(true)
    expect(sessionLayerVisible(nodes[5], nodes, selections)).toBe(false)
    expect(sessionLayerVisible(nodes[6], nodes, selections)).toBe(false)
  })

  it("路由焦点优先激活全部祖先分支", () => {
    localStorage.setItem(layerSessionStorageKey("n1", "m1"), JSON.stringify({ floor: "f1", f0: "a" }))
    const selections = resolveLayerSelections({
      nodes,
      novelId: "n1",
      mapId: "m1",
      focusNodeId: "b",
    })
    expect(selections).toMatchObject({ floor: "f0", f0: "b" })
    expect(activeSelectionReason(nodes[4], nodes, selections)).toBe("非当前独占图层")
    expect(activeSelectionReason(nodes[5], nodes, selections)).toBeNull()
  })

  it("只接受 group 的直接子层，isolate 只显示目标子树", () => {
    const original = resolveLayerSelections({ nodes, novelId: "n1", mapId: "m1" })
    expect(setLayerSelection({ nodes, selections: original, groupId: "floor", childId: "a" })).toBe(original)
    expect(sessionLayerVisible(nodes[4], nodes, original, "f0")).toBe(true)
    expect(sessionLayerVisible(nodes[0], nodes, original, "f0")).toBe(false)
  })
})

