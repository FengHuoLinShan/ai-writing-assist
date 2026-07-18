/**
 * useWorkflowPolling 测试 — 轮询启停与 scope 清理。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { effectScope } from "vue"
import { useWorkflowPolling } from "../../../vue/composables/useWorkflowPolling.js"
import { resetBridgeOverrides } from "../../../vue/bridge/index.js"

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("useWorkflowPolling", () => {
  it("轮询到终态自动停止并回调 onDone", async () => {
    const scope = effectScope()
    const polling = scope.run(() => useWorkflowPolling())
    globalThis.api.tasks.get = vi.fn(async () => ({
      task_id: "t1",
      task_type: "rag_rebuild",
      status: "done",
      progress: 100,
    }))
    const onUpdate = vi.fn()
    const onDone = vi.fn()

    polling.start({ taskId: "t1", workflowType: "rag_rebuild", onUpdate, onDone })
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(onUpdate).toHaveBeenCalled()
    expect(onDone.mock.calls[0][0].done).toBe(true)
    scope.stop()
  })

  it("stopAll 停止进行中的轮询（scope 销毁等价于 vanilla onLeave 清理）", async () => {
    const scope = effectScope()
    const polling = scope.run(() => useWorkflowPolling())
    globalThis.api.tasks.get = vi.fn(async () => ({
      task_id: "t1",
      task_type: "rag_rebuild",
      status: "running",
      progress: { percent: 10 },
    }))
    const onUpdate = vi.fn()
    polling.start({ taskId: "t1", workflowType: "rag_rebuild", intervalMs: 30, onUpdate })
    await vi.waitFor(() => expect(onUpdate).toHaveBeenCalled())

    polling.stopAll()
    const callsAtStop = globalThis.api.tasks.get.mock.calls.length
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(globalThis.api.tasks.get.mock.calls.length).toBe(callsAtStop)
    scope.stop()
  })
})
