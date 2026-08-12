import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { createDeepImportController } from "../../../vue/views/writing/controllers/deepImportController.js"

describe("deepImportController", () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("连续瞬时失败按 3/6/12/24/30 秒退避并封顶", async () => {
    vi.useFakeTimers()
    const api = {
      tasks: { get: vi.fn().mockRejectedValue(new Error("网络暂不可用")) },
      world: {},
      imports: {},
    }
    const controller = createDeepImportController({
      api,
      toast: vi.fn(),
      getProjectId: () => "p1",
      onChange: vi.fn(),
    })

    controller.startTask({ taskId: "task-backoff", workflowType: "deep_import" })
    await vi.advanceTimersByTimeAsync(0)
    expect(api.tasks.get).toHaveBeenCalledTimes(1)

    for (const delay of [3000, 6000, 12000, 24000, 30000, 30000]) {
      const callsBeforeDelay = api.tasks.get.mock.calls.length
      await vi.advanceTimersByTimeAsync(delay - 1)
      expect(api.tasks.get).toHaveBeenCalledTimes(callsBeforeDelay)
      await vi.advanceTimersByTimeAsync(1)
      expect(api.tasks.get).toHaveBeenCalledTimes(callsBeforeDelay + 1)
    }

    controller.dispose()
  })

  it("查询成功后重置连续失败退避", async () => {
    vi.useFakeTimers()
    const api = {
      tasks: {
        get: vi.fn()
          .mockRejectedValueOnce(new Error("第一次失败"))
          .mockResolvedValueOnce({ status: "running", progress: 0.25, result: {} })
          .mockRejectedValueOnce(new Error("成功后再次失败"))
          .mockImplementation(() => new Promise(() => {})),
      },
      world: {},
      imports: {},
    }
    const controller = createDeepImportController({
      api,
      toast: vi.fn(),
      getProjectId: () => "p1",
      onChange: vi.fn(),
    })

    controller.startTask({ taskId: "task-reset", workflowType: "deep_import" })
    await vi.advanceTimersByTimeAsync(0)
    expect(api.tasks.get).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(3000)
    expect(api.tasks.get).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(3000)
    expect(api.tasks.get).toHaveBeenCalledTimes(3)

    await vi.advanceTimersByTimeAsync(2999)
    expect(api.tasks.get).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(1)
    expect(api.tasks.get).toHaveBeenCalledTimes(4)

    controller.dispose()
  })

  it("完成态在再次打开时仍可恢复，直到作者明确关闭", async () => {
    localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
      id: "p1:deep_import:task-done",
      taskId: "task-done",
      workflowType: "deep_import",
      projectId: "p1",
      label: "深度导入",
    }]))
    const task = {
      status: "done",
      progress: 1,
      task_type: "deep_import",
      result: { workflow_id: "wf-done", degraded: true, degraded_reason: "timeout" },
    }
    const api = {
      tasks: { get: vi.fn(async () => task) },
      world: {},
      imports: {},
    }
    const firstChanges = []
    const first = createDeepImportController({
      api,
      toast: vi.fn(),
      getProjectId: () => "p1",
      onChange: (value) => firstChanges.push(value),
    })
    await first.recover()
    expect(firstChanges.at(-1).progress).toEqual(expect.objectContaining({
      status: "done",
      degraded: true,
    }))
    first.dispose()

    const secondChanges = []
    const second = createDeepImportController({
      api,
      toast: vi.fn(),
      getProjectId: () => "p1",
      onChange: (value) => secondChanges.push(value),
    })
    await second.recover()
    expect(api.tasks.get).toHaveBeenLastCalledWith("task-done", "p1")
    expect(secondChanges.at(-1).progress.status).toBe("done")

    second.dismiss()
    expect(JSON.parse(localStorage.getItem("novel_active_workflows_v1"))).toEqual([])
    second.dispose()
  })

  it("作者从终态启动新任务时只替换已确认离开的旧终态记录", async () => {
    const api = {
      tasks: {
        get: vi.fn()
          .mockResolvedValueOnce({ status: "done", progress: 1, task_type: "deep_import", result: {} })
          .mockImplementation(() => new Promise(() => {})),
      },
      world: {},
      imports: {},
    }
    const controller = createDeepImportController({
      api,
      toast: vi.fn(),
      getProjectId: () => "p1",
      onChange: vi.fn(),
    })
    controller.startTask({ taskId: "task-done", workflowType: "deep_import" })
    await vi.waitFor(() => expect(api.tasks.get).toHaveBeenCalledTimes(1))

    controller.startTask({ taskId: "task-new", workflowType: "deep_import" })
    expect(JSON.parse(localStorage.getItem("novel_active_workflows_v1"))).toEqual([
      expect.objectContaining({ taskId: "task-new" }),
    ])
    controller.dispose()
  })

  it("项目切换后丢弃晚到任务结果", async () => {
    let resolveTask
    const project = { value: "p1" }
    const changes = []
    const api = {
      tasks: { get: vi.fn(() => new Promise((resolve) => { resolveTask = resolve })) },
      world: {},
      imports: {},
    }
    const controller = createDeepImportController({
      api,
      toast: vi.fn(),
      getProjectId: () => project.value,
      onChange: (value) => changes.push(value),
    })
    controller.startTask({ taskId: "task-1", workflowType: "deep_import" })
    const before = changes.length
    project.value = "p2"
    resolveTask({ status: "done", progress: 1, task_type: "deep_import", result: {} })
    await Promise.resolve()
    await Promise.resolve()
    expect(changes).toHaveLength(before)
    controller.dispose()
  })

  it("重新打开时恢复最新任务并还原生命周期与详细进度", async () => {
    localStorage.setItem("novel_active_workflows_v1", JSON.stringify([
      {
        id: "p1:deep_import:task-old",
        taskId: "task-old",
        workflowType: "deep_import",
        projectId: "p1",
      },
      {
        id: "p1:scene_auto_extraction:task-current",
        taskId: "task-current",
        workflowType: "scene_auto_extraction",
        projectId: "p1",
      },
    ]))
    const changes = []
    const api = {
      tasks: {
        get: vi.fn(async () => ({
          status: "failed",
          progress: 0.4,
          task_type: "scene_auto_extraction",
          lifecycle: { recovery_required: true },
          available_actions: ["resume", "abandon"],
          result: {
            phase: "failed",
            progress_events: [{ phase: "phase1a", message: "窗口中断" }],
            phase_timeline: [{ phase: "phase1a", status: "failed" }],
          },
        })),
      },
      world: {},
      imports: {},
    }
    const controller = createDeepImportController({
      api,
      toast: vi.fn(),
      getProjectId: () => "p1",
      onChange: (value) => changes.push(value),
    })

    await controller.recover()

    expect(api.tasks.get).toHaveBeenCalledWith("task-current", "p1")
    expect(changes.at(-1).progress).toEqual(expect.objectContaining({
      recoveryRequired: true,
      progressEvents: [{ phase: "phase1a", message: "窗口中断" }],
      phaseTimeline: [{ phase: "phase1a", status: "failed" }],
    }))
    controller.dispose()
  })

  it("保留完整质量与审计 payload", async () => {
    const changes = []
    const result = {
      workflow_id: "wf-2",
      current_phase: "structure_analysis",
      current_round: 2,
      current_window: { start: 3, end: 5 },
      current_operation: "merge",
      current_item: { id: "item-1" },
      quality_status: "partial",
      quality_stats: { schema_422_rate: 0.02 },
      quality_rerun: { rounds: 1 },
      phase_artifacts: { phase1: { count: 2 } },
      acceptance_checks: [{ name: "coverage", passed: true }],
      diagnostic_counts: { warnings: 1 },
      phase2_throttle_reasons: ["budget"],
      snapshot_health_summary: { latest_failure: null },
      asset_summary: { scenes: 2 },
      phase_errors: [{ phase: "phase2" }],
    }
    const api = {
      tasks: { get: vi.fn(async () => ({ status: "done", progress: 1, task_type: "deep_import", result })) },
      world: {},
      imports: {},
    }
    const controller = createDeepImportController({ api, toast: vi.fn(), getProjectId: () => "p1", onChange: (value) => changes.push(value), onDone: vi.fn() })
    controller.startTask({ taskId: "task-2", workflowType: "deep_import" })
    await vi.waitFor(() => expect(changes.at(-1)?.progress?.currentPhase).toBe("structure_analysis"))
    expect(changes.at(-1).progress).toEqual(expect.objectContaining({
      currentPhase: "structure_analysis",
      currentRound: 2,
      qualityStats: { schema_422_rate: 0.02 },
      phaseArtifacts: { phase1: { count: 2 } },
      acceptanceChecks: [{ name: "coverage", passed: true }],
      diagnosticCounts: { warnings: 1 },
      throttleReasons: ["budget"],
    }))
    controller.dispose()
  })

  it("取消、继续与放弃都通过后端任务契约执行", async () => {
    const pending = new Promise(() => {})
    const changes = []
    const api = {
      tasks: { get: vi.fn(() => pending), cancel: vi.fn(async () => ({})) },
      world: {},
      imports: {
        resumeDeepImport: vi.fn(async () => ({ task_id: "task-resumed" })),
        abandonDeepImport: vi.fn(async () => ({})),
      },
    }
    const makeController = () => createDeepImportController({ api, toast: vi.fn(), getProjectId: () => "p1", onChange: (value) => changes.push(value) })

    const cancelled = makeController()
    cancelled.startTask({ taskId: "task-cancel", workflowType: "deep_import" })
    await cancelled.cancel()
    expect(api.tasks.cancel).toHaveBeenCalledWith("task-cancel", "p1")
    expect(changes.at(-1).progress.message).toContain("不会再排下一步")
    cancelled.dispose()

    const resumed = makeController()
    resumed.startTask({ taskId: "task-resume", workflowType: "deep_import" })
    await resumed.resume()
    expect(api.imports.resumeDeepImport).toHaveBeenCalledWith("task-resume")
    resumed.dispose()

    const abandoned = makeController()
    abandoned.startTask({ taskId: "task-abandon", workflowType: "deep_import" })
    await abandoned.abandon()
    expect(api.imports.abandonDeepImport).toHaveBeenCalledWith("task-abandon")
    abandoned.dispose()
  })

  it("放弃旧任务的晚到响应不会清除随后启动的新任务", async () => {
    let resolveAbandon
    const api = {
      tasks: { get: vi.fn(() => new Promise(() => {})) },
      world: {},
      imports: {
        abandonDeepImport: vi.fn(() => new Promise((resolve) => { resolveAbandon = resolve })),
      },
    }
    const changes = []
    const controller = createDeepImportController({
      api,
      toast: vi.fn(),
      getProjectId: () => "p1",
      onChange: (value) => changes.push(value),
    })
    controller.startTask({ taskId: "task-a", workflowType: "deep_import" })
    const abandoning = controller.abandon()
    controller.startTask({ taskId: "task-b", workflowType: "deep_import" })
    resolveAbandon({})

    await expect(abandoning).resolves.toBe(true)
    expect(changes.at(-1)).toEqual(expect.objectContaining({ taskId: "task-b" }))
    expect(JSON.parse(localStorage.getItem("novel_active_workflows_v1"))).toEqual([
      expect.objectContaining({ taskId: "task-b" }),
    ])
    controller.dispose()
  })

  it.each([
    ["cancel", "cancel", "tasks"],
    ["resume", "resumeDeepImport", "imports"],
  ])("%s 的晚到响应不会覆盖随后启动的新任务", async (method, apiMethod, namespace) => {
    let resolveOperation
    const api = {
      tasks: {
        get: vi.fn(() => new Promise(() => {})),
        cancel: vi.fn(() => new Promise((resolve) => { resolveOperation = resolve })),
      },
      world: {},
      imports: {
        resumeDeepImport: vi.fn(() => new Promise((resolve) => { resolveOperation = resolve })),
      },
    }
    const changes = []
    const controller = createDeepImportController({
      api,
      toast: vi.fn(),
      getProjectId: () => "p1",
      onChange: (value) => changes.push(value),
    })
    controller.startTask({ taskId: "task-a", workflowType: "deep_import" })
    const operation = controller[method]()
    expect(api[namespace][apiMethod]).toHaveBeenCalled()
    controller.startTask({ taskId: "task-b", workflowType: "deep_import" })
    resolveOperation(method === "resume" ? { task_id: "task-a" } : {})

    await expect(operation).resolves.toBe(true)
    expect(changes.at(-1)).toEqual(expect.objectContaining({
      taskId: "task-b",
      progress: expect.objectContaining({ status: "running" }),
    }))
    controller.dispose()
  })

  it.each([
    ["cancel", "cancel", "tasks"],
    ["resume", "resumeDeepImport", "imports"],
    ["abandon", "abandonDeepImport", "imports"],
  ])("%s 失败晚到时不向新任务提示或保留旧弹窗", async (method, apiMethod, namespace) => {
    let rejectOperation
    const toast = vi.fn()
    const api = {
      tasks: {
        get: vi.fn(() => new Promise(() => {})),
        cancel: vi.fn(() => new Promise((_resolve, reject) => { rejectOperation = reject })),
      },
      world: {},
      imports: {
        resumeDeepImport: vi.fn(() => new Promise((_resolve, reject) => { rejectOperation = reject })),
        abandonDeepImport: vi.fn(() => new Promise((_resolve, reject) => { rejectOperation = reject })),
      },
    }
    const controller = createDeepImportController({
      api,
      toast,
      getProjectId: () => "p1",
      onChange: vi.fn(),
    })
    controller.startTask({ taskId: "task-a", workflowType: "deep_import" })
    const operation = controller[method]()
    expect(api[namespace][apiMethod]).toHaveBeenCalled()
    controller.startTask({ taskId: "task-b", workflowType: "deep_import" })
    rejectOperation(new Error("旧请求失败"))

    await expect(operation).resolves.toBe(true)
    expect(toast).not.toHaveBeenCalled()
    controller.dispose()
  })

  it.each([
    ["404", Object.assign(new Error("旧任务不存在"), { status: 404 })],
    ["网络失败", new Error("旧任务查询失败")],
  ])("旧轮询的晚到%s不会清除或覆盖新任务", async (_label, failure) => {
    let rejectOldPoll
    const api = {
      tasks: {
        get: vi.fn()
          .mockImplementationOnce(() => new Promise((_resolve, reject) => {
            rejectOldPoll = reject
          }))
          .mockImplementation(() => new Promise(() => {})),
      },
      world: {},
      imports: {},
    }
    const changes = []
    const controller = createDeepImportController({
      api,
      toast: vi.fn(),
      getProjectId: () => "p1",
      onChange: (value) => changes.push(value),
    })
    controller.startTask({ taskId: "task-a", workflowType: "deep_import" })
    controller.startTask({ taskId: "task-b", workflowType: "deep_import" })
    rejectOldPoll(failure)
    await Promise.resolve()
    await Promise.resolve()

    expect(changes.at(-1)).toEqual(expect.objectContaining({
      taskId: "task-b",
      progress: expect.objectContaining({ status: "running" }),
    }))
    expect(JSON.parse(localStorage.getItem("novel_active_workflows_v1"))).toEqual([
      expect.objectContaining({ taskId: "task-a" }),
      expect.objectContaining({ taskId: "task-b" }),
    ])
    controller.dispose()
  })
})
