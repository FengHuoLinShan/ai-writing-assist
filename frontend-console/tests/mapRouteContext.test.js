import { describe, it, expect } from "vitest"
import { buildMapUrl, parseMapRouteContext } from "../views/mapRouteContext.js"

describe("mapRouteContext", () => {
  it("builds a map deep link with query params", () => {
    const url = buildMapUrl({
      projectId: "p1",
      mapId: "m1",
      sceneId: "s1",
      focusEntityId: "f1",
      focusHexQ: null,
      focusHexR: null,
      mode: "map",
    })

    expect(url).toBe(
      "#workbench/p1/map?map_id=m1&scene_id=s1&focus_entity_id=f1&mode=map"
    )
  })

  it("round-trips representative focus coordinates", () => {
    const url = buildMapUrl({
      projectId: "p1",
      mapId: "m1",
      focusEntityId: "f1",
      focusHexQ: 12,
      focusHexR: 9,
      mode: "live",
    })

    expect(parseMapRouteContext(url)).toMatchObject({ focusHexQ: 12, focusHexR: 9 })
  })

  it("传递线路和图层焦点", () => {
    const url = buildMapUrl({
      projectId: "p1",
      mapId: "m1",
      focusPathId: "path-1",
      focusLayerNodeId: "layer-1",
      mode: "live",
    })
    expect(url).toContain("focus_path_id=path-1")
    expect(url).toContain("focus_layer_node_id=layer-1")
    expect(parseMapRouteContext(url)).toMatchObject({
      focusPathId: "path-1",
      focusLayerNodeId: "layer-1",
    })
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
      focusHexQ: null,
      focusHexR: null,
      focusPathId: null,
      focusLayerNodeId: null,
      mode: "map",
    })
  })

  it("defaults to overview mode when mode is absent", () => {
    const context = parseMapRouteContext("#workbench/p1/map")

    expect(context.mode).toBe("overview")
    expect(context.projectId).toBe("p1")
  })
})
