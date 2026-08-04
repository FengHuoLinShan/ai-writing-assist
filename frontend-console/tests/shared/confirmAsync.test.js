/**
 * confirmAsync 最小测试
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { confirmAsync } from "../../shared/confirmAsync.js"
import { resetState, clearDocument } from "../helpers.js"

beforeEach(() => {
  resetState()
  clearDocument()
  vi.clearAllMocks()
  globalThis.confirmAction.mockReset()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("confirmAsync", () => {
  it("resolves true when confirmAction confirms", async () => {
    document.body.innerHTML = `
      <div id="modal-overlay"></div>
      <button id="modal-close"></button>
    `
    globalThis.confirmAction.mockImplementation((_msg, onConfirm, _text) => onConfirm())

    const result = await confirmAsync("确定？", "确认")
    expect(result).toBe(true)
  })

  it("does not leave cancellation listeners after synchronous confirmation", async () => {
    document.body.innerHTML = `
      <div id="modal-overlay"></div>
      <button id="modal-close"></button>
    `
    const closeButton = document.getElementById("modal-close")
    const addListener = vi.spyOn(closeButton, "addEventListener")
    globalThis.confirmAction.mockImplementation((_msg, onConfirm) => onConfirm())

    await expect(confirmAsync("确定？", "确认")).resolves.toBe(true)

    expect(addListener).not.toHaveBeenCalled()
  })

  it("resolves false when modal-close clicked", async () => {
    document.body.innerHTML = `
      <div id="modal-overlay"></div>
      <button id="modal-close"></button>
    `
    globalThis.confirmAction.mockImplementation(() => {})
    setTimeout(() => {
      document.getElementById("modal-close").click()
    }, 10)

    const result = await confirmAsync("确定？", "确认")
    expect(result).toBe(false)
  })

  it("binds a synchronously rendered cancel button without a timer", async () => {
    document.body.innerHTML = `
      <div id="modal-overlay"></div>
      <button id="modal-close"></button>
      <div id="modal-footer"></div>
    `
    globalThis.confirmAction.mockImplementation(() => {
      const cancel = document.createElement("button")
      cancel.textContent = "取消"
      document.getElementById("modal-footer").appendChild(cancel)
    })

    const pending = confirmAsync("确定？", "确认")
    document.querySelector("#modal-footer button").click()

    await expect(pending).resolves.toBe(false)
  })

  it("resolves false on overlay click", async () => {
    document.body.innerHTML = '<div id="modal-overlay"></div>'
    globalThis.confirmAction.mockImplementation(() => {})
    setTimeout(() => {
      document.getElementById("modal-overlay").click()
    }, 10)

    const result = await confirmAsync("确定？", "确认")
    expect(result).toBe(false)
  })

  it("resolves false on Escape key", async () => {
    document.body.innerHTML = `
      <div id="modal-overlay"></div>
      <button id="modal-close"></button>
    `
    globalThis.confirmAction.mockImplementation(() => {})
    setTimeout(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }))
    }, 10)

    const result = await confirmAsync("确定？", "确认")
    expect(result).toBe(false)
  })

  it("resolves false when overlay hidden", async () => {
    document.body.innerHTML = '<div id="modal-overlay" class=""></div>'
    globalThis.confirmAction.mockImplementation(() => {})
    setTimeout(() => {
      const overlay = document.getElementById("modal-overlay")
      overlay.classList.add("hidden")
    }, 10)

    const result = await confirmAsync("确定？", "确认")
    expect(result).toBe(false)
  })

  it("cancels an in-flight confirmation when its visible modal session is replaced", async () => {
    document.body.innerHTML = '<div id="modal-overlay"><button id="modal-close"></button><div id="modal-content"><div id="modal-footer"><button>取消</button></div></div></div>'
    const removeListener = vi.spyOn(document.getElementById("modal-close"), "removeEventListener")
    let staleConfirm
    globalThis.confirmAction.mockImplementation((_message, onConfirm) => { staleConfirm = onConfirm })

    const pending = confirmAsync("旧确认", "确认")
    document.getElementById("modal-content").replaceChildren(document.createElement("p"))
    await expect(pending).resolves.toBe(false)
    staleConfirm()
    await Promise.resolve()

    expect(removeListener).toHaveBeenCalledWith("click", expect.any(Function))
  })

  it("keeps a successor confirmation isolated from an old replaced session", async () => {
    document.body.innerHTML = '<div id="modal-overlay"><button id="modal-close"></button><div id="modal-content"><div id="modal-footer"></div></div></div>'
    const callbacks = []
    globalThis.confirmAction.mockImplementation((_message, onConfirm) => callbacks.push(onConfirm))

    const first = confirmAsync("旧确认", "确认")
    document.getElementById("modal-content").replaceChildren(document.createElement("div"))
    await expect(first).resolves.toBe(false)
    const second = confirmAsync("新确认", "确认")
    callbacks[0]()
    await Promise.resolve()
    callbacks[1]()

    await expect(second).resolves.toBe(true)
  })

  it("cancels a nested shell modal-host replacement without reacting to unrelated DOM changes", async () => {
    document.body.innerHTML = '<div id="app"><div class="vue-shell-root"><main id="page"><button>页面操作</button></main><div data-imperative-service-host="modal" id="modal-service"><div id="modal-overlay"><button id="modal-close"></button><div id="modal-content"><div id="modal-footer"></div></div></div></div></div></div>'
    const close = document.getElementById("modal-close")
    const removeListener = vi.spyOn(close, "removeEventListener")
    const callbacks = []
    globalThis.confirmAction.mockImplementation((_message, onConfirm) => callbacks.push(onConfirm))

    const pending = confirmAsync("旧确认", "确认")
    document.getElementById("page").append(document.createElement("span"))
    await Promise.resolve()
    expect(callbacks).toHaveLength(1)
    callbacks[0]()
    await expect(pending).resolves.toBe(true)

    const replaced = confirmAsync("待替换确认", "确认")
    const service = document.getElementById("modal-service")
    service.replaceChildren(Object.assign(document.createElement("div"), { id: "modal-overlay" }))
    await expect(replaced).resolves.toBe(false)
    expect(removeListener).toHaveBeenCalledWith("click", expect.any(Function))

    const successor = confirmAsync("继任确认", "确认")
    callbacks[1]()
    await Promise.resolve()
    callbacks[2]()
    await expect(successor).resolves.toBe(true)
  })
})
