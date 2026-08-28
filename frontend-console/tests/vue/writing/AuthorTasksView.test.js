import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import AuthorTasksView from "../../../vue/views/writing/home/AuthorTasksView.vue"

let api
let router
let toast

function task(overrides = {}) {
  return {
    id: "task-1",
    title: "核对港口规则",
    note: null,
    status: "open",
    due_date: null,
    source: null,
    created_at: "2026-08-27T10:00:00Z",
    updated_at: "2026-08-27T10:00:00Z",
    ...overrides,
  }
}

beforeEach(() => {
  api = {
    projects: {
      listAuthorTasks: vi.fn(async () => ({
        items: [task()], total: 1,
        counts: { today: 0, inbox: 1, later: 0, completed: 0 },
      })),
      createAuthorTask: vi.fn(async (_projectId, payload) => task(payload)),
      patchAuthorTask: vi.fn(async (_projectId, _taskId, payload) => task(payload)),
    },
  }
  router = { navigate: vi.fn(), refresh: vi.fn(), commitCurrentQuery: vi.fn(() => true) }
  toast = vi.fn()
  setBridgeOverrides({ api, router, toast })
})

afterEach(() => resetBridgeOverrides())

describe("作者任务工作台", () => {
  it("固定展示今天、收件箱、之后、已完成，并将归档放在次级入口", async () => {
    const wrapper = mount(AuthorTasksView, { props: { projectId: "p1", scope: "inbox" } })
    await flushPromises()

    const tabs = wrapper.get(".author-task-tabs")
    expect(tabs.text()).toContain("今天")
    expect(tabs.text()).toContain("收件箱")
    expect(tabs.text()).toContain("之后")
    expect(tabs.text()).toContain("已完成")
    expect(tabs.get(".author-task-tabs__archive").text()).toBe("已归档")
    expect(wrapper.text()).toContain("核对港口规则")
  })

  it("从来源打开时预填标题，且只向 API 发送封闭来源", async () => {
    api.projects.listAuthorTasks.mockResolvedValue({ items: [], total: 0, counts: {} })
    const wrapper = mount(AuthorTasksView, {
      props: {
        projectId: "p1",
        scope: "inbox",
        source: { kind: "world_page", id: "page-1", taskTitle: "核对《港口制度》", label: "港口制度" },
      },
    })
    await flushPromises()

    expect(wrapper.get("#author-task-title").element.value).toBe("核对《港口制度》")
    expect(wrapper.get(".author-task-form__heading p").text()).toContain("港口制度")
    await wrapper.get(".author-task-form").trigger("submit")
    await flushPromises()

    expect(api.projects.createAuthorTask).toHaveBeenCalledWith("p1", expect.objectContaining({
      title: "核对《港口制度》",
      source: { kind: "world_page", id: "page-1" },
    }))
    expect(router.commitCurrentQuery).toHaveBeenCalledWith(expect.any(URLSearchParams), "replace")
    expect(router.commitCurrentQuery.mock.calls.at(-1)[0].has("task_source_id")).toBe(false)
    expect(router.navigate).not.toHaveBeenCalled()
  })

  it("冲突后保留输入，并仅在作者再次保存时使用最新版本", async () => {
    const latest = task({ title: "其他位置的标题", updated_at: "2026-08-27T11:00:00Z" })
    api.projects.listAuthorTasks
      .mockResolvedValueOnce({ items: [task()], total: 1, counts: { inbox: 1 } })
      .mockResolvedValue({ items: [latest], total: 1, counts: { inbox: 1 } })
    api.projects.patchAuthorTask
      .mockRejectedValueOnce(Object.assign(new Error("任务已更新"), { status: 409 }))
      .mockResolvedValueOnce(task({ title: "保留的作者输入", updated_at: "2026-08-27T12:00:00Z" }))

    const wrapper = mount(AuthorTasksView, { props: { projectId: "p1", scope: "inbox" } })
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "编辑").trigger("click")
    await wrapper.get("#author-task-title").setValue("保留的作者输入")
    await wrapper.get(".author-task-form").trigger("submit")
    await flushPromises()

    expect(wrapper.get("#author-task-title").element.value).toBe("保留的作者输入")
    expect(wrapper.get(".author-task-conflict").text()).toContain("再次保存")
    expect(api.projects.patchAuthorTask).toHaveBeenCalledTimes(1)

    await wrapper.get(".author-task-form").trigger("submit")
    await flushPromises()

    expect(api.projects.patchAuthorTask).toHaveBeenNthCalledWith(2, "p1", "task-1", expect.objectContaining({
      title: "保留的作者输入",
      expected_updated_at: "2026-08-27T11:00:00Z",
    }))
    expect(wrapper.find(".author-task-form").exists()).toBe(false)
  })

  it("完成、重开、归档与恢复都走带版本的 PATCH", async () => {
    const wrapper = mount(AuthorTasksView, { props: { projectId: "p1", scope: "inbox" } })
    await flushPromises()

    await wrapper.get('.author-task-row input[type="checkbox"]').trigger("change")
    await flushPromises()
    expect(api.projects.patchAuthorTask).toHaveBeenCalledWith("p1", "task-1", {
      status: "completed", expected_updated_at: "2026-08-27T10:00:00Z",
    })

    await wrapper.findAll(".author-task-row__actions button").find((button) => button.text() === "归档").trigger("click")
    await flushPromises()
    expect(api.projects.patchAuthorTask).toHaveBeenCalledWith("p1", "task-1", {
      status: "archived", expected_updated_at: "2026-08-27T10:00:00Z",
    })

    wrapper.unmount()
    api.projects.listAuthorTasks.mockResolvedValue({
      items: [task({ status: "completed" })], total: 1,
      counts: { completed: 1 },
    })
    const completed = mount(AuthorTasksView, { props: { projectId: "p1", scope: "completed" } })
    await flushPromises()
    await completed.get('.author-task-row input[type="checkbox"]').trigger("change")
    await flushPromises()
    expect(api.projects.patchAuthorTask).toHaveBeenCalledWith("p1", "task-1", {
      status: "open", expected_updated_at: "2026-08-27T10:00:00Z",
    })

    completed.unmount()
    api.projects.listAuthorTasks.mockResolvedValue({
      items: [task({ status: "archived" })], total: 1, counts: {},
    })
    const archived = mount(AuthorTasksView, { props: { projectId: "p1", scope: "archived" } })
    await flushPromises()
    await archived.findAll(".author-task-row__actions button").find((button) => button.text() === "恢复").trigger("click")
    await flushPromises()
    expect(api.projects.patchAuthorTask).toHaveBeenCalledWith("p1", "task-1", {
      status: "open", expected_updated_at: "2026-08-27T10:00:00Z",
    })
  })

  it("来源失效时保留任务文字并可单独清除来源", async () => {
    api.projects.listAuthorTasks.mockResolvedValue({
      items: [task({ source: { kind: "world_entity", id: "gone", label: "世界对象已失效", available: false } })],
      total: 1, counts: { inbox: 1 },
    })
    const wrapper = mount(AuthorTasksView, { props: { projectId: "p1", scope: "inbox" } })
    await flushPromises()

    expect(wrapper.text()).toContain("来源已失效")
    expect(wrapper.text()).toContain("核对港口规则")
    await wrapper.findAll("button").find((button) => button.text() === "清除来源").trigger("click")
    await flushPromises()
    expect(api.projects.patchAuthorTask).toHaveBeenCalledWith("p1", "task-1", {
      source: null, expected_updated_at: "2026-08-27T10:00:00Z",
    })
  })
})
