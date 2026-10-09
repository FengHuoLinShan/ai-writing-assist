import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("../../../shared/aiReferenceModal.js", () => ({
  confirmAiReference: vi.fn(),
}))

import { confirmAiReference } from "../../../shared/aiReferenceModal.js"
import { createGuidedFlowController } from "../../../vue/views/writing/controllers/guidedFlowController.js"

function stopView(overrides = {}) {
  return {
    run_id: "run-1",
    flow_id: "continue_writing",
    flow_version: 1,
    title: "继续写下一场",
    status: "waiting_approval",
    chapter_index: 3,
    stop: {
      step_id: "confirm_reference",
      kind: "author_confirm",
      reason: "需要你确认本章资料后才能生成",
      actions: [{ action: "confirm_reference", label: "确认本章资料" }],
    },
    steps: [{ step_id: "confirm_reference", title: "确认本章资料", state: "active", detail: "" }],
    settings: { semantic_review: true },
    ...overrides,
  }
}

function makeController(overrides = {}) {
  const api = {
    assistant: {
      guidedFlow: vi.fn(async (_projectId, runId) => overrides.views?.[runId] || stopView()),
      guidedFlowActive: vi.fn(async () => overrides.active || null),
      guidedFlowAdvance: vi.fn(async (_runId, body) => overrides.advance?.(body) || stopView()),
      guidedFlowSettings: vi.fn(async (_runId, body) => stopView({ settings: { semantic_review: Boolean(body?.semantic_review) } })),
      guidedFlowAbandon: vi.fn(async () => ({ status: "cancelled", stop: null })),
    },
  }
  const toast = vi.fn()
  const controller = createGuidedFlowController({
    api,
    toast,
    getProjectId: () => "p1",
    getSceneId: () => "scene-1",
    onOpenCandidate: overrides.onOpenCandidate,
    confirmDialog: overrides.confirmDialog || vi.fn(async () => true),
  })
  return { controller, api, toast }
}

beforeEach(() => {
  vi.clearAllMocks()
  confirmAiReference.mockResolvedValue({ id: "confirmation-1" })
})

afterEach(() => {
  vi.useRealTimers()
})

describe("guidedFlowController", () => {
  it("attachRun 载入停点视图并显示宿主", async () => {
    const { controller } = makeController()
    await controller.attachRun("run-1")
    expect(controller.state.visible).toBe(true)
    expect(controller.state.view.stop.step_id).toBe("confirm_reference")
    controller.dispose()
  })

  it("probeActive 只在存在活动流程时显示；未开启或无流程保持隐藏", async () => {
    const { controller } = makeController()
    await controller.probeActive()
    expect(controller.state.visible).toBe(false)
    controller.dispose()

    const { controller: withActive } = makeController({ active: stopView() })
    await withActive.probeActive()
    expect(withActive.state.visible).toBe(true)
    expect(withActive.state.view.run_id).toBe("run-1")
    withActive.dispose()
  })

  it("确认停点复用既有资料确认弹窗并携带确认 ID 推进", async () => {
    const { controller, api } = makeController()
    await controller.attachRun("run-1")
    await controller.confirmReference()
    expect(confirmAiReference).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      action: "writing.generate",
      chapter_index: 3,
      scene_id: "scene-1",
    }))
    expect(api.assistant.guidedFlowAdvance).toHaveBeenCalledWith("run-1", {
      novel_id: "p1",
      context_confirmation_id: "confirmation-1",
    })
    controller.dispose()
  })

  it("作者取消确认弹窗时不推进也不报错提示", async () => {
    confirmAiReference.mockRejectedValue(new Error("已取消 AI 参考资料确认"))
    const { controller, toast } = makeController()
    await controller.attachRun("run-1")
    await controller.confirmReference()
    expect(toast).not.toHaveBeenCalled()
    controller.dispose()
  })

  it("轮询只在无停点时自动推进，有停点只刷新", async () => {
    vi.useFakeTimers()
    const running = stopView({ status: "running", stop: null })
    const advance = vi.fn(() => running)
    const { controller, api } = makeController({
      advance,
      views: { "run-1": running },
    })
    await controller.attachRun("run-1")
    await vi.advanceTimersByTimeAsync(4100)
    expect(advance).toHaveBeenCalledTimes(1)

    // 刷新到作者停点后：轮询继续，但不再自动推进。
    api.assistant.guidedFlow.mockResolvedValue(stopView())
    await vi.advanceTimersByTimeAsync(4100)
    expect(advance).toHaveBeenCalledTimes(2)
    advance.mockClear()
    await vi.advanceTimersByTimeAsync(4100)
    expect(advance).not.toHaveBeenCalled()
    expect(api.assistant.guidedFlow).toHaveBeenCalled()
    controller.dispose()
  })

  it("终态停止轮询；结束流程需要确认且保留候选说明", async () => {
    vi.useFakeTimers()
    const { controller, api } = makeController()
    api.assistant.guidedFlow.mockResolvedValue(stopView({ status: "completed", stop: null }))
    await controller.attachRun("run-1")
    await vi.advanceTimersByTimeAsync(10000)
    expect(api.assistant.guidedFlow).toHaveBeenCalledTimes(1)

    api.assistant.guidedFlow.mockResolvedValue(stopView())
    const confirmDialog = vi.fn(async () => true)
    const { controller: cancellable } = makeController({ confirmDialog })
    await cancellable.attachRun("run-1")
    await cancellable.abandonFlow()
    expect(confirmDialog).toHaveBeenCalledTimes(1)
    expect(cancellable.state.view.status).toBe("cancelled")
    cancellable.dispose()
    controller.dispose()
  })

  it("openCandidate 把候选交给写作页既有打开路径", async () => {
    const onOpenCandidate = vi.fn()
    const { controller } = makeController({
      onOpenCandidate,
      active: stopView({
        candidate: { draft_id: "c9", chapter_index: 3, title: "第 3 章" },
      }),
    })
    await controller.probeActive()
    controller.openCandidate()
    expect(onOpenCandidate).toHaveBeenCalledWith(expect.objectContaining({ draft_id: "c9" }))
    controller.dispose()
  })

  it("设置开关在确认停点保存并更新视图", async () => {
    const { controller, api } = makeController()
    await controller.attachRun("run-1")
    await controller.saveSettings(false)
    expect(api.assistant.guidedFlowSettings).toHaveBeenCalledWith("run-1", {
      novel_id: "p1",
      semantic_review: false,
    })
    expect(controller.state.view.settings.semantic_review).toBe(false)
    controller.dispose()
  })
})
