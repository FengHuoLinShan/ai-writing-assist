/**
 * outlineFloat 子模块最小测试
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { createOutlineFloat } from "../../views/writing/outlineFloat.js"
import { resetState, clearDocument } from "../helpers.js"

function createTestFloat(overrides = {}) {
  return createOutlineFloat({
    state: globalThis.state,
    api: globalThis.api,
    esc: globalThis.esc,
    ...overrides,
  })
}

beforeEach(() => {
  resetState()
  clearDocument()
  vi.clearAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("createOutlineFloat", () => {
  it("returns the public API", () => {
    const float = createTestFloat()
    expect(float.toggle).toBeTypeOf("function")
    expect(float.close).toBeTypeOf("function")
    expect(float.dispose).toBeTypeOf("function")
  })

  it("loads and renders outline threads when opening panel", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 2
    api.outline.listThreads.mockResolvedValue({
      items: [
        { id: "t1", title: "主线", chapter_ids: ["1", "2", "3"] },
        { id: "t2", title: "支线", chapter_ids: ["2"] },
      ],
    })
    document.body.innerHTML = '<div id="outline-float-panel" class="hidden"><div id="outline-float-body"></div></div>'

    const float = createTestFloat()
    await float.toggle()

    const body = document.getElementById("outline-float-body")
    expect(body.innerHTML).toContain("主线")
    expect(body.innerHTML).toContain("支线")
    expect(body.innerHTML).toContain('data-chapter="2"')
    expect(body.innerHTML).toContain("current")
  })

  it("closes already open panel", async () => {
    state.currentProjectId = "p1"
    document.body.innerHTML = '<div id="outline-float-panel"><div id="outline-float-body"></div></div>'

    const float = createTestFloat()
    await float.toggle()

    expect(document.getElementById("outline-float-panel").classList.contains("hidden")).toBe(true)
    expect(document.body.classList.contains("outline-float-open")).toBe(false)
  })

  it("renders empty state when no threads", async () => {
    state.currentProjectId = "p1"
    api.outline.listThreads.mockResolvedValue({ items: [] })
    document.body.innerHTML = '<div id="outline-float-panel" class="hidden"><div id="outline-float-body"></div></div>'

    const float = createTestFloat()
    await float.toggle()

    expect(document.getElementById("outline-float-body").innerHTML).toContain("暂无大纲条目")
  })

  it("shows error state when load fails", async () => {
    state.currentProjectId = "p1"
    api.outline.listThreads.mockRejectedValue(new Error("fail"))
    document.body.innerHTML = '<div id="outline-float-panel" class="hidden"><div id="outline-float-body"></div></div>'

    const float = createTestFloat()
    await float.toggle()

    expect(document.getElementById("outline-float-body").innerHTML).toContain("大纲加载失败")
  })

  it("escapes dynamic thread titles", async () => {
    state.currentProjectId = "p1"
    state._currentChapter = 1
    api.outline.listThreads.mockResolvedValue({
      items: [{ id: "t1", title: "<script>", chapter_ids: ["1"] }],
    })
    document.body.innerHTML = '<div id="outline-float-panel" class="hidden"><div id="outline-float-body"></div></div>'

    const float = createTestFloat()
    await float.toggle()

    expect(document.getElementById("outline-float-body").innerHTML).toContain("&lt;script&gt;")
  })

  it("does nothing when panel element is missing", async () => {
    state.currentProjectId = "p1"
    const float = createTestFloat()
    await expect(float.toggle()).resolves.toBeUndefined()
    expect(float.close()).toBeUndefined()
  })

  it("disposes by closing panel", async () => {
    state.currentProjectId = "p1"
    document.body.innerHTML = '<div id="outline-float-panel"><div id="outline-float-body"></div></div>'
    const float = createTestFloat()
    float.dispose()
    expect(document.getElementById("outline-float-panel").classList.contains("hidden")).toBe(true)
  })
})
