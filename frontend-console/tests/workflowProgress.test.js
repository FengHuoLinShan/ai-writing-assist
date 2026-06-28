import { describe, it, expect, vi, beforeEach } from "vitest"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
  workflowProgressStorageKey,
} from "../shared/workflowProgress.js"

beforeEach(() => {
  localStorage.clear()
  vi.useRealTimers()
  vi.clearAllMocks()
})

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
})
