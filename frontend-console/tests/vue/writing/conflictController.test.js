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
      runConflictAiReview: vi.fn(async () => ({ ...state.check, ai_review_status: "done" })),
      requestConflictAiSuggestion: vi.fn(async () => ({ id: "item-1", suggestion_status: "done", ai_suggestion: { suggested_text: "改写" } })),
      getConflictCheck: vi.fn(),
      ...overrides.writing,
    },
    tasks: { get: vi.fn(), ...overrides.tasks },
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
    confirmAiReference.mockResolvedValue({ id: "confirmation-1" })
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
    expect(api.writing.runConflictAiReview).toHaveBeenCalledWith("check-1", {
      novel_id: "p1",
      context_confirmation_id: "confirmation-1",
    })

    await controller.requestSuggestion("item-1")
    expect(confirmAiReference).toHaveBeenNthCalledWith(2, expect.objectContaining({
      novel_id: "p1",
      action: "writing.conflict_check.ai_suggestion",
    }))
    expect(api.writing.requestConflictAiSuggestion).toHaveBeenCalledWith("item-1", {
      novel_id: "p1",
      context_confirmation_id: "confirmation-1",
    })
    expect(state.check.items[0].ai_suggestion).toEqual({ suggested_text: "改写" })
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
    })
    expect(api.tasks.get).toHaveBeenCalledWith("task-1", "p1")
    expect(api.writing.getConflictCheck).toHaveBeenCalledWith("check-1", "p1")
    expect(state.check).toEqual(completed)
    expect(toast).toHaveBeenLastCalledWith("AI 软冲突判断部分生成", "warning")
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
