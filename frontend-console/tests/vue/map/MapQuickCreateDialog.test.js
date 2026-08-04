import { enableAutoUnmount, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { nextTick, reactive } from "vue"
import MapQuickCreateDialog from "../../../vue/views/map/components/MapQuickCreateDialog.vue"

enableAutoUnmount(afterEach)

function quickFixture() {
  const state = reactive({
    open: true, loading: false, saving: false,
    context: { locations: [{ id: "loc1", name: "洛阳" }], candidate_locations: [], existing_maps: [] },
    preview: { map: { grid_width: 40, grid_height: 30 }, warnings: [] },
    activeLayouts: [{ location_entity_id: "loc1", center_hex_q: 10, center_hex_r: 8, occupy_radius: 1, locked: false }],
    selectedIds: new Set(["loc1"]), history: [], redo: [], target: "world", parentEntityId: null,
    parentMapId: null, replaceMapId: null, mapName: "快速地图", mapType: "world", gridWidth: 40,
    gridHeight: 30, baseTemplate: "blank", includeCandidates: false,
  })
  return {
    state, close: vi.fn(), submit: vi.fn(), setTarget: vi.fn(), setReplacement: vi.fn(), changeSetting: vi.fn(),
    setIncludeCandidates: vi.fn(), addExtraLocation: vi.fn(), setAllSelected: vi.fn(), toggleSelection: vi.fn(),
    resizeLocation: vi.fn(), moveLocation: vi.fn(), toggleLock: vi.fn(), undo: vi.fn(), redo: vi.fn(),
    pushHistory: vi.fn(), moveLocationTo: vi.fn(), isCandidate: () => false, locationName: () => "洛阳",
  }
}

describe("MapQuickCreateDialog", () => {
  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ setTransform: vi.fn(), clearRect: vi.fn(), fillRect: vi.fn(), beginPath: vi.fn(), arc: vi.fn(), fill: vi.fn(), stroke: vi.fn(), fillText: vi.fn(), set fillStyle(_) {}, set strokeStyle(_) {}, set lineWidth(_) {}, set font(_) {}, set textAlign(_) {} })
  })

  it("associates quick-create fields and row controls with author-facing accessible names", async () => {
    const quick = quickFixture()
    quick.state.target = "drilldown"
    quick.state.parentEntityId = "loc1"
    quick.state.parentMapId = "map1"
    quick.state.context.locations.push({ id: "loc2", name: "长安" })
    quick.state.context.existing_maps = [{ id: "map1", name: "九州", grid_width: 40, grid_height: 30 }]
    const wrapper = mount(MapQuickCreateDialog, { props: { quick }, attachTo: document.body, global: { stubs: { Teleport: true } } })

    const fieldLabels = [
      ["map-quick-target", "创建目标"], ["map-quick-parent-entity", "父地点"], ["map-quick-parent-map", "父地图"],
      ["map-quick-replace", "创建方式"], ["map-quick-name", "地图名称"], ["map-quick-type", "地图类型"],
      ["map-quick-template", "底图模板"], ["map-quick-extra-search", "添加其他已采用地点"],
    ]
    for (const [id, label] of fieldLabels) {
      expect(wrapper.get(`label[for="${id}"]`).text()).toBe(label)
    }
    expect(wrapper.get("#map-quick-width").attributes("aria-label")).toBe("地图网格宽度")
    expect(wrapper.get("#map-quick-height").attributes("aria-label")).toBe("地图网格高度")
    expect(wrapper.get("#map-quick-extra").attributes("aria-label")).toBe("选择其他已采用地点")
    expect(wrapper.get("#map-quick-select-all").attributes("aria-label")).toBe("全选可放置地点")
    expect(wrapper.get('[data-action="map-quick-select"]').attributes("aria-label")).toBe("选择地点 洛阳")
    expect(wrapper.get("#map-quick-canvas").attributes("aria-label")).toBe("地点布局画布")

    const controls = wrapper.findAll(".map-quick-row-control")
    expect(controls.map((control) => control.attributes("aria-label"))).toEqual([
      "缩小地点 洛阳 的半径", "扩大地点 洛阳 的半径", "向左移动地点 洛阳", "向右移动地点 洛阳",
      "向上移动地点 洛阳", "向下移动地点 洛阳", "锁定地点 洛阳",
    ])

    quick.state.activeLayouts[0].locked = true
    await nextTick()
    expect(wrapper.get('[data-action="map-quick-lock"]').attributes("aria-label")).toBe("解锁地点 洛阳")
    expect(wrapper.get('[data-action="map-quick-lock"]').attributes("disabled")).toBeUndefined()
    expect(wrapper.findAll('[data-action="map-quick-radius"]').every((control) => control.attributes("disabled") !== undefined)).toBe(true)
    expect(wrapper.findAll('[data-action="map-quick-move"]').every((control) => control.attributes("disabled") !== undefined)).toBe(true)
  })

  it("connects Vue controls to layout resize, move, lock and undo/redo commands", async () => {
    const quick = quickFixture()
    const wrapper = mount(MapQuickCreateDialog, { props: { quick }, attachTo: document.body, global: { stubs: { Teleport: true } } })
    const rowControls = wrapper.findAll(".map-quick-row-control")
    expect(rowControls).toHaveLength(7)
    expect(rowControls.every((control) => ["map-quick-radius", "map-quick-move", "map-quick-lock"].includes(control.attributes("data-action")))).toBe(true)
    await wrapper.get('[aria-label="缩小地点 洛阳 的半径"]').trigger("click")
    await wrapper.get('[aria-label="扩大地点 洛阳 的半径"]').trigger("click")
    for (const label of ["向左移动地点 洛阳", "向右移动地点 洛阳", "向上移动地点 洛阳", "向下移动地点 洛阳"]) {
      await wrapper.get(`[aria-label="${label}"]`).trigger("click")
    }
    await wrapper.get('[aria-label="锁定地点 洛阳"]').trigger("click")
    const canvas = wrapper.find("#map-quick-canvas")
    await canvas.trigger("pointerdown", { clientX: 248, clientY: 127, pointerId: 1 })
    await canvas.trigger("pointermove", { clientX: 300, clientY: 160, pointerId: 1 })
    await canvas.trigger("pointerup", { clientX: 300, clientY: 160, pointerId: 1 })
    quick.state.history.push([])
    quick.state.redo.push([])
    await nextTick()
    await wrapper.find("#map-quick-undo").trigger("click")
    await wrapper.find("#map-quick-redo").trigger("click")
    expect(quick.resizeLocation.mock.calls).toEqual([["loc1", "decrease"], ["loc1", "increase"]])
    expect(quick.moveLocation.mock.calls).toEqual([["loc1", -1, 0], ["loc1", 1, 0], ["loc1", 0, -1], ["loc1", 0, 1]])
    expect(quick.toggleLock).toHaveBeenCalledWith("loc1")
    expect(quick.pushHistory).toHaveBeenCalled()
    expect(quick.moveLocationTo).toHaveBeenCalledWith("loc1", expect.any(Number), expect.any(Number))
    expect(quick.undo).toHaveBeenCalled()
    expect(quick.redo).toHaveBeenCalled()
    wrapper.unmount()
  })
})
