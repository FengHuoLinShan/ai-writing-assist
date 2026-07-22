import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const workflow = vi.hoisted(() => ({
  polls: [],
  clearActiveWorkflow: vi.fn(),
  persistActiveWorkflow: vi.fn(),
  recoverActiveWorkflows: vi.fn(() => []),
  pollTaskProgress: vi.fn((options) => {
    workflow.polls.push(options)
    return { stop: vi.fn() }
  }),
  normalizeTaskProgress: vi.fn((task, workflowType) => ({
    taskId: task.task_id,
    workflowType,
    status: task.status || "running",
    terminal: ["done", "failed", "cancelled"].includes(task.status),
    done: task.status === "done",
    cancelled: task.status === "cancelled",
    meta: task.meta || {},
  })),
}))

vi.mock("../../../shared/workflowProgress.js", () => ({
  clearActiveWorkflow: workflow.clearActiveWorkflow,
  persistActiveWorkflow: workflow.persistActiveWorkflow,
  recoverActiveWorkflows: workflow.recoverActiveWorkflows,
  pollTaskProgress: workflow.pollTaskProgress,
  normalizeTaskProgress: workflow.normalizeTaskProgress,
}))

import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { sceneAutoExtractManager } from "../../../vue/views/scene/sceneAutoExtractManager.js"

describe("scene auto extraction owner gates", () => {
  let api
  let toast

  beforeEach(() => {
    localStorage.clear()
    workflow.polls.length = 0
    vi.clearAllMocks()
    sceneAutoExtractManager.resetMemory()
    api = { tasks: { cancel: vi.fn() } }
    toast = vi.fn()
    setBridgeOverrides({ api, state: { currentProjectId: "p1" }, toast })
  })

  afterEach(() => {
    sceneAutoExtractManager.resetMemory()
    resetBridgeOverrides()
  })

  it("ignores stale poll callbacks after another project adopts a task", async () => {
    sceneAutoExtractManager.adopt({ task_id: "task-1", status: "running" }, { start_chapter: 1 }, "p1")
    const stalePoll = workflow.polls[0]
    sceneAutoExtractManager.adopt({ task_id: "task-2", status: "running" }, { start_chapter: 2 }, "p2")

    stalePoll.onUpdate({ taskId: "task-1", status: "running", percent: 90 })
    await stalePoll.onDone({ taskId: "task-1", done: true, status: "done" })

    expect(sceneAutoExtractManager.state.ownerProjectId).toBe("p2")
    expect(sceneAutoExtractManager.state.taskId).toBe("task-2")
    expect(toast).not.toHaveBeenCalled()
    expect(workflow.clearActiveWorkflow).not.toHaveBeenCalledWith("task-1")
  })

  it("does not let a late cancellation overwrite a newer owned task", async () => {
    let resolveCancel
    api.tasks.cancel.mockImplementation(() => new Promise((resolve) => { resolveCancel = resolve }))
    sceneAutoExtractManager.adopt({ task_id: "task-1", status: "running" }, {}, "p1")

    const cancelling = sceneAutoExtractManager.cancel("p1")
    sceneAutoExtractManager.adopt({ task_id: "task-2", status: "running" }, {}, "p2")
    resolveCancel({ status: "cancelled" })

    await expect(cancelling).resolves.toBe(false)
    expect(sceneAutoExtractManager.state.ownerProjectId).toBe("p2")
    expect(sceneAutoExtractManager.state.taskId).toBe("task-2")
    expect(sceneAutoExtractManager.state.progress.status).toBe("running")
  })

  it("releases the synchronous submission guard when the project changes", () => {
    const oldSubmission = sceneAutoExtractManager.beginSubmission("p1")
    expect(oldSubmission).not.toBeNull()
    expect(sceneAutoExtractManager.state.submitting).toBe(true)

    sceneAutoExtractManager.recover("p2")
    expect(sceneAutoExtractManager.state.submitting).toBe(false)
    expect(sceneAutoExtractManager.state.ownerProjectId).toBe("p2")

    const newSubmission = sceneAutoExtractManager.beginSubmission("p2")
    expect(newSubmission).not.toBeNull()
    sceneAutoExtractManager.endSubmission(oldSubmission)
    expect(sceneAutoExtractManager.state.submitting).toBe(true)
    sceneAutoExtractManager.endSubmission(newSubmission)
    expect(sceneAutoExtractManager.state.submitting).toBe(false)
  })
})
