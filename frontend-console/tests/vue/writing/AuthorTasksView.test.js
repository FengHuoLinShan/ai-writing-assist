import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { ISLAND_LEAVE_GUARD } from "../../../vue/mountIsland.js"
import AuthorTasksView from "../../../vue/views/writing/home/AuthorTasksView.vue"

let api
let router
let toast
let confirm

function deferred() {
  let resolve
  const promise = new Promise((next) => { resolve = next })
  return { promise, resolve }
}

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
  sessionStorage.clear()
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
  confirm = vi.fn(() => true)
  setBridgeOverrides({ api, router, toast, confirm })
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
    expect(sessionStorage.getItem("novel_author_task_form:v1:p1")).toBeNull()
  })

  it("按作品隔离暂存表单，切换范围或刷新后可恢复", async () => {
    api.projects.listAuthorTasks.mockResolvedValue({ items: [], total: 0, counts: {} })
    let guard
    const first = mount(AuthorTasksView, {
      props: { projectId: "p1", scope: "inbox" },
      global: { provide: { [ISLAND_LEAVE_GUARD]: (fn) => { guard = fn } } },
    })
    await flushPromises()
    await first.findAll("button").find((button) => button.text() === "添加第一项").trigger("click")
    await first.get("#author-task-title").setValue("核对潮汐")
    await first.get("#author-task-note").setValue("保留作者备注")
    await first.get("#author-task-date").setValue("2026-09-03")

    expect(guard()).toBe(true)
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("本浏览器会话暂存"))
    await first.findAll(".author-tasks__header button").find((button) => button.text().includes("写作首页")).trigger("click")
    expect(router.navigate.mock.calls.at(-1)[3].toString()).toBe("home=1")
    await first.findAll(".author-task-tabs button").find((button) => button.text().includes("之后")).trigger("click")
    expect(router.navigate.mock.calls.at(-1)[3].get("scope")).toBe("later")
    first.unmount()

    const otherProject = mount(AuthorTasksView, { props: { projectId: "p2", scope: "later" } })
    await flushPromises()
    expect(otherProject.find(".author-task-form").exists()).toBe(false)
    otherProject.unmount()

    const restored = mount(AuthorTasksView, { props: { projectId: "p1", scope: "later" } })
    await flushPromises()
    expect(restored.get("#author-task-title").element.value).toBe("核对潮汐")
    expect(restored.get("#author-task-note").element.value).toBe("保留作者备注")
    expect(restored.get("#author-task-date").element.value).toBe("2026-09-03")
    restored.unmount()
  })

  it("脏表单取消前二次确认，保存成功后清理草稿", async () => {
    api.projects.listAuthorTasks.mockResolvedValue({ items: [], total: 0, counts: {} })
    confirm.mockReturnValueOnce(false).mockReturnValueOnce(true)
    const wrapper = mount(AuthorTasksView, { props: { projectId: "p1", scope: "inbox" } })
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "添加第一项").trigger("click")
    await wrapper.get("#author-task-title").setValue("不能丢的任务")

    await wrapper.findAll(".author-task-form button").find((button) => button.text() === "取消").trigger("click")
    expect(wrapper.find(".author-task-form").exists()).toBe(true)
    await wrapper.findAll(".author-task-form button").find((button) => button.text() === "取消").trigger("click")
    expect(wrapper.find(".author-task-form").exists()).toBe(false)
    expect(sessionStorage.getItem("novel_author_task_form:v1:p1")).toBeNull()

    await wrapper.findAll("button").find((button) => button.text() === "添加第一项").trigger("click")
    await wrapper.get("#author-task-title").setValue("可保存的任务")
    expect(sessionStorage.getItem("novel_author_task_form:v1:p1")).not.toBeNull()
    await wrapper.get(".author-task-form").trigger("submit")
    await flushPromises()
    expect(api.projects.createAuthorTask).toHaveBeenCalledWith("p1", expect.objectContaining({ title: "可保存的任务" }))
    expect(sessionStorage.getItem("novel_author_task_form:v1:p1")).toBeNull()
    wrapper.unmount()
  })

  it("刷新后保留正在编辑的任务身份与作者输入", async () => {
    const first = mount(AuthorTasksView, { props: { projectId: "p1", scope: "inbox" } })
    await flushPromises()
    await first.findAll("button").find((button) => button.text() === "编辑").trigger("click")
    await first.get("#author-task-note").setValue("刷新后继续")
    first.unmount()

    api.projects.listAuthorTasks.mockResolvedValue({ items: [], total: 0, counts: {} })
    const restored = mount(AuthorTasksView, { props: { projectId: "p1", scope: "later" } })
    await flushPromises()
    expect(restored.get("#author-task-form-title").text()).toBe("编辑任务")
    expect(restored.get("#author-task-title").element.value).toBe("核对港口规则")
    expect(restored.get("#author-task-note").element.value).toBe("刷新后继续")
    await restored.get(".author-task-form").trigger("submit")
    await flushPromises()
    expect(api.projects.patchAuthorTask).toHaveBeenCalledWith("p1", "task-1", expect.objectContaining({
      note: "刷新后继续",
      expected_updated_at: "2026-08-27T10:00:00Z",
    }))
    expect(sessionStorage.getItem("novel_author_task_form:v1:p1")).toBeNull()
    restored.unmount()
  })

  it("PATCH 晚到成功不会清掉提交后的新输入", async () => {
    const late = deferred()
    api.projects.patchAuthorTask.mockReturnValue(late.promise)
    const wrapper = mount(AuthorTasksView, { props: { projectId: "p1", scope: "inbox" } })
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "编辑").trigger("click")
    await wrapper.get("#author-task-title").setValue("提交时标题")
    await wrapper.get(".author-task-form").trigger("submit")
    await vi.waitFor(() => expect(api.projects.patchAuthorTask).toHaveBeenCalledTimes(1))
    expect(wrapper.get("#author-task-title").attributes("disabled")).toBeDefined()

    wrapper.get("#author-task-title").element.disabled = false
    await wrapper.get("#author-task-title").setValue("提交后的新输入")
    late.resolve(task({ title: "提交时标题" }))
    await flushPromises()

    expect(wrapper.get("#author-task-title").element.value).toBe("提交后的新输入")
    expect(sessionStorage.getItem("novel_author_task_form:v1:p1")).toContain("提交后的新输入")
    wrapper.unmount()
  })

  it("PATCH 晚到成功不会关闭后来打开的其他任务", async () => {
    const late = deferred()
    api.projects.listAuthorTasks.mockResolvedValue({
      items: [task(), task({ id: "task-2", title: "第二个任务", updated_at: "2026-08-27T12:00:00Z" })],
      total: 2,
      counts: { inbox: 2 },
    })
    api.projects.patchAuthorTask.mockReturnValue(late.promise)
    const wrapper = mount(AuthorTasksView, { props: { projectId: "p1", scope: "inbox" } })
    await flushPromises()
    const editButtons = () => wrapper.findAll(".author-task-row__actions button").filter((button) => button.text() === "编辑")
    await editButtons()[0].trigger("click")
    await wrapper.get("#author-task-note").setValue("第一个修改")
    await wrapper.get(".author-task-form").trigger("submit")
    await vi.waitFor(() => expect(api.projects.patchAuthorTask).toHaveBeenCalledTimes(1))
    await editButtons()[1].trigger("click")
    expect(wrapper.get("#author-task-title").element.value).toBe("第二个任务")

    late.resolve(task({ note: "第一个修改" }))
    await flushPromises()
    expect(wrapper.get("#author-task-title").element.value).toBe("第二个任务")
    expect(wrapper.find(".author-task-form").exists()).toBe(true)
    wrapper.unmount()
  })

  it("create 晚到成功不会清掉卸载后重新打开的草稿", async () => {
    const late = deferred()
    api.projects.listAuthorTasks.mockResolvedValue({ items: [], total: 0, counts: {} })
    api.projects.createAuthorTask.mockReturnValue(late.promise)
    const first = mount(AuthorTasksView, { props: { projectId: "p1", scope: "inbox" } })
    await flushPromises()
    await first.findAll("button").find((button) => button.text() === "添加第一项").trigger("click")
    await first.get("#author-task-title").setValue("提交中的任务")
    await first.get(".author-task-form").trigger("submit")
    await vi.waitFor(() => expect(api.projects.createAuthorTask).toHaveBeenCalledTimes(1))
    first.unmount()

    const restored = mount(AuthorTasksView, { props: { projectId: "p1", scope: "later" } })
    await flushPromises()
    await restored.get("#author-task-note").setValue("重新打开后的输入")
    late.resolve(task({ title: "提交中的任务" }))
    await flushPromises()

    expect(restored.get("#author-task-note").element.value).toBe("重新打开后的输入")
    expect(sessionStorage.getItem("novel_author_task_form:v1:p1")).toContain("重新打开后的输入")
    restored.unmount()
  })

  it("冲突后保留输入，并仅在作者再次保存时使用最新版本", async () => {
    const latest = task({ title: "其他位置的标题", updated_at: "2026-08-27T11:00:00Z" })
    api.projects.listAuthorTasks.mockImplementation(async (_projectId, _query, options) => ({
      items: [options?.cache === "no-store" ? latest : task()],
      total: 1,
      counts: { inbox: 1 },
    }))
    api.projects.patchAuthorTask
      .mockRejectedValueOnce(Object.assign(new Error("任务已更新"), { status: 409 }))
      .mockResolvedValueOnce(task({ title: "保留的作者输入", updated_at: "2026-08-27T12:00:00Z" }))

    const wrapper = mount(AuthorTasksView, { props: { projectId: "p1", scope: "inbox" } })
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "编辑").trigger("click")
    await wrapper.get("#author-task-title").setValue("保留的作者输入")
    await wrapper.get("#author-task-note").setValue("保留的备注")
    await wrapper.get("#author-task-date").setValue("2026-09-01")
    await wrapper.get(".author-task-form").trigger("submit")
    await flushPromises()

    expect(wrapper.get("#author-task-title").element.value).toBe("保留的作者输入")
    expect(wrapper.get("#author-task-note").element.value).toBe("保留的备注")
    expect(wrapper.get("#author-task-date").element.value).toBe("2026-09-01")
    expect(wrapper.get(".author-task-conflict").text()).toContain("再次保存")
    expect(api.projects.patchAuthorTask).toHaveBeenCalledTimes(1)
    expect(api.projects.listAuthorTasks).toHaveBeenLastCalledWith(
      "p1",
      expect.objectContaining({ scope: "inbox" }),
      { cache: "no-store" },
    )

    await wrapper.get(".author-task-form").trigger("submit")
    await flushPromises()

    expect(api.projects.patchAuthorTask).toHaveBeenNthCalledWith(2, "p1", "task-1", expect.objectContaining({
      title: "保留的作者输入",
      note: "保留的备注",
      due_date: "2026-09-01",
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
