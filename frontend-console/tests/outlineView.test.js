/**
 * outlineView 测试 — 核心生命周期和辅助方法
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import outlineView from "../views/outlineView.js"

beforeEach(() => {
  state.currentProjectId = null
  state.currentSubView = "scenes"
  outlineView._threads = []
  outlineView._arcs = []
  outlineView._scenes = []
  outlineView._loading = false
  vi.clearAllMocks()
})

describe("onEnter", () => {
  it("无项目时设 loading=false", async () => {
    await outlineView.onEnter()
    expect(outlineView._loading).toBe(false)
  })

  it("加载 threads 子标签数据", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "threads"
    api.outline.listThreads.mockResolvedValue({ items: [{ id: "t1", name: "剧情线A" }] })

    await outlineView.onEnter()

    expect(outlineView._threads.length).toBe(1)
    expect(outlineView._threads[0].name).toBe("剧情线A")
  })

  it("API 失败时降级为空列表", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "threads"
    api.outline.listThreads.mockRejectedValue(new Error("fail"))

    await outlineView.onEnter()

    expect(outlineView._threads).toEqual([])
    expect(outlineView._loading).toBe(false)
  })

  it("加载 scenes 子标签数据", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "scenes"
    // scenes subView also loads threads
    api.outline.listScenes.mockResolvedValue({ items: [{ id: "s1" }] })
    api.outline.listThreads.mockResolvedValue({ items: [] })

    await outlineView.onEnter()

    expect(outlineView._scenes.length).toBe(1)
  })
})

describe("render", () => {
  it("加载中显示加载提示", async () => {
    outlineView._loading = true
    const html = await outlineView.render()
    expect(html).toContain("加载中")
  })

  it("有 Scene 数据时渲染卡片", async () => {
    outlineView._loading = false
    state.currentSubView = "scenes"
    state.currentProjectId = "p1"
    outlineView._scenes = [{
      id: "s1", scene_index: 0, title: "开篇", narrative_tag: "hook",
      goal: "引入主角", core_conflict: "身份危机", status: "draft", source: "manual",
    }]
    const html = await outlineView.render()
    expect(html).toContain("开篇")
  })

  it("Threads 子标签渲染表格", async () => {
    outlineView._loading = false
    state.currentSubView = "threads"
    state.currentProjectId = "p1"
    outlineView._threads = [{ id: "t1", name: "主线A", thread_type: "main", summary: "desc" }]
    const html = await outlineView.render()
    expect(html).toContain("主线A")
  })
})

describe("_narrativeTagLabel", () => {
  it("返回正确的中文标签", () => {
    expect(outlineView._narrativeTagLabel("hook")).toBe("钩子")
    expect(outlineView._narrativeTagLabel("climax")).toBe("阶段高潮")
    expect(outlineView._narrativeTagLabel("draft")).toBe("草稿")
    expect(outlineView._narrativeTagLabel(null)).toBe("草稿")
    expect(outlineView._narrativeTagLabel("unknown")).toBe("unknown")
  })
})
