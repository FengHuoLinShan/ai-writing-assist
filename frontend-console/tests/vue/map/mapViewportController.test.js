import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("../../../views/mapView.js", () => ({
  default: {},
}))

const { createMapViewportController } = await import(
  "../../../vue/views/map/controllers/mapViewportController.js"
)

function renderer(overrides = {}) {
  return {
    mount: vi.fn(async () => true),
    unmount: vi.fn(),
    canLeave: vi.fn(() => true),
    setTimelineProjection: vi.fn(),
    clearTimelineProjection: vi.fn(),
    setPresentationContext: vi.fn(() => true),
    focusPath: vi.fn(() => true),
    focusTimelineAnchor: vi.fn(() => true),
    clearPathFocus: vi.fn(() => true),
    selectInspectorObject: vi.fn(() => true),
    timelineEntityOptions: vi.fn(() => [{ id: "e1" }]),
    timelinePathOptions: vi.fn(() => [{ id: "path1" }]),
    pathRevisionMismatch: vi.fn(() => false),
    _state: { map: { id: "m1", name: "九州", grid_width: 20, grid_height: 12 } },
    _effectiveLocationLayouts: vi.fn(() => [{ location_entity_id: "l1", center_hex_q: 7, center_hex_r: 4 }]),
    _locationName: vi.fn(() => "北港"),
    ...overrides,
  }
}

describe("mapViewportController", () => {
  let state

  beforeEach(() => {
    document.body.replaceChildren()
    state = { currentProjectId: "p1" }
  })

  it("mounts the imperative engine only inside the Vue-owned host", async () => {
    const engine = renderer()
    const host = document.createElement("div")
    document.body.append(host)
    const controller = createMapViewportController({ renderer: engine, getState: () => state })

    await expect(controller.mount(host, { projectId: "p1", mapId: "m1" })).resolves.toBe(true)

    expect(host.id).toBe("map-root")
    expect(engine.mount).toHaveBeenCalledWith("map-root", expect.objectContaining({
      projectId: "p1",
      mapId: "m1",
    }))
    expect(controller.mounted).toBe(true)
  })

  it("rejects a late mount after the project owner changes", async () => {
    let resolveMount
    const engine = renderer({
      mount: vi.fn(() => new Promise((resolve) => { resolveMount = resolve })),
    })
    const host = document.createElement("div")
    document.body.append(host)
    const controller = createMapViewportController({ renderer: engine, getState: () => state })

    const pending = controller.mount(host, { projectId: "p1", mapId: "m1" })
    state.currentProjectId = "p2"
    resolveMount(true)

    await expect(pending).resolves.toBe(false)
    expect(engine.unmount).toHaveBeenCalledTimes(2)
    expect(controller.mounted).toBe(false)
  })

  it("does not let an earlier mount completion unmount the current viewport", async () => {
    const resolvers = []
    const engine = renderer({
      mount: vi.fn(() => new Promise((resolve) => { resolvers.push(resolve) })),
    })
    const host = document.createElement("div")
    document.body.append(host)
    const controller = createMapViewportController({ renderer: engine, getState: () => state })

    const firstMount = controller.mount(host, { projectId: "p1", mapId: "m1" })
    const secondMount = controller.mount(host, { projectId: "p1", mapId: "m2" })

    resolvers[1](true)
    await expect(secondMount).resolves.toBe(true)
    const unmountsAfterCurrentMount = engine.unmount.mock.calls.length

    resolvers[0](true)
    await expect(firstMount).resolves.toBe(false)

    expect(engine.unmount).toHaveBeenCalledTimes(unmountsAfterCurrentMount)
    expect(controller.mounted).toBe(true)
    expect(controller.projectId).toBe("p1")
  })

  it("invalidates an in-flight mount on dispose", async () => {
    let resolveMount
    const engine = renderer({
      mount: vi.fn(() => new Promise((resolve) => { resolveMount = resolve })),
    })
    const host = document.createElement("div")
    document.body.append(host)
    const controller = createMapViewportController({ renderer: engine, getState: () => state })

    const pending = controller.mount(host, { projectId: "p1", mapId: "m1" })
    controller.dispose()
    resolveMount(true)

    await expect(pending).resolves.toBe(false)
    expect(controller.mounted).toBe(false)
  })

  it("replays the latest presentation context after an in-flight mount", async () => {
    let resolveMount
    const engine = renderer({
      mount: vi.fn(() => new Promise((resolve) => { resolveMount = resolve })),
    })
    const host = document.createElement("div")
    document.body.append(host)
    const controller = createMapViewportController({ renderer: engine, getState: () => state })

    const pending = controller.mount(host, { projectId: "p1", mapId: "m1" })
    expect(controller.setPresentationContext({ viewMode: "lens" })).toBe(true)
    expect(controller.setPresentationContext({ lowMotion: true, focusEntityId: "e1" })).toBe(true)
    expect(engine.setPresentationContext).not.toHaveBeenCalled()

    resolveMount(true)
    await expect(pending).resolves.toBe(true)
    expect(engine.setPresentationContext).toHaveBeenCalledTimes(1)
    expect(engine.setPresentationContext).toHaveBeenCalledWith({
      viewMode: "lens",
      lowMotion: true,
      focusEntityId: "e1",
    })
  })

  it("旧路由 controller 延迟 dispose 不会卸载新路由已接管的单例视口", async () => {
    const engine = renderer()
    const firstHost = document.createElement("div")
    const secondHost = document.createElement("div")
    document.body.append(firstHost, secondHost)
    const first = createMapViewportController({ renderer: engine, getState: () => state })
    const second = createMapViewportController({ renderer: engine, getState: () => state })

    await first.mount(firstHost, { projectId: "p1", mapId: "m1" })
    await second.mount(secondHost, { projectId: "p1", mapId: "m1" })
    const unmountsAfterTakeover = engine.unmount.mock.calls.length

    first.dispose()
    expect(engine.unmount).toHaveBeenCalledTimes(unmountsAfterTakeover)

    second.dispose()
    expect(engine.unmount).toHaveBeenCalledTimes(unmountsAfterTakeover + 1)
  })

  it("forwards guards and projections only while mounted", async () => {
    const engine = renderer({ canLeave: vi.fn(() => false) })
    const host = document.createElement("div")
    document.body.append(host)
    const controller = createMapViewportController({ renderer: engine, getState: () => state })

    expect(controller.setTimelineProjection({ scene: 1 })).toBe(false)
    expect(controller.canLeave()).toBe(false)

    await controller.mount(host, { projectId: "p1", mapId: "m1" })
    expect(controller.setTimelineProjection({ scene: 2 })).toBe(true)
    expect(controller.clearTimelineProjection()).toBe(true)
    expect(controller.setPresentationContext({ viewMode: "lens" })).toBe(true)
    expect(engine.setTimelineProjection).toHaveBeenCalledWith({ scene: 2 })
    expect(engine.clearTimelineProjection).toHaveBeenCalledTimes(1)
    expect(controller.focusPath("path1")).toBe(true)
    expect(controller.focusTimelineAnchor({ hex_q: 1, hex_r: 2 })).toBe(true)
    expect(controller.timelineEntityOptions()).toEqual([{ id: "e1" }])
    expect(controller.timelinePathOptions()).toEqual([{ id: "path1" }])
    expect(controller.spatialContext()).toEqual({
      map: { id: "m1", name: "九州", grid_width: 20, grid_height: 12 },
      locationAnchors: [{ location_entity_id: "l1", name: "北港", q: 7, r: 4 }],
    })
  })
})
