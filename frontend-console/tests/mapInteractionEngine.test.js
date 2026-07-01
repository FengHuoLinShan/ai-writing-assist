import { describe, expect, it } from "vitest"
import {
  beginDrag,
  commitDrag,
  createMapInteractionSession,
  pushTerrainUndo,
  queryMapObjectsAt,
  undoLayout,
  undoTerrain,
  dragToHex,
} from "../views/mapInteractionEngine.js"

describe("mapInteractionEngine", () => {
  it("drags a location to a snapped hex and locks it", () => {
    const layouts = [{ location_entity_id: "loc1", center_hex_q: 1, center_hex_r: 1, locked: false }]
    let session = createMapInteractionSession()
    session = beginDrag(session, layouts[0])
    session = dragToHex(session, 4.4, 5.6)
    const committed = commitDrag(session, layouts)

    expect(committed.layouts[0]).toMatchObject({
      center_hex_q: 4,
      center_hex_r: 6,
      locked: true,
      layout_source: "user_drag",
    })
  })

  it("keeps layout and terrain undo stacks independent", () => {
    const originalLayouts = [{ location_entity_id: "loc1", center_hex_q: 1, center_hex_r: 1 }]
    const movedLayouts = [{ location_entity_id: "loc1", center_hex_q: 2, center_hex_r: 2 }]
    let session = createMapInteractionSession()
    session = { ...session, layoutUndo: [originalLayouts] }
    session = pushTerrainUndo(session, [{ hex_q: 1, hex_r: 1 }])

    const layoutUndo = undoLayout(session, movedLayouts)
    const terrainUndo = undoTerrain(layoutUndo.session, [{ hex_q: 2, hex_r: 2 }])

    expect(layoutUndo.layouts).toEqual(originalLayouts)
    expect(terrainUndo.terrain).toEqual([{ hex_q: 1, hex_r: 1 }])
  })

  it("returns hit objects sorted by z-index and priority", () => {
    const hits = queryMapObjectsAt({ x: 10, y: 10 }, {
      layers: [
        { type: "terrain_patch", zIndex: 10, objects: [{ id: "terrain", hitArea: { x: 0, y: 0, width: 20, height: 20 } }] },
        { type: "location", zIndex: 50, objects: [{ id: "location", priority: 3, hitArea: { x: 0, y: 0, width: 20, height: 20 } }] },
        { type: "marker", zIndex: 50, objects: [{ id: "marker", priority: 8, hitArea: { x: 0, y: 0, width: 20, height: 20 } }] },
      ],
    })

    expect(hits.map((hit) => hit.id)).toEqual(["marker", "location", "terrain"])
  })
})
