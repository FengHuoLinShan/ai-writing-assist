import { mount } from "@vue/test-utils"
import { describe, expect, it, vi } from "vitest"
import { reactive } from "vue"
import MapDynamicEditDialog from "../../../vue/views/map/components/MapDynamicEditDialog.vue"

function editorFixture(type = "location") {
  return {
    state: reactive({
      open: true, saving: false, error: null, isFact: false, legacy: false,
      item: { id: "o1", time_label: "Scene 2", evidence_text: "正文" }, status: "candidate",
      targetName: "沈澜", targetEntityId: "e1",
      entities: [{ id: "e1", name: "沈澜", entityType: "character" }, { id: "l1", name: "北港", entityType: "location" }],
      paths: [{ id: "path1", name: "北境道" }], scalarType: "string", hexText: "1,2",
      value: { schema_version: 1, type, state: "present", location_entity_id: "l1", related_entity_ids: [] },
      spatialContext: { map: { id: "m1", name: "九州", grid_width: 20, grid_height: 12 }, locationAnchors: [{ location_entity_id: "l1", name: "北港", q: 7, r: 4 }] },
      anchorQ: "", anchorR: "",
    }),
    close: vi.fn(), save: vi.fn(), useLocationCenter: vi.fn(), clearSpatialHex: vi.fn(),
  }
}

describe("MapDynamicEditDialog", () => {
  it.each([
    ["location", "#map-typed-location-entity"], ["route_state", "#map-typed-route-path"],
    ["status", "#map-typed-status-key"], ["boundary", "#map-typed-boundary-hexes"],
    ["resource", "#map-typed-resource-key"], ["terrain", "#map-typed-terrain-key"],
    ["crisis", "#map-typed-crisis-key"], ["semantic", "#map-typed-semantic-relation"],
  ])("renders the %s typed fieldset", (type, selector) => {
    const wrapper = mount(MapDynamicEditDialog, { attachTo: document.body, props: { editor: editorFixture(type) } })
    expect(document.body.querySelector(selector)).not.toBeNull()
    expect(document.body.querySelector("#map-object-edit-value-json")).toBeNull()
    wrapper.unmount()
  })

  it("submits through the typed editor controller", async () => {
    const editor = editorFixture("location")
    const wrapper = mount(MapDynamicEditDialog, { attachTo: document.body, props: { editor } })
    const save = [...document.body.querySelectorAll("button")].find((button) => button.textContent === "保存")
    save.click()
    expect(editor.save).toHaveBeenCalled()
    wrapper.unmount()
  })

  it("展示候选落点预览并调用地点中心动作", async () => {
    const editor = editorFixture("location")
    const wrapper = mount(MapDynamicEditDialog, { attachTo: document.body, props: { editor } })
    expect(document.body.querySelector("#map-spatial-anchor-preview")).not.toBeNull()
    document.body.querySelector("#map-anchor-use-location").click()
    await Promise.resolve()
    expect(editor.useLocationCenter).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
