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

  it("renders foreshadowing and reveal create buttons and delete actions", async () => {
    outlineView._loading = false
    state.currentProjectId = "p1"

    state.currentSubView = "foreshadowing"
    outlineView._foreshadowing = [{
      id: "f1",
      name: "伏笔A",
      summary: "摘要",
      status: "planted",
      planned_seed_chapter: 3,
    }]
    let html = await outlineView.render()
    expect(html).toContain('data-action="create-foreshadowing"')
    expect(html).toContain('data-action="edit-foreshadowing"')
    expect(html).toContain('data-action="delete-foreshadowing"')
    expect(html).toContain("新建伏笔")

    state.currentSubView = "reveals"
    outlineView._reveals = [{
      id: "r1",
      target_type: "world_entity",
      secret_summary: "秘密",
      status: "planned",
      reveal_stages: [{ stage_index: 0, chapter_index: 1, reveal_content: "揭示" }],
    }]
    html = await outlineView.render()
    expect(html).toContain('data-action="create-reveal"')
    expect(html).toContain('data-action="edit-reveal"')
    expect(html).toContain('data-action="delete-reveal"')
    expect(html).toContain("新建揭示")
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
      if (id === "generate-structure-confirm") return { checked: false }
      return null
    })
    outlineView._generateStructure = vi.fn()

    await capturedHandler()

    expect(outlineView._generateStructure).toHaveBeenCalledWith(1, 5)
  })

  it("counts overlapping threads and arcs for a range", () => {
    const threads = [
      { id: "t1", start_chapter: 1, planned_payoff_chapter: 3 },
      { id: "t2", start_chapter: 6, planned_payoff_chapter: 10 },
      { id: "t3", start_chapter: null, planned_payoff_chapter: 2 },
    ]
    const arcs = [
      { id: "a1", start_chapter: 4, end_chapter: 8 },
      { id: "a2", start_chapter: 20, end_chapter: 30 },
    ]

    const threadCount = outlineView._countRangeOverlap(threads, 2, 5, "start_chapter", "planned_payoff_chapter")
    const arcCount = outlineView._countRangeOverlap(arcs, 2, 5, "start_chapter", "end_chapter")

    expect(threadCount).toBe(2)
    expect(arcCount).toBe(1)
  })

  it("blocks generate when overlap exists and not confirmed", async () => {
    outlineView._showGenerateStructureForm()
    outlineView._generateOverlap = { threadCount: 1, arcCount: 1, rangeKey: "1-5" }

    document.getElementById = vi.fn((id) => {
      if (id === "generate-structure-start") return { value: "1" }
      if (id === "generate-structure-end") return { value: "5" }
      if (id === "generate-structure-confirm") return { checked: false }
      return null
    })
    outlineView._generateStructure = vi.fn()

    await capturedHandler()

    expect(outlineView._generateStructure).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("目标范围已存在结构，请勾选确认后继续", "warning")
  })
})

describe("foreshadowing and reveal forms", () => {
  afterEach(() => {
    showModal.mockClear()
    confirmAction.mockClear()
  })

  it("creates foreshadowing through the API", async () => {
    state.currentProjectId = "p1"
    let handler
    showModal.mockImplementation((_title, _html, buttons) => {
      handler = buttons[0]?.handler
    })
    document.getElementById = vi.fn((id) => {
      if (id === "create-foreshadowing-description") return { value: "伏笔描述" }
      if (id === "create-foreshadowing-target-chapter") return { value: "3" }
      if (id === "create-foreshadowing-status") return { value: "planted" }
      return null
    })
    api.outline.createForeshadowing.mockResolvedValue({})

    outlineView._showCreateForeshadowingForm()
    await handler()

    expect(api.outline.createForeshadowing).toHaveBeenCalledWith("p1", {
      name: "伏笔描述",
      summary: "伏笔描述",
      planned_seed_chapter: 3,
      status: "planted",
    })
    expect(toast).toHaveBeenCalledWith("伏笔已创建", "success")
    expect(router.refresh).toHaveBeenCalled()
  })

  it("edits foreshadowing through the API", async () => {
    state.currentProjectId = "p1"
    outlineView._foreshadowing = [{
      id: "f1",
      name: "旧描述",
      summary: "旧描述",
      status: "planted",
      planned_seed_chapter: 2,
    }]
    let handler
    showModal.mockImplementation((_title, _html, buttons) => {
      handler = buttons[0]?.handler
    })
    document.getElementById = vi.fn((id) => {
      if (id === "edit-foreshadowing-description") return { value: "新描述" }
      if (id === "edit-foreshadowing-target-chapter") return { value: "5" }
      if (id === "edit-foreshadowing-status") return { value: "triggered" }
      return null
    })
    api.outline.updateForeshadowing.mockResolvedValue({})

    outlineView._editForeshadowing("f1")
    await handler()

    expect(api.outline.updateForeshadowing).toHaveBeenCalledWith("f1", "p1", {
      name: "新描述",
      summary: "新描述",
      planned_seed_chapter: 5,
      status: "triggered",
    })
    expect(toast).toHaveBeenCalledWith("伏笔已保存", "success")
  })

  it("creates reveal plans through the API", async () => {
    state.currentProjectId = "p1"
    let handler
    showModal.mockImplementation((_title, _html, buttons) => {
      handler = buttons[0]?.handler
    })
    document.getElementById = vi.fn((id) => {
      if (id === "create-reveal-description") return { value: "揭示秘密" }
      if (id === "create-reveal-chapter") return { value: "5" }
      if (id === "create-reveal-foreshadowing-id") return { value: "" }
      if (id === "create-reveal-status") return { value: "planned" }
      return null
    })
    api.outline.createReveal.mockResolvedValue({})

    outlineView._showCreateRevealForm()
    await handler()

    expect(api.outline.createReveal).toHaveBeenCalledWith("p1", {
      target_type: "world_entity",
      target_id: "00000000-0000-0000-0000-000000000000",
      secret_summary: "揭示秘密",
      reveal_stages: [{ stage_index: 0, chapter_index: 5, reveal_content: "揭示秘密" }],
      status: "planned",
    })
    expect(toast).toHaveBeenCalledWith("揭示已创建", "success")
    expect(router.refresh).toHaveBeenCalled()
  })

  it("edits reveal plans through the API", async () => {
    state.currentProjectId = "p1"
    outlineView._reveals = [{
      id: "r1",
      target_type: "world_entity",
      target_id: "entity-1",
      secret_summary: "旧秘密",
      status: "planned",
      reveal_stages: [{ stage_index: 0, chapter_index: 2, reveal_content: "旧秘密" }],
    }]
    let handler
    showModal.mockImplementation((_title, _html, buttons) => {
      handler = buttons[0]?.handler
    })
    document.getElementById = vi.fn((id) => {
      if (id === "edit-reveal-description") return { value: "新秘密" }
      if (id === "edit-reveal-chapter") return { value: "8" }
      if (id === "edit-reveal-foreshadowing-id") return { value: "" }
      if (id === "edit-reveal-status") return { value: "revealed" }
      return null
    })
    api.outline.updateReveal.mockResolvedValue({})

    outlineView._editReveal("r1")
    await handler()

    expect(api.outline.updateReveal).toHaveBeenCalledWith("r1", "p1", {
      secret_summary: "新秘密",
      reveal_stages: [{ stage_index: 0, chapter_index: 8, reveal_content: "新秘密" }],
      status: "revealed",
    })
    expect(toast).toHaveBeenCalledWith("揭示已保存", "success")
  })

  it("deletes foreshadowing and reveal plans through confirmation", async () => {
    state.currentProjectId = "p1"
    confirmAction.mockImplementation((_message, onConfirm) => onConfirm())
    api.outline.deleteForeshadowing.mockResolvedValue(null)
    api.outline.deleteReveal.mockResolvedValue(null)

    await outlineView._deleteForeshadowing("f1")
    await outlineView._deleteReveal("r1")

    expect(confirmAction).toHaveBeenCalledWith("确定删除此伏笔？", expect.any(Function))
    expect(confirmAction).toHaveBeenCalledWith("确定删除此揭示？", expect.any(Function))
    expect(api.outline.deleteForeshadowing).toHaveBeenCalledWith("f1", "p1")
    expect(api.outline.deleteReveal).toHaveBeenCalledWith("r1", "p1")
    expect(router.refresh).toHaveBeenCalled()
  })
})
