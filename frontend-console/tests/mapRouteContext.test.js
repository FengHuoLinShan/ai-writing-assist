import { describe, it, expect } from "vitest"
import { buildMapUrl, parseMapRouteContext } from "../views/mapRouteContext.js"

describe("mapRouteContext", () => {
  it("builds a map deep link with query params", () => {
    const url = buildMapUrl({
      projectId: "p1",
      mapId: "m1",
      sceneId: "s1",
      focusEntityId: "f1",
      mode: "map",
    })

    expect(url).toBe(
      "#workbench/p1/map?map_id=m1&scene_id=s1&focus_entity_id=f1&mode=map"
    )
  })

  it("parses map route context from a hash", () => {
    const context = parseMapRouteContext(
      "#workbench/p1/map?map_id=m1&scene_id=s1&focus_entity_id=f1&mode=map"
    )

    expect(context).toEqual({
      projectId: "p1",
      mapId: "m1",
      sceneId: "s1",
      focusEntityId: "f1",
      mode: "map",
    })
  })

  it("defaults to overview mode when mode is absent", () => {
    const context = parseMapRouteContext("#workbench/p1/map")

    expect(context.mode).toBe("overview")
    expect(context.projectId).toBe("p1")
  })
})
