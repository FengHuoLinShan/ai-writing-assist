import { describe, expect, it } from "vitest"
import {
  beginTerrainStroke,
  createTerrainSession,
  endTerrainStroke,
  paintTerrainHex,
  terrainSessionToPayload,
  undoTerrainStroke,
} from "../views/mapTerrainEditor.js"

describe("mapTerrainEditor", () => {
  it("records dragged terrain patches", () => {
    let session = createTerrainSession({ assetKey: "barrier", layerId: "layer1", regionId: "region1" })
    session = beginTerrainStroke(session)
    session = paintTerrainHex(session, 2, 2)
    session = paintTerrainHex(session, 3, 2)
    session = endTerrainStroke(session)

    expect([...session.patches.keys()]).toContain("2,2")
    expect([...session.patches.keys()]).toContain("3,2")
  })

  it("undo removes the last stroke before save payload is built", () => {
    let session = createTerrainSession({ assetKey: "abyss", layerId: "layer1", regionId: "region1" })
    session = beginTerrainStroke(session)
    session = paintTerrainHex(session, 1, 1)
    session = endTerrainStroke(session)
    session = undoTerrainStroke(session)

    const payload = terrainSessionToPayload(session)

    expect(payload.patches).toEqual([])
    expect(payload.layer.terrain_asset_key).toBe("abyss")
  })

  it("supports erasing painted cells", () => {
    let session = createTerrainSession({ assetKey: "corruption", layerId: "layer1", regionId: "region1" })
    session = beginTerrainStroke(session)
    session = paintTerrainHex(session, 4, 4)
    session = endTerrainStroke(session)
    session = { ...session, tool: "eraser" }
    session = beginTerrainStroke(session)
    session = paintTerrainHex(session, 4, 4)
    session = endTerrainStroke(session)

    expect(session.patches.has("4,4")).toBe(false)
  })
})
