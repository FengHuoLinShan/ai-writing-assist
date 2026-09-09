import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import { defineComponent, h } from "vue"
import { useShellShortcuts } from "../../../vue/shell/composables/useShellShortcuts.js"

let host
let services
let commandOpen
let toastSpy

function pressKey(target, options) {
  const event = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...options })
  target.dispatchEvent(event)
  return event
}

function mountHost() {
  const Host = defineComponent({
    setup() {
      useShellShortcuts({
        services,
        shellState: { currentView: "world", currentSubView: null },
        getRouteHost: () => host,
        command: {
          isOpen: () => false,
          open: (prefix) => commandOpen(prefix),
          close: () => {},
        },
        help: { isOpen: () => false, open: () => {}, close: () => {} },
        focusSidebar: () => {},
      })
      return () => h("div", [h("input", { type: "text" })])
    },
  })
  return mount(Host, { attachTo: host })
}

beforeEach(() => {
  host = document.createElement("div")
  host.id = "workspace-content"
  document.body.appendChild(host)
  commandOpen = vi.fn()
  toastSpy = vi.fn()
  services = {
    toast: toastSpy,
    state: { mode: "NORMAL" },
    router: { navigate: vi.fn() },
    modal: { isOpen: () => false, close: () => {} },
    workspace: {
      triggerAction: vi.fn(() => false),
      moveSelection: vi.fn(() => false),
      autosave: vi.fn(() => false),
      quickopen: vi.fn(() => true),
      toggleOutlineFloat: vi.fn(() => false),
    },
  }
})

afterEach(() => {
  host.remove()
})

describe("useShellShortcuts — 输入框内的保存与快速打开", () => {
  it("在输入框中按 Ctrl/Cmd+S 触发保存 seam 而不是被表单跳过", () => {
    const wrapper = mountHost()
    const input = wrapper.get("input").element

    const event = pressKey(input, { key: "s", ctrlKey: true })

    expect(event.defaultPrevented).toBe(true)
    expect(services.workspace.autosave).toHaveBeenCalledWith(host)
  })

  it("在输入框中按 Ctrl/Cmd+K 优先触发 quickopen，未被处理时回退命令栏", () => {
    const wrapper = mountHost()
    const input = wrapper.get("input").element

    const event = pressKey(input, { key: "k", metaKey: true })

    expect(event.defaultPrevented).toBe(true)
    expect(services.workspace.quickopen).toHaveBeenCalledWith(host)
    expect(commandOpen).not.toHaveBeenCalled()

    services.workspace.quickopen.mockReturnValueOnce(false)
    pressKey(input, { key: "k", metaKey: true })
    expect(commandOpen).toHaveBeenCalledWith(":")
  })

  it("普通按键在输入框内仍被跳过，Escape 走失焦", () => {
    const wrapper = mountHost()
    const input = wrapper.get("input").element

    pressKey(input, { key: "x" })
    expect(services.workspace.triggerAction).not.toHaveBeenCalled()

    const blurSpy = vi.fn()
    input.blur = blurSpy
    pressKey(input, { key: "Escape" })
    expect(blurSpy).toHaveBeenCalled()
  })
})
