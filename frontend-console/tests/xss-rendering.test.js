/**
 * XSS 渲染回归测试
 *
 * 验证用户/AI 内容不通过 innerHTML 直接插入 DOM。
 */
import { describe, it, expect, vi, beforeEach } from "vitest"

import "../app.js"
import "../ui/modal.js"
import generateView from "../views/generateView.js"

beforeEach(() => {
  vi.clearAllMocks()
  document.body.replaceChildren()
  if (typeof globalThis.commands === "undefined") {
    globalThis.commands = { getSuggestions: () => [], execute: vi.fn() }
  }
})

describe("command suggestions", () => {
  it("keeps the hidden command bar out of keyboard navigation", () => {
    document.body.innerHTML = `
      <div id="command-bar" inert aria-hidden="true">
        <input id="command-input" />
        <div id="command-suggestions"></div>
      </div>
    `

    globalThis.App._focusCommandBar(":")
    const bar = document.getElementById("command-bar")
    expect(bar.inert).toBe(false)
    expect(bar.getAttribute("aria-hidden")).toBe("false")
    expect(bar.classList.contains("active")).toBe(true)

    globalThis.App._hideCommandBar()
    expect(bar.inert).toBe(true)
    expect(bar.getAttribute("aria-hidden")).toBe("true")
    expect(bar.classList.contains("active")).toBe(false)
  })

  it("renders suggestions via DOM construction without executing HTML", () => {
    const bar = document.createElement("div")
    bar.id = "command-bar"
    const input = document.createElement("input")
    input.id = "command-input"
    const suggestionsEl = document.createElement("div")
    suggestionsEl.id = "command-suggestions"
    const hint = document.createElement("span")
    hint.id = "command-hint"
    bar.append(input, suggestionsEl, hint)
    document.body.append(bar)

    // Mock command suggestions that contain HTML payloads
    const originalGetSuggestions = commands.getSuggestions
    commands.getSuggestions = () => [
      { name: "<img src=x onerror=alert(1)>", description: "<script>alert(1)</script>" },
    ]

    input.value = ":<img"
    globalThis.App._updateHint(input, hint, suggestionsEl)

    expect(suggestionsEl.querySelector("script")).toBeNull()
    expect(suggestionsEl.querySelector("img")).toBeNull()
    expect(suggestionsEl.textContent).toContain("<script>alert(1)</script>")
    expect(suggestionsEl.textContent).toContain("<img src=x onerror=alert(1)>")

    commands.getSuggestions = originalGetSuggestions
  })

  it("shows visible feedback when command execution rejects", async () => {
    document.body.innerHTML = `
      <div id="workspace" tabindex="-1"></div>
      <div id="command-bar">
        <input id="command-input" value=":fail" />
        <span id="command-hint"></span>
        <div id="command-suggestions"></div>
      </div>
    `
    commands.execute = vi.fn().mockRejectedValue(new Error("command failed"))
    globalThis.App._bindCommandBar()

    document.getElementById("command-input").dispatchEvent(new KeyboardEvent("keydown", {
      key: "Enter",
      bubbles: true,
    }))
    await Promise.resolve()
    await Promise.resolve()

    expect(toast).toHaveBeenCalledWith("命令执行失败：command failed", "error")
  })
})

describe("app navigation failure feedback", () => {
  it("shows visible feedback when navigation rejects", async () => {
    document.body.innerHTML = '<button class="nav-item" data-view="world"></button>'
    router.getRoute = vi.fn().mockReturnValue({ subViews: [] })
    router.getLastSubView = vi.fn().mockReturnValue(null)
    router.navigate = vi.fn().mockRejectedValue(new Error("route failed"))

    globalThis.App._bindNavigation()
    document.querySelector(".nav-item").click()
    await Promise.resolve()
    await Promise.resolve()

    expect(toast).toHaveBeenCalledWith("导航失败：route failed", "error")
  })
})

describe("context compile result", () => {
  it("renders AI bundle data without injecting HTML", () => {
    const output = document.createElement("div")
    output.id = "gen-task-output"
    document.body.append(output)

    output.innerHTML = generateView._renderCompileResult({
      total_tokens: 100,
      budget_tokens: 1000,
      scope: "<script>alert('scope')</script>",
      reveal_mode: "author_safe",
      sections: [{ key: "<script>alert('section')</script>", tier: "core", token_count: 100, truncated: false }],
      evicted: ["<script>alert('evicted')</script>"],
      truncated: ["<script>alert('truncated')</script>"],
      warnings: ["<script>alert('warning')</script>"],
    })

    expect(output.querySelector("script")).toBeNull()
    expect(output.textContent).toContain("<script>alert('scope')</script>")
    expect(output.textContent).toContain("<script>alert('section')</script>")
    expect(output.textContent).toContain("<script>alert('evicted')</script>")
    expect(output.textContent).toContain("<script>alert('truncated')</script>")
    expect(output.textContent).toContain("<script>alert('warning')</script>")
  })
})

describe("context markdown output", () => {
  it("renders markdown as text not HTML", async () => {
    state.currentProjectId = "p1"
    const output = document.createElement("div")
    output.id = "gen-task-output"
    document.body.append(output)

    generateView._lastContextRequestParams = { novel_id: "p1", task: "test", scope: "arc" }
    const originalRender = api.context.render
    api.context.render = vi.fn().mockResolvedValue({
      markdown: "<script>alert(1)</script>",
    })

    await generateView._renderTaskMarkdown()

    expect(output.querySelector("script")).toBeNull()
    expect(output.textContent).toContain("<script>alert(1)</script>")

    api.context.render = originalRender
  })
})

describe("generated object result rendering", () => {
  it("renders AI object fields as text nodes", () => {
    const node = generateView._renderEntityResultNode({
      name: "<img src=x onerror=alert(1)>",
      entity_type: "<script>alert('type')</script>",
      status: "draft",
      summary: "<script>alert('summary')</script>",
    })

    document.body.append(node)

    expect(document.querySelector("img")).toBeNull()
    expect(document.querySelector("script")).toBeNull()
    expect(document.body.textContent).toContain("<img src=x onerror=alert(1)>")
    expect(document.body.textContent).toContain("<script>alert('summary')</script>")
  })

  it("renders inline errors as text nodes", () => {
    const node = generateView._renderInlineError("生成失败：<img src=x onerror=alert(1)>")

    document.body.append(node)

    expect(document.querySelector("img")).toBeNull()
    expect(document.body.textContent).toContain("<img src=x onerror=alert(1)>")
  })
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
