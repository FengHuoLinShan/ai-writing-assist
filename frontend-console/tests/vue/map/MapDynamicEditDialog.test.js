import { mount } from "@vue/test-utils"
import { afterEach, describe, expect, it, vi } from "vitest"
import { nextTick, reactive } from "vue"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
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

async function nextRenderFrame() {
  if (typeof requestAnimationFrame === "function") {
    await new Promise((resolve) => requestAnimationFrame(resolve))
  } else {
    await Promise.resolve()
  }
  await nextTick()
}

describe("MapDynamicEditDialog", () => {
  afterEach(() => { document.body.replaceChildren(); vi.unstubAllGlobals() })
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

  it("moves focus into the dialog, traps it, closes on idle Escape, and restores its opener", async () => {
    const opener = document.createElement("button")
    opener.textContent = "打开编辑"
    document.body.appendChild(opener)
    opener.focus()
    const editor = editorFixture("location")
    const wrapper = mount(MapDynamicEditDialog, { attachTo: document.body, props: { editor } })
    await nextTick()
    const overlay = document.body.querySelector(".vue-map-dialog-backdrop")
    const close = document.body.querySelector('button[aria-label="关闭"]')
    const status = document.body.querySelector("#map-object-edit-status")
    const save = [...document.body.querySelectorAll("footer button")].find((button) => button.textContent === "保存")
    expect(document.activeElement).toBe(status)
    save.focus()
    overlay.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(close)
    overlay.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }))
    expect(editor.close).toHaveBeenCalledOnce()
    editor.state.open = false
    await nextTick()
    await Promise.resolve()
    expect(document.activeElement).toBe(opener)
    wrapper.unmount()
  })

  it("blocks close, Escape, and body interaction while saving", async () => {
    const editor = editorFixture("location")
    editor.state.saving = true
    const wrapper = mount(MapDynamicEditDialog, { attachTo: document.body, props: { editor } })
    await nextTick()
    const overlay = document.body.querySelector(".vue-map-dialog-backdrop")
    expect(document.body.querySelector("fieldset.vue-map-dialog__body").hasAttribute("disabled")).toBe(true)
    expect([...document.body.querySelectorAll("button")].every((button) => button.type === "button")).toBe(true)
    expect(document.body.querySelector('button[aria-label="关闭"]').disabled).toBe(true)
    overlay.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }))
    document.body.querySelector("#map-object-edit-status").dispatchEvent(new Event("change", { bubbles: true }))
    expect(editor.close).not.toHaveBeenCalled()
    expect(editor.state.status).toBe("candidate")
    wrapper.unmount()
  })

  it("inerts the map dialog beneath a nested global confirmation and restores editor focus", async () => {
    const global = document.createElement("div")
    global.id = "modal-overlay"
    global.className = "hidden"
    global.dataset.imperativeServiceHost = "modal"
    global.innerHTML = '<div id="modal-content"><button>取消</button></div>'
    document.body.appendChild(global)
    const editor = editorFixture("location")
    const wrapper = mount(MapDynamicEditDialog, { attachTo: document.body, props: { editor } })
    await nextTick()
    const status = document.body.querySelector("#map-object-edit-status")
    status.focus()
    global.classList.remove("hidden")
    await Promise.resolve()
    await nextTick()
    const overlay = document.body.querySelector(".vue-map-dialog-backdrop")
    expect(overlay.hasAttribute("inert")).toBe(true)
    expect(global.hasAttribute("inert")).toBe(false)
    expect(document.activeElement).toBe(document.getElementById("modal-content"))
    global.classList.add("hidden")
    await Promise.resolve()
    await nextTick()
    await nextRenderFrame()
    expect(overlay.hasAttribute("inert")).toBe(false)
    expect(document.activeElement).toBe(status)
    wrapper.unmount()
  })

  it("returns focus to Save after a nested confirmation cancellation unlocks it", async () => {
    const global = document.createElement("div")
    global.id = "modal-overlay"
    global.className = "hidden"
    global.dataset.imperativeServiceHost = "modal"
    global.innerHTML = '<div id="modal-content"><button>取消</button></div>'
    document.body.appendChild(global)
    const editor = editorFixture("location")
    const wrapper = mount(MapDynamicEditDialog, { attachTo: document.body, props: { editor } })
    await nextTick()
    const overlay = document.body.querySelector(".vue-map-dialog-backdrop")
    const save = [...document.body.querySelectorAll("footer button")].find((button) => button.textContent === "保存")
    save.focus()
    editor.state.saving = true
    await nextTick()
    global.classList.remove("hidden")
    await Promise.resolve()
    await nextTick()
    expect(overlay.hasAttribute("inert")).toBe(true)

    // A fact-save continuation clears saving after the global cancel/hide.
    await Promise.resolve().then(() => { global.classList.add("hidden"); editor.state.saving = false })
    await nextTick()
    await nextRenderFrame()
    expect(document.activeElement).toBe(save)
    wrapper.unmount()
  })

  it("waits one render frame for an async confirmation continuation to unlock Save", async () => {
    let deferredFrame = null
    vi.stubGlobal("requestAnimationFrame", (callback) => { deferredFrame = callback; return 1 })
    vi.stubGlobal("cancelAnimationFrame", vi.fn())
    const global = document.createElement("div")
    global.id = "modal-overlay"
    global.className = "hidden"
    global.dataset.imperativeServiceHost = "modal"
    global.innerHTML = '<div id="modal-content"><button>取消</button></div>'
    document.body.appendChild(global)
    const editor = editorFixture("location")
    const wrapper = mount(MapDynamicEditDialog, { attachTo: document.body, props: { editor } })
    await nextTick()
    // Complete the opening focus frame before modeling the save flow.
    deferredFrame?.()
    const save = [...document.body.querySelectorAll("footer button")].find((button) => button.textContent === "保存")
    save.focus()
    editor.state.saving = true
    await nextTick()
    global.classList.remove("hidden")
    await Promise.resolve()
    global.classList.add("hidden")
    await vi.waitFor(() => expect(deferredFrame).toBeTypeOf("function"))
    // confirmAsync settles first; editor.save's finally unlocks on its later
    // continuation, before the deferred post-render focus restoration.
    editor.state.saving = false
    await nextTick()
    deferredFrame()
    expect(document.activeElement).toBe(save)
    wrapper.unmount()
  })

  it("falls back inside the dialog when the nested-confirmation opener stays disabled", async () => {
    const global = document.createElement("div")
    global.id = "modal-overlay"
    global.className = "hidden"
    global.dataset.imperativeServiceHost = "modal"
    global.innerHTML = '<div id="modal-content"><button>取消</button></div>'
    document.body.appendChild(global)
    const editor = editorFixture("location")
    const wrapper = mount(MapDynamicEditDialog, { attachTo: document.body, props: { editor } })
    await nextTick()
    const overlay = document.body.querySelector(".vue-map-dialog-backdrop")
    const save = [...document.body.querySelectorAll("footer button")].find((button) => button.textContent === "保存")
    save.focus()
    editor.state.saving = true
    await nextTick()
    global.classList.remove("hidden")
    await Promise.resolve()
    await nextTick()
    expect(overlay.hasAttribute("inert")).toBe(true)
    global.classList.add("hidden")
    await Promise.resolve()
    await nextTick()
    await nextRenderFrame()
    expect(document.activeElement).not.toBe(save)
    expect(document.body.querySelector('[role="dialog"]').contains(document.activeElement)).toBe(true)
    expect(overlay.hasAttribute("inert")).toBe(false)
    wrapper.unmount()
  })

  it("keeps map, account, global, and toast layers in the intended order", () => {
    const styles = readFileSync(resolve(__dirname, "../../../styles.css"), "utf8")
    const dynamic = readFileSync(resolve(__dirname, "../../../vue/views/map/components/MapDynamicEditDialog.vue"), "utf8")
    const quick = readFileSync(resolve(__dirname, "../../../vue/views/map/components/MapQuickCreateDialog.vue"), "utf8")
    const account = readFileSync(resolve(__dirname, "../../../vue/shell/components/AccountDialog.vue"), "utf8")
    expect(dynamic).toMatch(/\.vue-map-dialog-backdrop\s*\{[^}]*z-index:\s*1100/s)
    expect(quick).toMatch(/\.vue-map-dialog-backdrop\s*\{[^}]*z-index:\s*1100/s)
    expect(account).toMatch(/\.account-overlay\{[^}]*z-index:1200/s)
    expect(styles).toMatch(/#modal-overlay[^}]*\{[^}]*z-index:\s*1300/s)
    expect(styles).toMatch(/#toast-container\s*\{[^}]*z-index:\s*2000/s)
  })
})
