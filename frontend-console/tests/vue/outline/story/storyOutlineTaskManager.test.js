/**
 * storyOutlineTaskManager 测试 — adopt / recover / cancel / dismiss 语义。
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

import {
  clearActiveWorkflow,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../../../../shared/workflowProgress.js"
import { storyOutlineTaskManager } from "../../../../vue/views/outline/story/storyOutlineData.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"

function resetManager() {
  storyOutlineTaskManager.resetMemoryScope()
  storyOutlineTaskManager.setOnTerminal(null)
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetManager()
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("adopt", () => {
  it("写入 reactive state、持久化 localStorage 并开始轮询", () => {
    setBridgeOverrides({ state: { currentProjectId: "p1" } })
    storyOutlineTaskManager.adopt(
      { task_id: "task-a1", status: "running" },
      { action: "outline.story_outline.generate", apply_base_revision_id: "rev-1", apply_idempotency_key: "key-1" },
      "p1",
    )

    expect(storyOutlineTaskManager.state.taskId).toBe("task-a1")
    expect(storyOutlineTaskManager.state.cancelPending).toBe(false)
    expect(storyOutlineTaskManager.state.meta).toEqual({
      action: "outline.story_outline.generate",
      apply_base_revision_id: "rev-1",
      apply_idempotency_key: "key-1",
    })
    expect(persistActiveWorkflow).toHaveBeenCalledWith(expect.objectContaining({
      taskId: "task-a1",
      workflowType: "story_outline_generate",
      label: "AI 小说总纲",
      projectId: "p1",
      view: "outline",
    }))
    expect(pollTaskProgress).toHaveBeenCalledWith(expect.objectContaining({
      taskId: "task-a1",
      workflowType: "story_outline_generate",
    }))
  })

  it("项目已切换时只持久化原项目工作流，不绑定当前 UI 轮询", () => {
    storyOutlineTaskManager.adopt(
      { task_id: "task-detached", status: "running" },
      { action: "outline.story_outline.generate", novel_id: "p-old" },
      "p-old",
      { attach: false },
    )

    expect(persistActiveWorkflow).toHaveBeenCalledWith(expect.objectContaining({
      taskId: "task-detached",
      projectId: "p-old",
    }))
    expect(storyOutlineTaskManager.state.taskId).toBeNull()
    expect(pollTaskProgress).not.toHaveBeenCalled()
  })
})

describe("recover", () => {
  it("无持久化记录时不动作", () => {
    recoverActiveWorkflows.mockReturnValue([])
    storyOutlineTaskManager.recover("p-none")
    expect(storyOutlineTaskManager.state.taskId).toBeNull()
    expect(pollTaskProgress).not.toHaveBeenCalled()
  })

  it("只恢复匹配 workflowType + action 的记录", () => {
    recoverActiveWorkflows.mockReturnValue([
      { taskId: "task-wrong-action", workflowType: "story_outline_generate", meta: { action: "outline.generate" } },
    ])
    storyOutlineTaskManager.recover("p1")
    expect(storyOutlineTaskManager.state.taskId).toBeNull()

    resetManager()
    vi.clearAllMocks()
    recoverActiveWorkflows.mockReturnValue([
      { taskId: "task-ok", workflowType: "story_outline_generate", projectId: "p1", meta: { action: "outline.story_outline.generate", novel_id: "p1" } },
    ])
    storyOutlineTaskManager.recover("p1")
    expect(storyOutlineTaskManager.state.taskId).toBe("task-ok")
  })

  it("多个匹配记录取最新 updatedAt", () => {
    recoverActiveWorkflows.mockReturnValue([
      { taskId: "task-old", workflowType: "story_outline_generate", projectId: "p1", meta: { action: "outline.story_outline.generate", novel_id: "p1" }, updatedAt: "2026-07-01T00:00:00Z" },
      { taskId: "task-new", workflowType: "story_outline_generate", projectId: "p1", meta: { action: "outline.story_outline.generate", novel_id: "p1" }, updatedAt: "2026-07-18T00:00:00Z" },
    ])
    storyOutlineTaskManager.recover("p1")
    expect(storyOutlineTaskManager.state.taskId).toBe("task-new")
  })

  it("未终结任务在轮询中时 recover 不重复启动", () => {
    setBridgeOverrides({ state: { currentProjectId: "p1" } })
    storyOutlineTaskManager.adopt({ task_id: "task-live", status: "running" }, {}, "p1")
    recoverActiveWorkflows.mockReturnValue([
      { taskId: "task-live", workflowType: "story_outline_generate", meta: { action: "outline.story_outline.generate" } },
    ])
    storyOutlineTaskManager.recover("p1")
    expect(pollTaskProgress).toHaveBeenCalledTimes(1)
  })

  it("不恢复缺少当前 project/novel 归属的记录", () => {
    recoverActiveWorkflows.mockReturnValue([
      { taskId: "task-no-project", workflowType: "story_outline_generate", meta: { action: "outline.story_outline.generate", novel_id: "p1" } },
      { taskId: "task-other-novel", workflowType: "story_outline_generate", projectId: "p1", meta: { action: "outline.story_outline.generate", novel_id: "p2" } },
    ])

    storyOutlineTaskManager.recover("p1")

    expect(storyOutlineTaskManager.state.taskId).toBeNull()
    expect(pollTaskProgress).not.toHaveBeenCalled()
  })

  it("切换项目时停止旧内存任务并恢复新项目记录", () => {
    const state = { currentProjectId: "p-old" }
    setBridgeOverrides({ state })
    storyOutlineTaskManager.adopt(
      { task_id: "task-old", status: "running" },
      { action: "outline.story_outline.generate", novel_id: "p-old" },
      "p-old",
    )
    const firstPoller = vi.mocked(pollTaskProgress).mock.results[0].value
    recoverActiveWorkflows.mockReturnValue([
      {
        taskId: "task-new",
        workflowType: "story_outline_generate",
        projectId: "p-new",
        meta: { action: "outline.story_outline.generate", novel_id: "p-new" },
      },
    ])

    state.currentProjectId = "p-new"
    storyOutlineTaskManager.recover("p-new")

    expect(firstPoller.stop).toHaveBeenCalled()
    expect(storyOutlineTaskManager.state.taskId).toBe("task-new")
    expect(pollTaskProgress).toHaveBeenCalledTimes(2)
    expect(clearActiveWorkflow).not.toHaveBeenCalledWith("task-old")
  })
})

describe("cancel", () => {
  it("无 taskId 时直接返回 false", async () => {
    const result = await storyOutlineTaskManager.cancel("p1")
    expect(result).toBe(false)
  })

  it("已取消中时不下发重复取消", async () => {
    storyOutlineTaskManager.state.taskId = "task-cancel"
    storyOutlineTaskManager.state.cancelPending = true
    const result = await storyOutlineTaskManager.cancel("p1")
    expect(result).toBe(false)
  })

  it("成功取消——调用 api.tasks.cancel", async () => {
    const toast = vi.fn()
    setBridgeOverrides({ state: {}, toast })
    storyOutlineTaskManager.adopt({ task_id: "task-cancel-api", status: "running" }, {}, "p1")
    vi.mocked(globalThis.api.tasks.cancel).mockResolvedValue({ task_id: "task-cancel-api", status: "cancelled" })
    vi.mocked(pollTaskProgress).mockReset()

    const result = await storyOutlineTaskManager.cancel("p1")

    expect(result).toBe(true)
    expect(globalThis.api.tasks.cancel).toHaveBeenCalledWith("task-cancel-api", "p1")
  })

  it("取消失败时恢复轮询并 toast", async () => {
    const toast = vi.fn()
    setBridgeOverrides({ state: {}, toast })
    storyOutlineTaskManager.adopt({ task_id: "task-cancel-fail", status: "running" }, {}, "p1")
    vi.mocked(globalThis.api.tasks.cancel).mockRejectedValue(new Error("网络错误"))
    vi.mocked(pollTaskProgress).mockReset()
    // 重置以便第二次 _startPolling 重新 mock
    vi.mocked(pollTaskProgress).mockReturnValue({ stop: vi.fn() })

    const result = await storyOutlineTaskManager.cancel("p1")

    expect(result).toBe(false)
    expect(toast).toHaveBeenCalledWith("网络错误", "error")
    expect(storyOutlineTaskManager.state.cancelPending).toBe(false)
    // 恢复轮询（mockReset 后仅在 catch 内调一次）
    expect(pollTaskProgress).toHaveBeenCalledTimes(1)
  })
})

describe("dismiss", () => {
  it("清空 state 并清除持久化", () => {
    setBridgeOverrides({ state: { currentProjectId: "p1" } })
    storyOutlineTaskManager.adopt({ task_id: "task-dismiss", status: "running" }, {}, "p1")
    expect(storyOutlineTaskManager.state.taskId).toBe("task-dismiss")

    storyOutlineTaskManager.dismiss()

    expect(storyOutlineTaskManager.state.taskId).toBeNull()
    expect(storyOutlineTaskManager.state.meta).toBeNull()
    expect(storyOutlineTaskManager.state.progress).toBeNull()
    expect(storyOutlineTaskManager.state.taskNotice).toBeNull()
    expect(storyOutlineTaskManager.state.cancelPending).toBe(false)
    expect(clearActiveWorkflow).toHaveBeenCalledWith("task-dismiss")
  })

  it("无 task 时直接清空", () => {
    storyOutlineTaskManager.dismiss()
    expect(storyOutlineTaskManager.state.taskId).toBeNull()
  })
})

describe("终态回调", () => {
  it("setOnTerminal 注册的回调在 onDone 时触发", () => {
    const terminalHandler = vi.fn()
    storyOutlineTaskManager.setOnTerminal(terminalHandler)
    setBridgeOverrides({ state: { currentProjectId: "p1" } })
    storyOutlineTaskManager.adopt({ task_id: "task-term", status: "running" }, {}, "p1")

    const callArgs = vi.mocked(pollTaskProgress).mock.calls[0][0]
    const progress = { taskId: "task-term", done: true, terminal: true }
    const task = {
      task_type: "story_outline_generate",
      meta: { action: "outline.story_outline.generate", novel_id: "p1" },
      result: { title: "done" },
    }
    callArgs.onDone(progress, task)

    expect(terminalHandler).toHaveBeenCalledWith("done", progress, task, storyOutlineTaskManager.state)
  })

  it("setOnTerminal 注册的回调在 onFailed 时触发", () => {
    const terminalHandler = vi.fn()
    storyOutlineTaskManager.setOnTerminal(terminalHandler)
    setBridgeOverrides({ state: { currentProjectId: "p1" } })
    storyOutlineTaskManager.adopt({ task_id: "task-fail", status: "running" }, {}, "p1")

    const callArgs = vi.mocked(pollTaskProgress).mock.calls[0][0]
    const progress = { taskId: "task-fail", failed: true, terminal: true, cancelled: false, errorMessage: "error" }
    callArgs.onFailed(progress)

    expect(terminalHandler).toHaveBeenCalledWith("failed", progress, null, storyOutlineTaskManager.state)
  })

  it("setOnTerminal 为 null 时不报错", () => {
    storyOutlineTaskManager.setOnTerminal(null)
    setBridgeOverrides({ state: { currentProjectId: "p1" } })
    storyOutlineTaskManager.adopt({ task_id: "task-no-handler", status: "running" }, {}, "p1")

    const callArgs = vi.mocked(pollTaskProgress).mock.calls[0][0]
    expect(() => callArgs.onDone({ done: true, terminal: true }, {})).not.toThrow()
  })

  it("注销函数不会清除后续注册的终态处理器", () => {
    const first = vi.fn()
    const second = vi.fn()
    const unsubscribeFirst = storyOutlineTaskManager.setOnTerminal(first)
    storyOutlineTaskManager.setOnTerminal(second)
    unsubscribeFirst()
    setBridgeOverrides({ state: { currentProjectId: "p1" } })
    storyOutlineTaskManager.adopt({ task_id: "task-owner", status: "running" }, {}, "p1")
    const callbacks = vi.mocked(pollTaskProgress).mock.calls[0][0]
    const task = {
      task_type: "story_outline_generate",
      meta: { action: "outline.story_outline.generate", novel_id: "p1" },
      result: {},
    }

    callbacks.onDone({ taskId: "task-owner", done: true, terminal: true }, task)

    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledOnce()
  })

  it("拒绝与当前 novel 不匹配的任务结果", () => {
    const terminalHandler = vi.fn()
    storyOutlineTaskManager.setOnTerminal(terminalHandler)
    setBridgeOverrides({ state: { currentProjectId: "p1" } })
    storyOutlineTaskManager.adopt({ task_id: "task-cross", status: "running" }, {}, "p1")
    const callbacks = vi.mocked(pollTaskProgress).mock.calls[0][0]

    callbacks.onDone(
      { taskId: "task-cross", done: true, terminal: true },
      {
        task_type: "story_outline_generate",
        meta: { action: "outline.story_outline.generate", novel_id: "p2" },
        result: {},
      },
    )

    expect(terminalHandler).not.toHaveBeenCalled()
    expect(clearActiveWorkflow).toHaveBeenCalledWith("task-cross")
    expect(storyOutlineTaskManager.state.taskId).toBeNull()
    expect(storyOutlineTaskManager.state.taskNotice).toContain("不匹配")
  })

  it("组件挂载前到达的终态会在注册处理器时重放", () => {
    setBridgeOverrides({ state: { currentProjectId: "p1" } })
    storyOutlineTaskManager.adopt({ task_id: "task-early", status: "running" }, {}, "p1")
    const callbacks = vi.mocked(pollTaskProgress).mock.calls[0][0]
    const task = {
      task_type: "story_outline_generate",
      meta: { action: "outline.story_outline.generate", novel_id: "p1" },
      result: { title: "done" },
    }
    callbacks.onDone({ taskId: "task-early", done: true, terminal: true }, task)
    const terminalHandler = vi.fn()

    storyOutlineTaskManager.setOnTerminal(terminalHandler)

    expect(terminalHandler).toHaveBeenCalledWith(
      "done",
      { taskId: "task-early", done: true, terminal: true },
      task,
      storyOutlineTaskManager.state,
    )
  })

  it("终态已被旧组件处理后，新组件重挂载仍会重放", () => {
    const firstHandler = vi.fn()
    storyOutlineTaskManager.setOnTerminal(firstHandler)
    setBridgeOverrides({ state: { currentProjectId: "p1" } })
    storyOutlineTaskManager.adopt({ task_id: "task-remount", status: "running" }, {}, "p1")
    const callbacks = vi.mocked(pollTaskProgress).mock.calls[0][0]
    const progress = { taskId: "task-remount", done: true, terminal: true }
    const task = {
      task_type: "story_outline_generate",
      meta: { action: "outline.story_outline.generate", novel_id: "p1" },
      result: { title: "done" },
    }
    callbacks.onDone(progress, task)
    const secondHandler = vi.fn()

    storyOutlineTaskManager.setOnTerminal(secondHandler)

    expect(firstHandler).toHaveBeenCalledOnce()
    expect(secondHandler).toHaveBeenCalledWith("done", progress, task, storyOutlineTaskManager.state)
  })
})
