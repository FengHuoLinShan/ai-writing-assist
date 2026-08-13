import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("../../../shared/aiReferenceModal.js", () => ({
  confirmAiReference: vi.fn(),
}))

import { confirmAiReference } from "../../../shared/aiReferenceModal.js"
import { createConflictController } from "../../../vue/views/writing/controllers/conflictController.js"

function makeController(overrides = {}) {
  const project = { value: "p1" }
  const state = {
    check: {
      id: "check-1",
      chapter_index: 3,
      scene_id: "scene-1",
      include_candidates: true,
      items: [{ id: "item-1", status: "open" }],
    },
  }
  const api = {
    writing: {
      updateConflictItem: vi.fn(async (_itemId, _projectId, payload) => ({ id: "item-1", status: payload.status })),
      enqueueConflictAiReview: vi.fn(async (_checkId, payload) => ({ task_id: payload.operation_id, check: { ...state.check, ai_review_status: "running" } })),
      enqueueConflictAiSuggestion: vi.fn(async (_itemId, payload) => ({ task_id: payload.operation_id, status: "pending" })),
      getConflictCheck: vi.fn(async () => ({ ...state.check, ai_review_status: "done" })),
      ...overrides.writing,
    },
    tasks: { get: vi.fn(async (taskId) => ({ id: taskId, status: "done", result: { check_id: "check-1", id: "item-1", suggestion_status: "done", ai_suggestion: { suggested_text: "改写" } } })), ...overrides.tasks },
  }
  const toast = vi.fn()
  const onCheck = vi.fn((check) => { state.check = check })
  const controller = createConflictController({
    api,
    toast,
    getProjectId: () => project.value,
    getCheck: () => state.check,
    onCheck,
  })
  return { controller, api, toast, state, project, onCheck }
}

describe("conflictController", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    sessionStorage.clear()
    confirmAiReference.mockResolvedValue({ id: "confirmation-1" })
  })

  it("does not let another tab's conflict receipt block this tab", async () => {
    localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
      id: "p1:writing_conflict_ai_review:other-tab-task",
      taskId: "other-tab-task",
      workflowType: "writing_conflict_ai_review",
      projectId: "p1",
      view: "writing",
      meta: { checkId: "check-1", kind: "review" },
    }]))
    const { controller, api } = makeController()

    await controller.runAiReview()

    expect(api.writing.enqueueConflictAiReview).toHaveBeenCalledOnce()
    controller.dispose()
  })

  it("状态决策始终携带当前 novel_id 并合并回检查记录", async () => {
    const { controller, api, state } = makeController()
    await controller.updateStatus("item-1", "resolved")
    expect(api.writing.updateConflictItem).toHaveBeenCalledWith("item-1", "p1", { status: "resolved" })
    expect(state.check.items[0].status).toBe("resolved")
    controller.dispose()
  })

  it("AI 判断和建议均经过显式参考资料授权并保持项目边界", async () => {
    const { controller, api, state } = makeController()
    await controller.runAiReview()
    expect(confirmAiReference).toHaveBeenNthCalledWith(1, expect.objectContaining({
      novel_id: "p1",
      action: "writing.conflict_check.ai_review",
      chapter_index: 3,
      scene_id: "scene-1",
      include_pending_objects: true,
    }))
    expect(api.writing.enqueueConflictAiReview).toHaveBeenCalledWith("check-1", {
      novel_id: "p1",
      context_confirmation_id: "confirmation-1",
      operation_id: expect.any(String),
    })

    await controller.requestSuggestion("item-1")
    expect(confirmAiReference).toHaveBeenNthCalledWith(2, expect.objectContaining({
      novel_id: "p1",
      action: "writing.conflict_check.ai_suggestion",
    }))
    expect(api.writing.enqueueConflictAiSuggestion).toHaveBeenCalledWith("item-1", {
      novel_id: "p1",
      context_confirmation_id: "confirmation-1",
      operation_id: expect.any(String),
    })
    expect(state.check.items[0].ai_suggestion).toEqual({ suggested_text: "改写" })
    controller.dispose()
  })

  it("取消 AI 参考资料时安静返回且不提交判断或建议", async () => {
    confirmAiReference.mockRejectedValue(new Error("已取消 AI 参考资料确认"))
    const { controller, api, toast } = makeController()
    await expect(controller.runAiReview()).resolves.toBeNull()
    await expect(controller.requestSuggestion("item-1")).resolves.toBeNull()
    expect(api.writing.enqueueConflictAiReview).not.toHaveBeenCalled()
    expect(api.writing.enqueueConflictAiSuggestion).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
    controller.dispose()
  })

  it("实际后台 AI 判断路径轮询任务并回取完整检查记录", async () => {
    const completed = { id: "check-1", chapter_index: 3, ai_review_status: "partial", items: [{ id: "ai-1", is_ai_judgment: true }] }
    const { controller, api, state, toast } = makeController({
      writing: {
        enqueueConflictAiReview: vi.fn(async () => ({ task_id: "task-1", check: { id: "check-1", chapter_index: 3, ai_review_status: "running", items: [] } })),
        getConflictCheck: vi.fn(async () => completed),
      },
      tasks: { get: vi.fn(async () => ({ status: "done", result: { check_id: "check-1" } })) },
    })
    await controller.runAiReview()
    expect(api.writing.enqueueConflictAiReview).toHaveBeenCalledWith("check-1", {
      novel_id: "p1",
      context_confirmation_id: "confirmation-1",
      operation_id: expect.any(String),
    })
    expect(api.tasks.get).toHaveBeenCalledWith("task-1", "p1")
    expect(api.writing.getConflictCheck).toHaveBeenCalledWith("check-1", "p1")
    expect(state.check).toEqual(completed)
    expect(toast).not.toHaveBeenCalled()
    controller.dispose()
  })

  it("项目切换后丢弃晚到的状态更新", async () => {
    let resolveUpdate
    const { controller, api, state, project, onCheck } = makeController({
      writing: { updateConflictItem: vi.fn(() => new Promise((resolve) => { resolveUpdate = resolve })) },
    })
    const updating = controller.updateStatus("item-1", "ignored")
    project.value = "p2"
    resolveUpdate({ id: "item-1", status: "ignored" })
    await updating
    expect(api.writing.updateConflictItem).toHaveBeenCalledWith("item-1", "p1", { status: "ignored" })
    expect(onCheck).not.toHaveBeenCalled()
    expect(state.check.items[0].status).toBe("open")
    controller.dispose()
  })
})
