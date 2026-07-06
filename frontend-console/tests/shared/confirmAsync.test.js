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
})
