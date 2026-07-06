import { describe, it, expect, beforeEach } from "vitest"
import {
  mapState,
  resetMapState,
  stageTerrainChange,
  consumePendingChanges,
  popUndo,
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
