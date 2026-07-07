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

describe("modal body rendering", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="modal-overlay" class="hidden">
        <div id="modal-title"></div>
        <div id="modal-body"></div>
        <div id="modal-footer"></div>
      </div>
    `
  })

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
})
