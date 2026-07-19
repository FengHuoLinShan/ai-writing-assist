import { mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

const stubs = vi.hoisted(() => ({
  controller: {
    mount: vi.fn(async () => true),
    dispose: vi.fn(),
    canLeave: vi.fn(() => true),
    setTimelineProjection: vi.fn(),
    clearTimelineProjection: vi.fn(),
    setPresentationContext: vi.fn(() => true),
    spatialContext: vi.fn(() => ({ map: { id: "m1" }, locationAnchors: [] })),
    focusPath: vi.fn(),
    focusTimelineAnchor: vi.fn(),
    clearPathFocus: vi.fn(),
    selectInspectorObject: vi.fn(),
    timelineEntityOptions: vi.fn(() => []),
    timelinePathOptions: vi.fn(() => []),
    pathRevisionMismatch: vi.fn(() => false),
  },
}))

vi.mock("../../../vue/views/map/controllers/mapViewportController.js", () => ({
  createMapViewportController: () => stubs.controller,
}))

const MapViewportAdapter = (await import(
  "../../../vue/views/map/MapViewportAdapter.vue"
)).default

describe("MapViewportAdapter", () => {
  beforeEach(() => vi.clearAllMocks())

  it("mounts and disposes the viewport controller with the Vue host", async () => {
    const wrapper = mount(MapViewportAdapter, {
      attachTo: document.body,
      props: { context: { projectId: "p1", mapId: "m1" } },
    })
    await vi.waitFor(() => expect(stubs.controller.mount).toHaveBeenCalled())

    expect(stubs.controller.mount.mock.calls[0][0]).toBeInstanceOf(HTMLElement)
    expect(stubs.controller.mount.mock.calls[0][1]).toMatchObject({ projectId: "p1", mapId: "m1" })

    wrapper.unmount()
    expect(stubs.controller.dispose).toHaveBeenCalledTimes(1)
  })

  it("remounts on route-owned context changes and forwards timeline projection", async () => {
    const wrapper = mount(MapViewportAdapter, {
      attachTo: document.body,
      props: {
        context: { projectId: "p1", mapId: "m1", sceneId: "s1" },
        timelineProjection: { sceneIndex: 1 },
      },
    })
    await vi.waitFor(() => expect(stubs.controller.setTimelineProjection).toHaveBeenCalledWith({ sceneIndex: 1 }))

    await wrapper.setProps({
      context: { projectId: "p1", mapId: "m1", sceneId: "s2" },
      timelineProjection: null,
    })
    await vi.waitFor(() => expect(stubs.controller.mount).toHaveBeenCalledTimes(2))
    expect(stubs.controller.clearTimelineProjection).toHaveBeenCalled()

    wrapper.unmount()
  })

  it("更新展示模式时不 remount 命令式视口", async () => {
    const wrapper = mount(MapViewportAdapter, {
      attachTo: document.body,
      props: { context: { projectId: "p1", mapId: "m1", viewMode: "dashboard", lowMotion: false } },
    })
    await vi.waitFor(() => expect(stubs.controller.mount).toHaveBeenCalledTimes(1))

    await wrapper.setProps({ context: { projectId: "p1", mapId: "m1", viewMode: "lens", lowMotion: true, focusEntityId: "e1" } })

    expect(stubs.controller.mount).toHaveBeenCalledTimes(1)
    expect(stubs.controller.setPresentationContext).toHaveBeenCalledWith({ viewMode: "lens", lowMotion: true, focusEntityId: "e1" })
    expect(wrapper.vm.spatialContext()).toEqual({ map: { id: "m1" }, locationAnchors: [] })
    wrapper.unmount()
  })
})
