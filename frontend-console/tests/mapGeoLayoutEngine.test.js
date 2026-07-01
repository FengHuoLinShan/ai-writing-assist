import { describe, expect, it } from "vitest"
import { applyLayoutResize, buildGeoLayout } from "../views/mapGeoLayoutEngine.js"

describe("mapGeoLayoutEngine", () => {
  it("keeps locked locations fixed", () => {
    const result = buildGeoLayout({
      nodes: [{ id: "loc1", name: "洛阳" }, { id: "loc2", name: "长安" }],
      lockedLayouts: [{
        location_entity_id: "loc1",
        center_hex_q: 7,
        center_hex_r: 8,
        occupy_radius: 2,
        locked: true,
      }],
      grid: { width: 20, height: 20 },
    })

    const locked = result.layouts.find((layout) => layout.location_entity_id === "loc1")
    expect(locked.center_hex_q).toBe(7)
    expect(locked.center_hex_r).toBe(8)
    expect(locked.occupy_radius).toBe(2)
  })

  it("displaces unlocked locations when radius grows", () => {
    const result = buildGeoLayout({
      nodes: [
        { id: "a", name: "A" },
        { id: "b", name: "B" },
        { id: "c", name: "C" },
      ],
      lockedLayouts: [{
        location_entity_id: "a",
        center_hex_q: 5,
        center_hex_r: 5,
        occupy_radius: 3,
        locked: true,
      }],
      grid: { width: 10, height: 10 },
    })

    const centers = result.layouts.map((layout) => `${layout.center_hex_q},${layout.center_hex_r}`)
    expect(new Set(centers).size).toBe(result.layouts.length)
    expect(result.conflicts).toEqual([])
  })

  it("reports expansion when space is insufficient", () => {
    const result = buildGeoLayout({
      nodes: Array.from({ length: 9 }, (_, index) => ({ id: `loc${index}`, name: `地点${index}`, occupy_radius: 3 })),
      grid: { width: 4, height: 4 },
    })

    expect(result.expandedBounds).toEqual({ width: 12, height: 10 })
    expect(result.conflicts.some((conflict) => conflict.type === "layout_conflict")).toBe(true)
  })

  it("ignores scene trajectory inputs because geography is authoritative", () => {
    const base = buildGeoLayout({
      nodes: [{ id: "luoyang", name: "洛阳" }, { id: "changan", name: "长安" }],
      relations: [],
      grid: { width: 20, height: 20 },
    })
    const withTrajectory = buildGeoLayout({
      nodes: [{ id: "luoyang", name: "洛阳" }, { id: "changan", name: "长安" }],
      relations: [{ source_id: "char1", target_id: "luoyang", relation_type: "scene_next" }],
      grid: { width: 20, height: 20 },
    })

    expect(withTrajectory.layouts).toEqual(base.layouts)
  })

  it("resizes locations through allowed radius steps", () => {
    const layouts = [{ location_entity_id: "loc1", occupy_radius: 1 }]

    expect(applyLayoutResize(layouts, "loc1", "increase")[0].occupy_radius).toBe(2)
    expect(applyLayoutResize([{ location_entity_id: "loc1", occupy_radius: 2 }], "loc1", "decrease")[0].occupy_radius).toBe(1)
  })
})
