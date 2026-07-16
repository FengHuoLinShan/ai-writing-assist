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
    expect(manager.runMapNextStep).toBeTypeOf("function")
    expect(manager.completeMapNextStep).toBeTypeOf("function")
    expect(manager.retryMapNextStep).toBeTypeOf("function")
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

  it("resume 的晚到响应不覆盖后续新任务", async () => {
    let resolveResume
    const api = createMockApi()
    api.imports.resumeDeepImport.mockReturnValue(new Promise((resolve) => {
      resolveResume = resolve
    }))
    api.tasks.get.mockResolvedValue({
      task_id: "new-task",
      task_type: "deep_import",
      status: "running",
      result: { phase: "running" },
    })
    const manager = createTestManager({ api })
    manager.startTask({
      taskId: "old-task",
      workflowType: "deep_import",
      stage: "scenes",
      label: "旧任务",
    })
    const resuming = manager.resume()
    manager.startTask({
      taskId: "new-task",
      workflowType: "deep_import",
      stage: "scenes",
      label: "新任务",
    })
    resolveResume({
      task_id: "old-task",
      status: "running",
      result: { phase: "running", message: "旧响应" },
    })

    await resuming

    expect(manager.getState().taskId).toBe("new-task")
    expect(manager.getState().progress.label).toBe("新任务")
    expect(toast).not.toHaveBeenCalledWith("已继续深度导入恢复", "success")
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

  it("离开写作台后不会执行已完成任务的延迟刷新回调", async () => {
    vi.useFakeTimers()
    try {
      const api = createMockApi()
      api.tasks.get.mockResolvedValue({
        task_id: "done-task",
        task_type: "scene_auto_extraction",
        status: "done",
        progress: 1,
        result: { phase: "done" },
      })
      const onDone = vi.fn()
      const manager = createTestManager({ api, onDone })

      manager.startTask({
        taskId: "done-task",
        workflowType: "scene_auto_extraction",
        stage: "scenes",
      })
      await vi.waitFor(() => expect(api.tasks.get).toHaveBeenCalled())
      manager.dispose()
      await vi.advanceTimersByTimeAsync(1500)

      expect(onDone).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it.each([
    {
      name: "已有地图进入地图收件箱",
      context: { existing_maps: [{ id: "map-1" }], locations: [], candidate_locations: [] },
      inbox: { total: 3, items: [] },
      expectedText: "查看地图收件箱（3）",
      callback: "openInbox",
    },
    {
      name: "无地图但有已采用地点进入一键创建",
      context: { existing_maps: [], locations: [{ id: "l1" }], candidate_locations: [] },
      inbox: { total: 0, items: [] },
      expectedText: "一键创建地图（1 个地点）",
      callback: "openQuickCreate",
    },
    {
      name: "只有候选地点进入精确审核",
      context: { existing_maps: [], locations: [], candidate_locations: [{ id: "c1" }, { id: "c2" }] },
      inbox: { total: 0, items: [] },
      expectedText: "先审核 2 个地点",
      callback: "openReviewLocations",
    },
  ])("完成深度导入后$name", async ({ context, inbox, expectedText, callback }) => {
    const api = createMockApi({
      tasks: {
        get: vi.fn().mockResolvedValue({
          task_id: "deep-map-done",
          task_type: "deep_import",
          status: "done",
          result: { phase: "done", workflow_id: "workflow-map-1" },
        }),
        cancel: vi.fn(),
      },
      world: {
        getMapQuickCreateContext: vi.fn().mockResolvedValue(context),
        listProjectMapObservationInbox: vi.fn().mockResolvedValue(inbox),
      },
    })
    persistActiveWorkflow({
      taskId: "deep-map-done",
      workflowType: "deep_import",
      label: "深度导入",
      projectId: "p1",
      view: "writing",
    })
    const callbacks = {
      openQuickCreate: vi.fn(),
      openReviewLocations: vi.fn(),
      openInbox: vi.fn(),
    }
    const manager = createTestManager({ api, mapNextStep: callbacks })

    await manager.recover()

    expect(api.world.getMapQuickCreateContext).toHaveBeenCalledWith("p1", true)
    expect(manager.renderBar()).toContain(expectedText)
    expect(manager.renderBar()).toContain('data-action="deep-import-map-next"')
    await manager.runMapNextStep()
    expect(callbacks[callback]).toHaveBeenCalled()
    if (callback === "openReviewLocations") {
      expect(callbacks.openReviewLocations).toHaveBeenCalledWith(expect.objectContaining({
        workflowId: "workflow-map-1",
      }))
    }
    if (callback === "openQuickCreate") manager.dismiss()
  })

  it("带地图行动的完成态在刷新后仍可恢复", async () => {
    const api = createMockApi({
      tasks: {
        get: vi.fn().mockResolvedValue({
          task_id: "deep-map-persist",
          task_type: "deep_import",
          status: "done",
          result: { phase: "done", workflow_id: "workflow-persist" },
        }),
        cancel: vi.fn(),
      },
      world: {
        getMapQuickCreateContext: vi.fn().mockResolvedValue({
          existing_maps: [{ id: "map-1" }], locations: [], candidate_locations: [],
        }),
        listProjectMapObservationInbox: vi.fn().mockResolvedValue({ total: 2 }),
      },
    })
    persistActiveWorkflow({
      taskId: "deep-map-persist",
      workflowType: "deep_import",
      label: "深度导入",
      projectId: "p1",
      view: "writing",
    })
    const first = createTestManager({ api })
    await first.recover()
    expect(recoverActiveWorkflows("p1")).toHaveLength(1)
    first.dispose()

    const second = createTestManager({ api })
    await second.recover()
    expect(second.renderBar()).toContain("查看地图收件箱（2）")
    second.dispose()
  })

  it("已完成任务忽略残留的恢复标记", async () => {
    const api = createMockApi({
      tasks: {
        get: vi.fn().mockResolvedValue({
          task_id: "deep-stale-recovery",
          task_type: "deep_import",
          status: "done",
          result: {
            phase: "done",
            workflow_id: "workflow-stale",
            recovery_required: true,
            recoverable: true,
          },
        }),
        cancel: vi.fn(),
      },
      world: {
        getMapQuickCreateContext: vi.fn().mockResolvedValue({
          existing_maps: [], locations: [{ id: "loc-1" }], candidate_locations: [],
        }),
      },
    })
    persistActiveWorkflow({
      taskId: "deep-stale-recovery",
      workflowType: "deep_import",
      label: "深度导入",
      projectId: "p1",
      view: "writing",
    })
    const manager = createTestManager({ api })

    await manager.recover()

    expect(manager.renderBar()).toContain("一键创建地图")
    expect(manager.renderRecoveryPrompt()).toBe("")
    manager.dispose()
  })

  it("dispose 和新任务会废弃旧 recover 的晚到响应", async () => {
    let resolveTask
    const taskPromise = new Promise((resolve) => { resolveTask = resolve })
    const api = createMockApi()
    api.tasks.get.mockReturnValue(taskPromise)
    persistActiveWorkflow({
      taskId: "deep-late",
      workflowType: "deep_import",
      label: "深度导入",
      projectId: "p1",
      view: "writing",
    })
    const manager = createTestManager({ api })
    const recovering = manager.recover()
    manager.startTask({
      taskId: "deep-new",
      workflowType: "deep_import",
      stage: "scenes",
      label: "新导入",
    })
    manager.dispose()
    resolveTask({
      task_id: "deep-late",
      task_type: "deep_import",
      status: "done",
      result: { phase: "done" },
    })

    await recovering

    expect(manager.getState().taskId).toBe("deep-new")
  })

  it("候选地点数量使用当前 workflow 的精确筛选", async () => {
    const api = createMockApi({
      tasks: {
        get: vi.fn().mockResolvedValue({
          task_id: "deep-current",
          task_type: "deep_import",
          status: "done",
          result: { phase: "done", workflow_id: "workflow-current" },
        }),
        cancel: vi.fn(),
      },
      world: {
        getMapQuickCreateContext: vi.fn().mockResolvedValue({
          existing_maps: [],
          locations: [],
          candidate_locations: [{ id: "old-1" }, { id: "old-2" }],
        }),
        listEntities: vi.fn().mockResolvedValue({ items: [], total: 0 }),
      },
    })
    persistActiveWorkflow({
      taskId: "deep-current",
      workflowType: "deep_import",
      label: "深度导入",
      projectId: "p1",
      view: "writing",
    })
    const manager = createTestManager({ api })

    await manager.recover()

    expect(api.world.listEntities).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      entity_type: "location",
      source: "deep_import",
      workflow_id: "workflow-current",
    }))
    expect(manager.renderBar()).not.toContain("先审核")
  })

  it("地图下一步加载失败时保留完成态并可重试", async () => {
    const getContext = vi.fn()
      .mockRejectedValueOnce(new Error("上下文暂时不可用"))
      .mockResolvedValueOnce({
        existing_maps: [], locations: [{ id: "loc-1" }], candidate_locations: [],
      })
    const api = createMockApi({
      tasks: {
        get: vi.fn().mockResolvedValue({
          task_id: "deep-retry-map",
          task_type: "deep_import",
          status: "done",
          result: { phase: "done", workflow_id: "workflow-retry" },
        }),
        cancel: vi.fn(),
      },
      world: { getMapQuickCreateContext: getContext },
    })
    persistActiveWorkflow({
      taskId: "deep-retry-map",
      workflowType: "deep_import",
      label: "深度导入",
      projectId: "p1",
      view: "writing",
    })
    const manager = createTestManager({ api })

    await manager.recover()
    expect(manager.renderBar()).toContain("上下文暂时不可用")
    expect(manager.renderBar()).toContain('data-action="retry-deep-import-map-next"')
    expect(recoverActiveWorkflows("p1")).toHaveLength(1)

    await manager.retryMapNextStep()
    expect(manager.renderBar()).toContain("一键创建地图")
    manager.dispose()
  })

  it("目标未打开时不清理完成条", async () => {
    const api = createMockApi({
      tasks: {
        get: vi.fn().mockResolvedValue({
          task_id: "deep-open-failed",
          task_type: "deep_import",
          status: "done",
          result: { phase: "done", workflow_id: "workflow-open-failed" },
        }),
        cancel: vi.fn(),
      },
      world: {
        getMapQuickCreateContext: vi.fn().mockResolvedValue({
          existing_maps: [{ id: "map-1" }], locations: [], candidate_locations: [],
        }),
        listProjectMapObservationInbox: vi.fn().mockResolvedValue({ total: 1 }),
      },
    })
    persistActiveWorkflow({
      taskId: "deep-open-failed",
      workflowType: "deep_import",
      label: "深度导入",
      projectId: "p1",
      view: "writing",
    })
    const manager = createTestManager({
      api,
      mapNextStep: { openInbox: vi.fn().mockResolvedValue(false) },
    })
    await manager.recover()

    expect(await manager.runMapNextStep()).toBe(false)
    expect(manager.renderBar()).toContain("查看地图收件箱")
    expect(recoverActiveWorkflows("p1")).toHaveLength(1)
    manager.dispose()
  })

  it("地图行动晚到回调不清理后续新任务", async () => {
    let resolveOpen
    const api = createMockApi({
      tasks: {
        get: vi.fn().mockResolvedValue({
          task_id: "deep-late-map-action",
          task_type: "deep_import",
          status: "done",
          result: { phase: "done", workflow_id: "workflow-late-map-action" },
        }),
        cancel: vi.fn(),
      },
      world: {
        getMapQuickCreateContext: vi.fn().mockResolvedValue({
          existing_maps: [{ id: "map-1" }], locations: [], candidate_locations: [],
        }),
        listProjectMapObservationInbox: vi.fn().mockResolvedValue({ total: 1 }),
      },
    })
    persistActiveWorkflow({
      taskId: "deep-late-map-action",
      workflowType: "deep_import",
      label: "深度导入",
      projectId: "p1",
      view: "writing",
    })
    const manager = createTestManager({
      api,
      mapNextStep: {
        openInbox: vi.fn().mockReturnValue(new Promise((resolve) => {
          resolveOpen = resolve
        })),
      },
    })
    await manager.recover()
    const opening = manager.runMapNextStep()
    manager.startTask({
      taskId: "new-task-after-map-action",
      workflowType: "deep_import",
      stage: "scenes",
      label: "新任务",
    })
    resolveOpen(true)

    expect(await opening).toBe(false)
    expect(manager.getState().taskId).toBe("new-task-after-map-action")
    manager.dispose()
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

})
