/**
 * outlineWorkflowManagers 测试 — outlineGenerate / outlineAnalysis / plotAutoExtract
 * 三条轮询线的 adopt / recover / 终态语义。
 * 管理器为模块级单例，beforeEach 手动复位。
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
  }
})

vi.mock("../../../../shared/aiReferenceModal.js", () => ({
  confirmAiReference: vi.fn(),
}))

import {
  clearActiveWorkflow,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../../../../shared/workflowProgress.js"

import {
  outlineGenerateManager,
  outlineAnalysisManager,
  plotAutoExtractManager,
  captureOutlineGeneratePreview,
  resetOutlineGenerateState,
  resetOutlineAnalysisState,
  clearOutlineGenerateWorkflowsForTarget,
  outlineAnalysisContextSummary,
  plotAutoExtractLabel,
} from "../../../../vue/views/outline/ai/outlineWorkflowManagers.js"

import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"

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
})

afterEach(() => {
  resetBridgeOverrides()
})

// ═══════════════════════════════════════════════════════════════════════
// outlineGenerateManager
// ═══════════════════════════════════════════════════════════════════════

describe("outlineGenerateManager", () => {
  describe("adopt", () => {
    it("写入 reactive state、持久化 localStorage 并开始轮询", () => {
      setBridgeOverrides({ state: { currentProjectId: "p-gen" } })
      outlineGenerateManager.adopt(
        { task_id: "task-g1", status: "running" },
        { target: "plot_thread", mode: "create", label: "剧情线" },
      )

      expect(outlineGenerateManager.state.taskId).toBe("task-g1")
      expect(outlineGenerateManager.state.status).toBe("运行中")
      expect(outlineGenerateManager.state.meta).toEqual({ target: "plot_thread", mode: "create", label: "剧情线" })
      expect(persistActiveWorkflow).toHaveBeenCalledWith(expect.objectContaining({
        taskId: "task-g1",
        workflowType: "outline_generate",
        projectId: "p-gen",
        view: "outline",
        meta: { target: "plot_thread", mode: "create", label: "剧情线" },
      }))
      expect(pollTaskProgress).toHaveBeenCalledWith(expect.objectContaining({
        taskId: "task-g1",
        workflowType: "outline_generate",
      }))
    })
  })

  describe("recover", () => {
    it("无当前项目时不读取或恢复任何持久化任务", () => {
      recoverActiveWorkflows.mockReturnValue([
        { taskId: "task-other-project", workflowType: "outline_generate", view: "outline" },
      ])

      outlineGenerateManager.recover(null)

      expect(recoverActiveWorkflows).not.toHaveBeenCalled()
      expect(outlineGenerateManager.state.taskId).toBeNull()
      expect(pollTaskProgress).not.toHaveBeenCalled()
    })

    it("无持久化记录时不动作", () => {
      setBridgeOverrides({ state: { currentProjectId: "p-rec", currentSubView: "threads", currentView: "outline" } })
      recoverActiveWorkflows.mockReturnValue([])
      outlineGenerateManager.recover("p-rec")
      expect(outlineGenerateManager.state.taskId).toBeNull()
      expect(pollTaskProgress).not.toHaveBeenCalled()
    })

    it("匹配 outline_generate 且 target 与当前 subView target 一致", () => {
      setBridgeOverrides({ state: { currentProjectId: "p-rec", currentSubView: "threads", currentView: "outline" } })
      recoverActiveWorkflows.mockReturnValue([
        { taskId: "task-rec", workflowType: "outline_generate", meta: { target: "plot_thread" }, updatedAt: "2026-01-01T00:00:00Z" },
        { taskId: "task-wrong", workflowType: "outline_generate", meta: { target: "outline_arc" }, updatedAt: "2026-01-01T00:01:00Z" },
      ])
      outlineGenerateManager.recover("p-rec")
      expect(outlineGenerateManager.state.taskId).toBe("task-rec")
    })

    it("未终结任务在轮询中时 recover 不重复启动", () => {
      setBridgeOverrides({ state: { currentProjectId: "p-dedupe", currentSubView: "threads", currentView: "outline" } })
      outlineGenerateManager.adopt(
        { task_id: "task-live", status: "running" },
        { target: "plot_thread" },
      )
      recoverActiveWorkflows.mockReturnValue([
        { taskId: "task-live", workflowType: "outline_generate", meta: { target: "plot_thread" } },
      ])
      outlineGenerateManager.recover("p-dedupe")
      expect(pollTaskProgress).toHaveBeenCalledTimes(1)
    })

    it("切换结构层时停止上一层轮询并恢复当前 target", () => {
      const state = { currentProjectId: "p-scope", currentSubView: "threads", currentView: "outline" }
      setBridgeOverrides({ state })
      outlineGenerateManager.adopt(
        { task_id: "task-thread", status: "running" },
        { target: "plot_thread" },
      )
      const firstPoller = vi.mocked(pollTaskProgress).mock.results[0].value
      recoverActiveWorkflows.mockReturnValue([
        { taskId: "task-arc", workflowType: "outline_generate", projectId: "p-scope", meta: { target: "outline_arc" } },
      ])

      state.currentSubView = "arcs"
      outlineGenerateManager.recover("p-scope")

      expect(firstPoller.stop).toHaveBeenCalled()
      expect(outlineGenerateManager.state.taskId).toBe("task-arc")
      expect(outlineGenerateManager.state.meta).toEqual({ target: "outline_arc" })
      expect(pollTaskProgress).toHaveBeenCalledTimes(2)
    })
  })

  describe("captureOutlineGeneratePreview", () => {
    it("返回 null 当 task_type 不匹配", () => {
      const result = captureOutlineGeneratePreview(
        { task_id: "t1", task_type: "outline_analyze", result: { draft_structure: {} } },
        null,
      )
      expect(result).toBeNull()
      expect(outlineGenerateManager.state.preview).toBeNull()
    })

    it("返回 null 当缺少必需的字段", () => {
      const result = captureOutlineGeneratePreview(
        { task_id: "t1", task_type: "outline_generate", result: { requires_apply: true, draft_structure: { foo: "bar" } } },
        null,
      )
      expect(result).toBeNull()
    })

    it("返回 preview 对象当字段完整", () => {
      outlineGenerateManager.state.taskId = "t1"
      outlineGenerateManager.state.meta = { context_confirmation_id: "cc-1", target: "plot_thread" }
      const result = captureOutlineGeneratePreview(
        {
          task_id: "t1",
          task_type: "outline_generate",
          result: {
            source_task_id: "st1",
            context_confirmation_id: "cc-1",
            requires_apply: true,
            draft_structure: { threads: [{ title: "主线" }] },
            target: "plot_thread",
            mode: "create",
            overlap: {},
            warnings: ["注意"],
          },
        },
        null,
      )
      expect(result).not.toBeNull()
      expect(result.sourceTaskId).toBe("st1")
      expect(result.contextConfirmationId).toBe("cc-1")
      expect(result.draftStructure).toEqual({ threads: [{ title: "主线" }] })
      expect(result.warnings).toEqual(["注意"])
      expect(outlineGenerateManager.state.preview).toBe(result)
    })
  })

  describe("轮询终态", () => {
    it("done 时从任务结果捕获可采用预览并保留 workflow", async () => {
      const toast = vi.fn()
      setBridgeOverrides({ state: { currentProjectId: "p-done" }, toast })
      outlineGenerateManager.adopt(
        { task_id: "task-done", status: "running" },
        { context_confirmation_id: "cc-done", target: "plot_thread", label: "剧情线" },
      )
      const callbacks = vi.mocked(pollTaskProgress).mock.calls[0][0]
      const progress = { taskId: "task-done", done: true, terminal: true, raw: {} }
      const task = {
        task_id: "task-done",
        task_type: "outline_generate",
        result: {
          requires_apply: true,
          source_task_id: "task-done",
          context_confirmation_id: "cc-done",
          target: "plot_thread",
          draft_structure: { threads: [{ title: "主线" }] },
        },
      }

      callbacks.onDone(progress, task)
      await Promise.resolve()

      expect(outlineGenerateManager.state.preview).toEqual(expect.objectContaining({
        sourceTaskId: "task-done",
        contextConfirmationId: "cc-done",
        draftStructure: { threads: [{ title: "主线" }] },
      }))
      expect(outlineGenerateManager.state.taskId).toBe("task-done")
      expect(clearActiveWorkflow).not.toHaveBeenCalled()
      expect(toast).toHaveBeenCalledWith("剧情线建议已生成，请检查后再采用", "info")
    })

    it("done 但没有可采用结构时清理 workflow", async () => {
      const toast = vi.fn()
      setBridgeOverrides({ state: { currentProjectId: "p-empty" }, toast })
      outlineGenerateManager.adopt(
        { task_id: "task-empty", status: "running" },
        { context_confirmation_id: "cc-empty", target: "plot_thread" },
      )
      const callbacks = vi.mocked(pollTaskProgress).mock.calls[0][0]

      callbacks.onDone(
        { taskId: "task-empty", done: true, terminal: true, raw: {} },
        { task_id: "task-empty", task_type: "outline_generate", result: { requires_apply: false } },
      )
      await Promise.resolve()

      expect(outlineGenerateManager.state.preview).toBeNull()
      expect(outlineGenerateManager.state.taskId).toBeNull()
      expect(clearActiveWorkflow).toHaveBeenCalledWith("task-empty")
    })
  })

  describe("resetOutlineGenerateState", () => {
    it("清空全部状态", () => {
      outlineGenerateManager.state.taskId = "t1"
      outlineGenerateManager.state.status = "运行中"
      outlineGenerateManager.state.preview = { draftStructure: {} }
      outlineGenerateManager.state.progress = { done: false }
      outlineGenerateManager.state.meta = { target: "plot_thread" }

      resetOutlineGenerateState()

      expect(outlineGenerateManager.state.taskId).toBeNull()
      expect(outlineGenerateManager.state.status).toBe("就绪")
      expect(outlineGenerateManager.state.meta).toBeNull()
      expect(outlineGenerateManager.state.progress).toBeNull()
      expect(outlineGenerateManager.state.preview).toBeNull()
    })
  })

  describe("clearOutlineGenerateWorkflowsForTarget", () => {
    it("清除指定 target 的所有持久化 workflow", () => {
      setBridgeOverrides({ state: { currentProjectId: "p-clr" } })
      recoverActiveWorkflows.mockReturnValue([
        { taskId: "w1", workflowType: "outline_generate", meta: { target: "plot_thread" } },
        { taskId: "w2", workflowType: "outline_generate", meta: { target: "outline_arc" } },
        { taskId: "w3", workflowType: "outline_analyze" },
      ])
      clearOutlineGenerateWorkflowsForTarget("plot_thread")
      expect(clearActiveWorkflow).toHaveBeenCalledTimes(1)
      expect(clearActiveWorkflow).toHaveBeenCalledWith("w1")
    })
  })
})

// ═══════════════════════════════════════════════════════════════════════
// outlineAnalysisManager
// ═══════════════════════════════════════════════════════════════════════

describe("outlineAnalysisManager", () => {
  describe("adopt", () => {
    it("使用 novelId 参数启动轮询", () => {
      setBridgeOverrides({ state: { currentProjectId: "p-ana" } })
      outlineAnalysisManager.adopt(
        { task_id: "task-a1", status: "running" },
        { project_id: "p-ana", start_chapter: 1, end_chapter: 5 },
      )
      expect(pollTaskProgress).toHaveBeenCalledWith(expect.objectContaining({
        taskId: "task-a1",
        workflowType: "outline_analyze",
        novelId: "p-ana",
      }))
    })
  })

  describe("recover", () => {
    it("匹配 outline_analyze 且 projectId 一致", () => {
      setBridgeOverrides({ state: { currentProjectId: "p-ana", currentView: "outline" } })
      recoverActiveWorkflows.mockReturnValue([
        { taskId: "task-a1", workflowType: "outline_analyze", projectId: "p-ana", updatedAt: "2026-01-01T00:00:00Z" },
        { taskId: "task-wrong-project", workflowType: "outline_analyze", projectId: "p-other", updatedAt: "2026-01-01T00:01:00Z" },
      ])
      outlineAnalysisManager.recover("p-ana")
      expect(outlineAnalysisManager.state.taskId).toBe("task-a1")
    })

    it("切换项目时不让旧项目轮询阻塞新项目恢复", () => {
      const state = { currentProjectId: "p-old", currentView: "outline", currentSubView: "threads" }
      setBridgeOverrides({ state })
      outlineAnalysisManager.adopt(
        { task_id: "task-old", status: "running" },
        { project_id: "p-old" },
      )
      const firstPoller = vi.mocked(pollTaskProgress).mock.results[0].value
      recoverActiveWorkflows.mockReturnValue([
        { taskId: "task-new", workflowType: "outline_analyze", projectId: "p-new", meta: { project_id: "p-new" } },
      ])

      state.currentProjectId = "p-new"
      outlineAnalysisManager.recover("p-new")

      expect(firstPoller.stop).toHaveBeenCalled()
      expect(outlineAnalysisManager.state.taskId).toBe("task-new")
      expect(outlineAnalysisManager.state.ownerProjectId).toBe("p-new")
    })
  })

  describe("终态处理", () => {
    it("done 时捕获分析结果", async () => {
      setBridgeOverrides({
        state: { currentProjectId: "p-term", currentView: "outline" },
        toast: vi.fn(),
      })
      outlineAnalysisManager.adopt(
        { task_id: "task-ad", status: "running" },
        { context_summary: { sections: [{ key: "ref", title: "参考资料" }] } },
      )
      const { onDone } = pollTaskProgress.mock.calls[0][0]
      await onDone({
        taskId: "task-ad",
        done: true,
        terminal: true,
        raw: { result: { analysis: "## 分析结论\n大纲结构完整。" } },
      })
      expect(outlineAnalysisManager.state.result).toEqual({
        markdown: "## 分析结论\n大纲结构完整。",
        contextSummary: { sections: [{ key: "ref", title: "参考资料" }] },
      })
    })

    it("done 但无分析内容时清除 workflow", async () => {
      const toast = vi.fn()
      setBridgeOverrides({
        state: { currentProjectId: "p-empty", currentView: "outline" },
        toast,
      })
      outlineAnalysisManager.adopt(
        { task_id: "task-empty", status: "running" },
        {},
      )
      const { onDone } = pollTaskProgress.mock.calls[0][0]
      await onDone({ taskId: "task-empty", done: true, terminal: true, raw: { result: {} } })
      expect(clearActiveWorkflow).toHaveBeenCalledWith("task-empty")
      expect(outlineAnalysisManager.state.result).toBeNull()
      expect(toast).toHaveBeenCalledWith("大纲分析完成，但没有返回可展示的内容", "info")
    })

    it("failed 时 toast 报错", async () => {
      const toast = vi.fn()
      setBridgeOverrides({
        state: { currentProjectId: "p-fail", currentView: "outline" },
        toast,
      })
      outlineAnalysisManager.adopt(
        { task_id: "task-fail", status: "running" },
        {},
      )
      const { onFailed } = pollTaskProgress.mock.calls[0][0]
      await onFailed({ taskId: "task-fail", failed: true, terminal: true, errorMessage: "模型超时" })
      expect(toast).toHaveBeenCalledWith("大纲分析失败: 模型超时", "error")
    })
  })

  describe("resetOutlineAnalysisState", () => {
    it("清空所有分析状态", () => {
      outlineAnalysisManager.state.taskId = "t1"
      outlineAnalysisManager.state.result = { markdown: "test" }
      outlineAnalysisManager.state.progress = { done: true }

      resetOutlineAnalysisState({ clearWorkflowState: false })

      expect(outlineAnalysisManager.state.taskId).toBeNull()
      expect(outlineAnalysisManager.state.status).toBe("就绪")
      expect(outlineAnalysisManager.state.result).toBeNull()
      expect(outlineAnalysisManager.state.progress).toBeNull()
    })
  })
})

// ═══════════════════════════════════════════════════════════════════════
// plotAutoExtractManager
// ═══════════════════════════════════════════════════════════════════════

describe("plotAutoExtractManager", () => {
  describe("adopt", () => {
    it("写入 reactive state 并开始轮询", () => {
      setBridgeOverrides({ state: { currentProjectId: "p-ext" } })
      plotAutoExtractManager.adopt(
        { task_id: "task-p1", status: "running" },
        { start_chapter: 1, end_chapter: 5 },
      )
      expect(plotAutoExtractManager.state.taskId).toBe("task-p1")
      expect(pollTaskProgress).toHaveBeenCalledWith(expect.objectContaining({
        taskId: "task-p1",
        workflowType: "plot_structure_auto_extraction",
      }))
    })
  })

  describe("recover", () => {
    it("优先匹配 view=outline 的记录", () => {
      setBridgeOverrides({ state: { currentProjectId: "p-ext", currentView: "outline" } })
      recoverActiveWorkflows.mockReturnValue([
        { taskId: "task-other", workflowType: "plot_structure_auto_extraction", view: "generate" },
        { taskId: "task-outline", workflowType: "plot_structure_auto_extraction", view: "outline" },
      ])
      plotAutoExtractManager.recover("p-ext")
      expect(plotAutoExtractManager.state.taskId).toBe("task-outline")
    })
  })

  describe("终态处理", () => {
    it("done 时 toast 成功并触发 router.refresh（当前在 outline 视图）", async () => {
      const refresh = vi.fn()
      const toast = vi.fn()
      setBridgeOverrides({
        state: { currentProjectId: "p-ext", currentView: "outline" },
        router: { refresh },
        toast,
      })
      plotAutoExtractManager.adopt({ task_id: "task-pd", status: "running" })
      const { onDone } = pollTaskProgress.mock.calls[0][0]
      await onDone({ taskId: "task-pd", done: true, terminal: true })
      expect(clearActiveWorkflow).toHaveBeenCalledWith("task-pd")
      expect(toast).toHaveBeenCalledWith("剧情线自动提取完成", "success")
      expect(refresh).toHaveBeenCalledTimes(1)
    })

    it("done 但不在 outline 视图时不 refresh", async () => {
      const refresh = vi.fn()
      setBridgeOverrides({
        state: { currentProjectId: "p-away", currentView: "rag" },
        router: { refresh },
        toast: vi.fn(),
      })
      plotAutoExtractManager.adopt({ task_id: "task-away", status: "running" })
      const { onDone } = pollTaskProgress.mock.calls[0][0]
      await onDone({ taskId: "task-away", done: true, terminal: true })
      expect(refresh).not.toHaveBeenCalled()
    })
  })
})

// ═══════════════════════════════════════════════════════════════════════
// 辅助函数
// ═══════════════════════════════════════════════════════════════════════

describe("outlineAnalysisContextSummary", () => {
  it("从 confirmation 提取 sections 和 warnings", () => {
    const confirmation = {
      sections: [
        { key: "threads", title: "剧情线", sources: [{ label: "主线" }, { label: "副线" }] },
        { key: "characters", title: "人物", sources: Array.from({ length: 8 }, (_, i) => ({ label: `人物${i + 1}` })) },
      ],
      warnings: ["缺少第 5 章数据"],
    }
    const result = outlineAnalysisContextSummary(confirmation)
    expect(result.sections).toHaveLength(2)
    expect(result.sections[0].sources).toEqual(["主线", "副线"])
    expect(result.sections[1].sources).toHaveLength(6)
    expect(result.sections[1].sourceCount).toBe(8)
    expect(result.warnings).toEqual(["缺少第 5 章数据"])
  })
})

describe("plotAutoExtractLabel", () => {
  it("threads 返回剧情线", () => {
    expect(plotAutoExtractLabel("threads")).toBe("从正文提取剧情线")
  })
  it("arcs 返回篇章纲", () => {
    expect(plotAutoExtractLabel("arcs")).toBe("从正文提取篇章纲")
  })
  it("默认回落 threads", () => {
    expect(plotAutoExtractLabel()).toBe("从正文提取剧情线")
  })
})
