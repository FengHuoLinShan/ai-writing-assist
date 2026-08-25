/**
 * outlineAiOps 测试 — 表单展示/提交/取消/预览采用。
 *
 * showModalHtml / confirmAction 等通过 bridge mock 注入；
 * 表单提交 DOM 读取通过 document.getElementById 模拟（happy-dom）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"

vi.mock("../../../../shared/workflowProgress.js", async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    pollTaskProgress: vi.fn(() => ({ stop: vi.fn() })),
    persistActiveWorkflow: vi.fn(),
    recoverActiveWorkflows: vi.fn(() => []),
    clearActiveWorkflow: vi.fn(),
    normalizeTaskProgress: vi.fn((task) => ({
      taskId: task.task_id,
      workflowType: task.task_type,
      status: task.status || "pending",
      terminal: ["done", "failed", "cancelled"].includes(task.status),
      ...task,
    })),
  }
})

vi.mock("../../../../shared/aiReferenceModal.js", () => ({
  confirmAiReference: vi.fn(),
}))

vi.mock("../../../../shared/importAuthorization.js", () => ({
  importAuthorizationPayload: vi.fn(() => ({ authorization: "confirmed" })),
  importAuthorizationNotice: vi.fn(() => "授权提示"),
}))

import { confirmAiReference } from "../../../../shared/aiReferenceModal.js"
import {
  persistActiveWorkflow,
  recoverActiveWorkflows,
  clearActiveWorkflow,
  normalizeTaskProgress,
} from "../../../../shared/workflowProgress.js"
import {
  outlineGenerateManager,
  outlineAnalysisManager,
  plotAutoExtractManager,
} from "../../../../vue/views/outline/ai/outlineWorkflowManagers.js"
import {
  showOutlineLayerAiForm,
  showOutlineAnalysisForm,
  showPlotStructureAutoExtractForm,
  showOutlineGeneratePreview,
  applyOutlineGeneratePreview,
  cancelOutlineAnalysisTask,
  generateOutlineLayer,
  analyzeOutline,
} from "../../../../vue/views/outline/ai/outlineAiOps.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"
import { clearAllBulkSelections, getBulkSelection } from "../../../../vue/views/outline/logic/outlineBulkSelection.js"

function setupBridge(overrides = {}) {
  const bridge = {
    api: {
      outline: {
        getStoryOutline: vi.fn(),
        generate: vi.fn(),
        analyze: vi.fn(),
        applyStructurePreview: vi.fn(),
      },
      imports: { startStage: vi.fn() },
      tasks: { cancel: vi.fn() },
    },
    state: { currentProjectId: "p-test", currentSubView: "threads", currentView: "outline" },
    router: { refresh: vi.fn(), navigate: vi.fn(), replace: vi.fn(), getCurrentQuery: vi.fn(() => new URLSearchParams()) },
    toast: vi.fn(),
    showModalHtml: vi.fn(),
    closeModal: vi.fn(),
    confirmAction: vi.fn(),
    esc: (v) => String(v ?? ""),
    ...overrides,
  }
  setBridgeOverrides(bridge)
  return bridge
}

function resetManagers() {
  for (const manager of [outlineGenerateManager, outlineAnalysisManager, plotAutoExtractManager]) {
    manager.stop()
    manager.state.taskId = null
    manager.state.status = "就绪"
    manager.state.meta = null
    manager.state.progress = null
    manager.state.ownerProjectId = null
    manager.state.submitting = false
  }
  outlineGenerateManager.state.preview = null
  outlineAnalysisManager.state.result = null
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetManagers()
  clearAllBulkSelections()
  // 确保 body 干净
  document.body.innerHTML = ""
})

afterEach(() => {
  resetBridgeOverrides()
})

// ═══════════════════════════════════════════════════════════════════════
// showOutlineLayerAiForm
// ═══════════════════════════════════════════════════════════════════════

describe("showOutlineLayerAiForm", () => {
  it("无总纲时提示并导航到 story-outline", async () => {
    const router = { refresh: vi.fn(), navigate: vi.fn() }
    const toast = vi.fn()
    const bridge = setupBridge({
      api: { outline: { getStoryOutline: vi.fn(async () => ({})) } },
      router,
      toast,
    })
    await showOutlineLayerAiForm("plot_thread")
    expect(toast).toHaveBeenCalledWith("请先在“故事总览”页创建并采用当前版本", "warning")
    expect(router.navigate).toHaveBeenCalledWith("outline", "story-outline")
  })

  it("从当前层批量选择恢复“修订所选”默认语义", async () => {
    const bridge = setupBridge()
    bridge.api.outline.getStoryOutline.mockResolvedValue({
      current_revision_id: "rev-1",
      revision: { id: "rev-1" },
    })
    getBulkSelection("outline-threads").add("thread-1")

    await showOutlineLayerAiForm("plot_thread")

    expect(bridge.showModalHtml).toHaveBeenCalledOnce()
    const html = bridge.showModalHtml.mock.calls[0][1]
    expect(html).toContain('<option value="revise" selected>')
    expect(html).toContain("当前已明确选择 1 个剧情线")
  })

  it("showModalHtml 有总纲时被调用", async () => {
    const showModalHtml = vi.fn()
    setupBridge({
      api: { outline: { getStoryOutline: vi.fn(async () => ({ current_revision_id: "r1", revision: { title: "总纲" } })) } },
      showModalHtml,
    })
    await showOutlineLayerAiForm("plot_thread")
    expect(showModalHtml).toHaveBeenCalled()
    const args = showModalHtml.mock.calls[0]
    expect(args[0]).toContain("AI 创作剧情线")
    expect(args[1]).toContain("outline-layer-mode")
    expect(args[1]).toContain("outline-layer-instruction")
  })
})

// ═══════════════════════════════════════════════════════════════════════
// generateOutlineLayer
// ═══════════════════════════════════════════════════════════════════════

describe("generateOutlineLayer", () => {
  it("取消 AI 参考资料时保持 reject 契约但不显示错误 toast", async () => {
    confirmAiReference.mockRejectedValue(new Error("已取消 AI 参考资料确认"))
    const generate = vi.fn()
    const toast = vi.fn()
    setupBridge({ api: { outline: { getStoryOutline: vi.fn(), generate } }, toast })
    await expect(generateOutlineLayer({
      target: "plot_thread", mode: "create", instruction: "取消", selectedIds: [], startChapter: 1, endChapter: 2,
    })).rejects.toThrow("已取消 AI 参考资料确认")
    expect(generate).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })

  it("提交成功并 adopt 到 manager", async () => {
    confirmAiReference.mockResolvedValue({ id: "confirm-1" })
    const generate = vi.fn(async () => ({ task_id: "task-gen1", status: "running" }))
    const toast = vi.fn()
    setupBridge({
      api: { outline: { getStoryOutline: vi.fn(), generate } },
      toast,
    })
    await generateOutlineLayer({
      target: "plot_thread",
      mode: "create",
      instruction: "写个主线",
      selectedIds: [],
      startChapter: 1,
      endChapter: 10,
    })
    expect(confirmAiReference).toHaveBeenCalled()
    expect(generate).toHaveBeenCalledWith(expect.objectContaining({
      contract_version: "outline_layer_v2",
      target: "plot_thread",
      mode: "create",
      instruction: "写个主线",
    }))
    expect(outlineGenerateManager.state.taskId).toBe("task-gen1")
    expect(clearActiveWorkflow).toHaveBeenCalledOnce()
    expect(clearActiveWorkflow).toHaveBeenCalledWith(expect.not.stringMatching(/^task-/))
    expect(toast).toHaveBeenCalledWith("剧情线建议生成任务已提交", "success")
  })

  it("参考确认期间切换项目时不向新项目提交", async () => {
    let resolveConfirmation
    confirmAiReference.mockImplementation(() => new Promise((resolve) => { resolveConfirmation = resolve }))
    const generate = vi.fn()
    const bridge = setupBridge({ api: { outline: { generate } } })
    const pending = generateOutlineLayer({
      target: "plot_thread", mode: "create", instruction: "只属于旧项目", selectedIds: [], startChapter: 1, endChapter: 3,
    })
    await Promise.resolve()
    bridge.state.currentProjectId = "p-next"
    resolveConfirmation({ id: "confirm-old" })

    await expect(pending).rejects.toThrow("项目已切换")
    expect(generate).not.toHaveBeenCalled()
  })

  it("提交响应返回前切换项目时只为原项目保留恢复记录", async () => {
    confirmAiReference.mockResolvedValue({ id: "confirm-old" })
    let resolveGenerate
    const generate = vi.fn(() => new Promise((resolve) => { resolveGenerate = resolve }))
    const bridge = setupBridge({ api: { outline: { generate } } })
    const pending = generateOutlineLayer({
      target: "plot_thread", mode: "create", instruction: "后台任务", selectedIds: [], startChapter: 1, endChapter: 3,
    })
    await vi.waitFor(() => expect(generate).toHaveBeenCalledOnce())
    bridge.state.currentProjectId = "p-next"
    resolveGenerate({ task_id: "task-old", status: "running" })
    await expect(pending).resolves.toMatchObject({ task_id: "task-old" })
    expect(persistActiveWorkflow).toHaveBeenCalledWith(expect.objectContaining({
      taskId: "task-old", projectId: "p-test", workflowType: "outline_generate",
    }))
    expect(outlineGenerateManager.state.taskId).toBeNull()
  })
})

// ═══════════════════════════════════════════════════════════════════════
// showOutlineGeneratePreview / applyOutlineGeneratePreview
// ═══════════════════════════════════════════════════════════════════════

describe("showOutlineGeneratePreview", () => {
  it("无 preview 时 toast 提示", () => {
    const toast = vi.fn()
    setupBridge({ toast })
    showOutlineGeneratePreview()
    expect(toast).toHaveBeenCalledWith("当前没有可采用的当前层建议", "warning")
  })

  it("剧情线 preview 进入可刷新审阅页", () => {
    const router = { refresh: vi.fn(), navigate: vi.fn(), getCurrentQuery: vi.fn(() => new URLSearchParams("status=draft")) }
    const showModalHtml = vi.fn()
    setupBridge({ showModalHtml, router })
    outlineGenerateManager.state.preview = {
      sourceTaskId: "st1",
      contextConfirmationId: "cc1",
      draftStructure: { threads: [{ name: "主线" }] },
      warnings: [],
      target: "plot_thread",
      mode: "create",
      overlap: {},
    }
    showOutlineGeneratePreview()
    expect(showModalHtml).not.toHaveBeenCalled()
    expect(router.navigate).toHaveBeenCalledWith("outline", "threads", true, expect.any(URLSearchParams))
    expect(router.navigate.mock.calls[0][3].toString()).toContain("review=ai")
    expect(router.navigate.mock.calls[0][3].toString()).toContain("status=draft")
  })

  it("篇章 preview 进入可刷新审阅页", () => {
    const router = { navigate: vi.fn(), getCurrentQuery: vi.fn(() => new URLSearchParams("status=draft")) }
    const showModalHtml = vi.fn()
    setupBridge({ showModalHtml, router })
    outlineGenerateManager.state.preview = {
      sourceTaskId: "st1",
      contextConfirmationId: "cc1",
      draftStructure: { arcs: [{ title: "第一部" }] },
      warnings: [],
      target: "outline_arc",
      mode: "create",
      overlap: {},
    }
    showOutlineGeneratePreview()
    expect(showModalHtml).not.toHaveBeenCalled()
    expect(router.navigate).toHaveBeenCalledWith("outline", "arcs", true, expect.any(URLSearchParams))
    expect(router.navigate.mock.calls[0][3].toString()).toContain("review=ai")
    expect(router.navigate.mock.calls[0][3].toString()).toContain("status=draft")
  })

  it("场景 preview 进入可刷新审阅页", () => {
    const router = { navigate: vi.fn(), getCurrentQuery: vi.fn(() => new URLSearchParams("status=draft")) }
    const showModalHtml = vi.fn()
    setupBridge({ showModalHtml, router })
    outlineGenerateManager.state.preview = {
      sourceTaskId: "st1",
      contextConfirmationId: "cc1",
      draftStructure: { scenes: [{ title: "开场" }] },
      warnings: [],
      target: "planned_scene",
      mode: "create",
      overlap: {},
    }
    showOutlineGeneratePreview()
    expect(showModalHtml).not.toHaveBeenCalled()
    expect(router.navigate).toHaveBeenCalledWith("outline", "scenes", true, expect.any(URLSearchParams))
    expect(router.navigate.mock.calls[0][3].toString()).toContain("review=ai")
    expect(router.navigate.mock.calls[0][3].toString()).toContain("status=draft")
  })
})

describe("applyOutlineGeneratePreview", () => {
  it("旧项目页的采用响应不改动新页面或新预览", async () => {
    let resolveApply
    const applyStructurePreview = vi.fn(() => new Promise((resolve) => { resolveApply = resolve }))
    const bridge = setupBridge({ api: { outline: { applyStructurePreview } } })
    const oldPreview = {
      sourceTaskId: "st-old",
      contextConfirmationId: "cc-old",
      draftStructure: { threads: [] },
      target: "plot_thread",
    }
    outlineGenerateManager.state.preview = oldPreview

    const pending = applyOutlineGeneratePreview({ threads: [] })
    await vi.waitFor(() => expect(applyStructurePreview).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p-test",
      source_task_id: "st-old",
    })))

    const newPreview = { ...oldPreview, sourceTaskId: "st-new" }
    bridge.state.currentProjectId = "p-next"
    bridge.state.currentSubView = "arcs"
    outlineGenerateManager.state.preview = newPreview
    resolveApply({ target: "plot_thread", total_threads: 1 })

    await expect(pending).resolves.toBe(true)
    expect(outlineGenerateManager.state.preview).toMatchObject({ sourceTaskId: "st-new" })
    expect(bridge.closeModal).not.toHaveBeenCalled()
    expect(bridge.toast).not.toHaveBeenCalled()
    expect(bridge.router.refresh).not.toHaveBeenCalled()
  })

  it("当前预览采用失败时保留审阅页并返回 false", async () => {
    const bridge = setupBridge({
      api: { outline: { applyStructurePreview: vi.fn(async () => { throw new Error("版本冲突") }) } },
    })
    outlineGenerateManager.state.preview = {
      sourceTaskId: "st-current",
      contextConfirmationId: "cc-current",
      draftStructure: { threads: [] },
      target: "plot_thread",
    }

    await expect(applyOutlineGeneratePreview({ threads: [] })).resolves.toBe(false)
    expect(bridge.toast).toHaveBeenCalledWith("版本冲突", "error")
    expect(bridge.closeModal).not.toHaveBeenCalled()
    expect(bridge.router.refresh).not.toHaveBeenCalled()
  })

  it("结构化审阅页直接提交编辑后的 draft 且不关闭其他模态", async () => {
    const applyStructurePreview = vi.fn(async () => ({ target: "plot_thread", total_threads: 1 }))
    const bridge = setupBridge({ api: { outline: { applyStructurePreview } } })
    outlineGenerateManager.state.preview = {
      sourceTaskId: "st-page",
      contextConfirmationId: "cc-page",
      draftStructure: { threads: [{ name: "AI 原稿" }] },
      target: "plot_thread",
    }
    const edited = { result: "proposed", threads: [{ name: "作者修改" }] }

    await expect(applyOutlineGeneratePreview(edited)).resolves.toMatchObject({ total_threads: 1 })
    expect(applyStructurePreview).toHaveBeenCalledWith({
      novel_id: "p-test",
      context_confirmation_id: "cc-page",
      source_task_id: "st-page",
      draft_structure: edited,
      confirmed: true,
    })
    expect(bridge.closeModal).not.toHaveBeenCalled()
    expect(bridge.router.refresh).not.toHaveBeenCalled()
  })
})

// ═══════════════════════════════════════════════════════════════════════
// showOutlineAnalysisForm
// ═══════════════════════════════════════════════════════════════════════

describe("showOutlineAnalysisForm", () => {
  it("已有运行中任务时提示", () => {
    const toast = vi.fn()
    setupBridge({ toast })
    outlineAnalysisManager.state.progress = { terminal: false, status: "running" }
    showOutlineAnalysisForm()
    expect(toast).toHaveBeenCalledWith("已有大纲分析任务正在处理", "info")
  })

  it("正常显示表单", () => {
    const showModalHtml = vi.fn()
    setupBridge({ showModalHtml })
    showOutlineAnalysisForm()
    expect(showModalHtml).toHaveBeenCalled()
    const args = showModalHtml.mock.calls[0]
    expect(args[0]).toBe("AI 分析大纲")
    expect(args[1]).toContain("outline-analysis-instruction")
    expect(args[1]).toContain("outline-analysis-start")
  })
})

// ═══════════════════════════════════════════════════════════════════════
// analyzeOutline
// ═══════════════════════════════════════════════════════════════════════

describe("analyzeOutline", () => {
  it("取消 AI 参考资料时保持 reject 契约但不显示错误 toast", async () => {
    confirmAiReference.mockRejectedValue(new Error("已取消 AI 参考资料确认"))
    const analyze = vi.fn()
    const toast = vi.fn()
    setupBridge({ api: { outline: { analyze } }, toast })
    await expect(analyzeOutline({ instruction: "取消", startChapter: 1, endChapter: 2 }))
      .rejects.toThrow("已取消 AI 参考资料确认")
    expect(analyze).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })

  it("成功提交并 adopt 到 manager", async () => {
    confirmAiReference.mockResolvedValue({
      id: "ca-1",
      compile_options: { chapter_index: 3, visible_until_chapter: 8 },
      sections: [{ key: "ref", title: "参考" }],
    })
    const analyze = vi.fn(async () => ({ task_id: "task-ana1", status: "running" }))
    const toast = vi.fn()
    setupBridge({
      api: { outline: { analyze } },
      toast,
    })
    await analyzeOutline({
      instruction: "检查节奏",
      startChapter: 3,
      endChapter: 8,
    })
    expect(confirmAiReference).toHaveBeenCalled()
    expect(analyze).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p-test",
      start_chapter: 3,
      end_chapter: 8,
    }))
    expect(outlineAnalysisManager.state.taskId).toBe("task-ana1")
    expect(toast).toHaveBeenCalledWith("大纲分析任务已提交", "success")
  })

  it("参考确认与 enqueue 期间阻止重复提交", async () => {
    let resolveConfirmation
    confirmAiReference.mockImplementation(() => new Promise((resolve) => { resolveConfirmation = resolve }))
    const analyze = vi.fn(async () => ({ task_id: "task-lock", status: "running" }))
    setupBridge({ api: { outline: { analyze } } })

    const first = analyzeOutline({ instruction: "", startChapter: 1, endChapter: 2 })
    await Promise.resolve()
    await expect(analyzeOutline({ instruction: "", startChapter: 1, endChapter: 2 }))
      .rejects.toThrow("大纲分析正在提交")

    resolveConfirmation({
      id: "confirm-lock",
      compile_options: { chapter_index: 1, visible_until_chapter: 2 },
      sections: [],
    })
    await first
    expect(analyze).toHaveBeenCalledOnce()
    expect(outlineAnalysisManager.state.submitting).toBe(false)
  })

  it("提交锁归属发起项目，切换项目可重置", async () => {
    let resolveConfirmation
    confirmAiReference.mockImplementation(() => new Promise((resolve) => { resolveConfirmation = resolve }))
    const bridge = setupBridge()
    const pending = analyzeOutline({ instruction: "", startChapter: 1, endChapter: 2 })
    await Promise.resolve()
    expect(outlineAnalysisManager.state.ownerProjectId).toBe("p-test")
    bridge.state.currentProjectId = "p-next"
    outlineAnalysisManager.recover("p-next")
    expect(outlineAnalysisManager.state.submitting).toBe(false)
    expect(outlineAnalysisManager.state.ownerProjectId).toBeNull()
    resolveConfirmation({ id: "confirm-old", compile_options: {}, sections: [] })
    await expect(pending).rejects.toThrow("项目已切换")
  })
})

// ═══════════════════════════════════════════════════════════════════════
// cancelOutlineAnalysisTask
// ═══════════════════════════════════════════════════════════════════════

describe("cancelOutlineAnalysisTask", () => {
  it("调用 confirmAction 后取消任务", async () => {
    const tasksCancel = vi.fn(async () => {})
    const toast = vi.fn()
    let confirmHandler = null
    const confirmAction = vi.fn((_msg, handler) => { confirmHandler = handler })
    setupBridge({
      api: { tasks: { cancel: tasksCancel } },
      toast,
      confirmAction,
    })
    outlineAnalysisManager.state.taskId = "task-c1"
    outlineAnalysisManager.state.meta = { project_id: "p-test" }

    cancelOutlineAnalysisTask()
    expect(confirmAction).toHaveBeenCalled()

    // 执行 confirm handler
    await confirmHandler()
    expect(tasksCancel).toHaveBeenCalledWith("task-c1", "p-test")
  })
})

// ═══════════════════════════════════════════════════════════════════════
// showPlotStructureAutoExtractForm
// ═══════════════════════════════════════════════════════════════════════

describe("showPlotStructureAutoExtractForm", () => {
  it("显示提取表单并提交任务", async () => {
    const startStage = vi.fn(async () => ({ task_id: "task-plot1", status: "running" }))
    const showModalHtml = vi.fn()
    const closeModal = vi.fn()
    const toast = vi.fn()
    setupBridge({
      api: { imports: { startStage } },
      showModalHtml,
      closeModal,
      toast,
    })

    showPlotStructureAutoExtractForm()
    expect(showModalHtml).toHaveBeenCalled()
    const args = showModalHtml.mock.calls[0]
    expect(args[0]).toBe("从正文提取剧情线")
    expect(args[1]).toContain("plot-auto-extract-start")

    // 模拟表单值并执行 handler
    document.body.innerHTML = `
      <input id="plot-auto-extract-start" value="1" />
      <input id="plot-auto-extract-end" value="5" />
    `
    const handler = args[2][0].handler
    await handler()

    expect(startStage).toHaveBeenCalledWith(
      "plot_structure",
      "p-test",
      1,
      5,
      false,
      false,
      { authorization: "confirmed" },
    )
    expect(closeModal).toHaveBeenCalled()
    expect(plotAutoExtractManager.state.taskId).toBe("task-plot1")
  })

  it("严格拒绝非正整数和倒序章节范围", async () => {
    const startStage = vi.fn()
    const showModalHtml = vi.fn()
    const toast = vi.fn()
    setupBridge({ api: { imports: { startStage } }, showModalHtml, toast })
    showPlotStructureAutoExtractForm()
    const handler = showModalHtml.mock.calls[0][2][0].handler
    document.body.innerHTML = `
      <input id="plot-auto-extract-start" value="1.5" />
      <input id="plot-auto-extract-end" value="5" />
    `

    await expect(handler()).resolves.toBe(false)
    expect(toast).toHaveBeenLastCalledWith("章节范围必须是正整数", "warning")

    document.getElementById("plot-auto-extract-start").value = "0"
    await expect(handler()).resolves.toBe(false)
    expect(toast).toHaveBeenLastCalledWith("章节范围必须是正整数", "warning")

    document.getElementById("plot-auto-extract-start").value = "6"
    await expect(handler()).resolves.toBe(false)
    expect(toast).toHaveBeenLastCalledWith("结束章节必须 ≥ 起始章节", "warning")
    expect(startStage).not.toHaveBeenCalled()
  })

  it("同步双击只提交一次，并在完成后释放锁", async () => {
    let resolveStart
    const startStage = vi.fn(() => new Promise((resolve) => { resolveStart = resolve }))
    const showModalHtml = vi.fn()
    setupBridge({
      api: { imports: { startStage } },
      showModalHtml,
      closeModal: vi.fn(),
      toast: vi.fn(),
    })
    showPlotStructureAutoExtractForm()
    document.body.innerHTML = `
      <input id="plot-auto-extract-start" value="1" />
      <input id="plot-auto-extract-end" value="5" />
    `
    const handler = showModalHtml.mock.calls[0][2][0].handler

    const first = handler()
    const second = handler()
    await expect(second).resolves.toBe(false)
    expect(startStage).toHaveBeenCalledTimes(1)
    expect(plotAutoExtractManager.state.submitting).toBe(true)
    resolveStart({ task_id: "task-plot-double", status: "running" })
    await expect(first).resolves.toBe(true)
    expect(plotAutoExtractManager.state.submitting).toBe(false)
  })

  it("响应前切换项目时任务持久化到原项目且不接管新项目 UI", async () => {
    let resolveStart
    const startStage = vi.fn(() => new Promise((resolve) => { resolveStart = resolve }))
    const showModalHtml = vi.fn()
    const bridge = setupBridge({ api: { imports: { startStage } }, showModalHtml, closeModal: vi.fn(), toast: vi.fn() })
    showPlotStructureAutoExtractForm()
    document.body.innerHTML = `
      <input id="plot-auto-extract-start" value="2" />
      <input id="plot-auto-extract-end" value="6" />
    `
    const pending = showModalHtml.mock.calls[0][2][0].handler()
    bridge.state.currentProjectId = "p-next"
    recoverActiveWorkflows.mockReturnValue([])
    plotAutoExtractManager.recover("p-next")
    resolveStart({ task_id: "task-plot-old", status: "running" })
    await expect(pending).resolves.toBe(true)

    expect(persistActiveWorkflow).toHaveBeenCalledWith(expect.objectContaining({
      taskId: "task-plot-old",
      projectId: "p-test",
    }))
    expect(plotAutoExtractManager.state.taskId).toBeNull()
    expect(plotAutoExtractManager.state.submitting).toBe(false)
  })
})
