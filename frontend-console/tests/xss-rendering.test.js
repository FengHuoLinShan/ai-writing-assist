/**
 * XSS 渲染回归测试
 *
 * 验证用户/AI 内容不通过 innerHTML 直接插入 DOM。
 */
import { describe, it, expect, vi, beforeEach } from "vitest"

import "../ui/modal.js"

beforeEach(() => {
  vi.clearAllMocks()
  document.body.replaceChildren()
})

describe("modal body rendering", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="modal-overlay" class="hidden">
        <div id="modal-content">
          <div id="modal-title"></div>
          <div id="modal-body"></div>
          <div id="modal-footer"></div>
        </div>
      </div>
    `
  })

  async function flushClick() {
    await Promise.resolve()
    await Promise.resolve()
  }

  function isModalOpen() {
    return !document.getElementById("modal-overlay").classList.contains("hidden")
  }

  it("does not execute script tags passed as a string body", () => {
    let executed = false
    globalThis.modalXssPayload = () => { executed = true }

    window.showModal("XSS test", "<script>globalThis.modalXssPayload()</script>")

    const bodyEl = document.getElementById("modal-body")
    expect(bodyEl.querySelector("script")).toBeNull()
    expect(executed).toBe(false)
    expect(bodyEl.textContent).toContain("<script>globalThis.modalXssPayload()</script>")

    delete globalThis.modalXssPayload
  })

  it("still accepts HTMLElement bodies", () => {
    const node = document.createElement("p")
    node.textContent = "paragraph"
    window.showModal("Node test", node)

    const bodyEl = document.getElementById("modal-body")
    expect(bodyEl.querySelector("p")?.textContent).toBe("paragraph")
  })

  it("renders trusted { html: string } via innerHTML", () => {
    window.showModal("HTML test", { html: "<p>paragraph</p>" })

    const bodyEl = document.getElementById("modal-body")
    expect(bodyEl.querySelector("p")?.textContent).toBe("paragraph")
  })

  it("showModalHtml wraps the body as trusted HTML", () => {
    window.showModalHtml("HTML helper test", "<p>helper paragraph</p>")

    const bodyEl = document.getElementById("modal-body")
    expect(bodyEl.querySelector("p")?.textContent).toBe("helper paragraph")
  })

  it("showModalHtml applies and resets optional size classes", () => {
    const contentEl = document.getElementById("modal-content")

    window.showModalHtml("Large helper test", "<p>large</p>", [], { size: "large" })
    expect(contentEl.classList.contains("modal-content--large")).toBe(true)
    expect(contentEl.dataset.modalSize).toBe("large")

    window.showModalHtml("Default helper test", "<p>default</p>")
    expect(contentEl.classList.contains("modal-content--large")).toBe(false)
    expect(contentEl.classList.contains("modal-content--full")).toBe(false)
    expect(contentEl.dataset.modalSize).toBeUndefined()
  })

  it("closes after an async handler resolves", async () => {
    window.showModal("Async ok", "body", [
      { text: "保存", handler: vi.fn().mockResolvedValue(true) },
    ])

    document.querySelector("#modal-footer button").click()
    await flushClick()

    expect(isModalOpen()).toBe(false)
  })

  it("keeps open and shows toast when an async handler rejects", async () => {
    window.showModal("Async fail", "body", [
      { text: "保存", handler: vi.fn().mockRejectedValue(new Error("boom")) },
    ])

    document.querySelector("#modal-footer button").click()
    await flushClick()

    expect(isModalOpen()).toBe(true)
    expect(toast).toHaveBeenCalledWith("操作失败：boom", "error")
  })

  it("keeps open when a handler returns false", async () => {
    window.showModal("Stay open", "body", [
      { text: "保存", handler: vi.fn().mockResolvedValue(false) },
    ])

    document.querySelector("#modal-footer button").click()
    await flushClick()

    expect(isModalOpen()).toBe(true)
  })

  it("still closes through cancel and close buttons", async () => {
    window.showModal("Cancel", "body", [
      { text: "关闭", handler: vi.fn().mockResolvedValue(false) },
    ])

    document.querySelector("#modal-footer button").click()
    await flushClick()

    expect(isModalOpen()).toBe(false)
  })

  it("confirmAction async reject does not bypass confirmation or close", async () => {
    const onConfirm = vi.fn().mockRejectedValue(new Error("拒绝删除"))
    window.confirmAction("确定永久删除？", onConfirm, "永久删除")

    expect(onConfirm).not.toHaveBeenCalled()

    document.querySelector("#modal-footer button").click()
    await flushClick()

    expect(onConfirm).toHaveBeenCalledOnce()
    expect(isModalOpen()).toBe(true)
    expect(toast).toHaveBeenCalledWith("操作失败：拒绝删除", "error")
  })
})
