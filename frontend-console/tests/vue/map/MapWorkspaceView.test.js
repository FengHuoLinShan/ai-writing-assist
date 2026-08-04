import { mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const viewportSpies = vi.hoisted(() => ({
  clearPathFocus: vi.fn(() => true),
  remount: vi.fn(async () => true),
}))

vi.mock("../../../vue/views/map/MapViewportAdapter.vue", async () => {
  const { defineComponent, h } = await import("vue")
  return { default: defineComponent({
    name: "MapViewportAdapter",
    props: { context: { type: Object, default: () => ({}) } },
    setup(_, { expose }) {
      expose({ canLeave: () => true, clearPathFocus: viewportSpies.clearPathFocus, remount: viewportSpies.remount, timelineEntityOptions: () => [], timelinePathOptions: () => [{ id: "path1", name: "北境道" }] })
      return () => h("div", { class: "map-root", "data-test": "viewport" })
    },
  }) }
})

const MapWorkspaceView = (await import("../../../vue/views/map/MapWorkspaceView.vue")).default

function worldApi() {
  return {
    getMapDashboard: vi.fn(async () => ({
      title: "<img src=x onerror=alert(1)>",
      first_visual_layer: { main_crisis: "危机", main_characters: [], top_risks: [] },
      dynamic_queue: [{ item_id: "o1", id: "o1", item_kind: "observation", title: "<script>alert(1)</script>", review_state: "candidate", updated_at: "rev-1", eligibility: { can_confirm: true }, source_summary: "正文", normalized_value: { schema_version: 1, type: "route_state", path_id: "path1", state: "open" } }],
      batch_groups: [],
      inspector: null,
    })),
    getMapPlayback: vi.fn(async () => ({ events: [], tracks: [] })),
    getMapTimeline: vi.fn(async () => ({ scenes: [], deltas: [], candidates: [], conflicts: [] })),
    listMapObservations: vi.fn(async () => ({ items: [] })),
    confirmMapObservation: vi.fn(async () => ({})),
    listMaps: vi.fn(async () => ({ items: [] })),
    listEntities: vi.fn(async () => ({ items: [] })),
    getMapQuickCreateContext: vi.fn(async () => ({ locations: [{ id: "l1", name: "北港" }], candidate_locations: [], existing_maps: [] })),
    previewQuickCreateMap: vi.fn(async () => ({ map: { name: "快速地图", grid_width: 40, grid_height: 30, map_type: "world" }, location_layouts: [{ location_entity_id: "l1", center_hex_q: 2, center_hex_r: 3, occupy_radius: 1 }], warnings: [] })),
    confirmQuickCreateMap: vi.fn(async () => ({ map: { id: "m2", name: "快速地图" } })),
    listMapVisualRevisions: vi.fn(async () => ({ items: [] })),
    restoreMapVisualRevision: vi.fn(async () => ({ editor_revision: 3 })),
  }
}

describe("MapWorkspaceView", () => {
  let api
  let state
  let router
  let showModalHtml
  beforeEach(() => {
    document.body.replaceChildren()
    localStorage.clear()
    resetBridgeOverrides()
    state = { currentProjectId: "p1", currentView: "map" }
    api = { world: worldApi() }
    router = { navigate: vi.fn(), replace: vi.fn(), getCurrentQuery: () => new URLSearchParams() }
    showModalHtml = vi.fn()
    viewportSpies.clearPathFocus.mockClear()
    viewportSpies.remount.mockClear()
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ setTransform: vi.fn(), clearRect: vi.fn(), fillRect: vi.fn(), beginPath: vi.fn(), arc: vi.fn(), fill: vi.fn(), stroke: vi.fn(), fillText: vi.fn(), set fillStyle(_) {}, set strokeStyle(_) {}, set lineWidth(_) {}, set font(_) {}, set textAlign(_) {} })
    setBridgeOverrides({ api, state, confirmAction: (_message, onConfirm) => onConfirm(), toast: vi.fn(), showModalHtml, closeModal: vi.fn(), esc: (value) => String(value ?? "").replaceAll("<", "&lt;"), router })
  })

  it.each([
    { maps: [], recent: null, label: "查找可用地图" },
    { maps: [{ id: "m1", name: "九州" }], recent: null, label: "打开可用地图" },
    { maps: [], recent: { mapId: "m1", name: "九州" }, label: "打开最近地图" },
  ])("uses the truthful recent-map action label for the overview state", ({ maps, recent, label }) => {
    if (recent) localStorage.setItem("novel_map_recent:p1", JSON.stringify(recent))

    const wrapper = mount(MapWorkspaceView, {
      attachTo: document.body,
      props: { projectId: "p1", route: { mode: "overview" }, maps, locations: [], archivedMaps: [], inbox: {} },
    })

    expect(wrapper.get('[data-action="map-open-recent"]').text()).toBe(label)
    wrapper.unmount()
  })

  it("refreshes the overview card and action label when a stale recent map is cleared", async () => {
    localStorage.setItem("novel_map_recent:p1", JSON.stringify({ mapId: "stale-map", name: "已删除地图" }))
    api.world.getMap = vi.fn(async () => { throw new Error("not found") })
    api.world.getMapOpenTarget = vi.fn(async () => ({ map_id: null }))
    const wrapper = mount(MapWorkspaceView, {
      attachTo: document.body,
      props: { projectId: "p1", route: { mode: "overview" }, maps: [], locations: [], archivedMaps: [], inbox: {} },
    })

    expect(wrapper.get('[data-action="map-open-recent"]').text()).toBe("打开最近地图")
    expect(wrapper.text()).toContain("已删除地图")
    await wrapper.get('[data-action="map-open-recent"]').trigger("click")

    await vi.waitFor(() => {
      expect(localStorage.getItem("novel_map_recent:p1")).toBeNull()
      expect(wrapper.get('[data-action="map-open-recent"]').text()).toBe("查找可用地图")
      expect(wrapper.text()).toContain("暂无最近地图")
    })
    wrapper.unmount()
  })

  it("opens the Vue quick-create layout editor from the route toolbar", async () => {
    const wrapper = mount(MapWorkspaceView, { attachTo: document.body, props: { projectId: "p1", route: { mode: "overview" }, maps: [], locations: [], archivedMaps: [], inbox: {} } })
    await wrapper.find('[data-action="map-quick-create"]').trigger("click")
    await vi.waitFor(() => expect(document.body.querySelector("#map-quick-canvas")).not.toBeNull())
    expect(api.world.previewQuickCreateMap).toHaveBeenCalledWith(expect.objectContaining({ include_markers: false }), "p1")
    wrapper.unmount()
  })

  it("routes dynamic-object modification into the Vue typed editor", async () => {
    const wrapper = mount(MapWorkspaceView, { attachTo: document.body, props: { projectId: "p1", route: { mapId: "m1", mode: "dashboard" }, maps: [{ id: "m1", name: "九州" }], inbox: {} } })
    await vi.waitFor(() => expect(wrapper.find(".map-dynamic-item").exists()).toBe(true))
    const title = wrapper.get('[data-action="map-open-dynamic-item"]')
    expect(title.element.tagName).toBe("BUTTON")
    expect(title.attributes("type")).toBe("button")
    showModalHtml.mockClear()
    await title.trigger("click")
    expect(showModalHtml).toHaveBeenCalledTimes(1)
    const buttons = showModalHtml.mock.calls.at(-1)[2]
    buttons.find((button) => button.text === "修改").handler()
    await vi.waitFor(() => expect(document.body.querySelector("#map-typed-route-path")).not.toBeNull())
    expect(document.body.querySelector("#map-object-edit-value-json")).toBeNull()
    wrapper.unmount()
  })

  it("restores a committed visual revision through the existing map modal style", async () => {
    api.world.listMapVisualRevisions.mockResolvedValue({ items: [
      { revision_number: 2, operation: "editor_apply", forward_changes: [{}], created_at: "2026-07-22T10:00:00Z" },
      { revision_number: 1, operation: "legacy_edit", forward_changes: [{}, {}], created_at: "2026-07-22T09:00:00Z" },
      { revision_number: 0, operation: "baseline", forward_changes: [], created_at: "2026-07-22T08:00:00Z" },
    ] })
    const wrapper = mount(MapWorkspaceView, {
      attachTo: document.body,
      props: { projectId: "p1", route: { mapId: "m1", mode: "dashboard" }, maps: [{ id: "m1", name: "九州", editor_revision: 2 }], locations: [], archivedMaps: [], inbox: {} },
    })

    await wrapper.get('[data-action="map-visual-history"]').trigger("click")
    await vi.waitFor(() => expect(showModalHtml).toHaveBeenCalled())
    const [title, body, buttons] = showModalHtml.mock.calls.at(-1)
    expect(title).toBe("地图编辑历史")
    expect(body).toContain("版本 1")
    document.body.insertAdjacentHTML("beforeend", body)
    await buttons.find((button) => button.text === "恢复所选版本").handler()

    expect(api.world.restoreMapVisualRevision).toHaveBeenCalledWith("m1", 1, 2, "p1")
    expect(viewportSpies.remount).toHaveBeenCalled()
    wrapper.unmount()
  })

  it("owns overview, inbox and search DOM without injecting dynamic HTML", async () => {
    const wrapper = mount(MapWorkspaceView, {
      attachTo: document.body,
      props: {
        projectId: "p1", route: { mode: "overview" },
        maps: [{ id: "m1", name: "<script>alert(1)</script>" }],
        locations: [{ id: "l1", name: "北港" }], archivedMaps: [],
        inbox: { items: [{ id: "i1", target_name: "<img src=x>", source: "manual", updated_at: "r1", eligibility: { can_confirm: false } }], total: 1, filters: {} },
      },
    })
    expect(wrapper.get('[aria-label="搜索地图或地点"]').attributes("placeholder")).toBe("搜索地图或地点")
    await wrapper.find(".map-overview-search").setValue("script")
    expect(wrapper.find(".map-project-inbox").exists()).toBe(true)
    expect(wrapper.find("#map-search-results").text()).toContain("<script>alert(1)</script>")
    expect(wrapper.find("script").exists()).toBe(false)
    expect(wrapper.find("img").exists()).toBe(false)
    wrapper.unmount()
  })

  it("exposes the selected map view mode and updates it through the existing control", async () => {
    const wrapper = mount(MapWorkspaceView, {
      attachTo: document.body,
      props: { projectId: "p1", route: { mapId: "m1", mode: "live" }, maps: [{ id: "m1", name: "九州" }], locations: [], archivedMaps: [], inbox: {} },
    })
    const viewModes = wrapper.get('[role="group"][aria-label="地图视图"]')
    const dashboard = viewModes.get("button:first-child")
    const live = viewModes.get("button:nth-child(2)")
    const lens = viewModes.get("button:nth-child(3)")

    expect(dashboard.attributes("aria-pressed")).toBe("false")
    expect(live.attributes("aria-pressed")).toBe("true")
    expect(lens.attributes("aria-pressed")).toBe("false")
    await dashboard.trigger("click")
    expect(dashboard.attributes("aria-pressed")).toBe("true")
    expect(live.attributes("aria-pressed")).toBe("false")
    expect(lens.attributes("aria-pressed")).toBe("false")
    wrapper.unmount()
  })

  it("renders the Vue-owned active workspace and preserves observation CAS", async () => {
    api.world.listMapObservations.mockResolvedValue({ items: [{
      id: "o1",
      item_id: "o1",
      item_kind: "observation",
      title: "<script>alert(1)</script>",
      review_state: "candidate",
      updated_at: "rev-2",
      eligibility: { can_confirm: true },
    }] })
    const wrapper = mount(MapWorkspaceView, {
      attachTo: document.body,
      props: { projectId: "p1", route: { mapId: "m1", mode: "dashboard" }, maps: [{ id: "m1", name: "九州" }], locations: [], archivedMaps: [], inbox: { items: [], total: 0, filters: {} } },
    })
    await vi.waitFor(() => expect(wrapper.find(".map-dynamic-title").text()).toContain("<script>alert(1)</script>"))
    expect(wrapper.find("[data-test='viewport']").exists()).toBe(true)
    expect(wrapper.find("script").exists()).toBe(false)

    showModalHtml.mockClear()
    await wrapper.find(".map-dynamic-item .btn-primary").trigger("click")
    await vi.waitFor(() => expect(api.world.confirmMapObservation).toHaveBeenCalledWith("m1", "o1", "p1", "rev-2"))
    expect(showModalHtml).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("不会在非播放状态的编辑通知中清除新建线路选中态", async () => {
    const wrapper = mount(MapWorkspaceView, {
      attachTo: document.body,
      props: { projectId: "p1", route: { mapId: "m1", mode: "live" }, maps: [{ id: "m1", name: "九州" }], locations: [], archivedMaps: [], inbox: {} },
    })
    const viewport = wrapper.findComponent({ name: "MapViewportAdapter" })
    await vi.waitFor(() => expect(viewport.props("context")?.onEditingChange).toEqual(expect.any(Function)))

    viewport.props("context").onEditingChange({ editing: true, dirty: true, editorLayer: "path" })

    expect(viewportSpies.clearPathFocus).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("drops late dynamic responses after project ownership changes", async () => {
    let resolveDashboard
    api.world.getMapDashboard.mockImplementationOnce(() => new Promise((resolve) => { resolveDashboard = resolve }))
    const wrapper = mount(MapWorkspaceView, { attachTo: document.body, props: { projectId: "p1", route: { mapId: "m1", mode: "dashboard" }, maps: [{ id: "m1", name: "九州" }], inbox: {} } })
    state.currentProjectId = "p2"
    resolveDashboard({ title: "迟到项目", dynamic_queue: [], first_visual_layer: {} })
    await Promise.resolve()
    await Promise.resolve()
    expect(wrapper.text()).not.toContain("迟到项目")
    wrapper.unmount()
  })

  it("does not start dynamic requests from the old island after map query navigation unmounts it", async () => {
    let resolveNavigation
    router.navigate.mockImplementationOnce(() => new Promise((resolve) => { resolveNavigation = resolve }))
    const wrapper = mount(MapWorkspaceView, {
      attachTo: document.body,
      props: { projectId: "p1", route: { mode: "overview" }, maps: [{ id: "m1", name: "九州" }], locations: [], archivedMaps: [], inbox: {} },
    })

    await wrapper.get('[data-action="map-open"]').trigger("click")
    await vi.waitFor(() => expect(resolveNavigation).toBeTypeOf("function"))
    wrapper.unmount()
    resolveNavigation(true)
    await Promise.resolve()
    await Promise.resolve()

    expect(api.world.getMapDashboard).not.toHaveBeenCalled()
    expect(api.world.getMapPlayback).not.toHaveBeenCalled()
    expect(api.world.getMapTimeline).not.toHaveBeenCalled()
    expect(api.world.listMapObservations).not.toHaveBeenCalled()
  })

  it("does not reload lens data from the old island after query-only navigation", async () => {
    const wrapper = mount(MapWorkspaceView, {
      attachTo: document.body,
      props: { projectId: "p1", route: { mapId: "m1", mode: "dashboard" }, maps: [{ id: "m1", name: "九州" }], locations: [], archivedMaps: [], inbox: {} },
    })
    await vi.waitFor(() => expect(api.world.getMapDashboard).toHaveBeenCalledTimes(1))
    const viewport = wrapper.findComponent({ name: "MapViewportAdapter" })
    let resolveNavigation
    router.replace.mockImplementationOnce(() => new Promise((resolve) => { resolveNavigation = resolve }))
    for (const method of ["getMapDashboard", "getMapPlayback", "getMapTimeline", "listMapObservations"]) {
      api.world[method].mockClear()
    }

    const pending = viewport.props("context").onFocusEntity("entity-1")
    await vi.waitFor(() => expect(resolveNavigation).toBeTypeOf("function"))
    wrapper.unmount()
    resolveNavigation(true)
    await pending

    expect(api.world.getMapDashboard).not.toHaveBeenCalled()
    expect(api.world.getMapPlayback).not.toHaveBeenCalled()
    expect(api.world.getMapTimeline).not.toHaveBeenCalled()
    expect(api.world.listMapObservations).not.toHaveBeenCalled()
  })
})
