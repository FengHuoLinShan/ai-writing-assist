import { mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { nextTick, reactive } from "vue"
import MapQuickCreateDialog from "../../../vue/views/map/components/MapQuickCreateDialog.vue"

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

  it("connects Vue controls to layout resize, move, lock and undo/redo commands", async () => {
    const quick = quickFixture()
    const wrapper = mount(MapQuickCreateDialog, { props: { quick }, attachTo: document.body, global: { stubs: { Teleport: true } } })
    const rowControls = wrapper.findAll(".map-quick-row-control")
    expect(rowControls).toHaveLength(7)
    expect(rowControls.every((control) => ["map-quick-radius", "map-quick-move", "map-quick-lock"].includes(control.attributes("data-action")))).toBe(true)
    await wrapper.find('[data-action="map-quick-radius"]:not(:disabled)').trigger("click")
    await wrapper.find('[data-action="map-quick-move"]:not(:disabled)').trigger("click")
    await wrapper.find('[data-action="map-quick-lock"]').trigger("click")
    const canvas = wrapper.find("#map-quick-canvas")
    await canvas.trigger("pointerdown", { clientX: 248, clientY: 127, pointerId: 1 })
    await canvas.trigger("pointermove", { clientX: 300, clientY: 160, pointerId: 1 })
    await canvas.trigger("pointerup", { clientX: 300, clientY: 160, pointerId: 1 })
    quick.state.history.push([])
    quick.state.redo.push([])
    await nextTick()
    await wrapper.find("#map-quick-undo").trigger("click")
    await wrapper.find("#map-quick-redo").trigger("click")
    expect(quick.resizeLocation).toHaveBeenCalledWith("loc1", "decrease")
    expect(quick.moveLocation).toHaveBeenCalledWith("loc1", -1, 0)
    expect(quick.toggleLock).toHaveBeenCalledWith("loc1")
    expect(quick.pushHistory).toHaveBeenCalled()
    expect(quick.moveLocationTo).toHaveBeenCalledWith("loc1", expect.any(Number), expect.any(Number))
    expect(quick.undo).toHaveBeenCalled()
    expect(quick.redo).toHaveBeenCalled()
    wrapper.unmount()
  })
})
