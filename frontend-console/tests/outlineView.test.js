/**
 * outlineView 测试 — 核心生命周期和辅助方法
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import outlineView from "../views/outlineView.js"

beforeEach(() => {
  state.currentProjectId = null
  state.currentSubView = "scenes"
  outlineView._threads = []
  outlineView._arcs = []
  outlineView._scenes = []
  outlineView._foreshadowing = []
  outlineView._reveals = []
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

  it("加载 foreshadowing 子标签数据", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "foreshadowing"
    api.outline.listForeshadowing.mockResolvedValue({ items: [{ id: "f1", name: "隐藏神器" }] })

    await outlineView.onEnter()

    expect(outlineView._foreshadowing.length).toBe(1)
    expect(outlineView._foreshadowing[0].name).toBe("隐藏神器")
  })

  it("加载 reveals 子标签数据", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "reveals"
    api.outline.listReveals.mockResolvedValue({ items: [{ id: "r1", target_type: "entity" }] })

    await outlineView.onEnter()

    expect(outlineView._reveals.length).toBe(1)
    expect(outlineView._reveals[0].target_type).toBe("entity")
  })

  it("foreshadowing API 失败时降级为空列表", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "foreshadowing"
    api.outline.listForeshadowing.mockRejectedValue(new Error("fail"))

    await outlineView.onEnter()

    expect(outlineView._foreshadowing).toEqual([])
    expect(outlineView._loading).toBe(false)
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

  it("Foreshadowing 子标签包含伏笔文字", async () => {
    outlineView._loading = false
    state.currentSubView = "foreshadowing"
    state.currentProjectId = "p1"
    const html = await outlineView.render()
    expect(html).toContain("伏笔")
  })

  it("Reveals 子标签包含揭示文字", async () => {
    outlineView._loading = false
    state.currentSubView = "reveals"
    state.currentProjectId = "p1"
    const html = await outlineView.render()
    expect(html).toContain("揭示")
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

describe("helpers", () => {
  const originalOnEnter = outlineView.onEnter

  beforeEach(() => {
    outlineView.onEnter = vi.fn()
  })

  afterEach(() => {
    outlineView.onEnter = originalOnEnter
  })

  it("reorders scenes through the API", async () => {
    state.currentProjectId = "p1"
    outlineView._scenes = [{ id: "s1" }, { id: "s2" }]
    api.outline.reorderScenes.mockResolvedValue({ updated: 2, total: 2 })

    await outlineView._reorderScenes(["s2", "s1"])

    expect(api.outline.reorderScenes).toHaveBeenCalledWith("p1", ["s2", "s1"])
    expect(toast).toHaveBeenCalledWith("Scene 顺序已更新", "success")
    expect(router.refresh).toHaveBeenCalled()
  })

  it("generates structure from outline view", async () => {
    state.currentProjectId = "p1"
    api.outline.generate.mockResolvedValue({ plot_threads: [], outline_arcs: [] })

    const result = await outlineView._generateStructure(1, 5)

    expect(api.outline.generate).toHaveBeenCalledWith("p1", 1, 5)
    expect(toast).toHaveBeenCalledWith("结构生成完成", "success")
    expect(result).toEqual({ plot_threads: [], outline_arcs: [] })
  })

  it("reorders scenes up correctly", async () => {
    state.currentProjectId = "p1"
    outlineView._scenes = [
      { id: "s1", scene_index: 0 },
      { id: "s2", scene_index: 1 },
      { id: "s3", scene_index: 2 },
    ]
    api.outline.reorderScenes.mockResolvedValue({ updated: 3, total: 3 })

    await outlineView._moveSceneUp("s2")

    expect(api.outline.reorderScenes).toHaveBeenCalledWith("p1", ["s2", "s1", "s3"])
  })

  it("reorders scenes down correctly", async () => {
    state.currentProjectId = "p1"
    outlineView._scenes = [
      { id: "s1", scene_index: 0 },
      { id: "s2", scene_index: 1 },
      { id: "s3", scene_index: 2 },
    ]
    api.outline.reorderScenes.mockResolvedValue({ updated: 3, total: 3 })

    await outlineView._moveSceneDown("s2")

    expect(api.outline.reorderScenes).toHaveBeenCalledWith("p1", ["s1", "s3", "s2"])
  })

  it("reorder error shows toast", async () => {
    state.currentProjectId = "p1"
    outlineView._scenes = [{ id: "s1" }, { id: "s2" }]
    api.outline.reorderScenes.mockRejectedValue(new Error("network error"))

    await outlineView._reorderScenes(["s2", "s1"])

    expect(toast).toHaveBeenCalledWith("network error", "error")
  })

  it("generate structure error shows toast", async () => {
    state.currentProjectId = "p1"
    api.outline.generate.mockRejectedValue(new Error("llm fail"))

    await expect(outlineView._generateStructure(1, 5)).rejects.toThrow("llm fail")
    expect(toast).toHaveBeenCalledWith("llm fail", "error")
  })
})

describe("render buttons", () => {
  it("renders generate structure and move buttons", async () => {
    outlineView._loading = false
    state.currentSubView = "scenes"
    state.currentProjectId = "p1"
    outlineView._scenes = [
      { id: "s1", scene_index: 0, title: "A", narrative_tag: "hook", status: "draft", source: "manual" },
    ]
    const html = await outlineView.render()
    expect(html).toContain('data-action="generate-structure"')
    expect(html).toContain('data-action="move-scene-up"')
    expect(html).toContain('data-action="move-scene-down"')
  })
})

describe("_showGenerateStructureForm", () => {
  let capturedHandler

  beforeEach(() => {
    capturedHandler = null
    showModal.mockImplementation((title, html, buttons) => {
      capturedHandler = buttons[0]?.handler
    })
  })

  afterEach(() => {
    showModal.mockClear()
  })

  it("validates end chapter >= start chapter", async () => {
    outlineView._showGenerateStructureForm()
    expect(capturedHandler).toBeTruthy()

    document.getElementById = vi.fn((id) => {
      if (id === "generate-structure-start") return { value: "5" }
      if (id === "generate-structure-end") return { value: "3" }
      return null
    })
    outlineView._generateStructure = vi.fn()

    await capturedHandler()

    expect(toast).toHaveBeenCalledWith("结束章节不能小于起始章节", "warning")
    expect(outlineView._generateStructure).not.toHaveBeenCalled()
  })

  it("calls generate with valid range", async () => {
    outlineView._showGenerateStructureForm()
    expect(capturedHandler).toBeTruthy()

    document.getElementById = vi.fn((id) => {
      if (id === "generate-structure-start") return { value: "1" }
      if (id === "generate-structure-end") return { value: "5" }
      return null
    })
    outlineView._generateStructure = vi.fn()

    await capturedHandler()

    expect(outlineView._generateStructure).toHaveBeenCalledWith(1, 5)
  })
})
