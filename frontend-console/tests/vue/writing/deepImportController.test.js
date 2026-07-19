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

  it("完成深度导入后生成可达的地图下一步", async () => {
    const changes = []
    const api = {
      tasks: { get: vi.fn(async () => ({ status: "done", progress: 1, task_type: "deep_import", result: { workflow_id: "wf-1" } })) },
      world: {
        getMapQuickCreateContext: vi.fn(async () => ({ existing_maps: [], locations: [{ id: "l1" }], candidate_locations: [] })),
        listProjectMapObservationInbox: vi.fn(),
      },
      imports: {},
    }
    const controller = createDeepImportController({
      api,
      toast: vi.fn(),
      getProjectId: () => "p1",
      onChange: (value) => changes.push(value),
      onDone: vi.fn(),
    })
    controller.startTask({ taskId: "task-1", workflowType: "deep_import", label: "深度导入" })
    await vi.waitFor(() => expect(changes.at(-1)?.progress?.mapNextStep?.action).toBe("quick-create"))
    expect(changes.at(-1).progress.mapNextStep.count).toBe(1)
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

  it("保留完整质量与审计 payload，并可重试地图下一步", async () => {
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
      world: {
        getMapQuickCreateContext: vi.fn()
          .mockRejectedValueOnce(new Error("下一步失败"))
          .mockResolvedValueOnce({ existing_maps: [], locations: [{ id: "l1" }], candidate_locations: [] }),
        listProjectMapObservationInbox: vi.fn(),
      },
      imports: {},
    }
    const controller = createDeepImportController({ api, toast: vi.fn(), getProjectId: () => "p1", onChange: (value) => changes.push(value), onDone: vi.fn() })
    controller.startTask({ taskId: "task-2", workflowType: "deep_import" })
    await vi.waitFor(() => expect(changes.at(-1)?.progress?.mapNextStepError).toBe("下一步失败"))
    expect(changes.at(-1).progress).toEqual(expect.objectContaining({
      currentPhase: "structure_analysis",
      currentRound: 2,
      qualityStats: { schema_422_rate: 0.02 },
      phaseArtifacts: { phase1: { count: 2 } },
      acceptanceChecks: [{ name: "coverage", passed: true }],
      diagnosticCounts: { warnings: 1 },
      throttleReasons: ["budget"],
    }))
    await controller.retryMapNextStep()
    expect(changes.at(-1).progress.mapNextStep.action).toBe("quick-create")
    controller.dispose()
  })

  it("取消、继续与放弃都通过后端任务契约执行", async () => {
    const pending = new Promise(() => {})
    const api = {
      tasks: { get: vi.fn(() => pending), cancel: vi.fn(async () => ({})) },
      world: {},
      imports: {
        resumeDeepImport: vi.fn(async () => ({ task_id: "task-resumed" })),
        abandonDeepImport: vi.fn(async () => ({})),
      },
    }
    const makeController = () => createDeepImportController({ api, toast: vi.fn(), getProjectId: () => "p1", onChange: vi.fn() })

    const cancelled = makeController()
    cancelled.startTask({ taskId: "task-cancel", workflowType: "deep_import" })
    await cancelled.cancel()
    expect(api.tasks.cancel).toHaveBeenCalledWith("task-cancel", "p1")
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
})
