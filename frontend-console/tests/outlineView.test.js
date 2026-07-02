/**
 * outlineView 测试 — 核心生命周期和辅助方法
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import outlineView from "../views/outlineView.js"
import { resetState, clearDocument, captureModalHandler, autoConfirm } from "./helpers.js"

beforeEach(() => {
  resetState({ currentSubView: "scenes" })
  outlineView._threads = []
  outlineView._arcs = []
  outlineView._scenes = []
  outlineView._foreshadowing = []
  outlineView._reveals = []
  outlineView._loading = false
  outlineView._structureFilters = {}
  outlineView._plotAutoExtractTaskId = null
  outlineView._plotAutoExtractProgress = null
  outlineView._plotAutoExtractPoller = null
  outlineView._plotAutoExtractMeta = null
  vi.clearAllMocks()
})

describe("outlineView onEnter", () => {
  it("无项目时设 loading=false", async () => {
    await outlineView.onEnter()
    expect(outlineView._loading).toBe(false)
  })

  it.each([
    {
      name: "threads",
      subView: "threads",
      apiName: "listThreads",
      mockResolved: { items: [{ id: "t1", name: "剧情线A" }] },
      store: "_threads",
      assertion: (items) => {
        expect(items.length).toBe(1)
        expect(items[0].name).toBe("剧情线A")
      },
    },
    {
      name: "foreshadowing",
      subView: "foreshadowing",
      apiName: "listForeshadowing",
      mockResolved: { items: [{ id: "f1", name: "隐藏神器" }] },
      store: "_foreshadowing",
      assertion: (items) => {
        expect(items.length).toBe(1)
        expect(items[0].name).toBe("隐藏神器")
      },
    },
    {
      name: "reveals",
      subView: "reveals",
      apiName: "listReveals",
      mockResolved: { items: [{ id: "r1", target_type: "entity" }] },
      store: "_reveals",
      assertion: (items) => {
        expect(items.length).toBe(1)
        expect(items[0].target_type).toBe("entity")
      },
    },
  ])("加载 $name 子标签数据", async ({ subView, apiName, mockResolved, store, assertion }) => {
    state.currentProjectId = "p1"
    state.currentSubView = subView
    api.outline[apiName].mockResolvedValue(mockResolved)

    await outlineView.onEnter()

    assertion(outlineView[store])
  })

  it.each([
    { name: "threads", subView: "threads", apiName: "listThreads", store: "_threads" },
    { name: "foreshadowing", subView: "foreshadowing", apiName: "listForeshadowing", store: "_foreshadowing" },
  ])("$name API 失败时降级为空列表", async ({ subView, apiName, store }) => {
    state.currentProjectId = "p1"
    state.currentSubView = subView
    api.outline[apiName].mockRejectedValue(new Error("fail"))

    await outlineView.onEnter()

    expect(outlineView[store]).toEqual([])
    expect(outlineView._loading).toBe(false)
  })

  it("scenes 子标签不再加载旧 Scene 管理数据", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "scenes"
    api.outline.listThreads.mockResolvedValue({ items: [] })

    await outlineView.onEnter()

    expect(api.outline.listScenes).not.toHaveBeenCalled()
    expect(outlineView._scenes.length).toBe(0)
  })

  it("加载结构资产时传递当前页签筛选参数", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "threads"
    outlineView._structureFilters.threads = {
      status: "deprecated",
      source: "deep_import",
      workflow_id: "wf-1",
      needs_review: "true",
      skip: 0,
      limit: 50,
    }
    api.outline.listThreads.mockResolvedValue({ items: [] })

    await outlineView.onEnter()

    expect(api.outline.listThreads).toHaveBeenCalledWith("p1", {
      status: "deprecated",
      source: "deep_import",
      workflow_id: "wf-1",
      needs_review: true,
      skip: 0,
      limit: 50,
    })
  })
})

describe("outlineView 批量操作", () => {
  beforeEach(() => {
    state.currentProjectId = "p1"
    outlineView._bulkSelections = {}
  })

  it("批量删除剧情线调用现有单项 API", async () => {
    outlineView._threads = [{ id: "t1", name: "主线" }, { id: "t2", name: "支线" }]
    outlineView._bulkSelections["outline-threads"] = new Set(["t1", "t2"])
    api.outline.deleteThread.mockResolvedValue(null)

    await outlineView._executeBulkAction("outline-threads", "delete-threads", outlineView._itemsForBulkScope("outline-threads"))

    expect(api.outline.deleteThread).toHaveBeenCalledWith("t1", "p1")
    expect(api.outline.deleteThread).toHaveBeenCalledWith("t2", "p1")
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("成功 2 / 2"), "success")
  })

  it("批量删除伏笔调用 deleteForeshadowing", async () => {
    outlineView._foreshadowing = [{ id: "f1", summary: "伏笔" }]
    outlineView._bulkSelections["outline-foreshadowing"] = new Set(["f1"])
    api.outline.deleteForeshadowing.mockResolvedValue(null)

    await outlineView._executeBulkAction("outline-foreshadowing", "delete-foreshadowing", outlineView._itemsForBulkScope("outline-foreshadowing"))

    expect(api.outline.deleteForeshadowing).toHaveBeenCalledWith("f1", "p1")
  })
})

describe("outlineView render", () => {
  it("加载中显示加载提示", async () => {
    outlineView._loading = true
    const html = await outlineView.render()
    expect(html).toContain("加载中")
  })

  it("scenes 子标签渲染场景工作台跳转页", async () => {
    outlineView._loading = false
    state.currentSubView = "scenes"
    state.currentProjectId = "p1"
    const html = await outlineView.render()
    expect(html).toContain("场景工作台")
    expect(html).not.toContain(">场景卡<")
    expect(html).toContain("data-action=\"open-scene-workbench\"")
  })

  it.each([
    { name: "Threads", subView: "threads", store: "_threads", data: [{ id: "t1", name: "主线A", thread_type: "main", summary: "desc" }], expected: "主线A" },
    { name: "Foreshadowing", subView: "foreshadowing", store: "_foreshadowing", data: [{ id: "f1", name: "伏笔A", summary: "摘要", status: "planted", planned_seed_chapter: 3 }], expected: "伏笔" },
    { name: "Reveals", subView: "reveals", store: "_reveals", data: [{ id: "r1", target_type: "world_entity", secret_summary: "秘密", status: "planned", reveal_stages: [{ stage_index: 0, chapter_index: 1, reveal_content: "揭示" }] }], expected: "揭示" },
  ])("$name 子标签渲染对应内容", async ({ subView, store, data, expected }) => {
    outlineView._loading = false
    state.currentSubView = subView
    state.currentProjectId = "p1"
    outlineView[store] = data
    const html = await outlineView.render()
    expect(html).toContain(expected)
  })

  it("结构资产列表显示深度导入和需复核标记", async () => {
    outlineView._loading = false
    state.currentSubView = "threads"
    state.currentProjectId = "p1"
    outlineView._threads = [{
      id: "t1",
      name: "主线A",
      thread_type: "main",
      status: "candidate",
      provenance_meta: {
        source: "deep_import",
        workflow_id: "wf-1",
        needs_review: true,
        phase: "structure_analysis",
      },
    }]

    const html = await outlineView.render()

    expect(html).toContain("深度导入")
    expect(html).toContain("需复核")
    expect(html).toContain("structure_analysis")
  })

  it("深度导入筛选为空时显示结构分析不完整提示", async () => {
    outlineView._loading = false
    state.currentSubView = "threads"
    state.currentProjectId = "p1"
    outlineView._threads = []
    outlineView._structureFilters.threads = {
      ...outlineView._structureFilterFor("threads"),
      source: "deep_import",
    }

    const html = await outlineView.render()

    expect(html).toContain("结构分析不完整")
    expect(html).toContain("可重新分析")
  })
})

describe("structure asset filters", () => {
  it("应用筛选后刷新当前页签", () => {
    state.currentSubView = "threads"
    document.body.innerHTML = `
      <select id="outline-filter-status"><option value="deprecated" selected>废弃</option></select>
      <select id="outline-filter-source"><option value="deep_import" selected>深度导入</option></select>
      <input id="outline-filter-workflow-id" value="wf-1" />
      <select id="outline-filter-needs-review"><option value="true" selected>需复核</option></select>
    `

    outlineView._applyStructureFilters()

    expect(outlineView._structureFilters.threads).toMatchObject({
      status: "deprecated",
      source: "deep_import",
      workflow_id: "wf-1",
      needs_review: "true",
      skip: 0,
    })
    expect(router.refresh).toHaveBeenCalled()
  })

  it("重置筛选后刷新当前页签", () => {
    state.currentSubView = "threads"
    outlineView._structureFilters.threads = {
      status: "deprecated",
      source: "deep_import",
      workflow_id: "wf-1",
      needs_review: "true",
      skip: 0,
      limit: 50,
    }

    outlineView._resetStructureFilters()

    expect(outlineView._structureFilters.threads).toMatchObject({
      status: "",
      source: "",
      workflow_id: "",
      needs_review: "",
      skip: 0,
      limit: 50,
    })
    expect(router.refresh).toHaveBeenCalled()
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
    document.body.innerHTML = `
      <div id="modal-overlay" class="hidden">
        <div id="modal-title"></div>
        <div id="modal-body"></div>
        <div id="modal-footer"></div>
      </div>
    `
    api.context.confirm.mockResolvedValue({ id: "confirm-1", selected_asset_ids: {}, warnings: [] })
    api.outline.generate.mockResolvedValue({ task_id: "task-1", status: "pending" })

    const promise = outlineView._generateStructure(1, 5)
    await Promise.resolve()
    document.querySelectorAll("#modal-footer button")[1].click()
    const result = await promise

    expect(api.outline.generate).toHaveBeenCalledWith({
      novel_id: "p1",
      context_confirmation_id: "confirm-1",
      start_chapter: 1,
      end_chapter: 5,
    })
    expect(toast).toHaveBeenCalledWith("剧情结构生成任务已提交", "success")
    expect(result).toEqual({ task_id: "task-1", status: "pending" })
  })

  it("submits plot structure auto extraction stage task", async () => {
    state.currentProjectId = "p1"
    api.imports.startStage.mockResolvedValue({ task_id: "plot-task" })
    outlineView._showPlotStructureAutoExtractForm()
    document.body.innerHTML += `
      <input id="plot-auto-extract-start" value="2" />
      <input id="plot-auto-extract-end" value="8" />
    `

    await captureModalHandler()()

    expect(api.imports.startStage).toHaveBeenCalledWith(
      "plot_structure",
      "p1",
      2,
      8,
    )
    expect(api.outline.generate).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(
      "剧情线自动提取任务已提交：plot-task",
      "success",
    )
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

  it.each([
    {
      name: "reorder",
      setup: () => { outlineView._scenes = [{ id: "s1" }, { id: "s2" }] },
      mockApi: () => api.outline.reorderScenes.mockRejectedValue(new Error("network error")),
      call: () => outlineView._reorderScenes(["s2", "s1"]),
      expectedError: "network error",
    },
    {
      name: "generate structure",
      setup: () => {
        document.body.innerHTML = `
          <div id="modal-overlay" class="hidden">
            <div id="modal-title"></div>
            <div id="modal-body"></div>
            <div id="modal-footer"></div>
          </div>
        `
        api.context.confirm.mockResolvedValue({ id: "confirm-1", selected_asset_ids: {}, warnings: [] })
      },
      mockApi: () => api.outline.generate.mockRejectedValue(new Error("llm fail")),
      call: async () => {
        const promise = outlineView._generateStructure(1, 5)
        await Promise.resolve()
        document.querySelectorAll("#modal-footer button")[1].click()
        return promise
      },
      expectedError: "llm fail",
      rejects: true,
    },
  ])("$name error shows toast", async ({ setup, mockApi, call, expectedError, rejects }) => {
    state.currentProjectId = "p1"
    setup()
    mockApi()
    if (rejects) {
      await expect(call()).rejects.toThrow(expectedError)
    } else {
      await call()
    }
    expect(toast).toHaveBeenCalledWith(expectedError, "error")
  })
})

describe("render buttons", () => {
  it("renders plot structure auto extraction action on thread view", async () => {
    outlineView._loading = false
    state.currentSubView = "threads"
    state.currentProjectId = "p1"

    const html = await outlineView.render()

    expect(html).toContain("剧情线自动提取")
    expect(html).toContain('data-action="plot-structure-auto-extract"')
  })

  it("renders scene workbench jump instead of legacy scene management buttons", async () => {
    outlineView._loading = false
    state.currentSubView = "scenes"
    state.currentProjectId = "p1"
    const html = await outlineView.render()
    expect(html).toContain('data-action="open-scene-workbench"')
    expect(html).not.toContain('data-action="generate-structure"')
    expect(html).not.toContain('data-action="move-scene-up"')
    expect(html).not.toContain('data-action="move-scene-down"')
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
  it("validates end chapter >= start chapter", async () => {
    outlineView._showGenerateStructureForm()
    const handler = captureModalHandler()
    expect(handler).toBeTruthy()

    document.getElementById = vi.fn((id) => {
      if (id === "generate-structure-start") return { value: "5", addEventListener: vi.fn() }
      if (id === "generate-structure-end") return { value: "3", addEventListener: vi.fn() }
      if (id === "generate-structure-warning") return { style: {}, innerHTML: "", addEventListener: vi.fn() }
      if (id === "generate-structure-confirm-row") return { style: {}, addEventListener: vi.fn() }
      return { addEventListener: vi.fn() }
    })
    outlineView._generateStructure = vi.fn()

    await handler()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(toast).toHaveBeenCalledWith("结束章节不能小于起始章节", "warning")
    expect(outlineView._generateStructure).not.toHaveBeenCalled()
  })

  it("calls generate with valid range", async () => {
    outlineView._showGenerateStructureForm()
    const handler = captureModalHandler()
    expect(handler).toBeTruthy()

    document.getElementById = vi.fn((id) => {
      if (id === "generate-structure-start") return { value: "1", addEventListener: vi.fn() }
      if (id === "generate-structure-end") return { value: "5", addEventListener: vi.fn() }
      if (id === "generate-structure-confirm") return { checked: false, addEventListener: vi.fn() }
      if (id === "generate-structure-warning") return { style: {}, innerHTML: "", addEventListener: vi.fn() }
      if (id === "generate-structure-confirm-row") return { style: {}, addEventListener: vi.fn() }
      return { addEventListener: vi.fn() }
    })
    outlineView._generateStructure = vi.fn()

    await handler()
    await new Promise((resolve) => setTimeout(resolve, 0))

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
      if (id === "generate-structure-start") return { value: "1", addEventListener: vi.fn() }
      if (id === "generate-structure-end") return { value: "5", addEventListener: vi.fn() }
      if (id === "generate-structure-confirm") return { checked: false, addEventListener: vi.fn() }
      if (id === "generate-structure-warning") return { style: {}, innerHTML: "", addEventListener: vi.fn() }
      if (id === "generate-structure-confirm-row") return { style: {}, addEventListener: vi.fn() }
      return { addEventListener: vi.fn() }
    })
    outlineView._generateStructure = vi.fn()

    await captureModalHandler()()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(outlineView._generateStructure).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("目标范围已存在结构，请勾选确认后继续", "warning")
  })
})

describe("foreshadowing and reveal forms", () => {
  afterEach(() => {
    showModal.mockClear()
    confirmAction.mockClear()
  })

  it.each([
    {
      name: "creates foreshadowing",
      setup: () => {},
      open: () => outlineView._showCreateForeshadowingForm(),
      values: {
        "create-foreshadowing-description": "伏笔描述",
        "create-foreshadowing-target-chapter": "3",
        "create-foreshadowing-status": "planted",
      },
      apiName: "createForeshadowing",
      mockApi: () => api.outline.createForeshadowing.mockResolvedValue({}),
      expectedCall: ["p1", { name: "伏笔描述", summary: "伏笔描述", planned_seed_chapter: 3, status: "planted" }],
      expectedToast: ["伏笔已创建", "success"],
      refresh: true,
    },
    {
      name: "edits foreshadowing",
      setup: () => {
        outlineView._foreshadowing = [{
          id: "f1", name: "旧描述", summary: "旧描述", status: "planted", planned_seed_chapter: 2,
        }]
      },
      open: () => outlineView._editForeshadowing("f1"),
      values: {
        "edit-foreshadowing-description": "新描述",
        "edit-foreshadowing-target-chapter": "5",
        "edit-foreshadowing-status": "triggered",
      },
      apiName: "updateForeshadowing",
      mockApi: () => api.outline.updateForeshadowing.mockResolvedValue({}),
      expectedCall: ["f1", "p1", { name: "新描述", summary: "新描述", planned_seed_chapter: 5, status: "triggered" }],
      expectedToast: ["伏笔已保存", "success"],
    },
    {
      name: "creates reveal plans",
      setup: () => {},
      open: () => outlineView._showCreateRevealForm(),
      values: {
        "create-reveal-description": "揭示秘密",
        "create-reveal-chapter": "5",
        "create-reveal-foreshadowing-id": "",
        "create-reveal-status": "planned",
      },
      apiName: "createReveal",
      mockApi: () => api.outline.createReveal.mockResolvedValue({}),
      expectedCall: ["p1", {
        target_type: "world_entity",
        target_id: "00000000-0000-0000-0000-000000000000",
        secret_summary: "揭示秘密",
        reveal_stages: [{ stage_index: 0, chapter_index: 5, reveal_content: "揭示秘密" }],
        status: "planned",
      }],
      expectedToast: ["揭示已创建", "success"],
      refresh: true,
    },
    {
      name: "edits reveal plans",
      setup: () => {
        outlineView._reveals = [{
          id: "r1", target_type: "world_entity", target_id: "entity-1",
          secret_summary: "旧秘密", status: "planned",
          reveal_stages: [{ stage_index: 0, chapter_index: 2, reveal_content: "旧秘密" }],
        }]
      },
      open: () => outlineView._editReveal("r1"),
      values: {
        "edit-reveal-description": "新秘密",
        "edit-reveal-chapter": "8",
        "edit-reveal-foreshadowing-id": "",
        "edit-reveal-status": "revealed",
      },
      apiName: "updateReveal",
      mockApi: () => api.outline.updateReveal.mockResolvedValue({}),
      expectedCall: ["r1", "p1", {
        secret_summary: "新秘密",
        reveal_stages: [{ stage_index: 0, chapter_index: 8, reveal_content: "新秘密" }],
        status: "revealed",
      }],
      expectedToast: ["揭示已保存", "success"],
    },
  ])("$name through the API", async ({ setup, open, values, mockApi, apiName, expectedCall, expectedToast, refresh }) => {
    state.currentProjectId = "p1"
    setup()
    mockApi()
    open()
    const handler = captureModalHandler()
    document.getElementById = vi.fn((id) => ({ value: values[id] ?? "", addEventListener: vi.fn() }))
    await handler()
    expect(api.outline[apiName]).toHaveBeenCalledWith(...expectedCall)
    expect(toast).toHaveBeenCalledWith(...expectedToast)
    if (refresh) {
      expect(router.refresh).toHaveBeenCalled()
    }
  })

  it.each([
    {
      name: "foreshadowing",
      deleteFn: (id) => outlineView._deleteForeshadowing(id),
      apiName: "deleteForeshadowing",
      confirmMessage: "确定删除此伏笔？",
      id: "f1",
    },
    {
      name: "reveal",
      deleteFn: (id) => outlineView._deleteReveal(id),
      apiName: "deleteReveal",
      confirmMessage: "确定删除此揭示？",
      id: "r1",
    },
  ])("deletes $name plan through confirmation", async ({ name, deleteFn, apiName, confirmMessage, id }) => {
    state.currentProjectId = "p1"
    autoConfirm()
    api.outline[apiName].mockResolvedValue(null)

    await deleteFn(id)

    expect(confirmAction).toHaveBeenCalledWith(confirmMessage, expect.any(Function))
    expect(api.outline[apiName]).toHaveBeenCalledWith(id, "p1")
    expect(router.refresh).toHaveBeenCalled()
  })
})
