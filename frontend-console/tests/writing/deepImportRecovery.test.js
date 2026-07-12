import { describe, it, expect, vi, beforeEach } from "vitest"
import { createDeepImportRecovery } from "../../views/writing/deepImportRecovery.js"
import {
  persistActiveWorkflow,
  recoverActiveWorkflows,
} from "../../shared/workflowProgress.js"
import { resetState, clearDocument } from "../helpers.js"

function createMockApi(overrides = {}) {
  return {
    tasks: {
      get: vi.fn(),
      cancel: vi.fn(),
    },
    imports: {
      resumeDeepImport: vi.fn(),
      abandonDeepImport: vi.fn(),
    },
    outline: {
      applyChapterScenePreview: vi.fn(),
    },
    clearCache: vi.fn(),
    ...overrides,
  }
}

function createMockModal() {
  return {
    showModalHtml: vi.fn(),
    confirmAction: vi.fn(),
    closeModal: vi.fn(),
  }
}

function createTestManager(overrides = {}) {
  return createDeepImportRecovery({
    state,
    api: createMockApi(),
    modal: createMockModal(),
    toast,
    esc,
    ...overrides,
  })
}

beforeEach(() => {
  resetState({ currentProjectId: "p1" })
  clearDocument()
  localStorage.clear()
  vi.clearAllMocks()
})

describe("createDeepImportRecovery", () => {
  it("returns the public API", () => {
    const manager = createTestManager()
    expect(manager.recover).toBeTypeOf("function")
    expect(manager.renderBar).toBeTypeOf("function")
    expect(manager.updateBar).toBeTypeOf("function")
    expect(manager.renderRecoveryPrompt).toBeTypeOf("function")
    expect(manager.resume).toBeTypeOf("function")
    expect(manager.abandon).toBeTypeOf("function")
    expect(manager.cancel).toBeTypeOf("function")
    expect(manager.showAuditDetails).toBeTypeOf("function")
    expect(manager.showScenePreview).toBeTypeOf("function")
    expect(manager.applyScenePreview).toBeTypeOf("function")
    expect(manager.discardScenePreview).toBeTypeOf("function")
    expect(manager.dismiss).toBeTypeOf("function")
    expect(manager.dispose).toBeTypeOf("function")
  })

  it("returns empty bar when no progress", () => {
    const manager = createTestManager()
    expect(manager.renderBar()).toBe("")
  })

  it("recovers a persisted running deep_import workflow and starts polling", async () => {
    const api = createMockApi()
    api.tasks.get.mockResolvedValue({
      task_id: "d1",
      task_type: "deep_import",
      status: "running",
      result: { phase: "running", current_step: "entity_extraction" },
    })
    persistActiveWorkflow({
      taskId: "d1",
      workflowType: "deep_import",
      label: "深度导入",
      projectId: "p1",
      view: "writing",
    })
    const onStatusChange = vi.fn()
    const manager = createTestManager({ api, onStatusChange })

    await manager.recover()

    expect(api.tasks.get).toHaveBeenCalledWith("d1", "p1")
    const state = manager.getState()
    expect(state.taskId).toBe("d1")
    expect(state.progress.workflowType).toBe("deep_import")
    expect(state.polling).toBe(true)
    expect(onStatusChange).toHaveBeenCalled()
    manager.dispose()
  })

  it("renders recovery prompt when progress requires recovery", async () => {
    const api = createMockApi()
    api.tasks.get.mockResolvedValue({
      task_id: "d2",
      task_type: "deep_import",
      status: "running",
      result: {
        phase: "running",
        recovery_required: true,
        recovery_summary: { current_phase: "scene_segmentation", committed_scenes: 3 },
        asset_summary: { adopted: 3, review: 2, not_adopted: 1 },
      },
    })
    persistActiveWorkflow({
      taskId: "d2",
      workflowType: "deep_import",
      label: "深度导入",
      projectId: "p1",
      view: "writing",
    })
    const onPrompt = vi.fn()
    const manager = createTestManager({ api, onPrompt })

    await manager.recover()

    expect(onPrompt).toHaveBeenCalled()
    const html = manager.renderRecoveryPrompt()
    expect(html).toContain("自动提取需要恢复")
    expect(html).toContain("已写入 Scene")
    expect(html).toContain("继续")
    expect(html).toContain("放弃恢复")
    const bar = manager.renderBar()
    expect(bar).toContain("已采用 3")
    expect(bar).toContain("待处理 2")
    expect(bar).toContain("未采用 1")
    manager.dispose()
  })

  it("dismiss clears progress and workflow", () => {
    const manager = createTestManager()
    manager.startTask({ taskId: "d3", workflowType: "deep_import", stage: "scenes", label: "深度导入" })
    manager.dismiss()

    expect(manager.getState().taskId).toBeNull()
    expect(manager.getState().progress).toBeNull()
    expect(manager.renderBar()).toBe("")
  })

  it("confirms cancellation with the persisted project id and retains the record", async () => {
    const api = createMockApi()
    api.tasks.cancel.mockResolvedValue({
      task_id: "d-cancel",
      status: "cancelled",
      cancelled: true,
    })
    const modal = createMockModal()
    modal.confirmAction.mockImplementation((_message, onConfirm) => onConfirm())
    const manager = createTestManager({ api, modal })
    manager.startTask({
      taskId: "d-cancel",
      workflowType: "deep_import",
      stage: "scenes",
      label: "深度导入",
    })

    expect(manager.renderBar()).toContain('data-action="cancel-deep-import"')
    await manager.cancel()

    expect(modal.confirmAction).toHaveBeenCalledWith(
      expect.stringContaining("确认取消当前任务"),
      expect.any(Function),
      "确认取消",
    )
    expect(api.tasks.cancel).toHaveBeenCalledWith("d-cancel", "p1")
    expect(manager.getState().progress.phase).toBe("cancelled")
    expect(manager.renderBar()).toContain("已取消")
    expect(manager.renderBar()).toContain('data-action="dismiss-deep-import"')
    expect(recoverActiveWorkflows("p1")).toHaveLength(1)
  })

  it("keeps polling and the recovery record when cancellation fails", async () => {
    const api = createMockApi()
    api.tasks.cancel.mockRejectedValue(new Error("取消接口暂时不可用"))
    api.tasks.get.mockResolvedValue({
      task_id: "d-cancel-failed",
      task_type: "deep_import",
      status: "running",
      progress: 0.2,
      result: { phase: "running" },
    })
    const modal = createMockModal()
    modal.confirmAction.mockImplementation((_message, onConfirm) => onConfirm())
    const manager = createTestManager({ api, modal })
    manager.startTask({
      taskId: "d-cancel-failed",
      workflowType: "deep_import",
      stage: "scenes",
      label: "深度导入",
    })

    await manager.cancel()

    expect(manager.getState().polling).toBe(true)
    expect(recoverActiveWorkflows("p1")).toHaveLength(1)
    expect(toast).toHaveBeenCalledWith("取消接口暂时不可用", "error")
    manager.dispose()
  })

  it("resume calls API and restarts polling", async () => {
    const api = createMockApi()
    api.imports.resumeDeepImport.mockResolvedValue({
      task_id: "d4",
      status: "running",
      result: { phase: "running" },
    })
    const manager = createTestManager({ api })
    manager.startTask({ taskId: "d4", workflowType: "deep_import", stage: "scenes", label: "深度导入" })
    manager.dispose()

    await manager.resume()

    expect(api.imports.resumeDeepImport).toHaveBeenCalledWith("d4")
    expect(manager.getState().polling).toBe(true)
    manager.dispose()
  })

  it("abandon confirms and clears state", async () => {
    const api = createMockApi()
    api.imports.abandonDeepImport.mockResolvedValue({
      cleanup_summary: { deprecated_scenes: 2, deprecated_entities: 1 },
    })
    const modal = createMockModal()
    modal.confirmAction.mockImplementation((_msg, onConfirm) => onConfirm())
    const manager = createTestManager({ api, modal })
    manager.startTask({ taskId: "d5", workflowType: "deep_import", stage: "scenes", label: "深度导入" })
    manager.dispose()

    await manager.abandon()

    expect(api.imports.abandonDeepImport).toHaveBeenCalledWith("d5")
    expect(manager.getState().taskId).toBeNull()
    expect(manager.getState().progress).toBeNull()
  })

  it("showAuditDetails renders snapshot health modal", () => {
    const modal = createMockModal()
    const manager = createTestManager({ modal })

    manager.showAuditDetails()

    expect(modal.showModalHtml).toHaveBeenCalled()
    const [, body] = modal.showModalHtml.mock.calls[0]
    expect(body).toContain("暂无快照健康摘要")
  })

  it("startTask sets progress and persists workflow", () => {
    const manager = createTestManager()
    const onStatusChange = vi.fn()
    const m = createTestManager({ onStatusChange })

    m.startTask({
      taskId: "d6",
      workflowType: "scene_auto_extraction",
      stage: "scenes",
      label: "场景自动提取",
      startChapter: 1,
      endChapter: 5,
      highQuality: true,
    })

    const state = m.getState()
    expect(state.taskId).toBe("d6")
    expect(state.progress.workflowType).toBe("scene_auto_extraction")
    expect(state.progress.stage).toBe("scenes")
    expect(state.polling).toBe(true)
    expect(onStatusChange).toHaveBeenCalled()
    m.dispose()
  })

  it("falls back to phase-based percent when task.progress is missing", async () => {
    const api = createMockApi()
    api.tasks.get.mockResolvedValue({
      task_id: "d-fb",
      task_type: "deep_import",
      status: "running",
      result: {
        phase: "running",
        current_phase: "entity_extraction",
        phase2_completed_scenes: 5,
        phase2_total_scenes: 10,
        completed_steps: ["scene_segmentation"],
      },
    })
    persistActiveWorkflow({
      taskId: "d-fb",
      workflowType: "deep_import",
      label: "深度导入",
      projectId: "p1",
      view: "writing",
    })
    const onStatusChange = vi.fn()
    const manager = createTestManager({ api, onStatusChange })

    await manager.recover()
    await new Promise((resolve) => setTimeout(resolve, 0))

    const html = manager.renderBar()
    expect(html).toContain("60%")
    manager.dispose()
  })

  it("shows indeterminate bar during structure_analysis phase", async () => {
    const api = createMockApi()
    api.tasks.get.mockResolvedValue({
      task_id: "d-ind",
      task_type: "deep_import",
      status: "running",
      progress: 0.8,
      result: {
        phase: "running",
        current_phase: "structure_analysis",
        current_step: "structure_analysis",
      },
    })
    persistActiveWorkflow({
      taskId: "d-ind",
      workflowType: "deep_import",
      label: "深度导入",
      projectId: "p1",
      view: "writing",
    })
    const onStatusChange = vi.fn()
    const manager = createTestManager({ api, onStatusChange })

    await manager.recover()
    await new Promise((resolve) => setTimeout(resolve, 0))

    const html = manager.renderBar()
    expect(html).toContain("workflow-progress--indeterminate")
    expect(html).toContain("正在生成剧情结构")
    manager.dispose()
  })

  it("keeps the persisted workflow across transient recovery errors", async () => {
    vi.useFakeTimers()
    const api = createMockApi()
    api.tasks.get
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValue({
        task_id: "d-transient",
        task_type: "scene_auto_extraction",
        status: "running",
        progress: 0.2,
        result: { phase: "running" },
      })
    persistActiveWorkflow({
      taskId: "d-transient",
      workflowType: "scene_auto_extraction",
      projectId: "p1",
      view: "writing",
    })
    const manager = createTestManager({ api })

    await manager.recover()

    expect(recoverActiveWorkflows("p1")).toHaveLength(1)
    expect(manager.getState().progress.message).toContain("正在重试")

    await vi.advanceTimersByTimeAsync(3000)

    expect(api.tasks.get).toHaveBeenLastCalledWith("d-transient", "p1")
    expect(manager.getState().progress.percent).toBe(20)
    manager.dispose()
  })

  it("clears a persisted workflow only after a confirmed 404", async () => {
    const api = createMockApi()
    const notFound = new Error("not found")
    notFound.status = 404
    api.tasks.get.mockRejectedValue(notFound)
    persistActiveWorkflow({
      taskId: "d-missing",
      workflowType: "scene_auto_extraction",
      projectId: "p1",
      view: "writing",
    })
    const manager = createTestManager({ api })

    await manager.recover()

    expect(recoverActiveWorkflows("p1")).toEqual([])
    expect(manager.getState().taskId).toBeNull()
  })

  it("retains a failed workflow until the user dismisses it", async () => {
    const api = createMockApi()
    api.tasks.get.mockResolvedValue({
      task_id: "d-failed",
      task_type: "scene_auto_extraction",
      status: "failed",
      progress: 0.3,
      error_message: "LLM API key is not configured",
      result: { phase: "failed", message: "场景提取失败" },
    })
    persistActiveWorkflow({
      taskId: "d-failed",
      workflowType: "scene_auto_extraction",
      projectId: "p1",
      view: "writing",
    })
    const manager = createTestManager({ api })

    await manager.recover()

    expect(manager.getState().progress.phase).toBe("failed")
    expect(manager.getState().progress.percent).toBe(30)
    expect(recoverActiveWorkflows("p1")).toHaveLength(1)

    manager.dismiss()

    expect(recoverActiveWorkflows("p1")).toEqual([])
  })

  it("recovers a completed Scene preview and applies edited suggestions explicitly", async () => {
    const api = createMockApi()
    api.tasks.get.mockResolvedValue({
      task_id: "scene-preview-task",
      task_type: "outline_chapter_scenes_extract",
      status: "done",
      result: {
        requires_apply: true,
        total_scenes: 1,
        draft_scenes: [{
          title: "旧标题",
          goal: "潜入王宫",
          chapter_ids: ["1"],
          status: "draft",
          display_state: "review",
          structure_meta: { preview_only: true, needs_review: true },
        }],
      },
    })
    api.outline.applyChapterScenePreview.mockResolvedValue({
      status: "applied",
      scene_ids: ["scene-1"],
      total_scenes: 1,
    })
    persistActiveWorkflow({
      taskId: "scene-preview-task",
      workflowType: "outline_chapter_scenes_extract",
      label: "章节/Scene 卡建议",
      projectId: "p1",
      view: "writing",
      meta: { confirmationId: "confirm-1", stage: "chapter_cards" },
    })
    const modal = createMockModal()
    const onDone = vi.fn()
    const manager = createTestManager({ api, modal, onDone })

    await manager.recover()

    expect(manager.getState().taskId).toBe("scene-preview-task")
    expect(manager.getState().polling).toBe(false)
    expect(manager.renderBar()).toContain("查看并采用待处理 Scene 建议（1）")

    manager.showScenePreview()
    const [, body, buttons] = modal.showModalHtml.mock.calls.at(-1)
    expect(body).toContain("只有点击“采用全部到工作 Scene”后才会写入")
    document.body.innerHTML = body
    document.getElementById("scene-preview-0-title").value = "用户修订标题"
    await buttons.find((button) => button.text === "采用全部到工作 Scene").handler()

    expect(api.outline.applyChapterScenePreview).toHaveBeenCalledWith({
      novel_id: "p1",
      context_confirmation_id: "confirm-1",
      source_task_id: "scene-preview-task",
      draft_scenes: [expect.objectContaining({
        title: "用户修订标题",
        goal: "潜入王宫",
        chapter_ids: ["1"],
      })],
      confirmed: true,
    })
    expect(toast).toHaveBeenCalledWith("已采用 1 个工作 Scene", "success")
    expect(onDone).toHaveBeenCalled()
    expect(manager.getState().progress).toBeNull()
  })
})
