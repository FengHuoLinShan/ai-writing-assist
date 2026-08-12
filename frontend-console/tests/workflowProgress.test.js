import { describe, it, expect, vi, beforeEach } from "vitest"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
  sanitizeTaskErrorMessage,
} from "../shared/workflowProgress.js"

beforeEach(() => {
  localStorage.clear()
  vi.useRealTimers()
  vi.clearAllMocks()
})

function mockVisibilityState(initial = "visible") {
  let value = initial
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => value,
  })
  return (next) => {
    value = next
    document.dispatchEvent(new Event("visibilitychange"))
  }
}

describe("normalizeTaskProgress", () => {
  it("将取消态说明为停止后续处理并保留已保存阶段", () => {
    const progress = normalizeTaskProgress({ status: "cancelled", result: { message: "任务已取消" } })

    expect(progress.message).toContain("不会再排下一步")
    expect(progress.message).toContain("可能不会瞬时断开")
  })

  it("normalizes legacy asset-state words from backend progress text", () => {
    const progress = normalizeTaskProgress({
      id: "task-copy",
      task_type: "plot_structure_auto_extraction",
      status: "running",
      result: {
        message: "正在融合 Scene 候选，待确认后进入正史",
        warnings: ["低置信候选需复核"],
        summary: "候选 2，已确认 1",
      },
    })

    expect(progress.message).toBe("正在融合场景待处理，处理后进入已采用")
    expect(progress.warnings).toEqual(["低置信待处理需要人工检查"])
    expect(progress.resultSummary).toBe("待处理 2，已采用 1")
  })

  it("normalizes real task progress to percentage", () => {
    const progress = normalizeTaskProgress({
      task_id: "t1",
      task_type: "rag_reindex_novel",
      status: "running",
      progress: 0.42,
    })

    expect(progress.label).toBe("修复查找资料")
    expect(progress.percent).toBe(42)
    expect(progress.hasPercent).toBe(true)
    expect(progress.indeterminate).toBe(false)
  })

  it("uses indeterminate state when no real progress exists", () => {
    const progress = normalizeTaskProgress({
      task_id: "t2",
      task_type: "world_object_auto_extraction",
      status: "running",
    })

    expect(progress.percent).toBe(null)
    expect(progress.hasPercent).toBe(false)
    expect(progress.indeterminate).toBe(true)
    expect(progress.message).toContain("世界对象")
  })

  it("marks done tasks as 100 percent", () => {
    const progress = normalizeTaskProgress({
      task_id: "t3",
      task_type: "publish_chapter",
      status: "done",
      progress: 0.5,
    })

    expect(progress.percent).toBe(100)
    expect(progress.done).toBe(true)
  })

  it("normalizes smart dedup scan summary", () => {
    const progress = normalizeTaskProgress({
      task_id: "t-dedup",
      task_type: "smart_dedup_scan",
      status: "done",
      result: {
        total_assets_scanned: 20,
        suggestion_count: 6,
        estimated_duplicate_count: 5,
      },
    })

    expect(progress.label).toBe("智能去重扫描")
    expect(progress.message).toBe("任务完成")
    expect(progress.resultSummary).toBe("扫描 20，建议 6，疑似重复 5")
  })

  it("renders map observation enrichment as a candidate-only workflow", () => {
    const progress = normalizeTaskProgress({
      task_id: "map-task",
      task_type: "map_observation_enrichment",
      status: "done",
      result: {
        scene_count: 12,
        candidate_created_count: 18,
        candidate_reused_count: 2,
        uncertain_count: 3,
      },
    })

    expect(progress.label).toBe("补充地图资料")
    expect(progress.resultSummary).toBe("检查 12 个场景，新增待处理 18 条，复用待处理 2 条，待判定 3 条")
  })

  it("collects failure details and warnings", () => {
    const progress = normalizeTaskProgress({
      task_id: "t4",
      task_type: "rag_reindex_novel",
      status: "failed",
      error_message: "boom",
      result: { warnings: ["warn"] },
    })

    expect(progress.failed).toBe(true)
    expect(progress.errorMessage).toBe("boom")
    expect(progress.warnings).toEqual(["warn"])
  })

  it("uses backend lifecycle actions without guessing from heartbeat", () => {
    const progress = normalizeTaskProgress({
      task_id: "stale-import",
      task_type: "deep_import",
      status: "failed",
      heartbeat_at: "2026-07-12T01:00:00Z",
      attempt: 1,
      max_attempts: 1,
      stale: false,
      lifecycle: {
        reason: "heartbeat_timeout",
        recovery_policy: "manual_resume",
        recovery_required: true,
      },
      available_actions: ["resume", "abandon"],
    })

    expect(progress.failed).toBe(true)
    expect(progress.recoveryRequired).toBe(true)
    expect(progress.availableActions).toEqual(["resume", "abandon"])
    expect(progress.attempt).toBe(1)
  })

  it("sanitizes raw DBAPI publish failures", () => {
    const raw = "DBAPIError: asyncpg.exceptions.InFailedSQLTransactionError [SQL: UPDATE async_tasks SET progress=$1]"
    const progress = normalizeTaskProgress({
      task_id: "publish-task",
      task_type: "publish_chapter",
      status: "failed",
      error_message: raw,
    })

    expect(progress.errorMessage).toBe("发布失败。工作稿已保存，请稍后重试。")
    expect(progress.errorMessage).not.toContain("DBAPIError")
    expect(progress.errorMessage).not.toContain("UPDATE async_tasks")
    expect(sanitizeTaskErrorMessage(raw, "publish_chapter")).toBe(progress.errorMessage)
  })

  it("normalizes deep import phase artifacts into warnings", () => {
    const progress = normalizeTaskProgress({
      task_id: "t5",
      task_type: "scene_auto_extraction",
      status: "done",
      result: {
        phase_artifacts: {
          phase1b_fusion: {
            status: "degraded",
            coverage: { missing_chapters: [2, 3] },
            repair: { attempts: 1 },
          },
        },
      },
    })

    expect(progress.phaseArtifacts.phase1b_fusion.status).toBe("degraded")
    expect(progress.warnings).toContain("phase1b_fusion 缺少章节：2, 3")
    expect(progress.warnings).toContain("phase1b_fusion 已尝试修复 1 次")
    expect(progress.warnings).toContain("phase1b_fusion 降级完成")
  })

  it("normalizes service progress diagnostics and gate warnings", () => {
    const progress = normalizeTaskProgress({
      task_id: "t6",
      task_type: "world_object_auto_extraction",
      status: "running",
      result: {
        progress_events: [{ event: "phase_started", phase: "entity_extraction" }],
        acceptance_checks: [
          {
            name: "entity_extraction_missing_scene_prerequisite",
            phase: "entity_extraction",
            ok: false,
            message: "请先执行场景",
          },
        ],
        phase_timeline: [{ phase: "entity_extraction", status: "running" }],
        diagnostic_counts: { entity_count: 0 },
        phase_errors: [{ phase: "entity_extraction", error_kind: "missing_scene_prerequisite" }],
      },
    })

    expect(progress.progressEvents).toHaveLength(1)
    expect(progress.acceptanceChecks).toHaveLength(1)
    expect(progress.phaseTimeline).toHaveLength(1)
    expect(progress.diagnosticCounts.entity_count).toBe(0)
    expect(progress.phaseErrors[0].error_kind).toBe("missing_scene_prerequisite")
    expect(progress.warnings).toContain("entity_extraction 请先执行场景")
  })

  it("uses current phase for running scene extraction message", () => {
    const progress = normalizeTaskProgress({
      task_id: "scene-task",
      task_type: "scene_auto_extraction",
      status: "running",
      progress: 0.295,
      result: {
        current_phase: "phase1a_scene_slicing",
        current_operation: "scene_slicing",
        current_item: { kind: "window", completed: 2, total: 4 },
        phase_timeline: [
          { phase: "phase0_plan", status: "completed" },
          { phase: "phase1a_scene_slicing", status: "running" },
        ],
        message: "正在按完整窗口切分 Scene 边界...",
      },
    })

    expect(progress.message).toBe("阶段 2 · 划分场景边界｜窗口 2/4")
    expect(progress.resultSummary).toBe("已完成 阶段 1")
    expect(progress.percent).toBe(30)
    expect(progress.currentPhase).toBe("phase1a_scene_slicing")
    expect(progress.currentOperation).toBe("scene_slicing")
  })

  it("shows phase 0 as preparation without a numeric percent", () => {
    const progress = normalizeTaskProgress({
      task_id: "scene-task",
      task_type: "scene_auto_extraction",
      status: "running",
      progress: 0,
      result: {
        current_phase: "phase0_plan",
        current_item: { kind: "chapter_range", start_chapter: 1, end_chapter: 60 },
      },
    })

    expect(progress.message).toBe("阶段 1 · 规划场景范围｜正在准备章节窗口")
    expect(progress.percent).toBeNull()
    expect(progress.hasPercent).toBe(false)
    expect(progress.indeterminate).toBe(true)
  })

  it("shows phase 1b scene progress and completed fine phases", () => {
    const progress = normalizeTaskProgress({
      task_id: "scene-task",
      task_type: "scene_auto_extraction",
      status: "running",
      progress: 0.79,
      result: {
        current_phase: "phase1b_enrichment",
        current_item: { kind: "scene_candidate", completed: 41, total: 82 },
        completed_steps: [],
        phase_timeline: [
          { phase: "phase0_plan", status: "completed" },
          { phase: "phase1a_scene_slicing", status: "completed" },
          { phase: "phase1b_enrichment", status: "running" },
        ],
      },
    })

    expect(progress.message).toBe("阶段 3 · 补充场景资料｜场景 41/82")
    expect(progress.resultSummary).toBe("已完成 阶段 1、阶段 2")
    expect(progress.resultSummary).not.toContain("已完成 0 个阶段")
    expect(progress.percent).toBe(79)
  })

  it("does not show stale running message for failed tasks", () => {
    const progress = normalizeTaskProgress({
      task_id: "scene-task",
      task_type: "scene_auto_extraction",
      status: "failed",
      error_message: "ValidationError",
      result: {
        phase: "running",
        message: "正在提交 enriched 正式 Scene...",
      },
    })

    expect(progress.message).toBe("任务失败")
    expect(progress.errorMessage).toBe("ValidationError")
  })
})

describe("active workflow storage", () => {
  it("persists, recovers, and clears active workflows", () => {
    const item = persistActiveWorkflow({
      taskId: "task-1",
      workflowType: "deep_import",
      projectId: "p1",
      view: "writing",
    })

    expect(item.id).toBe("p1:deep_import:task-1")
    expect(recoverActiveWorkflows("p1")).toHaveLength(1)

    clearActiveWorkflow("task-1")
    expect(recoverActiveWorkflows("p1")).toEqual([])
  })

})

describe("pollTaskProgress", () => {
  it("polls until task completion", async () => {
    vi.useFakeTimers()
    mockVisibilityState("visible")
    const onUpdate = vi.fn()
    const onDone = vi.fn()
    const apiClient = {
      tasks: {
        get: vi.fn()
          .mockResolvedValueOnce({ task_id: "t1", task_type: "rag_reindex_novel", status: "running", progress: 0.5 })
          .mockResolvedValueOnce({ task_id: "t1", task_type: "rag_reindex_novel", status: "done", progress: 1 }),
      },
    }

    pollTaskProgress({ taskId: "t1", workflowType: "rag_reindex_novel", intervalMs: 10, apiClient, onUpdate, onDone })
    await vi.runOnlyPendingTimersAsync()
    await vi.runOnlyPendingTimersAsync()

    expect(apiClient.tasks.get).toHaveBeenCalledTimes(2)
    expect(onUpdate).toHaveBeenCalledTimes(2)
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it("passes an explicit novel id to task status queries", async () => {
    const apiClient = {
      tasks: {
        get: vi.fn().mockResolvedValue({ task_id: "t1", status: "done" }),
      },
    }

    pollTaskProgress({
      taskId: "t1",
      novelId: "p1",
      apiClient,
    })
    await Promise.resolve()

    expect(apiClient.tasks.get).toHaveBeenCalledWith("t1", "p1")
  })

  it("skips API calls while the page is hidden", async () => {
    vi.useFakeTimers()
    mockVisibilityState("hidden")
    const apiClient = {
      tasks: {
        get: vi.fn().mockResolvedValue({ task_id: "t1", task_type: "rag_reindex_novel", status: "running" }),
      },
    }

    pollTaskProgress({ taskId: "t1", workflowType: "rag_reindex_novel", intervalMs: 10, apiClient })
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(50)

    expect(apiClient.tasks.get).not.toHaveBeenCalled()
  })

  it("ticks immediately when visibility returns", async () => {
    vi.useFakeTimers()
    const setVisibility = mockVisibilityState("hidden")
    const apiClient = {
      tasks: {
        get: vi.fn().mockResolvedValue({ task_id: "t1", task_type: "rag_reindex_novel", status: "running" }),
      },
    }

    pollTaskProgress({ taskId: "t1", workflowType: "rag_reindex_novel", intervalMs: 1000, apiClient })
    await Promise.resolve()
    expect(apiClient.tasks.get).not.toHaveBeenCalled()

    setVisibility("visible")
    await Promise.resolve()

    expect(apiClient.tasks.get).toHaveBeenCalledTimes(1)
  })

  it("does not respond to visibility changes after stop", async () => {
    vi.useFakeTimers()
    const setVisibility = mockVisibilityState("hidden")
    const apiClient = {
      tasks: {
        get: vi.fn().mockResolvedValue({ task_id: "t1", task_type: "rag_reindex_novel", status: "running" }),
      },
    }

    const poller = pollTaskProgress({ taskId: "t1", workflowType: "rag_reindex_novel", intervalMs: 10, apiClient })
    poller.stop()
    setVisibility("visible")
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(20)

    expect(apiClient.tasks.get).not.toHaveBeenCalled()
  })

  it("can disable visibility pausing for background monitors", async () => {
    vi.useFakeTimers()
    mockVisibilityState("hidden")
    const apiClient = {
      tasks: {
        get: vi.fn().mockResolvedValue({ task_id: "t1", task_type: "rag_reindex_novel", status: "running" }),
      },
    }

    pollTaskProgress({
      taskId: "t1",
      workflowType: "rag_reindex_novel",
      intervalMs: 10,
      apiClient,
      pauseWhenHidden: false,
    })
    await Promise.resolve()

    expect(apiClient.tasks.get).toHaveBeenCalledTimes(1)
  })

  it("reports polling errors as unknown and keeps polling", async () => {
    vi.useFakeTimers()
    mockVisibilityState("visible")
    const onUpdate = vi.fn()
    const onFailed = vi.fn()
    const apiClient = {
      tasks: {
        get: vi.fn()
          .mockRejectedValueOnce(new Error("network down"))
          .mockResolvedValueOnce({ task_id: "t1", status: "done", progress: 1 }),
      },
    }

    pollTaskProgress({
      taskId: "t1",
      intervalMs: 10,
      apiClient,
      onUpdate,
      onFailed,
    })
    await vi.runOnlyPendingTimersAsync()
    await vi.runOnlyPendingTimersAsync()

    expect(onUpdate.mock.calls[0][0].stateUnknown).toBe(true)
    expect(apiClient.tasks.get).toHaveBeenCalledTimes(2)
    expect(onFailed).not.toHaveBeenCalled()
  })
})
