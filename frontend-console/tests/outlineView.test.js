/**
 * outlineView 测试 — 核心生命周期和辅助方法
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import outlineView from "../views/outlineView.js"
import sceneWorkbenchView from "../views/sceneWorkbenchView.js"
import {
  normalizeTaskProgress,
  persistActiveWorkflow,
  recoverActiveWorkflows,
} from "../shared/workflowProgress.js"
import { resetState, clearDocument, captureModalHandler, autoConfirm } from "./helpers.js"

beforeEach(() => {
  outlineView._stopOutlineGeneratePolling?.()
  outlineView._stopOutlineAnalysisPolling?.()
  clearDocument()
  localStorage.clear()
  resetState({ currentSubView: "scenes" })
  outlineView._threads = []
  outlineView._arcs = []
  outlineView._scenes = []
  outlineView._foreshadowing = []
  outlineView._reveals = []
  outlineView._unassignedForeshadowing = []
  outlineView._unassignedReveals = []
  outlineView._loading = false
  outlineView._structureFilters = {}
  outlineView._structureTotals = {
    threads: 0,
    arcs: 0,
    foreshadowing: 0,
    reveals: 0,
  }
  outlineView._structureLoadErrors = {}
  outlineView._structureLoadRequestId = 0
  outlineView._plotAutoExtractTaskId = null
  outlineView._plotAutoExtractProgress = null
  outlineView._plotAutoExtractPoller = null
  outlineView._plotAutoExtractMeta = null
  outlineView._outlineGenerateTaskId = null
  outlineView._outlineGenerateProgress = null
  outlineView._outlineGeneratePoller = null
  outlineView._outlineGenerateMeta = null
  outlineView._outlineGeneratePreview = null
  outlineView._outlineAnalysisTaskId = null
  outlineView._outlineAnalysisProgress = null
  outlineView._outlineAnalysisPoller = null
  outlineView._outlineAnalysisMeta = null
  outlineView._outlineAnalysisResult = null
  outlineView._outlineAnalysisCancelPending = false
  outlineView._outlineAnalysisSubmitting = false
  outlineView._sceneWorkbenchActive = false
  sceneWorkbenchView._loading = false
  sceneWorkbenchView._workbench = { total: 0, health: {}, unassigned_chapters: [], items: [] }
  sceneWorkbenchView._total = 0
  sceneWorkbenchView._selectedSceneIdValue = null
  vi.clearAllMocks()
  api.outline.listForeshadowing.mockReset().mockResolvedValue({ items: [], total: 0 })
  api.outline.listReveals.mockReset().mockResolvedValue({ items: [], total: 0 })
  api.outline.getStoryOutline.mockReset().mockResolvedValue({
    current_revision_id: "so-1",
    revision: { id: "so-1" },
  })
})

afterEach(() => {
  outlineView._stopOutlineGeneratePolling?.()
  outlineView._stopOutlineAnalysisPolling?.()
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
  ])("加载 $name 子标签数据", async ({ subView, apiName, mockResolved, store, assertion }) => {
    state.currentProjectId = "p1"
    state.currentSubView = subView
    api.outline[apiName].mockResolvedValue(mockResolved)

    await outlineView.onEnter()

    assertion(outlineView[store])
  })

  it.each([
    { name: "threads", subView: "threads", apiName: "listThreads", store: "_threads" },
    { name: "arcs", subView: "arcs", apiName: "listArcs", store: "_arcs" },
  ])("$name API 失败时保留可见错误状态", async ({ subView, apiName, store }) => {
    state.currentProjectId = "p1"
    state.currentSubView = subView
    api.outline[apiName].mockRejectedValue(new Error("加载失败 <script>"))

    await outlineView.onEnter()

    expect(outlineView[store]).toEqual([])
    expect(outlineView._loading).toBe(false)
    expect(outlineView._structureLoadErrors[subView]).toBe("加载失败 <script>")
    const html = await outlineView.render()
    expect(html).toContain("加载失败")
    expect(html).toContain("&lt;script&gt;")
    expect(html).not.toContain("<script>")
    expect(html).toContain('data-action="retry-outline-load"')
  })

  it("较早的失败请求晚到时不会覆盖较新的成功结果", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "threads"
    let rejectFirst
    let resolveSecond
    api.outline.listThreads
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectFirst = reject }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve }))

    const firstLoad = outlineView.onEnter()
    const secondLoad = outlineView.onEnter()
    resolveSecond({ items: [{ id: "new", name: "最新结果" }] })
    await secondLoad
    rejectFirst(new Error("过期请求失败"))
    await firstLoad

    expect(outlineView._threads).toEqual([{ id: "new", name: "最新结果" }])
    expect(outlineView._structureLoadErrors.threads).toBeUndefined()
    expect(outlineView._loading).toBe(false)
  })

  it("scenes 子标签直接加载 Scene 工作台", async () => {
    state.currentProjectId = "p1"
    state.currentView = "outline"
    state.currentSubView = "scenes"
    api.outline.getSceneWorkbench.mockResolvedValue({ total: 0, health: {}, items: [] })

    await outlineView.onEnter()

    expect(api.outline.listScenes).not.toHaveBeenCalled()
    expect(api.outline.listThreads).not.toHaveBeenCalled()
    expect(api.outline.getSceneWorkbench).toHaveBeenCalledWith("p1", null, expect.any(Object))
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

  it("剧情线页按后端上限分页加载全部伏笔与揭示", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "threads"
    const firstPage = Array.from({ length: 50 }, (_, index) => ({ id: `f-${index}` }))
    api.outline.listForeshadowing.mockImplementation((_projectId, params) => {
      if (params.unassigned) return Promise.resolve({ items: [{ id: "f-u" }], total: 1 })
      if (params.skip === 0) return Promise.resolve({ items: firstPage, total: 51 })
      return Promise.resolve({ items: [{ id: "f-50" }], total: 51 })
    })
    api.outline.listReveals.mockImplementation((_projectId, params) => {
      if (params.unassigned) return Promise.resolve({ items: [{ id: "r-u" }], total: 1 })
      return Promise.resolve({ items: [{ id: "r-0" }], total: 1 })
    })

    await outlineView.onEnter()

    expect(outlineView._foreshadowing).toHaveLength(51)
    expect(outlineView._unassignedForeshadowing).toEqual([{ id: "f-u" }])
    expect(outlineView._reveals).toEqual([{ id: "r-0" }])
    expect(outlineView._unassignedReveals).toEqual([{ id: "r-u" }])
    expect(api.outline.listForeshadowing).toHaveBeenCalledWith("p1", {
      skip: 50,
      limit: 50,
    })
    for (const [, params] of [
      ...api.outline.listForeshadowing.mock.calls,
      ...api.outline.listReveals.mock.calls,
    ]) {
      expect(params.limit).toBeLessThanOrEqual(50)
    }
  })

  it.each([
    { subView: "threads", apiName: "listThreads", store: "_threads", totalKey: "threads" },
    { subView: "arcs", apiName: "listArcs", store: "_arcs", totalKey: "arcs" },
  ])("直接采用 $subView 服务端分页 items 和 total", async ({ subView, apiName, store, totalKey }) => {
    state.currentProjectId = "p1"
    state.currentSubView = subView
    const serverItems = [
      { id: "active", status: "draft" },
      { id: "server-history", status: "deprecated" },
    ]
    api.outline[apiName].mockResolvedValue({ items: serverItems, total: 17 })

    await outlineView.onEnter()

    expect(outlineView[store]).toEqual(serverItems)
    expect(outlineView._structureTotals[totalKey]).toBe(17)
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

  it("批量复核剧情线保留 provenance_meta 并标记已复核", async () => {
    outlineView._threads = [
      { id: "t1", name: "主线", status: "candidate", provenance_meta: { source: "deep_import", needs_review: true } },
    ]
    outlineView._bulkSelections["outline-threads"] = new Set(["t1"])
    api.outline.updateThread.mockResolvedValue({})
    api.outline.listThreads.mockResolvedValue({ items: outlineView._threads, total: 1 })

    await outlineView._executeBulkAction("outline-threads", "review-threads", outlineView._itemsForBulkScope("outline-threads"))

    expect(api.outline.updateThread).toHaveBeenCalledWith("t1", "p1", {
      status: "canonical",
      provenance_meta: expect.objectContaining({
        source: "deep_import",
        needs_review: false,
        reviewed_at: expect.any(String),
        reviewed_by: "manual",
        reviewed_from: "outline_threads_bulk",
        review_previous_status: "candidate",
      }),
    })
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("成功 1 / 1"), "success")
  })

  it("批量采用篇章纲写入 canonical 与人工复核来源", async () => {
    outlineView._arcs = [
      { id: "a1", title: "第一篇章", status: "draft", provenance_meta: { source: "ai_generated" } },
    ]
    outlineView._bulkSelections["outline-arcs"] = new Set(["a1"])
    api.outline.updateArc.mockResolvedValue({})
    api.outline.listArcs.mockResolvedValue({ items: outlineView._arcs, total: 1 })

    await outlineView._executeBulkAction("outline-arcs", "review-arcs", outlineView._itemsForBulkScope("outline-arcs"))

    expect(api.outline.updateArc).toHaveBeenCalledWith("a1", "p1", {
      status: "canonical",
      provenance_meta: expect.objectContaining({
        source: "ai_generated",
        needs_review: false,
        reviewed_at: expect.any(String),
        reviewed_by: "manual",
        reviewed_from: "outline_arcs_bulk",
        review_previous_status: "draft",
      }),
    })
  })

  it("批量采用剧情线确认按钮不使用删除文案", () => {
    outlineView._threads = [{ id: "t1", name: "主线" }]
    outlineView._bulkSelections["outline-threads"] = new Set(["t1"])

    outlineView._runBulkAction("outline-threads", "review-threads")

    expect(confirmAction).toHaveBeenCalledWith(
      "确定对选中的 1 项执行「批量采用 / 标记已检查」吗？",
      expect.any(Function),
      "确认处理",
    )
  })

  it("批量删除伏笔调用 deleteForeshadowing", async () => {
    outlineView._foreshadowing = [{ id: "f1", summary: "伏笔" }]
    outlineView._bulkSelections["outline-foreshadowing"] = new Set(["f1"])
    api.outline.deleteForeshadowing.mockResolvedValue(null)

    await outlineView._executeBulkAction("outline-foreshadowing", "delete-foreshadowing", outlineView._itemsForBulkScope("outline-foreshadowing"))

    expect(api.outline.deleteForeshadowing).toHaveBeenCalledWith("f1", "p1")
  })

  it("点击剧情线多选不重绘页面也不强制刷新数据", () => {
    const input = document.createElement("input")
    input.setAttribute("data-scope", "outline-threads")
    input.setAttribute("data-id", "t1")
    input.checked = true

    outlineView._toggleBulkOne(input)

    expect(outlineView._bulkSelections["outline-threads"]).toEqual(new Set(["t1"]))
    expect(router.renderCurrentView).not.toHaveBeenCalled()
    expect(router.refresh).not.toHaveBeenCalled()
  })
})

describe("outlineView render", () => {
  it("子导航只保留小说总纲、篇章纲、剧情线和 Scene", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "threads"
    outlineView._loading = false

    const html = await outlineView.render()

    const storyIndex = html.indexOf('data-action="nav-story-outline"')
    const arcIndex = html.indexOf('data-action="nav-arcs"')
    const threadIndex = html.indexOf('data-action="nav-threads"')
    const sceneIndex = html.indexOf('data-action="nav-scenes"')
    expect(storyIndex).toBeGreaterThanOrEqual(0)
    expect(storyIndex).toBeLessThan(arcIndex)
    expect(arcIndex).toBeLessThan(threadIndex)
    expect(threadIndex).toBeLessThan(sceneIndex)
    expect(html).not.toContain('data-action="nav-foreshadowing"')
    expect(html).not.toContain('data-action="nav-reveals"')
  })

  it("加载中显示加载提示", async () => {
    outlineView._loading = true
    state.currentSubView = "threads"
    const html = await outlineView.render()
    expect(html).toContain("大纲数据加载中")
    expect(html).toContain('class="loading-skeleton"')
    expect(html).toContain('role="status"')
  })

  it.each([
    { subView: "threads", apiName: "listThreads", store: "_threads", item: { id: "t1", name: "剧情线" } },
    { subView: "arcs", apiName: "listArcs", store: "_arcs", item: { id: "a1", title: "篇章纲" } },
  ])("$subView 加载失败后可通过按钮真实重新请求并恢复", async ({ subView, apiName, store, item }) => {
    state.currentProjectId = "p1"
    state.currentSubView = subView
    outlineView._structureLoadErrors[subView] = "网络暂时不可用"
    api.outline[apiName].mockResolvedValue({ items: [item] })
    let refreshPromise
    router.refresh.mockImplementation(() => {
      refreshPromise = outlineView.onEnter()
      return refreshPromise
    })
    document.body.innerHTML = `<main id="workspace-content">${await outlineView.render()}</main>`
    outlineView._bindEvents()

    const retryButton = document.querySelector('[data-action="retry-outline-load"]')
    retryButton.click()
    expect(retryButton.disabled).toBe(true)
    expect(retryButton.textContent).toBe("重新加载中...")
    await refreshPromise

    expect(router.refresh).toHaveBeenCalledOnce()
    expect(api.outline[apiName]).toHaveBeenCalledOnce()
    expect(outlineView[store]).toEqual([item])
    expect(outlineView._structureLoadErrors[subView]).toBeUndefined()
  })

  it("重新加载本身失败时恢复按钮并显示操作错误", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "threads"
    outlineView._structureLoadErrors.threads = "网络暂时不可用"
    router.refresh.mockRejectedValue(new Error("路由刷新失败"))
    document.body.innerHTML = `<main id="workspace-content">${await outlineView.render()}</main>`
    outlineView._bindEvents()

    const retryButton = document.querySelector('[data-action="retry-outline-load"]')
    retryButton.click()
    await vi.waitFor(() => expect(toast).toHaveBeenCalledWith("操作失败：路由刷新失败", "error"))

    expect(retryButton.disabled).toBe(false)
    expect(retryButton.textContent).toBe("重新加载")
  })

  it("scenes 子标签直接渲染场景工作台内容", async () => {
    outlineView._loading = false
    state.currentView = "outline"
    state.currentSubView = "scenes"
    state.currentProjectId = "p1"
    const html = await outlineView.render()
    expect(html).toContain("场景工作台")
    expect(html).not.toContain(">场景卡<")
    expect(html).toContain("scene-workbench-shell")
    expect(html).toContain('aria-label="Scene 管理筛选"')
    expect(html).toContain('aria-label="Scene 工作台操作"')
    expect(html).toContain('data-action="scene-auto-extract"')
    const rendered = document.createElement("div")
    rendered.innerHTML = html
    expect(rendered.querySelectorAll('[data-role="smart-dedup-action"]')).toHaveLength(1)
    expect(html.match(/data-role="smart-dedup-action"/g)).toHaveLength(1)
    expect(html.indexOf('data-action="scene-auto-extract"')).toBeLessThan(html.indexOf("scene-workbench-shell"))
  })

  it.each([
    { name: "Threads", subView: "threads", store: "_threads", data: [{ id: "t1", name: "主线A", thread_type: "main", summary: "desc" }], expected: "主线A" },
  ])("$name 子标签渲染对应内容", async ({ subView, store, data, expected }) => {
    outlineView._loading = false
    state.currentSubView = subView
    state.currentProjectId = "p1"
    outlineView[store] = data
    const html = await outlineView.render()
    expect(html).toContain(expected)
  })

  it.each([
    { subView: "threads", title: "剧情线", createAction: "create-thread", aiAction: "ai-create-plot-thread", extractLabel: "从正文提取剧情线" },
    { subView: "arcs", title: "篇章纲", createAction: "create-arc", aiAction: "ai-create-outline-arc", extractLabel: "从正文提取篇章纲" },
  ])("$subView 子标签渲染就地 AI 入口和正文提取入口", async ({ subView, title, createAction, aiAction, extractLabel }) => {
    outlineView._loading = false
    state.currentSubView = subView
    state.currentProjectId = "p1"
    outlineView._threads = [{ id: "t1", name: "主线A", thread_type: "main", summary: "desc", status: "canonical" }]
    outlineView._structureTotals = { threads: 1, arcs: 1, foreshadowing: 1, reveals: 1 }

    const html = await outlineView.render()

    expect(html).toContain("outline-toolbar")
    expect(html).toContain(title)
    expect(html).toContain(`data-action="${createAction}"`)
    expect(html).toContain(`data-action="${aiAction}"`)
    expect(html).toContain('data-action="plot-structure-auto-extract"')
    expect(html).toContain(extractLabel)
    const rendered = document.createElement("div")
    rendered.innerHTML = html
    expect(rendered.querySelectorAll('[data-role="smart-dedup-action"]')).toHaveLength(1)
    if (subView === "arcs") expect(html).not.toContain("从正文提取剧情线")
  })

  it("进度卡片出现在工具栏状态区，不再独占一行", async () => {
    outlineView._loading = false
    state.currentSubView = "threads"
    state.currentProjectId = "p1"
    outlineView._threads = [{ id: "t1", name: "主线A", thread_type: "main", summary: "desc", status: "canonical" }]
    outlineView._outlineGenerateProgress = {
      taskId: "task-1",
      label: "剧情结构建议",
      statusLabel: "运行中",
      percent: 50,
      hasPercent: true,
    }

    const html = await outlineView.render()

    expect(html).toContain("outline-progress-mini")
    expect(html).not.toMatch(/^\s*<div class="outline-progress-card-wrap"/)
  })

  it("剧情线详情按同一信息 movement 展示伏笔和揭示", async () => {
    outlineView._loading = false
    state.currentProjectId = "p1"
    state.currentSubView = "threads"
    outlineView._threads = [{ id: "t1", name: "遗迹真相", status: "canonical" }]
    outlineView._foreshadowing = [{ id: "f1", summary: "潮门发光", related_thread_ids: ["t1"], planned_seed_chapter: 3, provenance_meta: { information_movement_id: "m1" } }]
    outlineView._reveals = [{ id: "r1", secret_summary: "潮门在评分", related_thread_ids: ["t1"], reveal_stages: [{ chapter_index: 5 }], provenance_meta: { information_movement_id: "m1" } }]
    const html = await outlineView.render()
    expect(html).toContain("信息推进 1")
    expect(html).toContain("潮门发光")
    expect(html).toContain("潮门在评分")
  })

  it("结构资产列表显示深度导入和注意原因", async () => {
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
    expect(html).toContain("需要人工检查")
    expect(html).toContain("structure_analysis")
    expect(html).toContain('data-action="mark-thread-reviewed"')
    expect(html).toContain("采用")
  })

  it("工作稿状态本身不推断为需要人工检查", async () => {
    outlineView._loading = false
    state.currentSubView = "threads"
    state.currentProjectId = "p1"
    outlineView._threads = [{
      id: "t1",
      name: "草稿但已处理",
      thread_type: "main",
      status: "draft",
      provenance_meta: { source: "manual", needs_review: false },
    }]

    const html = await outlineView.render()
    const rowHtml = html.match(/<tr[^>]*data-id="t1"[^>]*>[\s\S]*?<\/tr>/)?.[0] || ""

    expect(rowHtml).toContain("工作稿")
    expect(rowHtml).not.toContain("需要人工检查")
  })

  it("工作稿加 needs_review=true 才显示需要人工检查", async () => {
    outlineView._loading = false
    state.currentSubView = "threads"
    state.currentProjectId = "p1"
    outlineView._threads = [{
      id: "t1",
      name: "草稿待复核",
      thread_type: "main",
      status: "draft",
      provenance_meta: { source: "deep_import", needs_review: true },
    }]

    const html = await outlineView.render()
    const rowHtml = html.match(/<tr[^>]*data-id="t1"[^>]*>[\s\S]*?<\/tr>/)?.[0] || ""

    expect(rowHtml).toContain("工作稿")
    expect(rowHtml).toContain("需要人工检查")
    expect(rowHtml).toContain('data-action="mark-thread-reviewed"')
  })

  it("标记单条剧情线复核通过", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "threads"
    outlineView._threads = [{
      id: "t1",
      name: "主线A",
      status: "candidate",
      provenance_meta: { source: "deep_import", needs_review: true },
    }]
    api.outline.updateThread.mockResolvedValue({})
    api.outline.listThreads.mockResolvedValue({
      items: [{
        id: "t1",
        name: "主线A",
        status: "canonical",
        provenance_meta: { source: "deep_import", needs_review: false },
      }],
      total: 1,
    })
    document.body.innerHTML = `<main id="workspace-content">${await outlineView.render()}</main>`
    document.getElementById("workspace-content").scrollTop = 92

    await outlineView._markThreadReviewed("t1")

    expect(api.outline.updateThread).toHaveBeenCalledWith("t1", "p1", {
      status: "canonical",
      provenance_meta: expect.objectContaining({
        source: "deep_import",
        needs_review: false,
        reviewed_at: expect.any(String),
        reviewed_by: "manual",
        reviewed_from: "outline_threads",
        review_previous_status: "candidate",
      }),
    })
    expect(toast).toHaveBeenCalledWith("剧情线已采用", "success")
    expect(router.refresh).not.toHaveBeenCalled()
    expect(document.getElementById("workspace-content").scrollTop).toBe(92)
  })

  it("标记单条剧情线需复核并移除复核字段", async () => {
    state.currentProjectId = "p1"
    outlineView._threads = [{
      id: "t1",
      name: "主线A",
      status: "canonical",
      provenance_meta: {
        source: "deep_import",
        review_previous_status: "candidate",
        reviewed_at: "2026-07-05T00:00:00.000Z",
        reviewed_by: "manual",
        reviewed_from: "outline_threads",
      },
    }]
    api.outline.updateThread.mockResolvedValue({})

    await outlineView._markThreadUnreviewed("t1")

    expect(api.outline.updateThread).toHaveBeenCalledWith("t1", "p1", {
      status: "candidate",
      provenance_meta: {
        source: "deep_import",
        needs_review: true,
      },
    })
    expect(toast).toHaveBeenCalledWith("剧情线已标记为需要人工检查", "success")
  })

  it("剧情线超过一页时显示分页控制", async () => {
    outlineView._loading = false
    state.currentSubView = "threads"
    state.currentProjectId = "p1"
    outlineView._threads = [{ id: "t1", name: "主线A", thread_type: "main" }]
    outlineView._structureTotals.threads = 75

    const html = await outlineView.render()

    expect(html).toContain('data-action="prev-outline-structure-page"')
    expect(html).toContain('data-action="next-outline-structure-page"')
    expect(html).toContain("共 75 条")
  })

  it("剧情线创建把描述写入 summary 字段", async () => {
    state.currentProjectId = "p1"
    api.outline.createThread.mockResolvedValue({ id: "t1" })

    outlineView._showCreateThreadForm()
    document.body.innerHTML = showModal.mock.calls.at(-1)[1].html
    document.getElementById("create-thread-name").value = "归一潮失踪案主线"
    document.getElementById("create-thread-type").value = "main"
    document.getElementById("create-thread-desc").value = "沈澜追查潮雾失踪案。"
    await captureModalHandler({ callIndex: showModal.mock.calls.length - 1 })()

    expect(api.outline.createThread).toHaveBeenCalledWith("p1", {
      name: "归一潮失踪案主线",
      thread_type: "main",
      summary: "沈澜追查潮雾失踪案。",
    })
  })

  it("剧情线和篇章纲列表显示后端真实描述字段", async () => {
    outlineView._loading = false
    state.currentProjectId = "p1"

    state.currentSubView = "threads"
    outlineView._threads = [{
      id: "t1",
      name: "归一潮失踪案主线",
      thread_type: "main",
      summary: "沈澜追查潮雾失踪案。",
    }]
    let html = await outlineView.render()
    expect(html).toContain("沈澜追查潮雾失踪案。")

    state.currentSubView = "arcs"
    outlineView._arcs = [{
      id: "a1",
      title: "三章短篇：潮雾、镜局、归潮",
      start_chapter: 1,
      end_chapter: 3,
      arc_goal: "三章内完成潮雾、镜局、归潮转折。",
    }]
    html = await outlineView.render()
    expect(html).toContain("三章内完成潮雾、镜局、归潮转折。")
    expect(html).toContain('data-action="mark-arc-reviewed"')
    expect(html).toContain("采用")
  })

  it("编辑篇章纲保留模型明确未定的章节边界", async () => {
    state.currentProjectId = "p1"
    outlineView._arcs = [{
      id: "a1",
      title: "开放篇章",
      start_chapter: 1,
      end_chapter: null,
      arc_goal: "保持终点未定。",
      status: "draft",
    }]
    api.outline.updateArc.mockResolvedValue({})

    outlineView._editArc("a1")
    document.body.innerHTML = showModal.mock.calls.at(-1)[1].html

    expect(document.getElementById("edit-arc-start").value).toBe("1")
    expect(document.getElementById("edit-arc-end").value).toBe("")
    await captureModalHandler({ callIndex: showModal.mock.calls.length - 1 })()

    expect(api.outline.updateArc).toHaveBeenCalledWith("a1", "p1", {
      title: "开放篇章",
      start_chapter: 1,
      end_chapter: null,
      arc_goal: "保持终点未定。",
    })
  })

  it("采用单条篇章纲", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "arcs"
    outlineView._arcs = [{
      id: "a1",
      title: "开放篇章",
      status: "draft",
      provenance_meta: { source: "ai_generated" },
    }]
    api.outline.updateArc.mockResolvedValue({})
    api.outline.listArcs.mockResolvedValue({
      items: [{ id: "a1", title: "开放篇章", status: "canonical" }],
      total: 1,
    })

    await outlineView._markArcReviewed("a1")

    expect(api.outline.updateArc).toHaveBeenCalledWith("a1", "p1", {
      status: "canonical",
      provenance_meta: expect.objectContaining({
        source: "ai_generated",
        reviewed_from: "outline_arcs",
      }),
    })
    expect(toast).toHaveBeenCalledWith("篇章纲已采用", "success")
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
    expect(html).toContain("从已采用 Scene 开始整理")
    expect(html).toContain('data-action="nav-scenes"')
  })

  it.each([
    ["threads", "剧情线"],
    ["arcs", "篇章纲"],
  ])("%s 空状态可返回已采用 Scene 整理", async (subView, kind) => {
    outlineView._loading = false
    state.currentSubView = subView
    state.currentProjectId = "p1"

    const html = await outlineView.render()

    expect(html).toContain(`暂无${kind}`)
    expect(html).toContain("从已采用 Scene 开始整理")
    expect(html).toContain('data-action="nav-scenes"')
  })
})

describe("structure asset filters", () => {
  it("Workflow 诊断筛选默认折叠，有条件时自动展开", () => {
    let html = outlineView._renderStructureFilters("threads")
    document.body.innerHTML = html
    expect(document.querySelector(".outline-structure-diagnostic-filters").open).toBe(false)
    expect(document.body.textContent).toContain("Workflow 诊断 ID")

    outlineView._structureFilters.threads = {
      ...outlineView._structureFilterFor("threads"),
      workflow_id: "wf-1",
    }
    html = outlineView._renderStructureFilters("threads")
    document.body.innerHTML = html

    expect(document.querySelector(".outline-structure-diagnostic-filters").open).toBe(true)
    expect(document.querySelector("#outline-filter-workflow-id").value).toBe("wf-1")
  })

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

  it("结构资产翻页时更新当前页签 skip", () => {
    state.currentSubView = "threads"
    outlineView._structureFilters.threads = {
      status: "",
      source: "",
      workflow_id: "",
      needs_review: "",
      skip: 0,
      limit: 50,
    }
    outlineView._structureTotals.threads = 120

    outlineView._changeStructurePage(1)

    expect(outlineView._structureFilters.threads.skip).toBe(50)
    expect(router.refresh).toHaveBeenCalled()
  })
})

describe("_narrativeTagLabel", () => {
  it("返回正确的中文标签", () => {
    expect(outlineView._narrativeTagLabel("hook")).toBe("钩子")
    expect(outlineView._narrativeTagLabel("climax")).toBe("阶段高潮")
    expect(outlineView._narrativeTagLabel("draft")).toBe("未标注")
    expect(outlineView._narrativeTagLabel(null)).toBe("未标注")
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

  it("generates one current-layer PlotThread preview", async () => {
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

    const promise = outlineView._generateOutlineLayer({
      target: "plot_thread",
      mode: "create",
      instruction: "设计联盟主线",
      selectedIds: [],
      startChapter: 1,
      endChapter: 5,
    })
    await Promise.resolve()
    document.querySelectorAll("#modal-footer button")[1].click()
    const result = await promise

    expect(api.outline.generate).toHaveBeenCalledWith({
      contract_version: "outline_layer_v2",
      novel_id: "p1",
      context_confirmation_id: "confirm-1",
      target: "plot_thread",
      mode: "create",
      instruction: "设计联盟主线",
      selected_thread_ids: [],
      selected_arc_ids: [],
      selected_scene_ids: [],
      start_chapter: 1,
      end_chapter: 5,
    })
    expect(api.context.confirm).toHaveBeenCalledWith(expect.objectContaining({
      action: "outline.generate",
      budget_tokens: 0,
      include_pending_objects: false,
    }))
    expect(toast).toHaveBeenCalledWith("剧情线建议生成任务已提交", "success")
    expect(result).toEqual({ task_id: "task-1", status: "pending" })
  })

  it("confirms range context before submitting a read-only outline analysis", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "threads"
    document.body.innerHTML = `
      <div id="modal-overlay" class="hidden">
        <div id="modal-title"></div>
        <div id="modal-body"></div>
        <div id="modal-footer"></div>
      </div>
    `
    api.context.confirm.mockResolvedValue({
      id: "analysis-confirm-1",
      compile_options: { chapter_index: 2, visible_until_chapter: 7 },
      sections: [{
        key: "outline_analysis_scenes",
        title: "范围内 Scene（按叙事顺序）",
        sources: [{ id: "scene-1", label: "码头冲突" }],
      }],
      warnings: [],
    })
    api.outline.analyze.mockResolvedValue({ task_id: "analysis-task-1", status: "pending" })

    const promise = outlineView._analyzeOutline({
      instruction: "判断主角的选择是否推动主线",
      startChapter: 2,
      endChapter: 7,
    })
    await Promise.resolve()
    expect(document.getElementById("ai-ref-scope").disabled).toBe(true)
    expect(document.getElementById("ai-ref-chapter").readOnly).toBe(true)
    expect(document.getElementById("modal-body").textContent).toContain("结束章节")
    document.querySelectorAll("#modal-footer button")[1].click()
    const result = await promise

    expect(api.context.confirm).toHaveBeenCalledWith(expect.objectContaining({
      action: "outline.analyze",
      scope: "full",
      chapter_index: 2,
      visible_until_chapter: 7,
      budget_tokens: 12000,
      context_mode: "working",
      include_pending_objects: false,
    }))
    expect(api.outline.analyze).toHaveBeenCalledWith({
      novel_id: "p1",
      context_confirmation_id: "analysis-confirm-1",
      start_chapter: 2,
      end_chapter: 7,
    })
    expect(outlineView._outlineAnalysisMeta.context_summary.sections[0]).toEqual(
      expect.objectContaining({
        title: "范围内 Scene（按叙事顺序）",
        sources: ["码头冲突"],
      }),
    )
    expect(result).toEqual({ task_id: "analysis-task-1", status: "pending" })
  })

  it("keeps the previous completed analysis when a replacement enqueue fails", async () => {
    state.currentProjectId = "p1"
    document.body.innerHTML = `
      <div id="modal-overlay" class="hidden">
        <div id="modal-title"></div>
        <div id="modal-body"></div>
        <div id="modal-footer"></div>
      </div>
    `
    outlineView._outlineAnalysisTaskId = "analysis-old"
    outlineView._outlineAnalysisMeta = { project_id: "p1", start_chapter: 1, end_chapter: 3 }
    outlineView._outlineAnalysisProgress = normalizeTaskProgress({
      task_id: "analysis-old",
      task_type: "outline_analyze",
      status: "done",
    }, "outline_analyze")
    outlineView._outlineAnalysisResult = {
      markdown: "已完成的旧分析",
      contextSummary: {},
    }
    persistActiveWorkflow({
      taskId: "analysis-old",
      workflowType: "outline_analyze",
      projectId: "p1",
      view: "outline",
    })
    api.context.confirm.mockResolvedValue({ id: "analysis-confirm-new", sections: [] })
    api.outline.analyze.mockRejectedValue(new Error("任务入队失败"))

    const promise = outlineView._analyzeOutline({
      instruction: "新的分析目标",
      startChapter: 4,
      endChapter: 6,
    })
    await Promise.resolve()
    document.querySelectorAll("#modal-footer button")[1].click()

    await expect(promise).rejects.toThrow("任务入队失败")
    expect(outlineView._outlineAnalysisTaskId).toBe("analysis-old")
    expect(outlineView._outlineAnalysisResult?.markdown).toBe("已完成的旧分析")
    expect(recoverActiveWorkflows("p1").map((item) => item.taskId)).toEqual([
      "analysis-old",
    ])
  })

  it("renders outline analysis and context summary as escaped read-only content", () => {
    outlineView._outlineAnalysisResult = {
      markdown: "# 判断\n<img src=x onerror=alert(1)>",
      contextSummary: {
        sections: [{
          title: "范围内 <Scene>",
          sources: ["码头<script>"],
          sourceCount: 1,
        }],
        warnings: ["资料 <不足>"],
      },
    }

    const html = outlineView._renderOutlineAnalysisResult()

    expect(html).toContain("只读分析")
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;")
    expect(html).toContain("码头&lt;script&gt;")
    expect(html).not.toContain("<img src=x")
    expect(html).not.toContain('data-action="apply')
    expect(html).not.toContain("采用")
  })

  it("recovers an outline analysis task and keeps its result until dismissed", async () => {
    state.currentProjectId = "p1"
    localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
      id: "p1:outline_analyze:analysis-task-2",
      taskId: "analysis-task-2",
      workflowType: "outline_analyze",
      projectId: "p1",
      meta: {
        start_chapter: 1,
        end_chapter: 4,
        context_summary: { sections: [{ title: "相关剧情线", sources: ["主线"], sourceCount: 1 }] },
      },
      updatedAt: "2026-07-16T00:00:00Z",
    }]))
    api.tasks.get.mockResolvedValue({
      id: "analysis-task-2",
      task_type: "outline_analyze",
      status: "done",
      progress: 1,
      result: { analysis: "## 已恢复的分析" },
    })

    outlineView._recoverOutlineAnalysisWorkflow()
    await vi.waitFor(() => {
      expect(outlineView._outlineAnalysisResult?.markdown).toBe("## 已恢复的分析")
    })

    expect(api.tasks.get).toHaveBeenCalledWith("analysis-task-2", "p1")
    expect(outlineView._renderOutlineAnalysisResult()).toContain("已恢复的分析")
    expect(JSON.parse(localStorage.getItem("novel_active_workflows_v1"))).toHaveLength(1)
    outlineView._resetOutlineAnalysisState({ clearWorkflow: true })
    expect(JSON.parse(localStorage.getItem("novel_active_workflows_v1"))).toEqual([])
  })

  it("recovers a cancelled outline analysis as cancelled instead of failed", async () => {
    state.currentProjectId = "p1"
    persistActiveWorkflow({
      taskId: "analysis-cancelled",
      workflowType: "outline_analyze",
      projectId: "p1",
      view: "outline",
      meta: { start_chapter: 2, end_chapter: 5 },
    })
    api.tasks.get.mockResolvedValue({
      id: "analysis-cancelled",
      task_type: "outline_analyze",
      status: "cancelled",
      progress: 0.4,
      result: {},
    })

    outlineView._recoverOutlineAnalysisWorkflow()
    await vi.waitFor(() => {
      expect(outlineView._outlineAnalysisProgress?.cancelled).toBe(true)
    })

    expect(outlineView._outlineAnalysisResult).toBeNull()
    expect(outlineView._outlineAnalysisPoller).toBeNull()
    expect(outlineView._renderOutlineProgressStatus()).toContain(
      'data-action="dismiss-outline-analysis"',
    )
    expect(toast).toHaveBeenCalledWith("大纲分析任务已取消", "warning")
    expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("大纲分析失败"), "error")
    expect(recoverActiveWorkflows("p1")).toHaveLength(1)
  })

  it("does not expose an outline analysis result after switching projects", () => {
    state.currentProjectId = "p1"
    localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
      id: "p1:outline_analyze:analysis-task-3",
      taskId: "analysis-task-3",
      workflowType: "outline_analyze",
      projectId: "p1",
      meta: { project_id: "p1" },
    }]))
    outlineView._outlineAnalysisTaskId = "analysis-task-3"
    outlineView._outlineAnalysisMeta = { project_id: "p1" }
    outlineView._outlineAnalysisResult = {
      markdown: "只属于项目一的分析",
      contextSummary: {},
    }

    state.currentProjectId = "p2"
    outlineView._syncOutlineAnalysisProject()

    expect(outlineView._outlineAnalysisResult).toBeNull()
    expect(outlineView._outlineAnalysisTaskId).toBeNull()
    expect(JSON.parse(localStorage.getItem("novel_active_workflows_v1"))).toHaveLength(1)
  })

  it("confirms and cancels a running outline analysis for its owning project", async () => {
    autoConfirm()
    api.tasks.cancel.mockResolvedValue({
      task_id: "analysis-running",
      status: "cancelled",
      cancelled: true,
    })
    outlineView._outlineAnalysisTaskId = "analysis-running"
    outlineView._outlineAnalysisMeta = {
      project_id: "p1",
      start_chapter: 2,
      end_chapter: 7,
    }
    outlineView._outlineAnalysisProgress = normalizeTaskProgress({
      task_id: "analysis-running",
      task_type: "outline_analyze",
      status: "running",
      available_actions: ["cancel"],
    }, "outline_analyze")
    persistActiveWorkflow({
      taskId: "analysis-running",
      workflowType: "outline_analyze",
      projectId: "p1",
      view: "outline",
    })

    expect(outlineView._renderOutlineProgressStatus()).toContain(
      'data-action="cancel-outline-analysis"',
    )
    await outlineView._cancelOutlineAnalysisTask()

    expect(api.tasks.cancel).toHaveBeenCalledWith("analysis-running", "p1")
    expect(outlineView._outlineAnalysisProgress.cancelled).toBe(true)
    expect(outlineView._renderOutlineProgressStatus()).toContain(
      'data-action="dismiss-outline-analysis"',
    )
    expect(recoverActiveWorkflows("p1")).toHaveLength(1)
  })

  it("keeps a completed outline generation as an editable preview until explicit adoption", async () => {
    state.currentProjectId = "p1"
    const draftStructure = {
      result: "proposed",
      reuse_judgments: [],
      threads: [{
        proposal_ref: "P1",
        target_thread_ref: null,
        name: "AI 主线",
        thread_type: "main",
        summary: "原摘要",
        information_movements: [],
        basis: "总纲方向尚未物化",
        uncertain_fields: [],
        confidence: 0.9,
      }],
      story_outline_conflict: null,
      author_decisions: [],
    }
    outlineView._outlineGenerateMeta = { context_confirmation_id: "confirm-1", start_chapter: 1, end_chapter: 5, target: "plot_thread", mode: "create", label: "剧情线" }
    outlineView._outlineGenerateProgress = {
      taskId: "task-1",
      status: "done",
      statusLabel: "已完成",
      message: "任务完成",
      percent: 100,
      terminal: true,
      warnings: [],
    }

    const preview = outlineView._captureOutlineGeneratePreview({
      id: "task-1",
      task_type: "outline_generate",
      result: {
        source_task_id: "task-1",
        context_confirmation_id: "confirm-1",
        draft_structure: draftStructure,
        contract_version: "outline_layer_v2",
        target: "plot_thread",
        mode: "create",
        overlap: { plot_threads: [{ ref: "T1", name: "已有主线" }] },
        warnings: ["一项需要作者判断"],
        requires_apply: true,
      },
    })

    expect(preview).toBeTruthy()
    expect(outlineView._renderOutlineGenerateProgress()).toContain('data-action="view-outline-generate-preview"')
    expect(outlineView._renderOutlineProgressStatus()).toContain('data-action="view-outline-generate-preview"')
    const html = outlineView._renderOutlineGeneratePreview()
    expect(html).toContain("待处理建议")
    expect(html).toContain("一项需要作者判断")
    expect(html).toContain("已有主线")
    document.body.innerHTML = html
    const edited = JSON.parse(document.getElementById("outline-layer-preview-json").value)
    edited.threads[0].name = "作者修订主线"
    document.getElementById("outline-layer-preview-json").value = JSON.stringify(edited)
    api.outline.applyStructurePreview.mockResolvedValue({
      status: "applied",
      target: "plot_thread",
      total_threads: 1,
      total_arcs: 0,
      total_scenes: 0,
    })
    persistActiveWorkflow({
      taskId: "task-1",
      workflowType: "outline_generate",
      projectId: "p1",
      meta: { target: "plot_thread" },
    })
    persistActiveWorkflow({
      taskId: "stale-thread-task",
      workflowType: "outline_generate",
      projectId: "p1",
      meta: { target: "plot_thread" },
    })
    persistActiveWorkflow({
      taskId: "arc-task",
      workflowType: "outline_generate",
      projectId: "p1",
      meta: { target: "outline_arc" },
    })

    const result = await outlineView._applyOutlineGeneratePreview()

    expect(api.outline.applyStructurePreview).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      context_confirmation_id: "confirm-1",
      source_task_id: "task-1",
      confirmed: true,
      draft_structure: expect.objectContaining({
        threads: [expect.objectContaining({ name: "作者修订主线" })],
      }),
    }))
    expect(result.status).toBe("applied")
    expect(outlineView._outlineGeneratePreview).toBeNull()
    expect(recoverActiveWorkflows("p1").map((item) => item.taskId)).toEqual(["arc-task"])
    expect(toast).toHaveBeenCalledWith("剧情线已采用：剧情线 1 · 篇章纲 0 · Scene 0", "success")
  })

  it("renders a completed P20 task only after capturing its adoptable preview", async () => {
    state.currentProjectId = "p1"
    outlineView._outlineGenerateMeta = {
      context_confirmation_id: "confirm-1",
      target: "plot_thread",
      mode: "create",
      label: "剧情线",
    }
    api.tasks.get.mockResolvedValue({
      id: "task-1",
      task_type: "outline_generate",
      status: "done",
      progress: 1,
      result: {
        source_task_id: "task-1",
        context_confirmation_id: "confirm-1",
        draft_structure: {
          result: "no_change",
          reuse_judgments: [],
          threads: [],
          story_outline_conflict: null,
          author_decisions: [],
        },
        target: "plot_thread",
        mode: "create",
        overlap: {},
        requires_apply: true,
      },
    })
    const render = vi.spyOn(router, "renderCurrentView").mockImplementation(() => {})

    outlineView._startOutlineGeneratePolling("task-1")
    await vi.waitFor(() => expect(outlineView._outlineGeneratePreview).toBeTruthy())

    expect(render).toHaveBeenCalledTimes(1)
    expect(outlineView._renderOutlineGenerateProgress()).toContain("查看并采用")
    render.mockRestore()
  })

  it("recovers the newest P20 task when an older unapplied preview is still stored", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "threads"
    localStorage.setItem("novel_active_workflows_v1", JSON.stringify([
      {
        id: "p1:outline_generate:task-old",
        taskId: "task-old",
        workflowType: "outline_generate",
        projectId: "p1",
        meta: { label: "剧情线", target: "plot_thread", context_confirmation_id: "confirm-old" },
        createdAt: "2026-07-17T08:00:00Z",
        updatedAt: "2026-07-17T08:05:00Z",
      },
      {
        id: "p1:outline_generate:task-new",
        taskId: "task-new",
        workflowType: "outline_generate",
        projectId: "p1",
        meta: { label: "剧情线", target: "plot_thread", context_confirmation_id: "confirm-new" },
        createdAt: "2026-07-17T09:00:00Z",
        updatedAt: "2026-07-17T09:01:00Z",
      },
    ]))
    api.tasks.get.mockResolvedValue({
      id: "task-new",
      task_type: "outline_generate",
      status: "running",
      progress: 0.2,
      result: {},
    })

    outlineView._recoverOutlineGenerateWorkflow()
    await vi.waitFor(() => {
      expect(api.tasks.get).toHaveBeenCalledWith("task-new")
    })

    expect(outlineView._outlineGenerateTaskId).toBe("task-new")
    outlineView._stopOutlineGeneratePolling()
  })

  it("recovers only the P20 task that belongs to the current outline layer", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "arcs"
    localStorage.setItem("novel_active_workflows_v1", JSON.stringify([
      {
        id: "p1:outline_generate:thread-newer",
        taskId: "thread-newer",
        workflowType: "outline_generate",
        projectId: "p1",
        meta: { label: "剧情线", target: "plot_thread", context_confirmation_id: "confirm-thread" },
        updatedAt: "2026-07-17T10:00:00Z",
      },
      {
        id: "p1:outline_generate:arc-older",
        taskId: "arc-older",
        workflowType: "outline_generate",
        projectId: "p1",
        meta: { label: "篇章纲", target: "outline_arc", context_confirmation_id: "confirm-arc" },
        updatedAt: "2026-07-17T09:00:00Z",
      },
    ]))
    api.tasks.get.mockResolvedValue({
      id: "arc-older",
      task_type: "outline_generate",
      status: "running",
      progress: 0.2,
      result: {},
    })

    outlineView._recoverOutlineGenerateWorkflow()
    await vi.waitFor(() => expect(api.tasks.get).toHaveBeenCalledWith("arc-older"))

    expect(api.tasks.get).not.toHaveBeenCalledWith("thread-newer")
    expect(outlineView._outlineGenerateTaskId).toBe("arc-older")
    outlineView._stopOutlineGeneratePolling()
  })

  it("drops mismatched in-memory P20 state without deleting its persisted workflow", () => {
    state.currentProjectId = "p1"
    state.currentSubView = "arcs"
    persistActiveWorkflow({
      taskId: "thread-task",
      workflowType: "outline_generate",
      projectId: "p1",
      meta: { target: "plot_thread" },
    })
    outlineView._outlineGenerateTaskId = "thread-task"
    outlineView._outlineGenerateMeta = { target: "plot_thread" }
    outlineView._outlineGenerateProgress = { terminal: false }

    outlineView._syncOutlineGenerateTarget()

    expect(outlineView._outlineGenerateTaskId).toBeNull()
    expect(recoverActiveWorkflows("p1").map((item) => item.taskId)).toContain("thread-task")
  })

  it("does not present a legacy plot_structure_generate task as adoptable", () => {
    outlineView._outlineGenerateMeta = { context_confirmation_id: "confirm-1" }
    const preview = outlineView._captureOutlineGeneratePreview({
      id: "legacy-task",
      task_type: "plot_structure_generate",
      result: {
        source_task_id: "legacy-task",
        context_confirmation_id: "confirm-1",
        draft_structure: { threads: [{ name: "旧结果" }] },
        requires_apply: true,
      },
    })

    expect(preview).toBeNull()
    expect(outlineView._outlineGeneratePreview).toBeNull()
  })

  it("submits plot structure auto extraction stage task", async () => {
    state.currentProjectId = "p1"
    api.imports.startStage.mockResolvedValue({ task_id: "plot-task" })
    outlineView._showPlotStructureAutoExtractForm()
    expect(showModal.mock.calls[0][1].html).toContain("自动采用通过门禁")
    expect(showModal.mock.calls[0][1].html).toContain("进入待处理")
    expect(showModal.mock.calls[0][2][0].text).toBe("确认并开始提取")
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
      false,
      false,
      {
        adoption_policy: "user_authorized_pipeline",
        authorization_confirmed: true,
      },
    )
    expect(api.outline.generate).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(
      "从正文提取剧情线任务已提交：plot-task",
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
      name: "generate current layer",
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
        const promise = outlineView._generateOutlineLayer({
          target: "plot_thread",
          mode: "create",
          instruction: "设计主线",
          selectedIds: [],
          startChapter: 1,
          endChapter: 5,
        })
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

    expect(html).toContain("从正文提取剧情线")
    expect(html).toContain('data-action="plot-structure-auto-extract"')
    expect(html).toContain('data-action="analyze-outline"')
    expect(html).toContain("AI 分析大纲")
  })

  it("renders the scene workbench in place instead of a jump button", async () => {
    outlineView._loading = false
    state.currentView = "outline"
    state.currentSubView = "scenes"
    state.currentProjectId = "p1"
    const html = await outlineView.render()
    expect(html).toContain("scene-workbench-shell")
    expect(html).not.toContain('data-action="open-scene-workbench"')
    expect(html).not.toContain('data-action="generate-structure"')
    expect(html).not.toContain('data-action="move-scene-up"')
    expect(html).not.toContain('data-action="move-scene-down"')
  })

  it("renders information progression inside threads without top-level create actions", async () => {
    outlineView._loading = false
    state.currentProjectId = "p1"
    state.currentSubView = "threads"
    outlineView._threads = [{ id: "t1", name: "主线", status: "canonical" }]
    outlineView._foreshadowing = [{
      id: "f1",
      name: "伏笔A",
      summary: "摘要",
      status: "planted",
      planned_seed_chapter: 3,
      related_thread_ids: ["t1"],
    }]
    outlineView._reveals = [{
      id: "r1",
      target_type: "world_entity",
      secret_summary: "秘密",
      status: "planned",
      related_thread_ids: ["t1"],
      reveal_stages: [{ stage_index: 0, chapter_index: 1, reveal_content: "揭示" }],
    }]
    const html = await outlineView.render()
    expect(html).toContain("信息推进")
    expect(html).toContain("摘要")
    expect(html).toContain("秘密")
    expect(html).not.toContain('data-action="create-foreshadowing"')
    expect(html).not.toContain('data-action="create-reveal"')
  })

  it("positions legacy information links at the merged thread section", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "threads"
    outlineView._threads = [{ id: "t1", name: "主线", status: "canonical" }]
    router.getCurrentQuery.mockReturnValueOnce(
      new URLSearchParams("information=foreshadowing"),
    )
    document.body.innerHTML = await outlineView.render()
    const section = document.getElementById("outline-thread-information")
    section.scrollIntoView = vi.fn()

    outlineView.onRendered()

    expect(section.scrollIntoView).toHaveBeenCalledWith({ block: "start" })
  })
})

describe("P20 current-layer form", () => {
  const originalGenerate = outlineView._generateOutlineLayer

  afterEach(() => {
    outlineView._generateOutlineLayer = originalGenerate
  })

  it("requires a current StoryOutline before opening", async () => {
    state.currentProjectId = "p1"
    api.outline.getStoryOutline.mockResolvedValue({ current_revision_id: null, revision: null })

    await outlineView._showOutlineLayerAiForm("plot_thread")

    expect(toast).toHaveBeenCalledWith("请先在“小说总纲”页创建并采用当前总纲", "warning")
    expect(router.navigate).toHaveBeenCalledWith("outline", "story-outline")
  })

  it("submits only the selected current layer in revise mode", async () => {
    state.currentProjectId = "p1"
    outlineView._bulkSelections = { "outline-threads": new Set(["t1"]) }
    await outlineView._showOutlineLayerAiForm("plot_thread")
    const handler = captureModalHandler()
    outlineView._generateOutlineLayer = vi.fn().mockResolvedValue({ task_id: "task-1" })
    document.getElementById = vi.fn((id) => ({
      value: {
        "outline-layer-mode": "revise",
        "outline-layer-instruction": "深化所选主线",
        "outline-layer-start": "1",
        "outline-layer-end": "5",
      }[id] || "",
    }))

    await handler()

    expect(outlineView._generateOutlineLayer).toHaveBeenCalledWith({
      target: "plot_thread",
      mode: "revise",
      instruction: "深化所选主线",
      selectedIds: ["t1"],
      startChapter: 1,
      endChapter: 5,
    })
  })

  it("allows create mode beside existing assets without a hard overlap block", async () => {
    state.currentProjectId = "p1"
    outlineView._threads = [{ id: "t1", name: "已有主线" }]
    await outlineView._showOutlineLayerAiForm("plot_thread")

    expect(showModal.mock.calls.at(-1)[1].html).toContain("新增设计允许与已有资产并行")
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
