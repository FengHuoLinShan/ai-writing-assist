import { describe, it, expect, vi, beforeEach } from "vitest"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
  sanitizeTaskErrorMessage,
  workflowProgressStorageKey,
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
  it("normalizes real task progress to percentage", () => {
    const progress = normalizeTaskProgress({
      task_id: "t1",
      task_type: "rag_reindex_novel",
      status: "running",
      progress: 0.42,
    })

    expect(progress.label).toBe("重建 RAG 索引")
    expect(progress.percent).toBe(42)
    expect(progress.hasPercent).toBe(true)
    expect(progress.indeterminate).toBe(false)
  })

  it("uses indeterminate state when no real progress exists", () => {
    const progress = normalizeTaskProgress({
      task_id: "t2",
      task_type: "world_entity_extraction",
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

  it("sanitizes raw DBAPI publish failures", () => {
    const raw = "DBAPIError: asyncpg.exceptions.InFailedSQLTransactionError [SQL: UPDATE async_tasks SET progress=$1]"
    const progress = normalizeTaskProgress({
      task_id: "publish-task",
      task_type: "publish_chapter",
      status: "failed",
      error_message: raw,
    })

    expect(progress.errorMessage).toBe("发布失败。草稿已保存，请稍后重试。")
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
      result: {
        current_phase: "phase1a_scene_slicing",
        current_operation: "scene_slicing",
        message: "正在按完整窗口切分 Scene 边界...",
      },
    })

    expect(progress.message).toBe("正在切分 Scene 边界")
    expect(progress.currentPhase).toBe("phase1a_scene_slicing")
    expect(progress.currentOperation).toBe("scene_slicing")
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

  it("migrates legacy task keys", () => {
    localStorage.setItem("novel_deepImportTaskId", "legacy-deep")
    localStorage.setItem("novel_world_extract_task", "legacy-world")

    const recovered = recoverActiveWorkflows("p1")

    expect(recovered.map((item) => item.taskId).sort()).toEqual(["legacy-deep", "legacy-world"])
    expect(localStorage.getItem("novel_deepImportTaskId")).toBe(null)
    expect(localStorage.getItem("novel_world_extract_task")).toBe(null)
    expect(JSON.parse(localStorage.getItem(workflowProgressStorageKey))).toHaveLength(2)
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
})
