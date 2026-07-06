import { describe, it, expect, vi, beforeEach } from "vitest"
import { createDeepImportRecovery } from "../../views/writing/deepImportRecovery.js"
import { persistActiveWorkflow } from "../../shared/workflowProgress.js"
import { resetState, clearDocument } from "../helpers.js"

function createMockApi(overrides = {}) {
  return {
    tasks: {
      get: vi.fn(),
    },
    imports: {
      resumeDeepImport: vi.fn(),
      abandonDeepImport: vi.fn(),
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
    expect(manager.showAuditDetails).toBeTypeOf("function")
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

    expect(api.tasks.get).toHaveBeenCalledWith("d1")
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
})
