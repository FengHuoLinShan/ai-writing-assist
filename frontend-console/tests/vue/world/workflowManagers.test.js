/**
 * workflowManagers 测试 — autoExtract / fusion 两条轮询线的 adopt/recover/终态语义。
 * 管理器为模块级单例，beforeEach 手动复位。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"

vi.mock("../../../shared/workflowProgress.js", async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    pollTaskProgress: vi.fn(() => ({ stop: vi.fn() })),
    persistActiveWorkflow: vi.fn(),
    recoverActiveWorkflows: vi.fn(() => []),
    clearActiveWorkflow: vi.fn(),
  }
})

vi.mock("../../../shared/importAuthorization.js", () => ({
  importAuthorizationPayload: vi.fn(() => ({ authorization: "confirmed" })),
  importAuthorizationNotice: vi.fn(() => "导入授权提示"),
}))

import {
  clearActiveWorkflow,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../../../shared/workflowProgress.js"
import {
  autoExtractManager,
  fusionManager,
  startEntityFusionSuggestions,
  submitAutoExtract,
} from "../../../vue/views/world/workflowManagers.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

function resetManagers() {
  for (const manager of [autoExtractManager, fusionManager]) {
    manager.stop()
    manager.state.taskId = null
    manager.state.status = "就绪"
    manager.state.meta = null
    manager.state.progress = null
    manager.state.ownerProjectId = null
    manager.state.submitting = false
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetManagers()
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("adopt", () => {
  it("写入 reactive state、持久化 localStorage 并开始轮询", () => {
    setBridgeOverrides({ state: { currentProjectId: "p-adopt" } })
    autoExtractManager.adopt({ task_id: "task-a1", status: "running" }, { start_chapter: 2, end_chapter: 5 })

    expect(autoExtractManager.state.taskId).toBe("task-a1")
    expect(autoExtractManager.state.status).toBe("运行中")
    expect(autoExtractManager.state.meta).toEqual({ start_chapter: 2, end_chapter: 5 })
    expect(persistActiveWorkflow).toHaveBeenCalledWith(expect.objectContaining({
      taskId: "task-a1",
      workflowType: "world_object_auto_extraction",
      projectId: "p-adopt",
      view: "world",
      meta: { start_chapter: 2, end_chapter: 5 },
    }))
    expect(pollTaskProgress).toHaveBeenCalledWith(expect.objectContaining({
      taskId: "task-a1",
      workflowType: "world_object_auto_extraction",
      novelId: "p-adopt",
    }))
  })
})

describe("recover", () => {
  it("无持久化记录时不动作", () => {
    recoverActiveWorkflows.mockReturnValue([])
    autoExtractManager.recover("p-none")
    expect(autoExtractManager.state.taskId).toBeNull()
    expect(pollTaskProgress).not.toHaveBeenCalled()
  })

  it("无当前项目时不读取或恢复任何持久化任务", () => {
    recoverActiveWorkflows.mockReturnValue([
      { taskId: "task-other-project", workflowType: "world_object_auto_extraction", view: "world" },
    ])

    autoExtractManager.recover(null)

    expect(recoverActiveWorkflows).not.toHaveBeenCalled()
    expect(autoExtractManager.state.taskId).toBeNull()
    expect(pollTaskProgress).not.toHaveBeenCalled()
  })

  it("autoExtract 优先匹配 view=world 的记录，缺省回落同类型", () => {
    recoverActiveWorkflows.mockReturnValue([
      { taskId: "task-other-view", workflowType: "world_object_auto_extraction", view: "generate" },
    ])
    autoExtractManager.recover("p-fallback")
    expect(autoExtractManager.state.taskId).toBe("task-other-view")

    resetManagers()
    vi.clearAllMocks()
    recoverActiveWorkflows.mockReturnValue([
      { taskId: "task-other", workflowType: "world_object_auto_extraction", view: "generate" },
      { taskId: "task-world", workflowType: "world_object_auto_extraction", view: "world" },
    ])
    autoExtractManager.recover("p-prefer-world")
    expect(autoExtractManager.state.taskId).toBe("task-world")
  })

  it("未终结任务在轮询中时 recover 不重复启动", () => {
    setBridgeOverrides({ state: { currentProjectId: "p-dedupe" } })
    autoExtractManager.adopt({ task_id: "task-live", status: "running" })
    recoverActiveWorkflows.mockReturnValue([
      { taskId: "task-live", workflowType: "world_object_auto_extraction", view: "world" },
    ])
    autoExtractManager.recover("p-dedupe")
    expect(pollTaskProgress).toHaveBeenCalledTimes(1)
  })

  it("未终结任务的 poller 已停止时 recover 会按原项目恢复轮询", () => {
    setBridgeOverrides({ state: { currentProjectId: "p-resume" } })
    autoExtractManager.adopt({ task_id: "task-resume", status: "running" })
    autoExtractManager.stop()

    autoExtractManager.recover("p-resume")

    expect(pollTaskProgress).toHaveBeenCalledTimes(2)
    expect(pollTaskProgress).toHaveBeenLastCalledWith(expect.objectContaining({
      taskId: "task-resume",
      novelId: "p-resume",
    }))
  })

  it("切换项目时清理旧内存任务并恢复新项目任务", () => {
    const state = { currentProjectId: "p-old" }
    setBridgeOverrides({ state })
    autoExtractManager.adopt({ task_id: "task-old", status: "running" })
    autoExtractManager.stop()
    recoverActiveWorkflows.mockReturnValue([
      { taskId: "task-new", workflowType: "world_object_auto_extraction", view: "world" },
    ])

    state.currentProjectId = "p-new"
    autoExtractManager.recover("p-new")

    expect(autoExtractManager.state.taskId).toBe("task-new")
    expect(autoExtractManager.state.ownerProjectId).toBe("p-new")
    expect(pollTaskProgress).toHaveBeenLastCalledWith(expect.objectContaining({
      taskId: "task-new",
      novelId: "p-new",
    }))
  })

  it("fusion 只匹配自己的 workflowType", () => {
    recoverActiveWorkflows.mockReturnValue([
      { taskId: "task-x", workflowType: "world_object_auto_extraction", view: "world" },
    ])
    fusionManager.recover("p-type-mismatch")
    expect(fusionManager.state.taskId).toBeNull()
  })
})

describe("终态处理",  () => {
  it("autoExtract done：toast 成功、清持久化、world 视图内触发 refresh", async () => {
    const refresh = vi.fn()
    const toast = vi.fn()
    setBridgeOverrides({
      state: { currentProjectId: "p-term", currentView: "world" },
      router: { refresh },
      toast,
    })
    autoExtractManager.adopt({ task_id: "task-done", status: "running" })
    const { onDone } = pollTaskProgress.mock.calls[0][0]
    await onDone({ taskId: "task-done", done: true, terminal: true })

    expect(clearActiveWorkflow).toHaveBeenCalledWith("task-done")
    expect(autoExtractManager.state.taskId).toBeNull()
    expect(toast).toHaveBeenCalledWith("人物、设定与关系已整理完成", "success")
    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it("autoExtract done 但当前不在 world 视图：不 refresh", async () => {
    const refresh = vi.fn()
    setBridgeOverrides({
      state: { currentProjectId: "p-away", currentView: "rag" },
      router: { refresh },
      toast: vi.fn(),
    })
    autoExtractManager.adopt({ task_id: "task-away", status: "running" })
    const { onDone } = pollTaskProgress.mock.calls[0][0]
    await onDone({ taskId: "task-away", done: true, terminal: true })
    expect(refresh).not.toHaveBeenCalled()
  })

  it("autoExtract failed：toast 报错、不 refresh", async () => {
    const refresh = vi.fn()
    const toast = vi.fn()
    setBridgeOverrides({
      state: { currentProjectId: "p-fail", currentView: "world" },
      router: { refresh },
      toast,
    })
    autoExtractManager.adopt({ task_id: "task-fail", status: "running" })
    const { onFailed } = pollTaskProgress.mock.calls[0][0]
    await onFailed({ taskId: "task-fail", failed: true, terminal: true, errorMessage: "模型超时" })
    expect(toast).toHaveBeenCalledWith("提取任务失败: 模型超时", "error")
    expect(refresh).not.toHaveBeenCalled()
  })

  it("fusion done：progress 保留供\"查看建议\"，不 refresh", async () => {
    const refresh = vi.fn()
    const toast = vi.fn()
    setBridgeOverrides({
      state: { currentProjectId: "p-fusion", currentView: "world" },
      router: { refresh },
      toast,
    })
    fusionManager.adopt({ task_id: "task-fuse" })
    const { onDone } = pollTaskProgress.mock.calls[0][0]
    const doneProgress = { taskId: "task-fuse", done: true, terminal: true, raw: { result: { suggestions: [{}] } } }
    await onDone(doneProgress)
    expect(fusionManager.state.progress).toEqual(doneProgress)
    expect(toast).toHaveBeenCalledWith("世界对象 AI 合并建议已生成", "success")
    expect(refresh).not.toHaveBeenCalled()
  })
})

describe("submitAutoExtract", () => {
  it("无项目 toast 警告且不提交", async () => {
    const toast = vi.fn()
    setBridgeOverrides({ state: { currentProjectId: null }, toast })
    expect(await submitAutoExtract(1, 10)).toBe(false)
    expect(toast).toHaveBeenCalledWith("请先选择项目", "warning")
  })

  it("起始章大于结束章 toast 警告", async () => {
    const toast = vi.fn()
    setBridgeOverrides({ state: { currentProjectId: "p-range" }, toast })
    expect(await submitAutoExtract(9, 2)).toBe(false)
    expect(toast).toHaveBeenCalledWith("起始章节不能大于结束章节", "warning")
  })

  it("成功：startStage 参数与 vanilla 一致并 adopt", async () => {
    const startStage = vi.fn(async () => ({ task_id: "task-submit", status: "running" }))
    setBridgeOverrides({
      api: { imports: { startStage } },
      state: { currentProjectId: "p-submit" },
      toast: vi.fn(),
    })
    expect(await submitAutoExtract(3, 7)).toBe(true)
    expect(startStage).toHaveBeenCalledWith("world_objects", "p-submit", 3, 7, false, false, { authorization: "confirmed" })
    expect(autoExtractManager.state.meta).toEqual({ start_chapter: 3, end_chapter: 7 })
  })

  it("失败：state.status 记录失败并 toast", async () => {
    const toast = vi.fn()
    setBridgeOverrides({
      api: { imports: { startStage: vi.fn(async () => { throw new Error("鉴权失败") }) } },
      state: { currentProjectId: "p-submit-fail" },
      toast,
    })
    expect(await submitAutoExtract(1, 10)).toBe(false)
    expect(autoExtractManager.state.status).toBe("失败: 鉴权失败")
    expect(toast).toHaveBeenCalledWith("鉴权失败", "error")
  })

  it("同步双击只提交一次，并在请求完成后释放提交锁", async () => {
    let resolveStart
    const startStage = vi.fn(() => new Promise((resolve) => { resolveStart = resolve }))
    setBridgeOverrides({
      api: { imports: { startStage } },
      state: { currentProjectId: "p-double" },
      toast: vi.fn(),
    })

    const first = submitAutoExtract(1, 3)
    const second = submitAutoExtract(1, 3)

    expect(await second).toBe(false)
    expect(startStage).toHaveBeenCalledTimes(1)
    expect(autoExtractManager.state.submitting).toBe(true)
    resolveStart({ task_id: "task-double", status: "running" })
    await expect(first).resolves.toBe(true)
    expect(autoExtractManager.state.submitting).toBe(false)
  })

  it("响应前切换项目时只持久化到提交项目，不接管新项目 UI", async () => {
    let resolveStart
    const state = { currentProjectId: "p-old" }
    setBridgeOverrides({
      api: { imports: { startStage: vi.fn(() => new Promise((resolve) => { resolveStart = resolve })) } },
      state,
      toast: vi.fn(),
    })

    const pending = submitAutoExtract(2, 4)
    state.currentProjectId = "p-new"
    recoverActiveWorkflows.mockReturnValue([])
    autoExtractManager.recover("p-new")
    resolveStart({ task_id: "task-old", status: "running" })
    await expect(pending).resolves.toBe(true)

    expect(persistActiveWorkflow).toHaveBeenCalledWith(expect.objectContaining({
      taskId: "task-old",
      projectId: "p-old",
    }))
    expect(autoExtractManager.state.taskId).toBeNull()
    expect(autoExtractManager.state.ownerProjectId).toBeNull()
    expect(autoExtractManager.state.submitting).toBe(false)
  })
})

describe("startEntityFusionSuggestions", () => {
  it("成功：createEntityFusionSuggestions 参数并 adopt", async () => {
    const createEntityFusionSuggestions = vi.fn(async () => ({ task_id: "task-f1" }))
    setBridgeOverrides({
      api: { world: { createEntityFusionSuggestions } },
      state: { currentProjectId: "p-fs" },
      toast: vi.fn(),
    })
    expect(await startEntityFusionSuggestions("location")).toBe(true)
    expect(createEntityFusionSuggestions).toHaveBeenCalledWith({ novel_id: "p-fs", entity_type: "location" })
    expect(fusionManager.state.taskId).toBe("task-f1")
  })

  it("空类型传 undefined", async () => {
    const createEntityFusionSuggestions = vi.fn(async () => ({ task_id: "task-f2" }))
    setBridgeOverrides({
      api: { world: { createEntityFusionSuggestions } },
      state: { currentProjectId: "p-fs2" },
      toast: vi.fn(),
    })
    await startEntityFusionSuggestions("")
    expect(createEntityFusionSuggestions).toHaveBeenCalledWith({ novel_id: "p-fs2", entity_type: undefined })
  })

  it("同步双击只提交一次", async () => {
    let resolveCreate
    const createEntityFusionSuggestions = vi.fn(() => new Promise((resolve) => { resolveCreate = resolve }))
    setBridgeOverrides({
      api: { world: { createEntityFusionSuggestions } },
      state: { currentProjectId: "p-fusion-double" },
      toast: vi.fn(),
    })

    const first = startEntityFusionSuggestions("location")
    const second = startEntityFusionSuggestions("location")
    expect(await second).toBe(false)
    expect(createEntityFusionSuggestions).toHaveBeenCalledTimes(1)
    resolveCreate({ task_id: "task-fusion-double" })
    await expect(first).resolves.toBe(true)
    expect(fusionManager.state.submitting).toBe(false)
  })

  it("响应前切换项目时把融合任务留在原项目", async () => {
    let resolveCreate
    const state = { currentProjectId: "p-fusion-old" }
    setBridgeOverrides({
      api: { world: { createEntityFusionSuggestions: vi.fn(() => new Promise((resolve) => { resolveCreate = resolve })) } },
      state,
      toast: vi.fn(),
    })

    const pending = startEntityFusionSuggestions("location")
    state.currentProjectId = "p-fusion-new"
    recoverActiveWorkflows.mockReturnValue([])
    fusionManager.recover("p-fusion-new")
    resolveCreate({ task_id: "task-fusion-old" })
    await expect(pending).resolves.toBe(true)

    expect(persistActiveWorkflow).toHaveBeenCalledWith(expect.objectContaining({
      taskId: "task-fusion-old",
      projectId: "p-fusion-old",
    }))
    expect(fusionManager.state.taskId).toBeNull()
    expect(fusionManager.state.submitting).toBe(false)
  })
})
