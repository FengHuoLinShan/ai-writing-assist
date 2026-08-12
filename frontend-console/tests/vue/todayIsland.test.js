import { mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../vue/bridge/index.js"
import { persistActiveWorkflow, recoverActiveWorkflows } from "../../shared/workflowProgress.js"
import { loadTodayProps } from "../../vue/todayIsland.js"
import TodayView from "../../vue/views/today/TodayView.vue"

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

afterEach(() => resetBridgeOverrides())

describe("todayIsland", () => {
  it("loads the safe project summary and restores at most three workflows", async () => {
    const state = { currentProjectId: "p1", currentProject: { id: "p1", title: "雾港" } }
    const api = {
      projects: { getWorkspaceSummary: vi.fn(async () => ({ project_id: "p1", continuation: null, writing: {}, attention: {} })) },
      tasks: { get: vi.fn(async (taskId) => ({ id: taskId, task_id: taskId, task_type: "deep_import", status: "running", progress: 0.5 })) },
    }
    for (let index = 1; index <= 4; index += 1) {
      persistActiveWorkflow({ taskId: `t${index}`, workflowType: "deep_import", projectId: "p1" })
    }
    setBridgeOverrides({ state, api })

    const props = await loadTodayProps()

    expect(props.summary.project_id).toBe("p1")
    expect(props.workflows).toHaveLength(3)
    expect(props.workflows[0]).not.toHaveProperty("errorMessage", expect.stringContaining("t1"))
    expect(api.tasks.get).toHaveBeenCalledTimes(3)
    expect(api.tasks.get).toHaveBeenCalledWith(expect.any(String), "p1")
  })

  it("keeps an unavailable workflow visible without exposing a technical failure", async () => {
    const state = { currentProjectId: "p1", currentProject: { id: "p1", title: "雾港" } }
    persistActiveWorkflow({ taskId: "private-task-id", workflowType: "writing_generate", projectId: "p1" })
    setBridgeOverrides({
      state,
      api: {
        projects: { getWorkspaceSummary: vi.fn(async () => ({ project_id: "p1" })) },
        tasks: { get: vi.fn(async () => { throw new Error("worker offline") }) },
      },
    })

    const props = await loadTodayProps()

    expect(props.workflows).toEqual([expect.objectContaining({ stateUnknown: true, statusLabel: "状态暂不可用" })])
  })

  it("does not block writing when the summary request fails", async () => {
    setBridgeOverrides({
      state: { currentProjectId: "p1", currentProject: { id: "p1", title: "雾港" } },
      api: {
        projects: { getWorkspaceSummary: vi.fn(async () => { throw new Error("暂时离线") }) },
        tasks: { get: vi.fn() },
      },
    })

    const props = await loadTodayProps()

    expect(props.summary).toBeNull()
    expect(props.loadError).toContain("暂时离线")
  })

  it("uses the single hero action to continue an unfinished import before the first chapter", async () => {
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    setBridgeOverrides({ router })
    const wrapper = mount(TodayView, {
      props: {
        project: { id: "p1", title: "雾港" },
        summary: { continuation: null, writing: { chapter_count: 0, word_count: 0 }, attention: {} },
        workflows: [{ taskId: "hidden-task", workflowType: "deep_import", status: "running" }],
      },
    })

    expect(wrapper.get("#today-resume-title").text()).toBe("继续整理导入内容")
    const primary = wrapper.get(".today-resume__action")
    expect(primary.text()).toBe("继续整理")
    expect(wrapper.findAll(".today-resume .btn-primary")).toHaveLength(1)
    await primary.trigger("click")
    expect(router.navigate).toHaveBeenCalledWith("writing", null)
  })

  it("隐藏首页任务只更新本地卡片，不整页刷新", async () => {
    const router = { navigate: vi.fn(), refresh: vi.fn() }
    persistActiveWorkflow({ taskId: "failed-task", workflowType: "writing_generate", projectId: "p1" })
    setBridgeOverrides({ router })
    const wrapper = mount(TodayView, {
      props: {
        project: { id: "p1", title: "雾港" },
        summary: { continuation: null, writing: {}, attention: {} },
        workflows: [{ taskId: "failed-task", workflowType: "writing_generate", failed: true }],
      },
    })

    await wrapper.get(".today-workflow-card__actions .btn-ghost").trigger("click")

    expect(wrapper.find(".today-workflow-card").exists()).toBe(false)
    expect(recoverActiveWorkflows("p1")).toEqual([])
    expect(router.refresh).not.toHaveBeenCalled()
  })
})
