import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import { defineComponent, h, nextTick } from "vue"
import { useModalDialog } from "../../../vue/composables/useModalDialog.js"

enableAutoUnmount(afterEach)

const Harness = defineComponent({
  props: {
    open: Boolean,
    canClose: { type: Boolean, default: true },
    body: { type: String, default: "input" },
    controls: { type: Boolean, default: true },
  },
  emits: ["close"],
  setup(props, { emit }) {
    const modal = useModalDialog({ isOpen: () => props.open, requestClose: () => emit("close"), canClose: () => props.canClose })
    return () => props.open ? h("div", { ref: modal.overlayRef, class: "modal-overlay", onKeydown: modal.onKeydown, onFocusin: modal.onFocusin }, [
      h("section", { ref: modal.dialogRef, class: "modal-content", role: "dialog", tabindex: -1 }, [
        h("div", { class: "modal-header" }, props.controls ? [h("button", { type: "button", "aria-label": "关闭" }, "×")] : []),
        h("div", { class: "modal-body" }, props.body === "details"
          ? [h("details", [h("summary", "详情"), h("button", { type: "button" }, "隐藏操作")])]
          : props.body === "empty" || !props.controls ? [] : [h("input", { autofocus: true }), h("button", { type: "button", disabled: true }, "禁用")]),
        h("div", { class: "modal-footer" }, props.controls ? [h("button", { type: "button" }, "确认")] : []),
      ]),
    ]) : null
  },
})

beforeEach(() => { document.body.innerHTML = "" })

function mountInShell(props = {}) {
  const { beforeMount, ...harnessProps } = props
  const shell = document.createElement("div")
  shell.className = "vue-shell-root"
  const topbar = document.createElement("button")
  topbar.textContent = "顶部"
  const main = document.createElement("main")
  const content = document.createElement("button")
  content.textContent = "写作内容"
  const host = document.createElement("div")
  main.append(content, host)
  shell.append(topbar, main)
  document.body.appendChild(shell)
  beforeMount?.({ shell, topbar, content, host })
  topbar.focus()
  return { wrapper: mount(Harness, { attachTo: host, props: { open: true, ...harnessProps } }), shell, topbar, content, host }
}

function addGlobalModal() {
  const global = document.createElement("div")
  global.id = "modal-overlay"
  global.className = "hidden"
  global.dataset.imperativeServiceHost = "modal"
  const globalContent = document.createElement("div")
  globalContent.id = "modal-content"
  const globalButton = document.createElement("button")
  globalButton.textContent = "取消"
  globalContent.appendChild(globalButton)
  global.appendChild(globalContent)
  document.body.appendChild(global)
  return { global, globalButton }
}

describe("useModalDialog", () => {
  it("focuses autofocus body controls and isolates ancestor-path siblings without inerting service hosts", async () => {
    const { wrapper, topbar, content, shell } = mountInShell({
      beforeMount: ({ shell: root }) => {
        const service = document.createElement("div")
        service.dataset.imperativeServiceHost = "modal"
        root.appendChild(service)
      },
    })
    await nextTick()
    const service = shell.querySelector("[data-imperative-service-host]")
    expect(document.activeElement).toBe(wrapper.get("input").element)
    expect(topbar.hasAttribute("inert")).toBe(true)
    expect(content.hasAttribute("inert")).toBe(true)
    expect(service.hasAttribute("inert")).toBe(false)
  })

  it("filters closed details descendants and traps Tab from outside the admitted controls", async () => {
    const { wrapper } = mountInShell({ body: "details" })
    await nextTick()
    const summary = wrapper.get("summary").element
    expect(document.activeElement).toBe(summary)
    const outside = document.createElement("button")
    document.body.appendChild(outside)
    outside.focus()
    const tab = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true })
    wrapper.get(".modal-overlay").element.dispatchEvent(tab)
    expect(tab.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(wrapper.get('[aria-label="关闭"]').element)
  })

  it("wraps Tab forward from last to first and backward from first to last", async () => {
    const { wrapper } = mountInShell()
    await nextTick()
    const close = wrapper.get('[aria-label="关闭"]').element
    const confirm = wrapper.get(".modal-footer button").element
    confirm.focus()
    const forward = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true })
    wrapper.get(".modal-overlay").element.dispatchEvent(forward)
    expect(forward.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(close)
    close.focus()
    const backward = new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true })
    wrapper.get(".modal-overlay").element.dispatchEvent(backward)
    expect(backward.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(confirm)
  })

  it("falls back to the dialog when it admits no focusable controls", async () => {
    const { wrapper } = mountInShell({ body: "empty", controls: false })
    await nextTick()
    const dialog = wrapper.get('[role="dialog"]').element
    expect(document.activeElement).toBe(dialog)
    const tab = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true })
    wrapper.get(".modal-overlay").element.dispatchEvent(tab)
    expect(tab.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(dialog)
  })

  it("contains ordinary keys, allows only closable Escape, and restores a valid opener", async () => {
    const { wrapper, topbar } = mountInShell({ canClose: false })
    await nextTick()
    const documentKeys = vi.fn()
    document.addEventListener("keydown", documentKeys)
    const ordinary = new KeyboardEvent("keydown", { key: "g", bubbles: true, cancelable: true })
    wrapper.get(".modal-overlay").element.dispatchEvent(ordinary)
    expect(ordinary.defaultPrevented).toBe(false)
    expect(documentKeys).not.toHaveBeenCalled()
    const escape = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })
    wrapper.get(".modal-overlay").element.dispatchEvent(escape)
    expect(escape.defaultPrevented).toBe(true)
    expect(wrapper.emitted("close")).toBeUndefined()
    await wrapper.setProps({ canClose: true })
    wrapper.get(".modal-overlay").element.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }))
    expect(wrapper.emitted("close")).toHaveLength(1)
    await wrapper.setProps({ open: false })
    await nextTick()
    expect(document.activeElement).toBe(topbar)
    document.removeEventListener("keydown", documentKeys)
  })

  it("preserves a preexisting inert background", async () => {
    const first = mountInShell({ beforeMount: ({ topbar }) => topbar.setAttribute("inert", "") })
    await nextTick()
    await first.wrapper.setProps({ open: false })
    await nextTick()
    expect(first.topbar.hasAttribute("inert")).toBe(true)
  })

  it("reference-counts a non-preexisting background lease until the final dialog closes", async () => {
    const first = mountInShell()
    await nextTick()
    const secondHost = document.createElement("div")
    first.host.parentElement.appendChild(secondHost)
    const second = mount(Harness, { attachTo: secondHost, props: { open: true } })
    await nextTick()
    expect(first.topbar.hasAttribute("inert")).toBe(true)
    await first.wrapper.setProps({ open: false })
    await nextTick()
    expect(first.topbar.hasAttribute("inert")).toBe(true)
    await second.setProps({ open: false })
    await nextTick()
    expect(first.topbar.hasAttribute("inert")).toBe(false)
  })

  it("releases background leases on ordinary close and unmount", async () => {
    const ordinary = mountInShell()
    await nextTick()
    expect(ordinary.topbar.hasAttribute("inert")).toBe(true)
    await ordinary.wrapper.setProps({ open: false })
    await nextTick()
    expect(ordinary.topbar.hasAttribute("inert")).toBe(false)

    const unmounted = mountInShell()
    await nextTick()
    expect(unmounted.topbar.hasAttribute("inert")).toBe(true)
    unmounted.wrapper.unmount()
    expect(unmounted.topbar.hasAttribute("inert")).toBe(false)
  })

  it("does not lease or focus after an immediate open-to-close unmount", async () => {
    const { wrapper, topbar, content } = mountInShell()
    content.focus()
    await wrapper.setProps({ open: false })
    wrapper.unmount()
    await nextTick()
    expect(topbar.hasAttribute("inert")).toBe(false)
    expect(document.activeElement).not.toBe(topbar)
  })

  it.each([
    ["removed", (topbar) => topbar.remove()],
    ["disabled", (topbar) => { topbar.disabled = true }],
    ["newly inert", (topbar) => topbar.setAttribute("inert", "")],
  ])("does not restore a %s opener", async (_label, invalidate) => {
    const { wrapper, topbar } = mountInShell()
    await nextTick()
    invalidate(topbar)
    await wrapper.setProps({ open: false })
    await nextTick()
    expect(document.activeElement).not.toBe(topbar)
  })

  it("handles nested global modal class toggles without inerting the global host", async () => {
    const { global } = addGlobalModal()
    const { wrapper } = mountInShell()
    await nextTick()
    global.classList.remove("hidden")
    await Promise.resolve()
    await nextTick()
    expect(wrapper.get(".modal-overlay").attributes("inert")).toBeDefined()
    expect(global.hasAttribute("inert")).toBe(false)
    expect(document.activeElement).toBe(global.querySelector("#modal-content"))
    global.classList.add("hidden")
    await Promise.resolve()
    await nextTick()
    await new Promise((resolve) => requestAnimationFrame(resolve))
    await nextTick()
    expect(wrapper.get(".modal-overlay").attributes("inert")).toBeUndefined()
    expect(wrapper.get(".modal-content").element.contains(document.activeElement)).toBe(true)
  })

  it("ignores stale nested focus and restore work across hide, close, and reopen", async () => {
    const { global } = addGlobalModal()
    const { wrapper, topbar } = mountInShell()
    await nextTick()

    global.classList.remove("hidden")
    await Promise.resolve()
    global.classList.add("hidden")
    await wrapper.setProps({ open: false })
    await wrapper.setProps({ open: true })
    await nextTick()

    expect(document.activeElement).not.toBe(global.querySelector("#modal-content"))
    expect(wrapper.get(".modal-content").element.contains(document.activeElement)).toBe(true)
    expect(document.activeElement).not.toBe(topbar)
  })

  it("does not restore the writing opener behind a still-visible global modal", async () => {
    const { global } = addGlobalModal()
    const { wrapper, topbar } = mountInShell()
    await nextTick()
    global.classList.remove("hidden")
    await Promise.resolve()
    await nextTick()
    expect(document.activeElement).toBe(global.querySelector("#modal-content"))

    await wrapper.setProps({ open: false })
    await nextTick()
    expect(document.activeElement).toBe(global.querySelector("#modal-content"))
    expect(document.activeElement).not.toBe(topbar)
  })

  it("isolates Teleported map content without inerting service-host ancestry", async () => {
    document.body.innerHTML = '<div id="app"><div class="vue-shell-root"><main id="app-content"><button>页面</button></main><div id="toast-container" data-imperative-service-host="toast"></div><div id="modal-overlay" class="hidden" data-imperative-service-host="modal"><div id="modal-content"></div></div></div></div>'
    const host = document.createElement("div")
    document.body.appendChild(host)
    const wrapper = mount(Harness, { attachTo: host, props: { open: true } })
    await nextTick()
    expect(document.getElementById("app-content").hasAttribute("inert")).toBe(true)
    expect(document.getElementById("app").hasAttribute("inert")).toBe(false)
    expect(document.getElementById("toast-container").hasAttribute("inert")).toBe(false)
    wrapper.unmount()
    expect(document.getElementById("app-content").hasAttribute("inert")).toBe(false)
  })
})
