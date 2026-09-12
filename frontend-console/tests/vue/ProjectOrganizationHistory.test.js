import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import ProjectOrganizationHistory from "../../vue/components/ProjectOrganizationHistory.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../vue/bridge/index.js"

enableAutoUnmount(afterEach)

const cancelled = {
  task_id: "cancelled-task",
  workflow_type: "deep_import",
  status: "cancelled",
  start_chapter: 1,
  end_chapter: 3,
  asset_summary: { scenes: 2, entities: 1 },
  cleanup_eligible: true,
  cleanup_status: "pending",
}

let api
let state

beforeEach(() => {
  state = { currentProjectId: "project-1" }
  let cleaned = false
  api = {
    imports: {
      recentWorkflows: vi.fn(async () => ({
        items: [{ ...cancelled, ...(cleaned ? { cleanup_status: "complete", cleanup_eligible: false } : {}) }],
        total: 1,
      })),
      previewCancelledCleanup: vi.fn(async () => ({
        ...cancelled,
        workflow_id: "workflow-1",
        cleanup_fingerprint: "a".repeat(64),
        message: "可清理",
      })),
      cleanupCancelled: vi.fn(async () => {
        cleaned = true
        return {
          ...cancelled,
          workflow_id: "workflow-1",
          cleanup_status: "complete",
          cleanup_eligible: false,
          cleanup_summary: { deprecated_scenes: 2, hard_deleted_assets: 0 },
          cleanup_fingerprint: "a".repeat(64),
          message: "已处理",
        }
      }),
    },
    world: { listEntities: vi.fn(async () => ({ total: 1 })) },
    outline: {
      listThreads: vi.fn(async () => ({ total: 2 })),
      listArcs: vi.fn(async () => ({ total: 3 })),
    },
  }
  setBridgeOverrides({ api, state, router: { navigate: vi.fn() } })
})

afterEach(() => resetBridgeOverrides())

describe("深度整理回收站", () => {
  it("取消仅停止，作者预览范围并二次确认后才清理", async () => {
    const wrapper = mount(ProjectOrganizationHistory, { props: { projectId: "project-1" } })
    await flushPromises()

    await wrapper.findAll('[role="tab"]').find((tab) => tab.text().includes("回收站")).trigger("click")
    expect(wrapper.text()).toContain("停止只会停止整理")
    expect(api.imports.cleanupCancelled).not.toHaveBeenCalled()

    await wrapper.get('[data-action="preview-import-cleanup"]').trigger("click")
    await flushPromises()
    expect(api.imports.previewCancelledCleanup).toHaveBeenCalledWith("cancelled-task", "project-1")
    expect(wrapper.text()).toContain("不会永久删除")

    await wrapper.get('[data-action="confirm-import-cleanup"]').trigger("click")
    await flushPromises()
    expect(api.imports.cleanupCancelled).toHaveBeenCalledWith("cancelled-task", {
      novel_id: "project-1",
      expected_cleanup_fingerprint: "a".repeat(64),
      confirmed: true,
    })
    expect(wrapper.text()).toContain("已处理，历史记录仍然保留")
  })

  it("切换项目后丢弃旧项目晚到的清理预览", async () => {
    let finishPreview
    api.imports.previewCancelledCleanup.mockImplementation(() => new Promise((resolve) => { finishPreview = resolve }))
    const wrapper = mount(ProjectOrganizationHistory, { props: { projectId: "project-1" } })
    await flushPromises()
    await wrapper.findAll('[role="tab"]').find((tab) => tab.text().includes("回收站")).trigger("click")
    await wrapper.get('[data-action="preview-import-cleanup"]').trigger("click")

    state.currentProjectId = "project-2"
    api.imports.recentWorkflows.mockResolvedValueOnce({ items: [], total: 0 })
    await wrapper.setProps({ projectId: "project-2" })
    finishPreview({ ...cancelled, cleanup_fingerprint: "b".repeat(64) })
    await flushPromises()

    expect(wrapper.find(".organization-cleanup-preview").exists()).toBe(false)
    expect(wrapper.text()).toContain("回收站是空的")
  })
})
