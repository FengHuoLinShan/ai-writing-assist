import { describe, it, expect, beforeEach } from "vitest"
import {
  mapState,
  resetMapState,
  stageTerrainChange,
  consumePendingChanges,
  hasMapDraftChanges,
  popEditorRedo,
  popEditorUndo,
  popUndo,
  recordEditorCommand,
  setEditorLayer,
} from "../views/mapState.js"

beforeEach(() => {
  resetMapState()
})

describe("mapState undoStack", () => {
  it("consumePendingChanges limits undoStack to 50 entries, dropping oldest", () => {
    for (let i = 0; i < 55; i += 1) {
      stageTerrainChange(i, 0, "water")
      consumePendingChanges()
    }

    expect(mapState.undoStack).toHaveLength(50)
    const firstRemaining = mapState.undoStack[0]
    expect(firstRemaining[0].hex_q).toBe(5)

    const last = popUndo()
    expect(last[0].hex_q).toBe(54)
  })

  it("consumePendingChanges does not push empty changes", () => {
    consumePendingChanges()
    expect(mapState.undoStack).toHaveLength(0)
  })
})

describe("mapState editor history", () => {
  it("keeps undo and redo isolated by editor layer", () => {
    setEditorLayer("location")
    recordEditorCommand("location", { type: "move", entityId: "loc-1" })
    setEditorLayer("terrainOverlay")
    recordEditorCommand("terrainOverlay", { type: "paint", layerId: "layer-1" })

    expect(popEditorUndo()).toEqual({ type: "paint", layerId: "layer-1" })
    expect(popEditorRedo()).toEqual({ type: "paint", layerId: "layer-1" })

    setEditorLayer("location")
    expect(popEditorUndo()).toEqual({ type: "move", entityId: "loc-1" })
  })

  it("clears redo when a new command is recorded and detects staged drafts", () => {
    setEditorLayer("marker")
    recordEditorCommand("marker", { type: "move", markerId: "marker-1" })
    popEditorUndo()
    recordEditorCommand("marker", { type: "delete", markerId: "marker-1" })

    expect(popEditorRedo()).toBeNull()
    expect(hasMapDraftChanges()).toBe(false)

    mapState.pendingLocationLayouts["loc-1"] = { q: 3, r: 4 }
    expect(hasMapDraftChanges()).toBe(true)
  })

  it("图层树与路径拥有独立历史并进入 dirty guard", () => {
    recordEditorCommand("layerTree", { type: "move", nodeId: "node-1" })
    recordEditorCommand("path", { type: "draw", pathId: "path-1" })

    expect(popEditorUndo("layerTree")).toEqual({ type: "move", nodeId: "node-1" })
    expect(popEditorUndo("path")).toEqual({ type: "draw", pathId: "path-1" })
    mapState.pendingPathChanges["path-1"] = { operation: "create" }
    expect(hasMapDraftChanges()).toBe(true)
  })
})
