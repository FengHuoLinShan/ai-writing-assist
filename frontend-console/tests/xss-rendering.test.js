/**
 * XSS 渲染回归测试
 *
 * 验证用户/AI 内容不通过 innerHTML 直接插入 DOM。
 */
import { describe, it, expect, vi, beforeEach } from "vitest"

import "../app.js"
import contextView from "../views/contextView.js"

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
    output.id = "ctx-output"
    document.body.append(output)

    contextView._renderCompileResult({
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
    const output = document.createElement("div")
    output.id = "ctx-output"
    document.body.append(output)

    contextView._lastBundle = { section_count: 1 }
    const originalRender = api.context.render
    api.context.render = vi.fn().mockResolvedValue({
      markdown: "<script>alert(1)</script>",
    })

    await contextView.renderMarkdown()

    expect(output.querySelector("script")).toBeNull()
    expect(output.textContent).toContain("<script>alert(1)</script>")

    api.context.render = originalRender
  })
})
